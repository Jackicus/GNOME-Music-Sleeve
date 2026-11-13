# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets.util.mirror_start: a Gtk.Inscription's text goes to its start in a right-to-left
window, as a Gtk.Label's does (GTK mirrors a label's xalign, never an inscription's)."""

import unittest

from tests.gtk import requires_gtk


@requires_gtk
class MirrorStartTest(unittest.TestCase):
    def test_right_to_left_mirrors_and_left_to_right_keeps(self):
        from gi.repository import Gtk

        from applemusic.widgets.util import mirror_start

        start, end = Gtk.Inscription(xalign=0), Gtk.Inscription(xalign=1)
        mirror_start(start, end)
        self.assertEqual((start.get_xalign(), end.get_xalign()), (0, 1))
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
        self.addCleanup(Gtk.Widget.set_default_direction, Gtk.TextDirection.LTR)
        start, end = Gtk.Inscription(xalign=0), Gtk.Inscription(xalign=1)
        mirror_start(start, end)
        self.assertEqual((start.get_xalign(), end.get_xalign()), (1, 0))


if __name__ == '__main__':
    unittest.main()
