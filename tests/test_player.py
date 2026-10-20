# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Player: its properties fed by synthetic engine events, and its commands over a fake
engine. GObject only, no GTK or display; the commands run under asyncio.run."""

import asyncio
import contextlib
import time
import types
import unittest
from unittest import mock

from gi.repository import GObject

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import iterate

from applemusic.backend.errors import EngineError
from applemusic.lyrics import Lyrics
from applemusic.player import (ACTIVE_STATES, STOPPED_STATES, NowPlaying, Player, format_time,
                               move_range, moved_entry, playback_error_text, removed_entry,
                               undone_tail)


class Clock:
    """A stand-in time.monotonic(): `now`, moved by advance()."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@contextlib.contextmanager
def patched_clocks(start=1000.0):
    """time.monotonic() under the test's control, as the Player and the MPRIS service read
    it (both read the time module's). asyncio's own timers stand still meanwhile: no
    `asyncio.sleep()` of more than 0 inside."""
    clock = Clock(start)
    with mock.patch.object(time, 'monotonic', clock):
        yield clock

# An invented track, as the bridge's formatTrack shapes it.
TRACK = {
    'id': 'i.demo0001', 'catalogId': '1000000001', 'title': 'Harbour Lights',
    'artist': 'The Invented Band', 'album': 'Fictional Album', 'trackNumber': 3,
    'discNumber': 1, 'durationMs': 214000, 'durationLabel': '3:34', 'explicit': False,
    'artUrl': 'https://example.invalid/art/256x256bb.jpg', 'index': 2,
}

# An invented queue of three, TRACK at index 2.
QUEUE = {'index': 2, 'items': [
    dict(TRACK, id='i.demo0003', catalogId='1000000003', title='Shoreline', index=0),
    dict(TRACK, id='i.demo0002', catalogId='1000000002', title='Pilot Light', index=1),
    TRACK,
]}

LYRICS = {'synced': True, 'lines': [
    {'startMs': 1000, 'endMs': 3000, 'text': 'One'},
    {'startMs': 4000, 'endMs': 6000, 'text': 'Two'},
]}


class FakeEngine(GObject.Object):
    """The Engine's surface the Player uses: the event signal, state, and the commands,
    which are recorded and answer what the test put in `answers`. A command named in
    `gates` (an asyncio.Event each) waits for its gate before answering, so a test can
    release an answer late; `now_playing` raises EngineError('api') without an answer, as
    the real engine does when the page gives none."""

    __gsignals__ = {
        'event': (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
    }

    state = GObject.Property(type=str, default='down')
    authorized = GObject.Property(type=bool, default=True)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.answers = {}
        self.gates = {}
        self.fail = None  # an EngineError every command raises
        self.play_options = []  # each play's start_id, and start_time and paused when given
        self.play_failures = []  # EngineErrors the next plays raise, one each, in turn
        self.edits = []  # each queue edit's number (queue_remove's and queue_move's `edit`)

    def event(self, name, data):
        self.emit('event', name, data)

    def gate(self, name):
        """Hold the next `name` command until the returned event is set."""
        self.gates[name] = asyncio.Event()
        return self.gates[name]

    async def _command(self, name, *args):
        self.calls.append((name, *args))
        gate = self.gates.get(name)
        if gate is not None:
            await gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.answers.get(name)

    async def start(self, visible=None):
        self.calls.append(('start', visible))
        self.state = 'up'

    async def now_playing(self):
        answer = await self._command('now_playing')
        if not isinstance(answer, dict):
            raise EngineError('api', 'the page gave no now-playing answer')
        return answer

    async def play(self, kind, item_id, start_with=None, shuffle=None, start_id=None,
                   **options):
        self.play_options.append(dict(options, start_id=start_id))  # start_time, paused
        answer = await self._command('play', kind, item_id, start_with, shuffle)
        if self.play_failures:
            raise self.play_failures.pop(0)
        return answer

    async def songs_found(self, song_ids):
        found = await self._command('songs_found', list(song_ids))
        return set(song_ids) if found is None else set(found)

    async def play_next(self, kind, item_id):
        return await self._command('play_next', kind, item_id)

    async def play_later(self, kind, item_id):
        return await self._command('play_later', kind, item_id)

    async def control(self, action):
        return await self._command('control', action)

    async def seek(self, seconds):
        return await self._command('seek', seconds)

    async def volume(self, level):
        return await self._command('volume', level)

    async def shuffle(self, mode):
        return await self._command('shuffle', mode)

    async def repeat(self, mode):
        return await self._command('repeat', mode)

    async def queue(self):
        return await self._command('queue')

    async def queue_jump(self, index):
        return await self._command('queue_jump', index)

    async def queue_remove(self, index, entry_id, edit=None):
        self.edits.append(edit)
        return await self._command('queue_remove', index, entry_id)

    async def queue_move(self, index, to_index, entry_id, edit=None):
        self.edits.append(edit)
        return await self._command('queue_move', index, to_index, entry_id)

    async def queue_clear(self):
        return await self._command('queue_clear')

    async def queue_undo_clear(self):
        return await self._command('queue_undo_clear')

    async def set_autoplay(self, on):
        answer = await self._command('set_autoplay', on)
        return answer if isinstance(answer, dict) else {'autoplay': on, 'canAutoplay': True}

    async def lyrics(self, catalog_id):
        return await self._command('lyrics', catalog_id)

    async def preview(self, song_id, url):
        return await self._command('preview', song_id, url)

    async def stop_preview(self):
        return await self._command('stop_preview')


class FakeSettings:
    def __init__(self, signed_in=True, autoplay=True):
        self.signed_in = signed_in
        self.autoplay = autoplay

    def get_boolean(self, key):
        assert key in ('signed-in', 'autoplay'), key
        return self.signed_in if key == 'signed-in' else self.autoplay

    def bind(self, key, obj, prop, _flags):
        """Gio.Settings.bind's first half: obj's property set from the setting."""
        obj.set_property(prop, self.get_boolean(key))


class FakeApp:
    """What the Player asks of the Application."""

    def account_key(self, name):
        return name  # the release build's keys

    def __init__(self, engine, signed_in=True, demo=False):
        self.engine = engine
        self.settings = FakeSettings(signed_in)
        self.demo = demo
        self.toasts = []
        self.tasks = []
        self.spawned = []  # the names of coroutines spawned with no loop running

    def toast(self, title, *_args):
        self.toasts.append(title)

    def report(self, error):
        self.toasts.append(error)

    def player_command(self, coro, on_error=None):
        """As the app's: a task whose EngineError is reported, then on_error() called."""
        async def command():
            try:
                await coro
            except EngineError as error:
                self.report(error)
                if on_error is not None:
                    on_error()
        return self.spawn(command())

    def spawn(self, coro):
        """A task on the running loop; without one (the event tests) the coroutine is only
        noted by name and closed."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.spawned.append(coro.__qualname__)
            coro.close()
            return None
        task = loop.create_task(coro)
        self.tasks.append(task)
        return task

    async def settle(self):
        """Wait for every task spawned so far, and for what they spawned."""
        while any(not task.done() for task in self.tasks):
            await asyncio.gather(*self.tasks, return_exceptions=True)


def make_player(signed_in=True, demo=False, state='down', grace_ms=0):
    """A Player over a FakeEngine; a null item clears the track at once unless `grace_ms`
    says otherwise (the synchronous tests want no timer)."""
    engine = FakeEngine()
    engine.state = state
    app = FakeApp(engine, signed_in, demo)
    player = Player(app)
    player.track_grace_ms = grace_ms
    return player, engine, app


def pump_until(predicate, timeout=1.0):
    """Run the default main context until predicate() holds (True) or `timeout` seconds
    pass (False): what a GLib timeout of the Player's needs."""
    from gi.repository import GLib

    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    wake = GLib.timeout_add(5, lambda: GLib.SOURCE_CONTINUE)
    try:
        while not predicate():
            if time.monotonic() >= deadline:
                return False
            iterate(context, True)
        return True
    finally:
        GLib.source_remove(wake)


class EventTest(unittest.TestCase):
    def setUp(self):
        self.player, self.engine, self.app = make_player()
        self.notified = []
        for prop in ('state', 'track', 'position', 'duration', 'shuffle', 'repeat', 'volume'):
            self.player.connect(f'notify::{prop}',
                                lambda _p, pspec: self.notified.append(pspec.name))

    def test_starts_with_nothing_playing(self):
        player = self.player
        self.assertEqual(player.state, 'none')
        self.assertIsNone(player.track)
        self.assertEqual((player.position, player.duration), (0.0, 0.0))
        self.assertFalse(player.shuffle)
        self.assertEqual(player.repeat, 'none')
        self.assertEqual(player.volume, 1.0)
        self.assertFalse(player.active)

    def test_now_playing_item_becomes_a_track(self):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        track = self.player.track
        self.assertIsInstance(track, NowPlaying)
        self.assertEqual((track.id, track.catalog_id), ('i.demo0001', '1000000001'))
        self.assertEqual((track.title, track.artist, track.album),
                         ('Harbour Lights', 'The Invented Band', 'Fictional Album'))
        self.assertEqual(track.duration_ms, 214000)
        self.assertEqual(track.artwork_url, 'https://example.invalid/art/256x256bb.jpg')
        self.assertEqual(track.index, 2)
        self.assertFalse(track.explicit)
        # A new item starts at the top, its duration Apple's until MusicKit says.
        self.assertEqual((self.player.position, self.player.duration), (0.0, 214.0))
        self.assertIn('track', self.notified)

    def test_kind_takes_musickits_own_item_types_too(self):
        """MusicKit types an item it made from a catalog queue 'song' or 'musicVideo',
        not the API's 'songs' or 'music-videos': the heart must rate those too."""
        for number, (resource, kind) in enumerate((
                ('songs', 'song'), ('library-songs', 'song'), ('song', 'song'),
                ('music-videos', 'video'), ('library-music-videos', 'video'),
                ('musicVideo', 'video'), ('music-video', 'video'), ('stations', ''), ('', ''))):
            track = dict(TRACK, id=f'i.kind{number}', type=resource)
            self.engine.event('nowPlayingItemDidChange', {'track': track, 'index': number})
            self.assertEqual(self.player.track.kind, kind, resource)
        track = dict(TRACK, id='i.kind-none')
        track.pop('type', None)
        self.engine.event('nowPlayingItemDidChange', {'track': track, 'index': 99})
        self.assertEqual(self.player.track.kind, 'song')  # a Track without one is a song

    def test_the_same_item_again_is_not_a_change(self):
        with patched_clocks() as clock:
            self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            clock.advance(41)
            self.engine.event('playbackTimeDidChange', {'position': 40, 'duration': 214})
            self.notified.clear()
            self.engine.event('nowPlayingItemDidChange', {'track': dict(TRACK), 'index': 2})
            self.assertEqual(self.notified, [])
            self.assertEqual(self.player.position, 40.0)

    def test_null_item_clears_the_track(self):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('playbackTimeDidChange', {'position': 40, 'duration': 214})
        self.engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.assertIsNone(self.player.track)
        self.assertEqual((self.player.position, self.player.duration), (0.0, 0.0))

    def test_a_null_item_waits_for_the_next_one(self):
        """MusicKit sends a null item between queues, right before the next item: the
        track is cleared only after the grace passes with no new item."""
        player, engine, _app = make_player(grace_ms=40)
        tracks = []
        player.connect('notify::track', lambda p, _pspec: tracks.append(
            p.track.id if p.track is not None else None))
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        engine.event('playbackTimeDidChange', {'position': 1, 'duration': 214})
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.assertIsNotNone(player.track)  # not yet
        # The 0 MusicKit reports as it clears the queue: the item is on its way out.
        engine.event('playbackStateDidChange', {'state': 'stopped', 'position': 0})
        self.assertEqual((player.state, player.position), ('stopped', 1.0))
        other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=0)
        engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
        self.assertFalse(pump_until(lambda: player.track is None, timeout=0.12))
        self.assertEqual(tracks, ['i.demo0001', 'i.demo0002'])  # never None in between
        # A null alone: cleared once the grace is over.
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})  # one timer
        self.assertTrue(pump_until(lambda: player.track is None))
        self.assertEqual(tracks[-1], None)
        self.assertEqual(player.queue_index, -1)
        # The engine going down clears at once, and cancels a grace under way.
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        player.apply(None)
        self.assertIsNone(player.track)
        self.assertEqual(player._clear_source, 0)
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertFalse(pump_until(lambda: player.track is None, timeout=0.1))

    def test_a_track_without_artwork(self):
        self.engine.event('nowPlayingItemDidChange',
                          {'track': dict(TRACK, artUrl=None, durationMs=None), 'index': 0})
        self.assertIsNone(self.player.track.artwork_url)
        self.assertEqual(self.player.track.duration_ms, 0)
        self.assertEqual(self.player.duration, 0.0)

    def test_a_track_change_notifies_with_its_own_times(self):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('playbackTimeDidChange', {'position': 200, 'duration': 214})
        seen = []
        self.player.connect('notify::track', lambda p, _pspec: seen.append(
            (p.track.id, p.position, p.duration)))
        other = dict(TRACK, id='i.demo0002', catalogId='1000000002', durationMs=180000,
                     index=3)
        self.engine.event('nowPlayingItemDidChange', {'track': other, 'index': 3})
        # The handler read the new item's times, not the previous one's.
        self.assertEqual(seen, [('i.demo0002', 0.0, 180.0)])
        # An item without a length after one with it: 0, not the previous item's.
        unknown = dict(TRACK, id='i.demo0003', catalogId='1000000003', durationMs=None, index=4)
        self.engine.event('nowPlayingItemDidChange', {'track': unknown, 'index': 4})
        self.assertEqual((self.player.position, self.player.duration), (0.0, 0.0))
        self.engine.event('playbackDurationDidChange', {'duration': 190})
        self.assertEqual(self.player.duration, 190.0)

    def test_a_zero_duration_keeps_the_items_length(self):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('playbackStateDidChange',
                          {'state': 'loading', 'position': 0, 'duration': 0})
        self.assertEqual(self.player.duration, 214.0)
        self.engine.event('playbackTimeDidChange', {'position': 1, 'duration': 213.5})
        self.assertEqual(self.player.duration, 213.5)

    def test_the_same_song_at_another_queue_position_keeps_its_times(self):
        with patched_clocks() as clock:
            self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            clock.advance(41)
            self.engine.event('playbackTimeDidChange', {'position': 40, 'duration': 214})
            self.notified.clear()
            self.engine.event('nowPlayingItemDidChange',
                              {'track': dict(TRACK, index=5), 'index': 5})
            self.assertEqual(self.notified, ['track'])  # the queue was reordered under it
            self.assertEqual(self.player.track.index, 5)
            self.assertEqual((self.player.position, self.player.duration), (40.0, 214.0))

    def test_a_position_an_answer_gave_goes_on(self):
        """The engine coming up mid-song: the answer's position, then MusicKit's ticks from
        there, all taken (a seek of the app's own ends the hold too)."""
        with patched_clocks() as clock:
            self.player.apply({'track': TRACK, 'state': 'playing', 'position': 90,
                               'duration': 214})
            clock.advance(0.25)
            self.engine.event('playbackTimeDidChange', {'position': 90, 'duration': 214})
            clock.advance(0.75)
            self.engine.event('playbackTimeDidChange', {'position': 91, 'duration': 214})
            self.assertEqual(self.player.position, 91.0)
            self.engine.event('nowPlayingItemDidChange',
                              {'track': dict(TRACK, id='i.demo0002', index=3), 'index': 3})

            async def seek():
                await self.player.seek(60)
            asyncio.run(seek())
            self.engine.event('playbackTimeDidChange', {'position': 60, 'duration': 214})
            self.assertEqual(self.player.position, 60.0)

    def test_playback_state_and_times(self):
        self.engine.event('playbackStateDidChange',
                          {'state': 'playing', 'position': 12.5, 'duration': 214})
        self.assertEqual(self.player.state, 'playing')
        self.assertTrue(self.player.active)
        self.assertEqual((self.player.position, self.player.duration), (12.5, 214.0))
        self.engine.event('playbackStateDidChange', {'state': 'paused', 'position': 13})
        self.assertEqual(self.player.state, 'paused')
        self.assertFalse(self.player.active)
        self.assertEqual(self.player.position, 13.0)
        self.assertEqual(self.player.duration, 214.0)  # no duration in the event: kept
        for state in ACTIVE_STATES:
            self.engine.event('playbackStateDidChange', {'state': state})
            self.assertTrue(self.player.active, state)
        self.engine.event('playbackStateDidChange', {'state': 'stopped'})
        self.assertFalse(self.player.active)

    def test_seeking_keeps_the_state_before_it(self):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('playbackStateDidChange', {'state': 'playing'})
        self.engine.event('playbackStateDidChange', {'state': 'seeking', 'position': 30})
        self.assertEqual((self.player.state, self.player.resting), ('seeking', 'playing'))
        self.assertTrue(self.player.active)  # the bar keeps its Pause icon
        self.assertFalse(self.player.stopped)

        async def toggle():
            await self.player.toggle()
        asyncio.run(toggle())
        self.assertEqual(self.engine.calls[-1], ('control', 'pause'))
        self.engine.event('playbackStateDidChange', {'state': 'paused'})
        self.engine.event('playbackStateDidChange', {'state': 'seeking'})
        self.assertEqual(self.player.resting, 'paused')
        self.assertFalse(self.player.active)
        self.engine.event('playbackStateDidChange', {'state': 'stopped'})
        self.engine.event('playbackStateDidChange', {'state': 'seeking'})
        self.assertTrue(self.player.stopped)

    def test_stopped_is_no_item_or_a_stopped_state(self):
        self.assertTrue(self.player.stopped)  # nothing yet
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        for state in ACTIVE_STATES + ('paused', 'seeking'):
            self.engine.event('playbackStateDidChange', {'state': state})
            self.assertFalse(self.player.stopped, state)
        for state in STOPPED_STATES:
            self.engine.event('playbackStateDidChange', {'state': state})
            self.assertTrue(self.player.stopped, state)
        self.engine.event('playbackStateDidChange', {'state': 'playing'})
        self.engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.assertTrue(self.player.stopped)  # playing, but no item

    def test_an_unknown_state_is_kept_as_it_is(self):
        self.engine.event('playbackStateDidChange', {'state': 'buffering'})
        self.assertEqual(self.player.state, 'buffering')
        self.engine.event('playbackStateDidChange', {'state': None})
        self.assertEqual(self.player.state, 'none')

    def test_time_updates_stamp_the_position(self):
        before = time.monotonic()
        self.engine.event('playbackTimeDidChange', {'position': 61, 'duration': 214})
        self.assertEqual((self.player.position, self.player.duration), (61.0, 214.0))
        self.assertGreaterEqual(self.player.position_updated_at, before)
        self.assertLessEqual(self.player.position_updated_at, time.monotonic())
        self.notified.clear()
        self.engine.event('playbackTimeDidChange', {'position': 61, 'duration': 214})
        self.assertEqual(self.notified, [])  # the same position notifies nothing

    def test_estimated_position_runs_on_while_playing(self):
        with patched_clocks() as clock:
            self.engine.event('playbackStateDidChange', {'state': 'playing'})
            self.engine.event('playbackTimeDidChange', {'position': 10, 'duration': 12})
            clock.advance(0.5)
            self.assertEqual(self.player.estimated_position(), 10.5)
            clock.advance(10)
            self.assertEqual(self.player.estimated_position(), 11.0)  # a second at most
            self.engine.event('playbackTimeDidChange', {'position': 11.5, 'duration': 12})
            clock.advance(0.8)
            self.assertEqual(self.player.estimated_position(), 12.0)  # never past the end
            self.engine.event('playbackStateDidChange', {'state': 'paused'})
            clock.advance(5)
            self.assertEqual(self.player.estimated_position(), 11.5)  # paused: as reported
            # Resumed: it runs on from the moment of the resume, not from the last report.
            self.engine.event('playbackStateDidChange', {'state': 'playing'})
            clock.advance(0.25)
            self.assertEqual(self.player.estimated_position(), 11.75)

    def test_the_estimate_never_runs_backwards(self):
        """MusicKit reports whole seconds four times a second: the estimate follows the
        clock within a quarter second and never decreases."""
        with patched_clocks() as clock:
            self.engine.event('playbackStateDidChange', {'state': 'playing'})
            estimates = []
            for step in range(20):
                second = 10 + step // 4
                self.engine.event('playbackTimeDidChange', {'position': second, 'duration': 214})
                estimates.append(self.player.estimated_position())
                self.assertAlmostEqual(estimates[-1], 10 + step / 4, delta=0.25)
                clock.advance(0.25)
            self.assertEqual(estimates, sorted(estimates))
            # After the tick from 12 to 13 plus 0.3 s, the estimate reaches a line at 13.2 s.
            clock.advance(0.3)
            lyrics = Lyrics({'synced': True, 'lines': [
                {'startMs': 1000, 'text': 'One'}, {'startMs': 13200, 'text': 'Two'}]})
            self.assertEqual(lyrics.index_at(self.player.estimated_position()), 1)

    def test_duration_shuffle_repeat_volume(self):
        self.engine.event('playbackDurationDidChange', {'duration': 300.5})
        self.assertEqual(self.player.duration, 300.5)
        self.engine.event('shuffleModeDidChange', {'shuffle': 'on'})
        self.assertTrue(self.player.shuffle)
        self.engine.event('shuffleModeDidChange', {'shuffle': 'off'})
        self.assertFalse(self.player.shuffle)
        self.engine.event('repeatModeDidChange', {'repeat': 'one'})
        self.assertEqual(self.player.repeat, 'one')
        self.engine.event('repeatModeDidChange', {'repeat': 'all'})
        self.assertEqual(self.player.repeat, 'all')
        self.engine.event('repeatModeDidChange', {'repeat': 'bogus'})
        self.assertEqual(self.player.repeat, 'none')
        self.engine.event('playbackVolumeDidChange', {'volume': 0.25})
        self.assertEqual(self.player.volume, 0.25)
        self.engine.event('playbackVolumeDidChange', {'volume': 7})
        self.assertEqual(self.player.volume, 1.0)  # clamped
        self.assertEqual(self.notified.count('volume'), 2)

    def test_next_repeat_cycles(self):
        self.assertEqual(self.player.next_repeat(), 'one')
        self.engine.event('repeatModeDidChange', {'repeat': 'one'})
        self.assertEqual(self.player.next_repeat(), 'all')
        self.engine.event('repeatModeDidChange', {'repeat': 'all'})
        self.assertEqual(self.player.next_repeat(), 'none')

    def test_other_events_and_bad_payloads_are_ignored(self):
        self.engine.event('queueItemsDidChange', {'index': 0, 'items': []})
        self.engine.event('authorizationStatusDidChange', {'authorized': True})
        self.engine.event('playbackTimeDidChange', None)
        self.engine.event('playbackTimeDidChange', {'error': 'MusicKit not initialized'})
        self.engine.event('playbackStateDidChange', 'playing')
        self.assertEqual(self.notified, [])
        self.assertEqual(self.player.state, 'none')

    def test_playback_error_is_a_signal_with_a_sentence(self):
        errors = []
        self.player.connect('error', lambda _p, message: errors.append(message))
        with self.assertLogs('applemusic.player', level='WARNING') as logged:
            self.engine.event('mediaPlaybackError',
                              {'code': 'CONTENT_UNAVAILABLE', 'message': 'x'})
            self.engine.event('mediaPlaybackError', {'code': 'BOGUS', 'message': 'y'})
            self.engine.event('mediaPlaybackError', {})
        self.assertEqual(errors[0], 'This isn’t available in your country or region')
        self.assertEqual(errors[1], 'This could not be played')  # an unknown code
        self.assertEqual(errors[2], 'This could not be played')
        self.assertIn('CONTENT_UNAVAILABLE: x', logged.output[0])  # the raw text, logged
        for code, sentence in (('GEO_BLOCK', 'This isn’t available in your country or region'),
                               ('CONTENT_RESTRICTED', 'This content is restricted'),
                               ('SUBSCRIPTION_ERROR',
                                'An Apple Music subscription is needed to play this'),
                               ('MEDIA_LICENSE', 'The engine could not play protected content'),
                               ('', 'This could not be played')):
            self.assertEqual(playback_error_text(code), sentence, code)


