# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The library model: Library.load() over a generated demo library and small invented ones.

No display needed: the model is GObject and Gio only, and load() runs under asyncio.run.
"""

import asyncio
import gc
import json
import locale
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests import ROOT

from applemusic.library import (ROOT_FOLDER, Item, Library, SongOrder, Track, TrackRecord,
                                drop_index, entries_without, moved, order_for, parse)
from applemusic.library import model as model_module
from applemusic.library import reading as reading_module
from applemusic.library import records as records_module
from applemusic.library import songs as songs_module
from applemusic.library import text_keys as text_keys_module
from applemusic.library import words as words_module
from applemusic.library.folders import PENDING_HOLD
from applemusic.library.model import SECTIONS
from applemusic.library.objects import Group, reorder_entries


def load(cache_dir, library=None):
    """A Library loaded from cache_dir/library.json, config pointed there as demo mode does."""
    library = library or Library()
    with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': str(cache_dir)}):
        asyncio.run(library.load())
    return library


def track(track_id, title, index):
    return {'id': track_id, 'catalogId': None, 'title': title, 'artist': 'Test Artist',
            'album': 'Test Album', 'trackNumber': index + 1, 'discNumber': 1,
            'durationMs': 180000, 'durationLabel': '3:00', 'explicit': False, 'index': index,
            'thumb': None, 'type': 'library-songs'}


def build_songs(library):
    asyncio.run(library.build_songs())
    return library.songs


def album(album_id, title, track_ids):
    play = {'kind': 'album', 'id': album_id}
    return {'id': album_id, 'kind': 'album', 'title': title, 'subtitle': 'Test Artist',
            'year': 2001, 'genre': None, 'summary': None, 'art': None, 'thumb': None,
            'artColor': None, 'countLabel': f'{len(track_ids)} songs', 'explicit': False,
            'catalogId': None, 'url': None, 'play': play,
            'groups': [{'name': 'Disc 1', 'play': play,
                        'entries': [track(t, f'Song {t}', i) for i, t in enumerate(track_ids)]}]}


def write_library(cache_dir, albums, shelves=(), playlists=None, folders=None):
    data = {'version': 1, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
            'sections': {'albums': albums}, 'shelves': list(shelves)}
    if playlists is not None:
        data['sections']['playlists'] = playlists
    if folders is not None:
        data['folders'] = folders
    Path(cache_dir, 'library.json').write_text(json.dumps(data), encoding='utf-8')


def playlist(playlist_id, title=None):
    return Item({'id': playlist_id, 'kind': 'playlist', 'title': title or playlist_id,
                 'play': {'kind': 'playlist', 'id': playlist_id}, 'groups': []})


def plain(value):
    """A parsed library value with its TrackRecords made dicts again, to compare with JSON."""
    if isinstance(value, TrackRecord):
        return dict(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def collation_order(tracks, column, descending=False):
    """SongOrder's order as sorting by the keys themselves makes it: collation keys, numbers
    and (disc, track) pairs, ties broken by SongOrder.TIES."""
    def key(name, track):
        raw = track.raw
        if name == 'time':
            return records_module._number(raw.get('durationMs'))
        if name == 'year':
            return records_module._number(raw.get('year'))
        if name == 'track':
            return (records_module._number(raw.get('discNumber')),
                    records_module._number(raw.get('trackNumber')))
        return text_keys_module.collation_key(records_module._text(raw.get(name)) or '')

    positions = list(range(len(tracks)))
    for name in reversed(SongOrder.TIES[column]):
        positions.sort(key=lambda position, name=name: key(name, tracks[position]))
    positions.sort(key=lambda position: key(column, tracks[position]), reverse=descending)
    return [tracks[position] for position in positions]


def shape(tree):
    """A PlaylistTree's flat list as (kind, id, depth, ancestors)."""
    return [(node.kind, node.id, node.depth, node.ancestors()) for node in tree.flat]


