# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The last session: what played, kept in the cache so the next launch shows it paused.

    keeper = SessionKeeper(app, config.cache_dir() / FILE_NAME)   # app.session, not in demo
    await keeper.load()      # at launch, with the window: the file read in a thread and
                             # shown on the Player (Player.restore), when signed in
    task = keeper.save_now() # quitting: the Player as it is now, written (await the task)
    keeper.forget()          # sign-out, Clear Cache: nothing kept from before is written
    data = snapshot(player)  # the dict the file holds, or None (nothing worth keeping)
    session = read(path)     # the file's session, checked (parse()), or None

<cache>/session.json holds the queue (the bridge's Track shape for each entry, the keys of
TRACK_KEYS, at most QUEUE_LIMIT of them around the item), the item's index in it, `offset`
(where that slice begins in the queue MusicKit had), the position and duration, the repeat
mode, and `source`: the album, playlist or station the queue came from, only while the queue
was still that (Player.source), so it is queued again as itself. A station keeps only its
item and no position (it plays live). Shuffle is not kept: the queue comes back in its order,
shuffle off. An item that is neither a song nor a video (a station's segment, without the
station) is not kept, and nothing (the engine gone, a request pending) never replaces what is.
The file is the account's: library ids and titles, in the cache (0600), which Clear Cache and
sign-out empty (cache.CACHE_ENTRIES); never in the settings, never logged.

