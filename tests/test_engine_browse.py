# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Unit tests for src/engine/browse.py, and the catalog's search with them: the browsing
pages, each kept for a day, and the kept answers themselves (src/engine/reads.py)."""

import json
import os
import pathlib
import tempfile
import time
import unittest
from datetime import UTC, datetime
from unittest import mock

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)


from applemusic import engine as engine_module
from applemusic.backend import api, normalize, store
from applemusic.backend.errors import EngineError
from applemusic.engine import reads as reads_module
from tests.engine_fixture import FIXTURES, EngineFixture
from tests.test_client import value


def curator(curator_id, name, short=None):
    return {'id': curator_id, 'type': 'apple-curators', 'attributes': {
        'name': name, 'shortName': short or name,
        'url': f'https://music.apple.com/gb/curator/x/{curator_id}',
        'artwork': {'url': 'https://x/{w}x{h}{c}.{f}', 'bgColor': 'dd6848'}}}


class SearchTest(EngineFixture):
    """search, suggest, landing, category, browse and made_for_you: the bridge calls, the
    shaping, and the day-long caches."""

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    def fixture(self, name):
        with open(FIXTURES / name, encoding='utf-8') as file:
            return json.load(file)

    async def test_search_needs_a_signed_in_engine(self):
        await self.up(authorized=False)
        for coro in (self.engine.search('paper'), self.engine.suggest('pa'),
                     self.engine.landing(), self.engine.category('1'), self.engine.browse(),
                     self.engine.made_for_you(), self.engine.radio(), self.engine.charts(),
                     self.engine.charts(genre='21'), self.engine.genres(),
                     self.engine.replay(), self.engine.replay(year='2025'),
                     self.engine.recently_played()):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'not-signed-in')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_search_is_shaped_into_shelves(self):
        await self.up()
        self.page.bridge_answers['search'] = self.fixture('search_results.json')
        answer = await self.engine.search('  paper   parachutes ')
        self.assertEqual(self.page.bridge_calls[-1],
                         ('search', 'paper parachutes', 20, api.SEARCH_TYPES, 0, True))
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['artists', 'songs', 'albums', 'playlists'])
        self.assertEqual(answer['shelves'][2]['key'], 'albums')
        self.assertEqual(answer['shelves'][2]['title'], '')  # the Search page has the words
        self.assertEqual(set(answer), {'shelves'})
        album = answer['shelves'][2]['items'][0]
        self.assertEqual(album['groups'], [])
        self.assertTrue(album['art'].startswith('https://'))  # not on disk: a catalog URL
        self.assertIsNone(album['thumb'])
        # With a limit (per kind).
        await self.engine.search('paper', limit=5)
        self.assertEqual(self.page.bridge_calls[-1],
                         ('search', 'paper', 5, api.SEARCH_TYPES, 0, True))

    async def test_a_search_of_one_kind_pages_on(self):
        await self.up()
        self.page.bridge_answers['search'] = {'results': {'apple-curators': {
            'next': '/v1/catalog/gb/search?offset=50&term=tide&types=apple-curators',
            'data': [{'id': '900000001', 'type': 'apple-curators', 'attributes': {
                'name': 'Invented Tide Show', 'kind': 'Show', 'showHostName': 'Ada Merrow',
                'url': 'https://music.apple.com/gb/curator/x/900000001'}},
                {'id': '900000002', 'type': 'apple-curators', 'attributes': {
                    'name': 'Invented Editors', 'kind': 'Curator'}}]}}}
        answer = await self.engine.search('tide', limit=25, kind='radio-shows', offset=25)
        self.assertEqual(self.page.bridge_calls[-1],
                         ('search', 'tide', 25, 'apple-curators', 25, False))
        self.assertEqual([(shelf['key'], shelf['next']) for shelf in answer['shelves']],
                         [('radio-shows', 50)])
        show = answer['shelves'][0]['items'][0]
        self.assertEqual((show['kind'], show['curatorKind'], show['subtitle'], show['play']),
                         ('category', 'show', 'Ada Merrow', {}))
        with self.assertRaises(EngineError) as raised:
            await self.engine.search('tide', kind='podcasts')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_the_demo_searches_its_invented_catalog(self):
        demo = engine_module.Engine(demo=True)
        with self.assertRaises(EngineError) as raised:  # no catalog written: no search
            await demo.search('tide')
        self.assertEqual(raised.exception.code, 'engine-down')
        songs = [{'id': f'17240{n:05d}', 'kind': 'song', 'title': f'Tide Song {n}',
                  'subtitle': 'Invented Artist'} for n in range(30)]
        path = pathlib.Path(normalize.demo_search_path(str(self.cache)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'demo': True, 'cached': '2020-01-01T00:00:00Z',
                                    'shelves': [
            {'key': 'artists', 'items': [{'id': 'l.art1', 'kind': 'artist',
                                          'title': 'Invented Artist'}]},
            {'key': 'songs', 'items': songs}]}), encoding='utf-8')
        answer = await demo.search('TIDE  song')
        self.assertEqual([(shelf['key'], len(shelf['items']), shelf['next'])
                          for shelf in answer['shelves']],
                         [('top', 1, None), ('songs', 20, 20)])
        page = await demo.search('tide', limit=25, kind='songs', offset=20)
        self.assertEqual([(shelf['key'], len(shelf['items']), shelf['next'])
                          for shelf in page['shelves']], [('songs', 10, None)])
        self.assertEqual((await demo.search('nothing like it'))['shelves'], [])
        suggested = await demo.suggest('invented')
        self.assertEqual((suggested['terms'], [item['id'] for item in suggested['items']]),
                         ([], ['l.art1', '1724000000']))

    async def test_search_errors(self):
        await self.up()
        with self.assertRaises(EngineError) as raised:
            await self.engine.search('   ')
        self.assertEqual(raised.exception.code, 'usage')
        self.page.bridge_answers['search'] = {'errors': [{'status': '400', 'title': 'Bad'}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.search('x')
        self.assertEqual(raised.exception.code, 'api')
        self.assertIn('400 Bad', raised.exception.message)
        # An answer that is not one: nothing found.
        self.page.bridge_answers['search'] = None
        self.assertEqual(await self.engine.search('x'), {'shelves': []})

    async def test_suggest(self):
        await self.up()
        self.page.bridge_answers['suggest'] = {'results': {'suggestions': [
            {'kind': 'terms', 'searchTerm': 'glow', 'displayTerm': 'glow'},
            {'kind': 'topResults', 'content': {
                'id': '900000701', 'type': 'artists',
                'attributes': {'name': 'Glowline', 'genreNames': ['Pop']}}},
        ]}}
        answer = await self.engine.suggest('gl', limit=4)
        self.assertEqual(self.page.bridge_calls[-1], ('suggest', 'gl', 4))
        self.assertEqual(answer['terms'], [{'term': 'glow', 'display': 'glow'}])
        self.assertEqual([(item['kind'], item['title']) for item in answer['items']],
                         [('artist', 'Glowline')])

    async def test_landing_is_kept_for_a_day(self):
        await self.up()
        self.page.bridge_answers['searchLanding'] = {'data': [
            {'id': 'r1', 'type': 'personal-recommendation',
             'relationships': {'contents': {'data': [
                 curator('900000801', 'Apple Music Folk', 'Folk'),
                 curator('900000802', 'Apple Music Live')]}}}]}
        answer = await self.engine.landing()
        self.assertEqual(self.page.bridge_calls, [('searchLanding',)])
        self.assertEqual([(c['id'], c['kind'], c['title']) for c in answer['categories']],
                         [('900000801', 'category', 'Folk'),
                          ('900000802', 'category', 'Apple Music Live')])
        self.assertIn('cached', answer)
        path = self.cache / 'landing.json'
        self.assertTrue(path.is_file())
        # Kept: answered from the file, even with the engine down.
        await self.engine.stop()
        again = await self.engine.landing()
        self.assertEqual(again['categories'], answer['categories'])
        self.assertEqual(len(self.page.bridge_calls), 1)
        # A refresh, or an old stamp, asks Apple again.
        await self.up()
        await self.engine.landing(refresh=True)
        self.assertEqual(len(self.page.bridge_calls), 2)
        kept = json.loads(path.read_text())
        kept['cached'] = '2020-01-01T00:00:00Z'
        path.write_text(json.dumps(kept))
        await self.engine.landing()
        self.assertEqual(len(self.page.bridge_calls), 3)

    async def test_category_is_kept_by_id(self):
        await self.up()
        self.page.bridge_answers['category'] = {'data': [{
            'id': '900000801', 'type': 'apple-curators',
            'attributes': {'name': 'Apple Music Folk', 'shortName': 'Folk'},
            'relationships': {'grouping': {'data': [
                self.fixture('editorial_groupings.json')['data'][0]]}}}]}
        answer = await self.engine.category('900000801')
        self.assertEqual(self.page.bridge_calls, [('category', '900000801')])
        self.assertEqual(answer['title'], 'Folk')
        self.assertEqual([s['key'] for s in answer['shelves']],
                         ['cat-best-new-songs', 'cat-new-releases', 'cat-stations'])
        self.assertTrue((self.cache / 'categories' / '900000801.json').is_file())
        await self.engine.stop()
        self.assertEqual((await self.engine.category('900000801'))['title'], 'Folk')
        with self.assertRaises(EngineError) as raised:
            await self.engine.category('900000802')  # not kept: needs the engine
        self.assertEqual(raised.exception.code, 'engine-down')
        with self.assertRaises(EngineError) as raised:
            await self.engine.category('')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_browse_is_the_editorial_groupings_kept_for_a_day(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/editorial/gb/groupings'
        self.page.api_answers[path] = self.fixture('editorial_groupings.json')
        answer = await self.engine.browse()
        self.assertEqual(self.page.api_calls, [path])
        self.assertEqual(self.page.api_params[-1],
                         {'name': 'music', 'platform': 'web', 'extend': 'editorialArtwork'})
        self.assertEqual([s['title'] for s in answer['shelves']],
                         ['', 'Best New Songs', 'New Releases', 'Stations'])
        self.assertTrue(answer['shelves'][0]['featured'])
        self.assertEqual([row['title'] for row in answer['links']], ['More', ''])
        self.assertTrue((self.cache / 'browse.json').is_file())
        await self.engine.stop()
        self.assertEqual(len((await self.engine.browse())['shelves']), 4)
        await self.up()
        await self.engine.browse(refresh=True)
        self.assertEqual(self.page.api_calls, [path, path])

    async def test_an_answer_kept_in_an_older_shape_is_asked_again(self):
        # New kept that morning by a version whose New had no banners or links: fresh by its
        # age, but not in the shape this version answers, so Apple is asked again.
        self.page.storefront = 'gb'
        path = '/v1/editorial/gb/groupings'
        self.page.api_answers[path] = self.fixture('editorial_groupings.json')
        self.cache.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        older = {'shelves': [{'key': 'old', 'title': 'Invented Old Shelf', 'items': []}],
                 'cached': stamp}
        (self.cache / 'browse.json').write_text(json.dumps(older), encoding='utf-8')
        await self.engine.stop()  # Apple cannot be asked: the older one, stale
        answer = await self.engine.browse()
        self.assertEqual((answer['shelves'][0]['key'], answer.get('stale')), ('old', True))
        await self.up()
        answer = await self.engine.browse()
        self.assertEqual(self.page.api_calls, [path])
        self.assertTrue(answer['shelves'][0]['featured'])
        self.assertEqual(answer['shape'], normalize.ANSWER_SHAPE)
        kept = json.loads((self.cache / 'browse.json').read_text(encoding='utf-8'))
        self.assertEqual(kept['shape'], normalize.ANSWER_SHAPE)
        await self.engine.browse()
        self.assertEqual(self.page.api_calls, [path])  # this shape's: kept a day

    async def test_more_to_explores_pages_are_asked_by_id_and_kept_a_day(self):
        # #370: a room, a grouping (New's shape: `platform` or a 400) and a multiroom.
        self.page.storefront = 'gb'
        await self.up()
        grouping = self.fixture('editorial_groupings.json')
        room = {'data': [{'id': '900000701', 'type': 'rooms', 'attributes': {
            'title': 'Invented Room'}, 'relationships': {'contents': {
                'data': grouping['data'][0]['relationships']['tabs']['data'][0][
                    'relationships']['children']['data'][2]['relationships']['contents'][
                    'data']}}}]}
        multiroom = {'data': [{'id': '900000705', 'type': 'multirooms', 'attributes': {
            'title': 'Invented Multiroom'}, 'relationships': {'children': {'data': []}}}]}
        self.page.api_answers['/v1/editorial/gb/rooms/900000701'] = room
        self.page.api_answers['/v1/editorial/gb/groupings/900000704'] = grouping
        self.page.api_answers['/v1/editorial/gb/multirooms/900000705'] = multiroom
        answer = await self.engine.room('900000701')
        self.assertEqual((answer['title'], [item['id'] for item in answer['items']]),
                         ('Invented Room', ['900000201', '900000202']))
        answer = await self.engine.grouping('900000704')
        self.assertEqual(answer['shelves'][0]['form'], 'banners')
        self.assertEqual([row['key'] for row in answer['links']], ['grp-links', 'grp-genres'])
        answer = await self.engine.multiroom('900000705')
        self.assertEqual(answer['title'], 'Invented Multiroom')
        self.assertEqual(self.page.api_calls, ['/v1/editorial/gb/rooms/900000701',
                                               '/v1/editorial/gb/groupings/900000704',
                                               '/v1/editorial/gb/multirooms/900000705'])
        self.assertEqual(self.page.api_params, [
            {}, {'platform': 'web', 'extend': 'editorialArtwork'},
            {'extend': 'editorialArtwork,uber,lockupStyle'}])
        for folder, name in (('rooms', '900000701'), ('groupings', '900000704'),
                             ('multirooms', '900000705')):
            self.assertTrue((self.cache / folder / f'{name}.json').is_file())
        await self.engine.stop()
        self.assertEqual((await self.engine.room('900000701'))['title'], 'Invented Room')
        with self.assertRaises(EngineError) as raised:
            await self.engine.room('900000702')  # not kept: needs the engine
        self.assertEqual(raised.exception.code, 'engine-down')
        for bad in ('', '../x', 'a/b', None):
            with self.assertRaises(EngineError) as raised:
                await self.engine.grouping(bad)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_browse_failure_is_api(self):
        await self.up()
        with mock.patch.object(reads_module, 'API_RETRIES', 1):
            with self.assertRaises(EngineError) as raised:
                await self.engine.browse()
        self.assertEqual(raised.exception.code, 'api')
        self.assertFalse((self.cache / 'browse.json').exists())

    async def test_the_charts_are_asked_with_their_playlists_and_kept_a_day(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/catalog/gb/charts'
        self.page.api_answers[path] = self.fixture('charts.json')
        answer = await self.engine.charts()
        self.assertEqual(self.page.api_params, [{
            'types': 'songs,albums,playlists,music-videos', 'limit': api.CHARTS_LIMIT,
            'with': 'dailyGlobalTopCharts,cityCharts'}])
        self.assertEqual([shelf['key'] for shelf in answer['shelves']][:3],
                         ['charts-songs', 'charts-albums', 'charts-playlists'])
        await self.engine.charts()
        self.assertEqual(self.page.api_calls, [path])  # kept
        self.assertTrue((self.cache / 'charts.json').exists())

    async def test_an_answer_that_cannot_be_shaped_is_an_engine_error_kept_nowhere(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/catalog/gb/charts'
        confused = self.fixture('charts.json')
        confused['results']['albums'][0]['data'][0]['attributes'] = ['junk']
        self.page.api_answers[path] = confused
        with self.assertLogs('applemusic.engine', 'WARNING'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.charts()
        self.assertEqual(raised.exception.code, 'api')
        self.assertFalse((self.cache / 'charts.json').exists())
        # An older answer kept there is the answer then, as no longer fresh.
        normalize.write_answer(str(self.cache / 'charts.json'), {'shelves': []},
                               str(self.cache))
        self.expire(self.cache / 'charts.json')
        with self.assertLogs('applemusic.engine', 'WARNING'):
            answer = await self.engine.charts()
        self.assertIs(answer.get('stale'), True)

    async def test_a_genres_charts_are_asked_for_it_and_kept_apart(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/catalog/gb/charts'
        self.page.api_answers[path] = self.fixture('charts.json')
        await self.engine.charts(genre='21')
        await self.engine.charts(genre='21')
        self.assertEqual(self.page.api_calls, [path])  # kept
        # Its rankings alone: the Daily Top 100 and City Charts are no genre's.
        self.assertEqual(self.page.api_params, [{
            'types': 'songs,albums,playlists,music-videos', 'limit': api.CHARTS_LIMIT,
            'genre': '21'}])
        self.assertTrue((self.cache / 'charts' / '21.json').exists())
        self.assertFalse((self.cache / 'charts.json').exists())  # every genre's is apart
        await self.engine.charts()
        self.assertEqual(self.page.api_calls, [path, path])
        # Music, every genre's, is the charts of every genre, kept as they are.
        await self.engine.charts(genre=api.ROOT_GENRE)
        self.assertEqual(self.page.api_calls, [path, path])  # charts.json's, kept
        self.assertFalse((self.cache / 'charts' / f'{api.ROOT_GENRE}.json').exists())
        for bad in ('../x', 'abc', '2 1'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.charts(genre=bad)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_the_genres_are_the_catalogs_kept_a_day(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/catalog/gb/genres'
        self.page.api_answers[path] = {'data': [
            {'id': '9000', 'type': 'genres', 'attributes': {'name': 'Invented Music'}},
            {'id': '9001', 'type': 'genres', 'attributes': {
                'name': 'Invented Folk', 'parentId': '9000', 'parentName': 'Invented Music'}}]}
        answer = await self.engine.genres()
        self.assertEqual(answer['genres'], [{'id': '9001', 'title': 'Invented Folk'}])
        self.assertEqual(self.page.api_params, [{}])
        await self.engine.stop()
        self.assertEqual((await self.engine.genres())['genres'][0]['id'], '9001')  # kept
        self.assertEqual(self.page.api_calls, [path])
        self.assertTrue((self.cache / 'genres.json').exists())

    async def test_charts_refused_with_their_playlists_are_asked_without(self):
        await self.up()
        path = '/v1/catalog/us/charts'
        refused = {'errors': [{'status': '400', 'title': 'Bad Request'}]}
        answers = iter([refused, self.fixture('charts.json')])
        page = self.page

        def charts(message):
            expression = message['params']['expression']
            if expression.startswith(f'window.__appleMusicLibrary.api("{path}"'):
                page.api_calls.append(path)
                return value(next(answers))
            return page(message)

        self.chrome.responders['Runtime.evaluate'] = charts
        answer = await self.engine.charts()
        self.assertEqual(self.page.api_calls, [path, path])
        self.assertEqual(answer['shelves'][0]['key'], 'charts-songs')
        # Any other failure is the command's.
        answers = iter([{'errors': [{'status': '403', 'title': 'Forbidden'}]}])
        with self.assertRaises(EngineError) as raised:
            await self.engine.charts(refresh=True)
        self.assertEqual(raised.exception.status, 403)

    async def test_radio_is_kept_until_its_live_programmes_run_out(self):
        self.page.storefront = 'gb'
        await self.up()
        path = '/v1/editorial/gb/groupings'
        self.page.api_answers[path] = self.fixture('editorial_radio.json')
        answer = await self.engine.radio()
        self.assertEqual(self.page.api_params[-1], {
            'name': 'radio', 'platform': 'web', 'tabs': 'subscriber',
            'extend': 'editorialArtwork', 'include[stations]': 'events,radio-show'})
        self.assertEqual([s['key'] for s in answer['shelves']][:2], ['radio-live', 'radio-hero'])
        self.assertTrue(answer['shelves'][0]['live'])
        self.assertIn('expires', answer)  # a few minutes on: the fixture's programmes are over
        await self.engine.radio()
        self.assertEqual(self.page.api_calls, [path])  # kept
        kept_path = self.cache / 'radio.json'
        kept = json.loads(kept_path.read_text())
        kept['expires'] = '2020-01-01T00:00:00Z'  # young, but its programmes have ended
        kept_path.write_text(json.dumps(kept))
        await self.engine.radio()
        self.assertEqual(self.page.api_calls, [path, path])  # asked again
        kept = json.loads(kept_path.read_text())
        kept['expires'] = '2020-01-01T00:00:00Z'
        kept_path.write_text(json.dumps(kept))
        await self.engine.stop()
        answer = await self.engine.radio()  # Apple cannot be asked: the old one, stale
        self.assertTrue(answer['stale'])
        self.assertEqual(answer['shelves'][0]['key'], 'radio-live')

    def expire(self, path):
        kept = json.loads(path.read_text())
        kept['cached'] = '2020-01-01T00:00:00Z'
        path.write_text(json.dumps(kept))

    async def test_an_old_answer_is_answered_when_apple_cannot_be_asked(self):
        commands = {
            'landing': (self.engine.landing, self.cache / 'landing.json'),
            'category': (lambda **kw: self.engine.category('900000801', **kw),
                         self.cache / 'categories' / '900000801.json'),
            'browse': (self.engine.browse, self.cache / 'browse.json'),
            'made_for_you': (self.engine.made_for_you, self.cache / 'made-for-you.json'),
            'radio': (self.engine.radio, self.cache / 'radio.json'),
            'charts': (self.engine.charts, self.cache / 'charts.json'),
            'genre_charts': (lambda **kw: self.engine.charts(genre='21', **kw),
                             self.cache / 'charts' / '21.json'),
            'genres': (self.engine.genres, self.cache / 'genres.json'),
            'recently_played': (self.engine.recently_played, self.cache / 'recent-played.json'),
        }
        for name, (_command, path) in commands.items():
            normalize.write_answer(str(path), {'shelves': [], 'name': name}, str(self.cache))
            self.expire(path)
        # Down: each answers its old answer, marked stale, stamped when it was fetched.
        for name, (command, _path) in commands.items():
            answer = await command()
            self.assertEqual((answer['name'], answer['stale'], answer['cached']),
                             (name, True, '2020-01-01T00:00:00Z'), name)
            # A refresh wants Apple's answer, and says why there is none.
            with self.assertRaises(EngineError) as raised:
                await command(refresh=True)
            self.assertEqual(raised.exception.code, 'engine-down')
        # Signed out: the same.
        await self.up(authorized=False)
        for name, (command, _path) in commands.items():
            self.assertTrue((await command())['stale'], name)
        await self.engine.stop()
        # Up and signed in, but Apple fails (offline, say): the same.
        await self.up()
        self.page.bridge_answers['searchLanding'] = {'errors': [{'status': '503'}]}
        self.page.bridge_answers['category'] = {'errors': [{'status': '503'}]}
        for name, (command, _path) in commands.items():
            self.assertTrue((await command())['stale'], name)
        self.assertEqual(len(self.page.bridge_calls), 2)
        # With nothing kept, the error.
        for _name, (_command, path) in commands.items():
            path.unlink()
        await self.engine.stop()
        for name, (command, _path) in commands.items():
            with self.assertRaises(EngineError) as raised:
                await command()
            self.assertEqual(raised.exception.code, 'engine-down', name)

    async def test_an_answer_past_its_day_outlives_the_startup_prune(self):
        # The prune at every startup and sync leaves an answer a day or two old, so a launch
        # with the engine down still has it to answer, stale; one past the keep age goes.
        two_days = time.time() - 2 * 24 * 3600
        path = self.cache / 'radio.json'
        normalize.write_answer(str(path), {'shelves': [], 'name': 'radio'}, str(self.cache))
        self.expire(path)
        os.utime(path, (two_days, two_days))
        old = self.cache / 'charts.json'
        normalize.write_answer(str(old), {'shelves': []}, str(self.cache))
        long_ago = time.time() - normalize.ANSWER_KEEP_AGE - 60
        os.utime(old, (long_ago, long_ago))
        gone = normalize.prune_caches(str(self.cache))
        self.assertEqual(gone['answers'], 1)
        self.assertFalse(old.exists())
        answer = await self.engine.radio()
        self.assertEqual((answer['name'], answer['stale']), ('radio', True))

    async def test_an_old_answer_is_asked_again_when_apple_can_be(self):
        await self.up()
        self.page.bridge_answers['searchLanding'] = {'data': []}
        path = self.cache / 'landing.json'
        normalize.write_answer(str(path), {'categories': [{'id': 'old'}]}, str(self.cache))
        self.expire(path)
        answer = await self.engine.landing()
        self.assertEqual(self.page.bridge_calls, [('searchLanding',)])
        self.assertEqual(answer['categories'], [])
        self.assertNotIn('stale', answer)
        self.assertNotEqual(answer['cached'], '2020-01-01T00:00:00Z')

    async def test_recently_played_is_read_a_page_at_a_time_and_kept(self):
        await self.up()
        path = '/v1/me/recent/played'

        def played(number, kind='albums'):
            return {'id': f'9000003{number:02d}', 'type': kind,
                    'attributes': {'name': f'Invented Played {number}',
                                   'artistName': 'Invented Artist',
                                   'playParams': {'id': f'9000003{number:02d}',
                                                  'kind': kind[:-1]}}}

        first = [played(n) for n in range(9)] + [played(9, 'stations')]
        self.page.api_answers[(path, 0)] = {'data': first, 'next': f'{path}?offset=10'}
        self.page.api_answers[(path, 10)] = {'data': [played(10), played(0)]}  # once each
        answer = await self.engine.recently_played()
        self.assertEqual(self.page.api_calls, [path, path])
        self.assertEqual(self.page.api_params, [{'limit': 10, 'offset': 0},
                                                {'limit': 10, 'offset': 10}])
        self.assertEqual(set(answer), {'items', 'cached', 'shape'})
        self.assertEqual([item['title'] for item in answer['items']],
                         [f'Invented Played {n}' for n in range(11)])
        self.assertEqual(answer['items'][9]['kind'], 'station')
        self.assertEqual(answer['items'][0]['groups'], [])
        self.assertTrue((self.cache / 'recent-played.json').is_file())
        # Kept: answered without the engine, but a refresh needs it.
        await self.engine.stop()
        self.assertEqual(len((await self.engine.recently_played())['items']), 11)
        with self.assertRaises(EngineError) as raised:
            await self.engine.recently_played(refresh=True)
        self.assertEqual(raised.exception.code, 'engine-down')

    async def test_recently_played_keeps_the_pages_read_when_a_later_one_fails(self):
        await self.up()
        path = '/v1/me/recent/played'
        self.page.api_answers[(path, 0)] = {
            'data': [{'id': f'9000004{n:02d}', 'type': 'playlists',
                      'attributes': {'name': f'Invented Mix {n}'}} for n in range(10)],
            'next': f'{path}?offset=10'}
        # The next page is Apple's 404 (the fake page's answer for what it has not got):
        # the first page's answered, but not kept.
        answer = await self.engine.recently_played(refresh=True)
        self.assertEqual(len(answer['items']), 10)
        self.assertIn('cached', answer)
        self.assertFalse((self.cache / 'recent-played.json').exists())
        # The first page failing fails the ask.
        del self.page.api_answers[(path, 0)]
        with self.assertRaises(EngineError) as raised:
            await self.engine.recently_played(refresh=True)
        self.assertEqual(raised.exception.status, 404)

    async def test_made_for_you_keeps_the_mixes_and_stations(self):
        await self.up()
        mixes = [{'id': f'pl.pm-{n}', 'type': 'playlists', 'attributes': {
            'name': f'Mix {n}', 'playlistType': 'personal-mix',
            'artwork': {'url': 'https://x/mix/{w}x{h}{c}.{f}', 'bgColor': '223344'},
            'playParams': {'id': f'pl.pm-{n}', 'kind': 'playlist'}}} for n in (1, 2)]
        albums = [{'id': '900000201', 'type': 'albums',
                   'attributes': {'name': 'Lantern Season', 'artistName': 'P', 'trackCount': 3}}]
        self.page.api_answers['/v1/me/recommendations'] = {'data': [
            {'id': 'r-mixes', 'type': 'personal-recommendation',
             'attributes': {'title': {'stringForDisplay': 'Made for You'}},
             'relationships': {'contents': {'data': mixes}}},
            {'id': 'r-albums', 'type': 'personal-recommendation',
             'attributes': {'title': {'stringForDisplay': 'New Releases for You'}},
             'relationships': {'contents': {'data': albums}}},
        ]}
        answer = await self.engine.made_for_you()
        self.assertEqual(self.page.api_calls, ['/v1/me/recommendations'])
        self.assertEqual(self.page.api_params[-1], {'limit': 25})
        self.assertEqual([(s['key'], s['title'], len(s['items'])) for s in answer['shelves']],
                         [('rec-r-mixes', 'Made for You', 2)])
        self.assertTrue((self.cache / 'made-for-you.json').is_file())
        await self.engine.stop()
        self.assertEqual(len((await self.engine.made_for_you())['shelves']), 1)

    REPLAY_SONGS = '/v1/catalog/us/songs'

    @staticmethod
    def replay_summary(year):
        """An invented summary of `year`, in the shape Apple answers it: each view's items
        period summaries, a top song its id alone, an album the whole resource."""
        def songs(*ids):
            return [{'id': f'inv-song-summary-{song_id}', 'type': 'song-period-summaries',
                     'attributes': {'playCount': 5, 'year': str(year)},
                     'relationships': {'song': {'data': [
                         {'id': song_id, 'type': 'songs',
                          'href': f'/v1/catalog/us/songs/{song_id}'}]}}} for song_id in ids]
        album = {'id': 'inv-album-summary', 'type': 'album-period-summaries',
                 'attributes': {'playCount': 9, 'listenTimeInMinutes': 30, 'year': str(year)},
                 'relationships': {'album': {'data': [{
                     'id': '900000401', 'type': 'albums',
                     'attributes': {'name': 'Invented Album', 'artistName': 'Invented'}}]}}}
        return {'data': [{
            'id': f'year-{year}', 'type': 'music-summaries',
            'attributes': {'year': year, 'period': 'year', 'name': 'Invented'},
            'views': {'top-songs': {'data': songs('900000302', '900000301')},
                      'top-albums': {'data': [album]}}}]}

    def replay_answers(self):
        """An invented summary of 2026 and of 2025, the catalog's songs they name and a
        listing of three years, each with its Replay playlist."""
        self.page.api_answers[api.REPLAY_ENDPOINT] = self.replay_summary(2026)
        self.page.api_answers['/v1/me/music-summaries/year-2025'] = self.replay_summary(2025)
        self.page.api_answers[self.REPLAY_SONGS] = {'data': [
            {'id': song_id, 'type': 'songs', 'attributes': {
                'name': f'Invented Song {song_id}', 'artistName': 'Invented Artist',
                'albumName': 'Invented Album'}} for song_id in ('900000301', '900000302')]}
        self.page.api_answers[api.REPLAY_YEARS_ENDPOINT] = {'data': [
            {'id': f'year-{year}', 'type': 'music-summaries',
             'attributes': {'period': 'year', 'year': year},
             'relationships': {'playlist': {'data': [{
                 'id': f'pl.inv{year}', 'type': 'playlists',
                 'attributes': {'name': f'Invented Replay {year}'}}]}}}
            for year in (2026, 2025, 2024)]}

    async def test_replay_is_the_summary_its_songs_and_the_years_kept_a_day(self):
        await self.up()
        self.replay_answers()
        answer = await self.engine.replay()
        self.assertEqual(self.page.api_calls,
                         [api.REPLAY_ENDPOINT, self.REPLAY_SONGS, api.REPLAY_YEARS_ENDPOINT])
        self.assertEqual(self.page.api_params, [
            {'filter[year]': 'latest', 'views': 'top-songs,top-artists,top-albums'},
            {'ids': '900000302,900000301'},
            {'period': 'year', 'fields[music-summaries]': 'period,year',
             'include[music-summaries]': 'playlist'}])
        self.assertEqual((answer['year'], answer['years']), ('2026', ['2026', '2025', '2024']))
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['replay-songs', 'replay-albums', 'replay-playlists'])
        self.assertEqual([item['title'] for item in answer['shelves'][0]['items']],
                         ['Invented Song 900000302', 'Invented Song 900000301'])  # its rank
        self.assertEqual(answer['basis'], normalize.REPLAY_SHAPE)
        self.assertTrue((self.cache / 'replay.json').is_file())
        await self.engine.stop()
        self.assertEqual((await self.engine.replay())['year'], '2026')  # kept
        self.assertEqual(len(self.page.api_calls), 3)

    async def test_a_replay_without_its_years_is_shown_not_kept(self):
        await self.up()
        self.replay_answers()
        years = self.page.api_answers.pop(api.REPLAY_YEARS_ENDPOINT)  # a 404, once
        answer = await self.engine.replay()
        self.assertEqual((answer['year'], answer['years']), ('2026', []))
        self.assertEqual(answer['shelves'][0]['key'], 'replay-songs')
        self.assertIn('cached', answer)
        self.assertFalse((self.cache / 'replay.json').exists())
        self.page.api_answers[api.REPLAY_YEARS_ENDPOINT] = years
        answer = await self.engine.replay()  # asked again
        self.assertEqual(self.page.api_calls, [api.REPLAY_ENDPOINT, self.REPLAY_SONGS,
                                               api.REPLAY_YEARS_ENDPOINT] * 2)
        self.assertEqual(answer['years'], ['2026', '2025', '2024'])
        self.assertTrue((self.cache / 'replay.json').is_file())

    async def test_a_replay_kept_in_an_older_shape_is_asked_again(self):
        await self.up()
        self.replay_answers()
        path = normalize.replay_cache_path(str(self.cache))
        normalize.write_answer(path, {'year': '2026', 'years': ['2026'], 'shelves': []},
                               str(self.cache))
        answer = await self.engine.replay()
        self.assertEqual(self.page.api_calls[0], api.REPLAY_ENDPOINT)
        self.assertEqual(answer['shelves'][0]['key'], 'replay-songs')
        # Apple out of reach, the older one is still the answer, as no longer fresh.
        normalize.write_answer(path, {'year': '2026', 'years': ['2026'], 'shelves': []},
                               str(self.cache))
        await self.engine.stop()
        answer = await self.engine.replay()
        self.assertIs(answer.get('stale'), True)

    async def test_a_past_years_replay_is_asked_by_its_resource_and_kept_apart(self):
        await self.up()
        self.replay_answers()
        answer = await self.engine.replay(year='2025')
        self.assertEqual(self.page.api_calls[0], '/v1/me/music-summaries/year-2025')
        self.assertEqual(self.page.api_params[0],
                         {'views': 'top-songs,top-artists,top-albums'})
        self.assertEqual(answer['year'], '2025')
        self.assertEqual(len(answer['shelves'][0]['items']), 2)
        self.assertTrue((self.cache / 'replay' / '2025.json').is_file())
        self.assertFalse((self.cache / 'replay.json').exists())
        for bad in ('../x', '25', 'latest'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.replay(year=bad)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_no_summary_is_an_empty_replay_and_no_years_are_none(self):
        await self.up()
        # The fake page answers a 404 for both: no listening history, no listing.
        answer = await self.engine.replay()
        self.assertEqual(answer['shelves'], [])
        self.assertEqual((answer['year'], answer['years']), ('', []))
        self.assertNotIn(self.REPLAY_SONGS, self.page.api_calls)  # no songs to ask for
        # A past year Apple has no summary of: its playlist alone.
        self.replay_answers()
        self.page.api_answers['/v1/me/music-summaries/year-2024'] = {
            'errors': [{'status': '404', 'title': 'Not Found'}]}
        answer = await self.engine.replay(year='2024')
        self.assertEqual(answer['year'], '2024')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']], ['replay-playlists'])
        # Any other failure of the summary is the command's.
        self.page.api_answers[api.REPLAY_ENDPOINT] = {
            'errors': [{'status': '403', 'title': 'Forbidden'}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.replay(refresh=True)
        self.assertEqual(raised.exception.status, 403)

    async def test_replays_songs_the_catalog_lacks_are_left_out(self):
        await self.up()
        self.replay_answers()
        # A 404: none of them in the catalog; the albums still show.
        self.page.api_answers[self.REPLAY_SONGS] = {
            'errors': [{'status': '404', 'title': 'Not Found'}]}
        answer = await self.engine.replay(refresh=True)
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['replay-albums', 'replay-playlists'])
        # Another failure of the songs read is the command's.
        self.page.api_answers[self.REPLAY_SONGS] = {
            'errors': [{'status': '403', 'title': 'Forbidden'}]}
        with self.assertRaises(EngineError) as raised:
            await self.engine.replay(refresh=True)
        self.assertEqual(raised.exception.status, 403)


class KeptAfterWipeTest(unittest.TestCase):
    """The engine's writers keep nothing for a cache cleared since their command began."""

    def test_kept_answers_and_lyrics(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = pathlib.Path(tmp.name)
        generation = store.cache_generation()
        store.bump_cache_generation()
        answer = reads_module._shape_and_keep(lambda raw, cache_dir: {'shelves': []}, {},
                                               str(cache / 'browse.json'), str(cache),
                                               generation)
        self.assertEqual(answer['shelves'], [])
        normalize.write_answer(str(cache / 'lyrics' / '1.json'), {'lines': []}, str(cache),
                               generation)
        self.assertEqual(list(cache.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
