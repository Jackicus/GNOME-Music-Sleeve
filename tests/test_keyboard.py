# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The window's key policy (applemusic.keyboard): which playback action a key runs, given
where the focus is, as a table; the context-menu and main-menu keys agree with the shortcuts
table. Widget classes only, no display."""

import unittest

import gi

from tests import ROOT  # noqa: F401  registers src/ as applemusic

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk, Gtk  # noqa: E402

from applemusic import keyboard, shortcuts  # noqa: E402

PRIMARY = Gdk.ModifierType.CONTROL_MASK
NO_FOCUS = type(None)


class ListItemWidget(Gtk.Widget):
    """A stand-in for a grid's tile or a list's row: a plain widget."""


def route(accel, focus_type=NO_FOCUS, dialog_open=False, in_popover=False, disabled=()):
    _ok, keyval, mods = Gtk.accelerator_parse(accel)
    return keyboard.playback_action(keyval, mods, focus_type, dialog_open, in_popover,
                                    lambda name: name not in disabled)


class RoutingTest(unittest.TestCase):
    def test_the_playback_keys_with_nothing_in_the_way(self):
        self.assertEqual(route('space'), 'play-pause')
        self.assertEqual(route('KP_Space'), 'play-pause')
        self.assertEqual(route('<primary>Right'), 'next')
        self.assertEqual(route('<primary>Left'), 'previous')
        self.assertEqual(route('space', ListItemWidget), 'play-pause')
        self.assertEqual(route('<primary>Right', Gtk.Scale), 'next')

    def test_other_keys_are_not_playback(self):
        for accel in ('Right', 'Left', 'Return', 'a', '<primary>space', '<shift>Right', 'F10'):
            with self.subTest(accel=accel):
                self.assertIsNone(route(accel))

    def test_typing_keeps_every_key(self):
        for focus_type in (Gtk.Text, Gtk.Entry, Gtk.SearchEntry, Gtk.TextView):
            for accel in ('space', '<primary>Right', '<primary>Left'):
                with self.subTest(focus=focus_type.__name__, accel=accel):
                    self.assertIsNone(route(accel, focus_type))

    def test_space_belongs_to_what_space_presses(self):
        # GTK's own binding: Space presses a button (a toggle, a menu button's inner button,
        # a toggle group's toggle), flips a switch or a check box, activates a boxed-list
        # row. The skip keys still go to playback there.
        for focus_type in (Gtk.Button, Gtk.ToggleButton, Gtk.LinkButton, Gtk.Switch,
                           Gtk.CheckButton, Gtk.ListBoxRow):
            with self.subTest(focus=focus_type.__name__):
                self.assertIsNone(route('space', focus_type))
                self.assertIsNone(route('KP_Space', focus_type))
                self.assertEqual(route('<primary>Right', focus_type), 'next')

    def test_space_plays_where_nothing_presses(self):
        for focus_type in (NO_FOCUS, ListItemWidget, Gtk.Scale, Gtk.Widget):
            with self.subTest(focus=focus_type.__name__):
                self.assertEqual(route('space', focus_type), 'play-pause')

    def test_a_dialog_or_a_menu_keeps_the_keys(self):
        self.assertIsNone(route('space', dialog_open=True))
        self.assertIsNone(route('<primary>Right', in_popover=True))

    def test_a_disabled_action_does_not_run(self):
        self.assertIsNone(route('space', disabled=('play-pause',)))
        self.assertEqual(route('<primary>Right', disabled=('play-pause',)), 'next')


def tab_route(accel, focus_type=NO_FOCUS, dialog_open=False, in_popover=False, disabled=(),
              capital=False):
    _ok, keyval, mods = Gtk.accelerator_parse(accel)
    if capital:  # a real press with Shift held reports the capital letter
        keyval = Gdk.keyval_to_upper(keyval)
    return keyboard.tab_action(keyval, mods, focus_type, dialog_open, in_popover,
                               lambda name: name not in disabled)


class TabRoutingTest(unittest.TestCase):
    """Ctrl+Shift+L and Ctrl+Shift+U: Now Playing on its Lyrics or Up Next tab, except where
    the keys are a text field's (Ctrl+Shift+U is GTK's Unicode entry)."""

    def test_the_tab_keys(self):
        self.assertEqual(tab_route('<primary><shift>l'), 'show-lyrics')
        self.assertEqual(tab_route('<primary><shift>u'), 'show-queue')
        self.assertEqual(tab_route('<primary><shift>l', capital=True), 'show-lyrics')
        self.assertEqual(tab_route('<primary><shift>u', Gtk.ToggleButton, capital=True),
                         'show-queue')
        for accel in ('<primary>l', '<primary>u', 'l', '<shift>u', 'space'):
            with self.subTest(accel=accel):
                self.assertIsNone(tab_route(accel))
        self.assertIsNone(route('<primary><shift>u'))  # not a playback key

    def test_typing_a_dialog_or_a_menu_keeps_them(self):
        for focus_type in (Gtk.Text, Gtk.SearchEntry, Gtk.TextView):
            with self.subTest(focus=focus_type.__name__):
                self.assertIsNone(tab_route('<primary><shift>u', focus_type, capital=True))
                self.assertIsNone(tab_route('<primary><shift>l', focus_type, capital=True))
        self.assertIsNone(tab_route('<primary><shift>l', dialog_open=True))
        self.assertIsNone(tab_route('<primary><shift>u', in_popover=True))

    def test_a_disabled_action_does_not_run(self):
        self.assertIsNone(tab_route('<primary><shift>l', disabled=('show-lyrics',)))
        self.assertEqual(tab_route('<primary><shift>u', disabled=('show-lyrics',)),
                         'show-queue')


class MoveStepTest(unittest.TestCase):
    """Alt+Up and Alt+Down on a playlist's focused song (shortcuts.MOVE_UP, MOVE_DOWN)."""

    def step(self, accel, focus_type=ListItemWidget, dialog_open=False, in_popover=False):
        _ok, keyval, mods = Gtk.accelerator_parse(accel)
        return keyboard.move_step(keyval, mods, focus_type, dialog_open, in_popover)

    def test_the_keys(self):
        self.assertEqual(self.step(shortcuts.MOVE_UP), -1)
        self.assertEqual(self.step(shortcuts.MOVE_DOWN), 1)
        self.assertEqual(self.step('<alt>KP_Up'), -1)
        self.assertEqual(self.step('<alt>KP_Down'), 1)
        for other in ('Up', 'Down', '<primary>Up', '<alt><shift>Up', '<alt>Left'):
            self.assertIsNone(self.step(other), other)

    def test_typing_a_dialog_or_a_menu_keeps_them(self):
        self.assertIsNone(self.step(shortcuts.MOVE_UP, Gtk.Text))
        self.assertIsNone(self.step(shortcuts.MOVE_UP, dialog_open=True))
        self.assertIsNone(self.step(shortcuts.MOVE_DOWN, in_popover=True))


