# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The backend's shaping of the New page and the Radio page (editorial groupings), Made for
You (recommendations) and the Charts page (the catalog's charts) into shelves, and Home's
Recently Played, over invented answers."""

import json
import os
import pathlib
import tempfile
import unittest
from datetime import UTC, datetime

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import api, normalize

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'


def mix(playlist_id, name, playlist_type='personal-mix'):
    return {'id': playlist_id, 'type': 'playlists', 'attributes': {
        'name': name, 'curatorName': 'Apple Music for You', 'playlistType': playlist_type,
        'artwork': {'url': 'https://x/mix/{w}x{h}{c}.{f}', 'bgColor': '223344'},
        'playParams': {'id': playlist_id, 'kind': 'playlist'}}}


def station(station_id, name):
    return {'id': station_id, 'type': 'stations', 'attributes': {
        'name': name, 'isLive': False,
        'artwork': {'url': 'https://x/station/{w}x{h}{c}.{f}', 'bgColor': '445566'},
        'playParams': {'id': station_id, 'kind': 'radioStation'}}}


def album(album_id, name):
    return {'id': album_id, 'type': 'albums', 'attributes': {
        'name': name, 'artistName': 'Paper Parachutes', 'trackCount': 10}}


def recommendation(rec_id, title, contents, members=None):
    rec = {'id': rec_id, 'type': 'personal-recommendation',
           'attributes': {'title': {'stringForDisplay': title}, 'kind': 'music-recommendations',
                          'isGroupRecommendation': bool(members)},
           'relationships': {'contents': {'data': contents}}}
    if members:
        rec['relationships']['recommendations'] = {'data': members}
    return rec


class EditorialShelvesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(FIXTURES / 'editorial_groupings.json', encoding='utf-8') as file:
            self.raw = json.load(file)

    def test_the_groupings_elements_become_shelves_in_order(self):
        out = normalize.editorial_shelves(self.raw, self.tmp.name)
        shelves = out['shelves']
        self.assertEqual([(s['key'], s['title'], len(s['items'])) for s in shelves], [
            ('new-banners', '', 2),      # the banners' items, the uploaded video left out
            ('new-best-new-songs', 'Best New Songs', 2),
            ('new-new-releases', 'New Releases', 2),  # the nameless album left out
            ('new-stations', 'Stations', 1),
        ])  # the rooms (links only) and the link row are not shelves
        # The banners are the one featured shelf, untitled: the New page has the word.
        self.assertEqual([s.get('featured', False) for s in shelves], [True, False, False, False])

    def test_featured_holds_the_banners_items_as_their_kinds(self):
        featured = normalize.editorial_shelves(self.raw, self.tmp.name)['shelves'][0]
        kinds = [(item['kind'], item['id'], item['title']) for item in featured['items']]
        self.assertEqual(kinds, [('album', '900000201', 'Lantern Season'),
                                 ('category', '900000301', 'Folk')])
        category = featured['items'][1]
        self.assertEqual(category['subtitle'], 'Apple Music Folk')
        self.assertEqual(category['artColor'], '#6b4f2a')
        self.assertIn('320x320', category['art'])

    def test_items_are_shaped_as_search_hits(self):
        shelves = normalize.editorial_shelves(self.raw, self.tmp.name)['shelves']
        song = shelves[1]['items'][0]
        self.assertEqual(song['kind'], 'song')
        self.assertEqual(song['play'], {'kind': 'song', 'id': '900000501'})
        self.assertEqual(song['groups'], [])
        self.assertIn('320x320', song['art'])  # the thumbnail-sized URL: nothing on disk
        self.assertIsNone(song['thumb'])
        self.assertTrue(shelves[1]['items'][1]['explicit'])
        album = shelves[2]['items'][0]
        self.assertEqual((album['kind'], album['subtitle'], album['artColor']),
                         ('album', 'Paper Parachutes', '#2a3b4c'))
        self.assertIsNone(shelves[2]['items'][1]['art'])  # no artwork at all
        self.assertEqual(shelves[3]['items'][0]['play'], {'kind': 'station', 'id': 'ra.900000601'})

    def test_nothing(self):
        nothing = {'shelves': [], 'links': []}
        self.assertEqual(normalize.editorial_shelves(None, self.tmp.name), nothing)
        self.assertEqual(normalize.editorial_shelves({'data': ['junk', {}]}, self.tmp.name),
                         nothing)
        answer = {'errors': [{'status': '500'}]}
        self.assertEqual(normalize.editorial_shelves(answer, self.tmp.name), nothing)

    def test_the_banners_carry_apples_label_line_and_wide_artwork(self):
        # #370: a 317's label over its content's editorial artwork, a 320's own; the
        # shelf is shown as banners since one has a banner.
        featured = normalize.editorial_shelves(self.raw, self.tmp.name)['shelves'][0]
        self.assertEqual(featured['form'], 'banners')
        album_item, curator = featured['items']
        self.assertEqual((album_item['badge'], album_item['tagline']),
                         ('NEW ALBUM', 'An invented tagline'))  # the tagline before short
        self.assertEqual(album_item['banner'], {
            'url': 'https://x/lantern-hero/{w}x{h}sr.jpg', 'crop': 'sr', 'width': 3840,
            'height': 2160, 'color': '#1a2b3c'})
        self.assertEqual((curator['badge'], curator['tagline']),
                         ('FEATURED CURATOR', 'Invented short notes'))  # the child's notes
        self.assertEqual(curator['banner']['url'], 'https://x/folk-wide/{w}x{h}sr.jpg')
        self.assertEqual((curator['banner']['width'], curator['banner']['height']),
                         (4320, 1080))
        # The other shelves' items have none of it, the same album among them.
        for shelf in normalize.editorial_shelves(self.raw, self.tmp.name)['shelves'][1:]:
            for item in shelf['items']:
                self.assertFalse({'badge', 'banner', 'tagline'} & set(item))
            self.assertNotIn('form', shelf)

    def test_banners_without_artwork_are_a_plain_featured_shelf(self):
        banners = self.raw['data'][0]['relationships']['tabs']['data'][0]['relationships'][
            'children']['data'][0]['relationships']['children']['data']
        for banner in banners:
            banner['attributes'].pop('editorialArtwork', None)
            for content in banner['relationships']['contents']['data']:
                content['attributes'].pop('editorialArtwork', None)
        featured = normalize.editorial_shelves(self.raw, self.tmp.name)['shelves'][0]
        self.assertNotIn('form', featured)
        self.assertEqual(featured['items'][0]['badge'], 'NEW ALBUM')
        self.assertNotIn('banner', featured['items'][0])
        # A category's page (no banners asked for) keeps none of it either.
        radio = normalize.radio_shelves(self.raw, self.tmp.name)['shelves'][0]
        self.assertNotIn('badge', radio['items'][0])

    def test_more_to_explore_and_the_genres_are_links(self):
        links = normalize.editorial_shelves(self.raw, self.tmp.name)['links']
        self.assertEqual([(row['key'], row['title']) for row in links],
                         [('new-links', 'More'), ('new-genres', '')])
        self.assertEqual([(link['kind'], link['id'], link['title'], link.get('genre'))
                          for link in links[0]['links']], [
            ('charts', 'charts', 'Charts', None),
            ('room', '900000701', 'Invented Room', None),  # once, though twice in the row
            ('room', '900000703', 'Invented Collection', None),
            ('grouping', '900000704', 'Invented Grouping', None),
            ('multiroom', '900000705', 'Invented Multiroom', None),
            ('charts', 'charts', 'Invented Genre Charts', '21'),
            ('link', 'https://example.com/invented-concerts', 'Invented Concerts', None),
        ])  # no label, no id, not https: left out
        self.assertEqual(links[0]['links'][-1]['url'], 'https://example.com/invented-concerts')
        self.assertEqual(links[1]['links'], [{'title': 'Invented Folk', 'kind': 'grouping',
                                              'id': '900000706', 'url': None}])

    def test_editorial_links(self):
        store = 'https://itunes.apple.com/WebObjects/MZStore.woa/wa/'

        def link(url, **more):
            return normalize.editorial_link(dict(label='  Invented   Label ', url=url, **more))
        self.assertEqual(link(store + 'viewRoom?fcId=1'),
                         {'title': 'Invented Label', 'kind': 'room', 'id': '1', 'url': None})
        self.assertEqual(link('https://music.apple.com/gb/room/6789')['id'], '6789')
        self.assertEqual(link(store + 'viewMultiRoom?FCID=2')['kind'], 'multiroom')
        self.assertEqual(link(store + 'viewTop?cc=gb')['kind'], 'charts')  # no genre
        self.assertNotIn('genre', link(store + 'viewTop?cc=gb'))
        self.assertEqual(link(store + 'viewTop?genreId=21&cc=gb')['genre'], '21')
        self.assertNotIn('genre', link(store + 'viewTop?genreId=abc'))  # not a genre's id
        # Music, the genre every other belongs to, is every genre's charts: All Genres.
        self.assertEqual(link(store + f'viewTop?genreId={api.ROOT_GENRE}'),
                         {'title': 'Invented Label', 'kind': 'charts', 'id': 'charts',
                          'url': None})
        # An in-app route marked external opens in the browser, as Apple's page would.
        self.assertEqual(link(store + 'viewRoom?fcId=1', target='external')['kind'], 'link')
        # An id that is not one (it goes into a path), a route without its id: none.
        self.assertIsNone(link(store + 'viewGrouping?id=../x'))
        self.assertIsNone(link(store + 'viewGrouping'))
        for bad in ('ftp://example.com/x', 'http://example.com/x', 'javascript:alert(1)', ''):
            self.assertIsNone(link(bad))
        self.assertIsNone(normalize.editorial_link({'url': store + 'viewRoom?fcId=1'}))
        self.assertIsNone(normalize.editorial_link('junk'))
        self.assertEqual(link('https://example.com/elsewhere')['kind'], 'link')

    def test_a_room(self):
        raw = {'data': [{'id': '900000701', 'type': 'rooms', 'attributes': {
            'title': 'Invented Room', 'sorts': []}, 'relationships': {'contents': {'data': [
                album('900000201', 'Lantern Season'), station('ra.q-1', 'Quiet Radio'),
                album('900000201', 'Lantern Season'), {'id': 'x', 'type': 'uploaded-videos',
                                                       'attributes': {'name': 'Upload'}},
                'junk']}}}]}
        out = normalize.editorial_room(raw, self.tmp.name)
        self.assertEqual((out['id'], out['title']), ('900000701', 'Invented Room'))
        self.assertEqual([(item['kind'], item['id']) for item in out['items']],
                         [('album', '900000201'), ('station', 'ra.q-1')])
        self.assertEqual(normalize.editorial_room(None, self.tmp.name),
                         {'id': '', 'title': '', 'items': []})

    def test_a_grouping_is_shaped_as_new(self):
        raw = {'data': [dict(self.raw['data'][0], id='900000704',
                             attributes={'name': 'Invented Grouping'})]}
        out = normalize.editorial_grouping(raw, self.tmp.name)
        self.assertEqual((out['id'], out['title']), ('900000704', 'Invented Grouping'))
        self.assertEqual([shelf['key'] for shelf in out['shelves']],
                         ['grp-banners', 'grp-best-new-songs', 'grp-new-releases',
                          'grp-stations'])
        self.assertEqual(out['shelves'][0]['form'], 'banners')
        self.assertEqual([row['key'] for row in out['links']], ['grp-links', 'grp-genres'])

    def test_a_multiroom_is_its_shelves(self):
        header = {'id': 'header', 'type': 'editorial-elements', 'attributes': {
            'editorialElementKind': '404', 'title': 'Invented Header'}}
        shelf = {'id': 'shelf-1', 'type': 'editorial-elements', 'attributes': {
            'editorialElementKind': '345', 'title': 'Invented Shelf'},
            'relationships': {'contents': {'data': [album('900000201', 'Lantern Season')]},
                              'room': {'data': [{'id': '900000799', 'type': 'rooms'}]}}}
        raw = {'data': [{'id': '900000705', 'type': 'multirooms', 'attributes': {
            'title': 'Invented Multiroom', 'uber': {'name': 'Invented Multiroom'}},
            'relationships': {'children': {'data': [header, shelf]}}}]}
        out = normalize.editorial_multiroom(raw, self.tmp.name)
        self.assertEqual((out['id'], out['title']), ('900000705', 'Invented Multiroom'))
        self.assertEqual([(s['key'], s['title'], [i['id'] for i in s['items']])
                          for s in out['shelves']],
                         [('mr-shelf-1', 'Invented Shelf', ['900000201'])])
        self.assertEqual(out['links'], [])

    def test_a_category_page_keeps_its_keys_and_leaves_untitled_elements_out(self):
        grouping = self.raw['data'][0]
        raw = {'data': [{'id': '900000301', 'type': 'apple-curators',
                         'attributes': {'name': 'Apple Music Folk', 'shortName': 'Folk'},
                         'relationships': {'grouping': {'data': [grouping]}}}]}
        out = normalize.category_page(raw, self.tmp.name)
        self.assertEqual(out['title'], 'Folk')
        self.assertEqual([s['key'] for s in out['shelves']],
                         ['cat-best-new-songs', 'cat-new-releases', 'cat-stations'])

    def test_a_shows_page_lists_its_episodes_then_its_playlists(self):
        # A radio show's page (#359, #360): its grouping's shelves (its episodes, which play
        # as stations), then the curator's own playlists, less one a shelf shows already.
        def playlist(pid, name):
            return {'id': pid, 'type': 'playlists', 'attributes': {
                'name': name, 'curatorName': 'The Lantern Hour',
                'playParams': {'id': pid, 'kind': 'playlist'}}}
        episode = {'id': 'ra.900000811', 'type': 'stations', 'attributes': {
            'name': 'Lanterns at Dusk', 'isLive': False, 'kind': 'streaming',
            'playParams': {'id': 'ra.900000811', 'kind': 'radioStation'}}}
        element = {'id': 'episodes', 'type': 'editorial-elements', 'attributes': {
            'editorialElementKind': '326', 'name': 'Episodes'},
            'relationships': {'contents': {'data': [
                episode, playlist('pl.900000821', 'Lantern Picks')]}}}
        grouping = {'id': '900000830', 'type': 'groupings', 'relationships': {'tabs': {
            'data': [{'id': 'tab', 'relationships': {'children': {'data': [element]}}}]}}}
        raw = {'data': [{'id': '900000901', 'type': 'apple-curators', 'attributes': {
            'name': 'The Lantern Hour', 'kind': 'Show', 'showHostName': 'Ada Fenwick'},
            'relationships': {
                'grouping': {'data': [grouping]},
                'playlists': {'data': [playlist('pl.900000821', 'Lantern Picks'),
                                       playlist('pl.900000822', 'Lantern Classics'),
                                       {'id': '900000902', 'type': 'apple-curators',
                                        'attributes': {'name': 'Invented Folk'}}]}}}]}
        out = normalize.category_page(raw, self.tmp.name)
        self.assertEqual(out['title'], 'The Lantern Hour')
        self.assertEqual([(s['key'], s['title'], [(i['kind'], i['id']) for i in s['items']])
                          for s in out['shelves']], [
            ('cat-episodes', 'Episodes', [('station', 'ra.900000811'),
                                          ('playlist', 'pl.900000821')]),
            ('playlists', '', [('playlist', 'pl.900000822')]),  # titled by the app
        ])
        self.assertEqual(out['shelves'][0]['items'][0]['play'],
                         {'kind': 'station', 'id': 'ra.900000811'})
        # Without playlists of its own, the grouping's shelves alone.
        del raw['data'][0]['relationships']['playlists']
        self.assertEqual([s['key'] for s in normalize.category_page(raw, self.tmp.name)[
            'shelves']], ['cat-episodes'])

    def test_a_curator_is_never_a_station(self):
        # #359: Apple gives a curator no playParams. However it reaches normalize_item, it
        # is a category tile with nothing to play, never a station.
        show = {'id': '900000901', 'type': 'apple-curators', 'attributes': {
            'name': 'The Lantern Hour', 'kind': 'Show', 'showHostName': 'Ada Fenwick',
            'url': 'https://music.apple.com/gb/curator/the-lantern-hour/900000901'}}
        item = normalize.normalize_item(show, self.tmp.name)
        self.assertEqual((item['kind'], item['title'], item['subtitle'], item['play'],
                          item['groups']),
                         ('category', 'The Lantern Hour', 'Ada Fenwick', {}, []))
        self.assertEqual(item['url'], show['attributes']['url'])
        nameless = normalize.normalize_item({'id': '900000903', 'type': 'apple-curators'},
                                            self.tmp.name)
        self.assertEqual((nameless['kind'], nameless['play']), ('unknown', {}))

    def test_cache_paths(self):
        self.assertEqual(normalize.browse_cache_path('/c'), os.path.join('/c', 'browse.json'))
        self.assertEqual(normalize.room_cache_path('/c', '1.2'),
                         os.path.join('/c', 'rooms', '1.2.json'))
        self.assertEqual(normalize.grouping_cache_path('/c', '../x'),
                         os.path.join('/c', 'groupings', '.._x.json'))
        self.assertEqual(normalize.multiroom_cache_path('/c', '7'),
                         os.path.join('/c', 'multirooms', '7.json'))
        for folder in ('rooms', 'groupings', 'multirooms'):
            self.assertIn(folder, normalize.ANSWER_FOLDERS)
        self.assertEqual(normalize.made_for_you_cache_path('/c'),
                         os.path.join('/c', 'made-for-you.json'))


class RadioShelvesTest(unittest.TestCase):
    NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(FIXTURES / 'editorial_radio.json', encoding='utf-8') as file:
            self.raw = json.load(file)

    def elements(self):
        return self.raw['data'][0]['relationships']['tabs']['data'][0]['relationships'][
            'children']['data']

    def shelves(self):
        return normalize.radio_shelves(self.raw, self.tmp.name, now=self.NOW)['shelves']

    def test_the_live_stations_come_first_and_the_hero_keeps_the_rest(self):
        shelves = self.shelves()
        self.assertEqual([(s['key'], s['title'], [i['id'] for i in s['items']])
                          for s in shelves], [
            ('radio-live', 'Invented Live Radio', ['ra.900000701', 'ra.900000702']),
            ('radio-hero', '', ['ra.900000801']),  # Harbour One is in the live row
            ('radio-episodes', 'Latest Episodes', ['ra.900000801']),  # the upload left out
            ('radio-shows', 'Invented Shows', ['900000901', '900000902']),
            ('radio-genres', 'Genre Stations', ['ra.900000601']),
        ])  # More to Explore and the genre links are links, not shelves
        self.assertEqual([s.get('live', False) for s in shelves], [True] + [False] * 4)
        self.assertTrue(shelves[1]['featured'])

    def test_a_hero_of_only_live_stations_is_left_out(self):
        hero = self.elements()[0]['relationships']['children']['data']
        hero.pop()  # the episode
        self.assertEqual([s['key'] for s in self.shelves()][:2], ['radio-live', 'radio-episodes'])

    def test_live_stations_carry_their_programmes_in_order(self):
        one, hits = self.shelves()[0]['items']
        self.assertEqual(one['events'], [
            {'title': 'Morning Lanterns', 'start': '2026-10-20T14:00:00Z',
             'end': '2026-10-20T16:00:00Z'},
            {'title': 'The Late Tide', 'start': '2026-10-20T16:00:00Z',
             'end': '2026-10-20T18:00:00Z'},
        ])  # the untitled one left out; the station's own subtitle kept
        self.assertEqual(one['subtitle'], 'Invented Radio')
        self.assertEqual(one['play'], {'kind': 'station', 'id': 'ra.900000701'})
        self.assertEqual(hits['events'], [{'title': 'Evergreen Requests',
                                           'start': '2026-10-20T14:00:00Z',
                                           'end': '2026-10-20T16:00:00Z'}])  # in UTC
        self.assertNotIn('events', self.shelves()[4]['items'][0])  # a genre station

    def test_episodes_are_subtitled_with_their_show_and_shows_with_their_host(self):
        shelves = self.shelves()
        for episode in (shelves[1]['items'][0], shelves[2]['items'][0]):
            self.assertEqual((episode['kind'], episode['subtitle']),
                             ('station', 'The Lantern Hour'))
        show, genre = shelves[3]['items']
        self.assertEqual((show['kind'], show['title'], show['subtitle']),
                         ('category', 'The Lantern Hour', 'Ada Fenwick'))
        self.assertNotIn('play', show)  # a show opens its page; it does not play
        self.assertEqual((genre['kind'], genre['subtitle']), ('category', 'Invented Folk'))

    def test_the_answer_expires_when_a_live_station_runs_out_of_programmes(self):
        answer = normalize.radio_shelves(self.raw, self.tmp.name, now=self.NOW)
        self.assertEqual(answer['expires'], '2026-10-20T16:00:00Z')  # Harbour Hits' last
        late = datetime(2026, 10, 20, 17, 0, tzinfo=UTC)  # every programme known ended
        self.assertEqual(normalize.radio_shelves(self.raw, self.tmp.name, now=late)['expires'],
                         '2026-10-20T17:05:00Z')
        self.assertFalse(normalize.answer_expired(answer, now=self.NOW))
        self.assertTrue(normalize.answer_expired(
            answer, now=datetime(2026, 10, 20, 16, 0, tzinfo=UTC)))
        self.assertFalse(normalize.answer_expired({'cached': '2026-10-20T00:00:00Z'}))
        self.assertFalse(normalize.answer_expired(None))

    def test_without_programmes_nothing_expires(self):
        for child in self.elements()[1]['relationships']['children']['data']:
            child['relationships']['contents']['data'][0].pop('relationships', None)
        answer = normalize.radio_shelves(self.raw, self.tmp.name)
        self.assertNotIn('expires', answer)
        self.assertNotIn('events', answer['shelves'][0]['items'][0])

    def test_nothing(self):
        self.assertEqual(normalize.radio_shelves(None, self.tmp.name), {'shelves': []})
        self.assertEqual(normalize.radio_shelves({'data': ['junk', {}]}, self.tmp.name),
                         {'shelves': []})

    def test_cache_path(self):
        self.assertEqual(normalize.radio_cache_path('/c'), os.path.join('/c', 'radio.json'))
        self.assertIn('radio.json', normalize.KEPT_ANSWERS)


class MadeForYouShelvesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_keeps_the_mixes_and_stations_and_leaves_the_rest_to_home(self):
        recs = [
            recommendation('r-mixes', 'Made for You',
                           [mix('pl.pm-1', 'Favourites Mix'), mix('pl.pm-2', 'Chill Mix')]),
            recommendation('r-recent', 'Recently Played',
                           [album('900000201', 'Lantern Season'),
                            station('ra.q-1', 'Quiet Radio')]),
            recommendation('r-albums', 'New Releases for You',
                           [album('900000202', 'Static Skyline')]),
            recommendation('r-stations', 'Stations for You',
                           [station('ra.u-1', 'Your Station'), station('ra.9', 'Folk Station')]),
            recommendation('r-editorial', 'Playlists for You',
                           [mix('pl.df-1', 'Folk Essentials', 'editorial')]),
            recommendation('r-empty', 'Nothing', []),
        ]
        shelves = normalize.made_for_you_shelves(recs, self.tmp.name)
        self.assertEqual([(s['key'], s['title'], [i['title'] for i in s['items']])
                          for s in shelves], [
            ('rec-r-mixes', 'Made for You', ['Favourites Mix', 'Chill Mix']),
            ('rec-r-stations', 'Stations for You', ['Your Station', 'Folk Station']),
        ])
        mix_item = shelves[0]['items'][0]
        self.assertEqual((mix_item['kind'], mix_item['play'], mix_item['artColor']),
                         ('playlist', {'kind': 'playlist', 'id': 'pl.pm-1'}, '#223344'))
        self.assertEqual(mix_item['groups'], [])
        self.assertEqual(shelves[1]['items'][0]['kind'], 'station')

    def test_a_group_recommendation_is_its_members(self):
        recs = [recommendation('r-group', 'For You', [], members=[
            recommendation('r-a', 'Mixes', [mix('pl.pm-1', 'Get Up! Mix')]),
            recommendation('r-b', 'Albums', [album('900000201', 'Lantern Season')]),
        ])]
        shelves = normalize.made_for_you_shelves(recs, self.tmp.name)
        self.assertEqual([s['key'] for s in shelves], ['rec-r-a'])

    def test_nothing(self):
        self.assertEqual(normalize.made_for_you_shelves(None, self.tmp.name), [])
        self.assertEqual(normalize.made_for_you_shelves(['junk', {}], self.tmp.name), [])

    def test_the_recommendations_fixture(self):
        # The invented Home fixture's "Made for You" set has no playlistType: not mixes.
        with open(FIXTURES / 'recommendations.json', encoding='utf-8') as file:
            raw = json.load(file)
        self.assertEqual(normalize.made_for_you_shelves(raw['data'], self.tmp.name), [])


class ChartsShelvesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(FIXTURES / 'charts.json', encoding='utf-8') as f:
            self.raw = json.load(f)

    def shelves(self):
        return normalize.charts_shelves(self.raw, self.tmp.name)['shelves']

    def test_the_charts_come_in_the_pages_order_whatever_the_answers(self):
        # Apple's order of `results` (and its meta order, which names only some) aside:
        # songs, albums, playlists, the Daily Top 100, City Charts, videos, then the rest.
        self.assertEqual([shelf['key'] for shelf in self.shelves()], [
            'charts-songs', 'charts-albums', 'charts-playlists', 'charts-dailyGlobalTopCharts',
            'charts-cityCharts', 'charts-music-videos', 'charts-otherCharts'])
        self.assertEqual([shelf['chart'] for shelf in self.shelves()], [
            'songs', 'albums', 'playlists', 'dailyGlobalTopCharts', 'cityCharts',
            'music-videos', 'otherCharts'])

    def test_the_rankings_are_ranked_and_top_songs_is_a_list(self):
        shelves = {shelf['chart']: shelf for shelf in self.shelves()}
        self.assertEqual({chart for chart, shelf in shelves.items() if shelf.get('ranked')},
                         {'songs', 'albums', 'playlists', 'music-videos'})
        self.assertEqual({chart for chart, shelf in shelves.items() if 'form' in shelf},
                         {'songs'})
        self.assertEqual(shelves['songs']['form'], 'songs')

    def test_titles_are_apples_and_an_untitled_chart_is_the_apps_to_name(self):
        shelves = {shelf['chart']: shelf for shelf in self.shelves()}
        self.assertEqual(shelves['songs']['title'], 'Top Songs')
        self.assertEqual(shelves['dailyGlobalTopCharts']['title'], 'Daily Top 100')
        self.assertEqual(shelves['playlists']['title'], '')  # no name in the answer

    def test_items_in_chart_order_each_once_with_a_songs_album(self):
        shelves = {shelf['chart']: shelf for shelf in self.shelves()}
        songs = shelves['songs']['items']
        # The repeat and the song without a name are left out.
        self.assertEqual([(item['id'], item['kind']) for item in songs],
                         [('1900000201', 'song'), ('1900000202', 'song')])
        self.assertEqual([item['album'] for item in songs], ['Harbour Lights', ''])
        self.assertTrue(songs[0]['explicit'])
        self.assertEqual(songs[0]['play'], {'kind': 'song', 'id': '1900000201'})
        size = normalize.ART_SIZES['thumb']
        self.assertEqual(songs[0]['art'], 'https://is1-ssl.mzstatic.com/image/thumb/Invented/'
                                          f'hl/{size}x{size}bb.jpg')
        self.assertEqual([item['id'] for item in shelves['albums']['items']],
                         ['1900000101', '1900000102'])
        # An uploaded video is not the app's to show.
        self.assertEqual([(item['id'], item['kind'])
                          for item in shelves['music-videos']['items']],
                         [('1900000301', 'video')])
        self.assertEqual([item['kind'] for item in shelves['cityCharts']['items']],
                         ['playlist', 'playlist'])

    def test_an_empty_chart_is_left_out_and_a_second_of_a_kind_keyed_apart(self):
        playlists = self.raw['results']['playlists']
        playlists[1]['data'] = playlists[0]['data']
        keys = [shelf['key'] for shelf in self.shelves()]
        self.assertEqual(keys[2:4], ['charts-playlists', 'charts-playlists-1'])

    def test_nothing(self):
        for raw in (None, {}, {'results': None}, {'results': {'songs': ['junk', {}]}},
                    {'results': {'songs': [{'data': None}]}}, 'junk'):
            self.assertEqual(normalize.charts_shelves(raw, self.tmp.name), {'shelves': []})

    def test_cache_path(self):
        self.assertEqual(normalize.charts_cache_path('/c'), os.path.join('/c', 'charts.json'))
        self.assertIn('charts.json', normalize.KEPT_ANSWERS)
        # A genre's beside it, in a folder of their own, pruned as the other answers are.
        self.assertEqual(normalize.charts_cache_path('/c', '21'),
                         os.path.join('/c', 'charts', '21.json'))
        self.assertIn('charts', normalize.ANSWER_FOLDERS)
        self.assertEqual(normalize.genres_cache_path('/c'), os.path.join('/c', 'genres.json'))
        self.assertIn('genres.json', normalize.KEPT_ANSWERS)


class CatalogGenresTest(unittest.TestCase):
    """The catalog's genres (`/v1/catalog/<sf>/genres`) as the Charts page's choice."""

    @staticmethod
    def genre(genre_id, name, parent='9000'):
        attrs = {'name': name, 'url': f'https://music.apple.com/xx/genre/{genre_id}'}
        if parent is not None:
            attrs.update(parentId=parent, parentName='Invented Music')
        return {'id': genre_id, 'type': 'genres', 'href': f'/v1/catalog/xx/genres/{genre_id}',
                'attributes': attrs}

    def test_the_genres_in_apples_order_without_the_one_they_belong_to(self):
        raw = {'data': [self.genre('9000', 'Invented Music', parent=None),
                        self.genre('9002', ' Invented   Rock '),
                        self.genre('9001', 'Invented Folk'),
                        self.genre('9002', 'Again'),  # once
                        self.genre('9003', ''),  # no name
                        self.genre('../x', 'Not an Id'),
                        {'id': '9004', 'type': 'songs', 'attributes': {'name': 'A Song'}},
                        'junk']}
        self.assertEqual(normalize.catalog_genres(raw), {'genres': [
            {'id': '9002', 'title': 'Invented Rock'}, {'id': '9001', 'title': 'Invented Folk'}]})

    def test_a_genre_without_a_parent_that_is_nobodys_stays(self):
        raw = {'data': [self.genre('9005', 'Invented Jazz', parent=None)]}
        self.assertEqual(normalize.catalog_genres(raw)['genres'],
                         [{'id': '9005', 'title': 'Invented Jazz'}])

    def test_nothing(self):
        for raw in (None, {}, {'data': None}, {'data': 'junk'}, 'junk'):
            self.assertEqual(normalize.catalog_genres(raw), {'genres': []})


class RecommendationReasonTest(unittest.TestCase):
    def test_a_reason_is_the_shelfs_subtitle_unless_it_repeats_the_title(self):
        recs = [recommendation('r-1', 'Stations for You', [station('ra.1', 'Folk Station')]),
                recommendation('r-2', 'Made for You', [mix('pl.pm-1', 'Chill Mix')]),
                recommendation('r-3', 'New Releases', [album('900000201', 'Lantern Season')])]
        recs[0]['attributes']['reason'] = {'stringForDisplay': '  Based on   what you play '}
        recs[1]['attributes']['reason'] = {'stringForDisplay': 'made for you'}  # the title
        shelves = normalize.recommendation_shelves(recs)
        self.assertEqual([shelf.get('subtitle') for shelf in shelves],
                         ['Based on what you play', None, None])
        # Made for You's shelves carry it too.
        self.assertEqual(normalize.made_for_you_shelves(recs)[0]['subtitle'],
                         'Based on what you play')

    def test_the_reason_alone(self):
        self.assertEqual(normalize.recommendation_reason(
            {'reason': {'stringForDisplay': 'Because you like folk'}, 'title': 'Folk'}),
            'Because you like folk')
        self.assertEqual(normalize.recommendation_reason({'reason': 'Bare text'}), 'Bare text')
        for attrs in (None, {}, {'reason': None}, {'reason': {'stringForDisplay': 3}}):
            self.assertEqual(normalize.recommendation_reason(attrs), '')


class RecentlyPlayedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_the_items_played_in_order_each_once(self):
        curator = {'id': '900000901', 'type': 'apple-curators',
                   'attributes': {'name': 'Invented Curator'}}
        library = {'id': 'l.pl101', 'type': 'library-playlists',
                   'attributes': {'name': 'Invented Evenings', 'canEdit': True,
                                  'playParams': {'id': 'p.pl101', 'kind': 'playlist',
                                                 'isLibrary': True}}}
        raw = [album('900000201', 'Lantern Season'), station('ra.q-1', 'Quiet Radio'),
               curator, library, album('900000201', 'Lantern Season'), 'junk',
               {'id': 'x', 'type': 'albums', 'attributes': {}}]  # no name: no tile
        answer = normalize.recently_played(raw, self.tmp.name)
        self.assertEqual(set(answer), {'items'})
        self.assertEqual([(item['kind'], item['id']) for item in answer['items']],
                         [('album', '900000201'), ('station', 'ra.q-1'),
                          ('playlist', 'l.pl101')])
        self.assertTrue(all(item['groups'] == [] for item in answer['items']))
        station_item = answer['items'][1]
        self.assertTrue(station_item['art'].startswith('https://'))  # a catalog URL
        self.assertIsNone(station_item['thumb'])

    def test_nothing(self):
        for raw in (None, [], {'data': []}, ['junk']):
            self.assertEqual(normalize.recently_played(raw, self.tmp.name), {'items': []})

    def test_cache_path(self):
        self.assertEqual(normalize.recent_played_cache_path('/c'),
                         os.path.join('/c', 'recent-played.json'))
        self.assertIn('recent-played.json', normalize.KEPT_ANSWERS)


if __name__ == '__main__':
    unittest.main()
