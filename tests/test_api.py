# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""src/backend/api.py: library ids, endpoints, resource types, pages, Apple's error answers and
the languages lyrics are asked in."""

import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend.api import (LIBRARY_ROUTES, api_error, http_status, is_deleted,
                                    is_final, is_library_id, item_endpoint, library_twin,
                                    library_twin_params, lyrics_languages, next_offset,
                                    page_data,
                                    playlist_entries, reordered_entries, resource_type,
                                    track_type)
from applemusic.backend.errors import EngineError


class LibraryIdTest(unittest.TestCase):
    def test_prefixes(self):
        for item_id in ('l.abc', 'p.xyz', 'r.1', 'i.song1'):
            self.assertTrue(is_library_id(item_id), item_id)
        for item_id in ('1000000002', 'pl.u-1', 'ra.1', '', None):
            self.assertFalse(is_library_id(item_id), item_id)


class EndpointTest(unittest.TestCase):
    def test_library_and_catalog(self):
        self.assertEqual(item_endpoint('album', 'l.abc', 'gb'),
                         '/v1/me/library/albums/l.abc?include=tracks,artists')
        self.assertEqual(item_endpoint('album', '123', 'gb'),
                         '/v1/catalog/gb/albums/123?include=tracks,artists')
        self.assertEqual(item_endpoint('playlist', 'p.xyz', 'us'),
                         '/v1/me/library/playlists/p.xyz?include=tracks')
        self.assertEqual(item_endpoint('playlist', 'pl.u-1', 'us'),
                         '/v1/catalog/us/playlists/pl.u-1?include=tracks')
        self.assertEqual(item_endpoint('artist', 'r.1', 'us'),
                         '/v1/me/library/artists/r.1?include=albums')
        self.assertEqual(item_endpoint('artist', '9', 'us'),
                         '/v1/catalog/us/artists/9?include=albums')
        self.assertEqual(item_endpoint('station', 'ra.1', 'us'), '/v1/catalog/us/stations/ra.1')
        self.assertEqual(item_endpoint('song', 'l.s', 'us'), '/v1/me/library/songs/l.s')
        self.assertEqual(item_endpoint('song', 'i.s', 'us'), '/v1/me/library/songs/i.s')
        self.assertEqual(item_endpoint('song', '5', 'us'), '/v1/catalog/us/songs/5')
        for kind in ('video', 'musicVideo', 'music-video'):
            self.assertEqual(item_endpoint(kind, '7', 'us'), '/v1/catalog/us/music-videos/7')
        self.assertEqual(item_endpoint('video', 'i.v', 'us'), '/v1/me/library/music-videos/i.v')
        self.assertEqual(item_endpoint('curator', '5', 'us'), '/v1/catalog/us/curators/5')


class ResourceTypeTest(unittest.TestCase):
    def test_types(self):
        self.assertEqual(resource_type('song', '1'), 'song')
        self.assertEqual(resource_type('song', 'i.1'), 'library-song')
        self.assertEqual(resource_type('album', 'l.1'), 'library-album')
        self.assertEqual(resource_type('playlist', 'p.1'), 'library-playlist')
        self.assertEqual(resource_type('playlist', 'pl.1'), 'playlist')
        self.assertEqual(resource_type('video', 'i.1'), 'library-music-video')
        self.assertEqual(resource_type('musicVideo', '1'), 'music-video')
        self.assertEqual(resource_type('station', 'ra.1'), 'station')
        for kind, item_id in (('artist', '1'), ('category', '1'), ('song', None)):
            with self.assertRaises(EngineError) as raised:
                resource_type(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')


class PlaylistTest(unittest.TestCase):
    def test_track_types(self):
        self.assertEqual(track_type('song', 'i.1'), 'library-songs')
        self.assertEqual(track_type('song', '1000000001'), 'songs')
        self.assertEqual(track_type('video', 'i.1'), 'library-music-videos')
        self.assertEqual(track_type('musicVideo', '1'), 'music-videos')
        for kind, item_id in (('album', 'l.1'), ('station', 'ra.1'), ('song', ''), (None, '1')):
            self.assertIsNone(track_type(kind, item_id))

    def test_what_the_account_deleted(self):
        # As Apple went on listing a deleted playlist, and a deleted folder (2026-10-03).
        self.assertTrue(is_deleted({'id': 'p.1', 'attributes': {
            'canDelete': False, 'canEdit': False, 'hasCatalog': False,
            'lastModifiedDate': '1970-01-01T00:00:00Z'}}))
        self.assertTrue(is_deleted({'id': 'p.2', 'attributes': {'canDelete': False,
                                                                'canEdit': False}}))
        # Live ones: the user's, Favourite Songs, Apple's own, a folder.
        for attributes in ({'name': 'Road Trip', 'canEdit': True, 'canDelete': True},
                           {'name': 'Favourite Songs', 'canEdit': False, 'canDelete': False,
                            'dateAdded': '2026-01-01T00:00:00Z'},
                           {'name': 'Apple Picks', 'canEdit': False, 'canDelete': True},
                           {'name': 'Evenings', 'canEdit': False, 'canDelete': True}):
            self.assertFalse(is_deleted({'id': 'p.3', 'attributes': attributes}), attributes)
        self.assertFalse(is_deleted({'id': 'p.4'}))
        self.assertFalse(is_deleted(None))


    def test_every_entry_goes_back_as_apple_gave_it(self):
        # One Apple cannot play (no playParams) and a catalog song among them; anything else
        # an entry carries stays behind.
        listed = [{'id': 'i.a', 'type': 'library-songs', 'attributes': {'playParams': {}}},
                  {'id': 'i.b', 'type': 'library-songs', 'attributes': {}},
                  {'id': '1000000001', 'type': 'songs'}]
        self.assertEqual(playlist_entries(listed), [
            {'id': 'i.a', 'type': 'library-songs'}, {'id': 'i.b', 'type': 'library-songs'},
            {'id': '1000000001', 'type': 'songs'}])
        for broken in ({'id': 'i.a'}, {'type': 'library-songs'}, {'id': '', 'type': 'x'},
                       {'id': 5, 'type': 'library-songs'}, 'i.a'):
            with self.assertRaises(EngineError) as raised:
                playlist_entries([listed[0], broken])
            self.assertEqual(raised.exception.code, 'api')

    def test_a_new_order_over_the_list_shown(self):
        listed = [{'id': track_id, 'type': 'library-songs'} for track_id in ('i.a', 'i.b',
                                                                             'i.a')]
        # The entries by position: of the song held twice, the one moved.
        self.assertEqual([entry['id'] for entry in reordered_entries(
            listed, ['i.a', 'i.b', 'i.a'], [2, 0, 1])], ['i.a', 'i.a', 'i.b'])
        with self.assertRaises(EngineError) as raised:
            reordered_entries(listed, ['i.a', 'i.a', 'i.b'], [0, 1, 2])
        self.assertEqual(raised.exception.code, 'conflict')
        with self.assertRaises(EngineError) as raised:
            reordered_entries(listed[:2], ['i.a', 'i.b', 'i.a'], [0, 1, 2])
        self.assertEqual(raised.exception.code, 'conflict')
        for order in ([0, 1], [0, 0, 1], [0, 1, 3], [0, 1, True], [0, 1, 2.0]):
            with self.assertRaises(EngineError) as raised:
                reordered_entries(listed, ['i.a', 'i.b', 'i.a'], order)
            self.assertEqual(raised.exception.code, 'usage', order)
        self.assertEqual(reordered_entries([], [], []), [])


class LibraryTwinTest(unittest.TestCase):
    """What a removal from the library sends: the catalog type in the library route, and
    the read that finds a catalog item's library id."""

    def test_the_routes_are_the_catalog_types(self):
        self.assertEqual([LIBRARY_ROUTES[kind] for kind in ('song', 'album', 'video',
                                                            'musicVideo', 'playlist')],
                         ['songs', 'albums', 'music-videos', 'music-videos', 'playlists'])
        self.assertNotIn('artist', LIBRARY_ROUTES)
        self.assertNotIn('station', LIBRARY_ROUTES)

    def test_the_read_and_its_answer(self):
        self.assertEqual(library_twin_params('video', 1000000009), {
            'ids[music-videos]': '1000000009', 'relate': 'library',
            'fields[music-videos]': 'inLibrary', 'omit[resource]': 'autos'})
        answer = {'data': [{'id': '1000000001', 'type': 'songs',
                            'relationships': {'library': {'data': [
                                {'id': 'i.song1', 'type': 'library-songs'}]}}}]}
        self.assertEqual(library_twin(answer), 'i.song1')
        for none in ({'data': [{'id': '1', 'relationships': {'library': {'data': []}}}]},
                     {'data': [{'id': '1'}]}, {'data': [{'relationships': None}]},
                     {'data': [{'relationships': {'library': {'data': [{'id': '1000'}]}}}]},
                     {}, None):
            self.assertIsNone(library_twin(none), none)


