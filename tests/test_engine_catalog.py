# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Unit tests for src/engine/catalog.py: an artist's, album's and playlist's page and their
views, a song's credits, a playlist's suggested songs."""

import json
import pathlib
import time
import unittest

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)


from applemusic import engine as engine_module
from applemusic.backend import api, normalize
from applemusic.backend.errors import EngineError
from tests.engine_fixture import FIXTURES, EngineFixture


class ArtistTest(EngineFixture):
    """artist_page, artist_view and catalog_artist: the reads they make, the shaping, the
    day-long cache, and the demo's own answers."""

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    def fixture(self):
        with open(FIXTURES / 'catalog_artist.json', encoding='utf-8') as file:
            return json.load(file)

    async def test_the_page_is_one_read_kept_for_a_day(self):
        await self.up()
        path = '/v1/catalog/us/artists/1724049001'
        self.page.api_answers[path] = self.fixture()
        answer = await self.engine.artist_page('1724049001')
        self.assertEqual(self.page.api_calls, [path])
        params = self.page.api_params[0]
        self.assertIn('top-songs', params['views'].split(','))
        self.assertIn('more-to-see', params['views'].split(','))
        self.assertEqual(params['extend'],
                         'artistBio,bornOrFormed,editorialArtwork,hero,inFavorites,isGroup,origin')
        self.assertEqual(answer['artist']['title'], 'Paper Parachutes')
        self.assertEqual(answer['latest']['item']['title'], 'Ladders of Rain')
        self.assertIn('cached', answer)
        self.assertTrue((self.cache / 'artists' / '1724049001.json').is_file())
        await self.engine.stop()
        again = await self.engine.artist_page('1724049001')  # from the file, the engine down
        self.assertEqual(again['shelves'], answer['shelves'])
        self.assertEqual(len(self.page.api_calls), 1)

    async def test_a_library_id_is_not_a_catalog_artist(self):
        await self.up()
        with self.assertRaises(EngineError) as raised:
            await self.engine.artist_page('l.art_0123456789ab')
        self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.api_calls, [])

    async def test_a_view_is_read_whole(self):
        await self.up()
        path = '/v1/catalog/us/artists/1724049001/view/full-albums'
        album = self.fixture()['data'][0]['views']['full-albums']['data'][0]
        self.page.api_answers[path] = {'data': [album], 'next': f'{path}?offset=1'}
        self.page.api_answers[f'{path}?offset=1'] = {
            'data': [dict(album, id='1724049111')]}
        items = await self.engine.artist_view('1724049001', 'full-albums')
        self.assertEqual(self.page.api_calls, [path, f'{path}?offset=1'])
        self.assertEqual(self.page.api_params[0], {'limit': 100})
        self.assertEqual([(item['id'], item['subtitle']) for item in items],
                         [('1724049100', '2026'), ('1724049111', '2026')])
        with self.assertRaises(EngineError) as raised:
            await self.engine.artist_view('1724049001', 'library-albums')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_a_library_artist_is_found_through_its_songs(self):
        await self.up()
        base = '/v1/catalog/us/songs'

        def song(artists):
            return {'data': [{'id': 's', 'relationships': {'artists': {'data': [
                {'id': artist_id, 'attributes': {'name': name}} for artist_id, name in artists]}}}]}

        # The first song is gone, the second is a duet: the artist named as the library's.
        self.page.api_answers[f'{base}/1'] = {'errors': [{'status': '404', 'title': 'no'}]}
        self.page.api_answers[f'{base}/2'] = song([('7', 'Mara Lind'),
                                                   ('1724049001', 'Paper  Parachutes')])
        found = await self.engine.catalog_artist('paper parachutes', ['1', '2', '3'])
        self.assertEqual(found, '1724049001')
        self.assertEqual(self.page.api_calls, [f'{base}/1', f'{base}/2'])
        self.assertEqual(self.page.api_params[1], {'include': 'artists'})
        # Remembered, a miss too.
        self.assertEqual(await self.engine.catalog_artist('Paper Parachutes', ['2']),
                         '1724049001')
        self.page.api_answers[f'{base}/4'] = song([('8', 'Someone Else')])
        self.assertIsNone(await self.engine.catalog_artist('Nobody', ['4']))
        self.assertIsNone(await self.engine.catalog_artist('nobody', ['4']))
        self.assertEqual(len(self.page.api_calls), 3)

    async def test_related_reads_a_song_with_its_album_and_artists(self):
        await self.up()
        path = '/v1/catalog/us/songs/1724049201'
        self.page.api_answers[path] = {'data': [{'id': '1724049201', 'type': 'songs',
                                                 'relationships': {
            'albums': {'data': [{'id': '1724049100', 'type': 'albums', 'attributes': {
                'name': 'Ladders of Rain', 'artistName': 'Paper Parachutes'}}]},
            'artists': {'data': [
                {'id': '1724049001', 'type': 'artists',
                 'attributes': {'name': 'Paper Parachutes'}},
                {'id': '1724049002', 'type': 'artists'}]}}}]}  # one Apple did not include
        found = await self.engine.related('song', '1724049201')
        self.assertEqual(self.page.api_calls, [path])
        self.assertEqual(self.page.api_params[0], {'include': 'albums,artists'})
        self.assertEqual((found['album']['id'], found['album']['title'],
                          found['album']['subtitle']),
                         ('1724049100', 'Ladders of Rain', 'Paper Parachutes'))
        self.assertEqual([(artist['id'], artist['kind'], artist['title'])
                          for artist in found['artists']],
                         [('1724049001', 'artist', 'Paper Parachutes')])
        # Remembered for the session, until the engine stops (another account may follow).
        self.assertEqual(await self.engine.related('song', '1724049201'), found)
        self.assertEqual(len(self.page.api_calls), 1)
        await self.engine.stop()
        await self.up()
        await self.engine.related('song', '1724049201')
        self.assertEqual(self.page.api_calls[-1], path)
        self.assertEqual(len([call for call in self.page.api_calls if call == path]), 2)

    async def test_related_of_an_album_and_what_it_refuses(self):
        await self.up()
        path = '/v1/catalog/us/albums/1724049100'
        self.page.api_answers[path] = {'data': [{'id': '1724049100', 'type': 'albums',
                                                 'attributes': {'name': 'Ladders of Rain'},
                                                 'relationships': {'artists': {'data': [
            {'id': '1724049001', 'type': 'artists',
             'attributes': {'name': 'Paper Parachutes'}}]}}}]}
        found = await self.engine.related('album', '1724049100')
        self.assertEqual(self.page.api_params[0], {'include': 'artists'})
        self.assertIsNone(found['album'])
        self.assertEqual([artist['id'] for artist in found['artists']], ['1724049001'])
        for kind, item_id in (('song', 'i.abc'), ('playlist', 'pl.1'), ('song', '')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.related(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(len(self.page.api_calls), 1)

    async def test_related_needs_a_sign_in(self):
        await self.up(authorized=False)
        with self.assertRaises(EngineError) as raised:
            await self.engine.related('song', '1724049201')
        self.assertEqual(raised.exception.code, 'not-signed-in')

    async def test_the_demo_answers_from_its_own_cache(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(normalize.artist_cache_path(str(self.cache), '1724049001'))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'id': '1724049001', 'shelves': [], 'demo': True,
                                    'cached': '2020-01-01T00:00:00Z'}), encoding='utf-8')
        answer = await demo.artist_page('1724049001')  # old, and still the demo's answer
        self.assertEqual(answer['id'], '1724049001')
        self.assertNotIn('stale', answer)
        # One of Apple's, kept by the app before: not the demo's to show.
        apple = pathlib.Path(normalize.artist_cache_path(str(self.cache), '1724049002'))
        apple.write_text(json.dumps({'id': '1724049002', 'shelves': [],
                                     'cached': '2020-01-01T00:00:00Z'}), encoding='utf-8')
        for coro in (demo.artist_page('1724049002'), demo.artist_page('1724049003'),
                     demo.browse(), demo.radio(), demo.charts(), demo.replay(),
                     demo.catalog_artist('Paper Parachutes', ['1']),
                     demo.related('song', '1724049201')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'engine-down')


