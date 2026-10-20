# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The selection of a track list's selection mode (applemusic.selection): Track objects, not
positions, so a filter or a sort keeps what it still shows. GObject only, no display."""

import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.library import Item, Track
from applemusic.selection import Picks, Selection


def tracks(count):
    # Invented songs; two of one id, as a playlist holding a song twice has them.
    return [Track({'id': f'i.s{n % 4}', 'title': f'Song {n}', 'index': n}) for n in range(count)]


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.selection = Selection()
        self.changes = []
        self.selection.connect('changed', lambda selection: self.changes.append(
            (selection.active, selection.count)))
        self.shown = tracks(6)

    def test_the_mode_on_and_off(self):
        self.assertFalse(self.selection.active)
        self.selection.start()
        self.assertTrue(self.selection.active)
        self.assertEqual(self.changes, [(True, 0)])
        self.selection.start()  # on already: nothing
        self.assertEqual(len(self.changes), 1)
        self.selection.toggle(self.shown[0])
        self.selection.stop()
        self.assertFalse(self.selection.active)
        self.assertEqual(self.selection.count, 0)  # leaving clears it
        self.assertEqual(self.changes[-1], (False, 0))

    def test_a_toggle_starts_the_mode_and_flips_one_track(self):
        a, b = self.shown[0], self.shown[4]  # the same song's two entries
        self.selection.toggle(a)
        self.assertTrue(self.selection.active)
        self.assertTrue(self.selection.has(a))
        self.assertFalse(self.selection.has(b))  # each entry by itself
        self.selection.toggle(a)
        self.assertFalse(self.selection.has(a))
        self.assertTrue(self.selection.active)  # the mode stays

    def test_a_range_from_the_last_toggled(self):
        shown = self.shown
        self.selection.toggle(shown[1])
        self.selection.extend(shown, shown[3])
        self.assertEqual(self.selection.ordered(shown), shown[1:4])
        # From the same anchor again, upwards, keeping what is selected.
        self.selection.extend(shown, shown[0])
        self.assertEqual(self.selection.ordered(shown), shown[:4])
        # No anchor shown (a filter took it away): the track alone, and it is the anchor.
        selection = Selection()
        selection.extend(shown, shown[2])
        self.assertEqual(selection.ordered(shown), [shown[2]])
        selection.extend(shown, shown[4])
        self.assertEqual(selection.ordered(shown), shown[2:5])
        selection.extend(shown, Track({'id': 'i.gone'}))  # not shown: nothing
        self.assertEqual(selection.count, 3)

    def test_all_and_none(self):
        self.selection.select_all(self.shown)
        self.assertTrue(self.selection.active)
        self.assertEqual(self.selection.count, 6)
        self.selection.select_none()
        self.assertEqual(self.selection.count, 0)
        self.assertTrue(self.selection.active)

    def test_what_a_filter_hides_leaves_the_selection(self):
        shown = self.shown
        for track in shown[:3]:
            self.selection.toggle(track)
        self.assertFalse(self.selection.keep(shown))  # all still shown: nothing changes
        self.assertTrue(self.selection.keep(shown[1:]))
        self.assertEqual(self.selection.ordered(shown), shown[1:3])
        # The anchor gone with it: a range starts again from the track.
        self.selection.toggle(shown[1])
        self.selection.keep(shown[2:])
        self.selection.extend(shown[2:], shown[5])
        self.assertEqual(self.selection.ordered(shown), [shown[2], shown[5]])

    def test_ordered_follows_the_order_shown(self):
        shown = self.shown
        self.selection.toggle(shown[4])
        self.selection.toggle(shown[0])
        self.assertEqual(self.selection.ordered(shown), [shown[0], shown[4]])
        self.assertEqual(self.selection.ordered(list(reversed(shown))), [shown[4], shown[0]])
        self.assertEqual(Selection().ordered(shown), [])


class PicksTest(unittest.TestCase):
    """Add Songs…'s picks: songs from the library's list and a search's, each once by its
    kind and id, in the order picked."""

    def test_picked_once_wherever_it_shows(self):
        picks = Picks()
        changes = []
        picks.connect('changed', lambda picks: changes.append(picks.count))
        library = Track({'id': 'i.s1', 'title': 'Harbour Lights', 'type': 'library-songs'})
        again = Track({'id': 'i.s1', 'title': 'Harbour Lights', 'type': 'library-songs'})
        catalog = Item({'id': '1000000001', 'kind': 'song', 'title': 'Tidewater'})
        video = Item({'id': '1000000002', 'kind': 'video', 'title': 'Lantern'})
        self.assertTrue(picks.toggle(catalog))
        self.assertTrue(picks.toggle(library))
        self.assertTrue(picks.toggle(video))
        self.assertTrue(picks.has(again))  # the same song in another list
        self.assertEqual(picks.objects(), [catalog, library, video])
        self.assertEqual(Picks.key(video), ('video', '1000000002'))
        self.assertTrue(picks.toggle(again))  # unpicked from there
        self.assertFalse(picks.has(library))
        self.assertEqual(picks.objects(), [catalog, video])
        self.assertEqual(changes, [1, 2, 3, 2])

    def test_only_songs_and_videos(self):
        picks = Picks()
        album = Item({'id': 'l.alb1', 'kind': 'album', 'title': 'Tidewater'})
        self.assertFalse(picks.toggle(album))
        self.assertFalse(picks.toggle(Track({'title': 'No Id'})))
        self.assertFalse(picks.has(album))
        self.assertEqual(picks.count, 0)


if __name__ == '__main__':
    unittest.main()
