# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

import os
import shutil
import tempfile
import unittest

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import art_cache, normalize

# The sizes these tests were written against (the extension's defaults). The
# app's own defaults come from config; test_art_cache's TestArtSizes covers those.
UPSTREAM_SIZES = {'cover': 512, 'thumb': 256}


class TestSync(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_format_duration(self):
        self.assertEqual(normalize.format_duration(0), '0:00')
        self.assertEqual(normalize.format_duration(-10), '0:00')
        self.assertEqual(normalize.format_duration(45000), '0:45')
        self.assertEqual(normalize.format_duration(216000), '3:36')
        self.assertEqual(normalize.format_duration(3600000), '1:00:00')
        self.assertEqual(normalize.format_duration(3661000), '1:01:01')

    def test_format_color(self):
        self.assertIsNone(normalize.format_color(None))
        self.assertIsNone(normalize.format_color(''))
        self.assertEqual(normalize.format_color('1a1a1a'), '#1a1a1a')
        self.assertEqual(normalize.format_color('#1a1a1a'), '#1a1a1a')

    def test_strip_html(self):
        self.assertIsNone(normalize.strip_html(None))
        self.assertIsNone(normalize.strip_html(''))
        self.assertEqual(normalize.strip_html('<p>Hello <b>World</b>&amp;Friends</p>'),
                         'Hello World&Friends')
        # Line breaks and paragraphs keep their words apart.
        self.assertEqual(normalize.strip_html(
            'First paragraph.<br><br>Second.<p>Third</p><p class="x">Fourth</p>'),
            'First paragraph.\n\nSecond.\n\nThird\n\nFourth')
        self.assertEqual(normalize.strip_html('One<br/>two <BR> three'), 'One\ntwo\nthree')
        self.assertIsNone(normalize.strip_html('<p></p><br>'))

    def test_normalize_track(self):
        raw = {
            'id': '1724040711',
            'type': 'songs',
            'attributes': {
                'name': 'Heroes Get Remembered',
                'artistName': 'Paper Parachutes',
                'albumName': 'Static Skyline',
                'trackNumber': 3,
                'discNumber': 1,
                'durationInMillis': 216000,
                'contentRating': 'explicit',
                'playParams': {'catalogId': '1724040711'},
            },
        }
        track = normalize.normalize_track(raw, index=2)
        self.assertEqual(track['id'], '1724040711')
        self.assertEqual(track['catalogId'], '1724040711')
        self.assertEqual(track['title'], 'Heroes Get Remembered')
        self.assertEqual(track['artist'], 'Paper Parachutes')
        self.assertEqual(track['album'], 'Static Skyline')
        self.assertEqual(track['trackNumber'], 3)
        self.assertEqual(track['discNumber'], 1)
        self.assertEqual(track['durationMs'], 216000)
        self.assertEqual(track['durationLabel'], '3:36')
        self.assertTrue(track['explicit'])
        self.assertEqual(track['index'], 2)
        self.assertIsNone(track['thumb'])
        self.assertEqual(track['type'], 'songs')
        self.assertIsNone(track['genre'])  # none given
        self.assertIsNone(track['year'])

    def test_a_track_keeps_its_genre_and_year(self):
        # The tables' Genre and Year columns: the first of genreNames, releaseDate's year.
        track = normalize.normalize_track({'id': 'i.1', 'type': 'library-songs', 'attributes': {
            'name': 'Glass Tide', 'genreNames': ['Shoegaze', 'Music'],
            'releaseDate': '2019-04-12'}})
        self.assertEqual((track['genre'], track['year']), ('Shoegaze', 2019))
        for released, year in (('2007', 2007), ('', None), ('soon', None), (None, None)):
            with self.subTest(released=released):
                self.assertEqual(normalize.track_year({'releaseDate': released}, {}), year)
        # A Track dict normalised again keeps what it carries; never a playlist's date.
        self.assertEqual(normalize.track_year({}, {'year': 1999}), 1999)
        self.assertIsNone(normalize.track_year({'lastModifiedDate': '2026-01-01'}, {}))
        again = normalize.normalize_track(track)
        self.assertEqual((again['genre'], again['year']), ('Shoegaze', 2019))

    def test_a_track_keeps_its_api_type(self):
        video = normalize.normalize_track({'id': 'i.video1', 'type': 'library-music-videos',
                                           'attributes': {'name': 'Harbour Lights (Live)'}})
        self.assertEqual(video['type'], 'library-music-videos')
        self.assertEqual(normalize.normalize_track({'id': 'i.x', 'attributes': {}})['type'], '')
        # In a playlist, each row keeps its own.
        playlist = normalize.normalize_playlist(
            {'id': 'p.1', 'attributes': {'name': 'Mixed'}},
            tracks=[{'id': 'i.s', 'type': 'library-songs', 'attributes': {'name': 'S'}},
                    {'id': 'i.v', 'type': 'library-music-videos', 'attributes': {'name': 'V'}}])
        self.assertEqual([entry['type'] for entry in playlist['groups'][0]['entries']],
                         ['library-songs', 'library-music-videos'])

    def test_normalize_track_names_thumbnail_when_asked(self):
        raw = {
            'id': 'i.one',
            'attributes': {'name': 'One', 'artwork': {'url': 'https://x/{w}x{h}bb.jpg'}},
        }
        art_urls = {}
        track = normalize.normalize_track(raw, index=0, cache_dir=self.tmp_dir, art_urls=art_urls)
        self.assertTrue(track['thumb'].startswith(os.path.join(self.tmp_dir, 'thumb')))
        self.assertEqual(art_urls[track['thumb']], 'https://x/256x256bb.jpg')
        # The same cover's full-size file has the same name, one folder over.
        self.assertEqual(os.path.basename(track['thumb']),
                         os.path.basename(art_cache.artwork_cache_path('https://x/512x512bb.jpg',
                                                                       self.tmp_dir)))

    def test_normalize_album(self):
        raw_album = {
            'id': 'l.alb123',
            'type': 'library-albums',
            'attributes': {
                'name': 'Static Skyline',
                'artistName': 'Paper Parachutes',
                'releaseDate': '2007-09-18',
                'genreNames': ['Rock'],
                'contentRating': 'explicit',
                'trackCount': 2,
                'artwork': {'url': 'https://example.com/{w}x{h}.{f}', 'bgColor': '112233'},
                'editorialNotes': {'standard': '<p>A classic easycore record.</p>'},
            },
        }
        raw_tracks = [
            {
                'id': 't2',
                'attributes': {
                    'name': 'Track Two',
                    'artistName': 'Paper Parachutes',
                    'trackNumber': 2,
                    'discNumber': 1,
                    'durationInMillis': 180000,
                },
            },
            {
                'id': 't1',
                'attributes': {
                    'name': 'Track One',
                    'artistName': 'Paper Parachutes',
                    'trackNumber': 1,
                    'discNumber': 1,
                    'durationInMillis': 120000,
                },
            },
            {
                'id': 't3',
                'attributes': {
                    'name': 'Bonus Track',
                    'artistName': 'Paper Parachutes',
                    'trackNumber': 1,
                    'discNumber': 2,
                    'durationInMillis': 200000,
                },
            },
        ]

        item = normalize.normalize_album(raw_album, cache_dir=self.tmp_dir, tracks=raw_tracks)
        self.assertEqual(item['id'], 'l.alb123')
        self.assertEqual(item['kind'], 'album')
        self.assertEqual(item['title'], 'Static Skyline')
        self.assertEqual(item['subtitle'], 'Paper Parachutes')
        self.assertEqual(item['year'], 2007)
        self.assertEqual(item['genre'], 'Rock')
        self.assertEqual(item['summary'], 'A classic easycore record.')
        self.assertEqual(item['artColor'], '#112233')
        self.assertEqual(item['play'], {'kind': 'album', 'id': 'l.alb123'})
        # Counts, not words: the model says "3 songs, 8 min".
        self.assertEqual((item['trackCount'], item['durationMs']), (3, 500000))
        self.assertNotIn('countLabel', item)

        # Two discs
        self.assertEqual(len(item['groups']), 2)
        disc1 = item['groups'][0]
        self.assertEqual(disc1['name'], 'Disc 1')
        self.assertEqual(len(disc1['entries']), 2)
        # Check sorting by trackNumber
        self.assertEqual(disc1['entries'][0]['title'], 'Track One')
        self.assertEqual(disc1['entries'][0]['index'], 0)
        self.assertEqual(disc1['entries'][1]['title'], 'Track Two')
        self.assertEqual(disc1['entries'][1]['index'], 1)

        disc2 = item['groups'][1]
        self.assertEqual(disc2['name'], 'Disc 2')
        self.assertEqual(len(disc2['entries']), 1)
        self.assertEqual(disc2['entries'][0]['title'], 'Bonus Track')
        # Numbered on from disc 1: the album plays as one queue, whichever disc's row starts it.
        self.assertEqual(disc2['play'], item['play'])
        self.assertEqual(disc2['entries'][0]['index'], len(disc1['entries']))

    def test_an_albums_entries_are_its_queue_in_order(self):
        tracks = [{'id': f'{disc}-{number}',
                   'attributes': {'name': f'{disc}.{number}', 'discNumber': disc,
                                  'trackNumber': number}}
                  for disc in (3, 1, 2) for number in (2, 1, 3)]
        album = normalize.normalize_album({'id': 'l.a', 'attributes': {'name': 'A'}},
                                          tracks=tracks)
        entries = [entry for group in album['groups'] for entry in group['entries']]
        self.assertEqual([entry['index'] for entry in entries], list(range(9)))
        self.assertEqual([entry['title'] for entry in entries],
                         [f'{disc}.{number}' for disc in (1, 2, 3) for number in (1, 2, 3)])
        # An artist's groups carry them as they are: an album's positions in its own queue.
        artist = normalize.normalize_artist({'id': 'l.r', 'attributes': {'name': 'R'}},
                                            albums=[album])
        self.assertEqual([entry['index'] for entry in artist['groups'][0]['entries']],
                         list(range(9)))

    def test_a_prerelease_album_and_its_tracks_not_out_yet(self):
        # Apple's isPrerelease, and a future releaseDate; a track out already (a single) has
        # playParams, the others none.
        def track(number, out):
            attrs = {'name': f'Song {number}', 'trackNumber': number, 'discNumber': 1,
                     'durationInMillis': 200000}
            if out:
                attrs['playParams'] = {'id': f'17240495{number:02d}', 'kind': 'song'}
            return {'id': f'17240495{number:02d}', 'type': 'songs', 'attributes': attrs}

        raw = {'id': '1724049500', 'type': 'albums',
               'attributes': {'name': 'Invented Album To Come', 'artistName': 'Invented Band',
                              'releaseDate': '2026-12-04', 'isPrerelease': True,
                              'isComplete': False, 'trackCount': 3},
               'relationships': {'tracks': {'data': [track(1, False), track(2, True),
                                                     track(3, False)]}}}
        item = normalize.normalize_album(raw)
        self.assertIs(item['prerelease'], True)
        self.assertEqual(item['releaseDate'], '2026-12-04')
        self.assertEqual(item['year'], 2026)
        entries = item['groups'][0]['entries']
        self.assertEqual([entry.get('unreleased') for entry in entries], [True, None, True])
        # Shaped again (an answer kept, an Item dict normalised once more), it says the same.
        again = normalize.normalize_album(dict(item, attributes={}), tracks=entries)
        self.assertIs(again['prerelease'], True)
        self.assertEqual(again['releaseDate'], '2026-12-04')
        self.assertEqual([entry.get('unreleased') for entry in again['groups'][0]['entries']],
                         [True, None, True])
        # A shelf's album (no tracks) says it is to come too.
        shelf = normalize.normalize_item(dict(raw, relationships={}), include_groups=False)
        self.assertIs(shelf['prerelease'], True)
        self.assertEqual(shelf['releaseDate'], '2026-12-04')

    def test_an_album_out_has_no_release_keys(self):
        # Out (no isPrerelease, or false): no `prerelease`, `releaseDate` or `unreleased`,
        # whatever its tracks' playParams (a library album's songs carry their own).
        for flag in ({}, {'isPrerelease': False}):
            raw = {'id': '1724049600', 'type': 'albums',
                   'attributes': dict({'name': 'Invented Album', 'releaseDate': '2020-01-01'},
                                      **flag)}
            item = normalize.normalize_album(raw, tracks=[
                {'id': '1724049601', 'attributes': {'name': 'Song', 'trackNumber': 1}}])
            self.assertNotIn('prerelease', item)
            self.assertNotIn('releaseDate', item)
            self.assertNotIn('unreleased', item['groups'][0]['entries'][0])

    def test_release_helpers(self):
        self.assertTrue(normalize.is_prerelease({'isPrerelease': True}))
        self.assertFalse(normalize.is_prerelease({'isPrerelease': 'yes'}))
        self.assertTrue(normalize.is_prerelease({}, {'prerelease': True}))
        self.assertFalse(normalize.is_prerelease(None))
        self.assertEqual(normalize.release_date({'releaseDate': '2026'}), '2026')
        self.assertEqual(normalize.release_date({'releaseDate': 'soon'},
                                                {'releaseDate': '2026-12-04'}), '2026-12-04')
        self.assertIsNone(normalize.release_date({}, None))
        self.assertTrue(normalize.track_released({'attributes': {'playParams': {'id': '1'}}}))
        self.assertFalse(normalize.track_released({'attributes': {'name': 'Song'}}))
        self.assertFalse(normalize.track_released({'title': 'Song', 'unreleased': True}))
        self.assertTrue(normalize.track_released({'title': 'Song'}))

    def test_normalize_playlist(self):
        raw_playlist = {
            'id': 'p.pl123',
            'type': 'library-playlists',
            'attributes': {
                'name': 'Workout Mix',
                'curatorName': 'Jordan',
                'lastModifiedDate': '2024-05-01',
                'trackCount': 1,
            },
        }
        raw_tracks = [
            {
                'id': 's1',
                'attributes': {
                    'name': 'Energy',
                    'artistName': 'Artist',
                    'trackNumber': 1,
                    'durationInMillis': 210000,
                },
            }
        ]

        item = normalize.normalize_playlist(raw_playlist, cache_dir=self.tmp_dir, tracks=raw_tracks)
        self.assertEqual(item['id'], 'p.pl123')
        self.assertEqual(item['kind'], 'playlist')
        self.assertEqual(item['title'], 'Workout Mix')
        self.assertEqual(item['subtitle'], 'Jordan')
        self.assertEqual(item['year'], 2024)
        self.assertEqual(len(item['groups']), 1)
        self.assertEqual(item['groups'][0]['name'], 'Tracks')
        self.assertEqual(item['groups'][0]['entries'][0]['title'], 'Energy')
        self.assertIn('thumb', item)
        self.assertIn('thumb', item['groups'][0]['entries'][0])
        # When Apple last changed it: what its page says it was updated.
        self.assertEqual(item['modified'], '2024-05-01')
        self.assertIsNone(item['catalogId'])  # one of the user's, not published
        raw_playlist['attributes'].pop('lastModifiedDate')
        self.assertNotIn('modified', normalize.normalize_playlist(raw_playlist))

    def test_a_library_playlist_names_its_catalog_playlist(self):
        # One of Apple's added to the library: its play parameters' globalId is the catalog
        # playlist it is, which the catalog's page finds it by (Library.holds()).
        raw = {'id': 'p.pl124', 'type': 'library-playlists',
               'attributes': {'name': 'Invented Picks', 'canEdit': False,
                              'playParams': {'id': 'p.pl124', 'kind': 'playlist',
                                             'isLibrary': True, 'globalId': 'pl.0123abcd'}}}
        self.assertEqual(normalize.normalize_playlist(raw)['catalogId'], 'pl.0123abcd')
        raw['attributes']['playParams']['globalId'] = 'not a playlist id'
        self.assertIsNone(normalize.normalize_playlist(raw)['catalogId'])

    def test_normalize_station(self):
        raw_station = {
            'id': 'ra.12345',
            'type': 'stations',
            'attributes': {
                'name': 'Apple Music 1',
                'stationProviderName': 'Apple Music',
                'description': {'standard': 'The new music that matters.'},
            },
        }
        item = normalize.normalize_station(raw_station, cache_dir=self.tmp_dir)
        self.assertEqual(item['id'], 'ra.12345')
        self.assertEqual(item['kind'], 'station')
        self.assertEqual(item['title'], 'Apple Music 1')
        self.assertEqual(item['subtitle'], 'Apple Music')
        self.assertEqual(item['summary'], 'The new music that matters.')
        self.assertEqual(item['groups'], [])

    def test_counts_are_numbers(self):
        # Without its tracks (a shelf item): Apple's count, and no total time.
        shelf_album = normalize.normalize_album({'id': '1', 'attributes': {'name': 'A',
                                                                           'trackCount': 11}})
        self.assertEqual((shelf_album['trackCount'], shelf_album['durationMs']), (11, None))
        empty = normalize.normalize_playlist({'id': 'p.1', 'attributes': {'name': 'P'}}, tracks=[])
        self.assertEqual((empty['trackCount'], empty['durationMs']), (0, None))
        playlist = normalize.normalize_playlist(
            {'id': 'p.2', 'attributes': {'name': 'P'}},
            tracks=[{'id': 'i.1', 'attributes': {'name': 'T', 'durationInMillis': 61000}}])
        self.assertEqual((playlist['trackCount'], playlist['durationMs']), (1, 61000))
        artist = normalize.normalize_artist({'id': 'l.r', 'attributes': {'name': 'R'}},
                                            albums=[shelf_album, playlist])
        self.assertEqual(artist['albumCount'], 2)
        song = normalize.normalize_item({'id': '9', 'type': 'songs',
                                         'attributes': {'name': 'S', 'durationInMillis': 1000}})
        self.assertEqual(song['durationMs'], 1000)
        station = normalize.normalize_station({'id': 'ra.1', 'attributes': {'name': 'S'}})
        for item in (shelf_album, empty, playlist, artist, song, station):
            with self.subTest(kind=item['kind']):
                self.assertNotIn('countLabel', item)
        self.assertNotIn('trackCount', station)

    def test_nothing_is_attributed_to_anyone_made_up(self):
        station = normalize.normalize_station({'id': 'ra.1', 'attributes': {'name': 'S'}})
        album = normalize.normalize_album({'id': 'l.a', 'attributes': {'name': 'A'}})
        playlist = normalize.normalize_playlist({'id': 'p.1', 'attributes': {'name': 'Mine'}})
        artist = normalize.normalize_artist({'id': 'l.r', 'attributes': {'name': 'R'}})
        for item in (station, album, playlist, artist):
            with self.subTest(kind=item['kind']):
                self.assertEqual(item['subtitle'], '')

    def test_a_resource_of_no_known_type_plays_nothing(self):
        item = normalize.normalize_item({'id': 'e.1', 'type': 'editorial-items',
                                         'attributes': {'name': 'A Banner'}})
        self.assertEqual((item['kind'], item['title'], item['play']), ('unknown', 'A Banner', {}))

    def test_songs_without_names_group_under_nameless_albums_and_artists(self):
        songs = [{'id': 'i.1', 'type': 'library-songs',
                  'attributes': {'name': 'Untitled', 'artistName': '', 'trackNumber': 1}},
                 {'id': 'i.2', 'type': 'library-songs',
                  'attributes': {'name': 'Also Untitled', 'trackNumber': 2}}]
        albums, artists = normalize.group_songs_into_albums_and_artists(songs)
        self.assertEqual([(album['title'], album['subtitle']) for album in albums], [('', '')])
        self.assertEqual([artist['title'] for artist in artists], [''])
        self.assertEqual(len(albums[0]['groups'][0]['entries']), 2)

    def test_a_stand_in_album_plays_its_songs(self):
        def song(song_id, number, album=None):
            raw = {'id': song_id, 'type': 'library-songs', 'attributes': {
                'name': f'Song {number}', 'artistName': 'The Invented Band',
                'albumName': 'Loose Ends', 'trackNumber': number, 'discNumber': 1}}
            if album:
                raw['relationships'] = {'albums': {'data': [{'id': album, 'type': 'library-albums',
                                                             'attributes': {'name': 'Tidewater'}}]}}
            return raw

        songs = [song('i.c', 3), song('i.a', 1), song('i.real', 1, album='l.alb1'), song('i.b', 2)]
        albums, artists = normalize.group_songs_into_albums_and_artists(songs)
        stand_in = next(album for album in albums if album['id'].startswith('l.alb_'))
        real = next(album for album in albums if album['id'] == 'l.alb1')
        play = {'kind': 'songs', 'id': 'i.a,i.b,i.c'}  # in the entries' order
        self.assertEqual(stand_in['play'], play)
        self.assertEqual([group['play'] for group in stand_in['groups']], [play])
        entries = stand_in['groups'][0]['entries']
        self.assertEqual([(entry['id'], entry['index']) for entry in entries],
                         [('i.a', 0), ('i.b', 1), ('i.c', 2)])
        self.assertEqual(real['play'], {'kind': 'album', 'id': 'l.alb1'})  # a real one as it was
        # The artist's group for it plays the same.
        band = next(artist for artist in artists if artist['title'] == 'The Invented Band')
        self.assertEqual([(group['name'], group['play']) for group in band['groups']],
                         [('Loose Ends', play)])
        # Its id is the one made from the group's and the artist's names, by which the
        # library's page of the artist finds the album (discography.py).
        self.assertEqual(stand_in['id'],
                         normalize.stand_in_album_id(band['groups'][0]['name'], band['title']))

    def test_group_songs_into_albums_and_artists(self):
        songs = [
            {
                'id': 's1',
                'attributes': {
                    'name': 'Track A',
                    'artistName': 'Artist One',
                    'albumName': 'Album One',
                    'trackNumber': 1,
                    'discNumber': 1,
                    'durationInMillis': 120000,
                    'releaseDate': '2020-01-01',
                    'genreNames': ['Pop'],
                },
                'relationships': {
                    'albums': {
                        'data': [{
                            'id': 'l.alb1',
                            'type': 'library-albums',
                            'attributes': {
                                'name': 'Album One',
                                'artistName': 'Artist One',
                                'releaseDate': '2020-01-01',
                                'genreNames': ['Pop'],
                            },
                        }]
                    }
                },
            },
            {
                'id': 's2',
                'attributes': {
                    'name': 'Track B',
                    'artistName': 'Artist One',
                    'albumName': 'Album One',
                    'trackNumber': 2,
                    'discNumber': 1,
                    'durationInMillis': 180000,
                    'releaseDate': '2020-01-01',
                    'genreNames': ['Pop'],
                },
                'relationships': {
                    'albums': {
                        'data': [{
                            'id': 'l.alb1',
                            'type': 'library-albums',
                            'attributes': {
                                'name': 'Album One',
                                'artistName': 'Artist One',
                                'releaseDate': '2020-01-01',
                                'genreNames': ['Pop'],
                            },
                        }]
                    }
                },
            },
        ]

        albums, artists = normalize.group_songs_into_albums_and_artists(songs, self.tmp_dir)
        self.assertEqual(len(albums), 1)
        self.assertEqual(albums[0]['title'], 'Album One')
        self.assertEqual(len(albums[0]['groups'][0]['entries']), 2)

        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0]['title'], 'Artist One')
        self.assertEqual(len(artists[0]['groups']), 1)
        self.assertEqual(artists[0]['groups'][0]['name'], 'Album One')

    def test_artist_takes_first_albums_thumbnail_with_its_cover(self):
        song = {
            'id': 's1', 'type': 'library-songs',
            'attributes': {
                'name': 'Track A', 'artistName': 'Artist One', 'albumName': 'Album One',
                'trackNumber': 1, 'discNumber': 1, 'durationInMillis': 1000,
                'artwork': {'url': 'https://x/{w}x{h}bb.jpg', 'bgColor': '123456'},
            },
            'relationships': {'albums': {'data': [{
                'id': 'l.alb1', 'type': 'library-albums',
                'attributes': {'name': 'Album One', 'artistName': 'Artist One',
                               'artwork': {'url': 'https://x/{w}x{h}bb.jpg', 'bgColor': '123456'}},
            }]}},
        }
        albums, artists = normalize.group_songs_into_albums_and_artists([song], self.tmp_dir)
        self.assertEqual(artists[0]['art'], albums[0]['art'])
        self.assertEqual(artists[0]['thumb'], albums[0]['thumb'])
        self.assertTrue(artists[0]['thumb'].startswith(os.path.join(self.tmp_dir, 'thumb')))
        self.assertEqual(artists[0]['artColor'], '#123456')


