# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The last session (src/session.py): the snapshot of a Player fed synthetic events, the file's
checks, and the keeper writing it after changes, at quit and never over a good one with
nothing, on the GLib loop (as the app runs), into a temporary directory. Invented data only."""

import asyncio
import datetime
import json
import os
import tempfile
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from gi.events import GLibEventLoop  # noqa: E402

from applemusic import session  # noqa: E402
from applemusic.backend import store  # noqa: E402
from applemusic.backend.errors import EngineError  # noqa: E402
from tests.test_player import QUEUE, SESSION, TRACK, make_player  # noqa: E402

NOW = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)


def playing(player, engine, position=83.0):
    """The Player with QUEUE playing, TRACK `position` seconds in."""
    engine.event('queueItemsDidChange', QUEUE)
    engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
    engine.event('playbackStateDidChange', {'state': 'playing'})
    player._set_position(position, 214.0)
    player._set_state('paused')  # no estimate running on


class SnapshotTest(unittest.TestCase):
    def test_nothing_playing_is_nothing(self):
        player, engine, app = make_player()
        self.assertIsNone(session.snapshot(player))

    def test_the_queue_the_item_and_its_position(self):
        player, engine, app = make_player()
        playing(player, engine)
        data = session.snapshot(player, now=NOW)
        self.assertEqual(data['version'], session.VERSION)
        self.assertEqual(data['saved'], '2026-01-02T03:04:05+00:00')
        self.assertEqual((data['index'], data['offset'], data['position'], data['duration']),
                         (2, 0, 83.0, 214.0))
        self.assertEqual([entry['id'] for entry in data['queue']],
                         ['i.demo0003', 'i.demo0002', 'i.demo0001'])
        self.assertEqual(set(data['queue'][2]), set(session.TRACK_KEYS) - {'type'})
        self.assertIsNone(data['source'])
        self.assertEqual(data['repeat'], 'none')
        self.assertNotIn('shuffle', data)  # comes back off, the queue in its order
        self.assertEqual(session.parse(json.loads(json.dumps(data)))['queue'], data['queue'])

    def test_a_source_kept_while_the_queue_is_its(self):
        async def go():
            player, engine, app = make_player(state='up')
            await player.play({'kind': 'album', 'id': 'l.alb1'}, shuffle=False)
            playing(player, engine)
            self.assertEqual(session.snapshot(player)['source'],
                             {'kind': 'album', 'id': 'l.alb1'})
            engine.event('queueItemsDidChange', dict(QUEUE, items=list(reversed(QUEUE['items']))))
            self.assertIsNone(session.snapshot(player)['source'])  # shuffled since
        asyncio.run(go())

    def test_a_station_keeps_its_item_and_no_position(self):
        async def go():
            player, engine, app = make_player(state='up')
            await player.play({'kind': 'station', 'id': 'ra.1'})
            segment = dict(TRACK, type='stations', index=0)
            engine.event('nowPlayingItemDidChange', {'track': segment, 'index': 0})
            player._set_position(40.0)
            data = session.snapshot(player)
            self.assertEqual(data['source'], {'kind': 'station', 'id': 'ra.1'})
            self.assertEqual((data['position'], len(data['queue'])), (0.0, 1))
        asyncio.run(go())

    def test_an_item_that_is_neither_song_nor_video_is_not_kept(self):
        player, engine, app = make_player()
        engine.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, type='stations'), 'index': 0})
        self.assertIsNone(session.snapshot(player))

    def test_a_pending_request_is_not_kept(self):
        player, engine, app = make_player()
        playing(player, engine)
        player.pending = True
        self.assertIsNone(session.snapshot(player))

    def test_a_long_queue_keeps_a_slice_around_the_item(self):
        player, engine, app = make_player()
        items = [dict(TRACK, id=f'i.demo{n:04d}', index=n) for n in range(1200)]
        engine.event('queueItemsDidChange', {'index': 700, 'items': items})
        engine.event('nowPlayingItemDidChange', {'track': items[700], 'index': 700})
        data = session.snapshot(player)
        self.assertEqual(len(data['queue']), session.QUEUE_LIMIT)
        self.assertEqual(data['offset'], 700 - session.QUEUE_BEFORE)
        self.assertEqual(data['queue'][data['index']]['id'], 'i.demo0700')
        engine.event('nowPlayingItemDidChange', {'track': items[1150], 'index': 1150})
        data = session.snapshot(player)  # near the end: the last QUEUE_LIMIT
        offset = 1200 - session.QUEUE_LIMIT
        self.assertEqual((data['offset'], data['index']), (offset, 1150 - offset))

    def test_a_session_restored_is_kept_with_its_local_changes(self):
        async def go():
            player, engine, app = make_player()
            player.restore(dict(SESSION, offset=40))
            await player.next()  # already the last: nothing
            await player.previous()  # 83 s in: the top
            await player.previous()
            data = session.snapshot(player)
            self.assertEqual((data['index'], data['offset'], data['position']), (1, 40, 0.0))
            self.assertEqual(data['source'], SESSION['source'])
            self.assertEqual(data['repeat'], 'all')
        asyncio.run(go())


def valid(**changes):
    """A file's JSON for SESSION, with `changes`."""
    data = {'version': session.VERSION, 'saved': '2026-01-02T03:04:05+00:00',
            'queue': SESSION['queue'], 'index': 2, 'offset': 0, 'position': 83.0,
            'duration': 214.0, 'repeat': 'all', 'source': {'kind': 'album', 'id': 'l.alb1'}}
    data.update(changes)
    return data