class PreviewTest(unittest.TestCase):
    """A suggested song's preview: `preview` follows previewDidChange, and nothing else of
    the Player does (the queue is paused, as MusicKit says); the commands."""

    def test_preview_follows_the_events_alone(self):
        player, engine, _app = make_player()
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 0})
        engine.event('playbackStateDidChange', {'state': 'paused'})
        notified = []
        player.connect('notify::preview', lambda p, _pspec: notified.append(p.preview))
        engine.event('previewDidChange', {'id': '1000000101'})
        self.assertEqual(player.preview, '1000000101')
        self.assertEqual((player.state, player.track.id), ('paused', 'i.demo0001'))
        engine.event('previewDidChange', {'id': '1000000101'})  # the same: no notify
        engine.event('previewDidChange', {'id': None, 'ended': '1000000101', 'reason': 'ended'})
        self.assertEqual(player.preview, '')
        self.assertEqual(notified, ['1000000101', ''])

    def test_the_engine_going_or_a_new_page_ends_it(self):
        player, engine, _app = make_player(state='up')
        engine.event('previewDidChange', {'id': '1000000101'})
        engine.event('bridgeReset', {})
        self.assertEqual(player.preview, '')
        engine.event('previewDidChange', {'id': '1000000102'})
        engine.state = 'down'
        self.assertEqual(player.preview, '')

    def test_the_commands(self):
        async def go():
            player, engine, app = make_player(state='down')
            await player.stop_preview()  # nothing to stop: the engine is not started for it
            self.assertEqual(engine.calls, [])
            await player.start_preview('1000000101', 'https://example.invalid/a.m4a')
            self.assertEqual(engine.calls, [
                ('start', None), ('preview', '1000000101', 'https://example.invalid/a.m4a')])
            await player.stop_preview()
            self.assertEqual(engine.calls[-1], ('stop_preview',))
            demo, demo_engine, _app = make_player(demo=True)
            with self.assertRaises(EngineError) as raised:
                await demo.start_preview('1000000101', 'https://example.invalid/a.m4a')
            self.assertEqual(raised.exception.code, 'engine-down')
        asyncio.run(go())


class StalePositionTest(unittest.TestCase):
    """After a track change MusicKit reports the previous item's position once more: the
    Player drops it, so no view sees it."""

    def test_the_previous_items_position_is_dropped_after_a_change(self):
        with patched_clocks() as clock:
            player, engine, _app = make_player()
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            engine.event('playbackStateDidChange',
                         {'state': 'playing', 'position': 195, 'duration': 214})
            clock.advance(5)
            engine.event('playbackTimeDidChange', {'position': 200, 'duration': 214})
            self.assertEqual(player.position, 200.0)
            other = dict(TRACK, id='i.demo0009', catalogId='1000000009', title='Later',
                         durationMs=180000, index=3)
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 3})
            # The skip's state transitions carry A's position and length once more.
            engine.event('playbackStateDidChange',
                         {'state': 'playing', 'position': 200, 'duration': 214})
            self.assertEqual(player.state, 'playing')  # the state is still taken
            self.assertEqual((player.position, player.duration), (0.0, 180.0))
            engine.event('playbackTimeDidChange', {'position': 200, 'duration': 214})
            self.assertEqual((player.position, player.duration), (0.0, 180.0))
            # The new item's own positions are taken, a little ahead of the clock too.
            engine.event('playbackTimeDidChange', {'position': 1, 'duration': 180})
            self.assertEqual(player.position, 1.0)
            clock.advance(1)
            engine.event('playbackTimeDidChange', {'position': 2.5, 'duration': 180})
            self.assertEqual(player.position, 2.5)
            engine.event('playbackTimeDidChange', {'position': 5, 'duration': 180})
            self.assertEqual(player.position, 2.5)  # 5 s in, 1 s after it started: stale
            # Once the hold is over, a jump is a seek and is taken.
            clock.advance(2)
            engine.event('playbackTimeDidChange', {'position': 60, 'duration': 180})
            self.assertEqual(player.position, 60.0)

    def test_the_same_song_at_another_position_is_not_a_new_start(self):
        with patched_clocks() as clock:
            player, engine, _app = make_player()
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            clock.advance(5)
            engine.event('playbackTimeDidChange', {'position': 200, 'duration': 214})
            engine.event('nowPlayingItemDidChange', {'track': dict(TRACK, index=4), 'index': 4})
            engine.event('playbackTimeDidChange', {'position': 201, 'duration': 214})
            self.assertEqual(player.position, 201.0)  # a reorder: its positions go on


class EngineLifecycleTest(unittest.TestCase):
    def test_engine_coming_up_reads_now_playing_once(self):
        async def go():
            player, engine, app = make_player(state='down')
            engine.answers['now_playing'] = {
                'state': 'paused', 'track': TRACK, 'position': 90, 'duration': 214,
                'shuffle': 'on', 'repeat': 'all', 'volume': 0.4}
            engine.answers['queue'] = QUEUE
            engine.state = 'up'
            await app.settle()
            # The app's autoplay setting goes to MusicKit as the engine comes up.
            self.assertEqual(engine.calls, [('now_playing',), ('set_autoplay', True), ('queue',),
                                            ('lyrics', '1000000001')])
            self.assertEqual(player.state, 'paused')
            self.assertEqual(player.queue.get_n_items(), 3)
            self.assertEqual(player.queue_index, 2)
            self.assertEqual(player.track.title, 'Harbour Lights')
            self.assertEqual((player.position, player.duration), (90.0, 214.0))
            self.assertTrue(player.shuffle)
            self.assertEqual(player.repeat, 'all')
            self.assertEqual(player.volume, 0.4)
            # The engine going down: nothing playing, the modes and the volume kept.
            engine.state = 'down'
            self.assertEqual(player.state, 'none')
            self.assertIsNone(player.track)
            self.assertEqual((player.position, player.duration), (0.0, 0.0))
            self.assertTrue(player.shuffle)
            self.assertEqual(player.volume, 0.4)
            self.assertEqual(player.queue.get_n_items(), 0)
            self.assertEqual(player.queue_index, -1)
            self.assertIsNone(player.lyrics)
        asyncio.run(go())

    def test_an_engine_already_up_is_read_at_once(self):
        async def go():
            player, engine, app = make_player(state='up')
            engine.answers['now_playing'] = {'state': 'playing', 'track': TRACK,
                                             'position': 1, 'duration': 214}
            await app.settle()
            self.assertEqual(player.state, 'playing')
            self.assertEqual(player.track.id, 'i.demo0001')
        asyncio.run(go())

    def test_a_failed_read_leaves_nothing_playing(self):
        async def go():
            player, engine, app = make_player(state='down')
            engine.fail = EngineError('api', 'no')
            engine.state = 'up'
            await app.settle()
            self.assertEqual(player.state, 'none')
            self.assertIsNone(player.track)
        asyncio.run(go())

    def test_events_during_the_read_are_newer_than_its_answer(self):
        """A state and a track arrive while now_playing() is on its way: the answer, older,
        sets only the modes and the volume."""
        async def go():
            player, engine, app = make_player(state='down')
            gate = engine.gate('now_playing')
            engine.answers['now_playing'] = {
                'state': 'paused', 'track': dict(TRACK, id='i.old', index=0), 'position': 90,
                'duration': 214, 'shuffle': 'on', 'repeat': 'all', 'volume': 0.4}
            engine.state = 'up'
            await asyncio.sleep(0)
            engine.event('playbackStateDidChange', {'state': 'loading'})
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            gate.set()
            await app.settle()
            self.assertEqual(player.state, 'loading')
            self.assertEqual(player.track.id, 'i.demo0001')
            self.assertEqual(player.position, 0.0)
            self.assertTrue(player.shuffle)
            self.assertEqual(player.repeat, 'all')
            self.assertEqual(player.volume, 0.4)
        asyncio.run(go())

    def test_a_reloaded_page_resets_and_is_read_again(self):
        """The engine's bridgeReset: the page loaded a new document, and nothing plays in
        it until MusicKit there says so."""
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            engine.event('playbackStateDidChange', {'state': 'playing', 'position': 30})
            await app.settle()
            reads = engine.calls.count(('now_playing',))
            engine.event('bridgeReset', None)
            self.assertIsNone(player.track)
            self.assertEqual(player.state, 'none')
            self.assertEqual((player.position, player.duration), (0.0, 0.0))
            await app.settle()
            self.assertEqual(engine.calls.count(('now_playing',)), reads + 1)
        asyncio.run(go())


