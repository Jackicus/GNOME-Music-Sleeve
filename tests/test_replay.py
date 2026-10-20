# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Replay: Apple's music summaries shaped into the page's answer (normalize.replay_page,
replay_years, api.replay_request), the year menu's choices and the page's title
(src/replay.py), the link to it (explore.replay_item, replay_sections), and the page itself
(pages/replay.py) over the stand-in engine: its shelves in their forms, its year menu, its
states, and the ways to it, Made for You's and Home's More for You and the window's
open_item. Every answer here is invented."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.page_harness import PageTestCase, album

from applemusic import explore
from applemusic import replay as years_menu
from applemusic.backend import api, normalize
from applemusic.backend.errors import EngineError


def resource(kind, number, **attributes):
    """An invented catalog resource of `kind` (Apple's type), named for its number."""
    names = {'songs': 'Invented Song', 'artists': 'Invented Artist',
             'albums': 'Invented Album', 'playlists': 'Invented Replay'}
    attrs = {'name': f'{names[kind]} {number}', 'artistName': 'Invented Artist',
             'artwork': {'url': 'https://example.invalid/{w}x{h}bb.jpg', 'width': 100,
                         'height': 100}}
    if kind == 'songs':
        attrs['albumName'] = f'Invented Album {number}'
    attrs.update(attributes)
    return {'id': f'90{number:04d}' if kind != 'playlists' else f'pl.inv{number}',
            'type': kind, 'attributes': attrs}


def period_summary(kind, number, year=2026, plays=10):
    """An invented period summary, as a Replay view's items are: the play counts of one
    song, artist or album, which it holds as its relationship. A song is its id alone (no
    attributes), an artist or album the whole catalog resource."""
    one = kind.removesuffix('s')
    held = resource(kind, number)
    if kind == 'songs':
        held = {'id': held['id'], 'type': 'songs', 'href': f'/v1/catalog/zz/songs/{held["id"]}'}
    attrs = {'playCount': plays, 'year': str(year), 'firstPlayed': f'{year}-01-02',
             'lastPlayed': f'{year}-03-04'}
    if kind != 'songs':
        attrs['listenTimeInMinutes'] = plays * 3
    return {'id': f'inv-{one}-summary-{number}', 'type': f'{one}-period-summaries',
            'attributes': attrs, 'relationships': {one: {'data': [held]}}}


def summary(year=2026, songs=3, artists=2, albums=2, titles=False):
    """An invented music summary, as `/v1/me/music-summaries?filter[year]=latest&views=…` and
    `/v1/me/music-summaries/year-<YYYY>?views=…` answer it: each view's items period
    summaries, in rank order."""
    def view(name, kind, count, start):
        entry = {'href': f'/v1/me/music-summaries/year-{year}/view/{name}',
                 'meta': {'count': count, 'types': [f'{kind.removesuffix("s")}-period-summaries']},
                 'data': [period_summary(kind, start + n, year) for n in range(count)]}
        if titles:
            entry['attributes'] = {'title': f'Invented {name}', 'shortTitle': 'Invented',
                                   'subtitle': 'Invented', 'highlights': []}
        return entry
    return {'data': [{'id': f'year-{year}', 'type': 'music-summaries',
                      'href': f'/v1/me/music-summaries/year-{year}',
                      'attributes': {'year': year, 'period': 'year', 'name': 'Invented',
                                     'topSongCount': songs},
                      'meta': {'views': {'order': ['top-artists', 'top-songs', 'top-albums']}},
                      'relationships': {'playlist': {'data': [{
                          'id': f'pl.inv{year}', 'type': 'playlists',
                          'href': f'/v1/catalog/zz/playlists/pl.inv{year}'}]}},
                      'views': {'top-songs': view('top-songs', 'songs', songs, 0),
                                'top-artists': view('top-artists', 'artists', artists, 100),
                                'top-albums': view('top-albums', 'albums', albums, 200)}}],
            'meta': {'filters': {'year': {'latest': [{
                'id': f'year-{year}', 'type': 'music-summaries',
                'href': f'/v1/me/music-summaries/year-{year}'}]}}}}