class TestDemoLibrary(unittest.TestCase):
    """The generated demo library, loaded once for the whole class."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.cache = cls.temp_dir.name
        subprocess.run([sys.executable, str(ROOT / 'scripts' / 'demo_library.py'),
                        '--cache', cls.cache], check=True, capture_output=True)
        with open(os.path.join(cls.cache, 'library.json'), encoding='utf-8') as file:
            cls.data = json.load(file)
        cls.library = load(cls.cache)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def store_ids(self, store):
        return [item.id for item in store]

    def test_parse_matches_json_loads(self):
        with open(os.path.join(self.cache, 'library.json'), encoding='utf-8') as file:
            self.assertEqual(parse(file.read()), self.data)

    def test_artist_groups_of_library_albums_lose_their_tracks(self):
        # The artist page shows the album's own tracks; the artist's copies are dropped.
        for artist in self.library.artists:
            for group in artist.groups:
                with self.subTest(artist=artist.id, group=group.name):
                    self.assertIsNotNone(self.library.by_id('album', group.play['id']))
                    self.assertEqual(group.entries.get_n_items(), 0)

    def test_state_and_metadata(self):
        self.assertEqual(self.library.state, 'ready')
        self.assertEqual(self.library.generated, self.data['generated'])
        self.assertEqual(self.library.storefront, self.data['storefront'])

    def test_counts_match_library_json(self):
        sections = self.data['sections']
        for name in SECTIONS:
            with self.subTest(section=name):
                store = getattr(self.library, name)
                self.assertEqual(self.store_ids(store),
                                 [item['id'] for item in sections.get(name, [])])
        self.assertEqual([item.kind for item in self.library.videos], ['video'] * 6)
        self.assertEqual([(shelf.key, shelf.title, shelf.items.get_n_items())
                          for shelf in self.library.shelves],
                         [(shelf['key'], shelf['title'], len(shelf['items']))
                          for shelf in self.data['shelves']])
        self.assertIs(self.library.shelf('recently-added'), self.library.shelves[1])
        self.assertIsNone(self.library.shelf('no-such-shelf'))

    def test_item_mirrors_the_shape(self):
        raw = self.data['sections']['albums'][0]
        item = self.library.albums.get_item(0)
        self.assertIsInstance(item, Item)
        self.assertEqual(plain(item.raw), raw)  # its tracks are TrackRecords of the same
        self.assertEqual(item.play, raw['play'])
        for prop, key in [('id', 'id'), ('kind', 'kind'), ('title', 'title'),
                          ('subtitle', 'subtitle'), ('year', 'year'), ('genre', 'genre'),
                          ('summary', 'summary'), ('art', 'art'), ('thumb', 'thumb'),
                          ('art-color', 'artColor'), ('explicit', 'explicit'),
                          ('catalog-id', 'catalogId'), ('url', 'url')]:
            with self.subTest(prop=prop):
                self.assertEqual(item.get_property(prop), raw[key])
        self.assertEqual(item.count_label,
                         words_module.songs_text(raw['trackCount'], raw['durationMs']))
        station = self.library.radio.get_item(0)
        self.assertIsNone(self.data['sections']['radio'][0]['year'])
        self.assertEqual(station.year, 0)  # JSON null in an int property

    def test_captions_are_made_from_the_counts(self):
        """The demo writes numbers, as the sync does: the captions are the model's words, and
        fixed shelf titles are the app's same words."""
        for name in SECTIONS:
            for item in getattr(self.library, name):
                raw = item.raw
                if item.kind in ('album', 'playlist'):
                    expected = words_module.songs_text(raw['trackCount'], raw['durationMs'])
                elif item.kind == 'artist':
                    expected = words_module.albums_text(raw['albumCount'])
                else:
                    expected = ''  # stations and videos have no count
                with self.subTest(item=item.id):
                    self.assertNotIn('countLabel', raw)
                    self.assertEqual(item.count_label, expected)
        self.assertEqual([shelf.title for shelf in self.library.shelves],
                         [shelf['title'] for shelf in self.data['shelves']])

    def test_by_id(self):
        for name in SECTIONS:
            for item in getattr(self.library, name):
                self.assertIs(self.library.by_id(item.kind, item.id), item)
        first = self.library.albums.get_item(0)
        self.assertIsNone(self.library.by_id('playlist', first.id))
        self.assertIsNone(self.library.by_id('album', 'l.nothing'))

    def test_shelf_items_are_the_section_items(self):
        for shelf in self.library.shelves:
            for item in shelf.items:
                self.assertIs(self.library.by_id(item.kind, item.id), item)

    def test_songs_are_every_album_track_once(self):
        expected = []
        for raw in self.data['sections']['albums']:
            for group in raw['groups']:
                for entry in group['entries']:
                    if entry['id'] not in expected:
                        expected.append(entry['id'])
        self.assertEqual(self.library.song_count(), len(expected))
        songs = build_songs(self.library)
        self.assertTrue(self.library.songs_ready)
        self.assertIs(self.library.songs, songs)
        self.assertEqual([t.id for t in songs], expected)
        self.assertEqual(self.library.song_count(), len(expected))
        # The same Track objects as the albums' own groups.
        first_album = self.library.albums.get_item(0)
        self.assertIs(songs.get_item(0), first_album.groups[0].entries.get_item(0))

    def test_song_orders_are_the_collation_orders(self):
        """Every SongOrder order, list for list, is the one sorting by the collation keys and
        (disc, track) pairs themselves gives (SongOrder before it kept ranks), in the C
        locale and in a real one."""
        songs = list(build_songs(self.library))
        collate = locale.setlocale(locale.LC_COLLATE)
        self.addCleanup(locale.setlocale, locale.LC_COLLATE, collate)
        for name in ('C', 'en_GB.UTF-8', 'en_US.UTF-8'):
            try:
                locale.setlocale(locale.LC_COLLATE, name)
            except locale.Error:
                continue  # not installed here
            order = SongOrder(songs)
            asyncio.run(order.prepare('title'))
            for column in SongOrder.TIES:
                for descending in (False, True):
                    with self.subTest(locale=name, column=column, descending=descending):
                        self.assertEqual(
                            [t.id for t in order.tracks(column, descending)],
                            [t.id for t in collation_order(songs, column, descending)])

    def test_favourite_songs(self):
        flagged = [raw['id'] for raw in self.data['sections']['playlists']
                   if raw.get('attributes', {}).get('isFavourites')]
        self.assertEqual(len(flagged), 1)
        favourites = self.library.favourite_songs()
        self.assertIs(favourites, self.library.by_id('playlist', flagged[0]))
        self.assertTrue(favourites.favourites)
        self.assertEqual([item.id for item in self.library.playlists if item.favourites],
                         flagged)

    def test_playlist_tree(self):
        tree = self.library.playlist_tree()
        folders = {raw['id']: raw for raw in self.data['folders']}

        def title(child):
            return self.library.by_id(child['kind'], child['id']).title.casefold()

        def expected(folder_id, depth, ancestors):
            # As Apple Music lists them: Favourite Songs, folders, playlists, each by title.
            children = folders[folder_id]['children']
            favourites = [child for child in children if child['kind'] == 'playlist'
                          and self.library.by_id('playlist', child['id']).favourites]
            ordered = favourites + sorted(
                (child for child in children if child not in favourites),
                key=lambda child: (child['kind'] != 'folder', title(child)))
            nodes = []
            for child in ordered:
                nodes.append((child['kind'], child['id'], depth, ancestors))
                if child['kind'] == 'folder':
                    nodes += expected(child['id'], depth + 1, ancestors + [child['id']])
            return nodes

        self.assertEqual(shape(tree), expected(ROOT_FOLDER, 0, []))
        self.assertNotEqual(  # the order is the app's, not the file's
            [child.id for child in tree.root.children],
            [child['id'] for child in folders[ROOT_FOLDER]['children']])
        # Three folders, one inside another, and every playlist once, as its section Item.
        self.assertEqual([(node.item.title, node.depth) for node in tree.folders()],
                         [(folders[node.id]['title'], node.depth) for node in tree.folders()])
        self.assertEqual(sorted(node.depth for node in tree.folders()), [0, 0, 1])
        playlists = [node for node in tree.flat if node.kind == 'playlist']
        self.assertEqual(sorted(node.id for node in playlists),
                         sorted(self.store_ids(self.library.playlists)))
        for node in playlists:
            self.assertIs(node.item, self.library.by_id('playlist', node.id))
        # Nested: each node is among its parent's children, and the stores mirror them.
        for node in tree.flat:
            self.assertIn(node, node.parent.children)
        for folder_node in [tree.root] + tree.folders():
            self.assertIs(self.library.by_id('folder', folder_node.id), folder_node.item)
            self.assertEqual(folder_node.item.kind, 'folder')
            store = self.library.folder_items(folder_node.id)
            self.assertIs(store, folder_node.store)
            self.assertEqual(list(store), [child.item for child in folder_node.children])
        self.assertIs(tree.folder(ROOT_FOLDER), tree.root)
        self.assertEqual(tree.root.depth, -1)
        self.assertIsNone(self.library.folder_items('l.no-such-folder'))
        # Favourite Songs is in the tree like any playlist (the sidebar leaves it out).
        self.assertIn(self.library.favourite_songs(), [node.item for node in playlists])