class VolumeStepTest(unittest.TestCase):
    """Ctrl+Up and Ctrl+Down (shortcuts.VOLUME_UP, VOLUME_DOWN): the volume a step, except
    where the keys are the focused widget's own."""

    def step(self, accel, focus_type=NO_FOCUS, dialog_open=False, in_popover=False):
        _ok, keyval, mods = Gtk.accelerator_parse(accel)
        return keyboard.volume_step(keyval, mods, focus_type, dialog_open, in_popover)

    def test_the_keys(self):
        self.assertEqual(self.step(shortcuts.VOLUME_UP), 1)
        self.assertEqual(self.step(shortcuts.VOLUME_DOWN), -1)
        self.assertEqual(self.step('<primary>KP_Up'), 1)
        self.assertEqual(self.step('<primary>KP_Down'), -1)
        for other in ('Up', 'Down', '<alt>Up', '<primary><shift>Up', '<primary>Right',
                      '<primary>Page_Up'):
            self.assertIsNone(self.step(other), other)

    def test_a_grid_s_tile_a_list_s_row_or_a_button_lets_them_go(self):
        # The grids and lists select nothing: there Ctrl+Up and Ctrl+Down only move the
        # focus as Up and Down do.
        for focus_type in (NO_FOCUS, ListItemWidget, Gtk.Button, Gtk.ToggleButton,
                           Gtk.ScaleButton, Gtk.ListView, Gtk.GridView, Gtk.Widget):
            with self.subTest(focus=focus_type.__name__):
                self.assertEqual(self.step(shortcuts.VOLUME_UP, focus_type), 1)

    def test_typing_a_slider_or_a_boxed_list_keeps_them(self):
        # A text view's paragraph keys, a slider's page step (the seek slider), a boxed
        # list's (the sidebar's) move of the focus without selecting.
        for focus_type in (Gtk.Text, Gtk.Entry, Gtk.SearchEntry, Gtk.TextView, Gtk.Scale,
                           Gtk.Range, Gtk.ListBoxRow):
            with self.subTest(focus=focus_type.__name__):
                self.assertIsNone(self.step(shortcuts.VOLUME_UP, focus_type))
                self.assertIsNone(self.step(shortcuts.VOLUME_DOWN, focus_type))

    def test_a_dialog_or_a_menu_keeps_them(self):
        self.assertIsNone(self.step(shortcuts.VOLUME_UP, dialog_open=True))
        self.assertIsNone(self.step(shortcuts.VOLUME_DOWN, in_popover=True))

    def test_not_playback_tab_or_move_keys(self):
        self.assertIsNone(route(shortcuts.VOLUME_UP))
        self.assertIsNone(tab_route(shortcuts.VOLUME_DOWN))
        _ok, keyval, mods = Gtk.accelerator_parse(shortcuts.VOLUME_UP)
        self.assertIsNone(keyboard.move_step(keyval, mods, ListItemWidget, False, False))