def catalog_songs(*numbers):
    """An invented catalog read of songs by id, as `/v1/catalog/<storefront>/songs?ids=…`
    answers it (not in the order asked)."""
    return {'data': [resource('songs', number) for number in sorted(numbers, reverse=True)]}


def years(*numbers, playlists=True):
    """An invented years listing, as `/v1/me/music-summaries/search?period=year` answers."""
    return {'data': [{'id': f'year-{year}', 'type': 'music-summaries',
                      'attributes': {'period': 'year', 'year': year},
                      'relationships': {'playlist': {'data': (
                          [resource('playlists', year)] if playlists else [])}}}
                     for year in numbers]}


class ReplayShapeTest(unittest.TestCase):
    """normalize.replay_page and replay_years, without the engine."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = tmp.name

    def shape(self, **raw):
        return normalize.replay_page(raw, self.cache)

    def test_the_views_in_the_pages_order_then_the_playlists(self):
        answer = self.shape(summary=summary(), songs=catalog_songs(0, 1, 2),
                            years=years(2024, 2026, 2025), year='')
        self.assertEqual(answer['year'], '2026')
        self.assertEqual(answer['years'], ['2026', '2025', '2024'])
        shelves = answer['shelves']
        self.assertEqual([(shelf['key'], shelf['chart']) for shelf in shelves], [
            ('replay-songs', 'songs'), ('replay-artists', 'artists'),
            ('replay-albums', 'albums'), ('replay-playlists', 'replay-playlists')])
        self.assertEqual([shelf.get('ranked') for shelf in shelves], [True, True, True, None])
        self.assertEqual([shelf.get('form') for shelf in shelves], ['songs', None, None, None])
        self.assertEqual([shelf['title'] for shelf in shelves], ['', '', '', ''])  # the app's
        songs = shelves[0]['items']
        self.assertEqual([item['title'] for item in songs],
                         ['Invented Song 0', 'Invented Song 1', 'Invented Song 2'])
        self.assertEqual(songs[0]['album'], 'Invented Album 0')
        self.assertEqual(songs[0]['groups'], [])
        self.assertEqual([item['kind'] for item in shelves[1]['items']], ['artist', 'artist'])
        self.assertEqual([item['title'] for item in shelves[1]['items']],
                         ['Invented Artist 100', 'Invented Artist 101'])
        self.assertEqual([(item['kind'], item['title']) for item in shelves[2]['items']],
                         [('album', 'Invented Album 200'), ('album', 'Invented Album 201')])
        self.assertEqual([item['id'] for item in shelves[3]['items']],
                         ['pl.inv2026', 'pl.inv2025', 'pl.inv2024'])  # newest first

    def test_the_songs_are_the_catalogs_in_the_summarys_order(self):
        # Apple names a top song by its id alone: its title and artwork are the catalog
        # read's, whatever order that answers in; a song it did not answer is left out.
        answer = self.shape(summary=summary(songs=4), songs=catalog_songs(3, 0, 1), year='')
        songs = answer['shelves'][0]['items']
        self.assertEqual([item['id'] for item in songs], ['900000', '900001', '900003'])
        self.assertEqual(songs[2]['album'], 'Invented Album 3')
        self.assertTrue(songs[0]['art'] or songs[0]['thumb'] or songs[0].get('artUrl'),
                        songs[0])
        # Without the catalog read, no song can be shown: Top Songs is left out.
        answer = self.shape(summary=summary(), songs=None, year='')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']],
                         ['replay-artists', 'replay-albums'])

    def test_the_song_ids_the_catalog_is_asked_for(self):
        raw = summary(songs=3)
        data = raw['data'][0]['views']['top-songs']['data']
        data.append(dict(data[0]))  # the same song again
        data.append({'type': 'song-period-summaries', 'relationships': {'song': {'data': []}}})
        data.append(period_summary('songs', 7) | {'relationships': {'song': {'data': [
            {'id': 'i.inv7', 'type': 'library-songs'}]}}})  # no catalog id
        self.assertEqual(normalize.replay_song_ids(raw), ['900000', '900001', '900002'])
        for junk in (None, {}, {'data': 'x'}, {'data': [{'views': {'top-songs': 'x'}}]}):
            self.assertEqual(normalize.replay_song_ids(junk), [])
        self.assertEqual(api.replay_songs_params(['900000', '900001', '900000', 'i.x', None]),
                         {'ids': '900000,900001'})
        self.assertIsNone(api.replay_songs_params([]))
        many = [str(900000 + n) for n in range(150)]
        self.assertEqual(len(api.replay_songs_params(many)['ids'].split(',')),
                         api.REPLAY_SONGS_LIMIT)

    def test_the_year_from_the_summarys_id(self):
        raw = summary(year=2025)
        del raw['data'][0]['attributes']['year']
        self.assertEqual(self.shape(summary=raw, year='')['year'], '2025')
        listing = years(2024)
        del listing['data'][0]['attributes']['year']
        self.assertEqual([entry['year'] for entry in normalize.replay_years(listing)], ['2024'])

    def test_apples_titles_are_kept(self):
        answer = self.shape(summary=summary(titles=True), songs=catalog_songs(0, 1, 2),
                            years=None, year='')
        self.assertEqual([shelf['title'] for shelf in answer['shelves']],
                         ['Invented top-songs', 'Invented top-artists', 'Invented top-albums'])
        self.assertEqual(answer['years'], [])

    def test_no_summary_leaves_the_playlists_and_the_year_asked(self):
        answer = self.shape(summary=None, years=years(2025, 2024), year='2025')
        self.assertEqual(answer['year'], '2025')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']], ['replay-playlists'])
        self.assertEqual(self.shape(summary=None, years=None, year=''),
                         {'year': '', 'years': [], 'shelves': []})

    def test_empty_views_and_junk_are_left_out(self):
        raw = summary(songs=0, artists=0, albums=1)
        raw['data'][0]['views']['top-songs'] = 'junk'
        albums = raw['data'][0]['views']['top-albums']['data']
        albums.append({'type': 'album-period-summaries', 'relationships': {
            'album': {'data': [{'id': '900299', 'type': 'albums'}]}}})  # no name
        albums.append({'type': 'album-period-summaries', 'relationships': {'album': 'junk'}})
        albums.append({'type': 'album-period-summaries'})
        albums.append('junk')
        answer = self.shape(summary=raw, songs={'data': 'junk'}, years={'data': ['junk']},
                            year='')
        self.assertEqual([shelf['key'] for shelf in answer['shelves']], ['replay-albums'])
        self.assertEqual(len(answer['shelves'][0]['items']), 1)
        for junk in (None, {}, [], 'x', {'summary': 'x', 'years': 3, 'year': '../x'}):
            self.assertEqual(normalize.replay_page(junk, self.cache)['shelves'], [])

    def test_the_years_each_once_newest_first(self):
        raw = years(2024, 2025, playlists=False)
        raw['data'] += [
            {'type': 'music-summaries', 'attributes': {'period': 'year', 'year': 2025}},
            {'type': 'music-summaries', 'attributes': {'period': 'month', 'year': 2023}},
            {'type': 'music-summaries', 'attributes': {'year': 'next'}},
            {'type': 'music-summaries', 'attributes': {'year': 2022}}]  # no period: a year
        found = normalize.replay_years(raw, self.cache)
        self.assertEqual([(entry['year'], entry['playlist']) for entry in found],
                         [('2025', None), ('2024', None), ('2022', None)])
        self.assertEqual(normalize.replay_years(None), [])

    def test_where_it_is_kept(self):
        self.assertEqual(normalize.replay_cache_path('/c'), os.path.join('/c', 'replay.json'))
        self.assertEqual(normalize.replay_cache_path('/c', '2025'),
                         os.path.join('/c', 'replay', '2025.json'))
        self.assertIn('replay.json', normalize.KEPT_ANSWERS)
        self.assertIn('replay', normalize.ANSWER_FOLDERS)

    def test_what_a_year_is_asked_with(self):
        # The latest year by filter[year]=latest; a past year by its own resource, since
        # Apple answers filter[year]=<YYYY> with a 400.
        views = {'views': 'top-songs,top-artists,top-albums'}
        self.assertEqual(api.replay_request(), (
            '/v1/me/music-summaries', {'filter[year]': 'latest', **views}))
        self.assertEqual(api.replay_request('2025'),
                         ('/v1/me/music-summaries/year-2025', views))
        self.assertTrue(api.is_replay_year('2025'))
        for bad in ('', '25', '20255', '../x', 2025, None, '3025'):
            self.assertFalse(api.is_replay_year(bad), bad)


class ChoicesTest(unittest.TestCase):
    """src/replay.py: the year menu's entries and the page's title, without GTK."""

    def test_the_years_newest_first_the_latest_as_latest(self):
        found = years_menu.choices(['2024', '2026', '2025', '2025', 'junk', 7], '2026')
        self.assertEqual(found, [('', '2026'), ('2025', '2025'), ('2024', '2024')])
        self.assertEqual(years_menu.position(found, '2024'), 2)
        self.assertEqual(years_menu.position(found, ''), 0)
        self.assertEqual(years_menu.position(found, '1999'), 0)
        # The latest year alone: one entry (the menu then hides).
        self.assertEqual(years_menu.choices([], '2026'), [('', '2026')])

    def test_without_the_latest_year_a_latest_entry_leads(self):
        self.assertEqual(years_menu.choices(['2025'], ''), [('', 'Latest'), ('2025', '2025')])
        self.assertEqual(years_menu.choices(None), [('', 'Latest')])

    def test_the_title(self):
        self.assertEqual(years_menu.page_title('2026'), 'Replay 2026')
        for none in (None, '', 'junk'):
            self.assertEqual(years_menu.page_title(none), 'Replay')

    def test_the_link(self):
        item = explore.replay_item()
        self.assertEqual((item.kind, item.id), ('replay', 'replay'))
        self.assertFalse(item.thumb or item.art)
        (section,) = explore.replay_sections()
        self.assertEqual((section.key, section.title), ('replay', 'More for You'))
        self.assertEqual([entry.kind for entry in section.items], ['replay'])
        rows = [{'key': 'r', 'title': 'Invented Row', 'links': [
            {'title': 'Invented Room', 'kind': 'room', 'id': '9001'}]}]
        self.assertEqual([found.key for found in explore.sections(rows, replay=True)],
                         ['r', 'replay'])
        self.assertEqual([found.key for found in explore.sections(None, replay=True)],
                         ['replay'])
        self.assertEqual([found.key for found in explore.sections(rows)], ['r'])


def song(number):
    return {'id': f'190{number}', 'kind': 'song', 'title': f'Invented Song {number}',
            'subtitle': 'Invented Artist', 'album': 'Invented Album', 'art': None,
            'thumb': None, 'play': {'kind': 'song', 'id': f'190{number}'}}


def artist(number):
    return {'id': f'c.art{number}', 'kind': 'artist', 'title': f'Invented Artist {number}',
            'subtitle': None, 'art': None, 'thumb': None,
            'play': {'kind': 'artist', 'id': f'c.art{number}'}}


def answer(year='2026', listed=('2026', '2025', '2024'), songs=6):
    """An invented Replay answer, as Engine.replay gives it (normalize.replay_page)."""
    return {'year': year, 'years': list(listed), 'shelves': [
        {'key': 'replay-songs', 'title': '', 'chart': 'songs', 'ranked': True,
         'form': 'songs', 'items': [song(n) for n in range(songs)]},
        {'key': 'replay-artists', 'title': '', 'chart': 'artists', 'ranked': True,
         'items': [artist(n) for n in range(3)]},
        {'key': 'replay-albums', 'title': '', 'chart': 'albums', 'ranked': True,
         'items': [dict(album(n, tracks=0), id=f'c{n}') for n in range(3)]},
        {'key': 'replay-playlists', 'title': '', 'chart': 'replay-playlists',
         'items': [dict(album(n, tracks=0, kind='playlist'), id=f'pl.replay{year}{n}')
                   for n in range(2)]},
    ]}


class ReplayPageTest(PageTestCase):
    async def replay_page(self):
        from applemusic.pages import replay

        page = await self.push(replay.create(replay.replay_item()))
        await self.settle()
        return page

    async def all_shelves(self, page, count=4):
        """Wait for the column to bind the answer's shelves: those after FIRST_SHELVES come
        one a frame (ShelfColumn), and a slow display's frames come late."""
        self.assertTrue(await self.until_frames(page, lambda: len([
            widget for widget in page._column.widgets if widget.get_visible()]) == count),
            [widget.shelf.title for widget in page._column.widgets])

    async def test_each_shelf_in_its_form_under_the_years_title(self):
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.song_shelf import SongShelf

        self.app.engine.answers['replay'] = answer()
        page = await self.replay_page()
        self.assertEqual(page.title_label.get_label(), 'Replay 2026')
        self.assertEqual(page.get_title(), 'Replay 2026')
        self.assertEqual(page.item.kind, 'replay')
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        await self.all_shelves(page)
        widgets = page._column.widgets
        self.assertEqual([(type(widget), widget.shelf.title) for widget in widgets], [
            (SongShelf, 'Top Songs'), (Shelf, 'Top Artists'), (Shelf, 'Top Albums'),
            (Shelf, 'Replay Playlists')])
        self.assertFalse(widgets[1].props.hero)  # no large cards
        self.assertEqual([widget.shelf.ranked for widget in widgets], [True, True, True, False])
        self.assertEqual(self.app.engine.calls, ['replay'])

    async def test_a_song_plays_the_list_from_it_and_a_playlist_opens(self):
        self.app.engine.answers['replay'] = answer()
        page = await self.replay_page()
        await self.all_shelves(page)
        songs, _artists, _albums, playlists = page._column.widgets
        songs.grid_view.emit('activate', 2)
        self.assertEqual(self.window.played, [
            ({'kind': 'songs', 'id': ','.join(f'190{n}' for n in range(6))}, 2, None)])
        playlists.list_view.emit('activate', 1)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('playlist', 'pl.replay20261')])

    async def test_the_year_menu_shows_a_past_year(self):
        asked = []

        def replay(year, refresh):
            asked.append((year, refresh))
            return answer(year or '2026', songs=2 if year else 6)

        self.app.engine.answers['replay'] = replay
        page = await self.replay_page()
        await self.all_shelves(page)
        menu = page.year_menu
        drop_down = menu.drop_down
        self.assertIs(drop_down.get_parent().get_ancestor(type(page.header_bar)),
                      page.header_bar)
        self.assertTrue(drop_down.get_visible())
        self.assertEqual(drop_down.get_tooltip_text(), 'Year')
        model = drop_down.get_model()
        self.assertEqual([model.get_string(n) for n in range(model.get_n_items())],
                         ['2026', '2025', '2024'])
        self.assertEqual((drop_down.get_selected(), asked), (0, [(None, False)]))
        drop_down.set_selected(2)
        self.assertEqual(menu.year, '2024')
        # Started over: that year's shelves, under its title.
        def shown():
            widgets = [widget for widget in page._column.widgets if widget.get_visible()]
            return [[item.id for item in widget.shelf.items] for widget in widgets]

        self.assertTrue(await self.until_frames(page, lambda: len(shown()) == 4 and shown()[0]
                                                == ['1900', '1901'] and shown()[-1]
                                                == ['pl.replay20240', 'pl.replay20241']))
        self.assertEqual(page.title_label.get_label(), 'Replay 2024')
        self.assertEqual(asked, [(None, False), ('2024', False)])
        page.refresh()
        await self.settle()
        self.assertEqual(asked[-1], ('2024', True))  # Refresh asks for the year shown
        drop_down.set_selected(0)  # the latest again: asked without a year
        self.assertEqual(page.title_label.get_label(), 'Replay 2026')  # at once
        self.assertTrue(await self.until(lambda: asked[-1] == (None, False)), asked)

    async def test_a_year_that_fails_says_so_under_its_title(self):
        def replay(year, refresh):
            return EngineError('api') if year else answer()

        self.app.engine.answers['replay'] = replay
        page = await self.replay_page()
        await self.all_shelves(page)
        page.year_menu.drop_down.set_selected(1)
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'status'))
        self.assertEqual(page.title_label.get_label(), 'Replay 2025')
        self.assertEqual(self.app.reported, [])  # the page says it: no toast

    async def test_one_year_alone_has_no_menu(self):
        self.app.engine.answers['replay'] = answer(listed=())
        page = await self.replay_page()
        self.assertFalse(page.year_menu.drop_down.get_visible())

    async def test_the_engine_down_and_signed_out_say_so(self):
        self.app.engine.answers['replay'] = EngineError('engine-down')
        page = await self.replay_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_icon_name(), 'x-office-calendar-symbolic')
        self.assertEqual(page.status_button.get_label(), 'Start Engine')
        self.assertEqual(page.title_label.get_label(), 'Replay')
        self.assertFalse(page.year_menu.drop_down.get_visible())  # nothing to choose
        self.window.navigation_view.pop()
        self.app.engine.answers['replay'] = EngineError('not-signed-in')
        page = await self.replay_page()
        self.assertEqual(page.status_button.get_label(), 'Sign In…')
        self.assertEqual(self.app.reported, [])  # the page says it: no toast

    async def test_no_listening_history(self):
        self.app.engine.answers['replay'] = {'year': '', 'years': [], 'shelves': []}
        page = await self.replay_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_title(), 'No Replay Yet')
        self.assertEqual(page.title_label.get_label(), 'Replay')


