# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Charts page (pages/charts.py) over the stand-in engine: Apple's charts as shelves in
their forms (Top Songs a numbered grid of songs, the rankings numbered tiles, the Daily Top
100 and City Charts playlists), its genre menu (src/charts.py's choices), the engine's
failures on its status page, and the ways to it: New's More to Explore (pages/new.py) and
the window's open_item."""

import unittest

from tests.page_harness import PageTestCase, album

from applemusic import charts as genres_menu
from applemusic.backend.api import ROOT_GENRE
from applemusic.backend.errors import EngineError
from applemusic.library import Item

GENRES = {'genres': [{'id': '21', 'title': 'Invented Rock'},
                     {'id': '22', 'title': 'Invented Folk'}]}


def genre_answer(genre):
    """An invented chart of one genre: its Top Songs alone, named for it."""
    return {'shelves': [{'key': 'charts-songs', 'title': f'Top Songs {genre}', 'chart': 'songs',
                         'ranked': True, 'form': 'songs',
                         'items': [song(n) for n in range(3)]}]}


def charts_link(genre, title='Invented Rock Charts'):
    """A More to Explore link's Item to a genre's charts (explore.link_item's)."""
    return Item({'id': 'charts', 'kind': 'charts', 'title': title, 'subtitle': None,
                 'art': None, 'thumb': None, 'artColor': None, 'url': None, 'play': {},
                 'groups': [], 'genre': genre})


class ChoicesTest(unittest.TestCase):
    """src/charts.py: the menu's entries, without GTK."""

    def test_all_genres_first_then_apples_each_once(self):
        found = genres_menu.choices(GENRES['genres'] + [
            {'id': '21', 'title': 'Again'}, {'id': 'x1', 'title': 'Not an Id'},
            {'id': '23', 'title': '  '}, 'junk'])
        self.assertEqual(found, [('', 'All Genres'), ('21', 'Invented Rock'),
                                 ('22', 'Invented Folk')])
        self.assertEqual(genres_menu.position(found, '22'), 2)
        self.assertEqual(genres_menu.position(found, '99'), 0)
        self.assertEqual(genres_menu.choices(None), [('', 'All Genres')])

    def test_a_links_genre_they_lack_follows_all_genres_under_its_words(self):
        found = genres_menu.choices([], '24', '  Invented   Jazz Charts ')
        self.assertEqual(found, [('', 'All Genres'), ('24', 'Invented Jazz Charts')])
        self.assertEqual(genres_menu.choices(None, '24')[1], ('24', '24'))
        # Once Apple's list has it, it is there under Apple's name.
        found = genres_menu.choices(GENRES['genres'], '22', 'Invented Folk Charts')
        self.assertEqual([choice.title for choice in found],
                         ['All Genres', 'Invented Rock', 'Invented Folk'])

    def test_the_genre_a_link_names(self):
        self.assertEqual(genres_menu.link_genre(charts_link('21')), '21')
        for genre in (None, '', '../x', 'abc'):
            self.assertEqual(genres_menu.link_genre(charts_link(genre)), '')
        from applemusic.explore import charts_item

        self.assertEqual(genres_menu.link_genre(charts_item()), '')

    def test_the_root_genre_is_all_genres(self):
        # Music, every genre's (New's "Charts" link names it): the charts of every genre.
        self.assertEqual(genres_menu.link_genre(charts_link(ROOT_GENRE, 'Charts')), '')
        self.assertEqual(genres_menu.choices(GENRES['genres'], ROOT_GENRE, 'Charts'),
                         genres_menu.choices(GENRES['genres']))
        self.assertEqual(genres_menu.position(
            genres_menu.choices(GENRES['genres'], ROOT_GENRE), ROOT_GENRE), 0)


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

    async def all_shelves(self, page):
        """Wait for the column to bind the answer's four shelves: those after FIRST_SHELVES
        come one a frame (ShelfColumn), and a slow display's frames come late."""
        self.assertTrue(await self.until_frames(page, lambda: len(page._column.widgets) == 4),
                        [widget.shelf.title for widget in page._column.widgets])

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
        await self.all_shelves(page)
        widgets = page._column.widgets
        self.assertEqual([(type(widget), widget.shelf.title) for widget in widgets], [
            (SongShelf, 'Top Songs'), (Shelf, 'Top Albums'), (Shelf, 'Daily Top 100'),
            (Shelf, 'City Charts')])
        self.assertFalse(widgets[1].props.hero)  # no large cards: the charts are alike
        self.assertEqual([widget.shelf.ranked for widget in widgets], [True, True, False, False])

    async def test_a_song_plays_the_chart_from_it_and_a_playlist_opens(self):
        self.app.engine.answers['charts'] = answer()
        page = await self.charts_page()
        await self.all_shelves(page)
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
        self.assertEqual(self.app.engine.calls, ['charts', 'genres'])
        self.assertFalse(page.genre_menu.drop_down.get_visible())  # nothing to choose

    async def test_the_genre_menu_narrows_the_charts_to_a_genre(self):
        asked = []

        def charts(genre, refresh):
            asked.append(genre)
            return genre_answer(genre) if genre else answer()

        self.app.engine.answers['charts'] = charts
        self.app.engine.answers['genres'] = GENRES
        page = await self.charts_page()
        await self.all_shelves(page)
        menu = page.genre_menu
        drop_down = menu.drop_down
        self.assertIs(drop_down.get_parent().get_ancestor(type(page.header_bar)),
                      page.header_bar)
        self.assertTrue(drop_down.get_visible())
        self.assertEqual(drop_down.get_tooltip_text(), 'Genre')
        model = drop_down.get_model()
        self.assertEqual([model.get_string(n) for n in range(model.get_n_items())],
                         ['All Genres', 'Invented Rock', 'Invented Folk'])
        self.assertEqual((drop_down.get_selected(), asked), (0, [None]))
        drop_down.set_selected(2)
        self.assertEqual(menu.genre, '22')
        # Started over: the other genre's shelves, not the old ones while it is asked.
        self.assertTrue(await self.until_frames(page, lambda: [
            widget.shelf.title for widget in page._column.widgets if widget.get_visible()]
            == ['Top Songs 22']))
        self.assertEqual(asked, [None, '22'])
        self.assertEqual(self.app.engine.calls.count('genres'), 1)  # read once
        page.refresh()
        await self.settle()
        self.assertEqual(asked, [None, '22', '22'])  # Refresh asks for the genre shown
        drop_down.set_selected(0)
        await self.all_shelves(page)
        self.assertEqual(asked, [None, '22', '22', None])

    async def test_a_genre_that_fails_says_so_rather_than_the_old_shelves(self):
        def charts(genre, refresh):
            return EngineError('api') if genre else answer()

        self.app.engine.answers['charts'] = charts
        self.app.engine.answers['genres'] = GENRES
        page = await self.charts_page()
        await self.all_shelves(page)
        page.genre_menu.drop_down.set_selected(1)
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'status'))
        self.assertEqual(self.app.reported, [])  # the page says it: no toast

    async def test_a_link_to_a_genres_charts_opens_on_it(self):
        from applemusic.pages import charts

        asked = []
        self.app.engine.answers['charts'] = lambda genre, refresh: (
            asked.append(genre) or genre_answer(genre))
        self.app.engine.answers['genres'] = GENRES
        page = await self.push(charts.create(charts_link('21')))
        await self.settle()
        self.assertEqual(asked, ['21'])
        self.assertEqual(page.title_label.get_label(), 'Top Charts')
        drop_down = page.genre_menu.drop_down
        self.assertEqual(drop_down.get_selected_item().get_string(), 'Invented Rock')

    async def test_a_link_to_the_root_genres_charts_opens_all_genres(self):
        from applemusic.pages import charts

        asked = []
        self.app.engine.answers['charts'] = lambda genre, refresh: (
            asked.append(genre) or answer())
        self.app.engine.answers['genres'] = GENRES
        page = await self.push(charts.create(charts_link(ROOT_GENRE, 'Charts')))
        await self.settle()
        self.assertEqual(asked, [None])  # every genre's, with the Daily Top 100
        model = page.genre_menu.drop_down.get_model()
        self.assertEqual([model.get_string(n) for n in range(model.get_n_items())],
                         ['All Genres', 'Invented Rock', 'Invented Folk'])
        self.assertEqual(page.genre_menu.drop_down.get_selected(), 0)

    async def test_a_links_genre_shows_under_its_words_while_the_genres_cannot_be_read(self):
        from applemusic.pages import charts

        self.app.engine.answers['charts'] = lambda genre, refresh: genre_answer(genre)
        page = await self.push(charts.create(charts_link('24', 'Invented Jazz Charts')))
        await self.settle()
        drop_down = page.genre_menu.drop_down
        self.assertTrue(drop_down.get_visible())
        self.assertEqual(drop_down.get_selected_item().get_string(), 'Invented Jazz Charts')
        drop_down.set_selected(0)
        self.assertEqual(page.genre_menu.genre, '')

    async def test_no_charts(self):
        self.app.engine.answers['charts'] = {'shelves': []}
        page = await self.charts_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_title(), 'No Charts')