class ParseTest(unittest.TestCase):
    def valid(self, **changes):
        return valid(**changes)

    def test_a_valid_session(self):
        parsed = session.parse(self.valid())
        kept = [{key: entry[key] for key in session.TRACK_KEYS if key in entry}
                for entry in SESSION['queue']]  # no durationLabel, which the bridge adds
        self.assertEqual(parsed, {'queue': kept, 'index': 2, 'offset': 0,
                                  'position': 83.0, 'duration': 214.0, 'repeat': 'all',
                                  'source': {'kind': 'album', 'id': 'l.alb1'}})

    def test_what_is_not_a_session(self):
        for bad in (None, [], 'x', self.valid(version=2), self.valid(version=None),
                    self.valid(queue=[]), self.valid(queue={}), self.valid(index=3),
                    self.valid(index=-1), self.valid(index=True), self.valid(index='2'),
                    self.valid(queue=[{'title': 'No id'}]),
                    self.valid(queue=[dict(SESSION['queue'][0], id='')]),
                    self.valid(queue=[dict(SESSION['queue'][0], title=5)]),
                    self.valid(queue=[dict(SESSION['queue'][0], durationMs=-1)]),
                    self.valid(queue=[dict(SESSION['queue'][0], explicit='yes')])):
            self.assertIsNone(session.parse(bad), bad)

    def test_odd_values_are_put_right(self):
        parsed = session.parse(self.valid(position=float('nan'), duration=-3, offset='x',
                                          repeat='sometimes', source={'kind': 'artist',
                                                                      'id': 'r.1'}))
        self.assertEqual((parsed['position'], parsed['duration'], parsed['offset'],
                          parsed['repeat'], parsed['source']), (0.0, 0.0, 0, 'none', None))
        self.assertEqual(session.parse(self.valid(position=900))['position'], 214.0)
        entry = session.parse(self.valid(queue=[dict(SESSION['queue'][0],
                                                     artUrl='http://example.invalid/a.jpg',
                                                     extra='dropped')], index=0))
        self.assertIsNone(entry)  # artwork that is not https: not this app's file
        queue = [dict(SESSION['queue'][0], extra='not kept')]
        self.assertNotIn('extra', session.parse(self.valid(queue=queue, index=0))['queue'][0])

    def test_a_queue_longer_than_the_limit_is_cut(self):
        queue = [dict(SESSION['queue'][0], id=f'i.demo{n:04d}')
                 for n in range(session.QUEUE_LIMIT + 5)]
        parsed = session.parse(self.valid(queue=queue, index=3))
        self.assertEqual(len(parsed['queue']), session.QUEUE_LIMIT)
        self.assertIsNone(session.parse(self.valid(queue=queue,
                                                   index=session.QUEUE_LIMIT + 1)))


class FileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, session.FILE_NAME)

    def test_missing_corrupt_and_foreign_files(self):
        self.assertIsNone(session.read(self.path))
        for content in ('', '{"version": 1, "queue": [', '[1, 2]', '{"version": 9}'):
            with open(self.path, 'w', encoding='utf-8') as file:
                file.write(content)
            with self.assertLogs('applemusic.session', 'WARNING'):
                self.assertIsNone(session.read(self.path), content)

    def test_written_and_read_back(self):
        player, engine, app = make_player()
        playing(player, engine)
        session.write(self.path, session.snapshot(player), store.cache_generation())
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        read = session.read(self.path)
        self.assertEqual((read['index'], read['position']), (2, 83.0))

    def test_a_write_for_a_cache_since_wiped_lands_nowhere(self):
        generation = store.cache_generation()
        store.bump_cache_generation()
        session.write(self.path, {'version': 1}, generation)
        self.assertFalse(os.path.exists(self.path))

    def test_remove(self):
        session.remove(self.path)  # nothing there: nothing to do
        with open(self.path, 'w', encoding='utf-8') as file:
            file.write('{}')
        session.remove(self.path)
        self.assertFalse(os.path.exists(self.path))


