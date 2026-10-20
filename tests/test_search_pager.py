# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""src/search_pager.py: the pages of one kind of a search, fetched as they are wanted, over a
stand-in for Engine.search."""

import asyncio
import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend.errors import EngineError
from applemusic.library import Item
from applemusic.search_pager import EMPTY_PAGES, SearchPager


def song(number):
    return {'id': f'17240{number:05d}', 'kind': 'song', 'title': f'Invented Song {number}',
            'subtitle': 'Invented Artist'}


class Catalog:
    """Engine.search's stand-in: `count` invented songs, `limit` a page; `fail` makes the
    next search raise it; `pages` maps an offset to an answer of its own."""

    def __init__(self, count):
        self.songs = [song(number) for number in range(count)]
        self.calls = []
        self.fail = None
        self.pages = {}
        self.gate = None

    async def search(self, term, kind=None, offset=0, limit=25):
        self.calls.append((term, kind, offset, limit))
        if self.gate is not None:
            await self.gate
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error
        if offset in self.pages:
            return self.pages[offset]
        page = self.songs[offset:offset + limit]
        following = offset + limit if offset + limit < len(self.songs) else None
        return {'shelves': [{'key': kind, 'title': '', 'items': page, 'next': following}]}


class SearchPagerTest(unittest.IsolatedAsyncioTestCase):
    def pager(self, catalog, first=20, limit=25):
        spawned = []

        def spawn(coro):
            task = asyncio.get_running_loop().create_task(coro)
            spawned.append(task)
            return task

        items = [Item(data) for data in catalog.songs[:first]]
        pager = SearchPager('tide', 'songs', items, first if first < len(catalog.songs) else None,
                            search=catalog.search, spawn=spawn, limit=limit)
        pager.spawned = spawned
        return pager

    def ids(self, pager):
        return [pager.items.get_item(n).id for n in range(pager.items.get_n_items())]

    async def test_pages_on_to_the_end(self):
        catalog = Catalog(60)
        pager = self.pager(catalog)
        states = []
        pager.connect('notify::state', lambda pager, _pspec: states.append(pager.state))
        self.assertEqual((pager.state, pager.items.get_n_items()), ('idle', 20))
        await pager.request()
        self.assertEqual((pager.state, pager.next, pager.items.get_n_items()), ('idle', 45, 45))
        await pager.request()
        self.assertEqual((pager.state, pager.next, pager.items.get_n_items()), ('done', None, 60))
        self.assertEqual(self.ids(pager), [data['id'] for data in catalog.songs])
        self.assertEqual(catalog.calls, [('tide', 'songs', 20, 25), ('tide', 'songs', 45, 25)])
        self.assertEqual(states, ['loading', 'idle', 'loading', 'done'])
        self.assertIsNone(pager.request())  # nothing more to ask
        self.assertEqual(len(catalog.calls), 2)

    async def test_one_page_at_a_time(self):
        catalog = Catalog(60)
        catalog.gate = asyncio.get_running_loop().create_future()
        pager = self.pager(catalog)
        task = pager.request()
        self.assertIsNone(pager.request())
        await asyncio.sleep(0)
        self.assertEqual(pager.state, 'loading')
        catalog.gate.set_result(None)
        await task
        self.assertEqual(len(catalog.calls), 1)

    async def test_a_failure_is_tried_again(self):
        catalog = Catalog(30)
        pager = self.pager(catalog)
        catalog.fail = EngineError('timeout')
        await pager.request()
        self.assertEqual((pager.state, pager.error.code, pager.next), ('failed', 'timeout', 20))
        await pager.request()
        self.assertEqual((pager.state, pager.error, pager.items.get_n_items()),
                         ('done', None, 30))

    async def test_what_it_holds_is_not_added_again_and_an_empty_page_is_followed(self):
        catalog = Catalog(30)
        pager = self.pager(catalog)
        # Apple's offsets moved: the next page holds only two it has (followed at once), the
        # one after it the rest.
        catalog.pages[20] = {'shelves': [{'key': 'songs', 'items': catalog.songs[18:20],
                                          'next': 22}]}
        catalog.pages[22] = {'shelves': [{'key': 'songs', 'items': catalog.songs[20:30],
                                          'next': None}]}
        await pager.request()
        self.assertEqual(self.ids(pager), [data['id'] for data in catalog.songs])
        self.assertEqual([call[2] for call in catalog.calls], [20, 22])
        self.assertEqual(pager.state, 'done')

    async def test_pages_of_nothing_new_end_it(self):
        catalog = Catalog(30)
        pager = self.pager(catalog)
        for offset in range(20, 20 + 5 * EMPTY_PAGES, 5):
            catalog.pages[offset] = {'shelves': [{'key': 'songs', 'items': [],
                                                  'next': offset + 5}]}
        await pager.request()
        self.assertEqual((pager.state, pager.next, len(catalog.calls)),
                         ('done', None, EMPTY_PAGES))

    async def test_a_next_that_does_not_move_on_ends_it(self):
        catalog = Catalog(30)
        pager = self.pager(catalog)
        catalog.pages[20] = {'shelves': [{'key': 'songs', 'items': catalog.songs[20:22],
                                          'next': 20}]}
        await pager.request()
        self.assertEqual((pager.state, pager.items.get_n_items()), ('done', 22))

    async def test_cancel_stops_the_page_on_its_way(self):
        catalog = Catalog(60)
        catalog.gate = asyncio.get_running_loop().create_future()
        pager = self.pager(catalog)
        task = pager.request()
        await asyncio.sleep(0)
        pager.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((pager.state, pager.items.get_n_items(), pager.next), ('idle', 20, 20))
        catalog.gate = None
        await pager.request()  # asked for again when wanted
        self.assertEqual(pager.items.get_n_items(), 45)

    async def test_nothing_to_page_is_done_at_once(self):
        catalog = Catalog(5)
        pager = self.pager(catalog, first=5)
        self.assertEqual(pager.state, 'done')
        self.assertIsNone(pager.request())
        self.assertEqual(catalog.calls, [])


if __name__ == '__main__':
    unittest.main()