class CommandTest(unittest.TestCase):
    def test_play_starts_a_down_engine_when_signed_in(self):
        async def go():
            player, engine, app = make_player(state='down')
            await player.play({'kind': 'album', 'id': 'l.alb1'}, start_with=2)
            self.assertEqual(engine.calls[0], ('start', None))  # the preferred mode
            self.assertEqual(engine.calls[-1], ('play', 'album', 'l.alb1', 2, None))
            self.assertEqual(app.toasts, ['Starting playback engine…'])
            await player.play({'kind': 'album', 'id': 'l.alb1'}, shuffle=False)
            self.assertEqual(engine.calls[-1], ('play', 'album', 'l.alb1', None, False))
        asyncio.run(go())

    def test_play_requests_run_in_order_and_the_newest_wins(self):
        async def go():
            player, engine, app = make_player(state='up')
            pending = []
            player.connect('notify::pending', lambda p, _pspec: pending.append(p.pending))
            gate = engine.gate('play')
            first = asyncio.ensure_future(player.play({'kind': 'album', 'id': 'l.a'}))
            await asyncio.sleep(0)
            self.assertTrue(player.pending)
            second = asyncio.ensure_future(player.play({'kind': 'album', 'id': 'l.b'}))
            third = asyncio.ensure_future(player.play({'kind': 'album', 'id': 'l.c'}))
            await asyncio.sleep(0)
            plays = [call for call in engine.calls if call[0] == 'play']
            self.assertEqual(len(plays), 1)  # the first is with the engine; the rest wait
            gate.set()
            await asyncio.gather(first, second, third)
            plays = [call[2] for call in engine.calls if call[0] == 'play']
            self.assertEqual(plays, ['l.a', 'l.c'])  # the second was superseded by the third
            self.assertFalse(player.pending)
            self.assertEqual(pending, [True, False])
        asyncio.run(go())

    def test_a_failed_request_is_no_longer_pending(self):
        async def go():
            player, engine, app = make_player(signed_in=False, state='down')
            with self.assertRaises(EngineError):
                await player.play({'kind': 'album', 'id': 'l.a'})
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_play_with_the_engine_up_plays_at_once(self):
        async def go():
            player, engine, app = make_player(state='up')
            await player.play({'kind': 'playlist', 'id': 'p.pl1'}, shuffle=True)
            self.assertEqual([call for call in engine.calls if call[0] != 'now_playing'],
                             [('play', 'playlist', 'p.pl1', None, True)])
            self.assertEqual(app.toasts, [])
        asyncio.run(go())

    def test_play_signed_out_is_not_signed_in(self):
        async def go():
            player, engine, app = make_player(signed_in=False, state='down')
            with self.assertRaises(EngineError) as raised:
                await player.play({'kind': 'station', 'id': 'ra.1'})
            self.assertEqual(raised.exception.code, 'not-signed-in')
            self.assertEqual(engine.calls, [])
        asyncio.run(go())

    def test_play_in_demo_mode_is_engine_down(self):
        async def go():
            player, engine, app = make_player(demo=True, state='down')
            with self.assertRaises(EngineError) as raised:
                await player.play({'kind': 'album', 'id': 'l.alb1'})
            self.assertEqual(raised.exception.code, 'engine-down')
            self.assertEqual(engine.calls, [])
        asyncio.run(go())

    def test_play_needs_a_target(self):
        async def go():
            player, engine, app = make_player(state='up')
            for play in (None, {}, {'kind': 'album'}, {'kind': '', 'id': 'x'}):
                with self.assertRaises(EngineError) as raised:
                    await player.play(play)
                self.assertEqual(raised.exception.code, 'usage')
        asyncio.run(go())

    def test_commands_are_thin(self):
        async def go():
            player, engine, app = make_player(state='up')
            engine.answers['volume'] = 0.3
            engine.answers['shuffle'] = {'shuffle': 'on', 'repeat': 'none'}
            await player.toggle()  # nothing under way: play
            engine.event('playbackStateDidChange', {'state': 'loading'})
            await player.toggle()  # loading counts as under way: pause
            engine.event('playbackStateDidChange', {'state': 'paused'})
            await player.pause()
            await player.resume()
            await player.next()
            await player.previous()
            await player.stop()
            await player.seek(42.5)
            self.assertEqual(await player.set_volume(0.3), 0.3)
            self.assertEqual(await player.set_shuffle(True), {'shuffle': 'on', 'repeat': 'none'})
            await player.set_shuffle(False)
            await player.set_repeat('all')
            await player.play_next('song', 'i.1')
            await player.play_later('album', 'l.2')
            await player.queue_jump(1)
            self.assertEqual([call for call in engine.calls if call[0] != 'now_playing'], [
                ('control', 'play'), ('control', 'pause'), ('control', 'pause'),
                ('control', 'play'),
                ('control', 'next'), ('control', 'previous'), ('control', 'stop'),
                ('seek', 42.5), ('volume', 0.3), ('shuffle', 'on'), ('shuffle', 'off'),
                ('repeat', 'all'),
                ('play_next', 'song', 'i.1'), ('play_later', 'album', 'l.2'),
                ('queue_jump', 1)])
            # Nothing above touched the properties but the volume MusicKit answered: the
            # rest only events do.
            self.assertEqual(player.volume, 0.3)
            self.assertFalse(player.shuffle)
        asyncio.run(go())

    def test_previous_restarts_the_item_a_few_seconds_in(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.calls.clear()
            player.apply({'track': TRACK, 'state': 'paused', 'position': 30})
            await player.previous()
            self.assertEqual(engine.calls, [('seek', 0)])
            player.apply({'position': 1})
            await player.previous()
            self.assertEqual(engine.calls[-1], ('control', 'previous'))
        asyncio.run(go())

    def test_errors_pass_through(self):
        async def go():
            player, engine, app = make_player(state='up')
            engine.fail = EngineError('engine-down', 'gone')
            with self.assertRaises(EngineError) as raised:
                await player.toggle()
            self.assertEqual(raised.exception.code, 'engine-down')
        asyncio.run(go())


# What MusicKit sent live when a page played album B while A played (tests/test_mpris.py's
# SEQUENCES has it with the times): it pauses, seeks and stops A as it loads the new queue.
QUEUE_SWAP = [
    ('playbackStateDidChange', {'state': 'paused', 'position': 100, 'duration': 214}),
    ('playbackStateDidChange', {'state': 'seeking', 'position': 100, 'duration': 214}),
    ('playbackStateDidChange', {'state': 'paused', 'position': 100, 'duration': 214}),
    ('nowPlayingItemDidChange', {'track': None, 'index': -1}),
    ('playbackStateDidChange', {'state': 'stopped', 'position': 0, 'duration': 0}),
    ('nowPlayingItemDidChange', {'track': dict(TRACK, id='i.demo0002', index=3), 'index': 3}),
    ('playbackDurationDidChange', {'duration': 180}),
    ('playbackStateDidChange', {'state': 'playing', 'position': 0, 'duration': 180}),
    ('playbackStateDidChange', {'state': 'waiting', 'position': 0, 'duration': 180}),
    ('playbackStateDidChange', {'state': 'loading', 'position': 0, 'duration': 180}),
    ('playbackStateDidChange', {'state': 'playing', 'position': 0, 'duration': 180}),
]


class PendingHoldTest(unittest.TestCase):
    """While a play request is pending, `resting` (and so `active`, `stopped`, the bar and
    MPRIS) holds through the stops MusicKit passes through as it swaps the queue."""

    def setUp(self):
        # A null item waits out its grace (the GLib timeout never runs under asyncio.run):
        # the next item follows it, as it does live.
        self.player, self.engine, self.app = make_player(state='up', grace_ms=10_000)
        self.shown = []  # what a notify::state handler reads
        self.player.connect('notify::state', lambda p, _pspec: self.shown.append(
            (p.resting, p.active, p.stopped)))

    def start(self, state='playing'):
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('playbackStateDidChange', {'state': state, 'position': 10})
        self.shown.clear()

    async def request(self):
        """A play request, held by the engine until the returned gate is set."""
        gate = self.engine.gate('play')
        task = asyncio.ensure_future(self.player.play({'kind': 'album', 'id': 'l.b'}))
        await asyncio.sleep(0)
        self.assertTrue(self.player.pending)
        return gate, task

    def test_the_queue_swap_never_shows_play_or_stopped(self):
        async def go():
            self.start()
            gate, task = await self.request()
            for name, data in QUEUE_SWAP:
                self.engine.event(name, data)
                where = f'{name} {data.get("state", "")}'
                self.assertTrue(self.player.active, where)  # the bar keeps Pause
                self.assertFalse(self.player.stopped, where)  # background playback holds
                self.assertIn(self.player.resting, ACTIVE_STATES, where)
            self.assertEqual(self.player.track.id, 'i.demo0002')
            self.assertEqual(self.player.resting, 'playing')
            self.assertTrue(all(active for _resting, active, _stopped in self.shown))
            count = len(self.shown)
            gate.set()
            await task
            self.assertFalse(self.player.pending)
            self.assertEqual(len(self.shown), count)  # MusicKit's state is what was shown
        asyncio.run(go())

    def test_without_a_request_the_stops_show(self):
        self.start()
        for name, data in QUEUE_SWAP[:5]:
            self.engine.event(name, data)
        self.assertEqual(self.player.resting, 'stopped')
        self.assertFalse(self.player.active)
        self.assertEqual(self.shown[0], ('paused', False, False))

    def test_the_answer_shows_musickits_state_and_tells_the_views(self):
        async def go():
            self.start()
            gate, task = await self.request()
            for name, data in QUEUE_SWAP[:5]:  # up to the stop: MusicKit refused B
                self.engine.event(name, data)
            self.assertEqual((self.player.state, self.player.resting), ('stopped', 'playing'))
            self.engine.fail = EngineError('api', 'refused')
            gate.set()
            with self.assertRaises(EngineError):
                await task
            self.assertFalse(self.player.pending)
            self.assertEqual(self.player.resting, 'stopped')
            self.assertFalse(self.player.active)
            self.assertEqual(self.shown[-1], ('stopped', False, True))  # notified
        asyncio.run(go())

    def test_the_hold_starts_from_the_state_the_request_found(self):
        async def go():
            self.start('paused')
            gate, task = await self.request()
            self.engine.event('playbackStateDidChange', {'state': 'stopped'})
            self.assertEqual(self.player.resting, 'paused')  # not Stopped
            self.engine.event('playbackStateDidChange', {'state': 'loading'})
            self.assertEqual(self.player.resting, 'loading')  # under way shows at once
            self.engine.event('playbackStateDidChange', {'state': 'stopped'})
            self.assertEqual(self.player.resting, 'loading')  # and holds from then on
            self.assertTrue(self.player.active)
            gate.set()
            await task
            self.assertEqual(self.player.resting, 'stopped')
            self.assertEqual(self.shown[-1], ('stopped', False, True))
        asyncio.run(go())

    def test_the_engine_going_down_ends_the_hold_at_once(self):
        async def go():
            self.start()
            gate, task = await self.request()
            self.engine.event('playbackStateDidChange', {'state': 'stopped'})
            self.assertEqual(self.player.resting, 'playing')
            self.engine.state = 'down'
            self.assertEqual(self.player.resting, 'none')
            self.assertTrue(self.player.stopped)
            self.assertEqual(self.shown[-1], ('none', False, True))
            gate.set()
            await task
            self.assertEqual(self.player.resting, 'none')
        asyncio.run(go())


class QueueTest(unittest.TestCase):
    """The queue store and index, from the queue events and the item playing."""

    def setUp(self):
        self.player, self.engine, self.app = make_player()
        self.changes = []
        self.player.queue.connect(
            'items-changed', lambda _s, position, removed, added: self.changes.append(
                (position, removed, added)))

    def ids(self):
        return [entry.id for entry in self.player.queue]

    def test_queue_items_event_fills_the_store(self):
        self.engine.event('queueItemsDidChange', QUEUE)
        self.assertEqual(self.ids(), ['i.demo0003', 'i.demo0002', 'i.demo0001'])
        self.assertEqual([entry.index for entry in self.player.queue], [0, 1, 2])
        self.assertEqual(self.player.queue_index, 2)
        self.assertEqual(self.changes, [(0, 0, 3)])
        # The same snapshot again rebinds nothing; its index is taken.
        self.engine.event('queueItemsDidChange', dict(QUEUE, index=0))
        self.assertEqual(self.changes, [(0, 0, 3)])
        self.assertEqual(self.player.queue_index, 0)
        # The same entries with a title filled in: that entry replaced (its row shows the
        # new title), the others kept.
        renamed = [dict(item) for item in QUEUE['items']]
        renamed[1]['title'] = 'Pilot Light (Live)'
        self.engine.event('queueItemsDidChange', {'index': 0, 'items': renamed})
        self.assertEqual(self.changes, [(0, 0, 3), (1, 1, 1)])
        self.assertEqual(self.player.queue.get_item(1).title, 'Pilot Light (Live)')
        # A shorter queue: what it no longer holds goes, in one splice.
        self.engine.event('queueItemsDidChange', {'index': 0, 'items': QUEUE['items'][:1]})
        self.assertEqual(self.ids(), ['i.demo0003'])
        self.assertEqual(self.changes, [(0, 0, 3), (1, 1, 1), (1, 2, 0)])

    def test_an_identical_snapshot_makes_no_objects(self):
        self.engine.event('queueItemsDidChange', QUEUE)
        entries = list(self.player.queue)
        with mock.patch('applemusic.player.NowPlaying', side_effect=AssertionError('made')):
            self.engine.event('queueItemsDidChange', dict(QUEUE, index=1))
        self.assertEqual(list(self.player.queue), entries)  # the same objects
        self.assertEqual(self.player.queue_index, 1)

    def test_index_before_playback_is_the_tracks_place(self):
        self.engine.event('nowPlayingItemDidChange', {'track': QUEUE['items'][1], 'index': 1})
        self.engine.event('queueItemsDidChange', dict(QUEUE, index=-1))
        self.assertEqual(self.player.queue_index, 1)

    def test_queue_position_event_moves_the_index(self):
        self.engine.event('queueItemsDidChange', QUEUE)
        self.engine.event('queuePositionDidChange', {'index': 1, 'oldIndex': 2})
        self.assertEqual(self.player.queue_index, 1)
        self.engine.event('queuePositionDidChange', {'index': 7, 'oldIndex': 1})
        self.assertEqual(self.player.queue_index, -1)  # nowhere in the queue held
        self.engine.event('queuePositionDidChange', {'index': None})
        self.assertEqual(self.player.queue_index, -1)

    def test_a_queued_item_playing_points_the_index_without_a_read(self):
        self.engine.event('queueItemsDidChange', dict(QUEUE, index=-1))
        self.app.spawned.clear()
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertEqual(self.player.queue_index, 2)
        self.assertNotIn('Player.refresh_queue', self.app.spawned)
        # At another index than its own: found by id.
        moved = dict(TRACK, index=5)
        self.engine.event('nowPlayingItemDidChange', {'track': moved, 'index': 5})
        self.assertEqual(self.player.queue_index, 2)
        self.assertNotIn('Player.refresh_queue', self.app.spawned)

    def test_an_item_not_in_the_queue_reads_it_again(self):
        self.engine.event('queueItemsDidChange', QUEUE)
        self.app.spawned.clear()
        stranger = dict(TRACK, id='i.demo0009', catalogId='1000000009', index=0)
        self.engine.event('nowPlayingItemDidChange', {'track': stranger, 'index': 0})
        self.assertEqual(self.player.queue_index, -1)
        self.assertEqual(self.app.spawned.count('Player.refresh_queue'), 1)

    def test_no_item_clears_the_index_and_keeps_the_entries(self):
        self.engine.event('queueItemsDidChange', QUEUE)
        self.engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.assertEqual(self.player.queue_index, -1)
        self.assertEqual(len(self.ids()), 3)

    def test_refresh_queue_reads_the_engine(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.answers['queue'] = QUEUE
            await player.refresh_queue()
            self.assertEqual([entry.title for entry in player.queue],
                             ['Shoreline', 'Pilot Light', 'Harbour Lights'])
            self.assertEqual(player.queue_index, 2)
            engine.fail = EngineError('engine-down', 'gone')
            await player.refresh_queue()  # logged, the queue kept
            self.assertEqual(player.queue.get_n_items(), 3)
        asyncio.run(go())

    def test_a_queue_event_during_the_read_wins(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            gate = engine.gate('queue')
            engine.answers['queue'] = {'index': 0, 'items': QUEUE['items'][:1]}
            task = app.spawn(player.refresh_queue())
            await asyncio.sleep(0)
            engine.event('queueItemsDidChange', QUEUE)  # newer than the answer
            gate.set()
            await task
            self.assertEqual(self.ids_of(player), ['i.demo0003', 'i.demo0002', 'i.demo0001'])
        asyncio.run(go())

    @staticmethod
    def ids_of(player):
        return [entry.id for entry in player.queue]

    def test_apply_takes_a_queue_and_bad_snapshots(self):
        self.player.apply({'track': TRACK, 'queue': QUEUE})
        self.assertEqual(self.player.queue_index, 2)
        self.player.apply_queue({'index': 0, 'items': 'nonsense'})
        self.assertEqual(self.player.queue.get_n_items(), 0)
        self.player.apply_queue(None)
        self.assertEqual(self.player.queue_index, -1)


class LyricsTest(unittest.TestCase):
    """Lyrics read once per catalog song as it starts, from the engine."""

    def test_a_new_item_asks_the_engine_once(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.answers['lyrics'] = LYRICS
            loading = []
            player.connect('notify::lyrics-loading',
                           lambda p, _pspec: loading.append(p.lyrics_loading))
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            self.assertTrue(player.lyrics_loading)
            self.assertIsNone(player.lyrics)
            await app.settle()
            # The item is not in the (empty) queue, so the queue is read as well.
            self.assertEqual(engine.calls, [('now_playing',), ('set_autoplay', True),
                                            ('queue',), ('lyrics', '1000000001')])
            self.assertIsInstance(player.lyrics, Lyrics)
            self.assertEqual(player.lyrics.catalog_id, '1000000001')
            self.assertEqual(len(player.lyrics), 2)
            self.assertEqual(loading, [True, False])
            # The same song again (repeat one): kept, not asked again.
            engine.event('nowPlayingItemDidChange', {'track': dict(TRACK, index=3), 'index': 3})
            await app.settle()
            self.assertEqual(engine.calls.count(('lyrics', '1000000001')), 1)
            self.assertIsNotNone(player.lyrics)
            # Another song: asked; none for it: None.
            engine.answers['lyrics'] = {'synced': False, 'lines': []}
            other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=0)
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
            self.assertIsNone(player.lyrics)
            await app.settle()
            self.assertEqual(engine.calls[-1], ('lyrics', '1000000002'))
            self.assertIsNone(player.lyrics)
            self.assertFalse(player.lyrics_loading)
            # Nothing playing: nothing asked, nothing loading.
            engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
            await app.settle()
            self.assertIsNone(player.lyrics)
            self.assertFalse(player.lyrics_loading)
        asyncio.run(go())

    def test_an_answer_for_a_song_no_longer_playing_is_dropped(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.answers['lyrics'] = LYRICS
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=0)
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
            await app.settle()
            self.assertEqual(player.lyrics.catalog_id, '1000000002')
            self.assertFalse(player.lyrics_loading)
        asyncio.run(go())

    def test_a_late_answer_for_the_song_before_is_dropped(self):
        """A → B while A's read is still out: A's task is cancelled and B's answer is what
        shows; A → B → A: A's lyrics end up shown once, with one read out at a time."""
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            gate = engine.gate('lyrics')
            engine.answers['lyrics'] = LYRICS
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await asyncio.sleep(0)
            first = player._lyrics_task
            other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=0)
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
            await asyncio.sleep(0)
            self.assertTrue(first.cancelled() or first.done())
            gate.set()
            await app.settle()
            self.assertEqual(player.lyrics.catalog_id, '1000000002')
            self.assertFalse(player.lyrics_loading)
            # Back to A while B's read is out, then A's answer: shown once.
            gate.clear()
            shown = []
            player.connect('notify::lyrics', lambda p, _pspec: shown.append(
                p.lyrics.catalog_id if p.lyrics is not None else None))
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await asyncio.sleep(0)
            gate.set()
            await app.settle()
            self.assertEqual(player.lyrics.catalog_id, '1000000001')
            self.assertEqual(shown, [None, '1000000001'])  # cleared once, then A's once
            self.assertFalse(player.lyrics_loading)
        asyncio.run(go())

    def test_a_null_item_or_the_engine_going_clears_the_lyrics(self):
        """Lyrics shown, or being read: a null item (and the engine going down) clears the
        lyrics, the loading flag and the read under way."""
        async def go():
            for how in ('null', 'down'):
                player, engine, app = make_player(state='up')
                await app.settle()
                gate = engine.gate('lyrics')
                engine.answers['lyrics'] = LYRICS
                engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
                await asyncio.sleep(0)
                task = player._lyrics_task
                self.assertTrue(player.lyrics_loading)
                if how == 'null':
                    engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
                else:
                    engine.state = 'down'
                self.assertIsNone(player.lyrics, how)
                self.assertFalse(player.lyrics_loading, how)
                gate.set()
                await app.settle()
                self.assertTrue(task.cancelled(), how)
                self.assertIsNone(player.lyrics, how)
                # Shown, then gone the same way.
                engine.state = 'up'
                await app.settle()
                engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
                await app.settle()
                self.assertIsNotNone(player.lyrics, how)
                if how == 'null':
                    engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
                else:
                    engine.state = 'down'
                self.assertIsNone(player.lyrics, how)
                self.assertFalse(player.lyrics_loading, how)
        asyncio.run(go())

    def test_engine_failure_means_no_lyrics(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.fail = EngineError('engine-down', 'gone')
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertIsNone(player.lyrics)
            self.assertFalse(player.lyrics_loading)
        asyncio.run(go())

    def test_an_item_without_a_catalog_id_asks_nothing(self):
        player, engine, app = make_player()
        engine.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, catalogId=None), 'index': 0})
        self.assertNotIn('Player._load_lyrics', app.spawned)
        self.assertFalse(player.lyrics_loading)

    def test_apply_with_lyrics_takes_them_as_they_are(self):
        player, engine, app = make_player()
        player.apply({'track': TRACK, 'lyrics': LYRICS})
        self.assertNotIn('Player._load_lyrics', app.spawned)
        self.assertEqual(player.lyrics.catalog_id, '1000000001')
        self.assertTrue(player.lyrics.synced)
        self.assertFalse(player.lyrics_loading)