class TestLaziness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = self.temp_dir.name

    def test_groups_wrap_on_first_access(self):
        raw = album('l.a1', 'First', ['i.1', 'i.2', 'i.3'])
        raw['thumb'] = '/nowhere/thumb/a1.jpg'
        raw['groups'].append({'name': 'Disc 2', 'play': raw['play'],
                              'entries': [dict(track('i.4', 'Four', 3), discNumber=2)]})
        write_library(self.cache, [raw])
        library = load(self.cache)
        item = library.albums.get_item(0)
        self.assertIsNone(item._groups)
        self.assertFalse(library.songs_ready)
        self.assertEqual(library.songs.get_n_items(), 0)  # nothing asked for it

        groups = item.groups
        self.assertIs(item.groups, groups)
        self.assertEqual([g.name for g in groups], ['Disc 1', 'Disc 2'])
        self.assertIsInstance(groups[0], Group)
        self.assertEqual(groups[0].play, raw['play'])
        tracks = list(groups[0].entries)
        self.assertTrue(all(isinstance(t, Track) for t in tracks))
        self.assertEqual([(t.id, t.title, t.index, t.track_number) for t in tracks],
                         [('i.1', 'Song i.1', 0, 1), ('i.2', 'Song i.2', 1, 2),
                          ('i.3', 'Song i.3', 2, 3)])
        first = tracks[0]
        self.assertEqual(first.get_property('duration-ms'), 180000)
        self.assertEqual(first.duration_label, '3:00')
        self.assertEqual(first.play, raw['play'])
        self.assertEqual(first.thumb, raw['thumb'])  # an album track draws its album's cover
        self.assertEqual(groups[1].entries.get_item(0).disc_number, 2)

    def test_songs_deduplicated_by_id(self):
        write_library(self.cache, [album('l.a1', 'One', ['i.1', 'i.2']),
                                   album('l.a2', 'Two', ['i.2', 'i.3', 'i.1'])])
        library = load(self.cache)
        self.assertEqual(library.song_count(), 3)
        self.assertEqual([t.id for t in build_songs(library)], ['i.1', 'i.2', 'i.3'])
        self.assertEqual([t.album for t in library.songs], ['Test Album'] * 3)
        self.assertEqual(library.songs.get_item(0).search_key, 'song i.1\ntest artist\ntest album')

    def test_favourites_flag(self):
        self.assertTrue(Item({'kind': 'playlist', 'attributes': {'isFavourites': True}}).favourites)
        for raw in ({'kind': 'playlist'}, {'attributes': None}, {'attributes': ['isFavourites']},
                    {'attributes': {'isFavourites': 'yes'}}, {'attributes': {}}):
            with self.subTest(raw=raw):
                self.assertFalse(Item(raw).favourites)
        write_library(self.cache, [album('l.a1', 'One', ['i.1'])])
        self.assertIsNone(load(self.cache).favourite_songs())

    def test_editable(self):
        """Songs can be added to library playlists, not to Favourite Songs, one whose canEdit
        is false, a catalog playlist or anything else."""
        self.assertTrue(Item({'id': 'p.1', 'kind': 'playlist'}).editable)
        self.assertTrue(Item({'id': 'l.pl1', 'kind': 'playlist'}).editable)  # the demo's
        self.assertTrue(Item({'id': 'p.1', 'kind': 'playlist', 'attributes': {}}).editable)
        for raw in ({'id': 'p.2', 'kind': 'playlist', 'attributes': {'isFavourites': True}},
                    {'id': 'p.3', 'kind': 'playlist', 'attributes': {'canEdit': False}},
                    {'id': 'pl.u-4', 'kind': 'playlist'}, {'id': 'l.a', 'kind': 'album'},
                    {'id': 'p.5', 'kind': 'folder'}, {'kind': 'playlist'}):
            with self.subTest(raw=raw):
                self.assertFalse(Item(raw).editable)

    def test_properties_notify(self):
        item = Item({'id': 'l.x', 'kind': 'album', 'title': 'Before'})
        seen = []
        item.connect('notify::title', lambda obj, _pspec: seen.append(obj.title))
        item.title = 'After'
        item.set_property('title', 'Again')
        self.assertEqual(seen, ['After', 'Again'])
        self.assertEqual(item.get_property('title'), 'Again')

    def test_merge_takes_a_fetched_item_in(self):
        # A shelf hit: no groups, little else. The engine's item() answer fills it in.
        item = Item({'id': 'l.a1', 'kind': 'album', 'title': 'Shelf Title',
                     'subtitle': 'Test Artist', 'play': {'kind': 'album', 'id': 'l.a1'}})
        self.assertEqual(item.groups, [])
        seen = []
        item.connect('notify', lambda obj, pspec: seen.append(pspec.name))
        answer = album('l.a1', 'Full Title', ['i.1', 'i.2'])
        answer.update(genre='Rock', summary='Notes', art='/x/art.jpg', thumb='/x/thumb.jpg',
                      artColor='#112233', cached='2026-01-01T00:00:00Z', kind='album',
                      id='l.a1')
        item.merge(answer)
        self.assertEqual((item.title, item.genre, item.summary, item.year), ('Full Title',
                         'Rock', 'Notes', 2001))
        self.assertEqual((item.art, item.thumb, item.art_color, item.count_label),
                         ('/x/art.jpg', '/x/thumb.jpg', '#112233', '2 songs'))
        self.assertEqual(item.raw['groups'], answer['groups'])
        self.assertEqual(item.raw['cached'], answer['cached'])
        self.assertEqual([t.id for t in item.groups[0].entries], ['i.1', 'i.2'])
        self.assertEqual(item.groups[0].entries.get_item(0).thumb, '/x/thumb.jpg')
        self.assertEqual(item.play, answer['play'])
        self.assertIn('title', seen)
        self.assertIn('art', seen)
        self.assertNotIn('subtitle', seen)  # unchanged: no notify
        # Merging again with the same answer changes nothing and notifies nothing.
        seen.clear()
        item.merge(answer)
        self.assertEqual(seen, [])

    def test_a_prerelease_album_out_since_is_out(self):
        # A shelf's album was to come (a day-old answer); the engine's item() answer, whole
        # with its groups, says it is out now: the flag and the date go, notified.
        item = Item({'id': '1724049700', 'kind': 'album', 'title': 'To Come',
                     'prerelease': True, 'releaseDate': '2099-12-04',
                     'play': {'kind': 'album', 'id': '1724049700'}})
        self.assertTrue(item.prerelease)
        seen = []
        item.connect('notify', lambda obj, pspec: seen.append(pspec.name))
        item.merge({'title': 'To Come', 'year': 2026})  # a part: the rest stays
        self.assertTrue(item.prerelease)
        answer = album('1724049700', 'To Come', ['1724049701'])
        item.merge(answer)
        self.assertFalse(item.prerelease)
        self.assertNotIn('releaseDate', item.raw)
        self.assertIn('prerelease', seen)
        # One still to come keeps them; its songs not out yet say so.
        answer = album('1724049700', 'To Come', ['1724049701', '1724049702'])
        answer.update(prerelease=True, releaseDate='2099-12-04')
        answer['groups'][0]['entries'][1]['unreleased'] = True
        item.merge(answer)
        self.assertTrue(item.prerelease)
        self.assertEqual([track.unreleased for track in item.groups[0].entries],
                         [False, True])


