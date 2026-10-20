# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Player: what is playing, as GObject properties fed by the engine's MusicKit events, and
the playback commands as thin coroutines over the engine.

    player = Player(app)                       # made once, in Application.do_startup
    player.state       # a MusicKit.PlaybackStates name: 'none', 'loading', 'playing', 'paused',
                       # 'stopped', 'ended', 'seeking', 'waiting', 'stalled', 'completed'
    player.resting     # the state with 'seeking' seen through (the one before the seek),
                       # and, while a play request is pending, the stops of the queue swap
    player.active, player.stopped              # playback under way (the bar shows Pause);
                                               # nothing playing or paused (no item, or ended)
    player.track       # a NowPlaying (id, catalog_id, title, artist, album, duration_ms,
                       # artwork_url, index, explicit, kind, live), or None
    player.live        # the item is a live radio station: no length, no seek, no pause
    player.can_seek, player.can_pause           # what MusicKit allows with the item now
    player.can_go_next, player.can_go_previous  # (mk.capabilities; all False while live)
    player.position, player.duration           # seconds, floats
    player.shuffle (bool), player.repeat ('none', 'one', 'all'), player.volume (0 to 1)
    player.position_updated_at                 # time.monotonic() when position last changed
    player.estimated_position()                # position, plus the time since (a second at
                                               # most) while playing: between the events
    player.queue, player.queue_index           # a Gio.ListStore of NowPlaying (the queue's
                                               # entries, in order) and where the item playing
                                               # is in it (-1: nowhere, or nothing playing)
    player.queue_editable                      # MusicKit allows edits of the queue (not a
                                               # station's)
    player.autoplay, player.can_autoplay       # MusicKit's autoplay on, and allowed now
    player.lyrics, player.lyrics_loading       # a lyrics.Lyrics for the track (None: none, or
                                               # not there yet), and whether one is being read
    player.pending                             # a play request is with the engine (the play
                                               # buttons show a spinner; `resting` holds)
    player.preview     # the catalog id of the song whose preview plays, or '' (none)
    await player.play({'kind': 'album', 'id': …}, start_with=2, shuffle=False)  # or True,
                                               # or None: the mode as it is
    await player.queue_jump(3)  # play the queue's entry at index 3
    await player.remove_from_queue(4, 'i.abc')   # an entry after the one playing, by index
                                                 # and id (Up Next's Remove)
    await player.clear_up_next()   # everything after the entry playing; undo_clear() puts
    await player.undo_clear()      # it back while that entry still plays
    await player.apply_autoplay()  # the `autoplay` setting to MusicKit (at every engine start)
    await player.toggle()       # pause while active (playing, loading…), else play; a live
                                # station stops instead
    await player.pause() / resume() / next() / stop()
    await player.previous()     # the item before, or this one again when a few seconds in
    await player.seek(seconds); await player.set_volume(level)
    await player.set_shuffle(True); set_repeat('all')   # next_repeat(): the cycle's next
    await player.play_next(kind, id) / play_later(kind, id)
    await player.start_preview(song_id, url)    # Apple's 30-second clip of a song (a suggested
    await player.stop_preview()                 # one's), outside the queue; MusicKit pauses
    await player.ensure_engine()  # start a down engine when signed in (the item actions)
    player.restore(session)     # the last session (session.read()) shown paused, MusicKit
                                # not asked yet: player.restored is True until the first Play
    await player.restore_session()   # hand it to MusicKit and play it (toggle and resume do)
    player.forget_session()     # sign-out, Clear Cache: the session restored goes