# An invented session as session.read() gives it: QUEUE's three songs, the third paused 83 s
# in, from an album that still is the queue.
SESSION = {
    'queue': [{key: value for key, value in entry.items() if key != 'index'}
              for entry in QUEUE['items']],
    'index': 2, 'offset': 0, 'position': 83.0, 'duration': 214.0, 'repeat': 'all',
    'source': {'kind': 'album', 'id': 'l.alb1'},
}


def session(**changes):
    return dict(SESSION, **changes)


class RestoreTest(unittest.TestCase):
    """The last session shown paused (restore), held while MusicKit holds nothing, changed
    locally, and handed to MusicKit by Play (restore_session)."""

    def restored(self, state='down', **changes):
        player, engine, app = make_player(state=state)
        self.assertTrue(player.restore(session(**changes)))
        return player, engine, app

    def test_restore_shows_the_item_paused(self):
        player, engine, app = self.restored()
        self.assertTrue(player.restored)
        self.assertEqual(player.track.id, 'i.demo0001')
        self.assertEqual(player.queue_index, 2)
        self.assertEqual([entry.title for entry in player.queue],
                         ['Shoreline', 'Pilot Light', 'Harbour Lights'])
        self.assertEqual(player.state, 'paused')
        self.assertFalse(player.active)
        self.assertFalse(player.stopped)
        self.assertEqual(player.position, 83.0)
        self.assertEqual(player.duration, 214.0)
        self.assertEqual(player.repeat, 'all')
        self.assertFalse(player.shuffle)  # the queue comes back in its order
        self.assertEqual(player.source, {'kind': 'album', 'id': 'l.alb1'})
        self.assertEqual(engine.calls, [])  # nothing asked of the engine for it
        self.assertEqual(app.spawned, ['Player._load_lyrics'])  # the lyrics from the cache

    def test_restore_takes_nothing_over_an_item_or_a_bad_session(self):
        player, engine, app = make_player()
        player.apply({'track': TRACK, 'state': 'playing'})
        self.assertFalse(player.restore(session()))
        self.assertFalse(player.restored)
        player, engine, app = make_player()
        for bad in (None, session(queue=[]), session(index=3), session(index=-1)):
            self.assertFalse(player.restore(bad))
        self.assertIsNone(player.track)

    def test_musickit_holding_nothing_changes_nothing(self):
        player, engine, app = self.restored(state='up')
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': 0})
        engine.event('playbackStateDidChange', {'state': 'none', 'position': 0})
        engine.event('playbackTimeDidChange', {'position': 0, 'duration': 0})
        engine.event('queueItemsDidChange', {'index': 0, 'items': []})
        engine.event('shuffleModeDidChange', {'shuffle': 'on'})
        engine.event('repeatModeDidChange', {'repeat': 'none'})
        engine.event('bridgeReset', {})
        engine.event('playbackVolumeDidChange', {'volume': 0.4})
        engine.state = 'down'
        engine.state = 'up'
        self.assertTrue(player.restored)
        self.assertEqual((player.track.id, player.state, player.position, player.repeat,
                          player.shuffle, player.queue.get_n_items()),
                         ('i.demo0001', 'paused', 83.0, 'all', False, 3))
        self.assertEqual(player.volume, 0.4)  # MusicKit's own, whatever it holds

    def test_the_engine_coming_up_empty_keeps_it(self):
        async def go():
            player, engine, app = self.restored()
            engine.answers['now_playing'] = {'state': 'none', 'track': None, 'position': 0,
                                             'shuffle': 'on', 'repeat': 'none', 'volume': 0.5}
            await player.refresh()
            self.assertTrue(player.restored)
            self.assertEqual((player.track.id, player.repeat, player.shuffle, player.volume),
                             ('i.demo0001', 'all', False, 0.5))
        asyncio.run(go())

    def test_musickit_playing_something_of_its_own_ends_it(self):
        player, engine, app = self.restored(state='up')
        other = dict(TRACK, id='i.demo0009', title='Elsewhere', index=0)
        engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
        self.assertFalse(player.restored)
        self.assertEqual(player.track.id, 'i.demo0009')
        player, engine, app = self.restored(state='up')
        engine.event('queueItemsDidChange', {'index': 0, 'items': [other]})
        self.assertFalse(player.restored)

    def test_seek_next_and_previous_are_local_and_paused(self):
        async def go():
            player, engine, app = self.restored()
            await player.seek(120)
            self.assertEqual(player.position, 120.0)
            await player.seek(999)
            self.assertEqual(player.position, 214.0)  # no further than its end
            await player.previous()  # more than a few seconds in: back to the top
            self.assertEqual((player.queue_index, player.position), (2, 0.0))
            await player.previous()
            self.assertEqual((player.track.title, player.queue_index, player.position),
                             ('Pilot Light', 1, 0.0))
            await player.next()
            self.assertEqual(player.track.title, 'Harbour Lights')
            await player.next()  # the end of the queue: nothing further
            self.assertEqual(player.queue_index, 2)
            await player.seek(30)
            await player.stop()  # MPRIS Stop: back to the top, still paused
            self.assertEqual(player.position, 0.0)
            await player.pause()
            self.assertEqual(player.state, 'paused')
            self.assertTrue(player.restored)
            self.assertEqual(engine.calls, [])
        asyncio.run(go())

    def test_shuffle_repeat_and_volume_wait_for_the_play(self):
        async def go():
            player, engine, app = self.restored()
            await player.set_repeat('one')
            await player.set_shuffle(True)
            self.assertEqual(await player.set_volume(0.3), 0.3)
            self.assertEqual((player.repeat, player.shuffle, player.volume), ('one', True, 0.3))
            self.assertEqual(engine.calls, [])
            await player.toggle()
            self.assertEqual([call[0] for call in engine.calls],
                             ['start', 'repeat', 'volume', 'play', 'shuffle'])
            self.assertEqual(engine.calls[1], ('repeat', 'one'))
            self.assertEqual(engine.calls[2], ('volume', 0.3))
            self.assertEqual(engine.calls[3], ('play', 'album', 'l.alb1', 2, False))
            self.assertEqual(engine.calls[4], ('shuffle', 'on'))  # what follows, shuffled
        asyncio.run(go())

    def test_play_hands_the_source_to_musickit_at_the_position(self):
        async def go():
            player, engine, app = self.restored(offset=40)
            pending = []
            player.connect('notify::pending', lambda p, _pspec: pending.append(
                (p.pending, p.resting, p.restored)))
            await player.toggle()
            self.assertEqual(engine.calls[0], ('start', None))  # the engine started for it
            self.assertEqual(app.toasts, ['Starting playback engine…'])
            self.assertEqual(engine.calls[-1], ('play', 'album', 'l.alb1', 42, False))
            self.assertEqual(engine.play_options,
                             [{'start_id': 'i.demo0001', 'start_time': 83.0}])
            self.assertFalse(player.restored)
            # Pending from the request on, paused held meanwhile; MusicKit's from the play.
            self.assertEqual(pending, [(True, 'paused', True), (False, 'paused', False)])
        asyncio.run(go())

    def test_without_a_source_the_songs_are_queued_by_id(self):
        async def go():
            video = dict(QUEUE['items'][1], id='i.video1', type='library-music-videos')
            queue = [SESSION['queue'][0], video, SESSION['queue'][2]]
            player, engine, app = self.restored(state='up', source=None, queue=queue)
            await player.resume()
            # The music video is left out: the item is the second of the songs.
            self.assertEqual(engine.calls[-1],
                             ('play', 'songs', 'i.demo0003,i.demo0001', 1, False))
            self.assertEqual(engine.play_options[-1]['start_id'], 'i.demo0001')
        asyncio.run(go())

    def test_a_video_item_plays_alone_and_a_station_live(self):
        async def go():
            video = dict(SESSION['queue'][2], type='music-videos', catalogId='1000000009')
            player, engine, app = self.restored(state='up', source=None, queue=[video],
                                                index=0)
            await player.resume()
            self.assertEqual(engine.calls[-1], ('play', 'musicVideo', '1000000009', None, False))
            self.assertEqual(engine.play_options[-1]['start_time'], 83.0)
            player, engine, app = self.restored(state='up', index=0, position=0.0,
                                                source={'kind': 'station', 'id': 'ra.1'},
                                                queue=[SESSION['queue'][2]])
            await player.resume()
            self.assertEqual(engine.calls[-1], ('play', 'station', 'ra.1', None, False))
            self.assertEqual(engine.play_options[-1], {'start_id': None})  # live: no position
        asyncio.run(go())

    def test_an_item_that_ended_starts_from_the_top(self):
        async def go():
            player, engine, app = self.restored(state='up', position=213.5)
            await player.resume()
            self.assertEqual(engine.play_options[-1], {'start_id': 'i.demo0001'})
        asyncio.run(go())

    def test_an_up_next_row_plays_that_entry_from_the_top(self):
        async def go():
            player, engine, app = self.restored(state='up')
            await player.queue_jump(0)
            self.assertEqual(engine.calls[-1], ('play', 'album', 'l.alb1', 0, False))
            self.assertEqual(engine.play_options[-1], {'start_id': 'i.demo0003'})
        asyncio.run(go())

    def test_play_next_queues_the_session_paused_first(self):
        async def go():
            player, engine, app = self.restored(state='up')
            await player.play_next('song', '1000000005')
            self.assertEqual([call[0] for call in engine.calls], ['repeat', 'play', 'play_next'])
            self.assertEqual(engine.play_options[-1],
                             {'start_id': 'i.demo0001', 'start_time': 83.0, 'paused': True})
            await player.play_later('song', '1000000006')  # MusicKit has it now
            self.assertEqual(engine.calls[-1], ('play_later', 'song', '1000000006'))
            self.assertEqual(len(engine.play_options), 1)
        asyncio.run(go())

    def test_another_play_replaces_the_session(self):
        async def go():
            player, engine, app = self.restored(state='up')
            await player.play({'kind': 'playlist', 'id': 'p.pl1'}, shuffle=False)
            self.assertFalse(player.restored)
            self.assertEqual(engine.calls, [('play', 'playlist', 'p.pl1', None, False)])
            self.assertEqual(engine.play_options, [{'start_id': None}])
        asyncio.run(go())

    def test_a_failed_start_or_sign_in_gives_the_session_back(self):
        async def go():
            for error in (EngineError('engine-down', 'no Chrome'),
                          EngineError('not-signed-in', 'expired'),
                          EngineError('no-widevine', 'no module')):
                player, engine, app = self.restored(state='up')
                engine.fail = error
                with self.assertRaises(EngineError):
                    await player.toggle()
                self.assertTrue(player.restored, error.code)
                self.assertEqual((player.track.id, player.state, player.position,
                                  player.queue.get_n_items()),
                                 ('i.demo0001', 'paused', 83.0, 3))
                self.assertFalse(player.pending)
        asyncio.run(go())

    def test_signed_out_the_session_stays(self):
        async def go():
            player, engine, app = make_player(signed_in=False)
            player.restore(session())
            with self.assertRaises(EngineError) as raised:
                await player.toggle()
            self.assertEqual(raised.exception.code, 'not-signed-in')
            self.assertTrue(player.restored)
        asyncio.run(go())

    def test_the_engines_empty_answer_as_it_starts_for_the_play_wipes_nothing(self):
        async def go():
            player, engine, app = self.restored()
            read = engine.gate('now_playing')  # the read the engine coming up makes
            play = engine.gate('play')
            engine.answers['now_playing'] = {'state': 'none', 'track': None, 'volume': 0.5}
            task = asyncio.ensure_future(player.toggle())
            for _ in range(5):
                await asyncio.sleep(0)
            self.assertFalse(player.restored)
            self.assertTrue(player.pending)
            read.set()  # MusicKit answers before it has the queue: nothing
            for _ in range(5):
                await asyncio.sleep(0)
            self.assertEqual(player.track.id, 'i.demo0001')  # older than the request
            self.assertEqual(player.volume, 0.5)
            play.set()
            await task
            await app.settle()
            self.assertEqual(player.track.id, 'i.demo0001')
        asyncio.run(go())

    def test_a_failed_other_play_gives_the_session_back_too(self):
        async def go():
            player, engine, app = self.restored(state='up')
            engine.fail = EngineError('api', 'play album: refused',
                                      musickit_code='CONTENT_UNAVAILABLE')
            with self.assertRaises(EngineError):
                await player.play({'kind': 'album', 'id': 'l.other'})
            self.assertTrue(player.restored)  # the session was not what MusicKit refused
            self.assertEqual(player.source, {'kind': 'album', 'id': 'l.alb1'})
        asyncio.run(go())

    def test_musickit_refusing_the_session_drops_it(self):
        async def go():
            player, engine, app = self.restored(state='up')
            dropped, errors = [], []
            player.connect('session-dropped', lambda _p: dropped.append(True))
            player.connect('error', lambda _p, message: errors.append(message))
            engine.fail = EngineError('api', 'play album: refused',
                                      musickit_code='CONTENT_UNAVAILABLE')
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()  # answered, not raised: the toast is the error signal
            self.assertFalse(player.restored)
            self.assertIsNone(player.track)
            self.assertEqual(player.queue.get_n_items(), 0)
            self.assertEqual(dropped, [True])
            self.assertEqual(errors, [playback_error_text('CONTENT_UNAVAILABLE')])
        asyncio.run(go())

    def not_found(self, *ids):
        """MusicKit refusing a queue by ids as it does when one cannot be resolved."""
        return EngineError('api', 'play songs: [mk-007] NOT_FOUND; One or more items could '
                                  f'not be resolved: {", ".join(ids)}',
                           musickit_code='NOT_FOUND')

    def plays(self, engine):
        return [call for call in engine.calls if call[0] == 'play']

    def test_a_song_musickit_cannot_find_is_left_out_and_the_rest_plays(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None)
            dropped = []
            player.connect('session-dropped', lambda _p: dropped.append(True))
            engine.play_failures = [self.not_found('i.demo0002')]
            engine.answers['songs_found'] = ['i.demo0003', 'i.demo0001']
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertEqual(self.plays(engine), [
                ('play', 'songs', 'i.demo0003,i.demo0002,i.demo0001', 2, False),
                ('play', 'songs', 'i.demo0003,i.demo0001', 1, False)])
            self.assertIn(('songs_found', ['i.demo0003', 'i.demo0002', 'i.demo0001']),
                          engine.calls)
            # The same item, where it was.
            self.assertEqual(engine.play_options[-1],
                             {'start_id': 'i.demo0001', 'start_time': 83.0})
            self.assertEqual(dropped, [])
            self.assertFalse(player.restored)  # MusicKit has it
        asyncio.run(go())

    def test_the_songs_missing_are_found_by_a_read_when_musickit_names_none(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None, index=0)
            engine.play_failures = [self.not_found()]
            engine.answers['songs_found'] = ['i.demo0003', 'i.demo0001']
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertEqual(engine.calls[-1], ('play', 'songs', 'i.demo0003,i.demo0001', 0,
                                                False))
        asyncio.run(go())

    def test_the_songs_musickit_names_are_left_out_when_the_read_fails(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None)
            engine.play_failures = [self.not_found('i.demo0003')]
            original = engine.songs_found

            async def failing(song_ids):
                await original(song_ids)
                raise EngineError('timeout', 'no answer')
            engine.songs_found = failing
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.restore_session(paused=True)
            self.assertEqual(engine.calls[-1], ('play', 'songs', 'i.demo0002,i.demo0001', 1,
                                                False))
            self.assertTrue(engine.play_options[-1]['paused'])
        asyncio.run(go())

    def test_the_item_itself_gone_drops_the_session(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None)
            dropped = []
            player.connect('session-dropped', lambda _p: dropped.append(True))
            engine.play_failures = [self.not_found('i.demo0001')]
            engine.answers['songs_found'] = ['i.demo0003', 'i.demo0002']
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertEqual(len(self.plays(engine)), 1)
            self.assertEqual(dropped, [True])
            self.assertIsNone(player.track)
        asyncio.run(go())

    def test_a_second_refusal_drops_the_session(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None)
            dropped = []
            player.connect('session-dropped', lambda _p: dropped.append(True))
            engine.play_failures = [self.not_found('i.demo0002'), self.not_found('i.demo0003')]
            engine.answers['songs_found'] = ['i.demo0003', 'i.demo0001']
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertEqual(len(self.plays(engine)), 2)
            self.assertEqual(dropped, [True])
        asyncio.run(go())

    def test_nothing_missing_found_drops_the_session_at_once(self):
        async def go():
            player, engine, app = self.restored(state='up', source=None)
            dropped = []
            player.connect('session-dropped', lambda _p: dropped.append(True))
            engine.play_failures = [self.not_found()]  # names none, and the read finds all
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertEqual(len(self.plays(engine)), 1)
            self.assertEqual(dropped, [True])
        asyncio.run(go())

    def test_a_source_refused_is_not_tried_by_ids(self):
        async def go():
            player, engine, app = self.restored(state='up')
            engine.play_failures = [self.not_found('l.alb1')]
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.toggle()
            self.assertNotIn('songs_found', [call[0] for call in engine.calls])
            self.assertEqual(len(self.plays(engine)), 1)
        asyncio.run(go())

    def test_an_item_of_musickits_during_a_failed_request_is_kept(self):
        async def go():
            player, engine, app = self.restored(state='up')
            gate = engine.gate('play')
            task = asyncio.ensure_future(player.toggle())
            await asyncio.sleep(0)
            other = dict(TRACK, id='i.demo0009', title='Elsewhere', index=0)
            engine.event('nowPlayingItemDidChange', {'track': other, 'index': 0})
            engine.fail = EngineError('engine-down', 'the page went')
            gate.set()
            with self.assertRaises(EngineError):
                await task
            self.assertFalse(player.restored)  # MusicKit's item shows: it is what plays
        asyncio.run(go())

    @staticmethod
    def slow_start(engine, fail=None):
        """engine.start() held, the engine 'starting', until the returned event is set; then
        up, or down and raising `fail`."""
        started = asyncio.Event()

        async def start(visible=None):
            engine.calls.append(('start', visible))
            engine.state = 'starting'
            await started.wait()
            engine.state = 'down' if fail else 'up'
            if fail:
                raise fail
        engine.start = start
        return started

    @staticmethod
    async def turns(count=5):
        for _ in range(count):
            await asyncio.sleep(0)

    @staticmethod
    def sent(engine, *names):
        names = names or ('play',)
        return [call for call in engine.calls if call[0] in names]

    def test_a_second_play_during_the_engines_start_sends_one_play(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            first = asyncio.ensure_future(player.toggle())
            await self.turns()
            self.assertTrue(player.pending)
            self.assertTrue(player.restored)  # shown as it is until the play goes out
            second = asyncio.ensure_future(player.toggle())  # Space again, MPRIS PlayPause
            third = asyncio.ensure_future(player.resume())
            await self.turns()
            self.assertEqual(self.sent(engine, 'play', 'control'), [])
            started.set()
            await asyncio.gather(first, second, third)
            await app.settle()
            self.assertEqual(self.sent(engine, 'play', 'control', 'start'),
                             [('start', None), ('play', 'album', 'l.alb1', 2, False)])
            self.assertEqual(engine.play_options,
                             [{'start_id': 'i.demo0001', 'start_time': 83.0}])
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_steps_during_the_engines_start_play_the_entry_shown(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            await player.seek(0)
            await player.previous()
            await player.seek(30)
            self.assertEqual((player.track.title, player.queue_index, player.position),
                             ('Pilot Light', 1, 30.0))
            started.set()
            await task
            await app.settle()
            self.assertEqual(self.sent(engine), [('play', 'album', 'l.alb1', 1, False)])
            self.assertEqual(engine.play_options,
                             [{'start_id': 'i.demo0002', 'start_time': 30.0}])
        asyncio.run(go())

    def test_an_up_next_row_during_the_engines_start_is_the_one_that_plays(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            row = asyncio.ensure_future(player.queue_jump(0))
            await self.turns()
            self.assertEqual((player.track.title, player.position), ('Shoreline', 0.0))
            started.set()
            await asyncio.gather(task, row)
            self.assertEqual(self.sent(engine), [('play', 'album', 'l.alb1', 0, False)])
            self.assertEqual(engine.play_options, [{'start_id': 'i.demo0003'}])
        asyncio.run(go())

    def test_play_next_during_the_engines_start_goes_after_the_play(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            queued = asyncio.ensure_future(player.play_next('song', '1000000005'))
            await self.turns()
            started.set()
            await asyncio.gather(task, queued)
            self.assertEqual(self.sent(engine, 'play', 'play_next'),
                             [('play', 'album', 'l.alb1', 2, False),
                              ('play_next', 'song', '1000000005')])
            self.assertEqual(engine.play_options,  # the Play's, not paused
                             [{'start_id': 'i.demo0001', 'start_time': 83.0}])
        asyncio.run(go())

    def test_a_play_during_a_paused_restore_plays_it(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            queued = asyncio.ensure_future(player.play_next('song', '1000000005'))
            await self.turns()
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            started.set()
            await asyncio.gather(task, queued)
            self.assertEqual(self.sent(engine, 'play', 'play_next'),
                             [('play', 'album', 'l.alb1', 2, False),
                              ('play_next', 'song', '1000000005')])
            self.assertEqual(engine.play_options,
                             [{'start_id': 'i.demo0001', 'start_time': 83.0}])
        asyncio.run(go())

    def test_another_play_during_the_engines_start_replaces_the_session(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            other = asyncio.ensure_future(player.play({'kind': 'playlist', 'id': 'p.pl1'},
                                                      shuffle=False))
            await self.turns()
            started.set()
            await asyncio.gather(task, other)
            self.assertEqual(self.sent(engine), [('play', 'playlist', 'p.pl1', None, False)])
            self.assertFalse(player.restored)
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_a_failed_start_keeps_the_session_and_takes_a_play_again(self):
        async def go():
            player, engine, app = self.restored()
            started = self.slow_start(engine, EngineError('engine-down', 'no Chrome'))
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            second = asyncio.ensure_future(player.toggle())
            await self.turns()
            started.set()
            with self.assertRaises(EngineError):
                await task
            await second  # the start's failure is the first press's to report
            self.assertTrue(player.restored)
            self.assertEqual((player.track.id, player.position), ('i.demo0001', 83.0))
            self.assertFalse(player.pending)
            self.assertEqual(self.sent(engine), [])
            del engine.start  # the FakeEngine's own: up at once
            await player.toggle()
            self.assertEqual(self.sent(engine), [('play', 'album', 'l.alb1', 2, False)])
        asyncio.run(go())

    @staticmethod
    def autostarting(engine, fail=None):
        """The app's autostart under way at launch: the engine 'starting' already, a start()
        meanwhile joining it and every command waiting for it (the Engine's _ready()), until
        the returned event is set; then up, or down with `fail` raised to the joined starts
        and the commands."""
        started = asyncio.Event()
        engine.state = 'starting'

        async def start(visible=None):
            engine.calls.append(('start', visible))
            await started.wait()
            if fail:
                raise fail

        async def autostart():
            await started.wait()
            engine.state = 'down' if fail else 'up'
            if fail:
                engine.fail = fail
        engine.start = start
        for name in ('play', 'control', 'repeat', 'volume', 'shuffle', 'seek', 'queue_jump'):
            engine.gates[name] = started
        return started, asyncio.ensure_future(autostart())

    def test_a_step_during_the_autostart_plays_the_entry_shown(self):
        async def go():
            player, engine, app = self.restored(index=1)
            started, autostart = self.autostarting(engine)
            first = asyncio.ensure_future(player.toggle())
            await self.turns()
            self.assertTrue(player.pending)
            self.assertTrue(player.restored)  # shown as it is until the play goes out
            steps = [asyncio.ensure_future(player.next()),
                     asyncio.ensure_future(player.toggle())]
            await self.turns()
            self.assertEqual((player.track.title, player.queue_index, player.position),
                             ('Harbour Lights', 2, 0.0))
            started.set()
            await asyncio.gather(autostart, first, *steps)
            await app.settle()
            self.assertEqual(self.sent(engine, 'play', 'control'),
                             [('play', 'album', 'l.alb1', 2, False)])
            self.assertEqual(engine.play_options, [{'start_id': 'i.demo0001'}])
            self.assertFalse(player.restored)
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_a_seek_or_an_up_next_row_during_the_autostart_is_what_plays(self):
        async def go():
            player, engine, app = self.restored()
            started, autostart = self.autostarting(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            steps = [asyncio.ensure_future(player.seek(0))]
            await self.turns()
            steps.append(asyncio.ensure_future(player.previous()))  # the item before
            await self.turns()
            steps.append(asyncio.ensure_future(player.seek(30)))
            await self.turns()
            self.assertEqual((player.track.title, player.position), ('Pilot Light', 30.0))
            steps.append(asyncio.ensure_future(player.queue_jump(0)))
            await self.turns()
            started.set()
            await asyncio.gather(autostart, task, *steps)
            self.assertEqual(self.sent(engine, 'play', 'control', 'seek', 'queue_jump'),
                             [('play', 'album', 'l.alb1', 0, False)])
            self.assertEqual(engine.play_options, [{'start_id': 'i.demo0003'}])
        asyncio.run(go())

    def test_another_play_during_the_autostart_replaces_the_session(self):
        async def go():
            player, engine, app = self.restored()
            started, autostart = self.autostarting(engine)
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            other = asyncio.ensure_future(player.play({'kind': 'playlist', 'id': 'p.pl1'},
                                                      shuffle=False))
            await self.turns()
            started.set()
            await asyncio.gather(autostart, task, other)
            self.assertEqual(self.sent(engine), [('play', 'playlist', 'p.pl1', None, False)])
            self.assertFalse(player.restored)
        asyncio.run(go())

    def test_a_failed_autostart_keeps_the_session(self):
        async def go():
            player, engine, app = self.restored()
            started, autostart = self.autostarting(
                engine, EngineError('engine-down', 'no Chrome'))
            task = asyncio.ensure_future(player.toggle())
            await self.turns()
            steps = [asyncio.ensure_future(player.next())]  # past the end: the item stays
            await self.turns()
            steps.append(asyncio.ensure_future(player.seek(40)))
            await self.turns()
            started.set()
            await autostart
            with self.assertRaises(EngineError):
                await task
            await asyncio.gather(*steps)
            self.assertTrue(player.restored)
            self.assertEqual((player.track.id, player.position), ('i.demo0001', 40.0))
            self.assertEqual(self.sent(engine, 'play', 'control', 'seek'), [])
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_a_reloaded_page_gets_the_autoplay_setting_while_restored(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.event('autoplayEnabledDidChange', {'autoplay': True})  # the page's own
            self.assertTrue(player.restore(session()))
            app.settings.autoplay = False  # the app's setting differs from the page's
            engine.calls.clear()
            engine.event('bridgeReset', {})  # the new page set its own as it loaded
            await app.settle()
            self.assertIn(('set_autoplay', False), engine.calls)
            self.assertFalse(player.autoplay)  # MusicKit's answer: the setting's
            self.assertNotIn(('now_playing',), engine.calls)  # the session stays as it is
            self.assertTrue(player.restored)
            self.assertEqual((player.track.id, player.position), ('i.demo0001', 83.0))
        asyncio.run(go())

    def test_musickits_autoplay_is_taken_while_restored(self):
        player, engine, app = self.restored(state='up')
        self.assertFalse(player.autoplay)
        engine.event('autoplayEnabledDidChange', {'autoplay': True})
        self.assertTrue(player.autoplay)
        self.assertTrue(player.restored)
        engine.event('autoplayEnabledDidChange', {'autoplay': False})
        self.assertFalse(player.autoplay)

    def test_forget_session(self):
        player, engine, app = self.restored()
        player.forget_session()
        self.assertFalse(player.restored)
        self.assertIsNone(player.track)
        self.assertIsNone(player.source)
        player, engine, app = make_player(state='up')
        player.apply({'track': TRACK, 'state': 'playing'})
        player.forget_session()  # MusicKit's own: the engine's to stop
        self.assertIsNotNone(player.track)


def not_found(*ids):
    """MusicKit refusing a list of songs because some cannot be resolved, as seen live."""
    return EngineError('api', 'play songs: [mk-007] NOT_FOUND; One or more items could not '
                              f'be resolved: {", ".join(ids)}', musickit_code='NOT_FOUND')


class SongListTest(unittest.TestCase):
    """A list of songs by id that MusicKit refuses whole because some of them cannot be
    found: played (or queued) once more without them, in order, from the song asked for or
    the next one found, with one toast; never a third time. Each way into such a list: the
    Songs page's Play and Shuffle, the library artist page's Play, a shelf of songs from the
    one clicked, a selection's Play Next and Play Later."""

    @staticmethod
    def refusing(engine, *missing):
        """The engine refusing any list of songs that holds one of `missing`, as MusicKit
        does (NOT_FOUND, the songs named), and Apple's read by id not finding them."""
        missing = set(missing)

        def check(kind, item_id):
            gone = [song_id for song_id in item_id.split(',') if song_id in missing]
            if kind == 'songs' and gone:
                raise not_found(*gone)

        play, play_next, play_later = engine.play, engine.play_next, engine.play_later

        async def refusing_play(kind, item_id, *args, **options):
            await play(kind, item_id, *args, **options)
            check(kind, item_id)

        async def refusing_next(kind, item_id):
            await play_next(kind, item_id)
            check(kind, item_id)

        async def refusing_later(kind, item_id):
            await play_later(kind, item_id)
            check(kind, item_id)

        async def songs_found(song_ids):
            engine.calls.append(('songs_found', list(song_ids)))
            return {song_id for song_id in song_ids if song_id not in missing}

        engine.play, engine.play_next, engine.play_later = (refusing_play, refusing_next,
                                                            refusing_later)
        engine.songs_found = songs_found

    @staticmethod
    def sent(engine, *names):
        return [call for call in engine.calls if call[0] in (names or ('play',))]

    def test_the_songs_pages_play_and_shuffle_play_the_rest(self):
        """SongsPage's Play and Shuffle: songs.play_target()'s list, from its top."""
        async def go():
            for shuffle in (False, True):
                player, engine, app = make_player(state='up')
                self.refusing(engine, 'i.s2')
                with self.assertLogs('applemusic.player', 'WARNING'):
                    await player.play({'kind': 'songs', 'id': 'i.s1,i.s2,i.s3'},
                                      shuffle=shuffle)
                self.assertEqual(self.sent(engine), [
                    ('play', 'songs', 'i.s1,i.s2,i.s3', None, shuffle),
                    ('play', 'songs', 'i.s1,i.s3', None, shuffle)])
                self.assertEqual(app.toasts, ['1 song could not be played'])
                self.assertFalse(player.pending)
        asyncio.run(go())

    def test_the_library_artist_pages_play_plays_the_rest(self):
        """LibraryArtistPage's Play: discography.play_target() of the albums shown."""
        from applemusic.discography import play_target
        from applemusic.library import Item

        def album(album_id, prefix):
            play = {'kind': 'album', 'id': album_id}
            return Item({'id': album_id, 'kind': 'album', 'title': 'Invented', 'play': play,
                         'groups': [{'name': '', 'play': play, 'entries': [
                             {'id': f'i.{prefix}{number}', 'title': f'Song {number}'}
                             for number in range(3)]}]})

        async def go():
            player, engine, app = make_player(state='up')
            self.refusing(engine, 'i.a1', 'i.b0')
            target = play_target([album('l.alb1', 'a'), album('l.alb2', 'b')])
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.play(target, shuffle=False)
            self.assertEqual(self.sent(engine), [
                ('play', 'songs', 'i.a0,i.a1,i.a2,i.b0,i.b1,i.b2', None, False),
                ('play', 'songs', 'i.a0,i.a2,i.b1,i.b2', None, False)])
            self.assertEqual(app.toasts, ['2 songs could not be played'])
        asyncio.run(go())

    def test_a_shelf_of_songs_starts_at_the_song_clicked_where_it_now_is(self):
        """SongShelf: the list from the song activated (start_with, start_id)."""
        async def go():
            player, engine, app = make_player(state='up')
            self.refusing(engine, 'i.s1')
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.play({'kind': 'songs', 'id': 'i.s0,i.s1,i.s2,i.s3'},
                                  start_with=2, start_id='i.s2')
            self.assertEqual(self.sent(engine)[-1], ('play', 'songs', 'i.s0,i.s2,i.s3', 1,
                                                     None))
            self.assertEqual(engine.play_options[-1], {'start_id': 'i.s2'})
        asyncio.run(go())

    def test_the_song_clicked_gone_starts_at_the_next_found(self):
        async def go():
            player, engine, app = make_player(state='up')
            self.refusing(engine, 'i.s1', 'i.s2')
            with self.assertLogs('applemusic.player', 'WARNING'):
                await player.play({'kind': 'songs', 'id': 'i.s0,i.s1,i.s2,i.s3'},
                                  start_with=1, start_id='i.s1')
            self.assertEqual(self.sent(engine)[-1], ('play', 'songs', 'i.s0,i.s3', 1, None))
            self.assertEqual(engine.play_options[-1], {'start_id': 'i.s3'})
            self.assertEqual(app.toasts, ['2 songs could not be played'])
            # None found after it: MusicKit's refusal stands.
            player, engine, app = make_player(state='up')
            self.refusing(engine, 'i.s2')
            with self.assertRaises(EngineError) as raised:
                await player.play({'kind': 'songs', 'id': 'i.s0,i.s1,i.s2'}, start_with=2,
                                  start_id='i.s2')
            self.assertEqual(raised.exception.musickit_code, 'NOT_FOUND')
            self.assertEqual(len(self.sent(engine)), 1)
            self.assertEqual(app.toasts, [])
        asyncio.run(go())

    def test_a_second_refusal_stands_and_nothing_is_tried_again(self):
        async def go():
            player, engine, app = make_player(state='up')
            engine.play_failures = [not_found('i.s1'), not_found('i.s2')]
            engine.answers['songs_found'] = ['i.s0', 'i.s2']
            with self.assertRaises(EngineError):
                await player.play({'kind': 'songs', 'id': 'i.s0,i.s1,i.s2'})
            self.assertEqual(self.sent(engine), [
                ('play', 'songs', 'i.s0,i.s1,i.s2', None, None),
                ('play', 'songs', 'i.s0,i.s2', None, None)])
            self.assertEqual(app.toasts, [])
            self.assertFalse(player.pending)
        asyncio.run(go())

    def test_only_a_refusal_for_songs_not_found_is_tried_again(self):
        async def go():
            player, engine, app = make_player(state='up')
            engine.play_failures = [EngineError('api', 'play songs: refused',
                                                musickit_code='CONTENT_UNAVAILABLE')]
            with self.assertRaises(EngineError):
                await player.play({'kind': 'songs', 'id': 'i.s0,i.s1'})
            self.assertEqual(len(self.sent(engine)), 1)
            self.assertNotIn('songs_found', [call[0] for call in engine.calls])
            # An album is not a list of ids.
            player, engine, app = make_player(state='up')
            engine.play_failures = [not_found('l.alb1')]
            with self.assertRaises(EngineError):
                await player.play({'kind': 'album', 'id': 'l.alb1'})
            self.assertNotIn('songs_found', [call[0] for call in engine.calls])
            # Nothing found missing, or every song: the refusal stands.
            for missing in ((), ('i.s0', 'i.s1')):
                player, engine, app = make_player(state='up')
                self.refusing(engine, *missing)
                engine.play_failures = [not_found()]
                with self.assertRaises(EngineError):
                    await player.play({'kind': 'songs', 'id': 'i.s0,i.s1'})
                self.assertEqual(len(self.sent(engine)), 1)
        asyncio.run(go())

    def test_play_next_and_later_of_a_list_queue_the_rest(self):
        """A selection's Play Next and Play Later (actions.queue_commands()' runs of songs),
        and a drop on the player bar."""
        async def go():
            for name in ('play_next', 'play_later'):
                player, engine, app = make_player(state='up')
                self.refusing(engine, 'i.s1')
                with self.assertLogs('applemusic.player', 'WARNING'):
                    await getattr(player, name)('songs', 'i.s0,i.s1,i.s2')
                self.assertEqual(self.sent(engine, name), [
                    (name, 'songs', 'i.s0,i.s1,i.s2'), (name, 'songs', 'i.s0,i.s2')])
                self.assertEqual(app.toasts, ['1 song could not be played'])
            # MusicKit's playNext and playLater throw: its code is only in the message.
            player, engine, app = make_player(state='up')
            engine.fail = EngineError('api', 'MKError: [mk-007] NOT_FOUND; One or more items '
                                             'could not be resolved: i.s1')
            engine.answers['songs_found'] = ['i.s0']
            with self.assertLogs('applemusic.player', 'WARNING'):
                with self.assertRaises(EngineError):
                    await player.play_later('songs', 'i.s0,i.s1')
            self.assertEqual(self.sent(engine, 'play_later'), [
                ('play_later', 'songs', 'i.s0,i.s1'), ('play_later', 'songs', 'i.s0')])
            # A song alone is not tried again.
            player, engine, app = make_player(state='up')
            engine.fail = not_found('i.s1')
            with self.assertRaises(EngineError):
                await player.play_next('song', 'i.s1')
            self.assertEqual(len(self.sent(engine, 'play_next')), 1)
        asyncio.run(go())


class SourceTest(unittest.TestCase):
    """What a queue came from, while it still is that queue."""

    def test_an_album_in_order_is_its_queue_until_the_queue_changes(self):
        async def go():
            player, engine, app = make_player(state='up')
            await player.play({'kind': 'album', 'id': 'l.alb1'}, shuffle=False)
            engine.event('queueItemsDidChange', QUEUE)
            self.assertEqual(player.source, {'kind': 'album', 'id': 'l.alb1'})
            engine.event('queueItemsDidChange', QUEUE)  # sent again, the same
            self.assertEqual(player.source, {'kind': 'album', 'id': 'l.alb1'})
            more = dict(QUEUE, items=QUEUE['items'] + [dict(TRACK, id='i.demo0004')])
            engine.event('queueItemsDidChange', more)  # Play Later, MusicKit's autoplay
            self.assertIsNone(player.source)
        asyncio.run(go())

    def test_shuffled_songs_and_artists_have_none(self):
        async def go():
            player, engine, app = make_player(state='up')
            for play, shuffle in (({'kind': 'album', 'id': 'l.alb1'}, True),
                                  ({'kind': 'songs', 'id': 'i.a,i.b'}, False),
                                  ({'kind': 'artist', 'id': 'r.1'}, False)):
                await player.play(play, shuffle=shuffle)
                self.assertIsNone(player.source, play)
            player._set_shuffle(True)
            await player.play({'kind': 'playlist', 'id': 'p.pl1'})  # the mode as it is
            self.assertIsNone(player.source)
            await player.play({'kind': 'station', 'id': 'ra.1'})  # a station is always its own
            engine.event('queueItemsDidChange', QUEUE)
            engine.event('queueItemsDidChange', dict(QUEUE, items=QUEUE['items'][:1]))
            self.assertEqual(player.source, {'kind': 'station', 'id': 'ra.1'})
        asyncio.run(go())


def entries(count, tag='e'):
    """An invented queue of `count` entries, as the bridge shapes them."""
    return [dict(TRACK, id=f'i.{tag}{number:04}', catalogId=str(1100000000 + number),
                 title=f'Entry {tag}{number}', index=number) for number in range(count)]


class QueueDiffTest(unittest.TestCase):
    """apply_queue: MusicKit's whole queue, sent again at every change, becomes the fewest
    splices of the store, the entries kept as the same objects, renumbered."""

    def setUp(self):
        self.player, self.engine, self.app = make_player()
        self.changes = []
        self.player.queue.connect(
            'items-changed', lambda _s, position, removed, added: self.changes.append(
                (position, removed, added)))

    def send(self, items, index=0):
        self.engine.event('queueItemsDidChange', {'index': index, 'items': items})

    def ids(self):
        return [entry.id for entry in self.player.queue]

    def check_numbered(self):
        for position, entry in enumerate(self.player.queue):
            self.assertEqual((entry.index, entry.raw['index']), (position, position), entry.id)

    def start(self, items):
        self.send(items)
        self.changes.clear()
        return list(self.player.queue)

    def test_an_entry_taken_out_is_one_splice_and_the_rest_stay(self):
        items = entries(8)
        kept = self.start(items)
        self.send(items[:5] + items[6:])
        self.assertEqual(self.changes, [(5, 1, 0)])
        self.assertEqual(list(self.player.queue), kept[:5] + kept[6:])  # the same objects
        self.check_numbered()

    def test_an_entry_put_in_is_one_splice(self):
        items = entries(6)
        kept = self.start(items)
        added = dict(TRACK, id='i.next', catalogId='1100009999', title='Next')
        self.send(items[:2] + [added] + items[2:])  # Play Next after the second
        self.assertEqual(self.changes, [(2, 0, 1)])
        self.assertEqual(self.ids()[2], 'i.next')
        self.assertEqual(list(self.player.queue)[:2] + list(self.player.queue)[3:], kept)
        self.check_numbered()
        self.send(items[:2] + [added] + items[2:] + [dict(added, id='i.later')])  # Play Later
        self.assertEqual(self.changes[-1], (7, 0, 1))
        self.check_numbered()

    def test_a_move_is_two_splices(self):
        items = entries(10)
        kept = self.start(items)
        first = items[:8] + items[9:]          # spliceQueueItems(8, 1)
        second = first[:2] + [items[8]] + first[2:]   # spliceQueueItems(2, 0, taken)
        self.send(first)
        self.send(second)
        self.assertEqual(self.changes, [(8, 1, 0), (2, 0, 1)])
        self.assertEqual(self.ids(), [item['id'] for item in second])
        moved = self.player.queue.get_item(2)
        self.assertNotIn(moved, kept)  # the entry moved is made again; the others are kept
        self.assertEqual([entry for entry in self.player.queue if entry is not moved],
                         kept[:8] + kept[9:])
        self.check_numbered()

    def test_a_whole_new_queue_is_one_splice(self):
        self.start(entries(5))
        self.send(entries(7, 'z'))
        self.assertEqual(self.changes, [(0, 5, 7)])
        self.assertEqual(self.ids(), [item['id'] for item in entries(7, 'z')])
        self.check_numbered()
        self.send([])
        self.assertEqual(self.changes[-1], (0, 7, 0))

    def test_an_entry_changed_in_place_is_replaced_alone(self):
        items = entries(5)
        kept = self.start(items)
        changed = [dict(item) for item in items]
        changed[3]['autoplay'] = True  # the mark is the entry's data
        self.send(changed)
        self.assertEqual(self.changes, [(3, 1, 1)])
        self.assertTrue(self.player.queue.get_item(3).autoplay)
        self.assertEqual(list(self.player.queue)[:3], kept[:3])

    def test_the_same_song_twice_and_a_queue_inside_itself(self):
        a, b, c = entries(3)
        self.start([a, b, b, c])
        self.send([a, b, c])
        self.assertEqual(self.changes, [(2, 1, 0)])
        self.assertEqual(self.ids(), [a['id'], b['id'], c['id']])
        self.check_numbered()
        self.start([a, b, a])
        self.send([a])
        self.assertEqual(self.changes, [(1, 2, 0)])
        self.send([a, b, a])
        self.assertEqual(self.changes[-1], (1, 0, 2))
        self.assertEqual(self.ids(), [a['id'], b['id'], a['id']])
        self.check_numbered()

    def test_autoplay_turned_off_one_event_each(self):
        items = entries(5) + [dict(item, autoplay=True) for item in entries(10, 'auto')]
        kept = self.start(items)
        for count in range(10):
            self.send(items[:len(items) - 1 - count])  # MusicKit takes them from the end
        self.assertEqual(self.changes, [(14 - count, 1, 0) for count in range(10)])
        self.assertEqual(list(self.player.queue), kept[:5])
        with mock.patch('applemusic.player.NowPlaying', side_effect=AssertionError('made')):
            self.send(items[:5])  # the same again: nothing made, nothing spliced
        self.assertEqual(len(self.changes), 10)

    def test_random_edits_end_as_the_snapshot(self):
        import random
        chooser = random.Random(332)
        pool = entries(40) + entries(10, 'x')
        for _round in range(200):
            current = chooser.sample(pool, chooser.randint(0, 20))
            before = self.start(current)
            wanted = list(current)
            for _edit in range(chooser.randint(1, 3)):
                kind = chooser.choice(('remove', 'insert', 'move', 'replace'))
                if kind == 'remove' and wanted:
                    wanted.pop(chooser.randrange(len(wanted)))
                elif kind == 'insert':
                    wanted.insert(chooser.randint(0, len(wanted)), chooser.choice(pool))
                elif kind == 'move' and wanted:
                    wanted.insert(chooser.randint(0, len(wanted) - 1),
                                  wanted.pop(chooser.randrange(len(wanted))))
                elif kind == 'replace':
                    wanted = chooser.sample(pool, chooser.randint(0, 20))
            self.send(wanted)
            self.assertEqual(self.ids(), [item['id'] for item in wanted])
            self.check_numbered()
            self.assertLessEqual(len(self.changes), 1)  # one splice at most
            # What is alike at the start is kept as it was.
            start = 0
            while (start < min(len(current), len(wanted))
                   and current[start]['id'] == wanted[start]['id']):
                self.assertIs(self.player.queue.get_item(start), before[start])
                start += 1


class QueueEditTest(unittest.TestCase):
    """Up Next's Remove, Clear and its Undo: the store at once, then the engine; the events
    that follow change nothing; a failure shows MusicKit's queue again."""

    def playing(self, count=6, index=1, items=None, **snapshot):
        """A Player with an invented queue of `count` (or `items`), the entry at `index`
        playing."""
        player, engine, app = make_player(state='up')
        items = entries(count) if items is None else items
        engine.event('queueItemsDidChange', dict(snapshot, index=index, items=items))
        engine.event('nowPlayingItemDidChange', {'track': items[index], 'index': index})
        return player, engine, app, items

    def ids(self, player):
        return [entry.id for entry in player.queue]

    def test_remove_takes_the_entry_out_at_once(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            engine.calls.clear()
            gate = engine.gate('queue_remove')
            task = asyncio.ensure_future(player.remove_from_queue(3, 'i.e0003'))
            await asyncio.sleep(0)
            self.assertEqual(self.ids(player), [item['id'] for item in items[:3] + items[4:]])
            self.assertEqual(engine.calls, [('queue_remove', 3, 'i.e0003')])
            gate.set()
            self.assertTrue(await task)
            changes = []
            player.queue.connect('items-changed', lambda *args: changes.append(args[1:]))
            # MusicKit's event for it: the store as it is already.
            engine.event('queueItemsDidChange', {'index': 1, 'items': items[:3] + items[4:]})
            self.assertEqual(changes, [])
            self.assertEqual([entry.index for entry in player.queue], [0, 1, 2, 3, 4])
        asyncio.run(go())

    def test_remove_refuses_what_it_may_not_take(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            engine.calls.clear()
            for index, entry_id in ((1, 'i.e0001'), (0, 'i.e0000'), (3, 'i.e0004'),
                                    (9, 'i.e0009')):
                self.assertFalse(await player.remove_from_queue(index, entry_id))
            self.assertEqual(engine.calls, [])
            self.assertEqual(player.queue.get_n_items(), 6)
            engine.event('queueItemsDidChange', {'index': 1, 'items': items, 'editable': False})
            self.assertFalse(player.queue_editable)
            self.assertFalse(player.can_edit(3))
            self.assertFalse(player.can_clear())
            self.assertFalse(await player.remove_from_queue(3, 'i.e0003'))
            self.assertEqual(await player.clear_up_next(), 0)
            self.assertEqual(engine.calls, [])
        asyncio.run(go())

    def test_a_refused_remove_shows_musickits_queue_again(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            engine.answers['queue'] = {'index': 1, 'items': items}
            engine.fail = EngineError('queue-changed', 'the entry at 3 is another')
            self.assertFalse(await player.remove_from_queue(3, 'i.e0003'))  # not raised
            engine.fail = None
            await app.settle()
            self.assertEqual(self.ids(player), [item['id'] for item in items])
            engine.fail = EngineError('queue-locked', 'a station')
            with self.assertRaises(EngineError):
                await player.remove_from_queue(3, 'i.e0003')
            engine.fail = None
            await app.settle()
            self.assertEqual(player.queue.get_n_items(), 6)
        asyncio.run(go())

    def test_clear_and_undo(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            engine.calls.clear()
            self.assertEqual(await player.clear_up_next(), 4)
            self.assertEqual(self.ids(player), ['i.e0000', 'i.e0001'])
            self.assertEqual(engine.calls, [('queue_clear',)])
            self.assertFalse(player.can_clear())
            self.assertTrue(player.can_undo_clear)
            self.assertEqual(await player.undo_clear(), 4)
            self.assertEqual(self.ids(player), [item['id'] for item in items])
            self.assertEqual([entry.index for entry in player.queue], list(range(6)))
            self.assertEqual(engine.calls, [('queue_clear',), ('queue_undo_clear',)])
            self.assertEqual(await player.undo_clear(), 0)  # once only
            self.assertEqual(app.toasts, [])
            # Another item playing since: nothing to put back after it, and a toast says so.
            await player.clear_up_next()
            engine.event('queueItemsDidChange', {'index': 0, 'items': items[:2]})
            self.assertFalse(player.can_undo_clear)
            self.assertEqual(await player.undo_clear(), 0)
            self.assertEqual(engine.calls[-1], ('queue_clear',))
            self.assertEqual(app.toasts, ['The cleared songs could not be put back'])
            self.assertEqual(await player.undo_clear(), 0)  # nothing cleared: no toast
            self.assertEqual(len(app.toasts), 1)
        asyncio.run(go())

    def test_undo_after_autoplays_refill_leaves_one_autoplay_batch(self):
        async def go():
            items = entries(6)
            for item in items[4:]:
                item['autoplay'] = True
            player, engine, app, _items = self.playing(items=items)
            await app.settle()
            self.assertEqual(await player.clear_up_next(), 4)
            # MusicKit's autoplay refills the queue after the Clear (about 2 s later).
            refill = [dict(entry, autoplay=True, index=2 + number)
                      for number, entry in enumerate(entries(3, tag='r'))]
            engine.event('queueItemsDidChange', {'index': 1, 'items': items[:2] + refill})
            self.assertEqual(player.queue.get_n_items(), 5)
            self.assertEqual(await player.undo_clear(), 4)
            # As before the Clear: the refill gone, one Autoplay batch.
            self.assertEqual(self.ids(player), [item['id'] for item in items])
            self.assertEqual([entry.autoplay for entry in player.queue],
                             [False] * 4 + [True] * 2)
            self.assertEqual([entry.index for entry in player.queue], list(range(6)))
            changes = []
            player.queue.connect('items-changed', lambda *args: changes.append(args[1:]))
            engine.event('queueItemsDidChange', {'index': 1, 'items': items})
            self.assertEqual(changes, [])  # MusicKit's queue after the bridge's Undo
        asyncio.run(go())

    def test_undo_keeps_what_was_queued_since_and_a_refill_after_the_users_songs(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            self.assertEqual(await player.clear_up_next(), 4)  # none of autoplay's
            queued = dict(entries(1, tag='q')[0], index=2)
            refill = [dict(entry, autoplay=True, index=3 + number)
                      for number, entry in enumerate(entries(2, tag='r'))]
            engine.event('queueItemsDidChange',
                         {'index': 1, 'items': items[:2] + [queued] + refill})
            kept = player.queue.get_item(2)
            self.assertEqual(await player.undo_clear(), 4)
            self.assertEqual(self.ids(player), [item['id'] for item in items]
                             + ['i.q0000', 'i.r0000', 'i.r0001'])
            self.assertIs(player.queue.get_item(6), kept)  # the same entry, renumbered
            self.assertEqual([entry.index for entry in player.queue], list(range(9)))
        asyncio.run(go())

    def test_undone_tail_orders_the_entries_as_the_bridge_does(self):
        def entry(name, autoplay=False):
            return types.SimpleNamespace(name=name, autoplay=autoplay)

        def names(tail):
            return [item.name for item in tail]

        user, auto = [entry('b'), entry('c')], [entry('a1', True), entry('a2', True)]
        since = [entry('x'), entry('r1', True), entry('r2', True)]
        self.assertEqual(names(undone_tail(user + auto, since)), ['b', 'c', 'x', 'a1', 'a2'])
        self.assertEqual(names(undone_tail(user, since)), ['b', 'c', 'x', 'r1', 'r2'])
        self.assertEqual(names(undone_tail(auto, [])), ['a1', 'a2'])
        self.assertEqual(names(undone_tail([], since)), ['x', 'r1', 'r2'])

    def test_a_failed_undo_shows_musickits_queue_again(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            self.assertEqual(await player.clear_up_next(), 4)
            # MusicKit's queue as the failed Undo left it: Clear's entries gone.
            engine.answers['queue'] = {'index': 1, 'items': items[:2]}
            engine.fail = EngineError('api', 'TypeError: r.filter is not a function')
            with self.assertRaises(EngineError):  # player_command toasts it
                await player.undo_clear()
            engine.fail = None
            await app.settle()
            self.assertEqual(self.ids(player), ['i.e0000', 'i.e0001'])
            self.assertFalse(player.can_undo_clear)
            # Nothing to put back in the page (it reloaded, or its queue changed): the
            # queue read again, a toast, nothing raised.
            engine.event('queueItemsDidChange', {'index': 1, 'items': items})
            self.assertEqual(await player.clear_up_next(), 4)
            engine.calls.clear()
            engine.fail = EngineError('queue-changed', 'nothing to put back')
            self.assertEqual(await player.undo_clear(), 0)
            engine.fail = None
            await app.settle()
            self.assertEqual(engine.calls, [('queue_undo_clear',), ('queue',)])
            self.assertEqual(self.ids(player), ['i.e0000', 'i.e0001'])
            self.assertEqual(app.toasts, ['The cleared songs could not be put back'])
        asyncio.run(go())

    def test_a_failed_clear_offers_no_undo(self):
        async def go():
            player, engine, app, items = self.playing()
            await app.settle()
            engine.answers['queue'] = {'index': 1, 'items': items}
            engine.fail = EngineError('engine-down', 'gone')
            with self.assertRaises(EngineError):
                await player.clear_up_next()
            engine.fail = None
            await app.settle()
            self.assertFalse(player.can_undo_clear)
            self.assertEqual(player.queue.get_n_items(), 6)
        asyncio.run(go())

    def test_a_restored_session_is_edited_locally(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.calls.clear()
            queue = [{key: value for key, value in item.items() if key != 'index'}
                     for item in entries(5)]
            self.assertTrue(player.restore(session(queue=queue, index=1)))
            self.assertTrue(player.queue_editable)
            self.assertTrue(await player.remove_from_queue(3, 'i.e0003'))
            self.assertIsNone(player.source)  # its songs' queue now, not the album's
            self.assertEqual(await player.clear_up_next(), 2)
            self.assertEqual(await player.undo_clear(), 2)
            self.assertEqual(self.ids(player), ['i.e0000', 'i.e0001', 'i.e0002', 'i.e0004'])
            self.assertEqual(engine.calls, [])  # nothing asked of MusicKit
            await player.clear_up_next()
            await player.resume()
            # What MusicKit gets is the session as edited.
            self.assertEqual(engine.calls[-1], ('play', 'songs', 'i.e0000,i.e0001', 1, False))
            self.assertFalse(player.can_undo_clear)  # the Clear was the session's
        asyncio.run(go())


class QueuePage:
    """MusicKit's queue behind a FakeEngine, edited as the bridge edits it: each remove or
    move runs when the page gets to it, in order (`hold()` keeps them waiting until
    `release()`), its queueItemsDidChange (the snapshot naming the edit's number) posted
    before the answer, or, `deferred`, on the loop's next turn (MusicKit posting its events
    after the call), read as the queue is then. An edit whose entry is not where it is named
    is refused ('queue-changed'), as the bridge refuses it; queue() answers the queue."""

    def __init__(self, engine, items, index, deferred=False):
        self.engine = engine
        self.items = [{key: value for key, value in item.items() if key != 'index'}
                      for item in items]
        self.index = index
        self.edit = 0
        self.deferred = deferred
        self._open = asyncio.Event()
        self._open.set()
        self._lock = asyncio.Lock()
        engine.queue_remove = self.remove
        engine.queue_move = self.move
        engine.queue = self.queue

    def hold(self):
        self._open.clear()

    def release(self):
        self._open.set()

    def ids(self):
        return [item['id'] for item in self.items]

    def snapshot(self):
        return {'index': self.index, 'edit': self.edit,
                'items': [dict(item, index=position) for position, item in enumerate(self.items)]}

    def post(self):
        self.engine.event('queueItemsDidChange', self.snapshot())

    def change(self, items):
        """MusicKit changing its queue itself (autoplay's refill, its entries going): the
        event the app did not ask for."""
        self.items = [dict(item) for item in items]
        self.post()

    async def queue(self):
        self.engine.calls.append(('queue',))
        return self.snapshot()

    async def _run(self, edit, apply):
        async with self._lock:
            await self._open.wait()
            edited = apply()
            if edited is None:
                raise EngineError('queue-changed', 'the entry named is another now')
            self.items = edited
            if edit is not None:
                self.edit = edit
            if self.deferred:
                asyncio.get_running_loop().call_soon(self.post)
            else:
                self.post()

    async def remove(self, index, entry_id, edit=None):
        self.engine.calls.append(('queue_remove', index, entry_id))
        self.engine.edits.append(edit)
        await self._run(edit, lambda: removed_entry(self.items, index, entry_id))

    async def move(self, index, to_index, entry_id, edit=None):
        self.engine.calls.append(('queue_move', index, to_index, entry_id))
        self.engine.edits.append(edit)
        await self._run(edit, lambda: moved_entry(self.items, index, to_index, entry_id))


class QueueMoveTest(unittest.TestCase):
    """Up Next's moves: within a section, in the store at once as one splice of the same
    objects, then MusicKit's queue; the edits out replayed onto every snapshot that does not
    hold them yet, so a burst of moves and removes never takes the store back a step."""

    def playing(self, count=8, index=1, autoplay=(), deferred=False):
        """A Player over a QueuePage of `count` invented entries (those at `autoplay` added
        by autoplay), the entry at `index` playing."""
        player, engine, app = make_player(state='up')
        items = entries(count)
        for position in autoplay:
            items[position]['autoplay'] = True
        page = QueuePage(engine, items, index, deferred=deferred)
        page.post()
        engine.event('nowPlayingItemDidChange', {'track': items[index], 'index': index})
        return player, engine, app, page

    def ids(self, player):
        return [entry.id for entry in player.queue]

    def watch(self, player):
        changes = []
        player.queue.connect('items-changed', lambda _store, *args: changes.append(args))
        return changes

    def test_move_range_is_the_entrys_section(self):
        queue = [types.SimpleNamespace(autoplay=flag)
                 for flag in (False, False, False, False, True, True)]
        self.assertEqual(move_range(queue, 1, 2), (2, 3))  # Playing Next
        self.assertEqual(move_range(queue, 1, 5), (4, 5))  # Autoplay
        self.assertEqual(move_range(queue[:4], 1, 3), (2, 3))  # no autoplay
        for index in (0, 1, 6):  # history, the entry playing, past the end
            self.assertIsNone(move_range(queue, 1, index))
        self.assertIsNone(move_range(queue, -1, 2))  # nothing playing

    def test_replays(self):
        items = [{'id': name} for name in 'abcd']
        self.assertEqual(moved_entry(items, 1, 3, 'b'), [{'id': 'a'}, {'id': 'c'},
                                                         {'id': 'd'}, {'id': 'b'}])
        self.assertIsNone(moved_entry(items, 1, 3, 'c'))
        self.assertIsNone(moved_entry(items, 1, 4, 'b'))
        self.assertEqual(removed_entry(items, 2, 'c'), [{'id': 'a'}, {'id': 'b'}, {'id': 'd'}])
        self.assertIsNone(removed_entry(items, 2, 'b'))
        self.assertIsNone(removed_entry(items, 7, 'b'))
        self.assertEqual(items, [{'id': name} for name in 'abcd'])  # not changed in place

    def test_a_move_takes_the_entry_out_and_puts_the_same_object_back(self):
        async def go():
            player, engine, app, page = self.playing()
            await app.settle()
            objects = list(player.queue)
            changes = self.watch(player)
            seen = []
            player.connect('notify::moving', lambda *_: seen.append(player.moving))
            page.hold()
            task = asyncio.ensure_future(player.move_in_queue(5, 2, 'i.e0005'))
            await asyncio.sleep(0)
            order = [0, 1, 5, 2, 3, 4, 6, 7]
            self.assertEqual(self.ids(player), [f'i.e{n:04}' for n in order])
            self.assertEqual(changes, [(5, 1, 0), (2, 0, 1)])
            self.assertEqual(list(player.queue), [objects[n] for n in order])
            self.assertEqual(seen, [objects[5], None])  # named while it moved
            self.assertEqual([entry.index for entry in player.queue], list(range(8)))
            self.assertEqual([entry.raw['index'] for entry in player.queue], list(range(8)))
            page.release()
            self.assertTrue(await task)
            self.assertEqual(engine.calls[-1], ('queue_move', 5, 2, 'i.e0005'))
            self.assertEqual(len(changes), 2)  # MusicKit's event changed nothing
            self.assertEqual(self.ids(player), page.ids())
            self.assertEqual(list(player.queue), [objects[n] for n in order])
            # Down, the other way.
            self.assertTrue(await player.move_in_queue(2, 7, 'i.e0005'))
            self.assertEqual(self.ids(player), page.ids())
            self.assertEqual(changes[2:], [(2, 1, 0), (7, 0, 1)])
            self.assertEqual(player._edits_out, [])
        asyncio.run(go())

    def test_a_move_stays_after_the_entry_playing_and_in_its_section(self):
        async def go():
            player, engine, app, page = self.playing(autoplay=(6, 7))
            await app.settle()
            engine.calls.clear()
            refused = ((1, 3, 'i.e0001'),   # the entry playing
                       (0, 3, 'i.e0000'),   # History
                       (3, 1, 'i.e0003'),   # above the entry playing
                       (3, 0, 'i.e0003'),   # into History
                       (3, 6, 'i.e0003'),   # into Autoplay
                       (6, 5, 'i.e0006'),   # out of Autoplay
                       (3, 4, 'i.e0004'),   # another entry is at 3
                       (3, 3, 'i.e0003'),   # where it is
                       (3, 8, 'i.e0003'),   # past the end
                       (9, 2, 'i.e0009'))
            for index, to_index, entry_id in refused:
                self.assertFalse(await player.move_in_queue(index, to_index, entry_id),
                                 (index, to_index))
            self.assertEqual(engine.calls, [])
            self.assertEqual(player.move_range(3), (2, 5))
            self.assertEqual(player.move_range(7), (6, 7))
            self.assertIsNone(player.move_range(1))
            self.assertTrue(await player.move_in_queue(7, 6, 'i.e0007'))  # within Autoplay
            self.assertTrue(await player.move_in_queue(2, 5, 'i.e0002'))  # within Playing Next
            self.assertEqual(self.ids(player), page.ids())
            self.assertEqual([entry.autoplay for entry in player.queue], [False] * 6 + [True] * 2)
            # A station's queue: nothing moves.
            page.engine.event('queueItemsDidChange', dict(page.snapshot(), editable=False))
            self.assertIsNone(player.move_range(3))
            self.assertFalse(await player.move_in_queue(3, 4, self.ids(player)[3]))
        asyncio.run(go())

    def assert_burst_kept_the_store(self, player, page, objects_by_id, changes):
        """After a burst: the store is MusicKit's queue, its entries the objects they were,
        and MusicKit's events changed nothing of it."""
        self.assertEqual(self.ids(player), page.ids())
        self.assertTrue(all(objects_by_id[entry.id] is entry for entry in player.queue))
        self.assertEqual(changes, [])
        self.assertEqual([entry.index for entry in player.queue],
                         list(range(player.queue.get_n_items())))
        self.assertEqual(player._edits_out, [])

    def test_held_alt_down(self):
        """Alt+Down held: one entry moved down five times while MusicKit has taken none of
        the moves yet. Each move's event arrives with the later moves still out."""
        for deferred in (False, True):
            with self.subTest(deferred=deferred):
                async def go(deferred=deferred):
                    player, engine, app, page = self.playing(count=10, deferred=deferred)
                    await app.settle()
                    page.hold()
                    tasks = []
                    for step in range(5):
                        tasks.append(asyncio.ensure_future(
                            player.move_in_queue(2 + step, 3 + step, 'i.e0002')))
                        await asyncio.sleep(0)
                    self.assertEqual(self.ids(player)[7], 'i.e0002')
                    objects = {entry.id: entry for entry in player.queue}
                    changes = self.watch(player)
                    page.release()
                    self.assertEqual(await asyncio.gather(*tasks), [True] * 5)
                    await asyncio.sleep(0)  # a deferred event's turn
                    await app.settle()
                    self.assertEqual(engine.edits, [1, 2, 3, 4, 5])
                    self.assert_burst_kept_the_store(player, page, objects, changes)
                asyncio.run(go())

    def test_rapid_delete(self):
        """Delete pressed four times: each removal names the entry that took the last one's
        place, and MusicKit's events come back with the later ones still out."""
        for deferred in (False, True):
            with self.subTest(deferred=deferred):
                async def go(deferred=deferred):
                    player, engine, app, page = self.playing(count=10, deferred=deferred)
                    await app.settle()
                    page.hold()
                    tasks = []
                    for number in range(4):
                        tasks.append(asyncio.ensure_future(
                            player.remove_from_queue(3, f'i.e{3 + number:04}')))
                        await asyncio.sleep(0)
                    self.assertEqual(player.queue.get_n_items(), 6)
                    objects = {entry.id: entry for entry in player.queue}
                    changes = self.watch(player)
                    page.release()
                    self.assertEqual(await asyncio.gather(*tasks), [True] * 4)
                    await asyncio.sleep(0)
                    await app.settle()
                    self.assertEqual(page.ids(), [f'i.e{n:04}' for n in (0, 1, 2, 7, 8, 9)])
                    self.assert_burst_kept_the_store(player, page, objects, changes)
                asyncio.run(go())

    def test_mixed_burst_with_musickits_own_change(self):
        """Moves and removes out together, and autoplay's refill landing in the middle: the
        refill is the one change the store takes, at its end."""
        async def go():
            player, engine, app, page = self.playing(count=8)
            await app.settle()
            page.hold()
            tasks = [asyncio.ensure_future(player.move_in_queue(6, 2, 'i.e0006'))]
            await asyncio.sleep(0)
            tasks.append(asyncio.ensure_future(player.remove_from_queue(4, 'i.e0003')))
            await asyncio.sleep(0)
            tasks.append(asyncio.ensure_future(player.move_in_queue(2, 5, 'i.e0006')))
            await asyncio.sleep(0)
            expected = ['i.e0000', 'i.e0001', 'i.e0002', 'i.e0004', 'i.e0005', 'i.e0006',
                        'i.e0007']
            self.assertEqual(self.ids(player), expected)
            objects = {entry.id: entry for entry in player.queue}
            changes = self.watch(player)
            refill = [dict(entry, autoplay=True) for entry in entries(2, tag='r')]
            page.change(page.items + refill)  # before MusicKit has taken any of the edits
            self.assertEqual(changes, [(7, 0, 2)])
            self.assertEqual(self.ids(player), expected + ['i.r0000', 'i.r0001'])
            objects.update((entry.id, entry) for entry in player.queue)
            changes.clear()
            page.release()
            self.assertEqual(await asyncio.gather(*tasks), [True] * 3)
            await app.settle()
            self.assert_burst_kept_the_store(player, page, objects, changes)
        asyncio.run(go())

    def test_an_edit_musickit_refuses_in_a_burst(self):
        """MusicKit's queue changed under a burst (an entry gone): the edit that named it is
        refused, its replay dropped, and the queue read again shows MusicKit's."""
        async def go():
            player, engine, app, page = self.playing(count=8)
            await app.settle()
            page.hold()
            first = asyncio.ensure_future(player.move_in_queue(3, 4, 'i.e0003'))
            await asyncio.sleep(0)
            second = asyncio.ensure_future(player.move_in_queue(6, 5, 'i.e0006'))
            await asyncio.sleep(0)
            # MusicKit loses i.e0005 before it takes either: the second names a place its
            # entry is no longer at.
            page.change([item for item in page.items if item['id'] != 'i.e0005'])
            page.release()
            self.assertTrue(await first)
            self.assertFalse(await second)
            await app.settle()
            self.assertEqual(self.ids(player), page.ids())
            self.assertEqual(page.ids()[2:], ['i.e0002', 'i.e0004', 'i.e0003', 'i.e0006',
                                              'i.e0007'])
            self.assertEqual(player._edits_out, [])
            self.assertIn(('queue',), engine.calls)  # read again
        asyncio.run(go())

    def test_a_restored_session_is_moved_locally(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.calls.clear()
            queue = [{key: value for key, value in item.items() if key != 'index'}
                     for item in entries(5)]
            self.assertTrue(player.restore(session(queue=queue, index=1)))
            self.assertTrue(await player.move_in_queue(4, 2, 'i.e0004'))
            self.assertEqual(self.ids(player), ['i.e0000', 'i.e0001', 'i.e0004', 'i.e0002',
                                                'i.e0003'])
            self.assertIsNone(player.source)  # its songs' queue now, not the album's
            self.assertEqual(engine.calls, [])
            self.assertEqual(player._edits_out, [])
            await player.resume()
            self.assertEqual(engine.calls[-1],
                             ('play', 'songs', 'i.e0000,i.e0001,i.e0004,i.e0002,i.e0003', 1,
                              False))
        asyncio.run(go())

    def test_the_engine_going_drops_the_edits_out(self):
        async def go():
            player, engine, app, page = self.playing()
            await app.settle()
            page.hold()
            task = asyncio.ensure_future(player.move_in_queue(3, 4, 'i.e0003'))
            await asyncio.sleep(0)
            self.assertEqual(len(player._edits_out), 1)
            player.apply_queue(None)
            self.assertEqual(player._edits_out, [])
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        asyncio.run(go())


class AutoplayTest(unittest.TestCase):
    """The autoplay setting goes to MusicKit at each start and bridgeReset; MusicKit's state
    and what it allows follow its snapshots and events."""

    def test_the_setting_goes_to_musickit_as_the_engine_comes_up(self):
        async def go():
            player, engine, app = make_player(state='down')
            app.settings.autoplay = False
            engine.answers['set_autoplay'] = {'autoplay': False, 'canAutoplay': True}
            engine.state = 'up'
            await app.settle()
            self.assertIn(('set_autoplay', False), engine.calls)
            self.assertFalse(player.autoplay)
            engine.calls.clear()
            engine.event('bridgeReset', {})  # the page set its own as it loaded
            await app.settle()
            self.assertIn(('set_autoplay', False), engine.calls)
            app.settings.autoplay = True
            engine.answers['set_autoplay'] = {'autoplay': True, 'canAutoplay': False}
            await player.apply_autoplay()
            self.assertTrue(player.autoplay)
            self.assertFalse(player.can_autoplay)
        asyncio.run(go())

    def test_nothing_without_an_engine_or_in_the_demo(self):
        async def go():
            for player, engine, app in (make_player(state='down'),
                                        make_player(state='up', demo=True)):
                await app.settle()
                engine.calls.clear()
                await player.apply_autoplay()
                self.assertEqual(engine.calls, [])
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.fail = EngineError('timeout', 'slow')
            await player.apply_autoplay()  # logged, not raised
        asyncio.run(go())

    def test_musickits_state_and_capabilities_follow_its_snapshots(self):
        player, engine, app = make_player()
        engine.event('autoplayEnabledDidChange', {'autoplay': True})
        self.assertTrue(player.autoplay)
        engine.event('queueItemsDidChange', dict(QUEUE, editable=False, canAutoplay=False,
                                                 autoplay=False))
        self.assertEqual((player.queue_editable, player.can_autoplay, player.autoplay),
                         (False, False, False))
        engine.event('queueItemsDidChange', QUEUE)  # an older shape: everything allowed
        self.assertEqual((player.queue_editable, player.can_autoplay), (True, True))
        engine.event('queueItemsDidChange', dict(QUEUE, editable=False))
        player.apply(None)  # the engine gone
        self.assertTrue(player.queue_editable)
        items = [dict(item) for item in QUEUE['items']]
        items[2]['autoplay'] = True
        engine.event('queueItemsDidChange', {'index': 0, 'items': items})
        self.assertEqual([entry.autoplay for entry in player.queue], [False, False, True])


# An invented live radio station playing, as the bridge's formatTrack shapes MusicKit's
# item (#343, src/backend/README.md: type radioStation, isLive, no length of its own).
LIVE = {
    'id': 'ra.live01', 'type': 'radioStation', 'isLive': True, 'catalogId': 'ra.live01',
    'title': 'Harbour One', 'artist': '', 'album': '', 'trackNumber': 1, 'discNumber': 1,
    'durationMs': 0, 'durationLabel': '0:00', 'explicit': False,
    'artUrl': 'https://example.invalid/live/256x256bb.jpg', 'index': 0,
}
# What MusicKit allows on a live station: nothing.
NOTHING = {'canSeek': False, 'canPause': False, 'canSkipToNextItem': False,
           'canSkipToPreviousItem': False}
EVERYTHING = dict.fromkeys(NOTHING, True)
CONTROLS = ('can_seek', 'can_pause', 'can_go_next', 'can_go_previous')


def controls(player):
    return {name: player.get_property(name) for name in CONTROLS}


def live_playing(engine):
    """A live station playing, as MusicKit was seen to report it: its item, playing, and a
    position inside the stream's window as its duration (160 s)."""
    engine.event('nowPlayingItemDidChange', {'track': LIVE, 'index': 0, 'capabilities': NOTHING})
    engine.event('playbackStateDidChange', {'state': 'playing', 'position': 112,
                                            'duration': 160, 'capabilities': NOTHING})
    engine.event('playbackTimeDidChange', {'position': 113, 'duration': 160})


class LiveTest(unittest.TestCase):
    """A live radio station: told by its item, not its duration; nothing may be done with
    it but Stop, and Play plays the station again."""

    def test_a_live_station_is_told_by_its_item(self):
        player, engine, app = make_player()
        notified = []
        player.connect('notify::can-seek', lambda p, _pspec: notified.append(p.can_seek))
        live_playing(engine)
        self.assertTrue(player.live)
        self.assertTrue(player.track.live)
        self.assertEqual(player.track.kind, '')  # nothing to love
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, False))
        self.assertEqual(notified, [False])  # once, with the item
        # A song after it: everything again.
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2,
                                                 'capabilities': EVERYTHING})
        self.assertFalse(player.live)
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, True))
        # A track with no isLive, or one not true, is no live station.
        self.assertFalse(NowPlaying(dict(LIVE, isLive=None)).live)
        self.assertFalse(NowPlaying(dict(TRACK, isLive='yes')).live)

    def test_a_live_item_allows_nothing_whatever_musickit_says(self):
        player, engine, app = make_player()
        engine.event('nowPlayingItemDidChange', {'track': LIVE, 'index': 0,
                                                 'capabilities': EVERYTHING})
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, False))
        # And without capabilities at all (an older bridge).
        player, engine, app = make_player()
        player.apply({'track': LIVE, 'state': 'playing', 'position': 112, 'duration': 160})
        self.assertTrue(player.live)
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, False))

    def test_the_controls_follow_musickits_capabilities(self):
        player, engine, app = make_player()
        engine.event('nowPlayingItemDidChange', {
            'track': TRACK, 'index': 2,
            'capabilities': dict(EVERYTHING, canSkipToNextItem=False,
                                 canSkipToPreviousItem=False)})
        # Previous still restarts an item that can be sought.
        self.assertEqual(controls(player), {'can_seek': True, 'can_pause': True,
                                            'can_go_next': False, 'can_go_previous': True})
        engine.event('capabilitiesChanged', {'capabilities': dict(NOTHING, canPause=True)})
        self.assertEqual(controls(player), {'can_seek': False, 'can_pause': True,
                                            'can_go_next': False, 'can_go_previous': False})
        # A state with an item loaded tells them again; the moments between items do not.
        engine.event('playbackStateDidChange', {'state': 'stopped', 'capabilities': EVERYTHING})
        self.assertFalse(player.can_seek)
        engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1,
                                                 'capabilities': EVERYTHING})
        self.assertIsNone(player.track)
        engine.event('playbackStateDidChange', {'state': 'playing', 'capabilities': EVERYTHING})
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, True))
        # An event without them keeps them; the engine going down forgets them.
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        engine.event('capabilitiesChanged', {'capabilities': {'canSkipToNextItem': False}})
        engine.event('playbackStateDidChange', {'state': 'playing'})
        self.assertFalse(player.can_go_next)
        player.apply(None)
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, True))

    def test_seek_next_and_previous_do_nothing_on_a_live_station(self):
        async def go():
            player, engine, app = make_player(state='up')
            live_playing(engine)
            engine.calls.clear()
            await player.seek(30)
            await player.next()
            await player.previous()  # 113 s in: a song would restart
            self.assertEqual(engine.calls, [])
        asyncio.run(go())

    def test_stop_keeps_the_station_and_play_plays_it_again(self):
        async def go():
            player, engine, app = make_player(state='up')
            await player.play({'kind': 'station', 'id': 'ra.live01'})
            live_playing(engine)
            engine.calls.clear()
            await player.toggle()  # the play button's Stop: it cannot be paused
            self.assertEqual(engine.calls, [('control', 'stop')])
            # MusicKit's stop: no item, stopped. The station stays, stopped.
            engine.event('playbackStateDidChange', {'state': 'stopped', 'position': 0,
                                                    'duration': 0})
            engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
            self.assertTrue(player.restored)
            self.assertEqual(player.track.id, 'ra.live01')
            self.assertTrue(player.live)
            self.assertEqual((player.state, player.position, player.duration),
                             ('stopped', 0.0, 0.0))
            self.assertFalse(player.active)
            self.assertTrue(player.stopped)
            self.assertEqual([entry.id for entry in player.queue], ['ra.live01'])
            self.assertEqual(player.source, {'kind': 'station', 'id': 'ra.live01'})
            self.assertEqual(controls(player), dict.fromkeys(CONTROLS, False))
            # Play: the station again, from now.
            engine.calls.clear()
            await player.toggle()
            self.assertIn(('play', 'station', 'ra.live01', None, False), engine.calls)
            self.assertEqual(engine.play_options[-1], {'start_id': None})
            self.assertFalse(player.restored)
        asyncio.run(go())

    def test_pause_stops_a_live_station(self):
        """MusicKit leaves a live station playing on a pause: MPRIS's Pause stops it."""
        async def go():
            player, engine, app = make_player(state='up')
            live_playing(engine)
            engine.calls.clear()
            await player.pause()
            self.assertEqual(engine.calls, [('control', 'stop')])
            # Without a play request of the app's, the station is the item itself.
            self.assertEqual(player.source, {'kind': 'station', 'id': 'ra.live01'})
            self.assertTrue(player.restored)
        asyncio.run(go())

    def test_stop_keeps_nothing_when_another_item_came_meanwhile(self):
        async def go():
            player, engine, app = make_player(state='up')
            live_playing(engine)
            gate = engine.gate('control')
            stop = asyncio.ensure_future(player.stop())
            await asyncio.sleep(0)
            engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            gate.set()
            await stop
            self.assertFalse(player.restored)
            self.assertEqual(player.track.id, 'i.demo0001')
        asyncio.run(go())

    def test_a_song_pauses_and_stops_as_it_did(self):
        async def go():
            player, engine, app = make_player(state='up')
            player.apply({'track': TRACK, 'state': 'playing', 'position': 10, 'duration': 214})
            engine.calls.clear()
            await player.toggle()
            await player.stop()
            self.assertEqual(engine.calls, [('control', 'pause'), ('control', 'stop')])
            self.assertFalse(player.restored)
        asyncio.run(go())

    def test_a_live_station_restored_shows_live(self):
        """The last session a live station: its item alone, no position (session.py), and
        LIVE again (the item keeps its isLive)."""
        player, engine, app = make_player()
        entry = {key: value for key, value in LIVE.items() if key != 'index'}
        self.assertTrue(player.restore(session(queue=[entry], index=0, position=0.0,
                                               duration=0.0,
                                               source={'kind': 'station', 'id': 'ra.live01'})))
        self.assertTrue(player.live)
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, False))
        self.assertEqual((player.position, player.duration), (0.0, 0.0))
        # A session of songs restored allows everything: its commands are the Player's.
        player, engine, app = make_player()
        player.restore(session())
        self.assertEqual(controls(player), dict.fromkeys(CONTROLS, True))