class AlbumPageTest(EngineFixture):
    """album_page and album_view: the reads they make (the album with its views, then its
    artist's albums; a library album's catalog album through one of its songs), the day-long
    cache, what a failure leaves out, and the demo's own answers."""

    ALBUM = '/v1/catalog/us/albums/1724049100'
    MORE_BY = '/v1/catalog/us/artists/1724049001/view/full-albums'

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    def answer(self, more_by=True):
        with open(FIXTURES / 'catalog_album_page.json', encoding='utf-8') as file:
            raw = json.load(file)
        self.page.api_answers[self.ALBUM] = raw['album']
        if more_by:
            self.page.api_answers[self.MORE_BY] = raw['moreBy']

    async def test_two_reads_kept_for_a_day(self):
        await self.up()
        self.answer()
        answer = await self.engine.album_page('1724049100')
        self.assertEqual(self.page.api_calls, [self.ALBUM, self.MORE_BY])
        self.assertEqual(self.page.api_params[0]['views'].split(','),
                         ['other-versions', 'related-videos', 'appears-on', 'you-might-also-like'])
        self.assertEqual(self.page.api_params[0]['include'], 'artists')
        self.assertEqual(self.page.api_params[1], {'limit': 30})
        self.assertEqual(answer['release']['copyright'], '℗ 2026 Invented Records Ltd')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['other-versions', 'more-by-artist', 'appears-on', 'you-might-also-like'])
        self.assertIn('cached', answer)
        self.assertTrue((self.cache / 'albums' / '1724049100.json').is_file())
        await self.engine.stop()
        again = await self.engine.album_page('1724049100')  # from the file, the engine down
        self.assertEqual(again['shelves'], answer['shelves'])
        self.assertEqual(len(self.page.api_calls), 2)

    async def test_an_answer_kept_with_other_views_is_asked_again(self):
        # An older app asked for `related-albums`, which Apple has no view of: what it kept
        # lacks You Might Also Like, so it is not fresh, however young.
        path = pathlib.Path(normalize.album_cache_path(str(self.cache), '1724049100'))
        path.parent.mkdir(parents=True)
        old = {'id': '1724049100', 'artistId': '', 'artistName': '', 'release': {},
               'shelves': [], 'cached': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        path.write_text(json.dumps(old), encoding='utf-8')
        await self.up()
        self.answer()
        answer = await self.engine.album_page('1724049100')
        self.assertEqual(self.page.api_calls, [self.ALBUM, self.MORE_BY])
        self.assertIn('you-might-also-like', [shelf['key'] for shelf in answer['shelves']])
        self.assertEqual(answer['basis'], ','.join(api.ALBUM_VIEWS))
        again = await self.engine.album_page('1724049100')  # kept with these views: fresh
        self.assertEqual(again['shelves'], answer['shelves'])
        self.assertEqual(len(self.page.api_calls), 2)

    async def test_a_library_album_is_found_through_a_song(self):
        await self.up()
        self.answer()
        song = '/v1/catalog/us/songs/1724049201'
        self.page.api_answers[song] = {'data': [{'id': '1724049201', 'type': 'songs',
                                                 'relationships': {'albums': {'data': [
                                                     {'id': '1724049100', 'type': 'albums'}]}}}]}
        answer = await self.engine.album_page('l.aW52ZW50ZWQ', song_id='1724049201')
        self.assertEqual(self.page.api_calls, [song, self.ALBUM, self.MORE_BY])
        self.assertEqual(self.page.api_params[0], {'include': 'albums'})
        self.assertEqual(answer['id'], '1724049100')
        # Kept under the library album's id, which is what the page asks by.
        self.assertTrue((self.cache / 'albums' / 'l.aW52ZW50ZWQ.json').is_file())

    async def test_a_song_on_no_catalog_album_is_a_404(self):
        await self.up()
        self.page.api_answers['/v1/catalog/us/songs/1724049201'] = {'data': [{'id': 's'}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.album_page('l.aW52ZW50ZWQ', song_id='1724049201')
        self.assertEqual((raised.exception.code, raised.exception.status), ('api', 404))
        self.assertFalse((self.cache / 'albums').exists())

    async def test_more_by_left_out_when_its_read_fails_and_not_kept(self):
        await self.up()
        self.answer(more_by=False)  # the artist's view answers 404
        answer = await self.engine.album_page('1724049100')
        self.assertEqual(self.page.api_calls, [self.ALBUM, self.MORE_BY])
        self.assertNotIn('more-by-artist', [shelf['key'] for shelf in answer['shelves']])
        self.assertIn('cached', answer)
        self.assertFalse((self.cache / 'albums' / '1724049100.json').exists())
        # The next visit asks again, and a whole answer is kept.
        self.answer()
        answer = await self.engine.album_page('1724049100')
        self.assertEqual(self.page.api_calls, [self.ALBUM, self.MORE_BY] * 2)
        self.assertIn('more-by-artist', [shelf['key'] for shelf in answer['shelves']])
        self.assertTrue((self.cache / 'albums' / '1724049100.json').is_file())

    async def test_an_album_the_catalog_lacks(self):
        await self.up()
        with self.assertRaises(EngineError) as raised:
            await self.engine.album_page('1724049199')
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.page.api_calls, ['/v1/catalog/us/albums/1724049199'])

    async def test_what_it_refuses(self):
        await self.up()
        for album_id, song_id in (('', None), ('l.aW52ZW50ZWQ', None), (None, '1')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.album_page(album_id, song_id=song_id)
            self.assertEqual(raised.exception.code, 'usage')
        for album_id, view in (('1724049100', 'full-albums'), ('l.aW52ZW50ZWQ', 'appears-on'),
                               ('', 'appears-on')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.album_view(album_id, view)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.api_calls, [])

    async def test_a_view_is_read_whole(self):
        await self.up()
        path = f'{self.ALBUM}/view/you-might-also-like'
        self.answer()
        views = self.page.api_answers[self.ALBUM]['data'][0]['views']
        album = views['you-might-also-like']['data'][0]
        self.page.api_answers[path] = {'data': [album], 'next': f'{path}?offset=1'}
        self.page.api_answers[f'{path}?offset=1'] = {'data': [dict(album, id='1724049301')]}
        items = await self.engine.album_view('1724049100', 'you-might-also-like')
        self.assertEqual(self.page.api_calls, [path, f'{path}?offset=1'])
        self.assertEqual(self.page.api_params[0], {'limit': 100})
        self.assertEqual([(item['id'], item['subtitle']) for item in items],
                         [('1724049300', 'Mara Lind'), ('1724049301', 'Mara Lind')])

    async def test_signed_out(self):
        await self.up(authorized=False)
        with self.assertRaises(EngineError) as raised:
            await self.engine.album_page('1724049100')
        self.assertEqual(raised.exception.code, 'not-signed-in')

    async def test_the_demo_answers_from_its_own_cache(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(normalize.album_cache_path(str(self.cache), '1724049100'))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'id': '1724049100', 'shelves': [], 'release': {},
                                    'demo': True, 'cached': '2020-01-01T00:00:00Z'}),
                        encoding='utf-8')
        answer = await demo.album_page('1724049100')
        self.assertEqual(answer['id'], '1724049100')
        self.assertNotIn('stale', answer)
        for coro in (demo.album_page('1724049110'), demo.album_view('1724049100', 'appears-on')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'engine-down')


class PlaylistPageTest(EngineFixture):
    """playlist_page, playlist_view and curator_playlists: the reads they make (the playlist
    with its curator and views, again with the documented views alone after a 400, then an
    Apple curator's playlists), the day-long cache, what they refuse, and the demo's own
    answers."""

    PLAYLIST = '/v1/catalog/us/playlists/pl.aW52ZW50ZWRwbA'
    CURATOR = '/v1/catalog/us/apple-curators/1724049500/playlists'

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    def answer(self, curator_playlists=True):
        with open(FIXTURES / 'catalog_playlist_page.json', encoding='utf-8') as file:
            self.page.api_answers[self.PLAYLIST] = json.load(file)
        if curator_playlists:
            with open(FIXTURES / 'curator_playlists.json', encoding='utf-8') as file:
                self.page.api_answers[self.CURATOR] = json.load(file)

    async def test_two_reads_kept_for_a_day(self):
        await self.up()
        self.answer()
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(self.page.api_calls, [self.PLAYLIST, self.CURATOR])
        self.assertEqual(self.page.api_params[0]['views'].split(','),
                         ['featured-artists', 'more-by-curator', 'you-might-also-like'])
        self.assertEqual(self.page.api_params[0]['include'], 'curator')
        # More By is the Apple curator's own playlists: Apple's view of it is always empty.
        self.assertEqual(self.page.api_params[1], {'limit': api.CURATOR_PLAYLISTS_LIMIT})
        self.assertEqual(answer['curator']['id'], '1724049500')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['featured-artists', 'more-by-curator', 'you-might-also-like'])
        self.assertEqual([item['id'] for item in answer['shelves'][1]['items']],
                         ['pl.aW52ZW50ZWRwMg'])
        self.assertEqual(answer['basis'], ','.join(api.PLAYLIST_VIEWS))
        self.assertTrue((self.cache / 'playlists' / 'pl.aW52ZW50ZWRwbA.json').is_file())
        await self.engine.stop()
        again = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')  # the file, engine down
        self.assertEqual(again['shelves'], answer['shelves'])
        self.assertEqual(len(self.page.api_calls), 2)

    async def test_more_by_left_out_when_its_read_fails_and_not_kept(self):
        await self.up()
        path = self.cache / 'playlists' / 'pl.aW52ZW50ZWRwbA.json'
        self.answer(curator_playlists=False)  # the curator's playlists answer 404
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(self.page.api_calls, [self.PLAYLIST, self.CURATOR])
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['featured-artists', 'you-might-also-like'])
        self.assertIn('cached', answer)
        self.assertFalse(path.exists())
        # The next visit asks again, and a whole answer is kept.
        self.answer()
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(self.page.api_calls, [self.PLAYLIST, self.CURATOR] * 2)
        self.assertIn('more-by-curator', [shelf['key'] for shelf in answer['shelves']])
        self.assertTrue(path.is_file())

    async def test_a_partial_answer_leaves_an_older_whole_one_kept(self):
        await self.up()
        path = self.cache / 'playlists' / 'pl.aW52ZW50ZWRwbA.json'
        self.answer()
        await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        kept = path.read_bytes()
        del self.page.api_answers[self.CURATOR]
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA', refresh=True)
        self.assertNotIn('more-by-curator', [shelf['key'] for shelf in answer['shelves']])
        self.assertEqual(path.read_bytes(), kept)

    async def test_no_second_read_without_an_apple_curator(self):
        await self.up()
        self.answer()
        resource = self.page.api_answers[self.PLAYLIST]['data'][0]
        resource['relationships']['curator']['data'] = [{
            'id': 'sp.aW52ZW50ZWQ', 'type': 'social-profiles',
            'attributes': {'name': 'Invented Listener',
                           'url': 'https://music.apple.com/profile/inventedlistener'}}]
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(self.page.api_calls, [self.PLAYLIST])
        self.assertEqual((answer['curator']['kind'], answer['curator']['url']),
                         ('link', 'https://music.apple.com/profile/inventedlistener'))

    async def test_a_400_is_asked_again_with_the_documented_views(self):
        await self.up()
        with open(FIXTURES / 'catalog_playlist_page.json', encoding='utf-8') as file:
            raw = json.load(file)
        answers = [{'errors': [{'status': '400', 'title': 'Invalid Parameter Value'}]}, raw]

        class Answers(dict):
            def get(self, key, default=None):
                return answers.pop(0) if key == PlaylistPageTest.PLAYLIST else default

        self.page.api_answers = Answers()
        answer = await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(self.page.api_calls, [self.PLAYLIST, self.PLAYLIST, self.CURATOR])
        self.assertEqual([params['views'] for params in self.page.api_params[:2]],
                         [','.join(api.PLAYLIST_VIEWS), 'featured-artists,more-by-curator'])
        self.assertEqual(answer['curator']['id'], '1724049500')

    async def test_a_playlist_the_catalog_lacks(self):
        await self.up()
        with self.assertRaises(EngineError) as raised:
            await self.engine.playlist_page('pl.aW52ZW50ZWQ5')
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(self.page.api_calls, ['/v1/catalog/us/playlists/pl.aW52ZW50ZWQ5'])
        self.assertFalse((self.cache / 'playlists').exists())

    async def test_what_it_refuses(self):
        await self.up()
        for playlist_id in ('', None, 'p.aW52ZW50ZWQ', 'l.pl001'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.playlist_page(playlist_id)
            self.assertEqual(raised.exception.code, 'usage')
        for playlist_id, view in (('pl.aW52ZW50ZWRwbA', 'tracks'), ('p.aW52', 'featured-artists'),
                                  ('', 'featured-artists'),
                                  # Apple has no view of it to read (a 404): curator_playlists.
                                  ('pl.aW52ZW50ZWRwbA', 'more-by-curator')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.playlist_view(playlist_id, view)
            self.assertEqual(raised.exception.code, 'usage')
        for curator_id in ('', None, '../x', 'a/b'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.curator_playlists(curator_id)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.api_calls, [])

    async def test_a_view_is_read_whole(self):
        await self.up()
        path = f'{self.PLAYLIST}/view/featured-artists'
        self.answer()
        view = self.page.api_answers[self.PLAYLIST]['data'][0]['views']['featured-artists']
        first, second = view['data'][:2]
        self.page.api_answers[path] = {'data': [first], 'next': f'{path}?offset=1'}
        self.page.api_answers[f'{path}?offset=1'] = {'data': [second]}
        items = await self.engine.playlist_view('pl.aW52ZW50ZWRwbA', 'featured-artists')
        self.assertEqual(self.page.api_calls, [path, f'{path}?offset=1'])
        self.assertEqual(self.page.api_params[0], {'limit': 100})
        self.assertEqual([item['id'] for item in items], [first['id'], second['id']])

    async def test_a_curators_playlists_are_read_whole(self):
        await self.up()
        self.answer()
        own, other = self.page.api_answers[self.CURATOR]['data'][:2]
        later = f'{self.CURATOR}?offset=10'
        self.page.api_answers[self.CURATOR] = {'data': [own, other], 'next': later}
        self.page.api_answers[later] = {'data': [dict(other, id='pl.aW52ZW50ZWQ4')]}
        items = await self.engine.curator_playlists('1724049500')
        self.assertEqual(self.page.api_calls, [self.CURATOR, later])
        self.assertEqual(self.page.api_params[0], {'limit': api.CURATOR_PLAYLISTS_LIMIT})
        # Every one of them: the page leaves its own playlist out (detail.playlist_completer).
        self.assertEqual([item['id'] for item in items],
                         ['pl.aW52ZW50ZWRwbA', 'pl.aW52ZW50ZWRwMg', 'pl.aW52ZW50ZWQ4'])

    async def test_signed_out(self):
        await self.up(authorized=False)
        with self.assertRaises(EngineError) as raised:
            await self.engine.playlist_page('pl.aW52ZW50ZWRwbA')
        self.assertEqual(raised.exception.code, 'not-signed-in')

    async def test_the_demo_answers_from_its_own_cache(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(normalize.playlist_cache_path(str(self.cache), 'pl.demo001'))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'id': 'pl.demo001', 'curator': None, 'shelves': [],
                                    'demo': True, 'cached': '2020-01-01T00:00:00Z'}),
                        encoding='utf-8')
        answer = await demo.playlist_page('pl.demo001')
        self.assertEqual(answer['id'], 'pl.demo001')
        self.assertNotIn('stale', answer)
        for coro in (demo.playlist_page('pl.demo002'),
                     demo.playlist_view('pl.demo001', 'featured-artists'),
                     demo.curator_playlists('1724049500')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'engine-down')