class PageDataTest(unittest.TestCase):
    def test_the_resources_of_a_page(self):
        self.assertEqual(page_data({'data': [{'id': '1'}, 'junk', None, {'id': '2'}]}),
                         [{'id': '1'}, {'id': '2'}])
        for answer in ({}, {'data': None}, {'data': 'x'}, None, [], 'text'):
            self.assertEqual(page_data(answer), [], answer)


class NextOffsetTest(unittest.TestCase):
    def test_the_offset_a_next_link_asks_for(self):
        self.assertEqual(next_offset('/v1/catalog/gb/search?offset=25&term=tide&types=songs'),
                         25)
        self.assertEqual(next_offset('/v1/catalog/gb/search?term=x&offset=50'), 50)
        for link in (None, '', 42, '/v1/catalog/gb/search?term=x', '/v1/x?offset=none',
                     '/v1/x?offset=0', '/v1/x?offset=-5'):
            self.assertIsNone(next_offset(link), link)


class ApiErrorTest(unittest.TestCase):
    def test_errors_answers(self):
        cases = (
            ({'errors': [{'status': '404', 'title': 'Not Found', 'detail': 'No such album'}]},
             'item: 404 Not Found: No such album'),
            ({'errors': [{'status': '400', 'title': 'Bad'}]}, 'item: 400 Bad:'),
            ({'errors': [{}]}, 'item: ? error:'),
            ({'errors': ['junk']}, 'item: ? error:'),
            ({'errors': 'Unauthorized'}, 'item: ? error:'),
        )
        for answer, message in cases:
            error = api_error(answer, 'item')
            self.assertIsInstance(error, EngineError, answer)
            self.assertEqual((error.code, error.message), ('api', message), answer)
        self.assertEqual(api_error(cases[0][0], 'item').status, 404)
        self.assertIsNone(api_error(cases[2][0], 'item').status)
        self.assertEqual(api_error({'errors': [{'status': 503}]}, 'x').status, 503)

    def test_anything_else_is_no_error(self):
        for answer in ({'data': []}, {'errors': []}, {'errors': None}, {}, None, [], 'text'):
            self.assertIsNone(api_error(answer, 'item'), answer)


