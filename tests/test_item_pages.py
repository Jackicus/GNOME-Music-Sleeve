# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""An artist's, an album's and a catalog playlist's pages, and a song's credits
(backend.item_pages)."""

import json
import os
import shutil
import tempfile
import unittest

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import (
    art_cache,
    cache_files,
    item_pages,
    normalize,
)



class TestArtistPage(unittest.TestCase):
    """artist_page over an invented catalog artist (tests/fixtures/catalog_artist.json, in the
    shape Apple answers api.ARTIST_ENDPOINT with)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'catalog_artist.json'),
                  encoding='utf-8') as f:
            self.raw = json.load(f)
        self.page = item_pages.artist_page(self.raw, self.tmp_dir)

    def shelf(self, key):
        return next(shelf for shelf in self.page['shelves'] if shelf['key'] == key)

    def test_the_artist_and_about(self):
        artist = self.page['artist']
        self.assertEqual((artist['id'], artist['kind'], artist['title']),
                         ('1724049001', 'artist', 'Paper Parachutes'))
        self.assertEqual(artist['summary'], 'An invented math-rock band.\nThey play in odd meters.')
        self.assertEqual((artist['origin'], artist['bornOrFormed'], artist['isGroup']),
                         ('Tallinn, Estonia', '2014', True))
        self.assertEqual(artist['genre'], 'Math Rock')
        self.assertEqual(artist['groups'], [])
        self.assertEqual(artist['play'], {'kind': 'artist', 'id': '1724049001'})
        self.assertTrue(artist['art'].startswith('https://'))  # fetched by the page

    def test_the_latest_release_with_its_date(self):
        latest = self.page['latest']  # the featured release is empty: the latest stands
        self.assertEqual((latest['key'], latest['title']), ('latest-release', 'Latest Release'))
        self.assertEqual((latest['item']['title'], latest['item']['subtitle'],
                          latest['item']['releaseDate']),
                         ('Ladders of Rain', '2026', '2026-03-14'))

    def test_a_featured_release_comes_first(self):
        views = self.raw['data'][0]['views']
        views['featured-release']['data'] = views['singles']['data']
        latest = item_pages.artist_page(self.raw, self.tmp_dir)['latest']
        self.assertEqual((latest['key'], latest['item']['title']),
                         ('featured-release', 'Gutter Hymn - Single'))

    def test_the_top_songs_carry_their_album(self):
        top = self.page['topSongs']
        self.assertEqual((top['title'], top['more']), ('Top Songs', True))
        self.assertEqual([(song['id'], song['kind'], song['album'], song['year'])
                          for song in top['items']],
                         [('1724049201', 'song', 'Ladders of Rain', 2026),
                          ('1724049202', 'song', 'Kites in Fog', 2023),
                          ('1724049203', 'song', 'Kites in Fog', 2023)])
        self.assertTrue(top['items'][1]['explicit'])

    def test_the_shelves_in_apples_order(self):
        # The empty views are left out; About goes before similar-artists on the page.
        self.assertEqual([shelf['key'] for shelf in self.page['shelves']], [
            'featured-albums', 'full-albums', 'music-videos', 'playlists', 'radio-shows',
            'singles', 'appears-on-albums', 'more-to-hear', 'more-to-see', 'similar-artists'])
        self.assertEqual([shelf['title'] for shelf in self.page['shelves']][:2],
                         ['Essential Albums', 'Albums'])
        self.assertEqual([shelf['key'] for shelf in self.page['shelves'] if shelf['more']],
                         ['full-albums', 'more-to-hear', 'similar-artists'])

    def test_each_card_says_what_apple_shows_under_it(self):
        self.assertEqual(self.shelf('featured-albums')['items'][0]['subtitle'],
                         'The invented band’s finest hour.')
        self.assertEqual([album['subtitle'] for album in self.shelf('full-albums')['items']],
                         ['2026', '2023'])  # the artist's own: the year
        # Its artist kept beside the year, for Go to Artist (related.artist_name).
        self.assertEqual({album['artistName'] for album in self.shelf('full-albums')['items']},
                         {'Paper Parachutes'})
        self.assertEqual(self.shelf('music-videos')['items'][0]['subtitle'], '2026')
        self.assertEqual(self.shelf('appears-on-albums')['items'][0]['subtitle'],
                         'Mara Lind & The Tide')  # another's: its artist
        self.assertEqual(self.shelf('playlists')['items'][0]['subtitle'], 'Apple Music Rock')
        episode = self.shelf('more-to-hear')['items'][0]
        self.assertEqual((episode['kind'], episode['subtitle']), ('station', 'The Long Play'))
        self.assertEqual(self.shelf('similar-artists')['items'][0]['kind'], 'artist')

    def test_a_video_about_the_artist_is_a_link(self):
        links = self.shelf('more-to-see')['items']
        # One without a page to open, and a kind the app has no tile for, are left out.
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertEqual((link['kind'], link['title'], link['subtitle'], link['url'], link['play']),
                         ('link', 'Paper Parachutes on Ladders of Rain', '11:22',
                          'https://music.apple.com/gb/post/1724049500', {}))
        # A video: its tile a 16:9 frame (#383), its artwork asked by its shorter edge.
        self.assertIs(link['video'], True)
        self.assertTrue(art_cache.wide_art(link))
        width, height = art_cache.thumb_box(art_cache.ART_SIZES['thumb'], wide=True)
        self.assertTrue(link['art'].endswith(f'/{width}x{height}bb.jpg'), link['art'])

    def test_the_radio_shows_the_artist_hosts(self):
        # #360: the view holds Apple curators of kind Show, once dropped (an empty shelf).
        # Each is a category tile opening the show's page, subtitled with its host, and
        # nothing plays it.
        shelf = self.shelf('radio-shows')
        self.assertEqual(shelf['title'], 'Radio Shows')
        show = shelf['items'][0]
        self.assertEqual((show['id'], show['kind'], show['title'], show['subtitle']),
                         ('1724049600', 'category', 'The Paper Parachutes Hour',
                          'Paper Parachutes'))
        self.assertEqual(show['url'],
                         'https://music.apple.com/gb/curator/the-paper-parachutes-hour/1724049600')
        self.assertTrue(show['art'].startswith('https://'))
        self.assertNotIn('play', show)
        # A curator in another view still has no tile there.
        views = self.raw['data'][0]['views']
        views['playlists']['data'].append(views['radio-shows']['data'][0])
        page = item_pages.artist_page(self.raw, self.tmp_dir)
        playlists = next(shelf for shelf in page['shelves'] if shelf['key'] == 'playlists')
        self.assertEqual({item['kind'] for item in playlists['items']}, {'playlist'})

    def test_a_view_seen_again_under_the_same_title_is_left_out(self):
        views = self.raw['data'][0]['views']
        views['radio-shows'] = dict(views['playlists'])
        shelves = item_pages.artist_page(self.raw, self.tmp_dir)['shelves']
        titles = [shelf['title'] for shelf in shelves]
        self.assertEqual(titles.count('Artist Playlists'), 1)

    def test_an_answer_without_an_artist(self):
        page = item_pages.artist_page({'data': []}, self.tmp_dir)
        self.assertEqual((page['latest'], page['topSongs'], page['shelves']), (None, None, []))
        self.assertIsNone(page['banner'])

    def test_no_banner_without_hero_or_editorial_artwork(self):
        self.assertIsNone(self.page['banner'])  # the fixture has neither: the portrait

    def test_whether_the_artist_is_a_favourite(self):
        self.assertIsNone(self.page['favourite'])  # the fixture does not say
        for value in (True, False):
            self.raw['data'][0]['attributes']['inFavorites'] = value
            self.assertIs(item_pages.artist_page(self.raw, self.tmp_dir)['favourite'], value)
        self.assertIs(normalize.in_favourites(self.raw), False)
        for raw in (None, {}, {'data': []}, {'data': [{'attributes': {'inFavorites': 1}}]}):
            self.assertIsNone(normalize.in_favourites(raw))