class KeeperTest(unittest.IsolatedAsyncioTestCase):
    """The keeper on the GLib loop, its delay 0 (a write at the next idle)."""

    loop_factory = GLibEventLoop

    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, session.FILE_NAME)
        self.player, self.engine, self.app = make_player(state='up')
        self.app.signing_out = False
        self.app.player = self.player
        self.keeper = session.SessionKeeper(self.app, self.path)
        self.keeper.delay_ms = 0

    async def written(self):
        """Let the delay's timeout and the writer run; the file's JSON, or None."""
        for _ in range(3):
            await asyncio.sleep(0.01)
            await self.app.settle()
        if not os.path.exists(self.path):
            return None
        with open(self.path, encoding='utf-8') as file:
            return json.load(file)

    async def test_a_change_is_written(self):
        playing(self.player, self.engine)
        data = await self.written()
        self.assertEqual((data['index'], data['position']), (2, 83.0))
        await self.player.seek(100)  # paused: a seek is a change (the engine's, here)
        self.player._set_position(100.0)
        self.assertEqual((await self.written())['position'], 100.0)

    async def test_the_engine_going_down_writes_nothing_over_it(self):
        playing(self.player, self.engine)
        await self.written()
        self.engine.state = 'down'  # the Player empties
        self.assertIsNone(self.player.track)
        self.assertEqual((await self.written())['index'], 2)

    async def test_load_restores_and_writes_nothing_back(self):
        with open(self.path, 'w', encoding='utf-8') as file:
            json.dump(valid(), file)
        before = os.stat(self.path).st_mtime_ns
        await self.keeper.load()
        self.assertTrue(self.player.restored)
        self.assertEqual(self.player.position, 83.0)
        await self.written()
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)
        await self.player.next()  # a local change: kept
        await self.player.previous()
        self.assertEqual((await self.written())['position'], 0.0)

    async def test_load_signed_out_shows_nothing(self):
        with open(self.path, 'w', encoding='utf-8') as file:
            json.dump(valid(), file)
        self.app.settings.signed_in = False
        await self.keeper.load()
        self.assertIsNone(self.player.track)

    async def test_save_now_takes_the_player_as_it_is_then(self):
        self.keeper.delay_ms = 60_000  # nothing written by a change
        playing(self.player, self.engine)
        task = self.keeper.save_now()
        self.engine.state = 'down'  # the quit's engine stop empties the Player
        await task
        with open(self.path, encoding='utf-8') as file:
            self.assertEqual(json.load(file)['position'], 83.0)
        self.keeper.delay_ms = 0
        self.player.apply({'track': dict(TRACK, id='i.demo0009')})
        self.assertFalse(self.keeper._timer)  # closed: nothing more scheduled
        self.assertEqual((await self.written())['queue'][2]['id'], 'i.demo0001')

    async def test_save_now_with_nothing_is_none(self):
        self.assertIsNone(self.keeper.save_now())

    async def test_forget_and_a_wiped_cache(self):
        playing(self.player, self.engine)
        self.keeper.delay_ms = 60_000
        self.player._set_position(90.0)
        self.player._set_state('paused')
        store.bump_cache_generation()  # sign-out's or Clear Cache's
        self.keeper.forget()
        self.assertFalse(self.keeper._timer)
        await self.written()
        self.assertFalse(os.path.exists(self.path))
        self.keeper.delay_ms = 0
        self.player._set_position(95.0)  # signed in still (Clear Cache): written anew
        self.assertEqual((await self.written())['position'], 95.0)

    async def test_nothing_is_scheduled_while_signing_out(self):
        self.app.signing_out = True
        playing(self.player, self.engine)
        self.assertIsNone(await self.written())

    async def test_musickit_refusing_the_session_deletes_the_file(self):
        with open(self.path, 'w', encoding='utf-8') as file:
            json.dump(valid(), file)
        await self.keeper.load()
        self.engine.fail = EngineError('api', 'refused', musickit_code='CONTENT_UNAVAILABLE')
        with self.assertLogs('applemusic.player', 'WARNING'):
            await self.player.toggle()
        await self.written()
        self.assertFalse(os.path.exists(self.path))

    async def test_the_position_is_written_while_playing_on_a_timer(self):
        playing(self.player, self.engine)
        await self.written()
        self.player._set_state('playing')
        self.assertTrue(self.keeper._ticker)
        await self.written()  # the state's change
        self.player._set_position(120.0)  # each second while playing: not a change
        self.assertLess((await self.written())['position'], 85.0)
        self.keeper.delay_ms = 0
        self.keeper._on_tick()  # POSITION_EVERY seconds on
        self.assertGreaterEqual((await self.written())['position'], 120.0)
        self.player._set_state('paused')
        self.assertFalse(self.keeper._ticker)


if __name__ == '__main__':
    unittest.main()