class TestLoading(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = self.temp_dir.name

    def watch(self, library):
        """The states library passes through and how often it emits 'changed'."""
        states, changed = [], []
        library.connect('notify::state', lambda obj, _pspec: states.append(obj.state))
        library.connect('changed', lambda _obj: changed.append(True))
        return states, changed

    def test_missing_file_is_empty(self):
        library = Library()
        states, changed = self.watch(library)
        load(self.cache, library)
        self.assertEqual(states, ['loading', 'empty'])
        self.assertEqual(len(changed), 1)
        self.assertEqual(library.albums.get_n_items(), 0)
        self.assertEqual(library.shelves, [])
        self.assertEqual(library.song_count(), 0)

    def test_unreadable_file_is_empty(self):
        Path(self.cache, 'library.json').write_text('{"version": 1, "sect', encoding='utf-8')
        with self.assertLogs('applemusic.library', 'WARNING'):
            library = load(self.cache)
        self.assertEqual(library.state, 'empty')

    def test_batches_keep_order(self):
        ids = [f'l.a{n}' for n in range(23)]
        write_library(self.cache, [album(i, i, []) for i in ids])
        library = Library()
        library.batch_size = 5
        states, changed = self.watch(library)
        load(self.cache, library)
        self.assertEqual([item.id for item in library.albums], ids)
        self.assertEqual(states, ['loading', 'ready'])
        self.assertEqual(len(changed), 1)

    def test_reload_refills_the_same_stores(self):
        write_library(self.cache, [album(f'l.a{n}', f'A{n}', [f'i.{n}']) for n in range(12)],
                      shelves=[{'key': 'recently-added', 'title': 'Recently Added',
                                'items': [album('l.a3', 'A3', [])]}])
        library = Library()
        library.batch_size = 5
        load(self.cache, library)
        albums, songs = library.albums, build_songs(library)
        self.assertEqual(songs.get_n_items(), 12)
        self.assertIs(library.shelf('recently-added').items.get_item(0),
                      library.by_id('album', 'l.a3'))

        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        write_library(other.name, [album('l.b1', 'B1', ['i.x', 'i.y'])])
        load(other.name, library)
        self.assertIs(library.albums, albums)
        self.assertEqual([item.id for item in albums], ['l.b1'])
        self.assertIs(library.songs, songs)  # built before, so kept current
        self.assertEqual([t.id for t in songs], ['i.x', 'i.y'])
        self.assertIsNone(library.by_id('album', 'l.a3'))
        self.assertIsNone(library.shelf('recently-added'))

    def test_syncing_notifies_only_changes(self):
        library = Library()
        seen = []
        library.connect('notify::syncing', lambda obj, _pspec: seen.append(obj.syncing))
        self.assertFalse(library.syncing)
        library.syncing = True
        library.syncing = True
        library.set_property('syncing', False)
        library.syncing = False
        self.assertEqual(seen, [True, False])

    def test_file_state_and_version(self):
        library = Library()
        self.assertEqual((library.file_state, library.version), ('', 0))  # nothing read yet
        load(self.cache, library)
        self.assertEqual((library.file_state, library.version), ('missing', 0))
        write_library(self.cache, [album('l.a1', 'A1', [])])  # version 1
        load(self.cache, library)
        self.assertEqual((library.file_state, library.version), ('ok', 1))
        path = Path(self.cache, 'library.json')
        path.write_text(json.dumps({'sections': {}}), encoding='utf-8')
        load(self.cache, library)
        self.assertEqual((library.file_state, library.version, library.state), ('ok', 0, 'ready'))
        # Nested past the decoder's recursion limit: unreadable like any damaged file. Where
        # that limit falls depends on the C stack size (Python 3.14 guards recursion by stack
        # depth, and containers often have a larger stack), so force the error rather than
        # rely on a deeply nested file failing on every machine.
        with mock.patch.object(reading_module, 'parse', side_effect=RecursionError('too deep')), \
                self.assertLogs('applemusic.library', 'WARNING'):
            load(self.cache, library)
        self.assertEqual((library.file_state, library.version, library.state),
                         ('unreadable', 0, 'empty'))
        for text in ('', '[1, 2]', '{"version": 2, "sect'):
            with self.subTest(text=text), self.assertLogs('applemusic.library', 'WARNING'):
                path.write_text(text, encoding='utf-8')
                load(self.cache, library)
                self.assertEqual(library.file_state, 'unreadable')

    def test_a_failed_load_is_empty_and_songs_are_asked_again(self):
        write_library(self.cache, [album('l.a1', 'A1', ['i.1', 'i.2'])])
        library = Library()
        states, changed = self.watch(library)

        async def load_and_ask():
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
                loading = asyncio.ensure_future(library.load())
                await asyncio.sleep(0)
            await library.build_songs()  # the load is to fill the Songs store
            await loading

        with mock.patch.object(Library, '_fill_songs', side_effect=RuntimeError('broken')), \
                self.assertRaises(RuntimeError):
            asyncio.run(load_and_ask())
        self.assertEqual(states, ['loading', 'empty'])
        self.assertEqual(len(changed), 1)
        self.assertFalse(library.songs_ready)
        load(self.cache, library)
        self.assertEqual([t.id for t in build_songs(library)], ['i.1', 'i.2'])
        self.assertTrue(library.songs_ready)

    def test_a_cancelled_reload_is_not_left_loading(self):
        write_library(self.cache, [album(f'l.a{n}', f'A{n}', [f'i.{n}']) for n in range(6)])
        library = load(self.cache)
        states, changed = self.watch(library)
        paused = []

        async def pause_for_good():  # the reload's first pause for a frame never ends
            paused.append(True)
            await asyncio.Event().wait()

        async def cancel_reload():
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
                reloading = asyncio.ensure_future(library.reload())
            while not paused:
                await asyncio.sleep(0.001)
            reloading.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await reloading

        with mock.patch.object(model_module, 'FRAME_BUDGET', 0), \
                mock.patch.object(model_module, 'yield_to_frames', pause_for_good):
            asyncio.run(cancel_reload())
        self.assertEqual(states, ['loading', 'empty'])
        self.assertEqual(len(changed), 1)
        self.assertTrue(gc.isenabled())  # the pause ended with it

    def test_a_newer_load_wins(self):
        write_library(self.cache, [album('l.old', 'Old', [])])
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        write_library(other.name, [album('l.new', 'New', [])])
        library = Library()
        states, changed = self.watch(library)
        # The first load's read waits in its thread until the second load has started: without
        # that, a quick thread could finish the first load before the second began.
        second_started = threading.Event()
        read = model_module._read_library

        def read_after_second_starts(path, *args):
            if Path(path).parent == Path(self.cache):
                second_started.wait(5)
            return read(path, *args)

        async def two_loads():
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
                first = asyncio.ensure_future(library.load())
                # The first load starts (its generation bumped); its read was submitted
                # when load() was called.
                await asyncio.sleep(0)
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': other.name}):
                second = asyncio.ensure_future(library.load())
                await asyncio.sleep(0)
            second_started.set()
            await asyncio.gather(first, second)

        with mock.patch.object(model_module, '_read_library', read_after_second_starts):
            asyncio.run(two_loads())
        self.assertEqual([item.id for item in library.albums], ['l.new'])
        self.assertEqual(library.state, 'ready')
        self.assertEqual(len(changed), 1)  # the overtaken load gave up without a word


class TestHolds(unittest.TestCase):
    """Library.holds(): whether an album or playlist of the catalog's is in the library, which
    an album's or playlist's page shows as Add or In Library."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = self.temp_dir.name
        tracks = album('l.a1', 'Harbour Lights', ['i.1', 'i.2'])
        for position, entry in enumerate(tracks['groups'][0]['entries']):
            entry['catalogId'] = str(500 + position)
        compilation = album('l.a2', 'Same Title', ['i.3'])
        compilation['catalogId'] = '700'
        apple = {'id': 'p.ap', 'kind': 'playlist', 'title': 'Invented Picks',
                 'subtitle': 'An Invented Curator', 'catalogId': 'pl.900',
                 'play': {'kind': 'playlist', 'id': 'p.ap'}, 'groups': []}
        catalog_shelf_item = {'id': '800', 'kind': 'album', 'title': 'Only On A Shelf',
                              'play': {'kind': 'album', 'id': '800'}}
        write_library(self.cache, [tracks, compilation], playlists=[apple],
                      shelves=[{'key': 'rec-1', 'title': 'Invented', 'items': [
                          catalog_shelf_item]}])
        self.library = load(self.cache)

    @staticmethod
    def catalog(item_id, kind='album', title='Harbour Lights', artist='Test Artist',
                songs=()):
        play = {'kind': kind, 'id': item_id}
        entries = [{'id': song, 'catalogId': song, 'title': 'Song', 'index': index}
                   for index, song in enumerate(songs)]
        return Item({'id': item_id, 'kind': kind, 'title': title, 'subtitle': artist,
                     'play': play, 'groups': [{'name': '', 'play': play, 'entries': entries}]
                     if entries else []})

    def test_by_its_own_id_or_its_catalog_id(self):
        self.assertTrue(self.library.holds(self.library.by_id('album', 'l.a1')))
        self.assertTrue(self.library.holds(self.catalog('700', title='Other Words')))
        self.assertTrue(self.library.holds(self.catalog('pl.900', kind='playlist')))
        self.assertFalse(self.library.holds(self.catalog('pl.901', kind='playlist')))
        # A shelf's album is not the library's.
        self.assertFalse(self.library.holds(self.catalog('800', title='Only On A Shelf')))
        self.assertFalse(self.library.holds(None))
        self.assertFalse(self.library.holds(self.catalog('42', kind='song')))

    def test_an_album_by_its_title_and_artist_and_a_song(self):
        # A library album carries no catalog id: its title and artist (case and accents
        # ignored) find it, and one of its songs confirms it when the catalog's has its songs.
        self.assertTrue(self.library.holds(self.catalog('600', title='harbour lights')))
        self.assertTrue(self.library.holds(self.catalog('600', songs=('501', '999'))))
        self.assertFalse(self.library.holds(self.catalog('600', songs=('998', '999'))))
        self.assertFalse(self.library.holds(self.catalog('600', artist='Someone Else')))
        # A shelf's album, subtitled with its year: its artistName is the artist.
        shelf = self.catalog('602', artist='2001')
        shelf.raw['artistName'] = 'Test Artist'
        self.assertTrue(self.library.holds(shelf))
        self.assertFalse(self.library.holds(self.catalog('601', title='Harbour Lights (Deluxe)',
                                                         songs=('500', '501'))))

    def test_one_just_added_until_the_library_lists_it(self):
        added = []
        self.library.connect('item-added', lambda _library, *args: added.append(args))
        picks = self.catalog('pl.902', kind='playlist')
        self.library.note_added(picks)
        self.assertEqual(added, [('playlist', 'pl.902')])
        self.assertTrue(self.library.holds(picks))
        # A reload that does not list it yet (Apple's listing lags) keeps the note.
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(self.library.reload())
        self.assertTrue(self.library.holds(picks))
        # Once listed the library answers by itself; a load (another account) forgets notes.
        data = json.loads(Path(self.cache, 'library.json').read_text(encoding='utf-8'))
        data['sections']['playlists'].append({
            'id': 'p.new', 'kind': 'playlist', 'title': 'Listed', 'catalogId': 'pl.902',
            'play': {'kind': 'playlist', 'id': 'p.new'}, 'groups': []})
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(self.library.reload())
        self.assertTrue(self.library.holds(picks))
        # The note went with that reload: once removed (elsewhere), it is not held.
        data['sections']['playlists'].pop()
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(self.library.reload())
        self.assertFalse(self.library.holds(picks))
        other = self.catalog('pl.903', kind='playlist')
        self.library.note_added(other)
        load(self.cache, self.library)
        self.assertFalse(self.library.holds(other))

    def test_held_item_is_what_holds_found(self):
        # The library's own Item a catalog one is found as: what its menu's Remove from
        # Library takes out.
        library = self.library
        own = library.by_id('album', 'l.a1')
        self.assertIs(library.held_item(own), own)
        self.assertIs(library.held_item(self.catalog('600', songs=('501',))), own)
        self.assertIs(library.held_item(self.catalog('700', title='Other Words')),
                      library.by_id('album', 'l.a2'))
        self.assertIs(library.held_item(self.catalog('pl.900', kind='playlist')),
                      library.by_id('playlist', 'p.ap'))
        for item in (self.catalog('pl.901', kind='playlist'), self.catalog('42', kind='song'),
                     self.catalog('800', title='Only On A Shelf'), None):
            self.assertIsNone(library.held_item(item))
        # One only noted as just added is held, but has no Item of the library's yet.
        picks = self.catalog('pl.902', kind='playlist')
        library.note_added(picks)
        self.assertTrue(library.holds(picks))
        self.assertIsNone(library.held_item(picks))


def playlist_with(playlist_id, track_ids):
    """A playlist's Item dict with these tracks, in this order (a song may be there twice)."""
    play = {'kind': 'playlist', 'id': playlist_id}
    return {'id': playlist_id, 'kind': 'playlist', 'title': f'Playlist {playlist_id}',
            'play': play, 'groups': [{'name': 'Tracks', 'play': play, 'entries': [
                dict(track(track_id, f'Song {track_id}', index), trackNumber=1)
                for index, track_id in enumerate(track_ids)]}]}


class TestReorder(unittest.TestCase):
    """A playlist's songs in a new order: the index arithmetic, Item.reorder() in place, and
    Library.reorder()'s order held through reloads until the file shows it."""

    def test_the_index_arithmetic(self):
        self.assertEqual(moved(4, 0, 2), [1, 2, 0, 3])
        self.assertEqual(moved(4, 3, 0), [3, 0, 1, 2])
        # A drop in a gap: before the song at the gap, or after the last; beside it, nothing.
        self.assertEqual(drop_index(1, 0), 0)
        self.assertEqual(drop_index(1, 4), 3)
        self.assertEqual(drop_index(1, 3), 2)
        self.assertIsNone(drop_index(1, 1))
        self.assertIsNone(drop_index(1, 2))

    def test_order_for_takes_a_song_held_twice_in_turn(self):
        entries = [{'id': 'a'}, {'id': 'b'}, {'id': 'a'}]
        self.assertEqual(order_for(entries, ['b', 'a', 'a']), [1, 0, 2])
        self.assertEqual(order_for(entries, ['a', 'a', 'b']), [0, 2, 1])
        self.assertIsNone(order_for(entries, ['a', 'b']))  # one short
        self.assertIsNone(order_for(entries, ['a', 'b', 'b']))
        self.assertIsNone(order_for(entries, ['a', 'b', 'a', 'c']))

    def test_reorder_entries_renumbers_only_what_moved(self):
        entries = [TrackRecord(track(t, t, i)) for i, t in enumerate('abcd')]
        arranged = reorder_entries(entries, [0, 2, 1, 3])
        self.assertEqual([entry['id'] for entry in arranged], ['a', 'c', 'b', 'd'])
        self.assertEqual([entry['index'] for entry in arranged], [0, 1, 2, 3])
        self.assertIs(arranged[0], entries[0])
        self.assertIs(arranged[3], entries[3])
        self.assertIsInstance(arranged[1], TrackRecord)
        self.assertEqual(dict(arranged[1]), dict(track('c', 'c', 2), index=1))
        self.assertEqual(reorder_entries([track('x', 'x', 0)], [0]), [track('x', 'x', 0)])

    def test_entries_without_takes_out_and_puts_back(self):
        raw = dict(playlist_with('p.1', ['a', 'b', 'c', 'd']), trackCount=4,
                   durationMs=4 * 180000)
        raw['groups'][0]['entries'][2] = TrackRecord(raw['groups'][0]['entries'][2])
        update = entries_without(raw, {1, 3, 9})
        entries = update['groups'][0]['entries']
        self.assertEqual([entry['id'] for entry in entries], ['a', 'c'])
        self.assertEqual([entry['index'] for entry in entries], [0, 1])  # the places now
        self.assertIsInstance(entries[1], TrackRecord)
        self.assertEqual((update['trackCount'], update['durationMs']), (2, 2 * 180000))
        self.assertEqual(raw['groups'][0]['entries'][3]['id'], 'd')  # raw itself untouched
        # Nothing to take out: raw's own groups and counts, as they are.
        again = entries_without(raw, ())
        self.assertIs(again['groups'], raw['groups'])
        self.assertEqual((again['trackCount'], again['durationMs']), (4, 4 * 180000))
        # The merge shows it: the rows go, and come back.
        item = Item(dict(raw))
        item.merge(update)
        self.assertEqual(item.track_ids(), ['a', 'c'])
        item.merge(entries_without(raw, ()))
        self.assertEqual(item.track_ids(), ['a', 'b', 'c', 'd'])
        # Without counts, none made up; not a list of one group, nothing.
        bare = playlist_with('p.2', ['a', 'b'])
        self.assertNotIn('trackCount', entries_without(bare, {0}))
        self.assertIsNone(entries_without(dict(bare, groups=[]), {0}))

    def test_item_reorder_keeps_its_objects_and_splices_once(self):
        item = Item(playlist_with('p.1', ['a', 'b', 'c', 'd', 'e']))
        group = item.groups[0]
        store = group.entries
        tracks = [store.get_item(n) for n in range(5)]
        splices = []
        store.connect('items-changed', lambda _s, *change: splices.append(change))
        told = []
        item.connect('groups-changed', lambda _item: told.append(True))
        notified = []
        tracks[3].connect('notify::index', lambda track, _pspec: notified.append(track.id))
        self.assertTrue(item.reorder(moved(5, 3, 1)))
        self.assertEqual(item.track_ids(), ['a', 'd', 'b', 'c', 'e'])
        self.assertEqual(splices, [(1, 3, 3)])  # the stretch that moved, one change
        self.assertEqual(told, [])
        self.assertIs(item.groups[0], group)
        self.assertIs(store.get_item(1), tracks[3])
        self.assertEqual([store.get_item(n).index for n in range(5)], [0, 1, 2, 3, 4])
        self.assertEqual(notified, ['d'])
        self.assertEqual([entry['id'] for entry in item.raw['groups'][0]['entries']],
                         ['a', 'd', 'b', 'c', 'e'])
        # Refused: not a permutation, not a playlist.
        self.assertFalse(item.reorder([0, 0, 1, 2, 3]))
        self.assertFalse(item.reorder([0, 1]))
        album_item = Item(album('l.a', 'A', ['x', 'y']))
        self.assertFalse(album_item.reorder([1, 0]))
        self.assertIsNone(album_item.track_ids())

    def test_the_order_held_through_reloads(self):
        library = Library()
        with tempfile.TemporaryDirectory() as cache:
            def reload(track_ids, hold_time=None):
                write_library(cache, [], playlists=[playlist_with('p.1', track_ids)])
                with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                    asyncio.run(library.reload())

            write_library(cache, [], playlists=[playlist_with('p.1', ['a', 'b', 'c'])])
            load(cache, library)
            item = library.by_id('playlist', 'p.1')
            store = item.groups[0].entries
            told = []
            item.connect('groups-changed', lambda _item: told.append(True))
            self.assertTrue(library.reorder(item, moved(3, 0, 2)))
            self.assertEqual(library.held_order('p.1'), ['b', 'c', 'a'])

            # A sync before Apple shows it: the order held, nothing changed on the page.
            reload(['a', 'b', 'c'])
            self.assertIs(library.by_id('playlist', 'p.1'), item)
            self.assertIs(item.groups[0].entries, store)
            self.assertEqual(item.track_ids(), ['b', 'c', 'a'])
            self.assertEqual(told, [])
            # Apple shows it: settled.
            reload(['b', 'c', 'a'])
            self.assertIsNone(library.held_order('p.1'))
            self.assertEqual(told, [])
            # Another song since (changed elsewhere): the file wins.
            library.reorder(item, moved(3, 2, 0))
            reload(['b', 'c', 'a', 'd'])
            self.assertIsNone(library.held_order('p.1'))
            self.assertEqual(item.track_ids(), ['b', 'c', 'a', 'd'])
            # Expired: the file wins; a load forgets every order held.
            with mock.patch.object(model_module, '_now', return_value=1000.0):
                library.reorder(item, moved(4, 0, 3))
            with mock.patch.object(model_module, '_now', return_value=1000.0 + PENDING_HOLD):
                reload(['b', 'c', 'a', 'd'])
            self.assertEqual(item.track_ids(), ['b', 'c', 'a', 'd'])
            library.reorder(library.by_id('playlist', 'p.1'), moved(4, 0, 3))
            load(cache, library)
            self.assertIsNone(library.held_order('p.1'))
            self.assertEqual(library.by_id('playlist', 'p.1').track_ids(), ['b', 'c', 'a', 'd'])

    def test_an_answer_takes_the_order_held(self):
        library = Library()
        with tempfile.TemporaryDirectory() as cache:
            write_library(cache, [], playlists=[playlist_with('p.1', ['a', 'b'])])
            load(cache, library)
            item = library.by_id('playlist', 'p.1')
            library.reorder(item, [1, 0])
            answer = playlist_with('p.1', ['a', 'b'])
            held = library.with_held_order(answer)
            self.assertEqual([entry['id'] for entry in held['groups'][0]['entries']],
                             ['b', 'a'])
            self.assertEqual([entry['index'] for entry in held['groups'][0]['entries']],
                             [0, 1])
            item.merge(held)
            self.assertEqual(item.track_ids(), ['b', 'a'])
            library.release_order('p.1')
            self.assertIs(library.with_held_order(answer), answer)
            other = {'kind': 'album', 'id': 'p.1'}
            self.assertIs(library.with_held_order(other), other)


class TestBuildSongs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = self.temp_dir.name
        self.ids = [f'i.{n}' for n in range(30)]
        write_library(self.cache, [album(f'l.a{n}', f'A{n}', self.ids[n * 3:n * 3 + 3])
                                   for n in range(10)])

    def test_batches_pause_and_splice_once(self):
        library = load(self.cache)
        spliced = []
        library.songs.connect('items-changed', lambda _store, *change: spliced.append(change))
        pauses = []
        yield_to_frames = model_module.yield_to_frames

        async def counting_yield():
            pauses.append(True)
            await yield_to_frames()

        # A zero budget pauses after every album; the splice gets a frame of its own.
        with mock.patch.object(model_module, 'FRAME_BUDGET', 0), \
                mock.patch.object(model_module, 'yield_to_frames', counting_yield):
            build_songs(library)
        self.assertEqual([t.id for t in library.songs], self.ids)
        self.assertEqual(len(pauses), 10 + 2)
        self.assertEqual(spliced, [(0, 0, 30)])
        self.assertTrue(library.songs_ready)
        build_songs(library)  # filled already: nothing happens
        self.assertEqual(spliced, [(0, 0, 30)])

    def test_asked_while_loading_the_load_fills_it(self):
        library = Library()
        ready = []
        library.connect('notify::songs-ready', lambda obj, _pspec: ready.append(obj.state))

        async def load_and_ask():
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
                loading = asyncio.ensure_future(library.load())
                await asyncio.sleep(0)  # the load has started
            self.assertEqual(library.state, 'loading')
            await library.build_songs()  # returns at once: the load will do it
            self.assertFalse(library.songs_ready)
            await loading

        asyncio.run(load_and_ask())
        self.assertEqual([t.id for t in library.songs], self.ids)
        self.assertEqual(ready, ['loading'])  # filled before the load reported 'ready'

    def test_a_load_during_the_build_refills_it(self):
        library = load(self.cache)
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        write_library(other.name, [album('l.b1', 'B1', ['i.x', 'i.y'])])

        async def build_then_reload():
            build = asyncio.ensure_future(library.build_songs())
            await asyncio.sleep(0)  # the build has paused after its first album
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': other.name}):
                await library.load()
            await build

        with mock.patch.object(model_module, 'FRAME_BUDGET', 0):
            asyncio.run(build_then_reload())
        self.assertEqual([t.id for t in library.songs], ['i.x', 'i.y'])
        self.assertTrue(library.songs_ready)

    def test_a_cancelled_build_is_asked_again(self):
        library = load(self.cache)

        async def cancel_build():
            build = asyncio.ensure_future(library.build_songs())
            await asyncio.sleep(0)  # paused after its first album
            build.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await build

        with mock.patch.object(model_module, 'FRAME_BUDGET', 0):
            asyncio.run(cancel_build())
        self.assertFalse(library.songs_ready)
        self.assertEqual([t.id for t in build_songs(library)], self.ids)
        self.assertTrue(library.songs_ready)

    def test_a_reload_changes_the_songs_store_only_where_it_changed(self):
        library = load(self.cache)
        songs = build_songs(library)
        before = list(songs)
        spliced = []
        songs.connect('items-changed', lambda _store, *change: spliced.append(change))
        # l.a4 gets a fourth song, and l.a8 goes.
        albums = [album(f'l.a{n}', f'A{n}', self.ids[n * 3:n * 3 + 3] + (['i.new'] if n == 4
                                                                           else []))
                  for n in range(10) if n != 8]
        write_library(self.cache, albums)
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(library.reload())
        after = list(songs)
        self.assertEqual([t.id for t in after],
                         self.ids[:15] + ['i.new'] + self.ids[15:24] + self.ids[27:])
        # l.a4's tracks are new Tracks (its groups changed), l.a8's gone; the rest stay put.
        self.assertEqual(sorted(spliced), [(12, 3, 4), (24, 3, 0)])
        kept = after[:12] + after[16:]
        self.assertTrue(all(a is b for a, b in zip(kept, before[:12] + before[15:24] + before[27:],
                                                   strict=True)))

    def test_the_store_wraps_an_album_only_for_a_song_asked_for(self):
        """The Songs store holds SongEntries: building it wraps no album's groups, and a
        song asked for is its album's own Track (the album's songs wrapped then)."""
        from applemusic.library import SongEntry

        library = load(self.cache)
        songs = build_songs(library)
        self.assertTrue(all(isinstance(entry, SongEntry) for entry in songs.entries))
        self.assertTrue(all(item._groups is None for item in library.albums))
        self.assertEqual([entry.id for entry in songs.entries], self.ids)
        self.assertEqual(songs.entries[4].title, 'Song i.4')
        track = songs.get_item(4)  # l.a1's second song
        second = library.by_id('album', 'l.a1')
        self.assertIs(track, second.groups[0].entries.get_item(1))
        self.assertIs(songs.get_item(4), track)
        self.assertEqual([item.id for item in library.albums if item._groups is not None],
                         ['l.a1'])
        self.assertEqual(track.play, {'kind': 'album', 'id': 'l.a1'})
        self.assertEqual(track.index, 1)
        # A reload that leaves the songs as they were keeps every entry.
        entries = list(songs.entries)
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(library.reload())
        self.assertTrue(all(a is b for a, b in zip(songs.entries, entries, strict=True)))

    def test_tracks_made_in_steps(self):
        from applemusic.library import SongEntry, make_song_tracks, song_track

        entries = [SongEntry(TrackRecord(track(f'i.{n}', f'Song {n}', n)),
                             (None, 0, {'kind': 'song', 'id': f'i.{n}'}, None))
                   for n in range(20)]
        yielded = []

        async def yield_to_frames():
            yielded.append(True)

        with mock.patch.object(songs_module, 'yield_to_frames', yield_to_frames):
            tracks = asyncio.run(make_song_tracks(entries, budget=-1))
            self.assertEqual(tracks, [song_track(entry) for entry in entries])
            self.assertEqual(len(yielded), 20)  # a frame after each: the budget spent
            asyncio.run(make_song_tracks(entries))
            self.assertEqual(len(yielded), 20)  # 20 songs: well within one frame's budget
        own = tracks[3]
        self.assertEqual(asyncio.run(make_song_tracks([own])), [own])  # a Track is itself

    def test_an_entry_reads_as_its_track_does(self):
        from applemusic.library import (SongEntry, SongModel, song_key, song_track,
                                        song_tracks)

        raw = TrackRecord(track('i.1', 'Lantern', 0))
        play = {'kind': 'song', 'id': 'i.1'}
        entry = SongEntry(raw, (None, 0, play, '/thumb/one.jpg'))
        own = song_track(entry)
        self.assertIsInstance(own, Track)
        self.assertIs(song_track(entry), own)  # a loose song's Track is made once
        self.assertIs(song_track(own), own)
        self.assertEqual((entry.id, entry.title, entry.artist, entry.album),
                         (own.id, own.title, own.artist, own.album))
        self.assertEqual(entry.search_key, own.search_key)
        self.assertEqual((own.play, own.thumb), (play, '/thumb/one.jpg'))
        self.assertEqual(song_key(entry), song_key(own))
        self.assertEqual(song_tracks([entry, own]), [own, own])
        model = SongModel([SongEntry(TrackRecord(track('i.0', 'Ember', 0)), (None, 0, {}, None)),
                           entry])
        self.assertEqual(model.find(own), (True, 1))
        self.assertEqual(model.find(Track({'id': 'i.9'})), (False, 0))
        self.assertIs(model.get_item(1), own)
        self.assertIsNone(model.get_item(2))

    def test_songs_matching_tests_only_what_a_shorter_text_matched(self):
        from applemusic.library import narrows, prepare_search_keys, songs_matching

        songs = [Track(track(f'i.{n}', title, n))
                 for n, title in enumerate(('Harbour Lights', 'Harbour', 'Lanterns'))]
        asyncio.run(prepare_search_keys(songs, step=2))
        self.assertTrue(all(song._search_key is not None for song in songs))
        self.assertEqual(songs_matching(songs, ''), [])
        found = songs_matching(songs, 'harb')
        self.assertEqual(found, songs[:2])
        self.assertTrue(narrows('harb', 'harbour l'))
        self.assertFalse(narrows('', 'harbour'))
        self.assertEqual(songs_matching(songs, 'harbour l', within=found), songs[:1])
        self.assertEqual(songs_matching(songs, 'lantern', within=found), [])

    def test_nothing_to_load_is_ready_and_empty(self):
        library = Library()
        load(tempfile.gettempdir() + '/no-such-apple-music-cache', library)
        self.assertEqual(build_songs(library).get_n_items(), 0)
        self.assertTrue(library.songs_ready)


class TestGenres(unittest.TestCase):
    """The Genres page's Items (genre_items(), Library.genres())."""

    def album(self, album_id, title, genre, thumb=None):
        return dict(album(album_id, title, []), genre=genre, thumb=thumb)

    def test_one_item_a_genre_by_name_with_its_count_and_first_cover(self):
        albums = [Item(self.album('l.a1', 'One', 'Shoegaze')),
                  Item(self.album('l.a2', 'Two', 'ambient', thumb='/t/2.jpg')),
                  Item(self.album('l.a3', 'Three', 'Shoegaze', thumb='/t/3.jpg')),
                  Item(self.album('l.a4', 'Four', None)),
                  Item(self.album('l.a5', 'Five', '  ')),
                  Item(self.album('l.a6', 'Six', 'Shoegaze', thumb='/t/6.jpg'))]
        items = model_module.genre_items(albums)
        self.assertEqual([item['title'] for item in items], ['ambient', 'Shoegaze'])
        shoegaze = items[1]
        self.assertEqual(shoegaze['id'], model_module.GENRE_PREFIX + 'Shoegaze')
        self.assertEqual(shoegaze['kind'], 'genre')
        self.assertEqual(shoegaze['albumCount'], 3)
        self.assertEqual(shoegaze['subtitle'], '3 albums')
        self.assertEqual(shoegaze['thumb'], '/t/3.jpg')  # the first album with a cover
        self.assertEqual(items[0]['subtitle'], '1 album')
        self.assertEqual(model_module.genre_items([]), [])

    def test_made_when_first_asked_and_kept_up_to_date_by_every_load(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            write_library(cache_dir, [self.album('l.a1', 'One', 'Shoegaze'),
                                      self.album('l.a2', 'Two', 'Ambient')])
            library = load(cache_dir)
            self.assertEqual(library._genres.get_n_items(), 0)  # not asked for: not made
            genres = library.genres()
            self.assertEqual([item.title for item in genres], ['Ambient', 'Shoegaze'])
            shoegaze = genres.get_item(1)
            self.assertEqual(shoegaze.kind, 'genre')
            self.assertEqual(shoegaze.subtitle, '1 album')
            notified = []
            shoegaze.connect('notify::subtitle', lambda *_args: notified.append(True))
            write_library(cache_dir, [self.album('l.a1', 'One', 'Shoegaze'),
                                      self.album('l.a3', 'Three', 'Shoegaze'),
                                      self.album('l.a4', 'Four', 'Nu-Jazz')])
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache_dir}):
                asyncio.run(library.reload())
            self.assertIs(library.genres(), genres)  # the same store
            self.assertEqual([item.title for item in genres], ['Nu-Jazz', 'Shoegaze'])
            self.assertIs(genres.get_item(1), shoegaze)  # a reload keeps the Item
            self.assertEqual(shoegaze.subtitle, '2 albums')
            self.assertEqual(notified, [True])
            load(cache_dir, library)  # a load makes new Items
            self.assertIsNot(genres.get_item(1), shoegaze)
            self.assertEqual(genres.get_item(1).title, 'Shoegaze')


