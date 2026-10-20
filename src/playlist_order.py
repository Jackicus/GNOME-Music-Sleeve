# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A playlist's songs put in a new order: shown at once, written to Apple one write at a
time, put back if Apple refuses.

    order = PlaylistOrder(app, refresh)    # the window's (ItemActions.playlist_order)
    order.can_reorder(item)                # a playlist of the user's with its tracks in hand
    order.move(item, 3, 1)                 # its 4th song 2nd: Move Up / Move Down, written a
                                           # MOVE_DELAY after the last of a burst
    order.move(item, 3, 1, at_once=True)   # a drop: written now
    order.undo(playlist_id)                # the order before the last write, written back
    await order.flush(playlist_id)         # what is pending written now, before another write
    await order.flush_all(quitting=True)   # the same for every playlist, as the app quits
    await sync_tracks(app, playlist_id)    # library.json given the playlist's tracks
    await refresh_playlist(app, playlist_id)   # the Item merged with Apple's tracks now

A move goes into the library at once (Library.reorder(): the page's rows move, the order is
held through reloads until Apple's listing shows it). Each playlist has at most one write
under way (Engine.reorder_playlist(): the order as positions in `base`, the track ids Apple
had when it was chosen, so a change made elsewhere meanwhile is refused as 'conflict' rather
than written over); moves made meanwhile go in the next. Move Up and Move Down wait
MOVE_DELAY after the last press, so a burst of them is one write; a drop is written at once.
Any other write to the playlist (an add, a removal, a rename) flushes the pending order
first: a removal's index is the order shown.

A write Apple took is toasted ("Moved “Song”", or "Changed the order of “Playlist”" when it
moved several) with Undo, which puts back the order before it as one more write. Once Apple's
tracks read shows the new order (SETTLE_DELAYS), a playlists pass of the sync reads the
playlist's tracks into library.json (sync_tracks()), so the order is there at the next
launch. A refusal puts the order Apple has back on the page, and is reported (app.report);
for 'conflict' the playlist is read again first.

The demo library has no engine: a move is shown, nothing is written, and the order lasts
until the next launch. A queue already playing from the playlist keeps its order; the next
play of it follows the new one (Player and Up Next are not touched).

GLib only besides the app's own modules: tests run it with a stand-in app and engine.
"""

import asyncio
import logging
from gettext import gettext as _

from gi.repository import GLib

from .backend.errors import EngineError
from .library import Item, moved, order_for

log = logging.getLogger(__name__)

# How long Move Up and Move Down wait after the last press before the order is written, in
# seconds: a burst of presses is one write.
MOVE_DELAY = 1.0

# After a write, how long to wait before each look at Apple's tracks, in seconds, until they
# show the new order (a playlist's lastModifiedDate moved within 5 s of an edit, 2026-10-02).
SETTLE_DELAYS = (0.5, 1, 1, 1, 2, 2, 3, 3)

# How long the quit waits for the orders pending to be written, in seconds.
QUIT_WAIT = 3.0


def positions(shown, wanted):
    """The order (positions in the list of ids `shown`) that makes it the list of ids
    `wanted`, a song there twice taking its places in turn; None when the two are not the
    same tracks."""
    return order_for([{'id': track_id} for track_id in shown], wanted)


async def refresh_playlist(app, playlist_id):
    """Bring a library playlist up to date after it changed on Apple's side (a song added,
    Favourite Songs loved into): the engine's full Item merged into the library's (its
    tracks in an order held ahead of Apple's listing, when they are the same tracks:
    Library.with_held_order()), whose groups-changed re-shows an open page. A failure is
    only logged: the next sync brings the change anyway."""
    playlist = app.library.by_id('playlist', playlist_id)
    if playlist is None:
        return
    try:
        answer = await app.engine.item('playlist', playlist_id)
    except EngineError as error:
        log.debug('playlist %s not refreshed: %s', playlist_id, error)
        return
    if isinstance(answer, dict):
        playlist.merge(app.library.with_held_order(answer))


async def sync_tracks(app, playlist_id):
    """A playlists pass of the sync that reads this playlist's tracks too, so library.json
    has them as Apple does now (after an add, a removal or a new order); after the sync
    running, if one is. True once one ran."""
    for _attempt in range(2):
        task = app.start_sync(playlists=True, tracks_of=(playlist_id,))
        if task is not None:
            await asyncio.wait([task])
            return True
        running = getattr(getattr(app, 'library_sync', None), 'task', None)
        if running is None:
            return False
        await asyncio.wait([running])
    return False


class _Pending:
    """A playlist's order not yet all written: `base`, the track ids Apple has as far as
    the app knows (what the next write is made against); the debounce's timer; the write
    under way; the ids of the tracks moved since the last write (its toast); `undoing`,
    the order being put back by Undo."""

    __slots__ = ('base', 'timer', 'writing', 'moved', 'undoing')

    def __init__(self, base):
        self.base = list(base)
        self.timer = None
        self.writing = None
        self.moved = []
        self.undoing = False


class PlaylistOrder:
    """The order of the user's playlists, as they move their songs. `app` gives the library,
    the engine, the player (ensure_engine()), spawn(), toast(), report(), start_sync(),
    library_sync and demo; `refresh(playlist_id)` (a coroutine) reads a playlist again, by
    default refresh_playlist(). See the module."""

    def __init__(self, app, refresh=None, delay=MOVE_DELAY, settle=SETTLE_DELAYS):
        self.app = app
        self.delay = delay
        self.settle = settle
        self._refresh = refresh or (lambda playlist_id: refresh_playlist(app, playlist_id))
        self._pending = {}  # playlist id -> _Pending
        self._undo = {}  # playlist id -> the track ids before its last write
        self._settling = set()  # the _settle() tasks under way

    @staticmethod
    def can_reorder(item):
        """Whether item's songs can be put in a new order: a playlist of the user's
        (Item.editable: not Favourite Songs, nor one of Apple's) with its one list of
        tracks in hand, two at least."""
        if not isinstance(item, Item) or item.kind != 'playlist' or not item.editable:
            return False
        ids = item.track_ids()
        return ids is not None and len(ids) > 1

    def pending(self, playlist_id):
        """Whether the playlist has an order not yet written (or being written)."""
        return playlist_id in self._pending

    def move(self, item, from_index, to_index, at_once=False):
        """Move the playlist's song at from_index to to_index: shown at once, written
        MOVE_DELAY after the last move of a burst, or at once (`at_once`: a drop). False,
        and nothing moved, where the playlist cannot be reordered or an index is out of
        range or the same."""
        if not self.can_reorder(item):
            return False
        ids = item.track_ids()
        count = len(ids)
        if not (0 <= from_index < count and 0 <= to_index < count) or from_index == to_index:
            return False
        if not self.app.library.reorder(item, moved(count, from_index, to_index)):
            return False
        if self.app.demo:
            return True  # shown, never written: the demo has no engine
        state = self._pending.get(item.id)
        if state is None:
            state = self._pending[item.id] = _Pending(ids)
        state.moved.append(ids[from_index])
        self._schedule(item.id, 0 if at_once else self.delay)
        return True

    def undo(self, playlist_id):
        """Put the playlist's songs back in the order before its last write: shown at once,
        written at once. False when there is nothing to put back."""
        before = self._undo.pop(playlist_id, None)
        item = self.app.library.by_id('playlist', playlist_id)
        if before is None or not self.can_reorder(item):
            return False
        current = item.track_ids()
        order = positions(current, before)
        if order is None or not self.app.library.reorder(item, order):
            return False
        state = self._pending.get(playlist_id)
        if state is None:
            state = self._pending[playlist_id] = _Pending(current)
        state.undoing = True
        self._schedule(playlist_id, 0)
        return True

    async def flush(self, playlist_id):
        """Write the playlist's pending order now, and wait for it (and a write under
        way) to end; nothing for a playlist with none."""
        while True:
            state = self._pending.get(playlist_id)
            if state is None:
                return
            self._cancel_timer(state)
            if state.writing is None or state.writing.done():
                state.writing = self.app.spawn(self._write(playlist_id))
            await asyncio.wait([state.writing])
            if self._pending.get(playlist_id) is state:
                return

    async def flush_all(self, quitting=False):
        """flush() every playlist. `quitting`: only with the engine up (nothing is
        started as the app quits); what cannot be written then is only logged."""
        ids = list(self._pending)
        if quitting and self.app.engine.state != 'up':
            if ids:
                log.warning('the order of %d playlists was not written: the engine is down',
                            len(ids))
            for playlist_id in ids:
                self._cancel_timer(self._pending.pop(playlist_id))
            return
        await asyncio.gather(*(self.flush(playlist_id) for playlist_id in ids))

    def forget(self):
        """Sign-out (ItemActions.forget_account()): the orders pending are dropped unwritten
        (their writes under way cancelled), and nothing is left to undo or to read back,
        so nothing of the account's playlists reaches the next account."""
        for state in self._pending.values():
            self._cancel_timer(state)
            if state.writing is not None and not state.writing.done():
                state.writing.cancel()
        for task in self._settling:
            task.cancel()
        self._pending.clear()
        self._undo.clear()
        self._settling.clear()

    def _cancel_timer(self, state):
        if state.timer is not None:
            state.timer.cancel()
            state.timer = None

    def _schedule(self, playlist_id, delay):
        """Write the playlist's order after `delay` seconds (again from now, a burst's
        timer restarted), or at once; a write under way takes it when it ends."""
        state = self._pending[playlist_id]
        self._cancel_timer(state)
        if state.writing is not None and not state.writing.done():
            return
        if delay <= 0:
            state.writing = self.app.spawn(self._write(playlist_id))
        else:
            state.timer = asyncio.get_running_loop().call_later(delay, self._on_timer,
                                                                playlist_id)

    def _on_timer(self, playlist_id):
        state = self._pending.get(playlist_id)
        if state is None:
            return
        state.timer = None
        if state.writing is None or state.writing.done():
            state.writing = self.app.spawn(self._write(playlist_id))

    async def _write(self, playlist_id):
        """Write the order shown until Apple has it, one write at a time: True once it does,
        False after a refusal (the order Apple has is put back, the error reported)."""
        state = self._pending.get(playlist_id)
        written = False
        while state is not None:
            item = self.app.library.by_id('playlist', playlist_id)
            current = item.track_ids() if isinstance(item, Item) else None
            order = positions(state.base, current) if current is not None else None
            if order is None or order == list(range(len(order))):
                break  # nothing to write: put back by hand, or the playlist changed or went
            track_ids, state.moved = state.moved, []
            undoing, state.undoing = state.undoing, False
            try:
                await self.app.player.ensure_engine()
                await self.app.engine.reorder_playlist(playlist_id, state.base, order)
            except EngineError as error:
                await self._put_back(item, state, error)
                return False
            before, state.base = state.base, current
            written = True
            self._toast(item, track_ids, before, undoing)
        if state is not None and self._pending.get(playlist_id) is state and state.timer is None:
            del self._pending[playlist_id]
        if written:
            task = self.app.spawn(self._settle(playlist_id, state.base))
            self._settling.add(task)
            task.add_done_callback(self._settling.discard)
        return True

    async def _put_back(self, item, state, error):
        """After a refused write: the order Apple has (`base`) back on the page, nothing
        pending, the error reported; for 'conflict' (Apple's list is not `base` any more)
        the playlist read again, Apple's order no longer held over it."""
        self._cancel_timer(state)
        if self._pending.get(item.id) is state:
            del self._pending[item.id]
        self._undo.pop(item.id, None)
        current = item.track_ids()
        order = positions(current, state.base) if current is not None else None
        if order is not None:
            self.app.library.reorder(item, order)
        if error.code == 'conflict':
            self.app.library.release_order(item.id)
            await self._refresh(item.id)
        self.app.report(error)

    def _toast(self, item, track_ids, before, undoing):
        """The toast for a write Apple took: the song moved, or the playlist when several
        were, with Undo (the order `before` it); a write that put an order back has none."""
        if undoing:
            self._undo.pop(item.id, None)
            self.app.toast(_('Put back the order of “{playlist}”').format(playlist=item.title))
            return
        self._undo[item.id] = before
        titles = {track.id: track.title for track in _tracks(item) if track.id in track_ids}
        if len(set(track_ids)) == 1 and titles.get(track_ids[0]):
            message = _('Moved “{title}”').format(title=titles[track_ids[0]])
        else:
            message = _('Changed the order of “{playlist}”').format(playlist=item.title)
        self.app.toast(message, _('Undo'), 'win.item-undo-reorder', GLib.Variant('s', item.id))

    async def _settle(self, playlist_id, ids):
        """Once Apple's tracks read shows the order written (`ids`), a sync pass reads them
        into library.json; nothing while another write of the playlist is to come (its own
        settling does it), or when Apple never shows it (the order stays held a while)."""
        for delay in self.settle:
            await asyncio.sleep(delay)
            if playlist_id in self._pending:
                return
            try:
                listed = await self.app.engine.playlist_track_ids(playlist_id)
            except EngineError as error:
                log.debug('playlist %s not read back: %s', playlist_id, error)
                return
            if listed == ids:
                await sync_tracks(self.app, playlist_id)
                return
        log.info('Apple does not show the new order yet: the next sync brings it')


def _tracks(item):
    entries = item.groups[0].entries if item.groups else None
    if entries is None:
        return []
    return [entries.get_item(position) for position in range(entries.get_n_items())]
