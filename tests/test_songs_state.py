# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Songs page (pages/songs.py): what it shows while the songs are on their way, and a
sync that changes the songs keeps the table's place; the Sort By menu sorts as a header does;
a row plays its own song, on a click; the row of the song playing is marked; a column dragged
wider or narrower follows the pointer and keeps its width on release.
Over an invented library.json in a temporary cache (tests/page_harness.py's window)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.page_harness import PageTestCase, find_all, playing, track


def library_json(cache, tracks, favourites=None):
    play = {'kind': 'album', 'id': 'l.album001'}
    album = {'id': 'l.album001', 'kind': 'album', 'title': 'Invented Album',
             'subtitle': 'Invented Artist', 'play': play,
             'groups': [{'name': '', 'play': play,
                         'entries': [track('l.album001', n, title=f'Song {n:04d}')
                                     for n in range(tracks)]}]}
    data = {'version': 1, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
            'sections': {'albums': [album], 'playlists': [], 'radio': []}, 'shelves': []}
    if favourites is not None:
        data['favourites'] = {'songs': favourites}
    Path(cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')


class SongsStateTest(PageTestCase):
    def test_a_resized_column_expands_again_from_its_width_less_the_others_share(self):
        from applemusic.pages.songs import resized_fixed_width

        self.assertEqual(resized_fixed_width(300, 260, 90, 2), 230)  # the others hold 70
        self.assertEqual(resized_fixed_width(200, 260, 90, 2), 80)  # they hold 120
        self.assertEqual(resized_fixed_width(500, 260, 90, 2), 500)  # no room is left
        self.assertIsNone(resized_fixed_width(50, 260, 90, 2))  # narrower than its share
        self.assertIsNone(resized_fixed_width(300, 260, 90, 0))

    def test_songs_that_exist_but_are_not_ordered_yet_are_loading(self):
        from applemusic.pages.songs import songs_state

        self.assertEqual(songs_state(0, 'ready', True, 3), 'loading')  # not ordered yet
        self.assertEqual(songs_state(0, 'ready', True, 0), 'empty')
        self.assertEqual(songs_state(5, 'ready', True, 5), 'items')
        self.assertEqual(songs_state(0, 'loading', True, 0), 'loading')
        self.assertEqual(songs_state(0, 'ready', False, 0), 'loading')  # not built yet
        # The first sync fills an empty library: on its way, not "No Songs".
        self.assertEqual(songs_state(0, 'empty', True, 0, syncing=True), 'loading')
        self.assertEqual(songs_state(0, 'empty', True, 0, syncing=False), 'empty')


class SongsPageTest(PageTestCase):
    async def asyncSetUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = cache.name
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def songs_page(self, tracks, favourites=None):
        from applemusic.pages.songs import SongsPage

        library_json(self.cache, tracks, favourites)
        await self.library.load()
        page = await self.show_root(SongsPage(self.library, 'Songs'))
        self.assertTrue(await self.until(lambda: page._rows.get_n_items() == tracks, 2))
        return page

    async def test_a_library_without_songs_offers_sign_in_while_signed_out(self):
        self.app.settings.set_boolean('signed-in', False)
        page = await self.songs_page(0)
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'empty'))
        button = page.empty_page.get_child()
        self.assertTrue(button.get_visible())
        self.assertEqual(button.get_action_name(), 'app.sign-in')
        self.assertEqual(page.empty_page.get_description(),
                         'Sign in to Apple Music to see your library')
        self.app.settings.set_boolean('signed-in', True)
        self.assertFalse(button.get_visible())
        self.assertEqual(page.empty_page.get_description(), 'Songs in your library appear here')

    async def test_a_sync_that_adds_a_song_keeps_the_scroll_position(self):
        page = await self.songs_page(300)
        adjustment = page.column_view.get_vadjustment()
        self.assertTrue(await self.until(lambda: adjustment.get_upper() > 3000))
        adjustment.set_value(2000)
        await self.turn()
        library_json(self.cache, 301)
        await self.library.reload()
        self.assertTrue(await self.until(lambda: page._rows.get_n_items() == 301, 2))
        await self.turn()
        # Within a pixel: the view's anchor is a row and a fraction of its height.
        self.assertAlmostEqual(adjustment.get_value(), 2000, delta=1)

    async def test_the_sort_menu_sorts_as_a_header_does(self):
        page = await self.songs_page(5)
        page.activate_action('songs.sort-order', _variant('descending'))
        self.assertEqual(page._rows.get_item(0).title, 'Song 0004')
        sorter = page.column_view.get_sorter()
        self.assertIs(sorter.get_primary_sort_column(), page.title_column)
        page.activate_action('songs.sort-column', _variant('time'))
        self.assertIs(sorter.get_primary_sort_column(), page.time_column)
        # A header click (the sorter changing) moves the menu's choice.
        page.column_view.sort_by_column(None, 0)
        page.column_view.sort_by_column(page.album_column, 0)
        self.assertEqual(page._sort_column.get_state().get_string(), 'album')
        self.assertEqual(page._sort_order.get_state().get_string(), 'ascending')

    async def test_a_dragged_column_follows_the_pointer_and_expands_again_on_release(self):
        # GTK's drag sets the fixed width to the allocated width, the expanding share
        # included: the share must not be added again, or the divider leaves the pointer.
        from gi.repository import Gtk

        page = await self.songs_page(5)
        gesture = next(controller for controller in page.column_view.observe_controllers()
                       if isinstance(controller, Gtk.GestureDrag)
                       and controller.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE)
        page.artist_column.set_fixed_width(120)  # not a drag (the breakpoint's setter)
        self.assertTrue(page.artist_column.get_expand())
        gesture.emit('drag-begin', 0.0, 0.0)
        page.title_column.set_fixed_width(170 + 90)  # GTK's: the allocation, a share of 90
        self.assertFalse(page.title_column.get_expand())
        page.title_column.set_fixed_width(170 + 90 + 40)  # dragged 40 px wider
        gesture.emit('drag-end', 40.0, 0.0)
        # Two others shared the 40 px: 70 each; the column's own 70 comes back as it expands.
        self.assertTrue(page.title_column.get_expand())
        self.assertEqual(page.title_column.get_fixed_width(), 300 - 70)
        self.assertTrue(page.artist_column.get_expand())

    async def test_a_filter_bringing_many_back_keeps_the_rows_and_adds_a_few_a_frame(self):
        from applemusic.pages.songs import GROW_ROWS

        page = await self.songs_page(400)
        page.set_filter('Song 0011')
        self.assertEqual(page._rows.get_n_items(), 1)
        row = page._rows.get_item(0)
        page.set_filter('')
        # Song 0011's row stays where it will be, the others come a few a frame.
        self.assertLessEqual(page._rows.get_n_items(), 1 + GROW_ROWS)
        self.assertTrue(await self.until_frames(
            page.column_view, lambda: page._rows.get_n_items() == 400, 60))
        self.assertIs(page._rows.get_item(11), row)
        self.assertEqual([page._rows.get_item(n).title for n in range(400)],
                         [f'Song {n:04d}' for n in range(400)])
        self.assertEqual(page.count_label.get_label(), '400 songs')

    async def test_a_backspace_to_a_text_filtered_by_lately_tests_no_song(self):
        page = await self.songs_page(30)
        for text in ('Song 00', 'Song 001', 'Song 0012'):
            page.set_filter(text)
        typed = page._matches
        page.set_filter('Song 001')
        self.assertEqual([track.title for track in page._matches],
                         [f'Song {n:04d}' for n in range(10, 20)])
        page.set_filter('Song 0012')
        self.assertIs(page._matches, typed)  # kept: nothing tested again
        # Favourites Only, or new songs, forget them.
        page.activate_action('songs.favourites-only', None)
        page.set_filter('Song 001')
        self.assertEqual(page._matches, [])
        page.activate_action('songs.favourites-only', None)  # off again, as remembered
    async def test_a_filter_set_from_elsewhere_applies_at_once(self):
        page = await self.songs_page(12)
        page.set_filter('Song 0011')
        self.assertEqual(page._rows.get_n_items(), 1)
        self.assertEqual(page.count_label.get_label(), '1 of 12 songs')
        # In the filter bar, shown with the text in it.
        self.assertTrue(page.filter_bar.get_search_mode())
        self.assertEqual(page.filter_bar.entry.get_text(), 'Song 0011')
        # Closing the bar (its button, Escape) clears the filter.
        page.filter_bar.set_search_mode(False)
        self.assertTrue(await self.until(lambda: page._rows.get_n_items() == 12))
        self.assertEqual(page.count_label.get_label(), '12 songs')
        self.assertEqual(page.filter_bar.entry.get_text(), '')

    async def test_the_filter_bar_is_shown_by_ctrl_f_and_typing_and_closed_by_escape(self):
        page = await self.songs_page(3)
        window = page.get_root()
        self.assertIs(page.filter_bar.get_key_capture_widget(), page)  # typing shows it
        self.assertTrue(page.filter_bar.button.get_visible())
        self.assertFalse(page.filter_bar.get_search_mode())
        self.assertTrue(page.focus_filter())
        self.assertTrue(page.filter_bar.get_search_mode())
        self.assertTrue(page.filter_bar.button.get_active())  # the header's toggle follows
        self.assertTrue(await self.until(
            lambda: window.get_focus() is not None
            and window.get_focus().is_ancestor(page.filter_bar.entry)))
        page.filter_bar.entry.set_text('Song 0002')
        page.filter_bar.entry.emit('search-changed')
        self.assertEqual(page._rows.get_n_items(), 1)
        page.filter_bar.entry.emit('stop-search')  # Escape
        self.assertFalse(page.filter_bar.get_search_mode())
        self.assertFalse(page.filter_bar.button.get_active())
        self.assertTrue(await self.until(lambda: page._rows.get_n_items() == 3))
        self.assertTrue(await self.until(
            lambda: window.get_focus() is not None
            and window.get_focus().is_ancestor(page.column_view)))

    async def test_escape_from_the_filter_puts_the_focus_back_on_the_row_it_was_on(self):
        # The table's own focus would be a recycled row out of view, bound to another song.
        page = await self.songs_page(120)
        view = page.column_view
        songs = [page._rows.get_item(n) for n in range(120)]
        self.assertTrue(await self.escape_from_filter(page, view, songs[100], 'song 000'),
                        self.window.get_focus())
        self.assertTrue(await self.escape_from_filter(page, view, songs[90], 'nothing'),
                        self.window.get_focus())

    async def test_no_songs_means_no_filter(self):
        page = await self.songs_page(0)
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'empty'))
        self.assertFalse(page.filter_bar.button.get_visible())
        self.assertFalse(page.focus_filter())
        self.assertFalse(page.filter_bar.get_search_mode())

    async def test_a_row_plays_its_album_from_its_own_song(self):
        from gi.repository import Gtk

        page = await self.songs_page(5)
        page.activate_action('songs.sort-order', _variant('descending'))
        page.on_activate(page.column_view, 1)
        window = page.get_root()
        track = page._rows.get_item(1)
        self.assertEqual(window.played[-1], (track.play, track.index, None))
        self.assertEqual(window.started_with[-1], track.id)
        # On a click; with no selection, which GTK would move to the hovered row.
        self.assertTrue(page.column_view.get_single_click_activate())
        self.assertIsInstance(page.column_view.get_model(), Gtk.NoSelection)

    async def test_a_plain_click_plays_and_a_ctrl_click_starts_selecting(self):
        """A click plays a song (docs/decisions.md), the selection mode or not; a Ctrl+click
        or a Shift+click enters the mode, and in it a click selects instead of playing."""
        from gi.repository import Gdk

        page = await self.songs_page(6)
        mode, view, window = page.selection_mode, page.column_view, page.get_root()
        self.assertTrue(await self.until(lambda: len(page._title_cells) == 6))
        songs = [page._rows.get_item(n) for n in range(6)]

        def click(position, modifiers=0):
            with mock.patch('applemusic.widgets.dnd.modifiers', return_value=modifiers):
                page.on_activate(view, position)

        click(1)
        self.assertEqual(window.played[-1], (songs[1].play, songs[1].index, None))
        self.assertFalse(mode.active)
        self.assertTrue(mode.select_button.get_visible())
        played = len(window.played)
        click(2, Gdk.ModifierType.CONTROL_MASK)
        self.assertEqual(len(window.played), played)  # selected, not played
        self.assertTrue(mode.active)
        self.assertEqual(mode.selection.ordered(songs), [songs[2]])
        click(4)  # in the mode, a plain click selects too
        click(2)  # and a second unselects
        click(0, Gdk.ModifierType.SHIFT_MASK)  # from the last toggled (2) up to it
        chosen = [songs[0], songs[1], songs[2], songs[4]]
        self.assertEqual(mode.selection.ordered(songs), chosen)
        self.assertEqual(len(window.played), played)
        # Shown: the check boxes, the count, Cancel for Select, the bar; Sort and Filter
        # leave the header bar Cancel's room.
        cells = {cell.get_item(): cell.get_child() for cell in page._title_cells}
        self.assertTrue(all(cell.check.get_visible() for cell in cells.values()))
        self.assertEqual([song for song in songs if cells[song].check.get_active()], chosen)
        self.assertIs(page.header_bar.get_title_widget(), mode.title_button)
        self.assertEqual(mode.title, '4 Selected')
        self.assertTrue(page.header_bar.get_show_title())
        self.assertEqual((mode.select_button.get_visible(), mode.cancel_button.get_visible()),
                         (False, True))
        self.assertTrue(mode.bar.get_revealed())
        self.assertFalse(page.sort_button.get_visible())
        self.assertFalse(page.filter_bar.button.get_visible())
        self.assertTrue(page.filter_bar.available)  # Ctrl+F still filters
        rows = {row.get_item(): row for row in page._row_items}
        self.assertEqual(rows[songs[0]].get_accessible_description(), 'Selected, 3:00')
        self.assertEqual(rows[songs[5]].get_accessible_description(), 'Not Selected, 3:00')
        # Escape (keyboard.selection_key's 'leave'): back as it was, nothing selected.
        self.assertTrue(mode.key('leave'))
        self.assertFalse(mode.active)
        self.assertFalse(any(cell.check.get_visible() for cell in cells.values()))
        self.assertIsNot(page.header_bar.get_title_widget(), mode.title_button)
        self.assertTrue(page.sort_button.get_visible())
        self.assertTrue(page.filter_bar.button.get_visible())
        self.assertEqual(rows[songs[0]].get_accessible_description(), '3:00')
        click(3)
        self.assertEqual(window.played[-1], (songs[3].play, songs[3].index, None))

    async def test_the_keys_and_the_filter(self):
        page = await self.songs_page(12)
        mode = page.selection_mode
        songs = [page._rows.get_item(n) for n in range(12)]
        self.assertFalse(mode.key('toggle'))  # no song focused
        self.assertTrue(mode.key('select-all'))  # Ctrl+A on a song starts it
        self.assertEqual(mode.selection.count, 12)
        self.assertTrue(mode.key('toggle', songs[0]))
        self.assertTrue(mode.key('extend', songs[3]))  # Shift+Space from the last toggled
        self.assertEqual(mode.selection.count, 12)
        mode.key('select-none')
        for song in songs[:3]:
            mode.key('toggle', song)
        # What the filter hides leaves the selection, and an action never reaches it.
        page.set_filter('Song 0001')
        self.assertEqual(mode.selection.ordered(page._matches), [songs[1]])
        self.assertEqual(mode.selection.count, 1)
        page.set_filter('')
        self.assertEqual(mode.selection.count, 1)
        # Hidden (another destination shown, or a page pushed over it): the mode ends.
        page.do_hidden()
        self.assertFalse(mode.active)

    async def test_the_bar_runs_the_item_actions_on_the_selection(self):
        page = await self.songs_page(4)
        mode = page.selection_mode
        actions = page.get_root().item_actions
        songs = [page._rows.get_item(n) for n in range(4)]
        self.assertFalse(mode.actions.get_action_enabled('play-next'))  # nothing selected
        for name, expected in (('play-next', ('queue', [songs[1], songs[3]], False)),
                               ('play-later', ('queue', [songs[1], songs[3]], True)),
                               ('new-playlist', ('new-playlist', [songs[1], songs[3]])),
                               ('remove-from-library',
                                ('remove-from-library', [songs[1], songs[3]]))):
            mode.key('toggle', songs[3])
            mode.key('toggle', songs[1])
            self.assertTrue(mode.actions.get_action_enabled(name))
            mode.actions.activate_action(name, None)
            self.assertEqual(actions.batches[-1], expected, name)  # in the order shown
            self.assertFalse(mode.active)  # an action ends the mode
        mode.key('toggle', songs[0])
        from gi.repository import GLib
        mode.actions.activate_action('add-to-playlist', GLib.Variant('s', 'l.playlist009'))
        self.assertEqual(actions.batches[-1], ('add', [songs[0]], 'l.playlist009'))
        # The Songs table is no playlist: no Remove from Playlist.
        mode.key('toggle', songs[0])
        self.assertFalse(mode.actions.get_action_enabled('remove-from-playlist'))

    async def test_a_drag_of_a_selected_song_carries_the_selection(self):
        from applemusic.widgets import context_menu

        page = await self.songs_page(4)
        mode = page.selection_mode
        songs = [page._rows.get_item(n) for n in range(4)]
        objects = page.column_view._drag_objects
        self.assertIsNone(objects(songs[0]))  # not selecting: the song alone
        mode.key('toggle', songs[2])
        mode.key('toggle', songs[0])
        self.assertEqual(objects(songs[2]), [songs[0], songs[2]])
        self.assertIsNone(objects(songs[1]))  # one not selected: itself
        refs = context_menu.drag_refs_of(objects(songs[2]))
        self.assertEqual([ref.id for ref in refs], [songs[0].id, songs[2].id])
        self.assertEqual(context_menu.songs_label(len(refs)), '2 Songs')

    async def test_the_song_playing_is_marked(self):
        page = await self.songs_page(5)
        self.assertTrue(await self.until(lambda: len(page._title_cells) == 5))
        cells = {cell.get_item().id: cell.get_child() for cell in page._title_cells}
        rows = {row.get_item().id: row for row in page._row_items}
        self.assertEqual(len(rows), 5)
        self.app.player.track = playing(track('l.album001', 2))
        self.assertEqual([song_id for song_id, cell in cells.items() if cell.playing],
                         ['l.album001.t1.2'])
        self.assertEqual(rows['l.album001.t1.2'].get_accessible_description(), 'Playing')
        self.assertEqual(rows['l.album001.t1.1'].get_accessible_description(), '3:00')
        self.app.player.track = None
        self.assertFalse(any(cell.playing for cell in cells.values()))
        self.assertEqual(rows['l.album001.t1.2'].get_accessible_description(), '3:00')


    async def test_a_narrow_table_shows_the_artist_under_the_title(self):
        """At 360 px the Artist column gives way to a line under the title, which keeps the
        room a title needs beside its badge and heart; wider, the column is back."""
        from gi.repository import Gtk

        from applemusic.pages.songs import SongsPage

        ids = [track('l.album001', n)['id'] for n in range(3)]
        library_json(self.cache, 3, favourites=ids)
        await self.library.load()
        page = await self.show_at(SongsPage(self.library, 'Songs'), 360)
        self.assertTrue(await self.until(lambda: len(page._title_cells) == 3, 2))
        cells = [cell.get_child() for cell in page._title_cells]
        self.assertTrue(await self.until(lambda: all(cell.artist_label.get_mapped()
                                                     for cell in cells)))
        self.assertFalse(page.artist_column.get_visible())
        self.assertFalse(page.album_column.get_visible())
        self.assertEqual({cell.artist_label.get_text() for cell in cells}, {'Invented Artist'})
        # The title's line has room for "Analog Boulevard" and its badge (about 140 px) beside
        # the heart, and the time is still shown whole, inside the window.
        line = cells[0].label.get_parent()
        self.assertTrue(await self.until(lambda: line.get_width() >= 150), line.get_width())
        times = [label for label in find_all(page.column_view, Gtk.Inscription)
                 if label.get_text() == '3:00' and label.get_mapped()]
        self.assertEqual(len(times), 3)
        for label in times:
            bounds = label.compute_bounds(page)[1]
            self.assertGreaterEqual(bounds.get_width(), 56)  # "1:02:03"
            self.assertLessEqual(bounds.get_x() + bounds.get_width(), page.get_width())
        # Wide again, the column is back and the line gone.
        page.get_root().set_default_size(1000, 640)
        self.assertTrue(await self.until(page.artist_column.get_visible, 2))
        self.assertFalse(any(cell.artist_label.get_visible() for cell in cells))

    async def test_favourites_have_hearts_and_favourites_only_shows_them(self):
        ids = [track('l.album001', n)['id'] for n in range(5)]
        page = await self.songs_page(5, favourites=[ids[1], ids[3]])
        self.addCleanup(self.app.settings.reset, 'favourites-only')
        self.assertTrue(await self.until(lambda: len(page._title_cells) == 5))
        cells = {cell.get_item().id: cell.get_child() for cell in page._title_cells}
        self.assertEqual(sorted(song_id for song_id, cell in cells.items()
                                if cell.favourite_icon.get_opacity() == 1), [ids[1], ids[3]])
        rows = {row.get_item().id: row for row in page._row_items}
        self.assertTrue(rows[ids[1]].get_accessible_label().endswith(', favourite'))
        self.assertFalse(rows[ids[0]].get_accessible_label().endswith(', favourite'))
        page.activate_action('songs.favourites-only', None)
        self.assertEqual([row.id for row in page._rows], [ids[1], ids[3]])
        self.assertEqual(page.count_label.get_label(), '2 of 5 songs')
        # A heart taken back here: the table follows at once.
        self.library.set_favourite(ids[1], False)
        self.assertEqual([row.id for row in page._rows], [ids[3]])
        self.library.set_favourite(ids[3], False)
        self.assertEqual(page.results_stack.get_visible_child_name(), 'no-results')
        self.assertEqual(page.no_results_page.get_title(), 'No Favourite Songs')
        page.activate_action('songs.favourites-only', None)
        self.assertEqual(page._rows.get_n_items(), 5)


def _variant(text):
    from gi.repository import GLib

    return GLib.Variant('s', text)


if __name__ == '__main__':
    unittest.main()