class ModesTest(unittest.TestCase):
    """Shuffle and Repeat follow what MusicKit allows (canSetShuffleMode,
    canSetRepeatMode), and a live station allows neither (#441): a mode set on a stream
    would only change what plays after it."""

    def test_a_live_station_allows_no_mode_whatever_musickit_says(self):
        player, engine, app = make_player()
        live_playing(engine)  # capabilities without the modes: allowed, but live
        self.assertEqual((player.can_shuffle, player.can_repeat), (False, False))
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2,
                                                 'capabilities': EVERYTHING})
        self.assertEqual((player.can_shuffle, player.can_repeat), (True, True))
        engine.event('capabilitiesChanged', {'capabilities': dict(
            EVERYTHING, canSetShuffleMode=False, canSetRepeatMode=True)})
        self.assertEqual((player.can_shuffle, player.can_repeat), (False, True))
        player.apply(None)  # the engine down: forgotten
        self.assertEqual((player.can_shuffle, player.can_repeat), (True, True))

    def test_the_modes_are_not_sent_while_live(self):
        async def go():
            player, engine, app = make_player(state='up')
            live_playing(engine)
            engine.calls.clear()
            self.assertEqual(await player.set_shuffle(True), {'shuffle': 'off',
                                                               'repeat': 'none'})
            self.assertEqual(await player.set_repeat('all'), {'shuffle': 'off',
                                                               'repeat': 'none'})
            self.assertEqual(engine.calls, [])
            self.assertEqual((player.shuffle, player.repeat), (False, 'none'))
            # The station stopped (a session restored, live): still nothing.
            await player.stop()
            engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
            self.assertTrue(player.restored and player.live)
            engine.calls.clear()
            await player.set_shuffle(True)
            await player.set_repeat('one')
            self.assertEqual(engine.calls, [])
            self.assertEqual((player.shuffle, player.repeat), (False, 'none'))
        asyncio.run(go())