class TestDatesAndFavourites(unittest.TestCase):
    """The Item's `added` (Apple's dateAdded) and the ids favourite_ids() records."""

    def test_date_added(self):
        for value in ('2026', '2026-03-01', '2026-03-01T10:20:30Z', '2026-03-01T10:20:30.5Z',
                      '2026-03-01T10:20:30+01:00', '2026-03-01T10:20'):
            self.assertEqual(normalize.date_added({'dateAdded': value}), value)
        for value in (None, '', 'yesterday', 2026, '26-03-01', '2026-03-01 10:20'):
            self.assertIsNone(normalize.date_added({'dateAdded': value}), value)
        self.assertIsNone(normalize.date_added(None))

    def test_a_dated_library_resource_has_added_and_others_not(self):
        added = '2026-03-01T10:20:30Z'
        album = normalize.normalize_album(
            {'id': 'l.a', 'type': 'library-albums', 'attributes': {'name': 'A',
                                                                   'dateAdded': added}})
        playlist = normalize.normalize_playlist(
            {'id': 'p.1', 'attributes': {'name': 'P', 'dateAdded': added}})
        video = normalize.normalize_item(
            {'id': 'i.v', 'type': 'library-music-videos', 'attributes': {'name': 'V',
                                                                         'dateAdded': added}})
        self.assertEqual((album['added'], playlist['added'], video['added']), (added,) * 3)
        catalog = normalize.normalize_album({'id': '1', 'type': 'albums',
                                             'attributes': {'name': 'A'}})
        self.assertNotIn('added', catalog)
        self.assertNotIn('added', normalize.normalize_album(
            {'id': 'l.b', 'attributes': {'name': 'B', 'dateAdded': 'not a date'}}))

    def test_favourite_ids(self):
        songs = [
            {'id': 'i.1', 'type': 'library-songs',
             'attributes': {'inFavorites': True, 'playParams': {'catalogId': '9001'}}},
            {'id': 'i.2', 'type': 'library-songs', 'attributes': {'inFavorites': True}},
            {'id': 'i.3', 'type': 'library-songs', 'attributes': {'inFavorites': False,
                                                                  'playParams': {}}},
            {'id': 'i.1', 'type': 'library-songs',
             'attributes': {'inFavorites': True, 'playParams': {'catalogId': '9001'}}},
        ]
        # A song by its catalog id, else its own: what the app rates a song by.
        self.assertEqual(normalize.favourite_ids(songs, songs=True), (['9001', 'i.2'], True))
        albums = [{'id': 'l.a', 'type': 'library-albums',
                   'attributes': {'inFavorites': True},
                   'relationships': {'catalog': {'data': [{'id': '7001'}]}}},
                  {'id': 'l.b', 'type': 'library-albums', 'attributes': {}}]
        # Anything else by its library id and its catalog id.
        self.assertEqual(normalize.favourite_ids(albums), (['l.a', '7001'], True))
        # No inFavorites anywhere: Apple did not answer it.
        self.assertEqual(normalize.favourite_ids([{'id': 'i.1', 'attributes': {}}, 'junk']),
                         ([], False))

    def test_included_albums(self):
        album = {'id': 'l.a', 'type': 'library-albums', 'attributes': {'inFavorites': True}}
        songs = [{'id': 'i.1', 'relationships': {'albums': {'data': [album]}}},
                 {'id': 'i.2', 'relationships': {'albums': {'data': [dict(album)]}}},
                 {'id': 'i.3'}]
        self.assertEqual(normalize.included_albums(songs), [album])


if __name__ == '__main__':
    unittest.main()
