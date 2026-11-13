# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A playlist page's filter and Sort By (pages/detail_sort_filter.py), over the stand-in
engine (tests/page_harness.py)."""

from tests.page_harness import PageTestCase, album, playing, track
from tests.test_detail_page import _controllers


class PlaylistFilterTest(PageTestCase):
    """A playlist's songs filtered on its page (widgets/filter_bar.py), its songs not moved
    meanwhile; an album's tracks have no filter."""

    async def show(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(1, tracks=4, kind='playlist')
        for entry, (title, by) in zip(data['groups'][0]['entries'], [
                ('Harbour Lights', 'Aura Invented'), ('Dawn', 'Zephyr'),
                ('Night Harbour', 'Lines Collective'), ('Quiet', 'Café Invented')],
                strict=True):
            entry['title'], entry['artist'] = title, by
        self.item = Item(data)
        return await self.push(DetailPage(self.library, self.item))

    def titles(self, page):
        from applemusic.library import Track

        rows = page.list_view.get_model()
        return [rows.get_item(n).title for n in range(rows.get_n_items())
                if isinstance(rows.get_item(n), Track)]

    async def test_the_songs_shown_are_those_the_filter_matches(self):
        from gi.repository import Gdk, Gtk

        page = await self.show()
        bar = page.filter_bar
        said = []
        self.window.announce = lambda text, _priority: said.append(text)
        self.addCleanup(delattr, self.window, 'announce')
        self.assertTrue(bar.button.get_visible())
        self.assertIs(bar.get_key_capture_widget(), page)  # typing on the page starts it
        self.assertTrue(page.can_reorder())
        self.assertTrue(page.focus_filter())  # Ctrl+F
        self.assertTrue(await self.until_focused(bar.entry))
        bar.set_text('harbour')
        self.assertEqual(self.titles(page), ['Harbour Lights', 'Night Harbour'])
        self.assertEqual(said[-1], '2 of 4 songs')
        bar.set_text('cafe')  # an artist, accents ignored
        self.assertEqual(self.titles(page), ['Quiet'])
        # A song plays the playlist from itself, as unfiltered.
        page._on_activate(page.list_view, 1)
        self.assertEqual(self.window.played[-1][1], 3)
        # Filtered, the order shown is not the playlist's: nothing moves.
        self.assertFalse(page.can_reorder())
        self.assertFalse(page.show_insertion(0))
        keys = next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))
        self.assertFalse(keys.emit('key-pressed', Gdk.KEY_Down, 0, Gdk.ModifierType.ALT_MASK))
        # Nothing matching: said in the status box.
        bar.set_text('nothing invented')
        self.assertEqual(self.titles(page), [])
        self.assertTrue(page.status_box.get_visible())
        self.assertEqual(page.status_title.get_label(), 'No Results Found')
        self.assertEqual(page.status_icon.get_icon_name(), 'edit-find-symbolic')
        # Closed (Escape): every song back, and they can be moved again.
        bar.close()
        self.assertTrue(await self.until(lambda: len(self.titles(page)) == 4))
        self.assertFalse(page.status_box.get_visible())
        self.assertTrue(page.can_reorder())

    async def test_escape_from_the_filter_puts_the_focus_back_on_the_song_it_was_on(self):
        # The list's own focus would be a recycled row out of view, bound to another song.
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        item = Item(album(2, tracks=60, kind='playlist'))
        page = await self.push(DetailPage(self.library, item))
        view = page.list_view
        songs = list(item.groups[0].entries)
        self.assertTrue(await self.escape_from_filter(page, view, songs[50], 'song 1'),
                        self.window.get_focus())
        self.assertTrue(await self.escape_from_filter(page, view, songs[40], 'nothing'),
                        self.window.get_focus())

    async def test_a_reload_keeps_the_filter(self):
        page = await self.show()
        page.filter_bar.set_text('harbour')
        data = dict(self.item.raw)
        data['groups'] = [dict(data['groups'][0])]
        data['groups'][0]['entries'] = data['groups'][0]['entries'][:3]  # one went
        self.item.merge(data, replace=True)  # groups-changed: shown again
        self.assertEqual(self.titles(page), ['Harbour Lights', 'Night Harbour'])

    async def test_go_to_current_song_on_a_filtered_playlist(self):
        """Go to Current Song with the filter on: the song's row within it when it matches,
        else the filter cleared and the song's row focused; nothing left waiting either way
        (#443)."""
        page = await self.show()
        bar = page.filter_bar
        rows = page.list_view.get_model()

        async def reveal():
            page.reveal_playing()
            self.assertTrue(await self.until(lambda: page._reveal_task.done(), timeout=2))
            self.assertIsNone(page._reveal_task.exception())
            self.assertFalse(page._reveal_wanted)

        bar.set_text('harbour')  # Harbour Lights and Night Harbour
        self.app.player.track = playing(self.item.groups[0].entries.get_item(2).raw)
        await reveal()
        self.assertEqual(bar.search, 'harbour')  # it matches: the filter stays
        self.assertTrue(page._has_focus_at(2))
        self.assertEqual(rows.get_item(2).title, 'Night Harbour')
        # A song the filter hides: the filter cleared, the song's row focused.
        self.app.player.track = playing(self.item.groups[0].entries.get_item(1).raw)
        await reveal()
        self.assertEqual(bar.search, '')
        self.assertFalse(bar.get_search_mode())
        self.assertEqual(len(self.titles(page)), 4)
        self.assertTrue(page._has_focus_at(2))
        self.assertEqual(rows.get_item(2).title, 'Dawn')
        # A song the playlist does not hold: the filter kept, nothing moves.
        bar.set_text('harbour')
        self.app.player.track = playing(track('l.album009', 0))
        await reveal()
        self.assertEqual(bar.search, 'harbour')

    async def test_an_albums_tracks_have_no_filter(self):
        from applemusic import keyboard
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.pages.detail_sort_filter import filters_songs

        page = await self.push(DetailPage(self.library, Item(album(2, tracks=3))))
        self.assertFalse(page.filter_bar.button.get_visible())
        self.assertIsNone(page.filter_bar.get_key_capture_widget())
        self.assertFalse(page.focus_filter())
        self.assertEqual(keyboard.search_target(page), 'search')
        self.assertFalse(filters_songs(page.item))
        self.assertTrue(filters_songs(Item(album(3, kind='playlist'))))
        self.assertFalse(filters_songs(None))


