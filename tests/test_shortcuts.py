# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The shortcuts table: the Keyboard Shortcuts dialog lists every accelerator and key."""

import unittest

import gi

from tests import SRC  # noqa: F401  registers src/ as applemusic

from applemusic import shortcuts

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # noqa: E402


def listed():
    return [key for _title, items in shortcuts.sections() for _item, key in items]


class ShortcutsTest(unittest.TestCase):
    def test_every_accelerator_is_listed(self):
        keys = listed()
        for action in shortcuts.ACCELS:
            self.assertIn(action, keys, action)
        for action in shortcuts.PLAYBACK:
            self.assertIn(action, keys, action)
        for action in shortcuts.NOW_PLAYING_TABS:
            self.assertIn(action, keys, action)
        for key in (shortcuts.MAIN_MENU, shortcuts.CONTEXT_MENU, shortcuts.CLOSE,
                    shortcuts.FOLDER_OPEN, shortcuts.FOLDER_CLOSE, shortcuts.QUEUE_REMOVE,
                    shortcuts.MOVE_UP, shortcuts.MOVE_DOWN, shortcuts.VOLUME_UP,
                    shortcuts.VOLUME_DOWN, shortcuts.SELECT_TOGGLE, shortcuts.SELECT_RANGE,
                    shortcuts.SELECT_ALL, shortcuts.SELECT_NONE, shortcuts.LEAVE_SELECTION):
            self.assertIn(key, keys, key)

    def test_titles_and_keys(self):
        for title, items in shortcuts.sections():
            self.assertTrue(title)
            self.assertTrue(items, title)
            for item_title, key in items:
                self.assertTrue(item_title, key)
                self.assertTrue(shortcuts.accelerator(key), item_title)

    def test_accelerators_parse(self):
        for key in listed():
            for accel in shortcuts.accelerator(key).split():
                self.assertTrue(Gtk.accelerator_parse(accel)[0], accel)
        for accels in (list(shortcuts.ACCELS.values()) + list(shortcuts.PLAYBACK.values())
                       + list(shortcuts.NOW_PLAYING_TABS.values())):
            for accel in accels:
                self.assertTrue(Gtk.accelerator_parse(accel)[0], accel)

    def test_no_key_does_two_things(self):
        seen = {}
        table = (list(shortcuts.ACCELS.items()) + list(shortcuts.PLAYBACK.items())
                 + list(shortcuts.NOW_PLAYING_TABS.items()))
        for action, accels in table:
            for accel in accels:
                parsed = Gtk.accelerator_parse(accel)[1:]
                self.assertNotIn(parsed, seen, f'{accel}: {action} and {seen.get(parsed)}')
                seen[parsed] = action
        for accel in (shortcuts.MAIN_MENU, *shortcuts.CONTEXT_MENU.split(), shortcuts.CLOSE,
                      shortcuts.FOLDER_OPEN, shortcuts.FOLDER_CLOSE, shortcuts.QUEUE_REMOVE,
                      shortcuts.MOVE_UP, shortcuts.MOVE_DOWN, shortcuts.VOLUME_UP,
                      shortcuts.VOLUME_DOWN):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], seen, accel)

    def test_the_higs_standard_keys_stay_free(self):
        """The HIG's standard shortcuts the app has no such action for are not taken by
        another: Ctrl+O (Open), Ctrl+S (Save), Ctrl+P (Print), Ctrl+Z (Undo). Ctrl+N is its
        "New": New Playlist, as on Apple's players; Now Playing is Ctrl+Shift+N."""
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        for accel in ('<primary>o', '<primary>s', '<primary>p', '<primary>z'):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], taken, accel)
        self.assertEqual(shortcuts.ACCELS['win.new-playlist'], ('<primary>n',))
        self.assertEqual(shortcuts.ACCELS['app.now-playing'], ('<primary><shift>n',))

    def test_the_volume_keys_are_not_accelerators(self):
        """Ctrl+Up and Ctrl+Down are editing chords (a text view's paragraphs, a slider's
        page step, a boxed list's move without selecting): the window's own
        (keyboard.volume_step), never accelerators GTK would run before the focus."""
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        for accel in (shortcuts.VOLUME_UP, shortcuts.VOLUME_DOWN):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], taken, accel)
        self.assertEqual((shortcuts.VOLUME_UP, shortcuts.VOLUME_DOWN),
                         ('<primary>Up', '<primary>Down'))
        self.assertEqual(shortcuts.ACCELS['win.go-to-current-song'], ('<primary>l',))

    def test_the_selection_keys_are_not_accelerators(self):
        """Ctrl+A and Ctrl+Shift+A are editing chords (select the text of the filter),
        Space a button's: the window's own in a list's selection mode
        (keyboard.selection_key), never accelerators GTK would run before the focus."""
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        for accel in (shortcuts.SELECT_ALL, shortcuts.SELECT_NONE, shortcuts.SELECT_TOGGLE,
                      shortcuts.SELECT_RANGE):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], taken, accel)

    def test_the_now_playing_tab_keys_are_not_accelerators(self):
        """Ctrl+Shift+U is GTK's Unicode entry in a text field: as an application
        accelerator, run before the focus widget, it would take that from the Search entry.
        The tab keys are the window's (keyboard.tab_action), Ctrl+Shift+L with them."""
        self.assertEqual(shortcuts.NOW_PLAYING_TABS, {
            'show-lyrics': ('<primary><shift>l',), 'show-queue': ('<primary><shift>u',)})
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        self.assertNotIn(Gtk.accelerator_parse('<primary><shift>u')[1:], taken)

    def test_f11_is_the_full_screen_players_and_f5_the_pages_refresh(self):
        """The HIG's Fullscreen key and Refresh's F5, the accelerators without a modifier
        (function keys, which no widget takes), listed in the dialog though they are off
        while nothing plays, or on a page without a Refresh."""
        self.assertEqual(shortcuts.ACCELS['win.fullscreen-player'], ('F11',))
        self.assertEqual(shortcuts.ACCELS['win.refresh'], ('F5',))
        bare = [accel for accels in shortcuts.ACCELS.values() for accel in accels
                if not Gtk.accelerator_parse(accel)[2]]
        self.assertEqual(sorted(bare), ['F11', 'F5'])
        self.assertIn('win.fullscreen-player', listed())
        self.assertIn('win.refresh', listed())


if __name__ == '__main__':
    unittest.main()