The keeper follows the Player: a change (the item, the queue, its index, the state, the
repeat mode, a seek while not playing, a session restored) is written SAVE_DELAY_MS later,
coalesced, and the position every POSITION_EVERY seconds while the music plays, so a crash
loses that much at most. The snapshot is made on the main thread, the JSON and the atomic
write (store.py) in a thread, one write at a time, the newest winning, for the cache
generation the keeper began with: a write under way when the cache is wiped lands nowhere.
MusicKit refusing the session restored (the Player's session-dropped) deletes the file.
GLib and GObject only, no GTK.
"""

import asyncio
import datetime
import json
import logging
import math
import os

from gi.repository import GLib

from .backend import store

log = logging.getLogger(__name__)

FILE_NAME = 'session.json'
VERSION = 1
QUEUE_LIMIT = 250    # entries kept of a long queue (each a NowPlaying at launch: ~45 µs)
QUEUE_BEFORE = 50    # of them, before the item
SAVE_DELAY_MS = 2000  # after a change: MusicKit sends its changes in bursts
POSITION_EVERY = 30   # seconds between writes of the position while playing

# What is kept of each queue entry (the bridge's formatTrack): what the bar, the sheet, Up
# Next and MPRIS show, and what queues it again.
TRACK_KEYS = ('id', 'type', 'catalogId', 'title', 'artist', 'album', 'trackNumber',
              'discNumber', 'durationMs', 'explicit', 'artUrl')
TEXT_KEYS = ('id', 'type', 'catalogId', 'title', 'artist', 'album')
NUMBER_KEYS = ('trackNumber', 'discNumber', 'durationMs')
SOURCE_KINDS = ('album', 'playlist', 'station')
REPEAT_MODES = ('none', 'one', 'all')


def _keep(raw):
    return {key: raw[key] for key in TRACK_KEYS if raw.get(key) is not None}


def snapshot(player, now=None):
    """What the file keeps of the Player now, or None: nothing playing or paused, a play
    request pending (the old queue and the new meet), or an item that cannot be queued again
    (neither a song nor a video, without its station)."""
    track = player.track
    if track is None or player.pending:
        return None
    source = player.source
    saved = (now or datetime.datetime.now(datetime.UTC)).isoformat(timespec='seconds')
    data = {'version': VERSION, 'saved': saved, 'repeat': player.repeat}
    if source is not None and source['kind'] == 'station':
        return dict(data, source=source, queue=[_keep(track.raw)], index=0, offset=0,
                    position=0.0, duration=0.0)
    if track.kind not in ('song', 'video'):
        return None
    entries = [_keep(entry.raw) for entry in player.queue]
    index = player.queue_index
    offset = player.queue_offset
    if not 0 <= index < len(entries):
        entries, index, offset, source = [_keep(track.raw)], 0, 0, None
    start = max(0, min(index - QUEUE_BEFORE, len(entries) - QUEUE_LIMIT))
    return dict(data, source=source, queue=entries[start:start + QUEUE_LIMIT],
                index=index - start, offset=offset + start,
                position=round(player.estimated_position(), 1),
                duration=round(float(player.duration), 1))


def _number(value):
    """A finite number that is not negative, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _entry(raw):
    """A queue entry as kept, or None when it is not one (no id, a value of the wrong type,
    artwork that is not https)."""
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id']:
        return None
    entry = {}
    for key in TRACK_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if key in TEXT_KEYS and not isinstance(value, str):
            return None
        if key in NUMBER_KEYS and _number(value) is None:
            return None
        if key == 'explicit' and not isinstance(value, bool):
            return None
        if key == 'artUrl' and not (isinstance(value, str) and value.startswith('https://')):
            return None
        entry[key] = int(value) if key in NUMBER_KEYS else value
    return entry


def parse(data):
    """The session a file's JSON holds, checked, or None: another version, no queue, an
    entry or an index that is not one. A position past the item's end is its end."""
    if not isinstance(data, dict) or data.get('version') != VERSION:
        return None
    queue = data.get('queue')
    if not isinstance(queue, list) or not queue:
        return None
    entries = [_entry(raw) for raw in queue[:QUEUE_LIMIT]]
    if None in entries:
        return None
    index = data.get('index')
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(entries):
        return None
    offset = data.get('offset')
    offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0
    duration = _number(data.get('duration')) or 0.0
    position = _number(data.get('position')) or 0.0
    if duration:
        position = min(position, duration)
    source = data.get('source')
    if not (isinstance(source, dict) and source.get('kind') in SOURCE_KINDS
            and isinstance(source.get('id'), str) and source['id']):
        source = None
    repeat = data.get('repeat') if data.get('repeat') in REPEAT_MODES else 'none'
    return {'queue': entries, 'index': index, 'offset': max(0, offset), 'position': position,
            'duration': duration, 'repeat': repeat,
            'source': {'kind': source['kind'], 'id': source['id']} if source else None}


def read(path):
    """The session kept at `path`, or None: no file, or one that cannot be read or is not a
    session (logged). Blocks: call it in a thread."""
    try:
        with open(path, encoding='utf-8') as file:
            data = json.load(file)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.warning('could not read the last session: %s', error)
        return None
    session = parse(data)
    if session is None:
        log.warning('the last session kept is not one this version reads')
    return session


def write(path, data, generation):
    """Keep `data` at `path`, atomically; not once the cache's generation has moved from
    `generation`. Best effort. Blocks: call it in a thread."""
    try:
        store.atomic_write(path, lambda file: json.dump(data, file), root=os.path.dirname(path),
                           text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not keep the last session: %s', error)


def remove(path):
    """Delete the file at `path`, if there is one. Blocks: call it in a thread."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        log.warning('could not delete the last session: %s', error)


class SessionKeeper:
    """See the module. `app` gives the Player (`app.player`), `spawn()`, the settings and
    `account_key()`, and `signing_out`."""

    def __init__(self, app, path):
        self._app = app
        self._player = app.player
        self.path = str(path)
        self.delay_ms = SAVE_DELAY_MS  # 0 in tests: written at the next idle
        self._timer = 0  # the GLib source of a write waiting out the delay
        self._ticker = 0  # the GLib source writing the position while the music plays
        self._latest = None  # the snapshot the writer is to write
        self._edits = 0  # snapshots taken, to know whether the writer is behind
        self._writer = None
        self._generation = None  # the cache's, taken at the first write after forget()
        self._quiet = False  # while restoring: the Player's changes are the file's own
        self._closed = False  # quitting: the last snapshot is taken
        player = self._player
        for name in ('track', 'queue-index', 'repeat', 'restored'):
            player.connect(f'notify::{name}', self._on_change)
        player.connect('notify::state', self._on_state)
        player.connect('notify::position', self._on_position)
        player.queue.connect('items-changed', self._on_change)
        player.connect('session-dropped', self._on_dropped)

    async def load(self):
        """Show the session kept on the Player (Player.restore), when the account is signed
        in and the Player has nothing: the file read and checked in a thread."""
        settings = self._app.settings
        if not settings.get_boolean(self._app.account_key('signed-in')):
            return
        session = await asyncio.to_thread(read, self.path)
        if session is None or self._closed:
            return
        self._quiet = True
        try:
            self._player.restore(session)
        finally:
            self._quiet = False

    def save_now(self):
        """Quitting: the snapshot taken now (before the engine stops and the Player
        empties) and written; nothing is scheduled after it. The writer's task to await, or
        None when there is nothing to write."""
        self._cancel_timers()
        self._closed = True
        return self._save()

    def forget(self, remove_file=False):
        """Sign-out or Clear Cache (after the cache's generation was bumped), or MusicKit
        refusing the session: nothing taken before is written, and the next write is for
        the cache as it is then; `remove_file` deletes the file too."""
        self._cancel_timers()
        self._latest = None
        self._generation = None
        if remove_file:
            self._app.spawn(asyncio.to_thread(remove, self.path))

    # -- following the Player ----------------------------------------------------------------

    def _on_change(self, *_args):
        self._schedule()

    def _on_position(self, *_args):
        if not self._player.active:  # a seek, a pause; while playing, the ticker writes
            self._schedule()

    def _on_state(self, *_args):
        self._schedule()
        if self._player.active and not self._closed:
            if not self._ticker:
                self._ticker = GLib.timeout_add_seconds(POSITION_EVERY, self._on_tick)
        elif self._ticker:
            GLib.source_remove(self._ticker)
            self._ticker = 0

    def _on_tick(self):
        self._schedule()
        return GLib.SOURCE_CONTINUE

    def _on_dropped(self, _player):
        self.forget(remove_file=True)

    def _schedule(self):
        if self._quiet or self._closed or self._timer or self._app.signing_out:
            return
        self._timer = GLib.timeout_add(self.delay_ms, self._on_due)

    def _on_due(self):
        self._timer = 0
        if self._player.pending:
            self._schedule()  # the queue is changing hands: once the request is answered
        else:
            self._save()
        return GLib.SOURCE_REMOVE

    def _cancel_timers(self):
        for name in ('_timer', '_ticker'):
            source = getattr(self, name)
            if source:
                GLib.source_remove(source)
                setattr(self, name, 0)

    def _save(self):
        data = snapshot(self._player)
        if data is None:
            return None
        self._latest = data
        self._edits += 1
        if self._writer is None or self._writer.done():
            self._writer = self._app.spawn(self._write())
        return self._writer

    async def _write(self):
        written = None
        while written != self._edits:
            written = self._edits
            data = self._latest
            if data is None:
                continue  # forgotten meanwhile
            if self._generation is None:
                self._generation = store.cache_generation()
            await asyncio.to_thread(write, self.path, data, self._generation)
