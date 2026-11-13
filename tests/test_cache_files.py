# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the cache keeps: library.json, the kept answers and the pruners (backend.cache_files)."""

import json
import os
import shutil
import tempfile
import unittest

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import (
    art_cache,
    cache_files,
    store,
)

# The sizes these tests were written against (the extension's defaults). The
# app's own defaults come from config; TestArtSizes covers those.
UPSTREAM_SIZES = {'cover': 512, 'thumb': 256}


class TestLibraryFile(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_save_library_replaces_the_file(self):
        library = {'version': 1, 'sections': {'albums': [{'id': 'a1', 'title': 'Album 1'}]},
                   'shelves': []}
        cache_files.save_library(library, self.tmp_dir)
        cache_files.save_library(dict(library, sections={}), self.tmp_dir, indent=None)
        lib_file = os.path.join(self.tmp_dir, 'library.json')
        with open(lib_file) as f:
            text = f.read()
        self.assertEqual(json.loads(text), {'version': 1, 'sections': {}, 'shelves': []})
        self.assertNotIn('\n', text)  # the compact form
        self.assertEqual(os.listdir(self.tmp_dir), ['library.json'])  # no lock, no temp

    def test_prune_art(self):
        art_dir = os.path.join(self.tmp_dir, 'art')
        thumb_dir = os.path.join(self.tmp_dir, 'thumb')
        os.makedirs(art_dir, exist_ok=True)
        os.makedirs(thumb_dir, exist_ok=True)
        used_file = os.path.join(art_dir, 'used.jpg')
        unused_file = os.path.join(art_dir, 'unused.jpg')
        used_thumb = os.path.join(thumb_dir, 'used.jpg')
        unused_thumb = os.path.join(thumb_dir, 'unused.jpg')
        row_thumb = os.path.join(thumb_dir, 'row.jpg')

        for path in (used_file, unused_file, used_thumb, unused_thumb, row_thumb):
            with open(path, 'w') as f:
                f.write('test')

        lib_data = {
            'sections': {
                'albums': [{'art': used_file, 'thumb': used_thumb}],
                'artists': [],
                'playlists': [{'art': None, 'thumb': None,
                               'groups': [{'entries': [{'thumb': row_thumb}]}]}],
                'radio': [],
            },
            'shelves': [],
        }

        marker = os.path.join(art_dir, '.sizes')
        with open(marker, 'w') as f:
            f.write('{"cover": 512, "thumb": 256}')

        pruned = cache_files.prune_art(lib_data, self.tmp_dir)
        self.assertEqual(pruned, 2)
        self.assertTrue(os.path.exists(marker))
        self.assertTrue(os.path.exists(used_file))
        self.assertTrue(os.path.exists(used_thumb))
        self.assertTrue(os.path.exists(row_thumb))
        self.assertFalse(os.path.exists(unused_file))
        self.assertFalse(os.path.exists(unused_thumb))


class TestPruneCaches(unittest.TestCase):
    """prune_caches over an invented cache."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.now = 10 ** 9

    def put(self, name, age=0, size=10):
        path = os.path.join(self.tmp_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'x' * size)
        os.utime(path, (self.now - age, self.now - age))
        return path

    def names(self, folder=''):
        return sorted(os.listdir(os.path.join(self.tmp_dir, folder)))

    def test_what_only_grows_is_trimmed(self):
        keep = cache_files.ANSWER_KEEP_AGE
        day = cache_files.ANSWER_MAX_AGE
        for number in range(5):  # played 0 to 4 hours ago
            self.put(f'lyrics/{number}.json', age=number * 3600)
        self.put('categories/old.json', age=keep + 60)
        self.put('categories/fresh.json', age=60)
        self.put('categories/yesterday.json', age=2 * day)  # stale, still the offline answer
        self.put('artists/1724049001.json', age=keep + 60)
        self.put('artists/1724049002.json', age=60)
        self.put('albums/1724049100.json', age=keep + 60)
        self.put('credits/1724049201.json', age=keep + 60)
        self.put('credits/1724049202.json', age=60)
        self.put('credits/.c.tmp', age=2 * 3600)
        self.put('landing.json', age=keep + 60)
        self.put('radio.json', age=2 * day)
        self.put('browse.json', age=60)
        self.put('.x.json.tmp', age=2 * 3600)  # a crash's leftover
        self.put('lyrics/.y.tmp', age=2 * 3600)
        self.put('.z.tmp', age=60)  # a write in progress
        self.put('items/album-1.json')
        self.put('items/artist-2.json')
        for number in range(3):
            self.put(f'remote-art/{number}.jpg', age=number, size=100)
        self.put('library.json', age=10 * day)  # the library's, never these
        self.put('art/a.jpg', age=10 * day)
        gone = cache_files.prune_caches(self.tmp_dir, now=self.now, remote_bytes=250,
                                        lyrics_keep=2)
        self.assertEqual(gone, {'remote-art': 1, 'lyrics': 3, 'answers': 5, 'items': 2,
                                'temps': 3})
        self.assertEqual(self.names('lyrics'), ['0.json', '1.json'])
        self.assertEqual(self.names('categories'), ['fresh.json', 'yesterday.json'])
        self.assertEqual(self.names('artists'), ['1724049002.json'])
        self.assertEqual(self.names('remote-art'), ['0.jpg', '1.jpg'])
        self.assertEqual(self.names('albums'), [])
        self.assertEqual(self.names('credits'), ['1724049202.json'])
        self.assertEqual(self.names(), ['.z.tmp', 'albums', 'art', 'artists', 'browse.json',
                                        'categories', 'credits', 'library.json', 'lyrics',
                                        'radio.json', 'remote-art'])
        # Again: nothing more to do.
        self.assertFalse(any(cache_files.prune_caches(self.tmp_dir, now=self.now,
                                                      remote_bytes=250, lyrics_keep=2).values()))

    def test_an_empty_cache(self):
        self.assertFalse(any(cache_files.prune_caches(os.path.join(self.tmp_dir, 'none')).values()))


class TestOtherCaches(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_prune_remote_art_keeps_the_newest_within_budget(self):
        folder = os.path.join(self.tmp_dir, 'remote-art')
        os.makedirs(folder)
        for i in range(5):
            path = os.path.join(folder, f'{i}.img')
            with open(path, 'wb') as f:
                f.write(b'x' * 100)
            os.utime(path, (1000 + i, 1000 + i))
        self.assertEqual(cache_files.prune_remote_art(self.tmp_dir, max_bytes=250), 3)
        self.assertEqual(sorted(os.listdir(folder)), ['3.img', '4.img'])
        self.assertEqual(cache_files.prune_remote_art(self.tmp_dir, max_bytes=250), 0)
        self.assertEqual(cache_files.prune_remote_art(os.path.join(self.tmp_dir, 'nowhere')), 0)

    def test_answer_paths_are_safe_names(self):
        self.assertEqual(cache_files.category_cache_path(self.tmp_dir, '98 85/../81'),
                         os.path.join(self.tmp_dir, 'categories', '98_85_.._81.json'))
        self.assertEqual(cache_files.landing_cache_path(self.tmp_dir),
                         os.path.join(self.tmp_dir, 'landing.json'))

    def test_answers_are_kept_and_age_out(self):
        path = cache_files.category_cache_path(self.tmp_dir, '1')
        self.assertIsNone(cache_files.read_answer(path, 60))
        kept = cache_files.write_answer(path, {'id': '1', 'groups': []}, self.tmp_dir)
        self.assertIn('cached', kept)
        self.assertEqual(cache_files.read_answer(path, 60)['id'], '1')
        # Older than allowed: as good as none.
        with open(path, 'r+', encoding='utf-8') as f:
            data = json.load(f)
            data['cached'] = '2000-01-01T00:00:00Z'
            f.seek(0)
            f.truncate()
            json.dump(data, f)
        self.assertIsNone(cache_files.read_answer(path, 60))
        # Unreadable: none.
        with open(path, 'w') as f:
            f.write('{not json')
        self.assertIsNone(cache_files.read_answer(path, 60))


    def test_a_kept_answer_is_patched_as_old_as_it_was(self):
        path = cache_files.artist_cache_path(self.tmp_dir, '1')
        cache_files.patch_answer(path, {'favourite': True}, self.tmp_dir)  # none kept: nothing
        self.assertFalse(os.path.exists(path))
        kept = cache_files.write_answer(path, {'id': '1', 'favourite': False}, self.tmp_dir)
        cache_files.patch_answer(path, {'favourite': True}, self.tmp_dir)
        with open(path, encoding='utf-8') as f:
            self.assertEqual(json.load(f), dict(kept, favourite=True))
        # The cache cleared since: not written.
        generation = store.cache_generation()
        store.bump_cache_generation()
        cache_files.patch_answer(path, {'favourite': False}, self.tmp_dir, generation)
        with open(path, encoding='utf-8') as f:
            self.assertIs(json.load(f)['favourite'], True)


if __name__ == '__main__':
    unittest.main()
