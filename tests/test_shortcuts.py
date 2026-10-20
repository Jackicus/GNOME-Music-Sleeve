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
                    shortcuts.FOLDER_OPEN, shortcuts.FOLDER_CLOSE, shortcuts.QUEUE_REMOVE):
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
                      shortcuts.FOLDER_OPEN, shortcuts.FOLDER_CLOSE, shortcuts.QUEUE_REMOVE):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], seen, accel)

    def test_the_higs_standard_keys_stay_free(self):
        """The HIG's standard shortcuts the app has no such action for are not taken by
        another: Ctrl+N (New), Ctrl+O (Open), Ctrl+S (Save), Ctrl+P (Print), Ctrl+Z (Undo)."""
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        for accel in ('<primary>n', '<primary>o', '<primary>s', '<primary>p', '<primary>z'):
            self.assertNotIn(Gtk.accelerator_parse(accel)[1:], taken, accel)
        self.assertEqual(shortcuts.ACCELS['app.now-playing'], ('<primary><shift>n',))

    def test_the_now_playing_tab_keys_are_not_accelerators(self):
        """Ctrl+Shift+U is GTK's Unicode entry in a text field: as an application
        accelerator, run before the focus widget, it would take that from the Search entry.
        The tab keys are the window's (keyboard.tab_action), Ctrl+Shift+L with them."""
        self.assertEqual(shortcuts.NOW_PLAYING_TABS, {
            'show-lyrics': ('<primary><shift>l',), 'show-queue': ('<primary><shift>u',)})
        taken = {Gtk.accelerator_parse(accel)[1:]
                 for accels in shortcuts.ACCELS.values() for accel in accels}
        self.assertNotIn(Gtk.accelerator_parse('<primary><shift>u')[1:], taken)

    def test_f11_is_the_full_screen_players(self):
        """The HIG's Fullscreen key, the one accelerator without a modifier (a function key,
        which no widget takes), and listed in the dialog though it is off while nothing
        plays."""
        self.assertEqual(shortcuts.ACCELS['win.fullscreen-player'], ('F11',))
        bare = [accel for accels in shortcuts.ACCELS.values() for accel in accels
                if not Gtk.accelerator_parse(accel)[2]]
        self.assertEqual(bare, ['F11'])
        self.assertIn('win.fullscreen-player', listed())


if __name__ == '__main__':
    unittest.main()