def held_library():
    """An invented library.json's data: two albums (the second of one song), a playlist
    holding a song of each (the first by its catalog id alone, as a playlist's own entry),
    their artist, a music video, a playlist of Apple's and a shelf of the second album."""
    first = album('l.a1', 'Low Tide', ['i.1', 'i.2'])
    for position, entry in enumerate(first['groups'][0]['entries']):
        entry['catalogId'] = f'100000000{position + 1}'
    first['trackCount'], first['durationMs'] = 2, 360000
    second = album('l.a2', 'Single File', ['i.3'])
    held = {'id': 'p.pl1', 'kind': 'playlist', 'title': 'Undertows', 'trackCount': 2,
            'durationMs': 360000, 'play': {'kind': 'playlist', 'id': 'p.pl1'},
            'groups': [{'name': 'Tracks', 'play': {'kind': 'playlist', 'id': 'p.pl1'},
                        'entries': [dict(track('i.p1', 'Song i.1', 0), catalogId='1000000001'),
                                    track('i.3', 'Song i.3', 1)]}]}
    apples = {'id': 'p.pl2', 'kind': 'playlist', 'title': 'Apple Picks',
              'attributes': {'canEdit': False}, 'play': {'kind': 'playlist', 'id': 'p.pl2'},
              'groups': []}
    artist = {'id': 'l.art1', 'kind': 'artist', 'title': 'Test Artist', 'albumCount': 2,
              'play': {}, 'groups': [{'name': 'Low Tide', 'play': first['play'], 'entries': []},
                                     {'name': 'Single File', 'play': second['play'],
                                      'entries': []}]}
    video = {'id': 'i.v1', 'kind': 'video', 'title': 'Undertow (Video)',
             'catalogId': '1000000009', 'play': {'kind': 'musicVideo', 'id': '1000000009'}}
    return {'version': 2, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
            'sections': {'albums': [first, second], 'playlists': [held, apples],
                         'artists': [artist], 'videos': [video]},
            'shelves': [{'key': 'recently-added', 'title': '',
                         'items': [dict(second, groups=[]), dict(video)]}],
            'folders': [{'id': 'root', 'title': '', 'parent': None,
                         'children': [{'kind': 'playlist', 'id': 'p.pl2'},
                                      {'kind': 'playlist', 'id': 'p.pl1'}]}]}


