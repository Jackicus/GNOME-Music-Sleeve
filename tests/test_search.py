# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's search answers as shelves, suggestions and categories (backend.search)."""

import json
import os
import shutil
import tempfile
import unittest

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import (
    art_cache,
    normalize,
    search,
)

# The sizes these tests were written against (the extension's defaults). The
# app's own defaults come from config; TestArtSizes covers those.
UPSTREAM_SIZES = {'cover': 512, 'thumb': 256}


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_search_results_are_shelved_in_apples_order(self):
        with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'search_results.json')) as f:
            raw = json.load(f)
        # The catalog's own Top Results — the same song again, and the album
        # — and its own order for the shelves, songs ahead of albums.
        song = raw['results']['songs']['data'][0]
        album = raw['results']['albums']['data'][0]
        raw['results']['topResults'] = {'data': [song, album]}
        raw['meta'] = {'results': {'order': ['topResults', 'artists', 'songs', 'albums',
                                             'playlists']}}
        # A cover the sync has fetched already, and its thumbnail.
        cover_url = art_cache.template_artwork_url(album['attributes']['artwork']['url'], 512, 512)
        thumb_path = art_cache.thumb_cache_path(cover_url, self.tmp_dir)
        os.makedirs(os.path.dirname(thumb_path))
        with open(thumb_path, 'wb') as f:
            f.write(b'jpg')

        out = search.search_results(raw, self.tmp_dir)

        self.assertEqual([s['key'] for s in out['shelves']],
                         ['top', 'artists', 'songs', 'albums', 'playlists'])
        self.assertEqual([s['title'] for s in out['shelves']], [''] * 5)  # the page's words
        top = out['shelves'][0]['items']
        self.assertEqual([it['kind'] for it in top], ['song', 'album'])
        self.assertEqual(top[0]['groups'], [])
        self.assertEqual(set(out), {'shelves'})
        # The album's thumbnail is on disk and stays; its cover is not, so a
        # small catalog URL stands in. The song carries no artwork at all.
        hit_album = out['shelves'][3]['items'][0]
        self.assertEqual(hit_album['thumb'], thumb_path)
        self.assertTrue(hit_album['art'].startswith('https://'))
        self.assertIn('256x256', hit_album['art'])
        hit_song = out['shelves'][2]['items'][0]
        self.assertIsNone(hit_song['thumb'])
        self.assertIsNone(hit_song['art'])

    def test_search_results_with_nothing(self):
        self.assertEqual(search.search_results(None, self.tmp_dir), {'shelves': []})
        self.assertEqual(search.search_results({'results': {'albums': {'data': []}}},
                                               self.tmp_dir),
                         {'shelves': []})

    def test_search_results_without_apples_order_take_the_usual(self):
        raw = {'results': {
            'albums': {'data': [{'id': '1', 'type': 'albums',
                                 'attributes': {'name': 'A', 'artistName': 'X'}}]},
            'artists': {'data': [{'id': '2', 'type': 'artists', 'attributes': {'name': 'X'}}]},
            'stations': {'data': [{'id': 'ra.3', 'type': 'stations', 'attributes': {'name': 'S'}}]},
        }}
        out = search.search_results(raw, self.tmp_dir)
        self.assertEqual([s['key'] for s in out['shelves']], ['artists', 'albums', 'stations'])

    def test_search_results_shelve_music_videos_as_videos(self):
        raw = {'results': {
            'music-videos': {'data': [{'id': '9', 'type': 'music-videos', 'attributes': {
                'name': 'Orbit Parade', 'artistName': 'Hollow Satellites',
                'durationInMillis': 240000,
                'artwork': {'url': 'https://x/{w}x{h}bb.{f}'}}}]},
        }}
        out = search.search_results(raw, self.tmp_dir)
        self.assertEqual([(s['key'], s['title']) for s in out['shelves']],
                         [('music-videos', '')])
        video = out['shelves'][0]['items'][0]
        self.assertEqual(video['kind'], 'video')
        self.assertEqual(video['title'], 'Orbit Parade')
        self.assertEqual(video['subtitle'], 'Hollow Satellites')
        self.assertEqual(video['play'], {'kind': 'musicVideo', 'id': '9'})
        self.assertIn('256x256', video['art'])

    def test_search_results_shelve_curators_and_radio_shows_and_name_the_next_page(self):
        raw = {'results': {
            'songs': {'next': '/v1/catalog/gb/search?offset=20&term=tide&types=songs',
                      'data': [{'id': '1', 'type': 'songs', 'attributes': {'name': 'Tide'}}]},
            'apple-curators': {
                'next': '/v1/catalog/gb/search?offset=20&term=tide&types=apple-curators',
                'data': [
                    {'id': '900000011', 'type': 'apple-curators', 'attributes': {
                        'name': 'Invented Editors', 'kind': 'Curator',
                        'url': 'https://music.apple.com/gb/curator/x/900000011'}},
                    {'id': '900000012', 'type': 'apple-curators', 'attributes': {
                        'name': 'Invented Tide Show', 'kind': 'Show',
                        'showHostName': ' Ada Merrow ',
                        'artwork': {'url': 'https://x/{w}x{h}bb.{f}'}}}]},
            'curators': {'data': [{'id': '900000013', 'type': 'curators',
                                   'attributes': {'name': 'Invented Label', 'kind': 'Show'}}]},
        }}
        out = search.search_results(raw, self.tmp_dir)
        self.assertEqual([(s['key'], [it['id'] for it in s['items']], s['next'])
                          for s in out['shelves']],
                         [('songs', ['1'], 20),
                          ('radio-shows', ['900000012'], 20),
                          ('curators', ['900000011', '900000013'], 20)])
        show = out['shelves'][1]['items'][0]
        # Apple's curators are category tiles, which open their page; a show names its host.
        self.assertEqual({key: show[key] for key in ('kind', 'curatorKind', 'title', 'subtitle',
                                                     'play', 'groups')},
                         {'kind': 'category', 'curatorKind': 'show',
                          'title': 'Invented Tide Show', 'subtitle': 'Ada Merrow', 'play': {},
                          'groups': []})
        self.assertIn('256x256', show['art'])
        editors, label = out['shelves'][2]['items']
        self.assertEqual((editors['kind'], editors['curatorKind'], editors['url']),
                         ('category', 'curator', 'https://music.apple.com/gb/curator/x/900000011'))
        # A third party's has no page here: a link to music.apple.com's (none without one).
        self.assertEqual((label['kind'], label['curatorKind'], label['play']),
                         ('unknown', 'curator', {}))
        self.assertEqual(normalize.curator_link({'id': '9', 'type': 'curators', 'attributes': {
            'name': 'Invented Label', 'url': 'https://music.apple.com/gb/curator/x/9'}})['kind'],
            'link')
        # One kind alone: its shelf, even with nothing on it, for the next page's sake.
        raw['results']['apple-curators']['data'] = raw['results']['apple-curators']['data'][:1]
        only = search.search_results(raw, self.tmp_dir, kind='radio-shows')
        self.assertEqual(only, {'shelves': [{'key': 'radio-shows', 'title': '', 'items': [],
                                             'next': 20}]})
        self.assertEqual(search.search_results({'results': {}}, self.tmp_dir, kind='songs'),
                         {'shelves': []})

    def test_search_suggestions_are_terms_and_top_hits(self):
        raw = {'results': {'suggestions': [
            {'kind': 'terms', 'searchTerm': 'glow', 'displayTerm': 'glow'},
            {'kind': 'terms', 'searchTerm': 'glow in the dark', 'displayTerm': 'glow in the dark'},
            {'kind': 'terms', 'searchTerm': 'Glow', 'displayTerm': 'Glow'},
            {'kind': 'topResults', 'content': {'id': '1', 'type': 'songs', 'attributes': {
                'name': 'Glow', 'artistName': 'Lantern Theory', 'durationInMillis': 1000}}},
            {'kind': 'topResults', 'content': {'id': '1', 'type': 'songs', 'attributes': {
                'name': 'Glow', 'artistName': 'Lantern Theory', 'durationInMillis': 1000}}},
            {'kind': 'topResults',
             'content': {'id': '2', 'type': 'artists', 'attributes': {'name': 'Glow'}}},
            {'kind': 'topResults', 'content': 'not a resource'},
            'not a suggestion',
        ]}}
        out = search.search_suggestions(raw, self.tmp_dir)
        self.assertEqual(out['terms'], [{'term': 'glow', 'display': 'glow'},
                                        {'term': 'glow in the dark',
                                         'display': 'glow in the dark'}])
        self.assertEqual([(it['kind'], it['id'], it['title']) for it in out['items']],
                         [('song', '1', 'Glow'), ('artist', '2', 'Glow')])
        self.assertEqual(out['items'][0]['groups'], [])
        self.assertIsNone(out['items'][0]['art'])

    def test_search_suggestions_with_nothing(self):
        self.assertEqual(search.search_suggestions(None, self.tmp_dir),
                         {'terms': [], 'items': []})
        self.assertEqual(search.search_suggestions({'results': {}}, self.tmp_dir),
                         {'terms': [], 'items': []})

    def test_search_landing_is_apples_curators_in_order(self):
        curator = lambda cid, name, short=None, bg='dd6848': {  # noqa: E731
            'id': cid, 'type': 'apple-curators', 'attributes': {
                'name': name, 'shortName': short or name,
                'url': f'https://music.apple.com/gb/curator/x/{cid}',
                'artwork': {'url': 'https://x/{w}x{h}{c}.{f}', 'bgColor': bg, 'width': 1080,
                            'height': 1080}}}
        raw = {'data': [
            {'id': 'r1', 'type': 'personal-recommendation',
             'attributes': {'title': {'stringForDisplay': 'Browse Categories'}},
             'relationships': {'contents': {'data': [curator('1', 'Apple Music Live')]}}},
            {'id': 'r2', 'type': 'personal-recommendation',
             'relationships': {'contents': {'data': [
                 curator('2', 'Apple Music Rock', 'Rock'),
                 {'id': 'e1', 'type': 'editorial-items', 'attributes': {'editorialArtwork': {}}},
                 curator('2', 'Apple Music Rock', 'Rock'),
                 {'id': '3', 'type': 'apple-curators', 'attributes': {'artwork': {}}},
                 'junk',
             ]}}},
        ]}
        out = search.search_landing(raw, self.tmp_dir)
        self.assertEqual([(c['id'], c['title'], c['subtitle']) for c in out['categories']],
                         [('1', 'Apple Music Live', None), ('2', 'Rock', 'Apple Music Rock')])
        rock = out['categories'][1]
        self.assertEqual(rock['kind'], 'category')
        self.assertEqual(rock['art'], 'https://x/320x320bb.jpg')
        self.assertEqual(rock['artColor'], '#dd6848')
        self.assertEqual(rock['url'], 'https://music.apple.com/gb/curator/x/2')
        self.assertEqual(search.search_landing(None, self.tmp_dir), {'categories': []})


if __name__ == '__main__':
    unittest.main()
