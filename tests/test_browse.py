# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The backend's shaping of the New page and the Radio page (editorial groupings) and Made
for You (recommendations) into shelves, over invented answers."""

import json
import os
import pathlib
import tempfile
import unittest
from datetime import UTC, datetime

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import normalize

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
        self.assertEqual(normalize.editorial_shelves(None, self.tmp.name), {'shelves': []})
        self.assertEqual(normalize.editorial_shelves({'data': ['junk', {}]}, self.tmp.name),
                         {'shelves': []})
        answer = {'errors': [{'status': '500'}]}
        self.assertEqual(normalize.editorial_shelves(answer, self.tmp.name), {'shelves': []})

    def test_a_category_page_keeps_its_keys_and_leaves_untitled_elements_out(self):
        grouping = self.raw['data'][0]
        raw = {'data': [{'id': '900000301', 'type': 'apple-curators',
                         'attributes': {'name': 'Apple Music Folk', 'shortName': 'Folk'},
                         'relationships': {'grouping': {'data': [grouping]}}}]}
        out = normalize.category_page(raw, self.tmp.name)
        self.assertEqual(out['title'], 'Folk')
        self.assertEqual([s['key'] for s in out['shelves']],
                         ['cat-best-new-songs', 'cat-new-releases', 'cat-stations'])

    def test_cache_paths(self):
        self.assertEqual(normalize.browse_cache_path('/c'), os.path.join('/c', 'browse.json'))
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


if __name__ == '__main__':
    unittest.main()