class TestHide(unittest.TestCase):
    """Library.hide() and unhide(): the models leave out what was removed, at once and at
    every load while the file holds it, and let it go once a load no longer meets it."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = self.temp_dir.name
        self.write(held_library())
        self.library = load(self.cache)
        build_songs(self.library)

    def write(self, data):
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')

    def run_in_cache(self, start):
        """Run the coroutine start() makes with the cache pointed at the test's: a reload
        starts reading the moment it is called."""
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': str(self.cache)}):
            asyncio.run(start())

    def ids(self, store):
        return [item.id for item in store]

    def test_a_hidden_album_leaves_every_store_and_comes_back(self):
        library = self.library
        playlist = library.by_id('playlist', 'p.pl1')
        self.assertEqual(library.song_count(), 3)
        self.run_in_cache(lambda: library.hide({('album', 'l.a1')}))
        self.assertEqual(self.ids(library.albums), ['l.a2'])
        self.assertIsNone(library.by_id('album', 'l.a1'))
        self.assertEqual([track.id for track in library.songs], ['i.3'])
        self.assertEqual(library.song_count(), 1)
        self.assertIs(library.by_id('playlist', 'p.pl1'), playlist)  # kept, its entry gone
        self.assertEqual([track.id for group in playlist.groups for track in group.entries],
                         ['i.3'])
        # A sync's reload of a file that still holds it (Apple's listing lags) leaves it out.
        self.run_in_cache(library.reload)
        self.assertEqual(self.ids(library.albums), ['l.a2'])
        self.assertEqual(library.hidden, {('album', 'l.a1')})
        # A failed removal brings it back.
        self.run_in_cache(lambda: library.unhide({('album', 'l.a1')}))
        self.assertEqual(self.ids(library.albums), ['l.a1', 'l.a2'])
        self.assertEqual(library.song_count(), 3)
        self.assertEqual(library.hidden, frozenset())

    def test_a_load_that_no_longer_meets_it_lets_it_go(self):
        library = self.library
        self.run_in_cache(lambda: library.hide({('playlist', 'p.pl2')}))
        self.assertEqual(self.ids(library.playlists), ['p.pl1'])
        self.assertEqual([node.id for node in library.playlist_tree().flat], ['p.pl1'])
        data = held_library()
        data['sections']['playlists'].pop()
        self.write(data)  # the sync after Apple dropped it
        self.run_in_cache(library.reload)
        self.assertEqual(library.hidden, frozenset())
        self.assertEqual(self.ids(library.playlists), ['p.pl1'])

    def test_a_sign_outs_load_forgets_what_was_hidden_and_favoured(self):
        # Sign-out wipes the cache, then loads: nothing the account removed or favoured this
        # run is held over the next account's library.
        library = self.library
        self.run_in_cache(lambda: library.hide({('album', 'l.a1')}))
        self.assertTrue(library.set_favourite('l.a2', True))
        os.remove(Path(self.cache, 'library.json'))
        self.run_in_cache(library.load)
        self.assertEqual(library.hidden, frozenset())
        self.write(held_library())  # the next account's first sync
        self.run_in_cache(library.reload)
        self.assertEqual(self.ids(library.albums), ['l.a1', 'l.a2'])
        self.assertFalse(library.by_id('album', 'l.a2').favourite)

    def test_library_ids_by_id_and_catalog_id(self):
        library = self.library
        self.assertEqual(library.library_id('song', 'i.2'), 'i.2')
        self.assertEqual(library.library_id('song', '1000000002'), 'i.2')
        self.assertEqual(library.library_id('song', 'i.p1', '1000000001'), 'i.1')
        self.assertIsNone(library.library_id('song', 'i.9', '1000000099'))
        self.assertEqual(library.library_id('video', '1000000009', '1000000009'), 'i.v1')
        self.assertEqual(library.library_id('album', 'l.a2'), 'l.a2')
        self.assertIsNone(library.library_id('album', 'l.a9'))
        self.assertEqual(library.playlists_holding({'1000000001'}), ['p.pl1'])
        self.assertEqual(library.playlists_holding({'i.2'}), [])
        # The index follows the loads.
        self.run_in_cache(lambda: library.hide({('album', 'l.a1')}))
        self.assertIsNone(library.library_id('song', 'i.2'))


if __name__ == '__main__':
    unittest.main()
