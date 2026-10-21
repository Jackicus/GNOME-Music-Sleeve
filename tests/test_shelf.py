# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/shelf.py: a Shelf follows its shelf and offers See All and the paging arrows only
when the row does not show everything (at any width: the row shows no scrollbar, and still
scrolls sideways and to the focus); a ShelfColumn keeps the
widgets of the shelves it keeps, and never shows a shelf twice while it binds the rest a frame
apart, each in its form (a grid of songs for a chart's Top Songs); a chart's shelves number
their tiles and songs."""

import unittest

from tests.page_harness import PageTestCase, album


def model(key, count, title=None):
    from applemusic.library import Item, ShelfModel

    items = [Item(dict(album(n), id=f'{key}.{n}')) for n in range(count)]
    return ShelfModel(key, title or f'Invented {key}', items)


class ShelfTest(PageTestCase):
    async def shown(self, shelf_model, width=None, **options):
        """A Shelf of shelf_model shown in the window, `width` pixels wide (or the window's
        width)."""
        from gi.repository import Adw

        from applemusic.widgets.shelf import Shelf

        shelf = Shelf(see_all=True, **options)
        shelf.bind_shelf(shelf_model)
        if width is None:
            self.window.root_box.append(shelf)
        else:
            self.window.root_box.append(Adw.Clamp(maximum_size=width,
                                                  tightening_threshold=width, child=shelf))
        adjustment = shelf.scrolled_window.get_hadjustment()
        self.assertTrue(await self.until(lambda: adjustment.get_page_size() > 0))
        await self.turn()
        return shelf

    async def test_a_mixed_row_shapes_each_tile_by_its_kind(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.tile import ART_SIZE, VIDEO_WIDTH, Tile
        from tests.page_harness import find_all

        items = [Item(album(0)),
                 Item({'id': 'i.mv1', 'kind': 'video', 'title': 'Invented Video',
                       'subtitle': 'Invented Artist'}),
                 Item({'id': 'r1', 'kind': 'artist', 'title': 'Invented Artist'})]
        shelf = await self.shown(ShelfModel('mixed', 'Invented Mix', items))
        tiles = {tile.context_item.kind: tile for tile in find_all(shelf.list_view, Tile)
                 if tile.context_item is not None}
        self.assertEqual({kind: tile.shape for kind, tile in tiles.items()},
                         {'album': 'cover', 'video': 'video', 'artist': 'artist'})
        self.assertTrue(await self.until(lambda: tiles['video'].cover.get_width() > 0))
        self.assertEqual(tiles['video'].cover.get_width(), VIDEO_WIDTH)
        self.assertEqual(tiles['video'].cover.get_height(), ART_SIZE)
        self.assertEqual(tiles['album'].cover.get_height(), ART_SIZE)

    async def test_album_and_playlist_tiles_are_drag_sources(self):
        # Onto a sidebar playlist (their songs added) or the player bar (queued); an
        # artist's tile drags nowhere.
        from gi.repository import Graphene, Gtk

        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.tile import Tile
        from tests.page_harness import find_all

        items = [Item(album(0)),
                 Item({'id': 'p.pl1', 'kind': 'playlist', 'title': 'Invented Playlist'}),
                 Item({'id': 'r1', 'kind': 'artist', 'title': 'Invented Artist'})]
        shelf = await self.shown(ShelfModel('mixed', 'Invented Mix', items))
        view = shelf.list_view
        sources = [controller for controller in view.observe_controllers()
                   if isinstance(controller, Gtk.DragSource)]
        self.assertEqual(len(sources), 1)
        tiles = {tile.context_item.kind: tile for tile in find_all(view, Tile)
                 if tile.context_item is not None}
        for kind, draggable in (('album', True), ('playlist', True), ('artist', False)):
            tile = tiles[kind]
            ok, middle = tile.compute_point(view, Graphene.Point().init(
                tile.get_width() / 2, tile.get_height() / 2))
            self.assertTrue(ok)
            provider = sources[0].emit('prepare', middle.x, middle.y)
            self.assertEqual(provider is not None, draggable, kind)

    async def test_a_short_row_offers_no_see_all_nor_arrows(self):
        shelf = await self.shown(model('short', 1))
        self.assertFalse(shelf.see_all_button.get_visible())
        self.assertFalse(shelf.next_button.get_visible())

    async def test_a_long_row_shows_its_first_tiles_see_all_and_the_arrows(self):
        from applemusic.widgets.shelf import ROW_LIMIT

        shelf = await self.shown(model('long', 40))
        # Its first tiles at once, the rest a few a frame (give_items()).
        self.assertTrue(await self.until_frames(
            shelf.list_view, lambda: shelf.list_view.get_model().get_n_items() == ROW_LIMIT))
        self.assertTrue(shelf.see_all_button.get_visible())
        self.assertTrue(shelf.next_button.get_visible())
        self.assertFalse(shelf.previous_button.get_sensitive())  # at the start
        self.assertTrue(shelf.next_button.get_sensitive())
        shelf.next_button.emit('clicked')  # animations are off: at once
        adjustment = shelf.scrolled_window.get_hadjustment()
        self.assertTrue(await self.until(lambda: adjustment.get_value() > 0))
        self.assertTrue(shelf.previous_button.get_sensitive())
        shelf.see_all_button.emit('clicked')
        self.assertEqual(len(self.window.shelves_opened), 1)

    async def test_a_pages_glide_is_freed_once_done(self):
        # Adw.TimedAnimation.new() returns a reference PyGObject never drops: the shelf
        # makes its glide with the constructor, which a stand-in here records.
        import gc
        from unittest import mock

        from gi.repository import Adw

        made = []
        constructor = Adw.TimedAnimation

        def recorded(**properties):
            animation = constructor(**properties)
            made.append(animation.weak_ref())
            return animation

        shelf = await self.shown(model('long', 40))
        adjustment = shelf.scrolled_window.get_hadjustment()
        with mock.patch.object(Adw, 'TimedAnimation', recorded):
            shelf.next_button.emit('clicked')  # animations are off: done at once
        self.assertTrue(await self.until(lambda: adjustment.get_value() > 0))
        self.assertEqual(len(made), 1)
        self.assertTrue(await self.until(lambda: gc.collect() is not None
                                         and made[0]() is None))

    async def test_a_narrow_row_keeps_its_arrows_and_its_whole_title(self):
        # The row shows no scrollbar, so the arrows show at 360 px too; the title goes onto
        # a second line rather than being cut short.
        shelf = await self.shown(model('narrow', 40, title='Invented Rotations'), width=360)
        adjustment = shelf.scrolled_window.get_hadjustment()
        self.assertGreater(adjustment.get_upper(), adjustment.get_page_size())  # overflows
        self.assertTrue(shelf.see_all_button.get_visible())
        self.assertTrue(shelf.previous_button.get_visible())
        self.assertTrue(shelf.next_button.get_visible())
        self.assertFalse(shelf.title_label.get_layout().is_ellipsized())

    async def test_the_row_shows_no_scrollbar_but_scrolls(self):
        # EXTERNAL, not NEVER: the scrollbar the pointer kept landing on is gone, the row
        # still scrolls sideways (a touchpad, Shift and the wheel), and a vertical wheel
        # goes on to the page.
        from gi.repository import Gtk

        shelf = await self.shown(model('wheel', 40))
        scrolled = shelf.scrolled_window
        self.assertEqual(scrolled.get_policy(), (Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER))
        self.assertFalse(scrolled.get_hscrollbar().get_mapped())
        adjustment = scrolled.get_hadjustment()
        scroll = next(controller for controller in scrolled.observe_controllers()
                      if isinstance(controller, Gtk.EventControllerScroll)
                      and controller.get_propagation_phase() == Gtk.PropagationPhase.BUBBLE)
        self.assertFalse(scroll.emit('scroll', 0, 3))  # vertical: the page's
        self.assertEqual(adjustment.get_value(), 0)
        self.assertTrue(scroll.emit('scroll', 3, 0))
        self.assertTrue(await self.until(lambda: adjustment.get_value() > 0))
        self.assertTrue(shelf.previous_button.get_sensitive())

    def test_a_grid_of_songs_shows_no_scrollbar_either(self):
        from gi.repository import Gtk

        from applemusic.widgets.song_shelf import SongShelf

        self.assertEqual(SongShelf().scrolled_window.get_policy(),
                         (Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER))

    async def test_the_focus_moving_along_the_row_scrolls_it(self):
        from gi.repository import Gtk

        shelf = await self.shown(model('focus', 20), width=600)
        adjustment = shelf.scrolled_window.get_hadjustment()
        shelf.list_view.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
        shelf.list_view.grab_focus()
        for _ in range(8):
            self.assertTrue(shelf.list_view.child_focus(Gtk.DirectionType.RIGHT))
            await self.turn()
        focus = self.window.get_focus()
        self.assertTrue(await self.until(lambda: adjustment.get_value() > 0))
        found, bounds = focus.compute_bounds(shelf.scrolled_window)
        self.assertTrue(found)
        self.assertGreaterEqual(bounds.get_x(), 0)
        self.assertLessEqual(bounds.get_x() + bounds.get_width(),
                             shelf.scrolled_window.get_width())

    async def test_the_arrows_follow_the_ends_of_the_row(self):
        shelf = await self.shown(model('ends', 40), width=600)
        adjustment = shelf.scrolled_window.get_hadjustment()
        self.assertTrue(await self.until_frames(
            shelf.list_view, lambda: shelf._growing is None))
        self.assertFalse(shelf.previous_button.get_sensitive())
        self.assertTrue(shelf.next_button.get_sensitive())
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        self.assertTrue(shelf.previous_button.get_sensitive())
        self.assertFalse(shelf.next_button.get_sensitive())
        adjustment.set_value(adjustment.get_upper() / 2)
        self.assertTrue(shelf.previous_button.get_sensitive())
        self.assertTrue(shelf.next_button.get_sensitive())

    async def test_a_shelf_rebound_out_of_the_page_shows_its_arrows_once_back(self):
        # Home's first shelf: a ShelfColumn moves a kept widget into place, so it is
        # bound while out of the page, with no width of its own, and its row, as wide as
        # before, lays out again with the very adjustment it had: nothing changes then.
        # FIRST_TILES items, all given at once: a longer row grows a few tiles a frame
        # (give_items()), and its upper would change as they come.
        from applemusic.widgets.shelf import FIRST_TILES

        shelf = await self.shown(model('first', FIRST_TILES))
        self.assertIsNone(shelf._growing)
        self.assertTrue(shelf.next_button.get_visible())
        adjustment = shelf.scrolled_window.get_hadjustment()
        settled = adjustment.get_page_size(), adjustment.get_upper()
        self.window.root_box.remove(shelf)
        shelf.bind_shelf(model('second', FIRST_TILES))
        self.assertIsNone(shelf._growing)
        self.assertEqual(shelf.get_width(), 0)
        self.window.root_box.append(shelf)
        self.assertTrue(await self.until(lambda: shelf.get_width() > 0))
        await self.turn()
        self.assertTrue(await self.until_frames(
            shelf, lambda: (adjustment.get_page_size(), adjustment.get_upper()) == settled),
            (adjustment.get_page_size(), adjustment.get_upper()))
        self.assertTrue(shelf.previous_button.get_visible())
        self.assertTrue(shelf.next_button.get_visible())

    async def test_see_all_follows_the_items(self):
        shelf_model = model('growing', 1)
        shelf = await self.shown(shelf_model)
        self.assertFalse(shelf.see_all_button.get_visible())
        more = model('more', 39)
        shelf_model.update(shelf_model.title, [shelf_model.items.get_item(0)]
                           + list(more.items))
        self.assertTrue(await self.until(shelf.see_all_button.get_visible))

    async def test_a_retitled_shelf_updates_its_heading(self):
        shelf_model = model('titled', 3, title='Old Title')
        shelf = await self.shown(shelf_model)
        self.assertEqual(shelf.title_label.get_label(), 'Old Title')
        shelf_model.update('New Title', list(shelf_model.items))
        self.assertEqual(shelf.title_label.get_label(), 'New Title')

    async def test_a_reason_shows_under_the_title_while_there_is_one(self):
        shelf_model = model('reasoned', 3)
        shelf = await self.shown(shelf_model)
        self.assertFalse(shelf.subtitle_label.get_visible())
        shelf_model.update(shelf_model.title, list(shelf_model.items),
                           'Because you play invented folk')
        self.assertTrue(shelf.subtitle_label.get_visible())
        self.assertEqual(shelf.subtitle_label.get_label(), 'Because you play invented folk')
        shelf_model.update(shelf_model.title, list(shelf_model.items))
        self.assertFalse(shelf.subtitle_label.get_visible())


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


class ShelfColumnTest(PageTestCase):
    def column(self):
        from gi.repository import Gtk

        from applemusic.widgets.shelf import ShelfColumn

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.anchor = Gtk.Label(label='Invented Page')
        self.box.append(self.anchor)
        self.window.root_box.append(self.box)
        return ShelfColumn(self.box, anchor=self.anchor)

    def shown(self):
        """The shelves the box shows, in order."""
        shown = []
        child = self.anchor.get_next_sibling()
        while child is not None:
            if child.get_visible():
                shown.append(child.shelf)
            child = child.get_next_sibling()
        return shown

    async def test_a_reshow_keeps_widgets_never_shows_a_shelf_twice_and_hides_extras(self):
        column = self.column()
        shelves = [model(f's{n}', 2) for n in range(6)]
        column.show(shelves, hero_first=True)
        self.assertEqual(self.shown(), shelves[:3])  # the first few at once
        # The rest one a frame: three frames, the first of them slow on cold caches.
        self.assertTrue(await self.until_frames(self.box, lambda: self.shown() == shelves))
        widgets = {shelf: widget for shelf, widget in zip(shelves, column.widgets,
                                                          strict=True)}
        self.assertTrue(widgets[shelves[0]].props.hero)

        # A new shelf at position 1, and the last one gone.
        inserted = model('new', 2)
        again = [shelves[0], inserted] + shelves[1:5]
        column.show(again, hero_first=True)
        seen = []
        while True:
            shown = self.shown()
            seen.append(shown)
            self.assertEqual(len(shown), len(set(shown)), shown)  # never twice
            self.assertNotIn(shelves[5], shown)  # gone at once
            if shown == again:
                break
            self.assertTrue(await self.until(lambda last=shown: self.shown() != last))
        for shelf in shelves[:5]:
            self.assertIs(column.widgets[again.index(shelf)], widgets[shelf])  # kept

        column.show(again[:2], hero_first=True)
        self.assertEqual(self.shown(), again[:2])
        hidden = [child for child in _descendants(self.box)
                  if child.get_parent() is self.box and not child.get_visible()]
        self.assertEqual(len(hidden), 4)  # kept, hidden, for later

    async def test_a_shelf_named_a_hero_shows_large_cards_wherever_it_is(self):
        column = self.column()
        shelves = [model(f's{n}', 2) for n in range(3)]
        column.show(shelves, heroes=[shelves[1]])  # an artist's Essential Albums
        self.assertEqual([widget.props.hero for widget in column.widgets],
                         [False, True, False])
        column.show(shelves)  # no longer a hero: a widget of the other kind
        self.assertEqual([widget.props.hero for widget in column.widgets],
                         [False, False, False])

    async def test_a_shelf_of_the_songs_form_is_a_grid_of_songs(self):
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.song_shelf import SongShelf

        column = self.column()
        shelves = [model(f's{n}', 2) for n in range(3)]
        shelves[1].form = 'songs'  # a chart's Top Songs
        column.show(shelves, hero_first=True)
        self.assertEqual([type(widget) for widget in column.widgets], [Shelf, SongShelf, Shelf])
        self.assertTrue(column.widgets[0].props.hero)
        self.assertEqual(self.shown(), shelves)
        songs = column.widgets[1]
        # Shown again in another form, the shelf gets another widget; the grid is kept for
        # the next shelf of songs.
        shelves[1].form = ''
        column.show(shelves)
        self.assertEqual([type(widget) for widget in column.widgets], [Shelf, Shelf, Shelf])
        other = model('other', 2)
        other.form = 'songs'
        column.show([other])
        self.assertIs(column.widgets[0], songs)
        self.assertEqual(self.shown(), [other])


class RankedShelfTest(PageTestCase):
    """A chart's shelves (a ShelfModel `ranked`): numbered tiles, numbered songs."""

    async def test_a_ranked_shelf_numbers_its_tiles(self):
        from applemusic.widgets.shelf import RankedTile, Shelf
        from applemusic.widgets.tile import Tile
        from tests.page_harness import find_all

        ranked = model('ranked', 3)
        ranked.ranked = True
        shelf = Shelf(see_all=True)
        shelf.bind_shelf(ranked)
        self.window.root_box.append(shelf)
        self.assertTrue(await self.until(lambda: len(find_all(shelf.list_view, RankedTile)) == 3))
        tiles = find_all(shelf.list_view, RankedTile)
        self.assertEqual([tile.rank.get_label() for tile in tiles], ['1', '2', '3'])
        self.assertEqual([tile.context_item.id for tile in tiles],
                         ['ranked.0', 'ranked.1', 'ranked.2'])
        # A shelf that is no chart's: plain tiles again.
        shelf.bind_shelf(model('plain', 2))
        self.assertTrue(await self.until(lambda: len(find_all(shelf.list_view, Tile)) == 2
                                         and not find_all(shelf.list_view, RankedTile)))

    async def test_a_ranked_shelf_of_songs_numbers_them_and_plays_from_the_one_chosen(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.song_shelf import SongRow, SongShelf
        from tests.page_harness import find_all

        songs = [Item({'id': f'190{n}', 'kind': 'song', 'title': f'Invented Song {n}',
                       'subtitle': 'Invented Artist', 'album': 'Invented Album',
                       'play': {'kind': 'song', 'id': f'190{n}'}}) for n in range(4)]
        top = ShelfModel('charts-songs', 'Top Songs', songs)
        top.ranked = True
        shelf = SongShelf()
        shelf.bind_shelf(top)
        self.window.root_box.append(shelf)
        self.assertTrue(await self.until(lambda: len(find_all(shelf.grid_view, SongRow)) == 4))
        rows = sorted(find_all(shelf.grid_view, SongRow), key=lambda row: row.rank.get_text())
        self.assertEqual([row.rank.get_text() for row in rows], ['1', '2', '3', '4'])
        self.assertEqual(rows[0].caption.get_text(), 'Invented Artist · Invented Album')
        shelf.grid_view.emit('activate', 2)
        self.assertEqual(self.window.played, [({'kind': 'songs', 'id': '1900,1901,1902,1903'},
                                               2, None)])
        self.assertEqual(self.window.started_with, ['1902'])

    async def test_a_long_shelf_gives_its_row_the_first_items_then_a_few_a_frame(self):
        # A chart's 100 songs at once held the main loop 80-90 ms: the first FIRST_SONGS,
        # then MORE_SONGS a frame after the one that draws them, until the grid makes no
        # more rows (30 columns of three), then the rest; activating plays them all still.
        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.song_shelf import FIRST_SONGS, MORE_SONGS, SongShelf

        songs = [Item({'id': f'19{n:03d}', 'kind': 'song', 'title': f'Invented Song {n}',
                       'subtitle': 'Invented Artist',
                       'play': {'kind': 'song', 'id': f'19{n:03d}'}}) for n in range(100)]
        top = ShelfModel('charts-songs', 'Top Songs', songs)
        top.ranked = True
        shelf = SongShelf()
        shelf.bind_shelf(top)
        model = shelf.grid_view.get_model()
        self.assertEqual(model.get_n_items(), FIRST_SONGS)
        sizes = [model.get_n_items()]
        model.connect('items-changed', lambda *_args: sizes.append(model.get_n_items()))
        self.window.root_box.append(shelf)
        self.assertTrue(await self.until_frames(
            shelf.grid_view, lambda: model.get_n_items() == 100, 60))
        steps = [b - a for a, b in zip(sizes, sizes[1:], strict=False)]
        self.assertTrue(all(step == MORE_SONGS for step in steps[:-1]), steps)
        self.assertLessEqual(sizes[-2], 90)  # the rest at once once the grid keeps no more
        shelf.grid_view.emit('activate', 99)
        self.assertEqual(self.window.started_with, ['19099'])
        # Another shelf: its own first ones, and the first one's growing stopped.
        shelf.bind_shelf(ShelfModel('more', 'More', songs[:3]))
        self.assertEqual(shelf.grid_view.get_model().get_n_items(), 3)
        self.assertIsNone(shelf._growing)


if __name__ == '__main__':
    unittest.main()