class VolumeTest(unittest.TestCase):
    """The level MusicKit answers a volume set with is the Player's at once (#466):
    holding no item, MusicKit posts no playbackVolumeDidChange."""

    def test_the_answer_is_taken_without_an_event(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            notified = []
            player.connect('notify::volume', lambda p, _pspec: notified.append(p.volume))
            engine.answers['volume'] = 0.2455
            self.assertEqual(await player.set_volume(0.2455), 0.2455)
            self.assertEqual(player.volume, 0.2455)
            # The event that follows while an item plays changes nothing more.
            engine.event('playbackVolumeDidChange', {'volume': 0.2455})
            self.assertEqual(notified, [0.2455])
        asyncio.run(go())

    def test_a_live_station_stopped_takes_the_level(self):
        """As seen live: a live station stopped (a session restored, the engine up,
        MusicKit's queue empty), then a volume set."""
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            live_playing(engine)
            await player.stop()
            engine.event('playbackStateDidChange', {'state': 'stopped'})
            engine.event('nowPlayingItemDidChange', {'track': None, 'index': -1})
            self.assertTrue(player.restored)
            engine.answers['volume'] = 0.25
            await player.set_volume(0.25)
            self.assertEqual(player.volume, 0.25)
            self.assertEqual(engine.calls[-1], ('volume', 0.25))
        asyncio.run(go())

    def test_no_answer_keeps_the_level(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            engine.event('playbackVolumeDidChange', {'volume': 0.6})
            engine.answers['volume'] = None  # a stand-in with nothing to say
            await player.set_volume(0.3)
            self.assertEqual(player.volume, 0.6)
        asyncio.run(go())


class FormatTimeTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(format_time(0), '0:00')
        self.assertEqual(format_time(7.4), '0:07')
        self.assertEqual(format_time(61), '1:01')
        self.assertEqual(format_time(214.6), '3:35')
        self.assertEqual(format_time(3600), '1:00:00')
        self.assertEqual(format_time(3725), '1:02:05')
        self.assertEqual(format_time(-3), '0:00')
        self.assertEqual(format_time(None), '0:00')
        self.assertEqual(format_time(30, remaining=True), '-0:30')


if __name__ == '__main__':
    unittest.main()
