# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Artists page (pages/artists.py): the library's artists A to Z beside the library's page
of the one selected, the collapsed layout's one pane at a time and its way back, and the
loading and empty states. Invented library items in a stand-in window."""

import unittest

from tests.gtk import requires_gtk
from tests.page_harness import PageTestCase, album, artist


@requires_gtk
class ArtistsPageTest(PageTestCase):
    def add_artist(self, artist_id, name, number):
        """An artist of the library's with one album (number) the library has."""
        from applemusic.library import Item

        item = Item(album(number, tracks=1))
        self.library._index[('album', item.id)] = item
        self.library.albums.append(item)
        data = artist([album(number)], artist_id=artist_id)
        data['title'] = name
        data['groups'][0]['entries'] = []
        band = Item(data)
        self.library._index[('artist', band.id)] = band
        self.library.artists.append(band)
        return band, item

    async def page(self):
        from applemusic.pages.artists import ArtistsPage

        page = await self.show_root(ArtistsPage(self.library, 'Artists'))
        await self.turn()
        return page

    def listed(self, page):
        model = page.list_view.get_model()
        return [model.get_item(position).title for position in range(model.get_n_items())]

    async def test_the_artists_a_to_z_beside_the_first(self):
        self.library.state = 'ready'
        zed, zed_album = self.add_artist('l.art2', 'Zephyr Lines', 2)
        aura, aura_album = self.add_artist('l.art1', 'Aura Invented', 1)
        page = await self.page()
        self.assertEqual(page.stack.get_visible_child_name(), 'artists')
        self.assertEqual(self.listed(page), ['Aura Invented', 'Zephyr Lines'])
        self.assertIs(page.detail.artist, aura)
        self.assertEqual(page.detail.shown_albums(), [aura_album])
        # Another selected: shown in place.
        page.list_view.get_model().set_selected(1)
        self.assertIs(page.detail.artist, zed)
        self.assertEqual(page.detail.shown_albums(), [zed_album])
        self.assertFalse(page.can_go_back())  # side by side, there is no back

    async def test_collapsed_one_pane_at_a_time(self):
        self.library.state = 'ready'
        self.add_artist('l.art1', 'Aura Invented', 1)
        band, _album = self.add_artist('l.art2', 'Zephyr Lines', 2)
        page = await self.page()
        changes = []
        page.connect('panes-changed', lambda _page: changes.append(True))
        page.split_view.set_collapsed(True)
        self.assertTrue(changes)
        self.assertFalse(page.split_view.get_show_content())  # the list first
        self.assertFalse(page.can_go_back())
        # Enter (the list's activate) shows the artist's albums, and Back the list again.
        page.list_view.emit('activate', 1)
        self.assertIs(page.detail.artist, band)
        self.assertTrue(page.split_view.get_show_content())
        self.assertTrue(page.can_go_back())
        self.assertIs(page.banner_host().get_ancestor(type(page.detail)), page.detail)
        self.assertTrue(page.go_back())
        self.assertFalse(page.split_view.get_show_content())
        self.assertFalse(page.go_back())
        self.assertIs(page.banner_host(), page.list_toolbar)

    async def test_the_list_has_its_first_rows_at_once_and_the_rest_frames_apart(self):
        from applemusic.pages.artists import FIRST_ROWS

        self.library.state = 'ready'
        for number in range(FIRST_ROWS + 30):
            self.add_artist(f'l.art{number}', f'Invented Artist {number:03d}', number)
        page = await self.page()
        self.assertTrue(await self.until(
            lambda: len(self.listed(page)) == FIRST_ROWS + 30))
        self.assertEqual(self.listed(page)[-1], f'Invented Artist {FIRST_ROWS + 29:03d}')

    async def test_the_filter_keeps_the_artist_selected_or_takes_the_first_match(self):
        self.library.state = 'ready'
        aura, _album = self.add_artist('l.art1', 'Aura Invented', 1)
        harbour, _album = self.add_artist('l.art2', 'Harbour Lines', 2)
        lines, _album = self.add_artist('l.art3', 'Lines Collective', 3)
        zed, _album = self.add_artist('l.art4', 'Zephyr Café', 4)
        page = await self.page()
        bar = page.filter_bar
        self.assertTrue(bar.button.get_visible())
        self.assertIs(bar.get_key_capture_widget(), page.list_page)  # typing on the list
        page.list_view.get_model().set_selected(2)
        self.assertIs(page.detail.artist, lines)
        shown = []
        page.detail.set_artist = lambda artist: shown.append(artist)  # what the pane is told
        self.assertTrue(page.focus_filter())
        bar.set_text('lines')  # still listed: still selected, the albums as they were
        self.assertEqual(self.listed(page), ['Harbour Lines', 'Lines Collective'])
        self.assertIs(page.list_view.get_model().get_selected_item(), lines)
        self.assertEqual(shown, [])
        bar.set_text('cafe')  # left out: the first match, once
        self.assertEqual(self.listed(page), ['Zephyr Café'])
        self.assertEqual(shown, [zed])
        bar.set_text('nothing invented')  # no match: the albums shown stay
        self.assertEqual(page.list_stack.get_visible_child_name(), 'no-results')
        self.assertEqual(shown, [zed])
        page.focus_content()  # Ctrl+2 with nothing listed: the filter, to change it
        self.assertTrue(await self.until_focused(bar.entry))
        bar.close()
        self.assertTrue(await self.until(lambda: len(self.listed(page)) == 4))
        self.assertEqual(page.list_stack.get_visible_child_name(), 'list')
        self.assertIs(page.list_view.get_model().get_selected_item(), zed)
        del page.detail.set_artist

    async def test_escape_from_the_filter_goes_back_to_the_artist_it_was_on(self):
        # The filter selects its first match meanwhile; Escape selects the artist again.
        self.library.state = 'ready'
        bands = [self.add_artist(f'l.art{n}', f'Invented Artist {n:03d}', n)[0]
                 for n in range(60)]
        page = await self.page()
        self.assertTrue(await self.until(lambda: len(self.listed(page)) == 60))
        view = page.list_view
        view.get_model().set_selected(50)
        self.assertTrue(await self.escape_from_filter(page, view, bands[50], 'artist 00'),
                        self.window.get_focus())
        self.assertIs(view.get_model().get_selected_item(), bands[50])
        self.assertIs(page.detail.artist, bands[50])

    async def test_ctrl_f_in_the_collapsed_layout_goes_back_to_the_list(self):
        self.library.state = 'ready'
        self.add_artist('l.art1', 'Aura Invented', 1)
        page = await self.page()
        page.split_view.set_collapsed(True)
        page.list_view.emit('activate', 0)
        self.assertTrue(page.split_view.get_show_content())
        self.assertTrue(page.focus_filter())
        self.assertFalse(page.split_view.get_show_content())
        self.assertTrue(await self.until_focused(page.filter_bar.entry))

    async def test_loading_then_empty(self):
        self.library.state = 'loading'
        page = await self.page()
        self.assertEqual(page.stack.get_visible_child_name(), 'loading')
        self.library.state = 'ready'
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'No Artists')
        # An artist arriving (a sync) shows the list, the artist selected.
        band, _album = self.add_artist('l.art1', 'Aura Invented', 1)
        self.assertEqual(page.stack.get_visible_child_name(), 'artists')
        self.assertIs(page.detail.artist, band)


if __name__ == '__main__':
    unittest.main()
