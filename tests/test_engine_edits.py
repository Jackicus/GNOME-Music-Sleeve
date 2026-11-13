# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Unit tests for src/engine/edits.py: ratings, favourite artists, the library's items, its
playlists and folders."""

import json
import pathlib
import unittest
from unittest import mock

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)


from applemusic import engine as engine_module
from applemusic.backend import api, cache_files
from applemusic.backend.errors import EngineError
from applemusic.engine import edits as edits_module
from tests.engine_fixture import FIXTURES, EngineFixture


class FavouriteArtistTest(EngineFixture):
    """An artist's favourite (their star): the favorites write, not a rating; its read past
    MusicKit's cache; the artist page's `favourite`, kept and overlaid."""

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    def fixture(self, favourite=None):
        with open(FIXTURES / 'catalog_artist.json', encoding='utf-8') as file:
            raw = json.load(file)
        if favourite is not None:
            raw['data'][0]['attributes']['inFavorites'] = favourite
        return raw

    async def test_the_write_is_the_favourites_not_a_rating(self):
        await self.up()
        rated = []
        self.engine.connect('rated', lambda _e, *args: rated.append(args))
        await self.engine.favourite_artist('1724049001')
        await self.engine.unfavourite_artist('1724049001')
        self.assertEqual(self.page.bridge_calls, [
            ('favourite', 'artists', '1724049001', True),
            ('favourite', 'artists', '1724049001', False)])
        self.assertEqual(rated, [('artist', '1724049001', 1), ('artist', '1724049001', 0)])
        for artist_id in ('l.art_0123456789ab', 'r.1', ''):
            with self.assertRaises(EngineError) as raised:
                await self.engine.favourite_artist(artist_id)
            self.assertEqual(raised.exception.code, 'usage')
        with self.assertRaises(EngineError) as raised:
            await self.engine.love('artist', '1724049001')  # no rating for an artist
        self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(len(self.page.bridge_calls), 2)

    async def test_it_needs_a_sign_in(self):
        await self.up(authorized=False)
        for coro in (self.engine.favourite_artist('1724049001'),
                     self.engine.is_favourite_artist('1724049001')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'not-signed-in')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_the_state_is_read_past_musickits_cache(self):
        await self.up()
        rated = []
        self.engine.connect('rated', lambda _e, *args: rated.append(args))
        self.page.bridge_answers['apiFresh'] = {
            'data': [{'id': '1724049001', 'type': 'artists', 'attributes': {'inFavorites': True}}]}
        self.assertTrue(await self.engine.is_favourite_artist('1724049001'))
        self.assertEqual(self.page.bridge_calls, [
            ('apiFresh', '/v1/catalog/us/artists/1724049001', {'extend': 'inFavorites'})])
        # An answer that does not say is no favourite.
        self.page.bridge_answers['apiFresh'] = {'data': [{'id': '1724049001', 'attributes': {}}]}
        self.assertFalse(await self.engine.is_favourite_artist('1724049001'))
        self.assertEqual(rated, [('artist', '1724049001', 1), ('artist', '1724049001', 0)])
        self.assertEqual(self.page.api_calls, [])  # never music(), which may be cached

    async def test_the_page_says_and_keeps_what_was_written(self):
        await self.up()
        rated = []
        self.engine.connect('rated', lambda _e, *args: rated.append(args))
        path = '/v1/catalog/us/artists/1724049001'
        self.page.api_answers[path] = self.fixture(favourite=False)
        answer = await self.engine.artist_page('1724049001')
        self.assertIs(answer['favourite'], False)
        self.assertEqual(rated, [('artist', '1724049001', 0)])
        kept = self.cache / 'artists' / '1724049001.json'
        stamp = json.loads(kept.read_text())['cached']
        await self.engine.favourite_artist('1724049001')
        # The kept page says so, as old as it was.
        written = json.loads(kept.read_text())
        self.assertIs(written['favourite'], True)
        self.assertEqual(written['cached'], stamp)
        self.assertIs((await self.engine.artist_page('1724049001'))['favourite'], True)
        self.assertEqual(self.page.api_calls, [path])  # the page was read once
        # What this session read overrides a kept answer's (one kept before a change made
        # elsewhere).
        self.page.bridge_answers['apiFresh'] = {'data': [{'attributes': {'inFavorites': False}}]}
        await self.engine.is_favourite_artist('1724049001')
        self.assertIs((await self.engine.artist_page('1724049001'))['favourite'], False)

    async def test_an_answer_that_does_not_say(self):
        await self.up()
        self.page.api_answers['/v1/catalog/us/artists/1724049001'] = self.fixture()
        rated = []
        self.engine.connect('rated', lambda _e, *args: rated.append(args))
        self.assertIsNone((await self.engine.artist_page('1724049001'))['favourite'])
        self.assertEqual(rated, [])

    async def test_the_demo_remembers_it_for_the_session(self):
        demo = engine_module.Engine(demo=True)
        path = pathlib.Path(cache_files.artist_cache_path(str(self.cache), '1724049001'))
        path.parent.mkdir(parents=True)
        page = {'id': '1724049001', 'shelves': [], 'favourite': False, 'demo': True,
                'cached': '2020-01-01T00:00:00Z'}
        path.write_text(json.dumps(page), encoding='utf-8')
        rated = []
        demo.connect('rated', lambda _e, *args: rated.append(args))
        await demo.favourite_artist('1724049001')
        self.assertEqual(rated, [('artist', '1724049001', 1)])
        self.assertIs((await demo.artist_page('1724049001'))['favourite'], True)
        self.assertEqual(json.loads(path.read_text()), page)  # the invented file untouched
        with self.assertRaises(EngineError) as raised:
            await demo.is_favourite_artist('1724049001')
        self.assertEqual(raised.exception.code, 'engine-down')


class LibraryWriteTest(EngineFixture):
    """love, unlove, rating, add_to_library, add_to_playlist and catalog_url: the bridge
    calls, with the API's types for library and catalog ids, all needing a signed-in engine.
    The fake page records the writes; nothing reaches Apple."""

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    async def test_love_and_unlove_rate_by_type(self):
        await self.up()
        rated = []
        self.engine.connect('rated', lambda _e, kind, item_id, value: rated.append(
            (kind, item_id, value)))
        await self.engine.love('song', '1000000001')
        await self.engine.love('song', 'i.song1')
        await self.engine.unlove('album', 'l.alb1')
        await self.engine.love('playlist', 'pl.u-1')
        await self.engine.love('video', '1000000009')
        await self.engine.unlove('station', 'ra.1')
        await self.engine.suggest_less('station', 'ra.1')
        await self.engine.suggest_less('album', 'l.alb1')
        self.assertEqual(self.page.bridge_calls, [
            ('rating', 'song', '1000000001', 1),
            ('rating', 'library-song', 'i.song1', 1),
            ('rating', 'library-album', 'l.alb1', 0),
            ('rating', 'playlist', 'pl.u-1', 1),
            ('rating', 'music-video', '1000000009', 1),
            ('rating', 'station', 'ra.1', 0),
            ('rating', 'station', 'ra.1', -1),
            ('rating', 'library-album', 'l.alb1', -1)])
        self.assertEqual(rated, [('song', '1000000001', 1), ('song', 'i.song1', 1),
                                 ('album', 'l.alb1', 0), ('playlist', 'pl.u-1', 1),
                                 ('video', '1000000009', 1), ('station', 'ra.1', 0),
                                 ('station', 'ra.1', -1), ('album', 'l.alb1', -1)])

    async def test_rating_reads_the_ids_form(self):
        await self.up()
        self.page.api_answers['/v1/me/ratings/songs'] = {
            'data': [{'id': '1000000001', 'type': 'ratings', 'attributes': {'value': 1}}]}
        self.page.api_answers['/v1/me/ratings/library-albums'] = {'data': []}
        self.page.api_answers['/v1/me/ratings/stations'] = {
            'data': [{'id': 'ra.1', 'type': 'ratings', 'attributes': {'value': -1}}]}
        rated = []
        self.engine.connect('rated', lambda _e, *args: rated.append(args))
        self.assertEqual(await self.engine.rating('song', '1000000001'), 1)
        self.assertEqual(await self.engine.rating('album', 'l.alb1'), 0)
        self.assertEqual(await self.engine.rating('station', 'ra.1'), -1)  # Suggest Less
        self.assertEqual(self.page.api_params[-3:], [{'ids': '1000000001'}, {'ids': 'l.alb1'},
                                                     {'ids': 'ra.1'}])
        self.assertEqual(rated, [('song', '1000000001', 1), ('album', 'l.alb1', 0),
                                 ('station', 'ra.1', -1)])

    async def test_nothing_to_rate(self):
        await self.up()
        for kind, item_id in (('artist', '1'), ('folder', 'x'), ('song', ''), (None, '1')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.love(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_add_to_library_takes_catalog_ids(self):
        await self.up()
        await self.engine.add_to_library('album', '1000000002')
        await self.engine.add_to_library('song', '1000000003')
        await self.engine.add_to_library('video', '1000000004')
        self.assertEqual(self.page.bridge_calls, [
            ('addToLibrary', 'album', '1000000002'), ('addToLibrary', 'song', '1000000003'),
            ('addToLibrary', 'music-video', '1000000004')])
        for kind, item_id in (('album', 'l.alb1'), ('song', 'i.1'), ('artist', '5'),
                              ('station', 'ra.1'), ('song', '')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.add_to_library(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_remove_from_library_by_the_library_id(self):
        await self.up()
        for kind, item_id in (('song', 'i.song1'), ('album', 'l.alb1'), ('video', 'i.vid1'),
                              ('playlist', 'p.pl2')):
            self.assertEqual(await self.engine.remove_from_library(kind, item_id), item_id)
        self.assertEqual(self.page.bridge_calls, [
            ('removeFromLibrary', 'songs', 'i.song1'), ('removeFromLibrary', 'albums', 'l.alb1'),
            ('removeFromLibrary', 'music-videos', 'i.vid1'),
            ('removeFromLibrary', 'playlists', 'p.pl2')])
        self.assertEqual(self.page.api_calls, [])  # no read before it
        for kind, item_id in (('artist', 'l.art1'), ('station', 'ra.1'), ('song', ''),
                              (None, 'i.1')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.remove_from_library(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_a_catalog_id_is_read_for_its_library_twin_first(self):
        # Apple answers a DELETE by catalog id with a 500: the library id is asked for.
        await self.up()
        self.page.api_answers['/v1/catalog/us'] = {'data': [{
            'id': '1000000001', 'type': 'songs', 'attributes': {'inLibrary': True},
            'relationships': {'library': {'data': [{'id': 'i.song1',
                                                    'type': 'library-songs'}]}}}]}
        self.assertEqual(await self.engine.remove_from_library('song', '1000000001'),
                         'i.song1')
        self.assertEqual(self.page.api_params, [{
            'ids[songs]': '1000000001', 'relate': 'library', 'fields[songs]': 'inLibrary',
            'omit[resource]': 'autos'}])
        self.assertEqual(self.page.bridge_calls, [('removeFromLibrary', 'songs', 'i.song1')])
        # Not in the library: nothing is sent.
        self.page.api_answers['/v1/catalog/us'] = {'data': [{
            'id': '1000000002', 'type': 'songs', 'attributes': {'inLibrary': False},
            'relationships': {'library': {'data': []}}}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.remove_from_library('song', '1000000002')
        self.assertEqual((raised.exception.code, raised.exception.status), ('api', 404))
        self.assertEqual(len(self.page.bridge_calls), 1)

    async def test_in_library_reads_through_the_request_builder(self):
        await self.up()
        self.assertTrue(await self.engine.in_library('song', 'i.song1'))
        self.page.bridge_answers['libraryHas'] = {'has': False}
        self.assertFalse(await self.engine.in_library('album', 'l.alb1'))
        self.assertEqual(self.page.bridge_calls, [('libraryHas', 'songs', 'i.song1'),
                                                  ('libraryHas', 'albums', 'l.alb1')])
        with self.assertRaises(EngineError) as raised:
            await self.engine.in_library('song', '1000000001')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_add_to_playlist_types_the_song(self):
        await self.up()
        await self.engine.add_to_playlist('p.1', 'i.song1')
        await self.engine.add_to_playlist('p.1', '1000000001')
        await self.engine.add_to_playlist('p.1', 'i.video1', kind='video')
        await self.engine.add_to_playlist('p.1', '1000000009', kind='musicVideo')
        self.assertEqual(self.page.bridge_calls, [
            ('addToPlaylist', 'p.1', [{'id': 'i.song1', 'type': 'library-songs'}]),
            ('addToPlaylist', 'p.1', [{'id': '1000000001', 'type': 'songs'}]),
            ('addToPlaylist', 'p.1', [{'id': 'i.video1', 'type': 'library-music-videos'}]),
            ('addToPlaylist', 'p.1', [{'id': '1000000009', 'type': 'music-videos'}])])
        for playlist_id, song_id, kind in (('pl.u-1', '1', 'song'), ('', '1', 'song'),
                                           ('p.1', '', 'song'), ('p.1', '1', 'album'),
                                           ('p.1', '1', 'station'), ('p.1', '1', None)):
            with self.assertRaises(EngineError) as raised:
                await self.engine.add_to_playlist(playlist_id, song_id, kind)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_many_tracks_are_added_in_batches_in_order(self):
        # An album's or a playlist's songs: one POST of their list per PLAYLIST_BATCH, in
        # order, library and catalog ids each typed as its own.
        await self.up()
        tracks = [('song', f'i.s{n}') for n in range(5)] + [('video', '1000000009'),
                                                            ('song', '1000000001')]
        with mock.patch.object(api, 'PLAYLIST_BATCH', 3):
            self.assertEqual(await self.engine.add_tracks_to_playlist('p.1', tracks), 7)
        sent = [call[2] for call in self.page.bridge_calls]
        self.assertEqual([len(batch) for batch in sent], [3, 3, 1])
        self.assertEqual([entry['id'] for batch in sent for entry in batch],
                         [track_id for _kind, track_id in tracks])
        self.assertEqual(sent[1][2], {'id': '1000000009', 'type': 'music-videos'})
        self.assertEqual(sent[2][0], {'id': '1000000001', 'type': 'songs'})
        # Nothing to add, or something that cannot go in: nothing sent.
        self.page.bridge_calls.clear()
        for bad in ([], [('song', 'i.s1'), ('album', 'l.1')]):
            with self.assertRaises(EngineError) as raised:
                await self.engine.add_tracks_to_playlist('p.1', bad)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_a_batch_refused_partway_says_how_many_went_in(self):
        await self.up()
        page = self.page
        posts = []

        def refuse_second(message):
            if 'addToPlaylist' in message['params']['expression']:
                posts.append(message)
                if len(posts) == 2:
                    return {'result': {'type': 'object'}, 'exceptionDetails': {
                        'text': 'Uncaught', 'exception': {
                            'description': 'Error: HTTP 500 Unable to update tracks'}}}
            return page(message)

        self.chrome.responders['Runtime.evaluate'] = refuse_second
        tracks = [('song', f'i.s{n}') for n in range(5)]
        with mock.patch.object(api, 'PLAYLIST_BATCH', 2):
            with self.assertRaises(EngineError) as raised:
                await self.engine.add_tracks_to_playlist('p.1', tracks)
        self.assertEqual(raised.exception.code, 'api')
        self.assertIn('after 2 tracks', raised.exception.message)
        self.assertEqual(len(posts), 2)  # the third batch is not sent

    async def test_a_refused_write_is_api(self):
        await self.up()

        def refuse(message):
            expression = message['params']['expression']
            if 'addToPlaylist' in expression:
                return {'result': {'type': 'object'}, 'exceptionDetails': {
                    'text': 'Uncaught', 'exception': {
                        'description': 'Error: HTTP 403 Forbidden: Not allowed'}}}
            return page(message)

        page = self.page
        self.chrome.responders['Runtime.evaluate'] = refuse
        with self.assertRaises(EngineError) as raised:
            await self.engine.add_to_playlist('p.1', 'i.song1')
        self.assertEqual(raised.exception.code, 'api')
        self.assertIn('403', raised.exception.message)

    async def test_songs_found_reads_the_library_and_the_catalog_by_id(self):
        self.page.storefront = 'gb'
        await self.up()
        self.page.api_answers['/v1/me/library/songs'] = {'data': [
            {'id': 'i.song1', 'type': 'library-songs'}]}
        self.page.api_answers['/v1/catalog/gb/songs'] = {'data': [
            {'id': '1000000001', 'type': 'songs'}]}
        found = await self.engine.songs_found(['i.song1', 'i.song2', '1000000001',
                                               '1000000002', 'i.song1'])
        self.assertEqual(found, {'i.song1', '1000000001'})
        reads = dict(zip(self.page.api_calls, self.page.api_params, strict=True))
        self.assertEqual(reads['/v1/me/library/songs'], {'ids': 'i.song1,i.song2'})
        self.assertEqual(reads['/v1/catalog/gb/songs'], {'ids': '1000000001,1000000002'})

    async def test_songs_found_none_and_many(self):
        await self.up()
        # No answer for the library's read: Apple's 404, none of them is there.
        self.assertEqual(await self.engine.songs_found(['i.gone1']), set())
        self.page.api_calls.clear()
        self.page.api_params.clear()
        self.page.api_answers['/v1/catalog/us/songs'] = {'data': []}
        ids = [str(1000000000 + n) for n in range(edits_module.SONG_IDS_PER_READ + 1)]
        self.assertEqual(await self.engine.songs_found(ids), set())
        self.assertEqual([len(params['ids'].split(',')) for params in self.page.api_params],
                         [edits_module.SONG_IDS_PER_READ, 1])

    async def test_catalog_url_of_a_library_album(self):
        await self.up()
        self.page.api_answers['/v1/me/library/albums/l.alb1/catalog'] = {'data': [
            {'id': '1000000002', 'type': 'albums',
             'attributes': {'url': 'https://music.apple.com/gb/album/x/1000000002'}}]}
        self.page.api_answers['/v1/me/library/albums/l.alb2/catalog'] = {'data': []}
        self.assertEqual(await self.engine.catalog_url('album', 'l.alb1'),
                         'https://music.apple.com/gb/album/x/1000000002')
        self.assertIsNone(await self.engine.catalog_url('album', 'l.alb2'))
        with self.assertRaises(EngineError) as raised:
            await self.engine.catalog_url('album', '1000000002')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_writes_need_a_signed_in_engine(self):
        for coro in (self.engine.love('song', '1'), self.engine.rating('song', '1'),
                     self.engine.add_to_library('song', '1'),
                     self.engine.remove_from_library('song', 'i.1'),
                     self.engine.in_library('song', 'i.1'),
                     self.engine.add_to_playlist('p.1', '1')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'engine-down')
        await self.up(authorized=False)
        for coro in (self.engine.unlove('song', '1'), self.engine.rating('song', '1'),
                     self.engine.add_to_library('album', '1'),
                     self.engine.remove_from_library('album', 'l.1'),
                     self.engine.in_library('album', 'l.1'),
                     self.engine.add_to_playlist('p.1', 'i.1'),
                     self.engine.catalog_url('album', 'l.1')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'not-signed-in')
        self.assertEqual(self.page.bridge_calls, [])


def listed(*entries):
    """A listing page of library playlists and folders: (type, id, name) each, name None for
    one the account deleted (Apple's nameless leftover)."""
    data = []
    for kind, item_id, name in entries:
        attributes = ({'name': name, 'canEdit': True, 'canDelete': True,
                       'dateAdded': '2026-01-01T00:00:00Z'} if name is not None
                      else {'canEdit': False, 'canDelete': False,
                            'lastModifiedDate': '1970-01-01T00:00:00Z'})
        data.append({'id': item_id, 'type': f'library-{kind}s', 'attributes': attributes})
    return {'data': data}


class PlaylistWriteTest(EngineFixture):
    """Making, renaming and deleting playlists and folders, and taking one entry out of a
    playlist: the bridge calls the engine makes, from the playlist's tracks as the fake page
    lists them."""

    async def up(self):
        self.page.authorized = True
        await self.engine.start()

    def tracks(self, playlist_id, *ids):
        self.page.api_answers[(f'/v1/me/library/playlists/{playlist_id}/tracks', 0)] = {
            'data': [{'id': song_id, 'type': 'library-songs'} for song_id in ids]}

    async def test_create_edit_and_delete_a_playlist(self):
        await self.up()
        self.page.bridge_answers['createPlaylist'] = {'id': 'p.new'}
        new_id = await self.engine.create_playlist(
            ' Night Drive ', 'Late', [('song', 'i.song1'), ('song', '1000000001'),
                                      ('video', 'i.video1')], folder_id='p.fd1')
        self.assertEqual(new_id, 'p.new')
        await self.engine.create_playlist('Empty', folder_id='root')
        await self.engine.edit_playlist('p.new', name='Renamed')
        await self.engine.edit_playlist('p.new', description='')
        await self.engine.edit_playlist('p.new')  # nothing to change: nothing sent
        await self.engine.edit_playlist('p.new', public=True)
        await self.engine.edit_playlist('p.new', name='Shown', public=False)
        await self.engine.create_playlist('Public', public=True)
        await self.engine.delete_playlist('p.new')
        self.assertEqual(self.page.bridge_calls, [
            ('createPlaylist', {'name': 'Night Drive', 'description': 'Late'},
             [{'id': 'i.song1', 'type': 'library-songs'},
              {'id': '1000000001', 'type': 'songs'},
              {'id': 'i.video1', 'type': 'library-music-videos'}], 'p.fd1'),
            ('createPlaylist', {'name': 'Empty'}, [], None),
            ('updatePlaylist', 'p.new', {'name': 'Renamed'}),
            ('updatePlaylist', 'p.new', {'description': ''}),
            ('updatePlaylist', 'p.new', {'isPublic': True}),
            ('updatePlaylist', 'p.new', {'name': 'Shown', 'isPublic': False}),
            ('createPlaylist', {'name': 'Public', 'isPublic': True}, [], None),
            ('deletePlaylist', 'p.new')])

    async def test_a_new_playlist_of_many_songs_gets_the_rest_after(self):
        await self.up()
        self.page.bridge_answers['createPlaylist'] = {'id': 'p.new'}
        tracks = [('song', f'i.s{n}') for n in range(5)]
        with mock.patch.object(api, 'PLAYLIST_BATCH', 2):
            self.assertEqual(await self.engine.create_playlist('Long', tracks=tracks), 'p.new')
        calls = self.page.bridge_calls
        self.assertEqual([call[0] for call in calls],
                         ['createPlaylist', 'addToPlaylist', 'addToPlaylist'])
        self.assertEqual([entry['id'] for entry in calls[0][2]], ['i.s0', 'i.s1'])
        self.assertEqual(calls[1][1], 'p.new')
        self.assertEqual([entry['id'] for call in calls[1:] for entry in call[2]],
                         ['i.s2', 'i.s3', 'i.s4'])

    async def test_what_the_playlist_writes_refuse(self):
        await self.up()
        for coro in (self.engine.create_playlist('  '),
                     self.engine.create_playlist('X', tracks=[('album', 'l.1')]),
                     self.engine.create_playlist('X', folder_id='1000000001'),
                     self.engine.edit_playlist('p.1', name=' '),
                     self.engine.edit_playlist('pl.u-catalog', name='X'),
                     self.engine.delete_playlist('l.demo'),
                     self.engine.remove_from_playlist('p.1', ''),
                     self.engine.rename_folder('root', 'X'),
                     self.engine.delete_folder('p.playlistsroot')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])
        # A new playlist Apple answered without its id is a failure, not a success.
        self.page.bridge_answers['createPlaylist'] = {'ok': True}
        with self.assertRaises(EngineError) as raised:
            await self.engine.create_playlist('X')
        self.assertEqual(raised.exception.code, 'api')

    async def test_a_song_the_playlist_holds_once_goes_as_the_web_player_removes_it(self):
        await self.up()
        self.tracks('p.1', 'i.a', 'i.b')
        self.assertTrue(await self.engine.remove_from_playlist('p.1', 'i.b', 1))
        self.assertEqual(self.page.bridge_calls,
                         [('removeFromPlaylist', 'p.1', 'library-songs', 'i.b')])

    async def test_one_entry_of_a_song_the_playlist_holds_twice(self):
        # Apple's DELETE takes every entry of the id: the list goes back whole without the
        # one at the index, the other entry kept.
        await self.up()
        self.tracks('p.1', 'i.a', 'i.b', 'i.a', 'i.c')
        await self.engine.remove_from_playlist('p.1', 'i.a', 2)
        # The list changed since the page showed it: the entry of that id nearest the index.
        self.tracks('p.2', 'i.x', 'i.a', 'i.b', 'i.a')
        await self.engine.remove_from_playlist('p.2', 'i.a', 0)
        entry = {'type': 'library-songs'}
        self.assertEqual(self.page.bridge_calls, [
            ('replacePlaylistTracks', 'p.1', [dict(entry, id='i.a'), dict(entry, id='i.b'),
                                              dict(entry, id='i.c')]),
            ('replacePlaylistTracks', 'p.2', [dict(entry, id='i.x'), dict(entry, id='i.b'),
                                              dict(entry, id='i.a')])])

    async def test_a_song_no_longer_in_the_playlist_is_nothing_to_do(self):
        await self.up()
        self.tracks('p.1', 'i.a')
        self.assertFalse(await self.engine.remove_from_playlist('p.1', 'i.z', 0))
        # An empty playlist: Apple answers 404 for its tracks.
        self.assertFalse(await self.engine.remove_from_playlist('p.empty', 'i.a', 0))
        self.assertEqual(self.page.bridge_calls, [])

    async def test_a_reorder_puts_every_entry_back_in_the_new_order(self):
        # Every entry read goes back by its own id and type, one Apple cannot play (no
        # playParams) and a catalog song among them; of a song held twice, the entry moved.
        await self.up()
        self.page.api_answers[('/v1/me/library/playlists/p.1/tracks', 0)] = {'data': [
            {'id': 'i.a', 'type': 'library-songs', 'attributes': {'playParams': {}}},
            {'id': 'i.b', 'type': 'library-songs'},
            {'id': 'i.a', 'type': 'library-songs'},
            {'id': '1000000001', 'type': 'songs'},
            {'id': 'i.v', 'type': 'library-music-videos'}]}
        await self.engine.reorder_playlist('p.1', ['i.a', 'i.b', 'i.a', '1000000001', 'i.v'],
                                           [1, 2, 4, 3, 0])
        self.assertEqual(self.page.bridge_calls, [('replacePlaylistTracks', 'p.1', [
            {'id': 'i.b', 'type': 'library-songs'}, {'id': 'i.a', 'type': 'library-songs'},
            {'id': 'i.v', 'type': 'library-music-videos'}, {'id': '1000000001', 'type': 'songs'},
            {'id': 'i.a', 'type': 'library-songs'}])])

    async def test_a_reorder_over_a_list_apple_no_longer_has_writes_nothing(self):
        await self.up()
        self.tracks('p.1', 'i.a', 'i.c', 'i.b')  # reordered on another device
        self.tracks('p.2', 'i.a', 'i.b', 'i.c')  # a song added there
        self.page.api_answers[('/v1/me/library/playlists/p.3/tracks', 0)] = {'data': [
            {'id': 'i.a', 'type': 'library-songs'}, {'id': 'i.b'}]}  # an entry without a type
        for playlist_id, shown, code in (('p.1', ['i.a', 'i.b', 'i.c'], 'conflict'),
                                         ('p.2', ['i.a', 'i.b'], 'conflict'),
                                         ('p.empty', ['i.a', 'i.b'], 'conflict'),
                                         ('p.3', ['i.a', 'i.b'], 'api')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.reorder_playlist(playlist_id, shown, [1, 0] + [2] * (
                    len(shown) - 2))
            self.assertEqual(raised.exception.code, code, playlist_id)
        for playlist_id, order in (('pl.u-catalog', [0]), ('p.1', [0, 0, 1]), ('p.1', [0, 1])):
            with self.assertRaises(EngineError) as raised:
                await self.engine.reorder_playlist(playlist_id, ['i.a', 'i.b', 'i.c'], order)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_several_entries_go_in_one_write(self):
        # A selection's Remove from Playlist: the list put back without the entries chosen,
        # of a song held twice only the one chosen; the list before answered, for Undo.
        await self.up()
        self.tracks('p.1', 'i.a', 'i.b', 'i.a', 'i.c')
        before = await self.engine.remove_playlist_entries('p.1', ['i.a', 'i.b', 'i.a', 'i.c'],
                                                           [1, 2])
        entry = {'type': 'library-songs'}
        self.assertEqual(before, [dict(entry, id=track_id)
                                  for track_id in ('i.a', 'i.b', 'i.a', 'i.c')])
        self.assertEqual(self.page.bridge_calls, [
            ('replacePlaylistTracks', 'p.1', [dict(entry, id='i.a'), dict(entry, id='i.c')])])
        # Undo: the entries as they were, once Apple lists what was kept.
        self.page.bridge_calls.clear()
        self.tracks('p.1', 'i.a', 'i.c')
        await self.engine.put_back_playlist_entries('p.1', ['i.a', 'i.c'], before)
        self.assertEqual(self.page.bridge_calls, [('replacePlaylistTracks', 'p.1', before)])

    async def test_every_entry_removed_goes_as_the_web_player_removes_them(self):
        # Never an empty PUT: each song's DELETE (mode=all), once a song.
        await self.up()
        self.tracks('p.1', 'i.a', 'i.b', 'i.a')
        await self.engine.remove_playlist_entries('p.1', ['i.a', 'i.b', 'i.a'], [0, 1, 2])
        self.assertEqual(self.page.bridge_calls, [
            ('removeFromPlaylist', 'p.1', 'library-songs', 'i.a'),
            ('removeFromPlaylist', 'p.1', 'library-songs', 'i.b')])

    async def test_a_removal_or_its_undo_over_a_changed_list_writes_nothing(self):
        await self.up()
        self.tracks('p.1', 'i.a', 'i.c', 'i.b')  # changed on another device
        for coro in (self.engine.remove_playlist_entries('p.1', ['i.a', 'i.b', 'i.c'], [0]),
                     self.engine.put_back_playlist_entries('p.1', ['i.a', 'i.b'], [])):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'conflict')
        with self.assertRaises(EngineError) as raised:
            await self.engine.remove_playlist_entries('pl.u-catalog', ['i.a'], [0])
        self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_folder_children_leave_out_what_was_deleted(self):
        await self.up()
        self.page.api_answers[('/v1/me/library/playlist-folders/p.playlistsroot/children',
                               0)] = listed(('playlist-folder', 'p.fd1', 'Evenings'),
                                            ('playlist', 'p.1', 'Road Trip'),
                                            ('playlist', 'p.gone', None))
        self.assertEqual(await self.engine.folder_children(), [
            {'kind': 'folder', 'id': 'p.fd1', 'name': 'Evenings'},
            {'kind': 'playlist', 'id': 'p.1', 'name': 'Road Trip'}])
        self.assertEqual(await self.engine.folder_children('p.none'), [])  # Apple's 404

    async def test_a_folder_is_emptied_before_it_is_deleted(self):
        await self.up()
        children = '/v1/me/library/playlist-folders/{}/children'
        self.page.api_answers[(children.format('p.fd1'), 0)] = listed(
            ('playlist', 'p.1', 'Road Trip'), ('playlist-folder', 'p.fd2', 'Inner'))
        self.page.api_answers[(children.format('p.fd2'), 0)] = listed(
            ('playlist', 'p.2', 'Deep'))
        await self.engine.rename_folder('p.fd1', ' Late Evenings ')
        await self.engine.delete_folder('p.fd1')
        self.assertEqual(self.page.bridge_calls, [
            ('updateFolder', 'p.fd1', {'name': 'Late Evenings'}),
            ('deletePlaylist', 'p.1'), ('deletePlaylist', 'p.2'), ('deleteFolder', 'p.fd2'),
            ('deleteFolder', 'p.fd1')])

    async def test_create_a_folder_and_move_a_playlist_into_it(self):
        await self.up()
        self.page.bridge_answers['createFolder'] = {'id': 'p.fdnew'}
        self.assertEqual(await self.engine.create_folder(' Box ', 'p.fd1'), 'p.fdnew')
        self.assertEqual(await self.engine.create_folder('Top', 'root'), 'p.fdnew')
        await self.engine.move_to_folder('playlist', 'p.1', 'p.fdnew')
        self.assertEqual(self.page.bridge_calls, [
            ('createFolder', {'name': 'Box'}, 'p.fd1'),
            ('createFolder', {'name': 'Top'}, None),
            ('moveToFolder', 'library-playlists', 'p.1', 'p.fdnew')])

    async def test_the_top_level_and_folder_moves(self):
        await self.up()
        # The top level is Apple's root folder; a folder moves as a folder.
        await self.engine.move_to_folder('playlist', 'p.1', 'root')
        await self.engine.move_to_folder('playlist', 'p.1', None)
        await self.engine.move_to_folder('folder', 'p.fd2', 'p.fd1')
        await self.engine.move_to_folder('folder', 'p.fd2', 'root')
        self.assertEqual(self.page.bridge_calls, [
            ('moveToFolder', 'library-playlists', 'p.1', 'p.playlistsroot'),
            ('moveToFolder', 'library-playlists', 'p.1', 'p.playlistsroot'),
            ('moveToFolder', 'library-playlist-folders', 'p.fd2', 'p.fd1'),
            ('moveToFolder', 'library-playlist-folders', 'p.fd2', 'p.playlistsroot')])

    async def test_a_move_switched_off_is_refused(self):
        await self.up()
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', False), \
                mock.patch.object(api, 'MOVE_FOLDERS', False):
            for coro in (self.engine.move_to_folder('playlist', 'p.1', 'root'),
                         self.engine.move_to_folder('playlist', 'p.1', None),
                         self.engine.move_to_folder('folder', 'p.fd2', 'p.fd1')):
                with self.assertRaises(EngineError) as raised:
                    await coro
                self.assertEqual(raised.exception.code, 'usage')
            await self.engine.move_to_folder('playlist', 'p.1', 'p.fd1')  # always on
        self.assertEqual(self.page.bridge_calls,
                         [('moveToFolder', 'library-playlists', 'p.1', 'p.fd1')])

    async def test_what_the_folder_writes_refuse(self):
        await self.up()
        for coro in (self.engine.create_folder('  '),
                     self.engine.create_folder('X', '1000000001'),
                     self.engine.move_to_folder('playlist', 'pl.u-catalog', 'p.fd1'),
                     self.engine.move_to_folder('album', 'l.1', 'p.fd1'),
                     self.engine.move_to_folder('folder', 'root', 'p.fd1'),
                     self.engine.move_to_folder('folder', 'p.fd1', 'p.fd1'),
                     self.engine.move_to_folder('playlist', 'p.1', 'l.notafolder')):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(self.page.bridge_calls, [])
        self.page.bridge_answers['createFolder'] = {'ok': True}
        with self.assertRaises(EngineError) as raised:
            await self.engine.create_folder('X')
        self.assertEqual(raised.exception.code, 'api')


if __name__ == '__main__':
    unittest.main()