class SearchTargetTest(unittest.TestCase):
    """Ctrl+F: the page's own filter when it has something to filter, else Search."""

    class Bar:
        def __init__(self, available):
            self.available = available

    class Page:
        def __init__(self, bar):
            self.filter_bar = bar

        def focus_filter(self):
            return True

    def test_a_page_with_a_filter_to_show_takes_it(self):
        self.assertEqual(keyboard.search_target(self.Page(self.Bar(True))), 'filter')

    def test_anything_else_goes_to_search(self):
        self.assertEqual(keyboard.search_target(self.Page(self.Bar(False))), 'search')  # empty
        self.assertEqual(keyboard.search_target(self.Page(None)), 'search')  # an album's grid
        self.assertEqual(keyboard.search_target(object()), 'search')  # Home
        self.assertEqual(keyboard.search_target(None), 'search')  # nothing shown yet


class KeysTest(unittest.TestCase):
    def test_the_playback_keys_are_the_shortcuts_tables(self):
        names = set(keyboard.PLAYBACK_KEYS.values())
        self.assertEqual(names, set(shortcuts.PLAYBACK))
        for action, accels in shortcuts.PLAYBACK.items():
            for accel in accels:
                _ok, keyval, mods = Gtk.accelerator_parse(accel)
                self.assertEqual(keyboard.PLAYBACK_KEYS[(keyval, int(mods))], action)

    def test_the_tab_keys_are_the_shortcuts_tables(self):
        self.assertEqual(set(keyboard.TAB_KEYS.values()), set(shortcuts.NOW_PLAYING_TABS))
        for action, accels in shortcuts.NOW_PLAYING_TABS.items():
            for accel in accels:
                _ok, keyval, mods = Gtk.accelerator_parse(accel)
                self.assertEqual(keyboard.TAB_KEYS[(keyval, int(mods))], action)

    def test_the_volume_keys_are_the_shortcuts_tables(self):
        for accel, step in ((shortcuts.VOLUME_UP, 1), (shortcuts.VOLUME_DOWN, -1)):
            _ok, keyval, mods = Gtk.accelerator_parse(accel)
            self.assertEqual(keyboard.VOLUME_KEYS[(keyval, int(mods))], step)

    def test_the_main_menu_key(self):
        self.assertTrue(keyboard.is_main_menu(Gdk.KEY_F10, 0))
        self.assertFalse(keyboard.is_main_menu(Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK))
        self.assertFalse(keyboard.is_main_menu(Gdk.KEY_F9, 0))

    def test_context_menu_keys_match(self):
        """The keys context_menu binds are the ones the shortcuts dialog lists."""
        from applemusic.widgets import context_menu

        bound = {Gtk.accelerator_parse(alt)[1:] for alt in context_menu.MENU_KEYS.split('|')}
        listed = {Gtk.accelerator_parse(alt)[1:] for alt in shortcuts.CONTEXT_MENU.split()}
        self.assertEqual(bound, listed)
        self.assertTrue(all(ok for ok in bound))
        self.assertIsNotNone(Gtk.ShortcutTrigger.parse_string(context_menu.MENU_KEYS))


if __name__ == '__main__':
    unittest.main()
