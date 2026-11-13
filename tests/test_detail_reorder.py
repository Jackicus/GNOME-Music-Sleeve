# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Moving and removing a playlist's songs on its page (pages/detail_reorder.py), over the
stand-in engine (tests/page_harness.py)."""

import asyncio

from tests.page_harness import PageTestCase, album
from tests.test_detail_page import _controllers


class ReorderTest(PageTestCase):
    """A playlist's songs moved on its page: Alt+Up and Alt+Down on the focused song, and a
    drag of one of its own songs, with the insertion line where it would go."""

    async def show(self, **attributes):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(1, tracks=4, kind='playlist')
        if attributes:
            data['attributes'] = attributes
        self.item = Item(data)
        page = await self.push(DetailPage(self.library, self.item))
        self.assertTrue(await self.until(
            lambda: len(page._bound) == 4 and page._row_at(3) is not None
            and page._row_at(3).get_height() > 0, timeout=2))
        return page

    def ids(self):
        return [track_id.rsplit('.', 1)[1] for track_id in self.item.track_ids()]

    def row(self, page, index):
        return page._row_at(index)

    def list_row(self, page, index):
        """The list's own row around the song's: where the insertion line is drawn."""
        return page._row_at(index).get_parent()

    def keys(self, page):
        from gi.repository import Gtk

        return next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))

    async def test_which_pages_can_reorder(self):
        page = await self.show()
        self.assertTrue(page.can_reorder())
        for attributes in ({'isFavourites': True}, {'canEdit': False}):
            other = await self.show(**attributes)
            self.assertFalse(other.can_reorder())
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        album_page = await self.push(DetailPage(self.library, Item(album(2, tracks=3))))
        self.assertFalse(album_page.can_reorder())

    async def test_alt_down_and_alt_up_move_the_focused_song(self):
        from gi.repository import Gdk

        page = await self.show()
        self.row(page, 1).get_parent().grab_focus()  # the second song's row
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.list_view)))
        keys = self.keys(page)
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Down, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['0', '2', '1', '3'])
        self.assertEqual(self.window.item_actions.moved, [('l.playlist001', 1, 2, False)])
        await self.turn()
        focus = self.window.get_focus()
        self.assertTrue(focus.is_ancestor(page.list_view) or focus is page.list_view)
        self.assertEqual(self.focused_track(page), 'l.playlist001.t1.1')  # it went with it
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['0', '1', '2', '3'])
        await self.turn()
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['1', '0', '2', '3'])
        await self.turn()
        # At the top: nothing moves, the key is the page's all the same.
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['1', '0', '2', '3'])
        self.assertEqual(len(self.window.item_actions.moved), 3)
        # The hero's button focused: not a song, the key is not taken.
        page.play_button.grab_focus()
        self.assertFalse(keys.emit('key-pressed', Gdk.KEY_Down, 0, Gdk.ModifierType.ALT_MASK))

    async def test_alt_end_and_alt_home_move_the_focused_song_to_an_end(self):
        from gi.repository import Gdk

        page = await self.show()
        self.row(page, 1).get_parent().grab_focus()  # the second song's row
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.list_view)))
        keys = self.keys(page)
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_End, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['0', '2', '3', '1'])
        self.assertEqual(self.window.item_actions.moved, [('l.playlist001', 1, 3, False)])
        await self.turn()
        self.assertEqual(self.focused_track(page), 'l.playlist001.t1.1')  # it went with it
        # At the bottom: nothing moves, the key is the page's all the same.
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_End, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(len(self.window.item_actions.moved), 1)
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Home, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['1', '0', '2', '3'])
        self.assertEqual(self.window.item_actions.moved[-1], ('l.playlist001', 3, 0, False))
        await self.turn()
        self.assertEqual(self.focused_track(page), 'l.playlist001.t1.1')

    def focused_track(self, page):
        from applemusic.pages.detail_rows import _row_of

        row = _row_of(self.window.get_focus())
        return row.track_row.context_item.id if row is not None else None

    async def test_a_drag_of_its_own_song_shows_where_it_goes_and_moves_it(self):
        from gi.repository import Gdk

        from applemusic.library import ItemRefs
        from applemusic.widgets import dnd

        page = await self.show()
        song = self.item.groups[0].entries.get_item(0)
        dnd._set_current(ItemRefs.for_objects([song], origin=('playlist', 'l.playlist001')))
        self.addCleanup(dnd._set_current, None)
        self.assertTrue(page._on_drop_accept(None, None))

        def at(index, lower):
            bounds = self.row(page, index).compute_bounds(page.list_view)[1]
            return (bounds.origin.x + 10,
                    bounds.origin.y + (bounds.size.height - 2 if lower else 2))

        # The top half of the third song: the line on its top edge.
        self.assertEqual(page._on_drop_motion(None, *at(2, False)), Gdk.DragAction.MOVE)
        self.assertTrue(self.list_row(page, 2).has_css_class('drop-before'))
        # The bottom half of the last: on its bottom edge.
        self.assertEqual(page._on_drop_motion(None, *at(3, True)), Gdk.DragAction.MOVE)
        self.assertFalse(self.list_row(page, 2).has_css_class('drop-before'))
        self.assertTrue(self.list_row(page, 3).has_css_class('drop-after'))
        # Beside itself: where it is, no line and no drop.
        self.assertEqual(page._on_drop_motion(None, *at(0, True)), 0)
        self.assertEqual(page._on_drop_motion(None, *at(1, False)), 0)
        self.assertFalse(self.list_row(page, 3).has_css_class('drop-after'))
        # Dropped on the bottom half of the third song: after it, written at once.
        self.assertTrue(page._on_drop(None, None, *at(2, True)))
        self.assertEqual(self.window.item_actions.moved, [('l.playlist001', 0, 2, True)])
        self.assertEqual(self.ids(), ['1', '2', '0', '3'])
        for index in range(4):
            self.assertFalse(self.list_row(page, index).has_css_class('drop-after'))

    async def test_other_drags_are_not_taken(self):
        from applemusic.library import Item, ItemRefs
        from applemusic.widgets import dnd

        page = await self.show()
        song = self.item.groups[0].entries.get_item(0)
        self.addCleanup(dnd._set_current, None)
        for refs in (ItemRefs.for_objects([song], origin=('playlist', 'p.other')),
                     ItemRefs.for_objects([song], origin=('album', 'l.album001')),
                     ItemRefs.for_objects([song, self.item.groups[0].entries.get_item(1)],
                                          origin=('playlist', 'l.playlist001')),
                     ItemRefs.for_objects([Item({'id': 'p.x', 'kind': 'playlist'})]), None):
            dnd._set_current(refs)
            self.assertFalse(page._on_drop_accept(None, None), refs)
            self.assertEqual(page._on_drop_motion(None, 10, 10), 0)
            self.assertFalse(page._on_drop(None, None, 10, 10))
        self.assertEqual(self.window.item_actions.moved, [])


class DeleteTest(PageTestCase):
    """Delete on a playlist's focused song: Remove from Playlist (the item actions' one
    write, with Undo), the focus on the row in its place once the songs show again; in the
    selection mode, the songs selected."""

    async def show(self, **attributes):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(1, tracks=4, kind='playlist')
        if attributes:
            data['attributes'] = attributes
        self.data = data
        self.item = Item(data)
        page = await self.push(DetailPage(self.library, self.item))
        self.assertTrue(await self.until(
            lambda: len(page._bound) == 4 and page._row_at(3) is not None
            and page._row_at(3).get_height() > 0, timeout=2))
        return page

    def songs(self):
        entries = self.item.groups[0].entries
        return [entries.get_item(n) for n in range(entries.get_n_items())]

    def keys(self, page):
        from gi.repository import Gtk

        return next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))

    async def focus(self, page, index):
        page._row_at(index).get_parent().grab_focus()
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.list_view)))

    def delete(self, page):
        from gi.repository import Gdk

        return self.keys(page).emit('key-pressed', Gdk.KEY_Delete, 0, Gdk.ModifierType(0))

    def focused(self, page):
        from applemusic.pages.detail_rows import _row_of

        focus = self.window.get_focus()
        row = _row_of(focus) if focus is not None else None
        return row.track_row.context_item.id if row is not None else None

    async def test_delete_removes_the_focused_song_and_the_focus_takes_the_next(self):
        page = await self.show()
        actions = self.window.item_actions
        actions.removal = asyncio.get_running_loop().create_future()  # under way
        await self.focus(page, 1)
        song = self.songs()[1]
        self.assertTrue(self.delete(page))
        self.assertEqual(actions.batches, [('remove-from-playlist', [song], self.item.id)])
        # One at a time: a second Delete meanwhile asks nothing.
        self.assertTrue(self.delete(page))
        self.assertEqual(len(actions.batches), 1)
        # Apple's answer: the playlist read again without it, its rows made again.
        entries = [dict(entry) for entry in self.data['groups'][0]['entries']
                   if entry['index'] != 1]
        for place, entry in enumerate(entries):
            entry['index'] = place
        self.item.merge({'groups': [dict(self.data['groups'][0], entries=entries)]})
        self.assertTrue(await self.until(lambda: self.focused(page) == 'l.playlist001.t1.2'))
        actions.removal.set_result(True)
        await self.turn()
        self.assertIsNone(page._removing)

    async def test_in_the_selection_mode_delete_removes_the_songs_selected(self):
        page = await self.show()
        await self.focus(page, 0)
        mode = page.selection_mode
        mode.key('toggle', self.songs()[2])
        mode.key('toggle', self.songs()[0])
        self.assertTrue(self.delete(page))
        self.assertEqual(self.window.item_actions.batches[-1],
                         ('remove-from-playlist', [self.songs()[0], self.songs()[2]],
                          self.item.id))
        self.assertFalse(mode.active)
        await self.turn()
        # Nothing selected: the key taken, nothing asked.
        mode.start()
        self.assertTrue(self.delete(page))
        self.assertEqual(len(self.window.item_actions.batches), 1)

    async def test_not_on_favourite_songs_apples_or_a_button(self):
        for attributes in ({'isFavourites': True}, {'canEdit': False}):
            page = await self.show(**attributes)
            await self.focus(page, 0)
            self.assertFalse(self.delete(page))
        page = await self.show()
        page.play_button.grab_focus()
        self.assertFalse(self.delete(page))
        self.assertEqual(self.window.item_actions.batches, [])

    async def test_an_empty_playlist_offers_add_songs(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(2, tracks=0, kind='playlist')
        data['groups'] = [{'name': '', 'play': data['play'], 'entries': []}]  # none in it
        empty = Item(data)
        page = await self.push(DetailPage(self.library, empty))
        self.assertTrue(page.status_button.get_visible())
        self.assertEqual(page.status_button.get_label(), 'Add Songs…')
        page.status_button.emit('clicked')
        self.assertEqual(self.window.item_actions.add_songs, [empty])
        # Favourite Songs: No Songs alone.
        favourites = Item(dict(data, id='l.playlist003', attributes={'isFavourites': True}))
        other = await self.push(DetailPage(self.library, favourites))
        self.assertFalse(other.status_button.get_visible())