class NewPageTest(PageTestCase):
    """New ends with More to Explore, whose Top Charts link opens the Charts page when
    Apple's links have none to the charts."""

    async def test_more_to_explore_follows_the_shelves_and_opens_the_charts(self):
        from applemusic.pages import new
        from applemusic.sections import Destination
        from applemusic.widgets.explore import ExploreBox, LinkChild

        self.app.engine.answers['browse'] = {'shelves': [
            {'key': f'new-{n}', 'title': f'Invented Shelf {n}',
             'items': [dict(album(i, tracks=0), id=f'n{n}.{i}') for i in range(3)]}
            for n in range(3)]}
        page = await self.show_root(new.create(Destination('new', 'New',
                                                            'view-grid-symbolic')))
        await self.settle()
        self.assertTrue(await self.until(lambda: len(page._column.widgets) == 3, timeout=3))
        last = page.shelves_box.get_last_child()
        self.assertIsInstance(last, ExploreBox)
        self.assertIs(last.get_prev_sibling(), page._column.widgets[-1])  # after them all
        section = last.get_first_child()
        title, links = section.get_first_child(), section.get_last_child()
        self.assertEqual(title.get_label(), 'More to Explore')
        child = links.get_child_at_index(0)
        self.assertIsInstance(child, LinkChild)
        self.assertEqual(child.item.title, 'Top Charts')
        links.emit('child-activated', child)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('charts', 'charts')])


if __name__ == '__main__':
    unittest.main()
