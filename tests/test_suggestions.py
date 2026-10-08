# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""suggestions.py: how many a playlist's page shows, the columns they take, and which songs
are shown, kept spare, offered and selected as answers come and songs are added."""

import unittest
from types import SimpleNamespace

from tests import ROOT  # noqa: F401  registers src/ as the applemusic package

from applemusic.suggestions import COUNT, MORE_COUNT, Suggestions, basis, columns_for, count


def songs(*numbers):
    return [SimpleNamespace(id=str(number)) for number in numbers]


def ids(items):
    return [item.id for item in items]


class CountTest(unittest.TestCase):
    def test_six_or_twelve(self):
        self.assertEqual((count(False), count(True)), (COUNT, MORE_COUNT))
        self.assertEqual((COUNT, MORE_COUNT), (6, 12))

    def test_columns_divide_the_count(self):
        # Six: 3 by 2, 2 by 3 or 6 by 1; twelve: 4, 3, 2 or 1 a row; never more than fit.
        for width, six, twelve in ((300, 1, 1), (611, 1, 1), (612, 2, 2), (924, 3, 3),
                                   (1236, 3, 4), (5000, 3, 4)):
            self.assertEqual(columns_for(width, 6, 300, 12), six, width)
            self.assertEqual(columns_for(width, 12, 300, 12), twelve, width)
        self.assertEqual(columns_for(1236, 5, 300, 12), 1)  # five: only one divides it
        self.assertEqual(columns_for(1236, 4, 300, 12), 4)
        self.assertEqual(columns_for(100, 0, 300), 1)


class BasisTest(unittest.TestCase):
    def test_the_same_songs_in_any_order_and_another_once_they_change(self):
        held = {'i.1', '2001', 'i.2'}
        self.assertEqual(basis(held), basis(['i.2', 'i.1', '2001', '2001', '', None]))
        self.assertNotEqual(basis(held), basis(held | {'2002'}))  # a song added
        self.assertNotEqual(basis(held), basis(held - {'i.2'}))  # one removed
        self.assertNotEqual(basis(['1', '0']), basis(['10']))  # ids kept apart
        self.assertEqual(len(basis(())), 16)


class SuggestionsTest(unittest.TestCase):
    def test_an_answer_shown_and_spare_less_what_is_held(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2, 3, 4, 5, 2), held={'2'})
        self.assertEqual(ids(suggestions.shown), ['1', '3', '4'])
        self.assertEqual(ids(suggestions.spares), ['5'])
        self.assertEqual(suggestions.offered, ['1', '3', '4'])
        self.assertFalse(suggestions.wants_more())

    def test_an_added_song_gives_its_place_to_the_next_spare(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2, 3, 4, 5))
        self.assertTrue(suggestions.fill(SimpleNamespace(id='2'), held={'4'}))
        self.assertEqual(ids(suggestions.shown), ['1', '5', '3'])  # 4 is held now
        self.assertEqual(suggestions.selected, ['2'])
        self.assertEqual(suggestions.offered, ['1', '2', '3', '5'])
        self.assertTrue(suggestions.wants_more())
        # None left: the place is given up, the rest keep theirs.
        suggestions.fill(SimpleNamespace(id='1'))
        self.assertEqual(ids(suggestions.shown), ['5', '3'])
        self.assertFalse(suggestions.fill(SimpleNamespace(id='9')))  # not shown

    def test_an_add_that_failed_gives_the_song_its_place_back(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2, 3, 4, 5))
        suggestions.fill(SimpleNamespace(id='2'))
        self.assertTrue(suggestions.restore(SimpleNamespace(id='2')))
        self.assertEqual(ids(suggestions.shown), ['1', '2', '3'])
        self.assertEqual(ids(suggestions.spares), ['4', '5'])  # the spare, first again
        self.assertEqual(suggestions.selected, [])
        self.assertFalse(suggestions.restore(SimpleNamespace(id='2')))  # once

    def test_a_given_up_place_is_given_back_while_there_is_room(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2, 3))
        suggestions.fill(SimpleNamespace(id='2'))  # no spare: the place is given up
        self.assertEqual(ids(suggestions.shown), ['1', '3'])
        self.assertTrue(suggestions.restore(SimpleNamespace(id='2')))
        self.assertEqual(ids(suggestions.shown), ['1', '2', '3'])

    def test_a_failed_add_is_not_shown_again_where_its_place_has_gone(self):
        suggestions = Suggestions(2)
        suggestions.take(songs(1, 2, 3, 4, 5, 6))
        suggestions.fill(SimpleNamespace(id='1'))
        suggestions.take(songs(7, 8))  # a Refresh: what was shown is replaced
        self.assertFalse(suggestions.restore(SimpleNamespace(id='1')))
        self.assertEqual(ids(suggestions.shown), ['7', '8'])
        self.assertEqual(suggestions.selected, [])
        # Held by now (it was added after all, as a sync shows): not shown again either.
        suggestions.fill(SimpleNamespace(id='7'))
        self.assertFalse(suggestions.restore(SimpleNamespace(id='7'), held={'7'}))

    def test_a_few_more_fill_empty_places_then_wait_as_spares(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2))
        self.assertTrue(suggestions.extend(songs(2, 3, 4, 5)))  # 2 was offered already
        self.assertEqual(ids(suggestions.shown), ['1', '2', '3'])
        self.assertEqual(ids(suggestions.spares), ['4', '5'])
        self.assertFalse(suggestions.extend(songs(1, 4)))  # nothing new

    def test_a_new_answer_leaves_out_what_was_offered_or_added(self):
        suggestions = Suggestions(2)
        suggestions.take(songs(1, 2, 3))
        suggestions.fill(SimpleNamespace(id='1'))
        suggestions.exhausted = True
        suggestions.take(songs(1, 2, 3, 6, 7, 8))
        self.assertEqual(ids(suggestions.shown), ['6', '7'])
        self.assertEqual(ids(suggestions.spares), ['8'])
        self.assertEqual(suggestions.selected, ['1'])
        self.assertFalse(suggestions.exhausted)

    def test_held_songs_give_their_places_up(self):
        suggestions = Suggestions(3)
        suggestions.take(songs(1, 2, 3, 4))
        suggestions.drop_held({'1', '3'})
        self.assertEqual(ids(suggestions.shown), ['4', '2'])

    def test_more_or_fewer_shown(self):
        suggestions = Suggestions(2)
        suggestions.take(songs(1, 2, 3, 4, 5))
        suggestions.set_count(4)
        self.assertEqual(ids(suggestions.shown), ['1', '2', '3', '4'])
        suggestions.set_count(2)
        self.assertEqual(ids(suggestions.shown), ['1', '2'])
        self.assertEqual(ids(suggestions.spares), ['3', '4', '5'])

    def test_rotate_shows_the_next_spares(self):
        suggestions = Suggestions(2)
        suggestions.take(songs(1, 2, 3, 4, 5))
        self.assertTrue(suggestions.rotate(held={'3'}))
        self.assertEqual(ids(suggestions.shown), ['4', '5'])
        self.assertFalse(suggestions.rotate())  # no spares left


if __name__ == '__main__':
    unittest.main()