class StatusTest(unittest.TestCase):
    def test_http_status(self):
        for value, status in (('404', 404), (' 429 ', 429), (503, 503), ('4o4', None),
                              ('', None), (None, None), (True, None), (42, None), (4.0, None)):
            self.assertEqual(http_status(value), status, value)

    def test_what_is_final(self):
        def error(code='api', status=None):
            return EngineError(code, 'x', status=status)

        for final in (error(status=400), error(status=403), error(status=404),
                      error('timeout')):
            self.assertTrue(is_final(final), (final.code, final.status))
        for passing in (error(status=429), error(status=500), error(status=503), error()):
            self.assertFalse(is_final(passing), (passing.code, passing.status))


class LyricsLanguagesTest(unittest.TestCase):
    def test_the_tag_and_the_script_of_the_pronunciations(self):
        cases = {
            'en_GB.UTF-8': ('en-GB', 'en-Latn'),
            'de_DE@euro': ('de-DE', 'de-Latn'),
            'pt_BR': ('pt-BR', 'pt-Latn'),
            'ja_JP.UTF-8': ('ja-JP', 'ja-Kana'),
            'ko_KR.UTF-8': ('ko-KR', 'ko-Hang'),
            'zh_TW.UTF-8': ('zh-TW', 'zh-Hans'),
            'ru_RU.UTF-8': ('ru-RU', 'ru-Cyrl'),
            'sr_RS.UTF-8@latin': ('sr-RS', 'sr-Latn'),  # @latin: Latin whatever the language
            'el': ('el', 'el-Grek'),
            'fr-CA': ('fr-CA', 'fr-Latn'),
        }
        for name, (tag, script) in cases.items():
            self.assertEqual(lyrics_languages(name), {'lyrics': tag, 'script': script}, name)

    def test_no_language_is_english(self):
        for name in ('C', 'C.UTF-8', 'POSIX', '', None, '123'):
            self.assertEqual(lyrics_languages(name), {'lyrics': 'en', 'script': 'en-Latn'}, name)


if __name__ == '__main__':
    unittest.main()
