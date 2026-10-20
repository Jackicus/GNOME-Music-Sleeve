# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Charts page (pages/charts.py) over the stand-in engine: Apple's charts as shelves in
their forms (Top Songs a numbered grid of songs, the rankings numbered tiles, the Daily Top
100 and City Charts playlists), the engine's failures on its status page, and the ways to it:
New's More to Explore (pages/new.py) and the window's open_item."""

import unittest

from tests.page_harness import PageTestCase, album

from applemusic.backend.errors import EngineError


def song(number):
    return {'id': f'190{number}', 'kind': 'song', 'title': f'Invented Song {number}',
            'subtitle': 'Invented Artist', 'album': 'Invented Album', 'art': None,
            'thumb': None, 'play': {'kind': 'song', 'id': f'190{number}'}}


def playlist(key, number):
    return dict(album(number, tracks=0, kind='playlist'), id=f'pl.{key}{number}')


def answer():
    """An invented charts answer, as Engine.charts gives it (normalize.charts_shelves)."""
    return {'shelves': [
        {'key': 'charts-songs', 'title': 'Top Songs', 'chart': 'songs', 'ranked': True,
         'form': 'songs', 'items': [song(n) for n in range(6)]},
        {'key': 'charts-albums', 'title': 'Top Albums', 'chart': 'albums', 'ranked': True,
         'items': [dict(album(n, tracks=0), id=f'c{n}') for n in range(4)]},
        {'key': 'charts-dailyGlobalTopCharts', 'title': '', 'chart': 'dailyGlobalTopCharts',
         'items': [playlist('daily', n) for n in range(3)]},
        {'key': 'charts-cityCharts', 'title': 'City Charts', 'chart': 'cityCharts',
         'items': [playlist('city', n) for n in range(2)]},
    ]}


class ChartsPageTest(PageTestCase):
    async def charts_page(self):
        from applemusic.pages import charts

        page = await self.push(charts.create(charts.charts_item()))
        await self.settle()
        return page

    def test_the_charts_item(self):
        from applemusic.pages.charts import charts_item

        item = charts_item()
        self.assertEqual((item.kind, item.id, item.title), ('charts', 'charts', 'Top Charts'))
        self.assertFalse(item.thumb or item.art)

    async def test_each_chart_in_its_form(self):
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.song_shelf import SongShelf

        self.app.engine.answers['charts'] = answer()
        page = await self.charts_page()
        self.assertEqual(page.title_label.get_label(), 'Top Charts')
        self.assertEqual(page.item.kind, 'charts')
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        widgets = page._column.widgets
        self.assertEqual([(type(widget), widget.shelf.title) for widget in widgets], [
            (SongShelf, 'Top Songs'), (Shelf, 'Top Albums'), (Shelf, 'Daily Top 100'),
            (Shelf, 'City Charts')])
        self.assertFalse(widgets[1].props.hero)  # no large cards: the charts are alike
        self.assertEqual([widget.shelf.ranked for widget in widgets], [True, True, False, False])

    async def test_a_song_plays_the_chart_from_it_and_a_playlist_opens(self):
        self.app.engine.answers['charts'] = answer()
        page = await self.charts_page()
        songs, _albums, daily, _cities = page._column.widgets
        songs.grid_view.emit('activate', 1)
        self.assertEqual(self.window.played, [
            ({'kind': 'songs', 'id': ','.join(f'190{n}' for n in range(6))}, 1, None)])
        daily.list_view.emit('activate', 2)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('playlist', 'pl.daily2')])

    async def test_the_engine_down_says_so(self):
        self.app.engine.answers['charts'] = EngineError('engine-down')
        page = await self.charts_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_icon_name(), 'view-list-ordered-symbolic')
        self.assertEqual(page.status_button.get_label(), 'Start Engine')
        self.assertEqual(self.app.engine.calls, ['charts'])

    async def test_no_charts(self):
        self.app.engine.answers['charts'] = {'shelves': []}
        page = await self.charts_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_title(), 'No Charts')


class NewPageTest(PageTestCase):
    """New ends with More to Explore, whose Top Charts tile opens the Charts page."""

    async def test_more_to_explore_follows_the_shelves_and_opens_the_charts(self):
        from applemusic.pages import new
        from applemusic.sections import Destination

        self.app.engine.answers['browse'] = {'shelves': [
            {'key': f'new-{n}', 'title': f'Invented Shelf {n}',
             'items': [dict(album(i, tracks=0), id=f'n{n}.{i}') for i in range(3)]}
            for n in range(3)]}
        page = await self.show_root(new.create(Destination('new', 'New',
                                                            'view-grid-symbolic')))
        await self.settle()
        self.assertTrue(await self.until(lambda: len(page._column.widgets) == 3, timeout=3))
        last = page.shelves_box.get_last_child()
        self.assertIs(last.get_prev_sibling(), page._column.widgets[-1])  # after them all
        title, tiles = last.get_first_child(), last.get_last_child()
        self.assertEqual(title.get_label(), 'More to Explore')
        tile = tiles.get_child_at_index(0).get_child()
        self.assertEqual(tile.item.title, 'Top Charts')
        tiles.emit('child-activated', tiles.get_child_at_index(0))
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('charts', 'charts')])


if __name__ == '__main__':
    unittest.main()