class MoreForYouTest(PageTestCase):
    """Made for You and Home end with More for You, whose link opens Replay."""

    def link(self, page):
        from applemusic.widgets.explore import ExploreBox, LinkChild

        last = page.shelves_box.get_last_child()
        self.assertIsInstance(last, ExploreBox)
        self.assertTrue(last.get_visible())
        section = last.get_first_child()
        title, links = section.get_first_child(), section.get_last_child()
        self.assertEqual(title.get_label(), 'More for You')
        child = links.get_child_at_index(0)
        self.assertIsInstance(child, LinkChild)
        self.assertEqual(child.item.title, 'Replay: Your Year in Music')
        return links, child

    async def test_made_for_you_ends_with_it(self):
        from applemusic.pages import made_for_you
        from applemusic.sections import Destination

        self.app.engine.answers['made_for_you'] = {'shelves': [
            {'key': 'rec-1', 'title': 'Invented Mixes',
             'items': [dict(album(n, tracks=0, kind='playlist'), id=f'pl.mix{n}')
                       for n in range(3)]}]}
        page = await self.show_root(made_for_you.create(
            Destination('made-for-you', 'Made for You', 'starred-symbolic')))
        await self.settle()
        self.assertTrue(await self.until(lambda: len(page._column.widgets) == 1, timeout=3))
        links, child = self.link(page)
        self.assertIs(page.shelves_box.get_last_child().get_prev_sibling(),
                      page._column.widgets[-1])  # after the shelves
        links.emit('child-activated', child)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('replay', 'replay')])

    async def test_home_ends_with_it(self):
        from applemusic.pages.home import HomePage

        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        data = {'version': 3, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': [album(1)], 'playlists': []},
                'shelves': [{'key': 'rec-top', 'title': 'Invented Picks',
                             'items': [album(1)]}]}
        Path(cache.name, 'library.json').write_text(json.dumps(data), encoding='utf-8')
        await self.library.load()
        page = await self.show_root(HomePage(self.library, 'Home', 'go-home-symbolic'))
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        links, child = self.link(page)
        links.emit('child-activated', child)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('replay', 'replay')])


if __name__ == '__main__':
    unittest.main()
