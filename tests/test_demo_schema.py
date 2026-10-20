# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

import gi

from tests import ROOT

from applemusic.backend import config, normalize

gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf  # noqa: E402

REPO_DIR = str(ROOT)


# The numbers each kind of Item carries for its caption, as the normaliser writes them.
COUNTS = {'album': ('trackCount', 'durationMs'), 'playlist': ('trackCount', 'durationMs'),
          'artist': ('albumCount',), 'video': ('durationMs',)}


class TestDemoLibrarySchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Built once, through the command line as the scripts run it: drawing
        # the covers is most of this suite's time.
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.out_dir = cls.temp_dir.name
        cls.cli = subprocess.run(
            [sys.executable, os.path.join(REPO_DIR, 'scripts', 'demo_library.py'), '--cache',
             cls.out_dir],
            capture_output=True,
            text=True,
        )
        if cls.cli.returncode != 0:
            cls.temp_dir.cleanup()
            raise AssertionError(f'CLI failed: {cls.cli.stderr}')
        cls.lib_path = os.path.join(cls.out_dir, 'library.json')
        with open(cls.lib_path, encoding='utf-8') as f:
            cls.data = json.load(f)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_the_run_stamps_what_made_it_last(self):
        # demo_stamp.py, which the harness and demo.sh ask: this directory is current.
        stamp = subprocess.run(
            [sys.executable, os.path.join(REPO_DIR, 'scripts', 'demo_stamp.py'), self.out_dir])
        self.assertEqual(stamp.returncode, 0)

    def test_top_level_schema(self):
        self.assertEqual(self.data.get('version'), 4)  # sync.LIBRARY_VERSION
        self.assertEqual(self.data.get('storefront'), 'us')
        self.assertIn('generated', self.data)
        self.assertTrue(isinstance(self.data['generated'], str))
        self.assertIn('sections', self.data)
        self.assertIn('shelves', self.data)

    def test_sections_presence_and_counts(self):
        sections = self.data['sections']
        self.assertSetEqual(set(sections.keys()),
                            {'albums', 'artists', 'playlists', 'radio', 'videos'})

        # 40 albums, 15 artists, 13 playlists (Favourite Songs the last), 8 radio stations,
        # 6 music videos
        self.assertEqual(len(sections['albums']), 40)
        self.assertEqual(len(sections['artists']), 15)
        self.assertEqual(len(sections['playlists']), 13)
        self.assertEqual(len(sections['radio']), 8)
        self.assertEqual(len(sections['videos']), 6)

    def test_shelves_schema(self):
        shelves = self.data['shelves']
        self.assertEqual(len(shelves), 3)
        shelf_keys = [s.get('key') for s in shelves]
        self.assertEqual(shelf_keys, ['heavy-rotation', 'recently-added', 'made-for-you'])
        # A recommendation's reason, as the sync writes Apple's (its `subtitle`).
        self.assertTrue(shelves[2]['subtitle'])
        for shelf in shelves:
            self.assertIn('title', shelf)
            self.assertIn('items', shelf)
            self.assertGreater(len(shelf['items']), 0)
            for item in shelf['items']:
                self._validate_item(item)

    def _validate_track(self, track, expected_album=None, expected_artist=None):
        self.assertIsInstance(track, dict)
        for field in (
            'id', 'catalogId', 'title', 'artist', 'album',
            'trackNumber', 'discNumber', 'durationMs', 'durationLabel',
            'explicit', 'index', 'type'
        ):
            self.assertIn(field, track, f'Track missing field: {field}')
        self.assertEqual(track['type'], 'library-songs')  # the API's, as the sync keeps it

        self.assertTrue(isinstance(track['id'], str) and track['id'])
        self.assertTrue(isinstance(track['title'], str) and track['title'])
        self.assertTrue(isinstance(track['artist'], str) and track['artist'])
        self.assertTrue(isinstance(track['album'], str) and track['album'])
        self.assertIsInstance(track['trackNumber'], int)
        self.assertGreaterEqual(track['trackNumber'], 1)
        self.assertIsInstance(track['discNumber'], int)
        self.assertGreaterEqual(track['discNumber'], 1)
        self.assertIsInstance(track['durationMs'], int)
        self.assertGreater(track['durationMs'], 0)
        self.assertIsInstance(track['durationLabel'], str)
        self.assertRegex(track['durationLabel'], r'^\d+:\d{2}$')
        self.assertIsInstance(track['explicit'], bool)
        self.assertIsInstance(track['index'], int)
        self.assertGreaterEqual(track['index'], 0)

        if expected_album:
            self.assertEqual(track['album'], expected_album)
        if expected_artist:
            self.assertEqual(track['artist'], expected_artist)

    def _validate_item(self, item):
        self.assertIsInstance(item, dict)
        for field in (
            'id', 'kind', 'title', 'subtitle', 'year', 'genre',
            'summary', 'art', 'thumb', 'artColor', 'explicit',
            'catalogId', 'url', 'play', 'groups'
        ):
            self.assertIn(field, item, f'Item missing field: {field}')
        # Counts, never words: the app makes those (library.Item.count_text).
        self.assertNotIn('countLabel', item)
        for field in COUNTS.get(item['kind'], ()):
            self.assertIsInstance(item[field], int, f'{item["kind"]} {field}')

        self.assertIn(item['kind'], {'album', 'playlist', 'artist', 'station', 'video'})
        self.assertTrue(isinstance(item['id'], str) and item['id'])
        self.assertTrue(isinstance(item['title'], str) and item['title'])
        self.assertIsInstance(item['subtitle'], str)
        self.assertIsInstance(item['explicit'], bool)

        # art path exists on disk
        if item['art'] is not None:
            self.assertTrue(os.path.isabs(item['art']), f"Art path not absolute: {item['art']}")
            self.assertTrue(os.path.exists(item['art']), f"Art file does not exist: {item['art']}")
            self.assertGreater(os.path.getsize(item['art']), 1000)
            # And its thumbnail beside it, under the same name.
            self.assertTrue(os.path.exists(item['thumb']),
                            f"Thumb file does not exist: {item['thumb']}")
            self.assertEqual(os.path.basename(item['thumb']), os.path.basename(item['art']))
            self.assertLess(os.path.getsize(item['thumb']), os.path.getsize(item['art']))

        # artColor is a hex string
        if item['artColor'] is not None:
            self.assertRegex(item['artColor'], r'^#[0-9a-fA-F]{6}$')

        # play object
        self.assertIsInstance(item['play'], dict)
        self.assertIn('kind', item['play'])
        self.assertIn('id', item['play'])

        # groups
        self.assertIsInstance(item['groups'], list)
        for group in item['groups']:
            self.assertIn('name', group)
            self.assertIn('play', group)
            self.assertIn('entries', group)
            self.assertIsInstance(group['entries'], list)
            for track in group['entries']:
                self._validate_track(track)

    def test_albums_detail(self):
        albums = self.data['sections']['albums']
        two_disc_found = False

        for alb in albums:
            self._validate_item(alb)
            self.assertEqual(alb['kind'], 'album')
            self.assertEqual(alb['play']['kind'], 'album')
            self.assertEqual(alb['play']['id'], alb['id'])
            self.assertIsInstance(alb['year'], int)
            self.assertGreaterEqual(alb['year'], 2000)
            self.assertIsInstance(alb['genre'], str)

            # Check groups and track indexing
            groups = alb['groups']
            self.assertIn(len(groups), (1, 2))
            if len(groups) == 2:
                two_disc_found = True
                self.assertEqual(groups[0]['name'], 'Disc 1')
                self.assertEqual(groups[1]['name'], 'Disc 2')

            # Check 0-based sequential indexing across all tracks in the album
            total_tracks = []
            for g in groups:
                total_tracks.extend(g['entries'])
            self.assertGreaterEqual(len(total_tracks), 8)
            self.assertLessEqual(len(total_tracks), 25)
            for expected_idx, track in enumerate(total_tracks):
                self.assertEqual(track['index'], expected_idx)
                self.assertEqual(track['album'], alb['title'])
            self.assertEqual(alb['trackCount'], len(total_tracks))
            self.assertEqual(alb['durationMs'], sum(t['durationMs'] for t in total_tracks))

        self.assertTrue(two_disc_found, 'Expected at least one 2-disc album')

    def test_artists_detail(self):
        artists = self.data['sections']['artists']
        for artist in artists:
            self._validate_item(artist)
            self.assertEqual(artist['kind'], 'artist')
            self.assertEqual(artist['play']['kind'], 'artist')
            self.assertEqual(artist['play']['id'], artist['id'])

            self.assertEqual(artist['subtitle'], '')  # no word of the data's
            # Groups represent albums
            self.assertGreater(len(artist['groups']), 0)
            self.assertEqual(artist['albumCount'], len(artist['groups']))
            for group in artist['groups']:
                self.assertTrue(group['name'])
                self.assertEqual(group['play']['kind'], 'album')
                self.assertGreater(len(group['entries']), 0)
                for track in group['entries']:
                    self.assertEqual(track['artist'], artist['title'])

    def test_playlists_detail(self):
        playlists = self.data['sections']['playlists']
        for pl in playlists:
            self._validate_item(pl)
            self.assertEqual(pl['kind'], 'playlist')
            self.assertEqual(pl['play']['kind'], 'playlist')
            self.assertEqual(pl['play']['id'], pl['id'])
            self.assertEqual(len(pl['groups']), 1)
            group = pl['groups'][0]
            self.assertEqual(group['name'], 'Tracks')
            self.assertGreater(len(group['entries']), 0)
            for idx, track in enumerate(group['entries']):
                self.assertEqual(track['index'], idx)
            self.assertEqual(pl['trackCount'], len(group['entries']))

    def test_playlist_suggestions(self):
        # Each playlist has the songs Apple would suggest for it, as the engine keeps them
        # (normalize.playlist_suggestions' keys), none of them one it holds.
        real = normalize.playlist_suggestions({'results': {'suggested': [
            {'id': '1', 'type': 'songs',
             'attributes': {'name': 'S', 'artistName': 'A', 'albumName': 'B'}}]}},
            None)['items'][0]
        for pl in self.data['sections']['playlists']:
            with self.subTest(id=pl['id']):
                path = os.path.join(self.out_dir, 'suggestions', f"{pl['id']}.json")
                with open(path, encoding='utf-8') as f:
                    answer = json.load(f)
                self.assertIs(answer['demo'], True)
                self.assertEqual(len(answer['items']), 24)
                held = {entry['catalogId'] for entry in pl['groups'][0]['entries']}
                for item in answer['items']:
                    self.assertEqual(set(item), set(real))
                    self.assertNotIn(item['id'], held)
                    self.assertEqual(item['play'], {'kind': 'song', 'id': item['id']})

    def test_artist_pages(self):
        # Each hand-written artist has the catalog's page of them, as the engine keeps it
        # (normalize.artist_page's keys); every third one an invented banner on disk, 3:1,
        # the first artist's among them, the second without one (the screenshots show both).
        real = normalize.artist_page({}, None)
        banners = []
        for artist in self.data['sections']['artists']:
            with self.subTest(id=artist['id']):
                path = os.path.join(self.out_dir, 'artists', f"{artist['catalogId']}.json")
                with open(path, encoding='utf-8') as f:
                    answer = json.load(f)
                self.assertIs(answer['demo'], True)
                self.assertEqual(set(answer) - {'demo', 'cached'}, set(real))
                banners.append(answer['banner'])
                if answer['banner'] is not None:
                    banner = answer['banner']
                    self.assertEqual(set(banner), {'url', 'art', 'crop', 'width', 'height',
                                                   'color'})
                    _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(banner['art'])
                    self.assertEqual((width, height), (banner['width'], banner['height']))
                    self.assertEqual(width, 3 * height)
        self.assertIsNotNone(banners[0])
        self.assertIsNone(banners[1])
        self.assertEqual(sum(banner is not None for banner in banners), 5)

    def test_album_pages(self):
        # Each album has what the catalog would show under its tracks, as the engine keeps
        # it (normalize.album_page's keys), every shelf in Apple's order, More By untitled.
        real = normalize.album_page({}, None)
        for album in self.data['sections']['albums']:
            with self.subTest(id=album['id']):
                path = os.path.join(self.out_dir, 'albums', f"{album['catalogId']}.json")
                with open(path, encoding='utf-8') as f:
                    answer = json.load(f)
                self.assertIs(answer['demo'], True)
                self.assertEqual(set(answer) - {'demo', 'cached'}, set(real))
                self.assertEqual(answer['id'], album['catalogId'])
                self.assertEqual(set(answer['release']),
                                 {'releaseDate', 'copyright', 'recordLabel'})
                self.assertTrue(answer['release']['releaseDate'].startswith(str(album['year'])))
                keys = [shelf['key'] for shelf in answer['shelves']]
                self.assertEqual(keys, [key for key in normalize.ALBUM_SHELVES if key in keys])
                self.assertIn('other-versions', keys)
                self.assertIn('related-albums', keys)
                for shelf in answer['shelves']:
                    self.assertEqual(shelf['title'] == '', shelf['key'] == 'more-by-artist')
                    self.assertTrue(shelf['items'])
                    self.assertNotIn(album['id'], [item['id'] for item in shelf['items']])
        # The first album, which the screenshots open, has every shelf.
        first = self.data['sections']['albums'][0]
        with open(os.path.join(self.out_dir, 'albums', f"{first['catalogId']}.json"),
                  encoding='utf-8') as f:
            self.assertEqual([shelf['key'] for shelf in json.load(f)['shelves']],
                             list(normalize.ALBUM_SHELVES))

    def test_radio_page(self):
        # The Radio page's answer, as the engine keeps it (normalize.radio_shelves' shape):
        # the live stations first, every shelf something in it, each station and show with
        # the keys the normaliser gives one, and each show's page beside it.
        with open(os.path.join(self.out_dir, 'radio.json'), encoding='utf-8') as f:
            answer = json.load(f)
        self.assertIs(answer['demo'], True)
        self.assertEqual(set(answer) - {'demo', 'cached'}, {'shelves'})
        shelves = answer['shelves']
        self.assertEqual([shelf.get('live', False) for shelf in shelves],
                         [True] + [False] * (len(shelves) - 1))
        station = set(normalize.normalize_station({'id': 'ra.1', 'attributes': {'name': 'S'}}))
        category = set(normalize.normalize_category({'id': '1', 'attributes': {'name': 'C'}}))
        kinds = set()
        for shelf in shelves:
            self.assertTrue(shelf['key'] and shelf['title'] and shelf['items'])
            for item in shelf['items']:
                kinds.add(item['kind'])
                if item['kind'] == 'station':
                    self.assertEqual(set(item), station)
                    self.assertEqual(item['play'], {'kind': 'station', 'id': item['id']})
                elif item['kind'] == 'category':
                    self.assertEqual(set(item) - {'thumb'}, category)
                    path = os.path.join(self.out_dir, 'categories', f"{item['id']}.json")
                    with open(path, encoding='utf-8') as f:
                        page = json.load(f)
                    self.assertIs(page['demo'], True)
                    self.assertEqual(page['title'], item['title'])
                    self.assertTrue(page['shelves'][0]['items'])
        self.assertEqual(kinds, {'station', 'category', 'album', 'video'})

    def test_artist_pages_and_the_shows_they_host(self):
        # Each artist's page has its shelves in Apple's order; every other one, the first
        # (which the screenshots open) among them, a Radio Shows shelf of one show, a category
        # tile as the normaliser makes one, whose page lists its episodes and playlists.
        category = set(normalize.normalize_category({'id': '1', 'attributes': {'name': 'C'}}))
        hosts = []
        for artist in self.data['sections']['artists'][:2]:
            with self.subTest(id=artist['catalogId']):
                path = os.path.join(self.out_dir, 'artists', f"{artist['catalogId']}.json")
                with open(path, encoding='utf-8') as f:
                    answer = json.load(f)
                keys = [shelf['key'] for shelf in answer['shelves']]
                self.assertEqual(keys, [key for key in normalize.ARTIST_SHELVES if key in keys])
                shows = [shelf for shelf in answer['shelves'] if shelf['key'] == 'radio-shows']
                hosts.append(bool(shows))
                if not shows:
                    continue
                show = shows[0]['items'][0]
                self.assertEqual(set(show) - {'thumb'}, category)
                self.assertEqual(show['kind'], 'category')
                with open(os.path.join(self.out_dir, 'categories', f"{show['id']}.json"),
                          encoding='utf-8') as f:
                    page = json.load(f)
                self.assertIs(page['demo'], True)
                self.assertEqual(page['title'], show['title'])
                self.assertEqual([{item['kind'] for item in shelf['items']}
                                  for shelf in page['shelves']], [{'station'}, {'playlist'}])
        self.assertEqual(hosts, [True, False])

    def test_charts_page(self):
        # The Charts page's answer, as the engine keeps it (normalize.charts_shelves' shape):
        # every chart in the page's order, the rankings ranked, Top Songs a list of songs with
        # their albums, and the Daily Top 100 and City Charts playlists with their tracks, so
        # their pages open in the demo.
        with open(os.path.join(self.out_dir, 'charts.json'), encoding='utf-8') as f:
            answer = json.load(f)
        self.assertIs(answer['demo'], True)
        self.assertEqual(set(answer) - {'demo', 'cached'}, {'shelves'})
        shelves = answer['shelves']
        self.assertEqual([shelf['chart'] for shelf in shelves], list(normalize.CHART_ORDER))
        for shelf in shelves:
            self.assertEqual(shelf['key'], 'charts-' + shelf['chart'])
            self.assertTrue(shelf['title'] and shelf['items'])
            self.assertEqual(shelf.get('ranked', False),
                             shelf['chart'] in normalize.RANKED_CHARTS)
            self.assertEqual(shelf.get('form'), 'songs' if shelf['chart'] == 'songs' else None)
        songs = shelves[0]['items']
        self.assertEqual({item['kind'] for item in songs}, {'song'})
        self.assertTrue(all(item['album'] and item['play']['kind'] == 'song' for item in songs))
        for shelf in shelves[3:5]:  # the Daily Top 100 and City Charts
            for item in shelf['items']:
                self.assertEqual(item['kind'], 'playlist')
                self.assertTrue(item['groups'][0]['entries'])
                self.assertTrue(os.path.exists(item['thumb']))

    def test_recently_played(self):
        # Home's Recently Played, as the engine keeps it (normalize.recently_played's
        # shape): the library's own albums, playlists and station, without track lists.
        with open(os.path.join(self.out_dir, 'recent-played.json'), encoding='utf-8') as f:
            answer = json.load(f)
        self.assertIs(answer['demo'], True)
        self.assertEqual(set(answer) - {'demo', 'cached'}, {'items'})
        library = {(item['kind'], item['id'])
                   for name in ('albums', 'playlists', 'radio')
                   for item in self.data['sections'][name]}
        self.assertEqual({item['kind'] for item in answer['items']},
                         {'album', 'playlist', 'station'})
        for item in answer['items']:
            self._validate_item(item)
            self.assertEqual(item['groups'], [])
            self.assertIn((item['kind'], item['id']), library)

    def test_one_favourites_playlist(self):
        # The flag the app looks for (applemusic.library.FAVOURITES) is on one playlist only, and
        # no other item carries attributes.
        flagged = [pl for pl in self.data['sections']['playlists']
                   if pl.get('attributes', {}).get('isFavourites') is True]
        self.assertEqual([pl['title'] for pl in flagged], ['Favourite Songs'])
        self.assertEqual(flagged[0]['attributes'], {'isFavourites': True})
        self.assertGreater(len(flagged[0]['groups'][0]['entries']), 20)
        others = [item for section in self.data['sections'].values() for item in section
                  if item is not flagged[0]]
        self.assertFalse([item['id'] for item in others if 'attributes' in item])

    def test_dates_added_and_favourites(self):
        # Every album, playlist (Favourite Songs aside) and video has an invented `added`,
        # as Apple writes it; Recently Added's albums are the newest, in the shelf's order.
        sections = self.data['sections']
        dated = [item for name in ('albums', 'playlists', 'videos') for item in sections[name]
                 if not (item.get('attributes') or {}).get('isFavourites')]
        for item in dated:
            self.assertRegex(item['added'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
            self.assertEqual(normalize.date_added({'dateAdded': item['added']}), item['added'])
        shelf = next(s for s in self.data['shelves'] if s['key'] == 'recently-added')
        newest = [item['added'] for item in shelf['items']]
        self.assertEqual(newest, sorted(newest, reverse=True))
        shelf_ids = {item['id'] for item in shelf['items']}
        older = [item['added'] for item in dated if item['id'] not in shelf_ids]
        self.assertLess(max(older), min(newest))
        # The favourites: Favourite Songs' songs by catalog id, and ids the library has.
        favourites = self.data['favourites']
        self.assertEqual(set(favourites), {'songs', 'albums', 'playlists', 'videos'})
        playlist = next(item for item in sections['playlists']
                        if (item.get('attributes') or {}).get('isFavourites'))
        self.assertEqual(favourites['songs'],
                         [entry['catalogId'] for entry in playlist['groups'][0]['entries']])
        for name in ('albums', 'playlists', 'videos'):
            known = {value for item in sections[name]
                     for value in (item['id'], item.get('catalogId')) if value}
            self.assertTrue(favourites[name])
            self.assertLessEqual(set(favourites[name]), known, name)

    def test_folders(self):
        # library.json's folders: the "root" entry lists the top level; three folders, one of
        # them inside another; every playlist in exactly one children list.
        folders = self.data['folders']
        by_id = {folder['id']: folder for folder in folders}
        self.assertEqual(len(by_id), len(folders))
        self.assertIsNone(by_id['root']['parent'])
        others = [folder for folder in folders if folder['id'] != 'root']
        self.assertEqual(len(others), 3)
        self.assertEqual(sorted(folder['parent'] != 'root' for folder in others),
                         [False, False, True])
        listed = []
        for folder in folders:
            self.assertEqual(set(folder), {'id', 'title', 'parent', 'children'})
            self.assertTrue(isinstance(folder['title'], str) and folder['title'])
            for child in folder['children']:
                self.assertEqual(set(child), {'kind', 'id'})
                self.assertIn(child['kind'], ('folder', 'playlist'))
                listed.append((child['kind'], child['id']))
                if child['kind'] == 'folder':
                    self.assertEqual(by_id[child['id']]['parent'], folder['id'])
        playlist_ids = [pl['id'] for pl in self.data['sections']['playlists']]
        self.assertEqual(sorted(listed), sorted([('folder', folder['id']) for folder in others]
                                                + [('playlist', pid) for pid in playlist_ids]))
        top = [child['kind'] for child in by_id['root']['children']]
        self.assertIn('playlist', top)  # loose playlists, not only folders

    def test_radio_stations_detail(self):
        radio = self.data['sections']['radio']
        for st in radio:
            self._validate_item(st)
            self.assertEqual(st['kind'], 'station')
            self.assertEqual(st['play']['kind'], 'station')
            self.assertEqual(st['play']['id'], st['id'])
            self.assertEqual(st['groups'], [])

    def test_music_videos_detail(self):
        # The Item shape the sync gives a library music video (normalize_item): a song's
        # fields, played as MusicKit's musicVideo, with 16:9 artwork.
        videos = self.data['sections']['videos']
        artists = {artist['title'] for artist in self.data['sections']['artists']}
        self.assertEqual(len({video['id'] for video in videos}), len(videos))
        for video in videos:
            self._validate_item(video)
            self.assertEqual(video['kind'], 'video')
            self.assertEqual(video['play'], {'kind': 'musicVideo', 'id': video['id']})
            self.assertEqual(video['groups'], [])
            self.assertIsNone(video['summary'])
            self.assertIn(video['subtitle'], artists)
            self.assertGreater(video['durationMs'], 0)
            _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(video['art'])
            self.assertEqual((width, height), (config.COVER_SIZE, config.COVER_SIZE * 9 // 16))
            _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(video['thumb'])
            self.assertEqual((width, height), (config.THUMB_SIZE, config.THUMB_SIZE * 9 // 16))

    def test_the_demo_has_the_normalisers_shapes(self):
        # Each kind of Item has the keys the real sync gives it (normalize), no more, no less,
        # apart from this app's own additions (library.json's `attributes`, `artUrl`, and a
        # playlist's `modified`).
        added = '2026-01-01T00:00:00Z'  # a library resource's dateAdded: the Item's `added`
        real = {
            'album': normalize.normalize_album({'id': 'l.a', 'attributes': {
                'name': 'A', 'dateAdded': added}}),
            'playlist': normalize.normalize_playlist({'id': 'p.1', 'attributes': {
                'name': 'P', 'dateAdded': added}}),
            'artist': normalize.normalize_artist({'id': 'l.r', 'attributes': {'name': 'R'}}),
            'station': normalize.normalize_station({'id': 'ra.1', 'attributes': {'name': 'S'}}),
            'video': normalize.normalize_item({'id': '1', 'type': 'library-music-videos',
                                               'attributes': {'name': 'V',
                                                              'dateAdded': added}}),
        }
        # Favourite Songs is Apple's own: no date of its being added.
        favourites = next(item for item in self.data['sections']['playlists']
                          if (item.get('attributes') or {}).get('isFavourites'))
        self.assertNotIn('added', favourites)
        favourites = dict(favourites, added=added)
        additions = {'attributes', 'artUrl', 'modified'}
        for name, items in self.data['sections'].items():
            if name == 'songs':
                continue  # Tracks, not Items
            for item in items:
                if (item.get('attributes') or {}).get('isFavourites'):
                    item = favourites
                with self.subTest(section=name, id=item['id']):
                    self.assertEqual(set(item) - additions, set(real[item['kind']]))

    def test_artwork_at_config_sizes(self):
        with open(os.path.join(self.out_dir, 'art', '.sizes'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'cover': config.COVER_SIZE, 'thumb': config.THUMB_SIZE})
        album = self.data['sections']['albums'][0]
        _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(album['art'])
        self.assertEqual((width, height), (config.COVER_SIZE, config.COVER_SIZE))
        _fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(album['thumb'])
        self.assertEqual((width, height), (config.THUMB_SIZE, config.THUMB_SIZE))

    def test_cli_execution(self):
        self.assertEqual(self.cli.returncode, 0, f'CLI failed: {self.cli.stderr}')
        self.assertIn('demo library: 40 albums', self.cli.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, 'library.json')))
        self.assertTrue(os.path.isdir(os.path.join(self.out_dir, 'art')))


class TestGeneratedAlbums(unittest.TestCase):
    """--albums N: the hand-written albums, then generated ones (no drawing here)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'demo_library', os.path.join(REPO_DIR, 'scripts', 'demo_library.py'))
        cls.demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.demo)

    def test_default_is_the_hand_written_library(self):
        artists, albums = self.demo.generated_albums(len(self.demo.ALBUMS_DATA))
        self.assertEqual(artists, self.demo.ARTISTS_DATA)
        self.assertEqual(albums, self.demo.ALBUMS_DATA)

    def test_generated_albums(self):
        artists, albums = self.demo.generated_albums(300)
        self.assertEqual(len(albums), 300)
        self.assertEqual(albums[:40], self.demo.ALBUMS_DATA)
        self.assertEqual(artists[:15], self.demo.ARTISTS_DATA)
        self.assertEqual(len({album['title'] for album in albums}), 300)
        self.assertEqual(len({artist['name'] for artist in artists}), len(artists))
        for album in albums:
            self.assertLess(album['artist_idx'], len(artists))
            self.assertTrue(album['discs'] and all(album['discs']))
        # Every generated artist has an album, and the same count gives the same library.
        self.assertEqual({album['artist_idx'] for album in albums}, set(range(len(artists))))
        self.assertEqual(self.demo.generated_albums(300), (artists, albums))

    def test_tracks_option_sizes_the_generated_albums(self):
        # --tracks N: the library holds N songs in all, the hand-written albums untouched.
        artists, albums = self.demo.generated_albums(300, tracks=4000)
        self.assertEqual(sum(len(disc) for album in albums for disc in album['discs']), 4000)
        self.assertEqual(albums[:40], self.demo.ALBUMS_DATA)
        self.assertEqual(len(albums), 300)
        generated = [len(album['discs'][0]) for album in albums[40:]]
        self.assertTrue(all(count >= 1 for count in generated))
        self.assertLessEqual(max(generated) - min(generated), 10)
        with self.assertRaises(ValueError):
            self.demo.generated_albums(300, tracks=100)

    def test_generated_song_titles_are_distinct(self):
        # As a real library's nearly all are, so collating them costs what it would; the
        # generated ones differ from the hand-written ones too.
        _artists, albums = self.demo.generated_albums(1000, tracks=12000)
        written = {song for album in albums[:40] for disc in album['discs'] for song in disc}
        generated = [song for album in albums[40:] for disc in album['discs'] for song in disc]
        self.assertEqual(len(generated), 12000 - sum(
            len(disc) for album in albums[:40] for disc in album['discs']))
        self.assertEqual(len(set(generated)), len(generated))
        self.assertFalse(written & set(generated))

    def test_generated_playlists(self):
        # --playlists N: the hand-written playlists, then invented ones, N with Favourite
        # Songs counted; the same N gives the same playlists.
        playlists = self.demo.generated_playlists(50)
        self.assertEqual(len(playlists), 49)
        self.assertEqual(playlists[:12], self.demo.PLAYLISTS_DATA)
        self.assertEqual(len({playlist['title'] for playlist in playlists}), 49)
        genres = {artist['genre'] for artist in self.demo.ARTISTS_DATA}
        for playlist in playlists[12:]:
            self.assertEqual(set(playlist),
                             {'title', 'subtitle', 'genre', 'summary', 'filter_genres'})
            self.assertIn(playlist['genre'], genres)
            self.assertTrue(set(playlist['filter_genres']) <= genres)
            self.assertIn(playlist['genre'], playlist['filter_genres'])
        self.assertEqual(self.demo.generated_playlists(50), playlists)
        self.assertEqual(self.demo.generated_playlists(13), self.demo.PLAYLISTS_DATA)


if __name__ == '__main__':
    unittest.main()