The properties change only from the engine's events (playbackStateDidChange,
nowPlayingItemDidChange, playbackTimeDidChange, playbackDurationDidChange,
shuffleModeDidChange, repeatModeDidChange, playbackVolumeDidChange, queueItemsDidChange,
queuePositionDidChange, autoplayEnabledDidChange, capabilitiesChanged), plus one now_playing()
(and queue()) read when the engine comes up,
so the bar follows what MusicKit does rather than what was asked; nothing here polls. A
null item clears the track only after TRACK_GRACE_MS without a new one (`track_grace_ms`;
MusicKit sends a null between queues, right before the next item), and the previous item's
position, which MusicKit reports once more after a track change, is dropped here
(TRACK_HOLD), so every view sees the same cleaned position. The queue is read again
(queue()) when an item arrives that the queue held does not hold at its index; the lyrics
are asked of the engine (lyrics(), cached on disk) once per catalog song as it starts,
never on a timer. A state or track event that arrives while a read is on its way is newer
than the read's answer, which then sets only the modes and the volume. When the engine
goes down everything resets to nothing playing, at once; so it does when the page loads a
new document (the engine's `bridgeReset` event), and now_playing() is read again for what
the new one holds.
A preview (Apple's clip of a suggested song, engine.preview()) is not the queue: MusicKit
pauses for it, and the state, the track and the times stay MusicKit's, so the bar, the sheet
and MPRIS show the queue paused, which it is. Only `preview` says a clip plays, from the
engine's previewDidChange events; it is '' again as the clip ends or stops (MusicKit playing
again stops it), and when the engine goes down or the page is reloaded.
A queue snapshot (queueItemsDidChange, queue()) is applied as the fewest changes to the store
that make it the snapshot (apply_queue: the entries before and after the change kept as they
are, renumbered), so a list over it keeps its rows. Up Next's edits (remove_from_queue,
clear_up_next, undo_clear) change the store at once and then ask the engine; the
queueItemsDidChange that follows is then the store as it is, and changes nothing. One that
fails reads the queue again (a queue changed meanwhile, 'queue-changed', only that). Each
names its entry by index and id, after the entry playing, and only while MusicKit allows edits
(queue_editable, from the snapshot's `editable`: not on a station). While a session is
restored they change it locally (it is then its songs' queue, no longer its source's).
Autoplay is the app's `autoplay` setting, set on MusicKit (apply_autoplay) as the engine comes
up, after a bridgeReset (the page set its own as it loaded) and when the setting changes;
`autoplay` is what MusicKit has, from the snapshots and autoplayEnabledDidChange, and an entry
autoplay added has NowPlaying.autoplay.
The last session (src/session.py keeps it) is restored as the Player's own state: restore()
shows its item paused, its queue and its position, and `restored` holds while MusicKit has
not been asked for it, so MusicKit holding nothing (its empty answer as the engine comes up,
a null item, its states and times, the engine going down) changes nothing meanwhile.
Seek, next, previous, stop, shuffle, repeat (and the volume, with the engine down) change
it locally, paused; Play (toggle, resume) and an Up Next row (queue_jump) hand it to MusicKit
through a play request (restore_session: the album or playlist it came from when the queue is
still that, else its songs' ids; shuffle off, the repeat mode, the position as start_time),
and play_next/play_later queue it paused first. A request that fails gives the session back,
unless MusicKit refused the queue (EngineError('api') with its code): then it is dropped,
`session-dropped` is emitted (the file goes) and `error` says why. MusicKit playing anything
of its own ends it too. `source` is what a queue came from ({kind, id}: an album, a playlist,
a station) while the queue is still that, in order; None otherwise.
A live radio station (the Track's `isLive`: MusicKit plays it as one item, and the duration
it reports is only the stream's window) cannot be sought, paused or skipped (every
mk.capabilities flag false; MusicKit ignores the seek and the pause): `live` is True, the
can_* properties False, seek(), next() and previous() do nothing, and toggle() and pause()
stop it, as the bar's Stop does. MusicKit then holds nothing, so the station is kept as a
session restored (its item alone, stopped, its station the source): Play plays it again.
The can_* properties follow the capabilities the state and item events carry otherwise
(true when MusicKit says nothing, and while a session is restored, whose commands are the
Player's own); Previous also restarts an item that can be sought.
The commands raise EngineError as the engine does; play() starts a down engine first when the
account is signed in (a toast says so) and raises EngineError('not-signed-in') when it is not,
which the window turns into the sign-in flow. `error(message)` is emitted for MusicKit's
mediaPlaybackError, with the sentence playback_error_text() gives its code (the app toasts
it as it is; the code and MusicKit's text go to the log). GObject only, no GTK: tests feed
it synthetic events.
"""

import asyncio
import logging
import time
from gettext import gettext as _

from gi.repository import Gio, GLib, GObject

from .backend.errors import EngineError
from .lyrics import Lyrics

log = logging.getLogger(__name__)

# How long a null item (nowPlayingItemDidChange with no track) waits before the track is
# cleared: MusicKit sends one between queues, half a second before the next item, and the
# bar, the actions, the heart, the lyrics and the Shell's media controls would all flash
# "Not Playing" in between.
TRACK_GRACE_MS = 800

# After a track change, MusicKit reports the previous item's position (and duration) once
# more with the state transitions of the skip, before the new item's 0. For TRACK_HOLD
# seconds after a new item, a position further than SEEK_JUMP seconds past where the item
# can be is that stale report, and is dropped (with its duration), so the bar, the sheet,
# the lyrics and MPRIS never show it. SEEK_JUMP is also how far a position may land from
# where the last one led before MPRIS calls it a seek.
TRACK_HOLD = 2.0
SEEK_JUMP = 2.0

# Seconds into an item after which Previous restarts it rather than going to the item
# before, as players do (GNOME Music, Apple's own).
PREVIOUS_RESTART = 3.0

PLAYBACK_STATES = ('none', 'loading', 'playing', 'paused', 'stopped', 'ended', 'seeking',
                   'waiting', 'stalled', 'completed')

# The states in which playback is under way (the bar shows Pause): what MusicKit is doing on
# the way to, or in, playing. 'seeking' is a transient of whichever state came before it
# (MusicKit passes through it on every seek and every new queue): `resting` sees through it.
ACTIVE_STATES = ('playing', 'loading', 'waiting', 'stalled')

# The states in which nothing plays or waits to resume: the item finished, the queue ended,
# playback was stopped, or there never was any. Paused is not among them.
STOPPED_STATES = ('none', 'stopped', 'ended', 'completed')

REPEAT_MODES = ('none', 'one', 'all')

# The events the Player takes its state from (MusicKit's, and the engine's own bridgeReset:
# the page loaded a new document, and whatever played is gone with the old one).
EVENTS = ('playbackStateDidChange', 'nowPlayingItemDidChange', 'playbackTimeDidChange',
          'playbackDurationDidChange', 'shuffleModeDidChange', 'repeatModeDidChange',
          'playbackVolumeDidChange', 'mediaPlaybackError', 'queueItemsDidChange',
          'queuePositionDidChange', 'previewDidChange', 'autoplayEnabledDidChange',
          'capabilitiesChanged', 'bridgeReset')

# What a state, item or capabilitiesChanged event's (and a now_playing() answer's)
# `capabilities` says MusicKit allows (the bridge's playbackCapabilities). They are taken
# from an item event with an item, a state event in CAPABLE_STATES (an item loaded), and
# capabilitiesChanged: never from the moments between items, when MusicKit holds none.
CAPABILITIES = ('canSeek', 'canPause', 'canSkipToNextItem', 'canSkipToPreviousItem')
CAPABLE_STATES = ('playing', 'paused', 'waiting', 'stalled')


def _text(value):
    return value if isinstance(value, str) else '' if value is None else str(value)


def _number(value, default=0.0):
    """A float from JSON, None and anything odd (NaN, a bool) being `default`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if value == value else default


def _duration_of(data):
    """An event's duration, or None when it carries none (the one held is kept)."""
    return _number(data['duration']) if 'duration' in data else None


# The types a Track's `type` names, by what they are to the ratings: the API's resource
# types, and MusicKit's own singular names for an item it made itself (seen live: an album
# queued from the catalog plays items typed 'song', not 'songs').
SONG_TYPES = ('songs', 'library-songs', 'song')
VIDEO_TYPES = ('music-videos', 'library-music-videos', 'musicVideo', 'music-video')


def _kind_of(data):
    if 'type' not in data:
        return 'song'
    resource = data.get('type')
    if resource in SONG_TYPES:
        return 'song'
    if resource in VIDEO_TYPES:
        return 'video'
    return ''


# What a queue may be restored from as itself rather than as its songs' ids: setQueue fetches
# an album or a playlist whole, and a station plays live.
SOURCE_KINDS = ('album', 'playlist', 'station')

# A restored position this close to the item's end starts it again from the top: it ended.
END_SLACK = 2.0


def _holds_item(name, data):
    """Whether an event says MusicKit holds an item or a queue of its own."""
    if name == 'nowPlayingItemDidChange':
        return isinstance(data.get('track'), dict)
    if name == 'queueItemsDidChange':
        return bool(data.get('items'))
    return False


def _entry_key(data):
    """A queue entry's data as compared with a snapshot's: all of it but its index."""
    return {key: value for key, value in data.items() if key != 'index'}


class NowPlaying(GObject.Object):
    """The item playing: the bridge's Track shape (formatTrack in bridge.js), as properties.

    `artwork_url` is the artwork URL the bridge gives (256 px; remote.fetch_remote re-sizes
    it), None without artwork. `duration_ms` is Apple's for the item; the Player's `duration`
    is what MusicKit reports while playing, which is what the seek bar follows. `kind` is
    what the item is to the account's ratings: 'song' or 'video' (from the Track's `type`,
    the API's resource type or MusicKit's own name for it; a Track without one is a song),
    else '' (a station's segment, an ad: nothing to love). `autoplay`: an entry autoplay added
    to the queue (the Track's `autoplay`). `live`: a live radio station (the Track's
    `isLive`), whose duration is no length. `key` is its data but the index, which apply_queue
    compares.
    """

    __gtype_name__ = 'AppleMusicNowPlaying'

    id = GObject.Property(type=str, default='')
    catalog_id = GObject.Property(type=str, default='')
    title = GObject.Property(type=str, default='')
    artist = GObject.Property(type=str, default='')
    album = GObject.Property(type=str, default='')
    duration_ms = GObject.Property(type=int, default=0)
    artwork_url = GObject.Property(type=str, default=None)
    index = GObject.Property(type=int, default=0)
    explicit = GObject.Property(type=bool, default=False)
    kind = GObject.Property(type=str, default='')
    autoplay = GObject.Property(type=bool, default=False)
    live = GObject.Property(type=bool, default=False)

    def __init__(self, data):
        data = data if isinstance(data, dict) else {}
        super().__init__(
            id=_text(data.get('id')),
            catalog_id=_text(data.get('catalogId')),
            title=_text(data.get('title')),
            artist=_text(data.get('artist')),
            album=_text(data.get('album')),
            duration_ms=int(_number(data.get('durationMs'))),
            artwork_url=data.get('artUrl') if isinstance(data.get('artUrl'), str) else None,
            index=int(_number(data.get('index'))),
            explicit=bool(data.get('explicit')),
            kind=_kind_of(data),
            autoplay=data.get('autoplay') is True,
            live=data.get('isLive') is True,
        )
        self.raw = data
        self.key = _entry_key(data)

    def same_as(self, other):
        """Whether `other` is this item at the same queue position: the same song at
        another queue entry (queued twice, or Play Next of the song playing) is another
        item; repeat one replays this one, at the same index."""
        return (other is not None and other.id == self.id and other.index == self.index)


class Player(GObject.Object):
    """The playback state and commands. See the module."""

    __gtype_name__ = 'AppleMusicPlayer'

    __gsignals__ = {
        'error': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # MusicKit refused the session restored: whatever keeps it forgets it.
        'session-dropped': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    state = GObject.Property(type=str, default='none')
    track = GObject.Property(type=NowPlaying, default=None)
    position = GObject.Property(type=float, default=0.0)
    duration = GObject.Property(type=float, default=0.0)
    shuffle = GObject.Property(type=bool, default=False)
    repeat = GObject.Property(type=str, default='none')
    volume = GObject.Property(type=float, default=1.0)
    queue_index = GObject.Property(type=int, default=-1)
    lyrics = GObject.Property(type=Lyrics, default=None)
    lyrics_loading = GObject.Property(type=bool, default=False)
    pending = GObject.Property(type=bool, default=False)
    preview = GObject.Property(type=str, default='')
    restored = GObject.Property(type=bool, default=False)
    queue_editable = GObject.Property(type=bool, default=True)
    autoplay = GObject.Property(type=bool, default=False)
    can_autoplay = GObject.Property(type=bool, default=True)
    can_seek = GObject.Property(type=bool, default=True)
    can_pause = GObject.Property(type=bool, default=True)
    can_go_next = GObject.Property(type=bool, default=True)
    can_go_previous = GObject.Property(type=bool, default=True)

    def __init__(self, app):
        """`app` gives the engine (`app.engine`), the settings (`signed-in`), `toast()`,
        `spawn()` and `demo`; a test passes a stand-in with those."""
        super().__init__()
        self._app = app
        self._engine = app.engine
        self._resting = 'none'  # the last state that was not 'seeking'
        self._held = None  # while a play request is pending: the resting state held (resting)
        self.track_grace_ms = TRACK_GRACE_MS  # 0: a null item clears the track at once
        self._clear_source = 0  # the GLib source waiting out the grace, while one does
        self._track_since = float('-inf')  # when the item playing started (_plausible)
        self._events = 0  # state and track events so far: a refresh() answer older than one
        self._queue_events = 0  # is not applied over it (the same for the queue's)
        self._play_lock = asyncio.Lock()  # one play request at a time, in order
        self._play_serial = 0  # the latest request's number: an older one waiting is dropped
        self.position_updated_at = time.monotonic()
        self.queue = Gio.ListStore(item_type=NowPlaying)
        self._lyrics_task = None  # the task reading the track's lyrics, while one runs
        self._lyrics_wanted = None  # the catalog id that task reads
        self._session = None  # while restored: the session (session.read()'s dict)
        self._queue_offset = 0  # while restored: where the queue shown begins in the session's
        self._source = None  # what the queue came from ({kind, id}), while it is still that
        self._source_ids = None  # the ids of the source's queue as MusicKit first gave them
        self._volume_wanted = None  # a volume set while restored with the engine down
        self._cleared = None  # what the last Clear took, for its Undo ({id, entries, local})
        self._capabilities = {}  # what MusicKit last said it allows (CAPABILITIES), if anything
        self._engine.connect('event', self._on_event)
        self._engine.connect('notify::state', self._on_engine_state)
        if self._engine.state == 'up':
            self._app.spawn(self.refresh())
            self._app.spawn(self.apply_autoplay())

    # -- state from the engine -------------------------------------------------------------

    def _on_engine_state(self, engine, _pspec):
        if engine.state == 'up':
            self._app.spawn(self.refresh())
            self._app.spawn(self.apply_autoplay())
        elif engine.state == 'down':
            if self.restored:
                self._set_preview('')  # MusicKit never had the session: it stays
            else:
                self.apply(None)

    async def refresh(self):
        """Read the engine's now_playing() once (as the engine comes up: whatever it was
        doing before, or nothing) and apply it; an item playing then has the queue read too
        (apply, through _track_queued) and its lyrics. A state or track event that arrived
        while the answer was on its way is newer than the answer, which then sets only the
        modes and the volume, as it does while a play request is pending. Errors are
        logged: events will tell."""
        events = self._events
        try:
            answer = await self._engine.now_playing()
        except EngineError as error:
            log.debug('now playing: %s', error)
            return
        if self.restored and not (isinstance(answer, dict)
                                  and isinstance(answer.get('track'), dict)):
            await self._restored_volume(answer)
            return
        if (self._events != events or self.pending) and isinstance(answer, dict):
            # A play request with the engine is newer than the answer too: its events tell.
            log.debug('now playing: events arrived meanwhile; the answer sets the modes only')
            answer = {key: answer[key] for key in ('shuffle', 'repeat', 'volume')
                      if key in answer}
        self._end_restored()
        self.apply(answer)

    async def _restored_volume(self, answer):
        """The engine up under a session restored, MusicKit holding nothing: the volume
        set meanwhile goes to it, or its own is taken."""
        level, self._volume_wanted = self._volume_wanted, None
        if level is not None:
            try:
                await self._engine.volume(level)
            except EngineError as error:
                log.debug('volume: %s', error)
        elif isinstance(answer, dict) and 'volume' in answer:
            self._set_volume(answer.get('volume'))

    async def refresh_queue(self):
        """Read the engine's queue() and apply it, unless a queueItemsDidChange arrived
        meanwhile (the event is newer). Errors are logged."""
        events = self._queue_events
        try:
            answer = await self._engine.queue()
        except EngineError as error:
            log.debug('queue: %s', error)
            return
        if self._queue_events != events:
            log.debug('queue: an event arrived meanwhile; the answer is dropped')
            return
        self.apply_queue(answer)

    def apply(self, now_playing):
        """Set everything from a now-playing answer ({state, track, position, duration,
        shuffle, repeat, volume}; a key left out is left alone; a `queue` snapshot and a
        `lyrics` answer are taken too, the lyrics then not asked of the engine), or reset
        to nothing playing (None: the state, track, times, queue and lyrics; shuffle,
        repeat and the volume are Apple's page's, kept across engine restarts, and the
        next refresh() reads them)."""
        if not isinstance(now_playing, dict):
            self._end_restored()
            self._release_hold()  # nothing plays: nothing to hold through
            self._cancel_clear()
            self._set_preview('')
            self._set_track(None)
            self._set_state('none')
            self._set_position(0.0, 0.0)
            self.apply_queue(None)
            self._cleared = None
            self._take_capabilities_of({'capabilities': {}})
            return
        data = now_playing
        if 'queue' in data:  # before the track, which then finds itself in it
            self.apply_queue(data.get('queue'))
        if isinstance(data.get('track'), dict):
            self._take_capabilities_of(data, update=False)  # with the item, under its freeze
        if 'track' in data:
            self._set_track(data.get('track'), fetch_lyrics='lyrics' not in data)
        if 'lyrics' in data:
            self._set_lyrics(data.get('lyrics'))
        if 'state' in data:
            self._set_state(data.get('state'))
        if 'position' in data or 'duration' in data:
            self._set_position(_number(data.get('position', self.position)),
                               _number(data.get('duration', self.duration)))
        if 'shuffle' in data:
            self._set_shuffle(data.get('shuffle'))
        if 'repeat' in data:
            self._set_repeat(data.get('repeat'))
        if 'volume' in data:
            self._set_volume(data.get('volume'))
        self._update_controls()

    def apply_queue(self, snapshot):
        """Set the queue from a {index, items: [Track…], editable, canAutoplay, autoplay}
        snapshot (the bridge's queue() answer and the queueItemsDidChange event), or empty it
        (None). MusicKit re-sends the whole queue at every change, so the snapshot is compared
        with the store, entry by entry, before any object is made (_splice_queue), and only
        what differs is spliced: the same entries rebind no rows, one entry taken out or put
        in is one splice of it, and the entries kept are renumbered. The index is the
        snapshot's, or the track's place when it says -1."""
        items = snapshot.get('items') if isinstance(snapshot, dict) else None
        items = items if isinstance(items, list) else []
        wanted = [dict(item, index=position) for position, item in enumerate(items)
                  if isinstance(item, dict)]
        self._splice_queue(wanted)
        self._take_capabilities(snapshot if isinstance(snapshot, dict) else {})
        self._follow_source(wanted)
        index = snapshot.get('index') if isinstance(snapshot, dict) else None
        index = int(index) if isinstance(index, int) and not isinstance(index, bool) else -1
        if index < 0 and self.track is not None:
            index = self._index_of(self.track)
        self._set_queue_index(index)

    def _splice_queue(self, wanted):
        """Make the store hold `wanted` (entries' data, each with its index) with one
        splice of what differs: the entries alike at the start and at the end (compared by
        NowPlaying.key: everything but the index) are kept as they are, and those after the
        change get their new index."""
        store = self.queue
        count = store.get_n_items()
        keys = [_entry_key(data) for data in wanted]
        start = 0
        limit = min(count, len(wanted))
        while start < limit and store.get_item(start).key == keys[start]:
            start += 1
        end = 0
        limit -= start
        while (end < limit
               and store.get_item(count - 1 - end).key == keys[len(wanted) - 1 - end]):
            end += 1
        removed = count - start - end
        added = wanted[start:len(wanted) - end]
        if removed or added:
            store.splice(start, removed, [NowPlaying(data) for data in added])
        if removed != len(added):
            self._renumber(start + len(added))

    def _renumber(self, start):
        """The entries from `start` on get the index of their place (after a splice)."""
        for position in range(start, self.queue.get_n_items()):
            entry = self.queue.get_item(position)
            if entry.index != position:
                entry.raw['index'] = position
                entry.index = position

    def _take_capabilities(self, snapshot):
        """What MusicKit allows with the queue now (a snapshot's `editable` and
        `canAutoplay`), and its `autoplay`; a snapshot without them (an older answer, the
        session restored, None) allows everything and leaves autoplay as it was."""
        editable = snapshot.get('editable') is not False or self.restored
        if editable != self.queue_editable:
            self.queue_editable = editable
        can_autoplay = snapshot.get('canAutoplay') is not False
        if can_autoplay != self.can_autoplay:
            self.can_autoplay = can_autoplay
        if 'autoplay' in snapshot:
            self._set_autoplay(snapshot.get('autoplay'))

    def _set_autoplay(self, value):
        autoplay = value is True
        if autoplay != self.autoplay:
            self.autoplay = autoplay

    def _follow_source(self, entries):
        """The source is kept while the queue holds what MusicKit first queued for it, in
        that order: Play Next, Play Later, a shuffle or MusicKit's own additions make it a
        queue of its own. A station's queue changes as it plays, and stays the station's."""
        if self._source is None or self._source['kind'] == 'station' or not entries:
            return
        ids = [entry.get('id') for entry in entries]
        if self._source_ids is None:
            self._source_ids = ids
        elif ids != self._source_ids:
            log.debug('the queue is no longer the one its source queued')
            self._source = None

    def _index_of(self, track):
        """Where `track` is in the queue: at its own index when the entry there is it, else
        the first entry with its id, else -1."""
        count = self.queue.get_n_items()
        if 0 <= track.index < count and self.queue.get_item(track.index).id == track.id:
            return track.index
        for position, entry in enumerate(self.queue):
            if entry.id == track.id:
                return position
        return -1

    def _set_queue_index(self, index):
        index = index if 0 <= index < self.queue.get_n_items() else -1
        if index != self.queue_index:
            self.queue_index = index

    def _on_event(self, _engine, name, data):
        if name not in EVENTS:
            return
        data = data if isinstance(data, dict) else {}
        if 'error' in data and len(data) == 1:
            log.warning('%s: the bridge could not read the state: %s', name, data['error'])
            return
        log.debug('event %s: %s', name, data if name not in ('nowPlayingItemDidChange',
                                                             'queueItemsDidChange')
                  else {'index': data.get('index'), 'track': bool(data.get('track')),
                        'items': len(data.get('items') or ())})
        if self.restored:
            if _holds_item(name, data):
                self._end_restored()  # MusicKit plays something of its own: that shows now
            elif name not in ('playbackVolumeDidChange', 'mediaPlaybackError',
                              'previewDidChange'):
                return  # MusicKit holds nothing of the session restored: it stays as it is
        if name == 'playbackStateDidChange':
            self._events += 1
            self._set_state(data.get('state'))
            if 'position' in data:
                self._take_position(data)
            if data.get('state') in CAPABLE_STATES:
                self._take_capabilities_of(data)
        elif name == 'nowPlayingItemDidChange':
            self._events += 1
            if isinstance(data.get('track'), dict):
                # Taken first: they go out with the new item, under its freeze. An item
                # without them (an older bridge's) forgets the item before's.
                self._take_capabilities_of({'capabilities': data.get('capabilities') or {}},
                                           update=False)
                self._set_track(data['track'])
                self._update_controls()
            else:
                self._clear_track_soon()
        elif name == 'capabilitiesChanged':
            self._take_capabilities_of(data)
        elif name == 'bridgeReset':
            # A new document in the page: nothing plays in it, and MusicKit there says
            # nothing of what the old one was doing. Read what it holds.
            self._events += 1
            self.apply(None)
            self._app.spawn(self.refresh())
            self._app.spawn(self.apply_autoplay())  # the page set its own as it loaded
        elif name == 'playbackTimeDidChange':
            self._take_position(data)
        elif name == 'playbackDurationDidChange':
            self._set_duration(_number(data.get('duration')))
        elif name == 'shuffleModeDidChange':
            self._set_shuffle(data.get('shuffle'))
        elif name == 'repeatModeDidChange':
            self._set_repeat(data.get('repeat'))
        elif name == 'playbackVolumeDidChange':
            self._set_volume(data.get('volume'))
        elif name == 'queueItemsDidChange':
            self._queue_events += 1
            self.apply_queue(data)
        elif name == 'queuePositionDidChange':
            index = data.get('index')
            self._set_queue_index(index if isinstance(index, int) else -1)
        elif name == 'previewDidChange':
            self._set_preview(_text(data.get('id')))
        elif name == 'autoplayEnabledDidChange':
            self._set_autoplay(data.get('autoplay'))
        elif name == 'mediaPlaybackError':
            code = _text(data.get('code'))
            log.warning('playback error %s: %s', code or '(no code)',
                        _text(data.get('message')) or '(no message)')
            self.emit('error', playback_error_text(code))

    def _set_preview(self, song_id):
        if song_id != self.preview:
            self.preview = song_id

    def _take_position(self, data):
        """An event's position and duration, unless the position is the previous item's,
        reported once more after a track change (TRACK_HOLD, SEEK_JUMP), or the item is on
        its way out (a null item's grace: the 0 MusicKit reports as it clears a queue)."""
        if self._clear_source:
            return
        position = _number(data.get('position'))
        if not self._plausible(position):
            log.debug('position %.1f dropped: the item started %.1f s ago', position,
                      time.monotonic() - self._track_since)
            return
        self._set_position(position, _duration_of(data))

    def _plausible(self, position):
        """Whether `position` can be the item playing's: any position once TRACK_HOLD has
        passed since it started, else one within SEEK_JUMP of how far it can have got (from
        0, or from where an answer put it)."""
        elapsed = time.monotonic() - self._track_since
        return (elapsed >= TRACK_HOLD or position <= elapsed + SEEK_JUMP
                or abs(position - self.estimated_position()) <= SEEK_JUMP)

    def _set_state(self, state):
        state = state if isinstance(state, str) and state else 'none'
        if state not in PLAYBACK_STATES:
            log.debug('unknown playback state %r', state)
        if state != 'seeking':
            self._resting = state
            if self._held is not None and state in ACTIVE_STATES:
                self._held = state
        if state != self.state:
            self.position_updated_at = time.monotonic()  # the position runs on, or stops, from here
            self.state = state

    def _set_track(self, data, fetch_lyrics=True):
        """The item playing from an event's or an answer's Track (or None: nothing). The
        track, its position and its duration change together, under one freeze, so a
        `notify::track` handler reads the new item's times: 0 and Apple's length for it
        (0 without one; MusicKit's duration follows). The same song at another queue
        position (the queue reordered under it: a shuffle toggle) keeps its times."""
        if isinstance(data, dict):
            self._cancel_clear()
            track = NowPlaying(data)
            current = self.track
            if current is not None and current.same_as(track) and current.raw == data:
                return
            with self.freeze_notify():
                if current is None or current.id != track.id:
                    self._track_since = time.monotonic()
                    self._reset_times(track.duration_ms / 1000)
                self.track = track
                self._update_controls()  # notified with the track, after it
            self._track_queued(track)
            if fetch_lyrics:
                self._want_lyrics(track)
        elif self.track is not None:
            with self.freeze_notify():
                self._reset_times(0.0)
                self.track = None
                self._update_controls()
            self._set_queue_index(-1)
            self._cancel_lyrics()
            self._set_lyrics(None)

    def _clear_track_soon(self):
        """A null item: the track is cleared once track_grace_ms have passed without a new
        item (MusicKit's null between queues is followed by one), or at once without a
        grace. The engine going down (apply(None)) clears at once."""
        if self.track is None or self._clear_source:
            return
        if not self.track_grace_ms:
            self._set_track(None)
            return
        self._clear_source = GLib.timeout_add(self.track_grace_ms, self._on_grace_over)

    def _on_grace_over(self):
        self._clear_source = 0
        self._set_track(None)
        return GLib.SOURCE_REMOVE

    def _cancel_clear(self):
        if self._clear_source:
            GLib.source_remove(self._clear_source)
            self._clear_source = 0

    def _reset_times(self, duration):
        """Position 0 and `duration` for an item that starts (or none), as they are."""
        self.position_updated_at = time.monotonic()
        if self.position != 0.0:
            self.position = 0.0
        if duration != self.duration:
            self.duration = duration

    def _track_queued(self, track):
        """The item playing has changed: point the queue index at it, or read the queue
        again when the entries held do not include it (a new queue whose items event was
        missed, or came before the engine's connection)."""
        index = self._index_of(track)
        if index >= 0:
            self._set_queue_index(index)
        else:
            self._set_queue_index(-1)
            self._app.spawn(self.refresh_queue())

    # -- lyrics ------------------------------------------------------------------------------

    def _want_lyrics(self, track):
        """Lyrics for the item playing: kept when they are the song's already (the same
        song again, or repeat one), else asked of the engine as a task; none for an item
        without a catalog id (a station's ad, say), or for a live station (its id is the
        station's)."""
        catalog_id = track.catalog_id if not track.live else ''
        if self.lyrics is not None and self.lyrics.catalog_id == catalog_id:
            return
        if self._lyrics_task is not None and not self._lyrics_task.done():
            if self._lyrics_wanted == catalog_id:
                return
        self._cancel_lyrics()
        self._set_lyrics(None)
        if not catalog_id:
            return
        self._set_lyrics_loading(True)
        self._lyrics_wanted = catalog_id
        self._lyrics_task = self._app.spawn(self._load_lyrics(catalog_id))

    def _cancel_lyrics(self):
        task, self._lyrics_task = self._lyrics_task, None
        self._lyrics_wanted = None
        if task is not None and not task.done():
            task.cancel()
        self._set_lyrics_loading(False)

    async def _load_lyrics(self, catalog_id):
        task = asyncio.current_task()
        answer = None
        try:
            answer = await self._engine.lyrics(catalog_id)
        except EngineError as error:
            log.debug('lyrics: %s', error)
        finally:
            if self._lyrics_task is task:
                self._lyrics_task = None
                self._lyrics_wanted = None
                self._set_lyrics_loading(False)
        if self.track is not None and self.track.catalog_id == catalog_id:
            self._set_lyrics(answer, catalog_id)

    def _set_lyrics(self, answer, catalog_id=None):
        """`answer` the engine's lyrics answer (no lines: no lyrics), or None."""
        if isinstance(answer, Lyrics):
            lyrics = answer
        elif isinstance(answer, dict) and answer.get('lines'):
            if catalog_id is None:
                catalog_id = self.track.catalog_id if self.track is not None else ''
            lyrics = Lyrics(answer, catalog_id)
        else:
            lyrics = None
        if lyrics is not self.lyrics:
            self.lyrics = lyrics

    def _set_lyrics_loading(self, loading):
        if loading != self.lyrics_loading:
            self.lyrics_loading = loading

    def _set_position(self, position, duration=None):
        """The position (stamped only when it changes: MusicKit reports whole seconds
        four times a second, and the stamp is when the second began) and the duration."""
        position = max(0.0, position)
        if position != self.position:
            self.position_updated_at = time.monotonic()
            self.position = position
        if duration is not None:
            self._set_duration(duration)

    def _set_duration(self, duration):
        """MusicKit's duration for the item; nothing (0, while an item loads) keeps Apple's
        length for it, when the item has one."""
        duration = max(0.0, duration)
        if duration <= 0 and self.track is not None:
            duration = self.track.duration_ms / 1000
        if duration != self.duration:
            self.duration = duration

    def _set_shuffle(self, value):
        shuffle = value == 'on' if isinstance(value, str) else bool(value)
        if shuffle != self.shuffle:
            self.shuffle = shuffle

    def _set_repeat(self, value):
        repeat = value if value in REPEAT_MODES else 'none'
        if repeat != self.repeat:
            self.repeat = repeat

    def _set_volume(self, value):
        volume = min(1.0, max(0.0, _number(value, 1.0)))
        if volume != self.volume:
            self.volume = volume

    # -- what may be done ------------------------------------------------------------------

    def _take_capabilities_of(self, data, update=True):
        """An event's or an answer's `capabilities` ({canSeek, canPause, canSkipToNextItem,
        canSkipToPreviousItem}: MusicKit's now), when it has them; {} forgets them. `update`
        False leaves the can_* properties to the caller (the item's change sets them)."""
        capabilities = data.get('capabilities')
        if not isinstance(capabilities, dict):
            return
        self._capabilities = {key: capabilities[key] is not False
                              for key in CAPABILITIES if key in capabilities}
        if update:
            self._update_controls()

    def _update_controls(self):
        """can_seek, can_pause, can_go_next and can_go_previous from the item and what
        MusicKit allows: nothing for a live station; everything for a session restored (its
        commands are the Player's own) and where MusicKit says nothing; Previous also while
        the item can be sought (it restarts it)."""
        live = self.live
        allowed = {key: not live and (self.restored or self._capabilities.get(key, True))
                   for key in CAPABILITIES}
        values = {'can_seek': allowed['canSeek'], 'can_pause': allowed['canPause'],
                  'can_go_next': allowed['canSkipToNextItem'],
                  'can_go_previous': allowed['canSkipToPreviousItem'] or allowed['canSeek']}
        for name, value in values.items():
            if self.get_property(name) != value:
                self.set_property(name, value)

    @property
    def live(self):
        """Whether the item is a live radio station (NowPlaying.live): it has no length (its
        duration is the stream's window), and cannot be sought, paused or skipped."""
        return self.track is not None and self.track.live

    # -- derived -------------------------------------------------------------------------

    @property
    def resting(self):
        """The state with 'seeking' seen through: the state before the seek while it lasts
        (a seek while playing stays playing, one while paused stays paused). While a play
        request is pending, the states that are not ACTIVE_STATES are seen through too:
        MusicKit pauses, seeks and stops the queue playing as it loads the new one, and
        the bar and MPRIS would flip to Play and Stopped for a moment. The last active
        state since the request shows instead, or the resting state it began in; MusicKit's
        own once the engine has answered (notify::state then, when that differs)."""
        state = self._resting if self.state == 'seeking' else self.state
        if self._held is not None and state not in ACTIVE_STATES:
            return self._held
        return state

    @property
    def active(self):
        """Whether playback is under way (ACTIVE_STATES, a seek during it included): the
        bar shows Pause."""
        return self.resting in ACTIVE_STATES

    @property
    def stopped(self):
        """Whether nothing plays or is paused (no item, or STOPPED_STATES): what background
        playback waits for before the app quits. MusicKit passes through these between
        queues and at the end of each item, so a caller gives it a moment."""
        return self.track is None or self.resting in STOPPED_STATES

    def estimated_position(self):
        """The position now: the last one reported plus the time since while playing (a
        second at most: the reports are whole seconds, so the truth is within the second
        that began at the stamp, and a stalled stream does not run ahead), never past the
        duration when that is known. What MPRIS answers between events and the lyrics
        follow."""
        position = self.position
        if self.state == 'playing':
            position += min(time.monotonic() - self.position_updated_at, 1.0)
            if self.duration:
                position = min(position, self.duration)
        return position

    @property
    def source(self):
        """What the queue came from, {kind, id} (an album, a playlist, a station), while
        it is still that queue in order; None otherwise."""
        return dict(self._source) if self._source is not None else None

    @property
    def queue_offset(self):
        """Where the queue shown begins in the session's own (a restored session keeps a
        slice of a long queue); 0 for MusicKit's."""
        return self._queue_offset if self.restored else 0

    # -- the last session ------------------------------------------------------------------

    def restore(self, session):
        """Show `session` (session.read()'s dict: queue, index, offset, position, duration,
        repeat, source) as its item paused, MusicKit not asked for it yet: `restored` holds
        until restore_session() hands it over or MusicKit plays something of its own.
        Shuffle shows off: the queue comes back in its order. Nothing when the Player has an
        item already. Whether it was taken."""
        if not isinstance(session, dict) or self.track is not None or self.pending:
            return False
        queue = session.get('queue') or []
        index = session.get('index', 0)
        if not queue or not isinstance(index, int) or not 0 <= index < len(queue):
            return False
        self._session = session
        self._queue_offset = session.get('offset', 0)
        self._source = session.get('source')
        self._source_ids = None
        self.restored = True
        self._update_controls()
        self.apply_queue({'index': index, 'items': queue})
        self._set_track(dict(queue[index], index=index))
        self._set_state('paused')
        self._set_position(_number(session.get('position')),
                           _number(session.get('duration'), self.duration) or None)
        self._set_shuffle(False)
        self._set_repeat(session.get('repeat'))
        log.info('the last session restored: %d in the queue, at %d', len(queue), index)
        return True

    def forget_session(self):
        """Sign-out or Clear Cache: a session restored goes, and the bar with it. What
        MusicKit plays is the engine's to stop."""
        if self.restored:
            self.apply(None)
        self._source = None
        self._source_ids = None
        self._volume_wanted = None

    def _end_restored(self):
        """The session restored is over: MusicKit has it, or holds another (a Clear of the
        session's has nothing to undo in MusicKit's)."""
        self._session = None
        self._queue_offset = 0
        if self._cleared is not None and self._cleared['local']:
            self._cleared = None
        if self.restored:
            self.restored = False
            self._update_controls()

    def _take_restored(self):
        """A play request is about to reach MusicKit: the session restored, if any, is
        its no longer (MusicKit's events show what plays from here, and a refresh() answer
        under way is older than the request). What _give_back() needs to show it again, or
        None."""
        if not self.restored:
            return None
        held = {'session': self._session, 'track': self.track, 'position': self.position,
                'queue': {'index': self.queue_index,
                          'items': [dict(entry.raw) for entry in self.queue]}}
        self._events += 1
        self._end_restored()
        return held

    def _give_back(self, held, error, restoring):
        """A play request failed: the session restored is the Player's again while the
        item it showed still shows (MusicKit put nothing of its own in its place), but not
        when MusicKit refused the session itself (`restoring`, EngineError('api') with its
        code): then it goes, `session-dropped` tells its keeper, and `error` says why.
        Whether the error was answered so (not to be raised)."""
        if held is None or self.track is not held['track']:
            return False
        if restoring and error.code == 'api' and error.musickit_code:
            log.warning('the last session could not be restored: %s', error)
            self.apply(None)
            self.emit('session-dropped')
            self.emit('error', playback_error_text(error.musickit_code))
            return True
        session = held['session']
        self._session = session
        self._queue_offset = session.get('offset', 0)
        self.restored = True
        self._update_controls()
        self._cancel_clear()  # a null item MusicKit sent meanwhile clears nothing
        self.apply_queue(held['queue'])
        self._set_state('paused')
        self._set_position(held['position'])
        return False

    async def restore_session(self, index=None, paused=False):
        """Hand the session restored to MusicKit and play it: the item shown at its
        position, or the queue's entry at `index` from the top (an Up Next row); `paused`
        only queues it (play_next, play_later), the position kept for the first Play. The
        source when the queue is still that (a station plays live), else the queue's songs
        by id (a music video in it is left out, or plays alone when it is the item); shuffle
        off, the repeat mode shown, a volume set meanwhile. Nothing when not restored."""
        if not self.restored:
            return
        entries = list(self.queue)
        at = self.queue_index if index is None else index
        if not 0 <= at < len(entries):
            return
        entry = entries[at]
        position = self.position if index is None else 0.0
        if self.duration and position >= self.duration - END_SLACK:
            position = 0.0
        source = self._source
        start_with = start_id = None
        if source is not None and source['kind'] == 'station':
            target, position = source, 0.0
        elif source is not None:
            target, start_with, start_id = source, self._queue_offset + at, entry.id
        elif entry.kind == 'video':
            target = {'kind': 'musicVideo', 'id': entry.catalog_id or entry.id}
        else:
            songs = [(place, item) for place, item in enumerate(entries) if item.kind == 'song']
            places = [place for place, _item in songs]
            if at not in places:
                log.warning('the item of the last session cannot be restored')
                return
            target = {'kind': 'songs', 'id': ','.join(item.id for _place, item in songs)}
            start_with, start_id = places.index(at), entry.id
        await self._request(target, start_with=start_with, shuffle=False, start_id=start_id,
                            restoring={'start_time': position, 'paused': paused,
                                       'shuffle': self.shuffle, 'repeat': self.repeat})

    def _seek_restored(self, seconds):
        seconds = max(0.0, _number(seconds))
        if self.duration:
            seconds = min(seconds, self.duration)
        self._set_position(seconds)

    def _step_restored(self, step):
        """Next (1) or previous (-1) in the session restored, paused, from the top; past the
        queue's ends, nothing (previous: back to the top)."""
        at = self.queue_index + step
        if not 0 <= at < self.queue.get_n_items():
            if step < 0:
                self._seek_restored(0)
            return
        self._set_track(dict(self.queue.get_item(at).raw))
        self._set_position(0.0)

    # -- commands ------------------------------------------------------------------------

    async def ensure_engine(self):
        """The engine up for a play request (or any command of the account's: the item
        actions use it too): started first when it is down and the account is signed in (a
        toast meanwhile); EngineError('not-signed-in') when it is not."""
        if self._app.demo:
            raise EngineError('engine-down', 'no engine with the demo library')
        if self._engine.state != 'down':
            return
        if not self._app.settings.get_boolean(self._app.account_key('signed-in')):
            raise EngineError('not-signed-in', 'sign in to Apple Music to play')
        self._app.toast(_('Starting playback engine…'))
        await self._engine.start()

    async def play(self, play, start_with=None, shuffle=None, start_id=None):
        """Play what `play` names ({kind, id}: an Item's or a Group's play target), from its
        entry at queue position `start_with`, the track `start_id` (a track row's: the item
        that must play, wherever MusicKit queues it); `shuffle` True shuffled (a Shuffle
        button), False in order (a Play button), None as the mode is (a track row). Requests
        go to the engine one at a time, in order, and one superseded while it waits is dropped
        (the newest wins: a second album clicked while the first's queue loads). `pending`
        is True from a request until the engine has answered it, or it failed. A session
        restored is replaced (given back when the request fails)."""
        await self._request(play, start_with, shuffle, start_id)

    async def _request(self, play, start_with=None, shuffle=None, start_id=None,
                       restoring=None):
        """play()'s request; `restoring` ({start_time, paused, shuffle, repeat}) when it
        hands the session restored to MusicKit (restore_session)."""
        kind = play.get('kind') if isinstance(play, dict) else None
        item_id = play.get('id') if isinstance(play, dict) else None
        if not kind or item_id in (None, ''):
            raise EngineError('usage', 'nothing to play')
        self._play_serial += 1
        serial = self._play_serial
        self._set_pending(True)
        try:
            async with self._play_lock:
                if serial != self._play_serial:
                    log.debug('play %s %s superseded', kind, item_id)
                    return
                await self.ensure_engine()
                log.info('play %s %s%s%s%s', kind, item_id if kind != 'songs' else '…',
                         f' from {start_with}' if start_with is not None else '',
                         {True: ' shuffled', False: ' in order'}.get(shuffle, ''),
                         ' (the last session)' if restoring else '')
                held = self._take_restored()
                source = self._source, self._source_ids
                self._note_source(kind, item_id, shuffle)
                try:
                    await self._send_play(kind, item_id, start_with, shuffle, start_id,
                                          restoring)
                except EngineError as error:
                    self._source, self._source_ids = source
                    if not self._give_back(held, error, restoring is not None):
                        raise
        finally:
            if serial == self._play_serial:
                self._set_pending(False)

    async def _send_play(self, kind, item_id, start_with, shuffle, start_id, restoring):
        """The engine's play, with what a session restored brings: its repeat mode and a
        volume set meanwhile before it, its position as start_time, shuffle turned on after
        it when it was asked for meanwhile (MusicKit shuffles what follows)."""
        extra = {}
        if restoring is not None:
            await self._engine.repeat(restoring['repeat'])
            level, self._volume_wanted = self._volume_wanted, None
            if level is not None:
                await self._engine.volume(level)
            if restoring['start_time']:
                extra['start_time'] = restoring['start_time']
            if restoring['paused']:
                extra['paused'] = True
        await self._engine.play(kind, item_id, start_with=start_with, shuffle=shuffle,
                                start_id=start_id, **extra)
        if restoring is not None and restoring['shuffle']:
            await self._engine.shuffle('on')

    def _note_source(self, kind, item_id, shuffle):
        """A play request's target is the queue's source when it can be queued again as
        itself: an album or a playlist in order, a station."""
        shuffled = self.shuffle if shuffle is None else shuffle
        if kind in SOURCE_KINDS and (kind == 'station' or not shuffled):
            self._source = {'kind': kind, 'id': str(item_id)}
        else:
            self._source = None
        self._source_ids = None

    def _set_pending(self, pending):
        """A play request pending or not; the resting state is held while one is."""
        if pending == self.pending:
            return
        if pending:
            self._held = self.resting
        else:
            self._release_hold()
        self.pending = pending

    def _release_hold(self):
        """Show MusicKit's own resting state again (the request answered or failed, or the
        engine gone), telling the views through notify::state when it is not what they
        showed: they read `resting`, `active` and `stopped` there."""
        if self._held is None:
            return
        shown = self.resting
        self._held = None
        if self.resting != shown:
            self.notify('state')

    async def play_next(self, kind, item_id):
        """Queue an item after the one playing; a session restored is queued first, paused
        (restore_session), so it goes after that."""
        await self.ensure_engine()
        await self.restore_session(paused=True)
        await self._engine.play_next(kind, item_id)

    async def play_later(self, kind, item_id):
        await self.ensure_engine()
        await self.restore_session(paused=True)
        await self._engine.play_later(kind, item_id)

    async def start_preview(self, song_id, url):
        """Play Apple's preview of a song (`url`, its clip's https address) in place of any
        before it, MusicKit paused meanwhile (engine.preview()): the engine is started first
        as for a play (ensure_engine()). `preview` follows from the engine's events."""
        await self.ensure_engine()
        log.info('preview %s', song_id)
        await self._engine.preview(song_id, url)

    async def stop_preview(self):
        """Stop the preview playing, if one is."""
        if self._engine.state != 'down':
            await self._engine.stop_preview()

    async def toggle(self):
        """Pause when playback is under way (ACTIVE_STATES: what the bar's button shows),
        play otherwise. Decided here, not by the bridge's toggle: MusicKit's isPlaying is
        false while an item loads, so a toggle then would ask it to play again. A session
        restored plays (restore_session). A live station playing cannot be paused: it
        stops (stop())."""
        if self.restored:
            await self.restore_session()
            return
        if self.live and self.active:
            await self.stop()
            return
        await self._engine.control('pause' if self.active else 'play')

    async def pause(self):
        """Pause; a live station, which MusicKit would leave playing, stops (stop())."""
        if self.restored:
            return  # paused already, and MusicKit holds nothing
        if self.live:
            await self.stop()
            return
        await self._engine.control('pause')

    async def resume(self):
        if self.restored:
            await self.restore_session()
            return
        await self._engine.control('play')

    async def next(self):
        if self.live:
            return  # MusicKit skips nothing on a live station
        if self.restored:
            self._step_restored(1)
            return
        await self._engine.control('next')

    async def previous(self):
        """The item before, or this one from the top when it is PREVIOUS_RESTART seconds
        in; nothing on a live station."""
        if self.live:
            return
        if self.estimated_position() > PREVIOUS_RESTART:
            await self.seek(0)
        elif self.restored:
            self._step_restored(-1)
        else:
            await self._engine.control('previous')

    async def stop(self):
        """Stop. A live station's item goes with it in MusicKit (it holds nothing then), so
        the station stays shown as a session restored, stopped (_keep_station): Play plays
        it again."""
        if self.restored:
            self._seek_restored(0)
            return
        station = self._station_playing()
        await self._engine.control('stop')
        if station is not None:
            self._keep_station(*station)

    def _station_playing(self):
        """(the item, its station's play target) while a live station plays, else None:
        the station the queue came from, else the item's own id (a live station's item is
        the station)."""
        if not self.live:
            return None
        source = self._source
        if source is None or source['kind'] != 'station':
            source = {'kind': 'station', 'id': self.track.id}
        return self.track, dict(source)

    def _keep_station(self, track, source):
        """A live station stopped: shown as a session restored (its item alone, stopped,
        no position, the station its source), unless another item has come meanwhile."""
        if self.track is not track or self.restored:
            return
        raw = {key: value for key, value in track.raw.items() if key != 'index'}
        self._cancel_clear()  # the null item MusicKit sends after its stop clears nothing
        self._session = {'queue': [raw], 'index': 0, 'offset': 0, 'position': 0.0,
                         'duration': 0.0, 'repeat': self.repeat, 'source': source}
        self._queue_offset = 0
        self._source = source
        self._source_ids = None
        self.restored = True
        self._update_controls()
        self.apply_queue({'index': 0, 'items': [raw]})
        self._set_state('stopped')
        self._set_position(0.0, 0.0)
        log.info('the live station stopped; Play plays it again')

    async def queue_jump(self, index):
        """Play the queue's entry at `index` (the Up Next list)."""
        if self.restored:
            await self.restore_session(index=int(index))
            return
        await self._engine.queue_jump(int(index))

    # -- Up Next's edits ---------------------------------------------------------------------

    def can_edit(self, index, entry_id=None):
        """Whether the queue's entry at `index` (the entry `entry_id`, when given) may be
        taken out: one after the entry playing, while MusicKit allows edits."""
        if not self.queue_editable or self.queue_index < 0:
            return False
        if not self.queue_index < index < self.queue.get_n_items():
            return False
        return entry_id is None or self.queue.get_item(index).id == entry_id

    def can_clear(self):
        """Whether anything follows the entry playing that Clear could take out."""
        return (self.queue_editable and self.queue_index >= 0
                and self.queue_index + 1 < self.queue.get_n_items())

    def _queue_edited(self):
        """A session restored was edited: it is its songs' queue now, not its source's."""
        if self.restored:
            self._source = None
            self._source_ids = None

    async def _send_edit(self, command):
        """An edit made in the store, sent to the engine: on a failure the queue is read
        again (MusicKit's is what shows); 'queue-changed' (the entry named is not there now)
        only that, else the error is raised. Whether the engine took it."""
        try:
            await command
        except EngineError as error:
            self._app.spawn(self.refresh_queue())
            if error.code == 'queue-changed':
                log.info('Up Next: %s', error)
                return False
            raise
        return True

    async def remove_from_queue(self, index, entry_id):
        """Take the queue's entry at `index` out, when it is the entry `entry_id` and comes
        after the entry playing (can_edit): out of the store at once, then out of MusicKit's
        queue (engine.queue_remove), whose queueItemsDidChange then finds the store as it is.
        While a session is restored, out of it alone. Whether it was taken out."""
        index = int(index)
        if not self.can_edit(index, entry_id):
            log.debug('Up Next: entry %d is not %s, or cannot be removed', index, entry_id)
            return False
        self.queue.remove(index)
        self._renumber(index)
        if self.restored:
            self._queue_edited()
            return True
        return await self._send_edit(self._engine.queue_remove(index, entry_id))

    async def clear_up_next(self):
        """Take everything after the entry playing out (Up Next's Clear): out of the store at
        once, then out of MusicKit's queue (engine.queue_clear), or out of the session
        restored alone. What went is kept for undo_clear(). How many entries went."""
        if not self.can_clear():
            return 0
        at = self.queue_index
        count = self.queue.get_n_items()
        entries = [dict(self.queue.get_item(position).raw) for position in range(at + 1, count)]
        self._cleared = {'id': self.queue.get_item(at).id, 'entries': entries,
                         'local': self.restored}
        self.queue.splice(at + 1, count - at - 1, [])
        if self.restored:
            self._queue_edited()
            return len(entries)
        try:
            taken = await self._send_edit(self._engine.queue_clear())
        except EngineError:
            self._cleared = None
            raise
        if not taken:
            self._cleared = None
            return 0
        return len(entries)

    @property
    def can_undo_clear(self):
        """Whether undo_clear() has something to put back after the entry playing."""
        cleared = self._cleared
        return (cleared is not None and self.queue_index >= 0
                and self.queue.get_item(self.queue_index).id == cleared['id']
                and cleared['local'] == self.restored)

    async def undo_clear(self):
        """Put back what the last clear_up_next() took, after the entry playing, while that
        is still the entry it was (and MusicKit's, or the session's, as the Clear was): into
        the store at once, then MusicKit's queue (engine.queue_undo_clear). Once only. How
        many came back."""
        if not self.can_undo_clear:
            self._cleared = None
            return 0
        cleared, self._cleared = self._cleared, None
        at = self.queue_index + 1
        self.queue.splice(at, 0, [NowPlaying(dict(data, index=at + offset))
                                  for offset, data in enumerate(cleared['entries'])])
        self._renumber(at + len(cleared['entries']))
        if self.restored:
            return len(cleared['entries'])
        if not await self._send_edit(self._engine.queue_undo_clear()):
            return 0
        return len(cleared['entries'])

    async def apply_autoplay(self):
        """MusicKit's autoplay set to the app's `autoplay` setting (the page keeps a switch
        of its own, which the web player sets as it loads): as the engine comes up, after a
        bridgeReset and when the setting changes. Nothing with the engine not up or the demo
        library; a failure is logged."""
        if self._app.demo or self._engine.state != 'up':
            return
        wanted = self._app.settings.get_boolean('autoplay')
        try:
            answer = await self._engine.set_autoplay(wanted)
        except EngineError as error:
            log.debug('autoplay: %s', error)
            return
        self._set_autoplay(answer.get('autoplay'))
        can_autoplay = answer.get('canAutoplay') is not False
        if can_autoplay != self.can_autoplay:
            self.can_autoplay = can_autoplay
        if self.autoplay != wanted:
            log.info('autoplay: MusicKit kept it %s', 'on' if self.autoplay else 'off')

    async def seek(self, seconds):
        if self.live:
            return  # MusicKit ignores a seek on a live station
        if self.restored:
            self._seek_restored(seconds)
            return
        self._track_since = float('-inf')  # the positions that follow are the seek's
        await self._engine.seek(seconds)

    async def set_volume(self, level):
        """MusicKit's volume; with a session restored and the engine down, the Player's
        until the engine comes up or the session plays."""
        if self.restored and self._engine.state == 'down':
            level = min(1.0, max(0.0, _number(level, 1.0)))
            self._volume_wanted = level
            self._set_volume(level)
            return level
        return await self._engine.volume(level)

    async def set_shuffle(self, on):
        """Shuffle on or off; with a session restored, the Player's until it plays."""
        if self.restored:
            self._set_shuffle(bool(on))
            return {'shuffle': 'on' if self.shuffle else 'off', 'repeat': self.repeat}
        return await self._engine.shuffle('on' if on else 'off')

    async def set_repeat(self, mode):
        """The repeat mode; with a session restored, the Player's until it plays."""
        if self.restored:
            self._set_repeat(mode)
            return {'shuffle': 'on' if self.shuffle else 'off', 'repeat': self.repeat}
        return await self._engine.repeat(mode)

    def next_repeat(self):
        """The repeat mode after this one in the cycle none → one → all → none."""
        position = REPEAT_MODES.index(self.repeat) if self.repeat in REPEAT_MODES else 0
        return REPEAT_MODES[(position + 1) % len(REPEAT_MODES)]


def playback_error_text(code):
    """The sentence the user sees for a MusicKit playback error code (a
    mediaPlaybackError's, or EngineError.musickit_code of a refused play): what it means
    for them, never the code or MusicKit's own text, which go to the log."""
    if code in ('CONTENT_UNAVAILABLE', 'GEO_BLOCK'):
        return _('This isn’t available in your country or region')
    if code == 'CONTENT_RESTRICTED':
        return _('This content is restricted')
    if code == 'SUBSCRIPTION_ERROR':
        return _('An Apple Music subscription is needed to play this')
    if code in ('DEVICE_LIMIT', 'NETWORK_ERROR', 'MEDIA_LICENSE', 'MEDIA_KEY'):
        return _('The engine could not play protected content')
    return _('This could not be played')


def format_time(seconds, remaining=False):
    """Seconds as m:ss (h:mm:ss past an hour), the remaining time with a leading minus."""
    total = max(0, int(_number(seconds) + 0.5))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        text = f'{hours}:{minutes:02d}:{secs:02d}'
    else:
        text = f'{minutes}:{secs:02d}'
    return f'-{text}' if remaining else text
