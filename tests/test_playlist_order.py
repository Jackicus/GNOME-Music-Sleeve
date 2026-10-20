# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A playlist's songs put in a new order (applemusic.playlist_order): shown at once, one
write at a time, a burst of moves one write, put back on a refusal, Undo, and library.json
following once Apple shows it. Stand-ins for the app, the library and the engine."""

import asyncio
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import playlist_order
from applemusic.backend.errors import EngineError
from applemusic.library import Item
from applemusic.playlist_order import PlaylistOrder, positions, sync_tracks


def playlist(playlist_id='p.1', track_ids='abcde', **attributes):
    play = {'kind': 'playlist', 'id': playlist_id}
    raw = {'id': playlist_id, 'kind': 'playlist', 'title': 'Evening Walks', 'play': play,
           'groups': [{'name': 'Tracks', 'play': play, 'entries': [
               {'id': track_id, 'title': f'Song {track_id.upper()}', 'index': index,
                'type': 'library-songs'} for index, track_id in enumerate(track_ids)]}]}
    if attributes:
        raw['attributes'] = attributes
    return Item(raw)


class FakeLibrary:
    def __init__(self, *items):
        self.items = {item.id: item for item in items}
        self.held = {}
        self.released = []

    def by_id(self, kind, item_id):
        return self.items.get(item_id) if kind == 'playlist' else None

    def reorder(self, item, order):
        if not item.reorder(order):
            return False
        self.held[item.id] = item.track_ids()
        return True

    def release_order(self, playlist_id):
        self.released.append(playlist_id)
        self.held.pop(playlist_id, None)

    def with_held_order(self, raw):
        return raw


class FakeEngine:
    def __init__(self):
        self.state = 'up'
        self.writes = []  # (playlist id, shown, order)
        self.failure = None  # an EngineError the next write raises
        self.failures = []  # or one per write, in turn (None: it succeeds)
        self.hold = None  # an asyncio.Event a write waits for
        self.listed = {}  # playlist id -> the ids playlist_track_ids() answers

    async def reorder_playlist(self, playlist_id, shown, order):
        if self.hold is not None:
            await self.hold.wait()
        self.writes.append((playlist_id, list(shown), list(order)))
        if self.failures:
            self.failure = self.failures.pop(0)
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure

    async def playlist_track_ids(self, playlist_id):
        return self.listed.get(playlist_id, [])


class FakePlayer:
    async def ensure_engine(self):
        pass


class FakeSync:
    task = None


class FakeApp:
    def __init__(self, library):
        self.library = library
        self.engine = FakeEngine()
        self.player = FakePlayer()
        self.library_sync = FakeSync()
        self.demo = False
        self.tasks = []
        self.toasts = []  # (title, button label, action, target)
        self.reported = []
        self.syncs = []

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    def toast(self, title, button_label=None, action_name=None, target=None):
        self.toasts.append((title, button_label, action_name,
                            target.unpack() if target is not None else None))

    def report(self, error):
        self.reported.append(error.code)

    def start_sync(self, quick=False, playlists=False, videos=False, tracks_of=()):
        self.syncs.append(tuple(tracks_of))
        return self.spawn(asyncio.sleep(0))


class PlaylistOrderTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.item = playlist()
        self.library = FakeLibrary(self.item)
        self.app = FakeApp(self.library)
        self.refreshed = []

        async def refresh(playlist_id):
            self.refreshed.append(playlist_id)

        self.order = PlaylistOrder(self.app, refresh=refresh, delay=0.02, settle=(0,))

    async def settle(self, seconds=0.0):
        await asyncio.sleep(seconds)
        while any(not task.done() for task in self.app.tasks):
            await asyncio.wait([task for task in self.app.tasks if not task.done()])

    def ids(self):
        return ''.join(self.item.track_ids())

    async def test_a_burst_of_moves_is_one_write(self):
        self.assertTrue(self.order.move(self.item, 1, 2))
        self.assertTrue(self.order.move(self.item, 2, 3))
        self.assertTrue(self.order.move(self.item, 3, 4))
        self.assertEqual(self.ids(), 'acdeb')  # shown at once
        self.assertEqual(self.app.engine.writes, [])
        self.assertTrue(self.order.pending('p.1'))
        await self.settle(0.05)
        self.assertEqual(self.app.engine.writes, [('p.1', list('abcde'), [0, 2, 3, 4, 1])])
        self.assertFalse(self.order.pending('p.1'))
        self.assertEqual(self.app.toasts, [('Moved “Song B”', 'Undo', 'win.item-undo-reorder',
                                            'p.1')])

    async def test_a_drop_is_written_at_once_and_moves_meanwhile_go_next(self):
        self.app.engine.hold = asyncio.Event()
        self.order.move(self.item, 0, 4, at_once=True)
        await asyncio.sleep(0)
        self.order.move(self.item, 0, 1, at_once=True)  # while the first is written
        self.app.engine.hold.set()
        await self.settle()
        self.assertEqual(self.app.engine.writes, [
            ('p.1', list('abcde'), [1, 2, 3, 4, 0]),
            ('p.1', list('bcdea'), [1, 0, 2, 3, 4])])
        self.assertEqual(self.ids(), 'cbdea')
        self.assertEqual([toast[0] for toast in self.app.toasts],
                         ['Moved “Song A”', 'Moved “Song B”'])

    async def test_several_songs_moved_name_the_playlist(self):
        self.order.move(self.item, 0, 1)
        self.order.move(self.item, 4, 0)
        await self.settle(0.05)
        self.assertEqual(self.app.toasts[0][0], 'Changed the order of “Evening Walks”')

    async def test_a_refusal_puts_back_what_apple_has(self):
        self.app.engine.failure = EngineError('api', 'invented refusal')
        self.order.move(self.item, 0, 2, at_once=True)
        await self.settle()
        self.assertEqual(self.ids(), 'abcde')
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.refreshed, [])
        self.assertFalse(self.order.pending('p.1'))
        self.assertFalse(self.order.undo('p.1'))  # nothing to undo
        self.assertEqual(self.app.toasts, [])

    async def test_a_conflict_reads_the_playlist_again(self):
        self.app.engine.failure = EngineError('conflict', 'changed elsewhere')
        self.order.move(self.item, 0, 2, at_once=True)
        await self.settle()
        self.assertEqual(self.ids(), 'abcde')
        self.assertEqual(self.library.released, ['p.1'])
        self.assertEqual(self.refreshed, ['p.1'])
        self.assertEqual(self.app.reported, ['conflict'])

    async def test_a_second_write_refused_keeps_the_first(self):
        self.app.engine.hold = asyncio.Event()
        self.order.move(self.item, 0, 1, at_once=True)  # bacde, written
        await asyncio.sleep(0)
        self.order.move(self.item, 4, 0, at_once=True)  # ebacd, refused
        self.app.engine.failures = [None, EngineError('api', 'invented refusal')]
        self.app.engine.hold.set()
        await self.settle()
        self.assertEqual(self.ids(), 'bacde')
        self.assertEqual(self.app.reported, ['api'])

    async def test_undo_writes_the_order_before(self):
        self.order.move(self.item, 0, 2, at_once=True)
        await self.settle()
        self.assertTrue(self.order.undo('p.1'))
        self.assertEqual(self.ids(), 'abcde')
        await self.settle()
        self.assertEqual(self.app.engine.writes[-1], ('p.1', list('bcade'), [2, 0, 1, 3, 4]))
        self.assertEqual(self.app.toasts[-1],
                         ('Put back the order of “Evening Walks”', None, None, None))
        self.assertFalse(self.order.undo('p.1'))  # once

    async def test_flush_writes_what_is_pending_now(self):
        self.order.move(self.item, 0, 1)
        await self.order.flush('p.1')
        self.assertEqual(len(self.app.engine.writes), 1)
        self.assertFalse(self.order.pending('p.1'))
        await self.order.flush('p.1')  # nothing pending: nothing written
        self.assertEqual(len(self.app.engine.writes), 1)

    async def test_quitting_with_the_engine_down_writes_nothing(self):
        self.order.move(self.item, 0, 1)
        self.app.engine.state = 'down'
        with self.assertLogs('applemusic.playlist_order', 'WARNING'):
            await self.order.flush_all(quitting=True)
        await self.settle(0.05)
        self.assertEqual(self.app.engine.writes, [])
        self.assertFalse(self.order.pending('p.1'))
        # Up, it writes.
        self.app.engine.state = 'up'
        self.order.move(self.item, 0, 1)
        await self.order.flush_all(quitting=True)
        self.assertEqual(len(self.app.engine.writes), 1)

    async def test_a_sign_out_forgets_the_orders_pending_and_their_undo(self):
        # Nothing of the account signed out is written for, or undone on, the next one.
        self.order.settle = (0.02,)
        self.app.engine.listed['p.1'] = list('bcade')
        self.order.move(self.item, 0, 2, at_once=True)
        await self.order.flush('p.1')  # written; Apple's tracks to be read back
        self.order.move(self.item, 0, 1)  # waiting out its delay
        self.order.forget()
        await self.settle(0.05)
        self.assertEqual(len(self.app.engine.writes), 1)
        self.assertFalse(self.order.pending('p.1'))
        self.assertEqual(self.app.syncs, [])  # no pass for the playlist read back
        self.assertFalse(self.order.undo('p.1'))

    async def test_the_demo_shows_the_move_and_writes_nothing(self):
        self.app.demo = True
        self.assertTrue(self.order.move(self.item, 0, 1, at_once=True))
        await self.settle(0.05)
        self.assertEqual(self.ids(), 'bacde')
        self.assertEqual(self.app.engine.writes, [])
        self.assertEqual(self.app.toasts, [])
        self.assertFalse(self.order.pending('p.1'))

    async def test_library_json_follows_once_apple_shows_the_order(self):
        self.app.engine.listed['p.1'] = list('bcade')
        self.order.move(self.item, 0, 2, at_once=True)
        await self.settle()
        self.assertEqual(self.app.syncs, [('p.1',)])
        # Apple does not show it: no pass (the order stays held a while).
        self.app.syncs = []
        self.order.move(self.item, 0, 1, at_once=True)
        with self.assertLogs('applemusic.playlist_order', 'INFO'):
            await self.settle()
        self.assertEqual(self.app.syncs, [])

    async def test_what_cannot_be_moved(self):
        self.assertFalse(self.order.move(self.item, 0, 0))
        self.assertFalse(self.order.move(self.item, 0, 5))
        self.assertFalse(self.order.move(self.item, -1, 2))
        for item in (playlist(isFavourites=True), playlist(canEdit=False),
                     playlist('pl.u-catalog'), playlist(track_ids='a'),
                     Item({'id': 'l.1', 'kind': 'album', 'groups': []}), None):
            self.assertFalse(PlaylistOrder.can_reorder(item))
            self.assertFalse(self.order.move(item, 0, 1))
        self.assertEqual(self.ids(), 'abcde')


class HelpersTest(unittest.IsolatedAsyncioTestCase):
    def test_positions(self):
        self.assertEqual(positions(list('aba'), list('aab')), [0, 2, 1])
        self.assertIsNone(positions(list('ab'), list('abc')))

    async def test_sync_tracks_waits_for_a_sync_running(self):
        app = FakeApp(FakeLibrary())
        running = asyncio.get_running_loop().create_future()
        starts = []

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            starts.append(tracks_of)
            if len(starts) == 1:
                return None  # a sync runs already
            return app.spawn(asyncio.sleep(0))

        app.start_sync = start_sync
        app.library_sync.task = running
        waiting = asyncio.ensure_future(sync_tracks(app, 'p.1'))
        await asyncio.sleep(0)
        self.assertEqual(starts, [('p.1',)])
        running.set_result(None)
        app.library_sync.task = None
        self.assertTrue(await waiting)
        self.assertEqual(starts, [('p.1',), ('p.1',)])
        # None running and none started (signed out, demo): nothing to wait for.
        app.start_sync = lambda **_kwargs: None
        self.assertFalse(await sync_tracks(app, 'p.1'))

    def test_constants(self):
        self.assertGreater(playlist_order.MOVE_DELAY, 0)
        self.assertLess(playlist_order.QUIT_WAIT, 6)


if __name__ == '__main__':
    unittest.main()
