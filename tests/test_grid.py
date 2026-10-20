# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The grid pages (pages/grid.py): their columns, their sort orders and the Sort By menu, the
title in the header bar, and a folder that is gone."""

import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.page_harness import PageTestCase, album, artist

from applemusic.pages import estimate_width


class EstimateWidthTest(unittest.TestCase):
    def test_the_default_width_less_the_sidebar(self):
        self.assertEqual(estimate_width(1100, False, 1920, 280), 820)

    def test_maximized_takes_the_monitors_width(self):
        self.assertEqual(estimate_width(1100, True, 1920, 280), 1640)

    def test_a_collapsed_sidebar_takes_nothing(self):
        self.assertEqual(estimate_width(360, False, 1920, 0), 360)

    def test_no_monitor_known_keeps_the_default(self):
        self.assertEqual(estimate_width(1100, True, 0, 280), 820)


class GridTest(PageTestCase):
    def test_columns_for(self):
        from applemusic.pages.grid import columns_for

        # The content pane at 700, 1100 and 1920 px wide.
        self.assertEqual(columns_for(700), 4)
        self.assertEqual(columns_for(1100), 6)
        self.assertEqual(columns_for(1920), 11)
        self.assertEqual(columns_for(200), 2)  # never fewer

    def test_video_columns_fit_their_tile(self):
        from applemusic.pages.grid import COLUMN_WIDTH, VIDEO_COLUMN_WIDTH, columns_for
        from applemusic.widgets.tile import ART_SIZE, GRID_VIDEO_SIZE

        # A tile and the 3 px a side Adwaita pads a grid view's child with.
        self.assertEqual(COLUMN_WIDTH, ART_SIZE + 6)
        self.assertEqual(VIDEO_COLUMN_WIDTH, GRID_VIDEO_SIZE[0] + 6)
        self.assertAlmostEqual(GRID_VIDEO_SIZE[0] / GRID_VIDEO_SIZE[1], 16 / 9, delta=0.01)
        # Inside the grid's margins: the default window's content pane (820 px less 42), a
        # middle width, a maximized 1920 px one's.
        self.assertEqual(778 // VIDEO_COLUMN_WIDTH, 3)
        self.assertEqual(600 // VIDEO_COLUMN_WIDTH, 2)
        self.assertEqual(1598 // VIDEO_COLUMN_WIDTH, 6)
        self.assertEqual(332 // VIDEO_COLUMN_WIDTH, 1)  # 360 px, its 14 px margins
        self.assertEqual(columns_for(360, VIDEO_COLUMN_WIDTH), 2)  # never fewer

    def test_first_tiles(self):
        from applemusic.pages.grid import first_tiles

        # The rows a 700 px pane shows (four of 220, the last in part) and one more.
        self.assertEqual(first_tiles(4, 700), 20)
        self.assertEqual(first_tiles(6, 220), 12)
        self.assertIsNone(first_tiles(None, 700))  # no window: every item at once
        self.assertIsNone(first_tiles(4, 0))

    def _limited_page(self, count, **options):
        """A GridPage of `count` albums made while the window says its content pane fits four
        columns and is 300 px tall: it shows two rows and one more at first."""
        from unittest import mock

        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages import grid
        from applemusic.pages.grid import GridPage

        for name, value in (('estimate_columns', 4), ('estimate_height', 300)):
            patcher = mock.patch.object(grid, name, lambda *_args, value=value: value)
            patcher.start()
            self.addCleanup(patcher.stop)
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(album(n, year=1990 + n % 30)) for n in range(count)])
        return GridPage(self.library, 'Invented Grid', store, **options)

    async def test_the_first_frame_makes_the_rows_in_view_and_the_rest_come_after(self):
        page = self._limited_page(200)
        model = page.grid_view.get_model()
        self.assertEqual(model.get_n_items(), 12)
        await self.show_root(page)
        # 16 more a frame from the frame after the first tiles' (GROW_TILES).
        self.assertTrue(await self.until_frames(page.grid_view,
                                                lambda: model.get_n_items() == 200, frames=30))
        self.assertEqual(model.get_item(199).title, page._shown.get_item(199).title)

    async def test_a_filter_shows_every_match_at_once(self):
        # Hidden, the grid gets no frames to grow in: the filter lets every match in itself,
        # as the grid's rows recycled for the matches need them (ShownModel.replacing).
        page = self._limited_page(200, filter_words=('Filter Albums', lambda shown, total: ''))
        model = page.grid_view.get_model()
        self.assertEqual(model.get_n_items(), 12)
        page.filter_bar.set_text('Invented')
        self.assertTrue(await self.until(lambda: model.get_n_items() == 200))

    async def test_a_grid_of_albums_decodes_covers_at_the_size_drawn(self):
        # Every grid tile is made with GRID_VIDEO_SIZE; an album's square cover is still
        # asked for at ART_SIZE times the scale factor, not the frame's height (#399).
        from unittest import mock

        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets import artwork
        from applemusic.widgets.tile import ART_SIZE
        from tests.test_artwork import FakeLoader

        loader = FakeLoader()
        patcher = mock.patch.object(artwork, '_default', loader)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(dict(album(n), thumb=f'/cache/thumb/a{n}.jpg'))
                            for n in range(6)])
        page = await self.show_root(GridPage(self.library, 'Invented Albums', store))
        self.assertTrue(await self.until(lambda: loader.requests))
        self.assertEqual({size for _path, size in loader.requests},
                         {ART_SIZE * page.get_scale_factor()})

    async def test_a_grid_of_videos_shows_16_9_tiles(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets.tile import GRID_VIDEO_SIZE, Tile
        from tests.page_harness import find_all

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item({'id': f'i.mv{n}', 'kind': 'video', 'title': f'Video {n}',
                                  'subtitle': 'Invented Artist'}) for n in range(6)])
        page = await self.show_root(GridPage(self.library, 'Invented Videos', store,
                                             video=True))

        def tiles():
            return [tile for tile in find_all(page.grid_view, Tile)
                    if tile.context_item is not None]

        self.assertTrue(await self.until(lambda: tiles() and tiles()[0].cover.get_width()))
        self.assertTrue(all(tile.shape == 'video' for tile in tiles()))
        self.assertEqual(page.grid_view.get_min_columns(), 1)  # one fits a 360 px window
        cover = tiles()[0].cover
        self.assertEqual((cover.get_width(), cover.get_height()), GRID_VIDEO_SIZE)
        # 1000 px: four columns of 246 at most (three fit inside the margins).
        self.assertTrue(await self.until(lambda: page.grid_view.get_max_columns() == 4))

    async def test_the_title_and_the_first_cover_sit_on_the_margin(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets.tile import Tile
        from tests.page_harness import find_all

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(album(n)) for n in range(12)])
        page = await self.show_root(GridPage(self.library, 'Invented Grid', store))

        def x_of(widget):
            return widget.compute_bounds(page.overlay)[1].get_x()

        def first_cover_x():
            return min((x_of(tile.cover) for tile in find_all(page.grid_view, Tile)),
                       default=None)

        # The page is 1000 px wide: five columns in the 958 inside the margins, each wider
        # than a tile, the tile at the start of its cell, so the first cover and the title
        # are both 24 px in, as Home's title is.
        self.assertTrue(await self.until(lambda: first_cover_x() == 24))
        self.assertEqual(x_of(page.title_label), 24)

    def test_grid_sorts(self):
        from gi.repository import Gio, Gtk

        from applemusic.library import Item
        from applemusic.pages.grid import SORTS, make_sorter

        items = [Item(dict(album(0), title='B', subtitle='Zed', year=2001)),
                 Item(dict(album(1), title='A', subtitle='Zed', year=1999)),
                 Item(dict(album(2), title='C', subtitle='Abe', year=0)),
                 Item(dict(album(3), title='D', subtitle='Abe', year=2020)),
                 Item(dict(album(4), title='E', subtitle='Abe', year=2001))]
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)

        def titles(key, descending=False):
            sorter, backwards = make_sorter(key, descending)
            model = Gtk.SortListModel(model=store, sorter=sorter)
            order = [model.get_item(n).title for n in range(model.get_n_items())]
            return order[::-1] if backwards else order

        self.assertEqual(titles('title'), ['A', 'B', 'C', 'D', 'E'])
        self.assertEqual(titles('title', descending=True), ['E', 'D', 'C', 'B', 'A'])
        # By artist, then year (unknown first), then title; Z to A is that backwards.
        self.assertEqual(titles('artist'), ['C', 'E', 'D', 'A', 'B'])
        self.assertEqual(titles('artist', descending=True), ['B', 'A', 'D', 'E', 'C'])
        # Year's own direction is newest first, an unknown year last, the titles A to Z
        # within a year; ascending turns the years round and leaves the titles.
        self.assertTrue(SORTS['year'][2])
        self.assertEqual(titles('year', descending=True), ['D', 'B', 'E', 'A', 'C'])
        self.assertEqual(titles('year'), ['C', 'A', 'B', 'E', 'D'])

    def test_a_shown_model_maps_positions_and_changes(self):
        from gi.repository import Gtk

        from applemusic.widgets.filter_bar import ShownModel

        strings = Gtk.StringList.new(['a', 'b', 'c'])
        model = ShownModel(strings)
        changes = []
        model.connect('items-changed', lambda _model, *change: changes.append(change))

        def shown():
            return [model.get_item(n).get_string() for n in range(model.get_n_items())]

        self.assertEqual(shown(), ['a', 'b', 'c'])
        model.set_backwards(True)
        self.assertEqual(shown(), ['c', 'b', 'a'])
        self.assertEqual(changes, [(0, 3, 3)])
        model.set_backwards(True)  # as it is: nothing changes
        self.assertEqual(changes, [(0, 3, 3)])
        strings.splice(1, 1, ['x', 'y'])  # a, x, y, c: shown as c, y, x, a
        self.assertEqual(shown(), ['c', 'y', 'x', 'a'])
        self.assertEqual(changes[-1], (1, 1, 2))
        model.set_backwards(False)
        self.assertEqual(shown(), ['a', 'x', 'y', 'c'])

    async def test_the_sort_menu_sorts_and_is_remembered_by_page(self):
        from gi.repository import Gio, GLib

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(album(n, year=1990 + n)) for n in range(6)])
        self.addCleanup(self.app.settings.reset, 'grid-sort')
        page = GridPage(self.library, 'Invented Grid', store, sorts=('title', 'year'))
        page.set_tag('albums')
        await self.show_root(page)
        self.assertTrue(page.sort_button.get_visible())
        page.activate_action('page.sort', GLib.Variant('s', 'year'))
        model = page.grid_view.get_model()
        self.assertEqual(model.get_item(0).title, 'Invented Album 005')  # newest first
        self.assertEqual(page._order_action.get_state().get_string(), 'descending')
        self.assertEqual(self.app.settings.get_value('grid-sort').unpack(), {'albums': 'year'})
        # The direction turns the order; a key chosen comes its own way round (Title A to Z).
        page.activate_action('page.sort-order', GLib.Variant('s', 'ascending'))
        self.assertEqual(model.get_item(0).title, 'Invented Album 000')
        page.activate_action('page.sort', GLib.Variant('s', 'title'))
        self.assertEqual(model.get_item(0).title, 'Invented Album 000')
        self.assertEqual(page._order_action.get_state().get_string(), 'ascending')
        page.activate_action('page.sort-order', GLib.Variant('s', 'descending'))
        self.assertEqual(model.get_item(0).title, 'Invented Album 005')
        self.assertEqual(self.app.settings.get_value('grid-sort').unpack(), {'albums': 'title'})
        page.activate_action('page.sort', GLib.Variant('s', 'year'))

        self.window.navigation_view.replace([self.window.root_page])  # one page a tag
        self.window.navigation_view.remove(page)
        self._roots.remove(page)
        again = GridPage(self.library, 'Invented Grid', store, sorts=('title', 'year'))
        again.set_tag('albums')
        await self.show_root(again)
        self.assertEqual(again.grid_view.get_model().get_item(0).title, 'Invented Album 005')

    def test_date_added_is_newest_first(self):
        from gi.repository import Gio, Gtk

        from applemusic.library import Item
        from applemusic.pages.grid import SORTS, make_sorter

        items = [Item(dict(album(0), title='B', added='2026-01-01T10:00:00Z')),
                 Item(dict(album(1), title='A', added='2026-01-01T10:00:00Z')),
                 Item(dict(album(2), title='C', added='2026-03-01T09:00:00Z')),
                 Item(dict(album(3), title='D'))]
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)

        def titles(descending):
            sorter, backwards = make_sorter('added', descending)
            model = Gtk.SortListModel(model=store, sorter=sorter)
            self.assertFalse(backwards)  # a number: its sorter takes the direction
            return [model.get_item(n).title for n in range(model.get_n_items())]

        self.assertTrue(SORTS['added'][2])
        # To the second, ties by title A to Z, an unknown date last.
        self.assertEqual(titles(True), ['C', 'A', 'B', 'D'])
        self.assertEqual(titles(False), ['D', 'A', 'B', 'C'])

    async def test_favourites_only_filters_and_is_remembered(self):
        from gi.repository import Gio, GLib

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        items = [Item(album(n)) for n in range(6)]
        items[1].favourite = items[4].favourite = True
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)
        self.addCleanup(self.app.settings.reset, 'favourites-only')

        def make():
            page = GridPage(self.library, 'Invented Grid', store, sorts=('title', 'added'),
                            favourites=('No Favourite Albums', 'Invented words'))
            page.set_tag('albums')
            return page

        page = await self.show_root(make())
        self.assertEqual(page.sort_button.get_tooltip_text(), 'Sort and Filter')
        model = page.grid_view.get_model()
        self.assertEqual(model.get_n_items(), 6)
        page.activate_action('page.favourites-only', None)  # the check item
        self.assertTrue(page._favourites_action.get_state().get_boolean())
        self.assertEqual([model.get_item(n).id for n in range(model.get_n_items())],
                         [items[1].id, items[4].id])
        self.assertEqual(self.app.settings.get_strv('favourites-only'), ['albums'])
        # Unfavourited (a sync, a heart): the library says so, and the filter looks again;
        # none left, the page says so and keeps its button, to turn the filter off.
        items[1].favourite = items[4].favourite = False
        self.library.emit('favourites-changed')
        self.assertEqual(model.get_n_items(), 0)
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'No Favourite Albums')
        self.assertTrue(page.sort_button.get_visible())
        items[4].favourite = True
        self.library.emit('favourites-changed')
        self.assertEqual(model.get_n_items(), 1)
        # A page made again for the tag shows the favourites only, as it was left.
        self.window.navigation_view.replace([self.window.root_page])
        self.window.navigation_view.remove(page)
        self._roots.remove(page)
        again = await self.show_root(make())
        self.assertEqual(again.grid_view.get_model().get_n_items(), 1)
        again.activate_action('page.favourites-only', None)
        self.assertEqual(again.grid_view.get_model().get_n_items(), 6)
        self.assertEqual(self.app.settings.get_strv('favourites-only'), [])
        again.activate_action('page.sort', GLib.Variant('s', 'title'))

    async def filter_grid(self, count):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        items = [Item(album(n)) for n in range(count)]
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)
        page = GridPage(self.library, 'Invented Grid', store, sorts=('title', 'artist'),
                        icon_name='media-optical-cd-audio-symbolic',
                        filter_words=('Filter Albums', lambda shown, total: '{shown} of {total}'))
        await self.show_root(page)
        return page, items

    async def test_escape_from_the_filter_puts_the_focus_back_on_the_tile_it_was_on(self):
        # The grid's own focus would be a recycled tile out of view, bound to another album.
        page, items = await self.filter_grid(90)
        grid = page.grid_view
        # A filter that leaves the album out, one that leaves some albums, and none.
        self.assertTrue(await self.escape_from_filter(page, grid, items[80], 'album 00'),
                        self.window.get_focus())
        self.assertTrue(await self.escape_from_filter(page, grid, items[85], 'album 08'))
        self.assertTrue(await self.escape_from_filter(page, grid, items[70], 'nothing'),
                        self.window.get_focus())
        # From outside the grid (its filter's button), the first album.
        page.filter_bar.button.grab_focus()
        self.assertTrue(page.focus_filter())
        self.assertTrue(await self.until_focused(page.filter_bar.entry))
        page.filter_bar.set_text('album 08')
        await self.turn()
        page.filter_bar.entry.emit('stop-search')
        self.assertTrue(await self.until(lambda: self.focused_in(grid) is items[0]),
                        self.window.get_focus())

    async def test_the_filter_bar_filters_by_title_and_artist_with_favourites_only(self):
        from gi.repository import Gdk, Gio, GLib, Gtk

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        items = [Item(dict(album(n), title=title, subtitle=artist))
                 for n, (title, artist) in enumerate([
                     ('Harbour Café', 'Aura Invented'), ('Dawn Lines', 'Zephyr'),
                     ('Night Harbour', 'Lines Collective'), ('Quiet', 'Ça Invented')])]
        items[2].favourite = True
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)
        self.addCleanup(self.app.settings.reset, 'favourites-only')
        said = []
        self.window.announce = lambda text, _priority: said.append(text)
        self.addCleanup(delattr, self.window, 'announce')
        page = GridPage(self.library, 'Invented Grid', store, sorts=('title', 'artist'),
                        icon_name='media-optical-cd-audio-symbolic',
                        favourites=('No Favourite Albums', 'Invented words'),
                        filter_words=('Filter Albums', lambda shown, total: '{shown} of {total}'))
        page.set_tag('albums')
        await self.show_root(page)
        model = page.grid_view.get_model()

        def titles():
            return [model.get_item(n).title for n in range(model.get_n_items())]

        bar = page.filter_bar
        self.assertIsNotNone(bar)
        self.assertTrue(bar.button.get_visible())
        self.assertIs(bar.get_key_capture_widget(), page)  # typing on the page starts it
        self.assertTrue(page.focus_filter())  # Ctrl+F
        self.assertTrue(await self.until_focused(bar.entry))
        self.assertTrue(bar.get_search_mode())
        bar.set_text('harbour')  # titles, in the order chosen
        self.assertEqual(titles(), ['Harbour Café', 'Night Harbour'])
        self.assertEqual(said[-1], '2 of 4')
        bar.set_text('lines')  # a title and an artist
        self.assertEqual(titles(), ['Dawn Lines', 'Night Harbour'])
        page.activate_action('page.sort-order', GLib.Variant('s', 'descending'))
        self.assertEqual(titles(), ['Night Harbour', 'Dawn Lines'])  # still filtered
        page.activate_action('page.sort-order', GLib.Variant('s', 'ascending'))
        bar.set_text('ca invented')  # accents and case ignored
        self.assertEqual(titles(), ['Quiet'])
        # With Favourites Only: both apply.
        page.activate_action('page.favourites-only', None)
        self.assertEqual(titles(), [])
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'No Results Found')
        self.assertEqual(page.empty_page.get_icon_name(), 'edit-find-symbolic')
        self.assertTrue(bar.button.get_visible())  # to change it
        self.assertTrue(page.sort_button.get_visible())
        bar.set_text('harbour')
        self.assertEqual(titles(), ['Night Harbour'])
        bar.close()  # Escape, the button: the filter goes, Favourites Only stays
        self.assertTrue(await self.until(lambda: bar.search == ''))
        self.assertEqual(titles(), ['Night Harbour'])
        items[2].favourite = False
        self.library.emit('favourites-changed')
        self.assertEqual(page.empty_page.get_title(), 'No Favourite Albums')  # not the text
        self.assertEqual(page.empty_page.get_icon_name(), 'media-optical-cd-audio-symbolic')
        page.activate_action('page.favourites-only', None)
        self.assertEqual(len(titles()), 4)
        # Escape from the grid closes it and returns the focus to the grid.
        bar.set_text('dawn')
        escape = next(controller for controller in page.observe_controllers()
                      if isinstance(controller, Gtk.EventControllerKey))
        self.assertTrue(escape.emit('key-pressed', Gdk.KEY_Escape, 0, Gdk.ModifierType(0)))
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.grid_view)))
        self.assertEqual(len(titles()), 4)

    async def test_a_filter_change_recycles_the_tiles(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets import tile

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(dict(album(n), title=f'{n:03d} {"Even" if n % 2 else "Odd"}'))
                            for n in range(600)])
        page = GridPage(self.library, 'Invented Grid', store, sorts=('title',),
                        filter_words=('Filter Albums', lambda shown, total: ''))
        await self.show_root(page)
        await self.turn()
        made = []
        init = tile.Tile.__init__

        def counting(self, *args, **kwargs):
            made.append(True)
            init(self, *args, **kwargs)

        tile.Tile.__init__ = counting
        self.addCleanup(setattr, tile.Tile, '__init__', init)
        page.filter_bar.set_text('even')  # most tiles shown change their album
        await self.turn()
        self.assertEqual(page.grid_view.get_model().get_n_items(), 300)
        self.assertLess(len(made), 6)  # rebound, not built again

    async def test_a_page_without_filter_words_has_none(self):
        from gi.repository import Gio

        from applemusic import keyboard
        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(album(n)) for n in range(3)])
        page = await self.show_root(GridPage(self.library, 'Invented Grid', store))
        self.assertIsNone(page.filter_bar)
        self.assertFalse(page.focus_filter())
        self.assertEqual(keyboard.search_target(page), 'search')

    async def test_an_empty_library_offers_no_filter(self):
        from applemusic import keyboard, pages
        from applemusic.sections import sidebar_sections

        destinations = {destination.key: destination
                        for section in sidebar_sections() for destination in section.destinations}
        for key in ('albums', 'music-videos', 'artists', 'songs'):
            page = await self.show_root(pages.create(destinations[key], self.library))
            await self.turn()
            self.assertFalse(page.filter_bar.button.get_visible(), key)
            self.assertFalse(page.focus_filter(), key)
            self.assertEqual(keyboard.search_target(page), 'search', key)

    async def test_date_added_is_offered_only_with_dates(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item({'id': f'i.mv{n}', 'kind': 'video', 'title': f'Video {n}'})
                            for n in range(3)])
        page = await self.show_root(GridPage(self.library, 'Invented Videos', store,
                                             video=True, sorts=('title', 'artist'),
                                             data_sorts=('added',)))
        keys = page._keys_menu
        self.assertEqual(keys.get_n_items(), 2)  # Title, Artist: Apple dated none
        store.append(Item({'id': 'i.mv9', 'kind': 'video', 'title': 'Video 9',
                           'added': '2026-01-01T00:00:00Z'}))
        self.library.emit('changed')  # a sync brought dates
        self.assertEqual(keys.get_n_items(), 3)
        self.assertEqual(page._sort_keys, ('title', 'artist', 'added'))

    async def test_the_header_shows_the_title_only_while_the_big_one_is_away(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        store = Gio.ListStore(item_type=Item)
        page = await self.push(GridPage(self.library, 'Invented Grid', store, root=False))
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertTrue(await self.until(page.header_bar.get_show_title))
        store.splice(0, 0, [Item(album(n)) for n in range(60)])
        self.assertTrue(await self.until(lambda: not page.header_bar.get_show_title()))
        page.scrolled_window.get_vadjustment().set_value(400)
        self.assertTrue(await self.until(page.header_bar.get_show_title))

    async def test_a_folder_that_is_gone_says_so(self):
        from applemusic.pages import folder

        page = await self.show_root(folder(self.library, 'l.gone', 'Invented Folder'))
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'Folder Not Found')



class FirstSyncTest(PageTestCase):
    """While the first sync fills an empty library, the pages are on their way, not empty."""

    async def test_home_albums_and_songs_show_loading_during_the_first_sync(self):
        from applemusic import pages
        from applemusic.sections import sidebar_sections

        destinations = {destination.key: destination
                        for section in sidebar_sections() for destination in section.destinations}
        self.library.syncing = True  # an empty library ('empty'), the first sync running
        shown = {}
        for key in ('home', 'albums', 'songs'):
            page = await self.show_root(pages.create(destinations[key], self.library))
            await self.turn()
            shown[key] = page.stack.get_visible_child_name()
        self.assertEqual(shown, dict.fromkeys(shown, 'loading'))

        self.library.syncing = False  # it ended with nothing: empty
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')


SIGNED_OUT = 'Sign in to Apple Music to see your library'


def offer(page):
    """The Sign In… button on a page's empty state (pages.SignInOffer's)."""
    return page.empty_page.get_child()


class SignInOfferTest(PageTestCase):
    """A library page's empty state while signed out (pages.SignInOffer): Sign In… and what
    signing in does; the page's own words once signed in, and in the demo."""

    async def empty_grid(self):
        from gi.repository import Gio

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage

        page = GridPage(self.library, 'Albums', Gio.ListStore(item_type=Item),
                        empty_title='No Albums',
                        empty_description='Albums in your library appear here')
        await self.show_root(page)
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        return page

    async def test_signed_out_offers_sign_in_and_says_what_it_does(self):
        self.app.settings.set_boolean('signed-in', False)
        page = await self.empty_grid()
        button = offer(page)
        self.assertTrue(button.get_visible())
        self.assertEqual(button.get_label(), 'Sign In…')
        self.assertEqual(button.get_action_name(), 'app.sign-in')
        self.assertTrue(button.has_css_class('pill'))
        self.assertTrue(button.has_css_class('suggested-action'))
        self.assertEqual(page.empty_page.get_title(), 'No Albums')
        self.assertEqual(page.empty_page.get_description(), SIGNED_OUT)
        # Signed in: the page's own words, no button (a first sync is the loading state).
        self.app.settings.set_boolean('signed-in', True)
        self.assertFalse(button.get_visible())
        self.assertEqual(page.empty_page.get_description(), 'Albums in your library appear here')

    async def test_the_demo_has_no_account_to_sign_in_to(self):
        self.app.demo = True
        self.app.settings.set_boolean('signed-in', False)
        page = await self.empty_grid()
        self.assertFalse(offer(page).get_visible())
        self.assertEqual(page.empty_page.get_description(), 'Albums in your library appear here')

    async def test_a_page_shown_again_catches_up(self):
        page = await self.empty_grid()
        self.assertFalse(offer(page).get_visible())
        self.window.navigation_view.replace([self.window.root_page])  # hidden: not following
        self.assertTrue(await self.until(lambda: not page.get_mapped()))
        self.app.settings.set_boolean('signed-in', False)
        self.assertFalse(offer(page).get_visible())
        self.window.navigation_view.replace([page])
        self.assertTrue(await self.until(page.get_mapped))
        self.assertTrue(offer(page).get_visible())
        self.assertEqual(page.empty_page.get_description(), SIGNED_OUT)

    async def test_every_library_page_offers_it(self):
        from applemusic import pages
        from applemusic.sections import sidebar_sections

        self.app.settings.set_boolean('signed-in', False)
        destinations = {destination.key: destination
                        for section in sidebar_sections() for destination in section.destinations}
        offered = {}
        for key in ('home', 'albums', 'artists', 'recently-added', 'songs',
                    'all-playlists', 'favourite-songs', 'music-videos'):
            page = await self.show_root(pages.create(destinations[key], self.library))
            await self.turn()
            self.assertEqual(page.stack.get_visible_child_name(), 'empty', key)
            offered[key] = (offer(page).get_visible(), page.empty_page.get_description())
        self.assertEqual(offered, dict.fromkeys(offered, (True, SIGNED_OUT)))


