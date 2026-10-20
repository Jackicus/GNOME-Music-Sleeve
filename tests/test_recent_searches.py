# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""RecentSearches (recent_searches.py): newest first and once each, LIMIT kept, only what a
search opens, written to the cache and read back, and forgotten when the cache is cleared."""

import asyncio
import json
import os
import tempfile
import unittest

from tests import ROOT  # noqa: F401  (registers the applemusic package)

from applemusic import recent_searches
from applemusic.backend import store
from applemusic.library import Item
from applemusic.recent_searches import LIMIT, RecentSearches


def hit(number, kind='album', **extra):
    return Item(dict({'id': f'c{number}', 'kind': kind, 'title': f'Invented {number}',
                      'subtitle': 'Nobody', 'groups': [{'entries': []}]}, **extra))


def ids(recent):
    return [recent.items.get_item(i).id for i in range(recent.items.get_n_items())]


class RecentSearchesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, recent_searches.FILE_NAME)
        self.tasks = []

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    async def written(self):
        await asyncio.gather(*self.tasks)
        with open(self.path, encoding='utf-8') as file:
            return json.load(file)['items']

    async def test_newest_first_once_each_and_at_most_limit(self):
        recent = RecentSearches()
        for number in range(LIMIT + 3):
            recent.add(hit(number))
        recent.add(hit(5))
        self.assertEqual(recent.items.get_n_items(), LIMIT)
        self.assertEqual(ids(recent)[:3], ['c5', f'c{LIMIT + 2}', f'c{LIMIT + 1}'])
        self.assertEqual(ids(recent).count('c5'), 1)

    async def test_only_what_a_search_opens_is_kept(self):
        recent = RecentSearches()
        recent.add(hit(1, kind='category'))
        recent.add(Item({'kind': 'album', 'title': 'No id'}))
        self.assertEqual(recent.items.get_n_items(), 0)

    async def test_written_without_the_tracks_and_read_back(self):
        recent = RecentSearches(self.path, self.spawn)
        await recent.load()
        recent.add(hit(1, play={'id': 'c1'}))
        recent.add(hit(2, kind='artist'))
        entries = await self.written()
        self.assertEqual([entry['id'] for entry in entries], ['c2', 'c1'])
        self.assertNotIn('groups', entries[1])
        self.assertEqual(entries[1]['play'], {'id': 'c1'})
        again = RecentSearches(self.path, self.spawn)
        await again.load()
        self.assertEqual(ids(again), ['c2', 'c1'])

    async def test_clear_empties_the_file(self):
        recent = RecentSearches(self.path, self.spawn)
        await recent.load()
        recent.add(hit(1))
        recent.clear()
        self.assertEqual(recent.items.get_n_items(), 0)
        self.assertEqual(await self.written(), [])

    async def test_a_cleared_cache_is_read_again(self):
        recent = RecentSearches(self.path, self.spawn)
        await recent.load()
        recent.add(hit(1))
        await self.written()
        store.bump_cache_generation()  # Clear Cache, or a sign-out
        os.remove(self.path)
        await recent.load()
        self.assertEqual(recent.items.get_n_items(), 0)

    async def test_a_damaged_file_reads_as_nothing(self):
        with open(self.path, 'w', encoding='utf-8') as file:
            file.write('{"items": [{"id": 3}, "x", {"id": "c4", "kind": "song"}]')
        self.assertEqual(recent_searches.read(self.path), [])
        with open(self.path, 'w', encoding='utf-8') as file:
            json.dump({'items': [{'id': 3}, 'x', {'id': 'c4', 'kind': 'song'}]}, file)
        self.assertEqual(recent_searches.read(self.path), [{'id': 'c4', 'kind': 'song'}])


if __name__ == '__main__':
    unittest.main()