class PlaylistSortTest(PageTestCase):
    """A playlist's Sort By: the order shown, never the playlist's (no song moves in any
    other); Playlist Order first to last is the playlist's own."""

    async def show(self, kind='playlist'):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(1, tracks=4, kind=kind)
        for entry, (title, by, on, ms) in zip(data['groups'][0]['entries'], [
                ('Delta', 'Bravo Band', 'Zulu', 200000), ('Alpha', 'Delta Duo', 'Kilo', 90000),
                ('Charlie', 'Alpha Act', 'Kilo', 300000), ('Bravo', 'Alpha Act', 'Echo', 150000)],
                strict=True):
            entry.update(title=title, artist=by, album=on, durationMs=ms)
        self.item = Item(data)
        page = await self.push(DetailPage(self.library, self.item))
        self.assertTrue(await self.until(lambda: len(page._bound) == 4, timeout=2))
        return page

    def titles(self, page):
        from applemusic.library import Track

        rows = page.list_view.get_model()
        return [rows.get_item(n).title for n in range(rows.get_n_items())
                if isinstance(rows.get_item(n), Track)]

    async def test_each_order(self):
        page = await self.show()
        self.assertTrue(page.sort_button.get_visible())
        self.assertEqual(self.titles(page), ['Delta', 'Alpha', 'Charlie', 'Bravo'])
        page.sort('title')
        self.assertEqual(self.titles(page), ['Alpha', 'Bravo', 'Charlie', 'Delta'])
        self.assertFalse(page.can_reorder())  # not the playlist's order
        page.sort('title', descending=True)
        self.assertEqual(self.titles(page), ['Delta', 'Charlie', 'Bravo', 'Alpha'])
        page.sort('artist')  # by artist, then album
        self.assertEqual(self.titles(page), ['Bravo', 'Charlie', 'Delta', 'Alpha'])
        page.sort('album')
        self.assertEqual(self.titles(page), ['Bravo', 'Alpha', 'Charlie', 'Delta'])
        page.sort('time', descending=True)
        self.assertEqual(self.titles(page), ['Charlie', 'Delta', 'Bravo', 'Alpha'])
        page.sort('playlist', descending=True)  # last to first: still no move
        self.assertEqual(self.titles(page), ['Bravo', 'Charlie', 'Alpha', 'Delta'])
        self.assertFalse(page.can_reorder())
        page.sort('playlist')
        self.assertEqual(self.titles(page), ['Delta', 'Alpha', 'Charlie', 'Bravo'])
        self.assertTrue(page.can_reorder())
        # The playlist itself kept its order throughout.
        self.assertEqual([track_id.rsplit('.', 1)[1] for track_id in self.item.track_ids()],
                         ['0', '1', '2', '3'])

    async def test_the_menus_actions_and_what_keeps_the_order(self):
        from gi.repository import GLib

        page = await self.show()
        page.activate_action('tracks.sort', GLib.Variant('s', 'time'))
        self.assertEqual(self.titles(page), ['Alpha', 'Bravo', 'Delta', 'Charlie'])
        page.activate_action('tracks.sort-order', GLib.Variant('s', 'descending'))
        self.assertEqual(page.order, ('time', True))
        self.assertEqual(self.titles(page), ['Charlie', 'Delta', 'Bravo', 'Alpha'])
        # A filter, and a reload of the songs, keep it.
        page.filter_bar.set_text('a')
        self.assertEqual(self.titles(page), ['Charlie', 'Delta', 'Bravo', 'Alpha'])
        page.filter_bar.set_text('')
        page._show(self.item)
        self.assertEqual(self.titles(page), ['Charlie', 'Delta', 'Bravo', 'Alpha'])
        # Selecting leaves it out of the header bar (Cancel takes its room).
        page.selection_mode.start()
        self.assertFalse(page.sort_button.get_visible())
        page.selection_mode.leave()
        self.assertTrue(page.sort_button.get_visible())

    async def test_an_album_has_no_sort(self):
        page = await self.show(kind='album')
        self.assertFalse(page.sort_button.get_visible())

    def test_the_labels_mnemonics_differ(self):
        from applemusic.pages.detail_sort_filter import PLAYLIST_SORTS

        labels = [label() for label, _names in PLAYLIST_SORTS.values()]
        labels += ['Asc_ending', 'Desce_nding']
        letters = [label[label.index('_') + 1].lower() for label in labels]
        self.assertEqual(len(letters), len(set(letters)), labels)
