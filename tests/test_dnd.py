# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/dnd.py: the auto-scroll's speed and a reorder's insertion point as pure functions,
and, with GTK, the marks a DropFeedback puts on widgets, its auto-scroll, and a drag
source's prepare."""

import unittest

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')

from tests import ROOT  # noqa: E402,F401  registers src/ as applemusic
from tests.gtk import pump, requires_gtk, wait_for  # noqa: E402

from applemusic.library import ItemRefs, Ref  # noqa: E402
from applemusic.widgets import dnd  # noqa: E402


class PureTest(unittest.TestCase):
    def test_scroll_step(self):
        step = dnd.scroll_step
        self.assertEqual(step(200, 400), 0)  # the middle
        self.assertEqual(step(0, 400, edge=32, speed=12), -12)  # at the top edge
        self.assertEqual(step(-10, 400, edge=32, speed=12), -12)  # past it
        self.assertEqual(step(16, 400, edge=32, speed=12), -6)  # half way into the band
        self.assertEqual(step(400, 400, edge=32, speed=12), 12)
        self.assertEqual(step(384, 400, edge=32, speed=12), 6)
        self.assertEqual(step(32, 400, edge=32), 0)  # the band's inner line
        self.assertEqual(step(10, 50, edge=32), 0)  # too short for both edges
        self.assertEqual(step(10, 400, edge=0), 0)

    def test_insertion_point(self):
        tops, heights = [0, 40, 80], [40, 40, 40]
        point = dnd.insertion_point
        self.assertEqual(point(tops, heights, 5), (0, False))
        self.assertEqual(point(tops, heights, 25), (0, True))
        self.assertEqual(point(tops, heights, 41), (1, False))
        self.assertEqual(point(tops, heights, 100), (2, True))
        self.assertEqual(point(tops, heights, 500), (2, True))  # below the last
        self.assertEqual(point(tops, heights, -5), (0, False))  # above the first
        self.assertEqual(point([], [], 10), (-1, False))

    def test_no_drag_in_progress(self):
        self.assertIsNone(dnd.current())


@requires_gtk
class FeedbackTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gtk

        self.Gtk = Gtk
        self.rows = [Gtk.Label(label=str(n)) for n in range(3)]

    def marks(self):
        return [[name for name in dnd.MARKS if row.has_css_class(name)] for row in self.rows]

    def test_one_mark_at_a_time(self):
        feedback = dnd.DropFeedback()
        feedback.highlight(self.rows[0])
        self.assertEqual(self.marks(), [['drop-highlight'], [], []])
        feedback.insert(self.rows[1], after=True)
        self.assertEqual(self.marks(), [[], ['drop-after'], []])
        feedback.insert(self.rows[1], after=False)
        self.assertEqual(self.marks(), [[], ['drop-before'], []])
        self.assertEqual(feedback.marked(), (self.rows[1], 'drop-before'))
        feedback.highlight(None)
        self.assertEqual(self.marks(), [[], [], []])
        feedback.highlight(self.rows[2])
        feedback.clear()
        self.assertEqual(self.marks(), [[], [], []])
        self.assertIsNone(feedback.marked())

    def test_it_holds_its_widgets_weakly(self):
        feedback = dnd.DropFeedback()
        label = self.Gtk.Label()
        feedback.highlight(label)
        scrolled = self.Gtk.ScrolledWindow()
        feedback.scrolled = scrolled
        freed = []
        label.weak_ref(lambda: freed.append('label'))
        scrolled.weak_ref(lambda: freed.append('scrolled'))
        del label, scrolled
        self.assertEqual(sorted(freed), ['label', 'scrolled'])
        self.assertIsNone(feedback.marked())
        self.assertIsNone(feedback.scrolled)
        feedback.motion(0)  # nothing to scroll
        feedback.clear()

    def test_auto_scroll_near_an_edge(self):
        Gtk = self.Gtk
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for n in range(60):
            box.append(Gtk.Label(label=f'Row {n}'))
        scrolled = Gtk.ScrolledWindow(child=box)
        window = Gtk.Window(child=scrolled, default_width=200, default_height=200)
        window.present()
        self.addCleanup(window.destroy)
        adjustment = scrolled.get_vadjustment()
        self.assertTrue(wait_for(lambda: adjustment.get_upper() > adjustment.get_page_size()
                                 and scrolled.get_height() > 0))
        feedback = dnd.DropFeedback(scrolled)
        feedback.motion(scrolled.get_height() - 1)  # at the bottom edge: scrolls down
        self.assertTrue(wait_for(lambda: adjustment.get_value() > 0))
        feedback.motion(scrolled.get_height() / 2)  # the middle: stops
        pump()
        stopped = adjustment.get_value()
        pump()
        self.assertEqual(adjustment.get_value(), stopped)
        feedback.motion(1)  # the top edge: back up, and clear() stops it
        self.assertTrue(wait_for(lambda: adjustment.get_value() < stopped))
        feedback.clear()
        pump()
        now = adjustment.get_value()
        pump()
        self.assertEqual(adjustment.get_value(), now)

    def test_a_source_prepares_what_find_answers(self):
        Gtk = self.Gtk
        box = Gtk.Box()
        asked = []
        refs = ItemRefs([Ref('playlist', 'p.1', 'One')])

        def find(x, y):
            asked.append((x, y))
            return (refs, box) if x < 10 else None

        source = dnd.attach_source(box, find)
        self.assertIsInstance(source, Gtk.DragSource)
        self.assertIsNotNone(source.emit('prepare', 2.0, 3.0))
        self.assertIsNone(source.emit('prepare', 20.0, 3.0))
        self.assertEqual(asked, [(2.0, 3.0), (20.0, 3.0)])
        self.assertIsNone(dnd.current())  # only a drag that began sets it


if __name__ == '__main__':
    unittest.main()