class CreditsTest(EngineFixture):
    """credits: one read of a catalog song's credits, the shaping, the day-long cache, a 404
    as none, and the demo's own answers."""

    PATH = '/v1/catalog/us/songs/1724049201/credits'

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    async def test_one_read_kept_for_a_day(self):
        await self.up()
        with open(FIXTURES / 'song_credits.json', encoding='utf-8') as file:
            self.page.api_answers[self.PATH] = json.load(file)
        answer = await self.engine.credits('1724049201')
        self.assertEqual(self.page.api_calls, [self.PATH])
        self.assertEqual([category['kind'] for category in answer['categories']],
                         ['performer', 'composer-and-lyrics', 'production-and-engineering'])
        self.assertIn('cached', answer)
        self.assertTrue((self.cache / 'credits' / '1724049201.json').is_file())
        await self.engine.stop()
        again = await self.engine.credits('1724049201')  # from the file, the engine down
        self.assertEqual(again['categories'], answer['categories'])
        self.assertEqual(self.page.api_calls, [self.PATH])

    async def test_a_404_is_no_credits(self):
        await self.up()  # the fake page answers 404 for a path it was given nothing for
        answer = await self.engine.credits('1724049201')
        self.assertEqual(answer['categories'], [])
        self.assertEqual(self.page.api_calls, [self.PATH])

    async def test_another_failure_is_raised(self):
        await self.up()
        self.page.api_answers[self.PATH] = {'errors': [{'status': '403', 'title': 'no'}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.credits('1724049201')
        self.assertEqual(raised.exception.status, 403)
        self.assertFalse((self.cache / 'credits').exists())

    async def test_a_catalog_id_only(self):
        await self.up()
        for song_id in ('', None, 'i.aW52ZW50ZWQ'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.credits(song_id)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.api_calls, [])

    async def test_signed_out(self):
        await self.up(authorized=False)
        with self.assertRaises(EngineError) as raised:
            await self.engine.credits('1724049201')
        self.assertEqual(raised.exception.code, 'not-signed-in')

    async def test_the_demo_answers_from_its_own_cache(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(normalize.credits_cache_path(str(self.cache), '1724049201'))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'categories': [], 'demo': True,
                                    'cached': '2020-01-01T00:00:00Z'}), encoding='utf-8')
        self.assertEqual((await demo.credits('1724049201'))['categories'], [])
        with self.assertRaises(EngineError) as raised:
            await demo.credits('1724049202')
        self.assertEqual(raised.exception.code, 'engine-down')


