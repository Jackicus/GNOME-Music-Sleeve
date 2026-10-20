# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The song tables' optional columns (src/song_columns.py): the setting, the menu's
section and its actions."""

import unittest

from tests import ROOT  # noqa: F401  (before applemusic: the test environment)

from gi.repository import Gio, GLib

from applemusic import song_columns
from tests.gtk import SCHEMA_ID, requires_gtk


class SettingTest(unittest.TestCase):
    def setUp(self):
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.addCleanup(self.settings.reset, song_columns.SETTING)

    def test_none_until_chosen_and_in_the_tables_order(self):
        self.assertEqual(song_columns.shown(self.settings), frozenset())
        self.assertEqual(song_columns.shown(None), frozenset())  # a stand-in application's
        song_columns.set_shown(self.settings, 'year', True)
        song_columns.set_shown(self.settings, 'genre', True)
        self.assertEqual(self.settings.get_strv(song_columns.SETTING), ['genre', 'year'])
        self.assertEqual(song_columns.shown(self.settings), {'genre', 'year'})
        song_columns.set_shown(self.settings, 'genre', False)
        self.assertEqual(self.settings.get_strv(song_columns.SETTING), ['year'])

    def test_unknown_names_are_ignored(self):
        self.settings.set_strv(song_columns.SETTING, ['composer', 'year'])
        self.assertEqual(song_columns.shown(self.settings), {'year'})
        song_columns.set_shown(self.settings, 'composer', True)
        self.assertEqual(self.settings.get_strv(song_columns.SETTING), ['composer', 'year'])
        song_columns.set_shown(None, 'genre', True)  # nothing to write to: nothing happens

    def test_year_text(self):
        self.assertEqual(song_columns.year_text(2019), '2019')
        self.assertEqual(song_columns.year_text(0), '')


class MenuTest(unittest.TestCase):
    def test_check_items_hidden_while_their_action_is_disabled(self):
        section = song_columns.menu_section('songs')
        self.assertEqual(section.get_n_items(), len(song_columns.OPTIONAL))
        for position, name in enumerate(song_columns.OPTIONAL):
            with self.subTest(column=name):
                action = section.get_item_attribute_value(position, 'action', None)
                self.assertEqual(action.get_string(), f'songs.column-{name}')
                hidden = section.get_item_attribute_value(position, 'hidden-when', None)
                self.assertEqual(hidden.get_string(), 'action-disabled')
                label = section.get_item_attribute_value(position, 'label', None)
                self.assertEqual(label.get_string(), song_columns.labels()[name])

    @requires_gtk  # the page modules' templates
    def test_mnemonics_differ_from_the_sort_menus(self):
        # They share the Songs page's Sort and Filter menu and a playlist's Sort By.
        from applemusic.pages.detail import PLAYLIST_SORTS
        from applemusic.pages.grid import sort_labels

        def mnemonic(label):
            return label[label.index('_') + 1].lower()

        others = [label() for label, _names in PLAYLIST_SORTS.values()]
        others += list(sort_labels().values())
        others += ['_Title', '_Artist', 'Al_bum', '_Genre', '_Year', 'T_ime']  # songs.blp's
        taken = {mnemonic(label) for label in others}
        mine = [mnemonic(label) for label in song_columns.labels().values()]
        self.assertEqual(len(mine), len(set(mine)))
        self.assertFalse(taken & set(mine), (taken, mine))

    def test_actions_hand_the_choice_on_and_follow_the_columns(self):
        group = Gio.SimpleActionGroup()
        chosen = []
        actions = song_columns.make_actions(group, lambda name, show: chosen.append(
            (name, show)))
        self.assertEqual(set(actions), set(song_columns.OPTIONAL))
        group.change_action_state('column-year', GLib.Variant('b', True))
        self.assertEqual(chosen, [('year', True)])
        self.assertFalse(actions['year'].get_state().get_boolean())  # the page sets it
        song_columns.show_states(actions, {'year'}, available=False)
        self.assertTrue(actions['year'].get_state().get_boolean())
        self.assertFalse(actions['genre'].get_state().get_boolean())
        self.assertFalse(actions['year'].get_enabled())  # no room: the items hide
        song_columns.show_states(actions, set(), available=True)
        self.assertTrue(actions['genre'].get_enabled())
        self.assertFalse(actions['year'].get_state().get_boolean())


if __name__ == '__main__':
    unittest.main()