class TestAlbumPage(unittest.TestCase):
    """album_page over an invented catalog album (tests/fixtures/catalog_album_page.json: the
    album as Apple answers api.ALBUM_ENDPOINT with its views, and a page of its artist's
    albums, api.MORE_BY_VIEW)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'catalog_album_page.json'),
                  encoding='utf-8') as f:
            self.raw = json.load(f)
        self.page = item_pages.album_page(self.raw, self.tmp_dir)

    def shelf(self, key):
        return next(shelf for shelf in self.page['shelves'] if shelf['key'] == key)

    def test_the_album_its_artist_and_its_release(self):
        self.assertEqual((self.page['id'], self.page['artistId'], self.page['artistName']),
                         ('1724049100', '1724049001', 'Paper Parachutes'))
        self.assertEqual(self.page['release'], {
            'releaseDate': '2026-03-14', 'copyright': '℗ 2026 Invented Records Ltd',
            'recordLabel': 'Invented Records'})

    def test_the_shelves_in_apples_order(self):
        # More By between Music Videos (empty here: left out) and Featured On, untitled (the
        # app names it); Apple's titles for the rest; `more` where Apple has more.
        self.assertEqual([(shelf['key'], shelf['title'], shelf['more'])
                          for shelf in self.page['shelves']],
                         [('other-versions', 'Other Versions', False),
                          ('more-by-artist', '', True),
                          ('appears-on', 'Featured On', False),
                          ('you-might-also-like', 'You Might Also Like', True)])

    def test_each_card_says_what_apple_shows_under_it(self):
        other = self.shelf('other-versions')['items'][0]
        self.assertEqual((other['id'], other['kind'], other['subtitle'], other['artistName']),
                         ('1724049150', 'album', '2026', 'Paper Parachutes'))  # the year
        self.assertEqual(other['groups'], [])
        self.assertTrue(other['art'].startswith('https://'))  # fetched by the page
        # More By leaves the album itself out.
        self.assertEqual([(album['id'], album['subtitle'])
                          for album in self.shelf('more-by-artist')['items']],
                         [('1724049110', '2023')])
        # A curator Apple puts among the playlists has no tile here.
        playlists = self.shelf('appears-on')['items']
        self.assertEqual([(playlist['kind'], playlist['subtitle']) for playlist in playlists],
                         [('playlist', 'Apple Music Indie')])
        alike = self.shelf('you-might-also-like')['items'][0]
        self.assertEqual((alike['subtitle'], alike['artistName']), ('Mara Lind', 'Mara Lind'))

    def test_without_more_by(self):
        # The artist's albums could not be read: the album's own views still show.
        page = item_pages.album_page(dict(self.raw, moreBy=None), self.tmp_dir)
        self.assertNotIn('more-by-artist', [shelf['key'] for shelf in page['shelves']])
        self.assertEqual(len(page['shelves']), 3)

    def test_an_answer_without_an_album(self):
        for raw in ({}, {'album': {'data': []}}, None, {'album': {'data': ['x']}}):
            with self.subTest(raw=raw):
                page = item_pages.album_page(raw, self.tmp_dir)
                self.assertEqual((page['id'], page['artistId'], page['release'],
                                  page['shelves']), ('', '', {}, []))

    def test_the_release_keeps_only_what_apple_has(self):
        self.assertEqual(item_pages.album_release({'releaseDate': '1999', 'copyright': ' ',
                                                   'recordLabel': 7}),
                         {'releaseDate': '1999'})
        self.assertEqual(item_pages.album_release({'releaseDate': 'soon'}), {})
        self.assertEqual(item_pages.album_release(None), {})

    def test_the_cache_path(self):
        self.assertEqual(cache_files.album_cache_path('/c', '1724049100'),
                         '/c/albums/1724049100.json')
        self.assertEqual(cache_files.album_cache_path('/c', 'l.ab/c'), '/c/albums/l.ab_c.json')


class TestPlaylistPage(unittest.TestCase):
    """playlist_page over an invented catalog playlist (tests/fixtures/
    catalog_playlist_page.json: the playlist as Apple answers api.PLAYLIST_ENDPOINT with its
    curator and views, More By the curator titled but empty, as Apple sends it) and its
    Apple curator's playlists (curator_playlists.json, api.CURATOR_PLAYLISTS_ENDPOINT's)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        fixtures = os.path.join(os.path.dirname(__file__), 'fixtures')
        with open(os.path.join(fixtures, 'catalog_playlist_page.json'), encoding='utf-8') as f:
            self.playlist = json.load(f)
        with open(os.path.join(fixtures, 'curator_playlists.json'), encoding='utf-8') as f:
            self.curator_playlists = json.load(f)
        self.raw = {'playlist': self.playlist, 'curatorPlaylists': self.curator_playlists}
        self.resource = self.playlist['data'][0]
        self.page = item_pages.playlist_page(self.raw, self.tmp_dir)

    def shelf(self, key):
        return next(shelf for shelf in self.page['shelves'] if shelf['key'] == key)

    def test_the_shelves_in_apples_order(self):
        self.assertEqual(self.page['id'], 'pl.aW52ZW50ZWRwbA')
        self.assertEqual([(shelf['key'], shelf['title'], shelf['more'])
                          for shelf in self.page['shelves']],
                         [('featured-artists', 'Featured Artists', False),
                          ('more-by-curator', 'More By Apple Music Invented', True),
                          ('you-might-also-like', 'You Might Also Like', False)])

    def test_each_card(self):
        artists = self.shelf('featured-artists')['items']
        self.assertEqual([(artist['kind'], artist['id'], artist['title']) for artist in artists],
                         [('artist', '1724049001', 'Paper Parachutes'),
                          ('artist', '1724049002', 'Mara Lind')])
        self.assertTrue(artists[0]['art'].startswith('https://'))  # fetched by the page
        # The curator's playlists leave the playlist itself out, and a curator among them.
        self.assertEqual([(item['id'], item['subtitle'])
                          for item in self.shelf('more-by-curator')['items']],
                         [('pl.aW52ZW50ZWRwMg', 'Apple Music Invented')])
        self.assertEqual([item['id'] for item in self.shelf('you-might-also-like')['items']],
                         ['pl.aW52ZW50ZWRwMw'])

    def test_an_apple_curator_is_its_category_page(self):
        self.assertEqual(self.page['curator'], {
            'id': '1724049500', 'kind': 'category', 'title': 'Apple Music Invented',
            'subtitle': None, 'art': 'https://example.invalid/image/thumb/Y3VyYXRvcg/320x320cc.jpg',
            'artColor': '#402030',
            'url': 'https://music.apple.com/gb/curator/apple-music-invented/1724049500'})
        # Its id alone (the relationship without `include`): named as the playlist names it.
        curator = self.resource['relationships']['curator']['data'][0]
        curator.pop('attributes')
        page = item_pages.playlist_page(self.raw, self.tmp_dir)
        self.assertEqual((page['curator']['id'], page['curator']['kind'],
                          page['curator']['title']),
                         ('1724049500', 'category', 'Apple Music Invented'))
        self.resource['attributes'].pop('curatorName')
        self.assertIsNone(item_pages.playlist_page(self.raw, self.tmp_dir)['curator'])

    def test_a_third_party_curator_is_a_link(self):
        self.resource['relationships']['curator']['data'] = [{
            'id': '1724049700', 'type': 'curators',
            'attributes': {'name': 'Harbour Editors',
                           'url': 'https://music.apple.com/gb/curator/harbour-editors/1724049700'}}]
        curator = item_pages.playlist_page(self.raw, self.tmp_dir)['curator']
        self.assertEqual((curator['kind'], curator['title'], curator['url']),
                         ('link', 'Harbour Editors',
                          'https://music.apple.com/gb/curator/harbour-editors/1724049700'))
        # Without an https page: no link.
        self.resource['relationships']['curator']['data'][0]['attributes']['url'] = 'ftp://x'
        self.assertIsNone(item_pages.playlist_page(self.raw, self.tmp_dir)['curator'])

    def test_more_by_the_curator_is_its_playlists(self):
        # Apple's view is empty, its title kept; the curator's own playlists fill it.
        self.assertEqual(self.resource['views']['more-by-curator']['data'], [])
        shelf = self.shelf('more-by-curator')
        self.assertEqual((shelf['title'], shelf['more']), ('More By Apple Music Invented', True))
        # Without them (the second read failed, a curator not Apple's): none.
        for raw in ({'playlist': self.playlist},
                    {'playlist': self.playlist, 'curatorPlaylists': {'data': []}}):
            with self.subTest(raw=raw):
                page = item_pages.playlist_page(raw, self.tmp_dir)
                self.assertEqual([shelf['key'] for shelf in page['shelves']],
                                 ['featured-artists', 'you-might-also-like'])
        # Should Apple fill its view one day, the view it sent is the shelf.
        self.resource['views']['more-by-curator']['data'] = [
            {'id': 'pl.aW52ZW50ZWRwNA', 'type': 'playlists',
             'attributes': {'name': 'Invented Late Tram',
                            'playParams': {'id': 'pl.aW52ZW50ZWRwNA', 'kind': 'playlist'}}}]
        page = item_pages.playlist_page(self.raw, self.tmp_dir)
        shelf = next(shelf for shelf in page['shelves'] if shelf['key'] == 'more-by-curator')
        self.assertEqual(([item['id'] for item in shelf['items']], shelf['more']),
                         (['pl.aW52ZW50ZWRwNA'], False))

    def test_a_shared_playlists_curator_is_a_link_to_their_profile(self):
        self.resource['attributes']['playlistType'] = 'user-shared'
        self.resource['relationships']['curator']['data'] = [{
            'id': 'sp.aW52ZW50ZWQ', 'type': 'social-profiles',
            'attributes': {'name': 'Invented Listener', 'handle': 'inventedlistener',
                           'isPrivate': False, 'isVerified': False,
                           'url': 'https://music.apple.com/profile/inventedlistener'}}]
        curator = item_pages.playlist_page({'playlist': self.playlist}, self.tmp_dir)['curator']
        self.assertEqual((curator['id'], curator['kind'], curator['title'], curator['url']),
                         ('sp.aW52ZW50ZWQ', 'link', 'Invented Listener',
                          'https://music.apple.com/profile/inventedlistener'))

    def test_no_curator(self):
        for curator in ({}, {'data': []}, {'data': [{'type': 'apple-curators'}]},
                        {'data': [{'id': '9', 'type': 'social-profiles'}]},
                        {'data': [{'id': '9', 'type': 'social-profiles',
                                   'attributes': {'name': 'Invented', 'url': 'http://x'}}]},
                        None):
            with self.subTest(curator=curator):
                self.resource['relationships']['curator'] = curator
                self.assertIsNone(item_pages.playlist_page(self.raw, self.tmp_dir)['curator'])

    def test_an_answer_without_a_playlist(self):
        for raw in ({}, {'playlist': {'data': []}}, None, {'playlist': {'data': ['x']}},
                    {'playlist': None, 'curatorPlaylists': self.curator_playlists}):
            with self.subTest(raw=raw):
                self.assertEqual(item_pages.playlist_page(raw, self.tmp_dir),
                                 {'id': '', 'curator': None, 'shelves': []})

    def test_a_view_whole(self):
        resources = self.curator_playlists['data']
        self.assertEqual([item['id'] for item in item_pages.playlist_view_items(
            resources, 'pl.aW52ZW50ZWRwbA', self.tmp_dir)], ['pl.aW52ZW50ZWRwMg'])
        self.assertEqual(item_pages.playlist_view_items(None, 'pl.x', self.tmp_dir), [])

    def test_the_cache_path(self):
        self.assertEqual(cache_files.playlist_cache_path('/c', 'pl.aW52ZW50ZWQ'),
                         '/c/playlists/pl.aW52ZW50ZWQ.json')
        self.assertEqual(cache_files.playlist_cache_path('/c', 'pl.a/b'),
                         '/c/playlists/pl.a_b.json')
        self.assertIn('playlists', cache_files.ANSWER_FOLDERS)