class SuggestionsTest(EngineFixture):
    """playlist_suggestions: the bridge's one read, the shaping and the day-long cache."""

    @staticmethod
    def song(song_id, name):
        return {'id': song_id, 'type': 'songs', 'attributes': {
            'name': name, 'artistName': 'Paper Parachutes', 'albumName': 'Ladders of Rain',
            'durationInMillis': 201000, 'contentRating': 'explicit',
            'playParams': {'id': song_id, 'kind': 'song'},
            'artwork': {'url': 'https://example.invalid/{w}x{h}bb.jpg'}}}

    async def test_one_read_kept_for_a_day(self):
        self.page.authorized = True
        await self.engine.start()
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            self.song('1724049301', 'Tin Roof'), self.song('1724049302', 'Low Tide'),
            self.song('1724049301', 'Tin Roof'), {'id': '9', 'type': 'stations'}]}}
        answer = await self.engine.playlist_suggestions('p.pl1')
        self.assertEqual(self.page.bridge_calls, [('playlistSuggestions', 'p.pl1', 16, [], [], [])])
        self.assertEqual([item['id'] for item in answer['items']], ['1724049301', '1724049302'])
        song = answer['items'][0]
        self.assertEqual((song['kind'], song['title'], song['subtitle'], song['album']),
                         ('song', 'Tin Roof', 'Paper Parachutes', 'Ladders of Rain'))
        self.assertTrue(song['explicit'])
        self.assertEqual(song['play'], {'kind': 'song', 'id': '1724049301'})
        self.assertIn('cached', answer)
        self.assertTrue((self.cache / 'suggestions' / 'p.pl1.json').is_file())
        await self.engine.playlist_suggestions('p.pl1')  # from the file
        self.assertEqual(len(self.page.bridge_calls), 1)
        await self.engine.playlist_suggestions('p.pl1', refresh=True, limit=10,
                                               offered=['1724049301', 1724049302],
                                               selected=['1724049302'],
                                               previewed=[1724049301])
        self.assertEqual(self.page.bridge_calls[-1], (
            'playlistSuggestions', 'p.pl1', 10, ['1724049301', '1724049302'], ['1724049302'],
            ['1724049301']))

    async def test_asked_again_once_the_playlist_holds_other_songs(self):
        self.page.authorized = True
        await self.engine.start()
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            self.song('1724049301', 'Tin Roof')]}}
        answer = await self.engine.playlist_suggestions('p.pl1', basis='held-a')
        self.assertEqual(answer['basis'], 'held-a')
        await self.engine.playlist_suggestions('p.pl1', basis='held-a')  # from the file
        self.assertEqual(len(self.page.bridge_calls), 1)
        # A song added or removed since: another basis, so Apple is asked again, however
        # young the kept answer, and the new one is kept with it.
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            self.song('1724049302', 'Low Tide')]}}
        answer = await self.engine.playlist_suggestions('p.pl1', basis='held-b')
        self.assertEqual(len(self.page.bridge_calls), 2)
        self.assertEqual([item['id'] for item in answer['items']], ['1724049302'])
        kept = json.loads((self.cache / 'suggestions' / 'p.pl1.json').read_text('utf-8'))
        self.assertEqual(kept['basis'], 'held-b')
        await self.engine.playlist_suggestions('p.pl1', basis='held-b')
        self.assertEqual(len(self.page.bridge_calls), 2)
        # Apple out of reach: the answer for other songs is still better than none.
        await self.engine.stop()
        answer = await self.engine.playlist_suggestions('p.pl1', basis='held-c')
        self.assertTrue(answer['stale'])
        self.assertEqual([item['id'] for item in answer['items']], ['1724049302'])

    async def test_a_few_more_are_neither_read_from_the_file_nor_kept(self):
        self.page.authorized = True
        await self.engine.start()
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            self.song('1724049301', 'Tin Roof')]}}
        await self.engine.playlist_suggestions('p.pl1')
        path = self.cache / 'suggestions' / 'p.pl1.json'
        kept = path.read_text(encoding='utf-8')
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            self.song('1724049303', 'Weather Vane')]}}
        answer = await self.engine.playlist_suggestions('p.pl1', limit=4, more=True,
                                                        offered=['1724049301'])
        self.assertEqual([item['id'] for item in answer['items']], ['1724049303'])
        self.assertEqual(self.page.bridge_calls[-1],
                         ('playlistSuggestions', 'p.pl1', 4, ['1724049301'], [], []))
        self.assertEqual(path.read_text(encoding='utf-8'), kept)

    async def test_only_a_library_playlist(self):
        self.page.authorized = True
        await self.engine.start()
        with self.assertRaises(EngineError) as raised:
            await self.engine.playlist_suggestions('pl.u-catalog')
        self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_needs_a_sign_in(self):
        await self.engine.start()
        with self.assertRaises(EngineError) as raised:
            await self.engine.playlist_suggestions('p.pl1')
        self.assertEqual(raised.exception.code, 'not-signed-in')

    async def test_a_song_keeps_its_preview(self):
        self.page.authorized = True
        await self.engine.start()
        song = self.song('1724049301', 'Tin Roof')
        song['attributes']['previews'] = [{'url': 'https://example.invalid/tin-roof.m4a'}]
        plain = self.song('1724049302', 'Low Tide')
        plain['attributes']['previews'] = [{'url': 'http://example.invalid/low-tide.m4a'}]
        self.page.bridge_answers['playlistSuggestions'] = {'results': {'suggested': [
            song, plain]}}
        items = (await self.engine.playlist_suggestions('p.pl1'))['items']
        self.assertEqual(items[0]['previewUrl'], 'https://example.invalid/tin-roof.m4a')
        self.assertNotIn('previewUrl', items[1])  # only an https clip

    async def test_the_demo_answers_its_own(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(normalize.suggestions_cache_path(str(self.cache), 'l.pl001'))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'items': [], 'demo': True,
                                    'cached': '2020-01-01T00:00:00Z'}), encoding='utf-8')
        self.assertEqual((await demo.playlist_suggestions('l.pl001'))['items'], [])
        with self.assertRaises(EngineError) as raised:
            await demo.playlist_suggestions('l.pl002')
        self.assertEqual(raised.exception.code, 'engine-down')
        with self.assertRaises(EngineError) as raised:
            await demo.playlist_suggestions('l.pl001', more=True)
        self.assertEqual(raised.exception.code, 'engine-down')


if __name__ == '__main__':
    unittest.main()
