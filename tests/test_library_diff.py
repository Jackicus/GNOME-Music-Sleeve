# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""apply_diff() (library/diff.py): a store brought to new contents with the fewest splices."""

import unittest

from tests import ROOT  # noqa: F401  (registers src/ as applemusic)

from applemusic.library import Item
from applemusic.library import diff as diff_module


class TestApplyDiff(unittest.TestCase):
    """apply_diff(): a store brought to a new list with the fewest splices."""

    def setUp(self):
        self.objects = [Item({'id': f'l.{n}'}) for n in range(8)]

    def check(self, before, after, splices, old=False):
        from gi.repository import Gio
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [self.objects[n] for n in before])
        seen = []
        store.connect('items-changed', lambda _store, *change: seen.append(change))
        items = [self.objects[n] for n in after]
        diff_module.apply_diff(store, items, list(store) if old else None)
        self.assertEqual([store.get_item(n) for n in range(store.get_n_items())], items)
        if splices is not None:
            self.assertEqual(seen, splices)
        return seen

    def test_the_same_list_changes_nothing(self):
        self.check([0, 1, 2], [0, 1, 2], [])
        self.check([], [], [])

    def test_the_unchanged_ends_are_left_alone(self):
        self.check([0, 1, 2, 3, 4], [0, 1, 2, 7, 4], [(3, 1, 1)])
        self.check([0, 1, 2, 3, 4], [0, 1, 5, 2, 3, 4], [(2, 0, 1)])
        self.check([0, 1, 2, 3, 4], [0, 3, 4], [(1, 2, 0)], old=True)
        self.check([], [0, 1], [(0, 0, 2)])
        self.check([0, 1], [], [(0, 2, 0)])

    def test_a_middle_sharing_objects_is_diffed(self):
        # 2 goes, 5 comes after 3: two splices, the later first (5 at its old position), and
        # 3 untouched.
        self.check([0, 1, 2, 3, 4], [0, 1, 3, 5, 4], [(4, 0, 1), (2, 1, 0)])

    def test_runs_that_went_and_came_are_found_in_one_walk(self):
        # Changes at both ends and in the middle, nothing moved: a splice for each.
        self.check([0, 1, 2, 3, 4, 5], [6, 1, 2, 4, 5, 7],
                   [(6, 0, 1), (3, 1, 0), (0, 1, 1)])

    def test_moves_and_repeats_are_still_diffed(self):
        seen = self.check([0, 1, 2, 3, 4], [0, 3, 2, 1, 4], None)  # 1 and 3 swapped
        self.assertTrue(all(0 < position and position + removed < 5
                            for position, removed, _added in seen))  # 0 and 4 untouched
        self.check([0, 1, 2], [0, 1, 1, 2], None)  # the same object twice

    def test_a_wholly_new_list_is_one_splice(self):
        self.check([0, 1, 2], [3, 4, 5, 6], [(0, 3, 4)])


if __name__ == '__main__':
    unittest.main()