class TestSongCredits(unittest.TestCase):
    """song_credits: a song's credits answer (invented) as View Credits shows it."""

    def read(self):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'song_credits.json'),
                  encoding='utf-8') as file:
            return json.load(file)

    def test_the_categories_in_apples_order(self):
        answer = item_pages.song_credits(self.read(), None)
        self.assertEqual([(category['kind'], category['title'])
                          for category in answer['categories']],
                         [('performer', 'Performers'),
                          ('composer-and-lyrics', 'Composition & Lyrics'),
                          ('production-and-engineering', '')])
        self.assertEqual(answer['categories'][0]['people'], [
            {'name': 'The Invented Band', 'roles': ['Performer']},
            {'name': 'Ada Brightwater', 'roles': ['Vocals', 'Guitar']},
            {'name': 'Bram Holloway', 'roles': []}])
        # Someone without a name and the same person twice are left out; a category with
        # nobody (an empty one, one without its relationship) is too.
        self.assertEqual(answer['categories'][2]['people'],
                         [{'name': 'Cleo Ashdown', 'roles': ['Producer']}])
        # No ids: a credit's is not an artist's catalog id.
        self.assertNotIn('id', json.dumps(answer))

    def test_the_song_read_with_its_credits(self):
        # include=credits on the song: the same categories, under its relationships.
        categories = self.read()['data']
        song = {'data': [{'id': '1724049201', 'type': 'songs',
                          'relationships': {'credits': {'data': categories}}}]}
        self.assertEqual(item_pages.song_credits(song, None),
                         item_pages.song_credits(self.read(), None))

    def test_none(self):
        for raw in (None, {}, {'data': []}, {'data': [{'type': 'songs'}]}, {'data': 'x'}):
            self.assertEqual(item_pages.song_credits(raw, None), {'categories': []}, raw)

    def test_kept_by_its_id(self):
        self.assertEqual(cache_files.credits_cache_path('/c', '1724049201'),
                         os.path.join('/c', 'credits', '1724049201.json'))
        self.assertEqual(cache_files.credits_cache_path('/c', '../x'),
                         os.path.join('/c', 'credits', '.._x.json'))


if __name__ == '__main__':
    unittest.main()