class SortMenuTest(PageTestCase):
    async def test_every_sort_menu_item_has_a_mnemonic_of_its_own(self):
        """Sort By and Sort and Filter, on every page that has one: each item has a
        mnemonic, none two in one menu (F is Favourites Only)."""
        from gi.repository import Gio

        from applemusic import pages
        from applemusic.library import Item
        from applemusic.pages.library_artist import LibraryArtistPage
        from applemusic.sections import sidebar_sections

        def labels(menu):
            found = []
            for position in range(menu.get_n_items()):
                section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
                if section is not None:
                    found.extend(labels(section))
                else:
                    found.append(menu.get_item_attribute_value(
                        position, Gio.MENU_ATTRIBUTE_LABEL).unpack())
            return found

        destinations = {destination.key: destination
                        for section in sidebar_sections() for destination in section.destinations}
        menus = {key: pages.create(destinations[key], self.library).sort_button.get_menu_model()
                 for key in ('albums', 'songs', 'music-videos', 'recently-added',
                             'all-playlists')}
        band = Item(artist([album(1)]))
        menus['library-artist'] = LibraryArtistPage(self.library, band).sort_button \
            .get_menu_model()
        for key, menu in menus.items():
            with self.subTest(page=key):
                found = labels(menu)
                self.assertTrue(all('_' in label for label in found), found)
                letters = [label[label.index('_') + 1].lower() for label in found]
                self.assertEqual(len(letters), len(set(letters)), found)
        self.assertIn('_Favourites Only', labels(menus['albums']))
        self.assertIn('Date A_dded', labels(menus['albums']))
        self.assertIn('_Favourites Only', labels(menus['songs']))
        self.assertEqual(labels(menus['recently-added']), ['Asc_ending', 'Desce_nding'])


if __name__ == '__main__':
    unittest.main()
