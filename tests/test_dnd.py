# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/dnd.py: the auto-scroll's speed, a reorder's insertion point and a drag's links as
pure functions, and, with GTK, the marks a DropFeedback puts on widgets, its auto-scroll, a
drag source's prepare and the formats and values its content offers."""

import unittest

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')

from tests import ROOT  # noqa: E402,F401  registers src/ as applemusic
from tests.gtk import pump, requires_gtk, wait_for  # noqa: E402

from applemusic.library import Item, ItemRefs, Ref, Track  # noqa: E402
from applemusic.widgets import dnd  # noqa: E402

# Invented: a catalog album with its own page, two songs with catalog ids, an upload.
ALBUM = Item({'id': '1000000002', 'kind': 'album', 'title': 'Harbour Suite',
              'url': 'https://music.apple.com/gb/album/harbour-suite/1000000002'})
SONG = Track({'id': 'i.song1', 'catalogId': '1000000001', 'title': 'Harbour Lights',
              'type': 'library-songs', 'index': 0}, play={'kind': 'album', 'id': 'l.alb1'})
OTHER_SONG = Track({'id': '1000000009', 'catalogId': '1000000009', 'title': 'Shoreline',
                    'index': 1}, play={'kind': 'album', 'id': 'l.alb1'})
UPLOAD = Track({'id': 'i.song2', 'title': 'Demo Take', 'index': 2},
               play={'kind': 'album', 'id': 'l.alb1'})
SONG_URL = 'https://music.apple.com/gb/song/1000000001'
OTHER_URL = 'https://music.apple.com/gb/song/1000000009'


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

    def test_links_as_text(self):
        self.assertEqual(dnd.uri_list([SONG_URL, OTHER_URL]), f'{SONG_URL}\r\n{OTHER_URL}\r\n')
        self.assertEqual(dnd.plain_text([SONG_URL, OTHER_URL]), f'{SONG_URL}\n{OTHER_URL}')
        self.assertEqual(dnd.plain_text([SONG_URL]), SONG_URL)
        self.assertEqual(dnd.uri_list([]), '')

    def test_no_drag_in_progress(self):
        self.assertIsNone(dnd.current())
        self.assertEqual(dnd.offered(), 0)

    def test_the_drag_in_progress_and_what_its_source_offers(self):
        from gi.repository import Gdk

        refs = ItemRefs([Ref('song', 'i.1', 'One')])
        self.addCleanup(dnd._set_current, None)
        dnd._set_current(refs, Gdk.DragAction.MOVE)
        self.assertIs(dnd.current(), refs)
        self.assertEqual(dnd.offered(), Gdk.DragAction.MOVE)
        dnd._set_current(None, Gdk.DragAction.MOVE)
        self.assertEqual(dnd.offered(), 0)

    def test_choose_action(self):
        from gi.repository import Gdk

        copy, move = Gdk.DragAction.COPY, Gdk.DragAction.MOVE
        choose = dnd.choose_action
        self.assertEqual(choose(copy | move), copy)
        self.assertEqual(choose(move), move)  # a sidebar row's drag offers only MOVE
        self.assertEqual(choose(copy | move, preferred=move), move)
        self.assertEqual(choose(copy, preferred=move), copy)
        self.assertEqual(choose(Gdk.DragAction.LINK), 0)
        self.assertEqual(choose(0), 0)

    def test_shift_held(self):
        from gi.repository import Gdk

        copy, move = Gdk.DragAction.COPY, Gdk.DragAction.MOVE
        shift = Gdk.ModifierType.SHIFT_MASK
        held = dnd.shift_held
        self.assertFalse(held(copy, copy | move, 0))
        self.assertTrue(held(copy, copy | move, shift))  # the keyboard says so
        self.assertTrue(held(move, copy | move, 0))  # Shift made the drop a move
        self.assertFalse(held(move, move, 0))  # a source that offers only MOVE
        self.assertTrue(held(move, move, shift))
        self.assertFalse(held(copy, copy | move, Gdk.ModifierType.CONTROL_MASK))


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



@requires_gtk
class ContentTest(unittest.TestCase):
    """What a drag offers: the ItemRefs first, for the app's own targets, and the links."""

    def read(self, content, mime):
        from gi.repository import Gio

        out = Gio.MemoryOutputStream.new_resizable()
        done = []
        content.write_mime_type_async(mime, out, 0, None,
                                      lambda source, result: done.append(
                                          source.write_mime_type_finish(result)))
        self.assertTrue(wait_for(lambda: done))
        out.close()
        return bytes(out.steal_as_bytes().get_data()).decode()

    def test_songs_offer_their_links_one_a_line(self):
        refs = ItemRefs.for_objects([SONG, UPLOAD, OTHER_SONG])
        content = dnd.provider(refs, 'gb')
        formats = content.ref_formats()
        self.assertEqual(formats.get_gtypes()[0], ItemRefs.__gtype__)
        for mime in (dnd.URI_LIST, *dnd.PLAIN_TEXT):
            self.assertTrue(formats.contain_mime_type(mime), mime)
        self.assertEqual(self.read(content, dnd.URI_LIST), f'{SONG_URL}\r\n{OTHER_URL}\r\n')
        for mime in dnd.PLAIN_TEXT:
            self.assertEqual(self.read(content, mime), f'{SONG_URL}\n{OTHER_URL}')

    def test_the_apps_own_targets_still_take_the_item_refs(self):
        from gi.repository import Gdk

        content = dnd.provider(ItemRefs.for_objects([ALBUM]))
        wanted = Gdk.ContentFormats.new_for_gtype(ItemRefs.__gtype__)
        self.assertEqual(wanted.match_gtype(content.ref_formats()), ItemRefs.__gtype__)
        self.assertEqual(self.read(content, 'text/plain'), ALBUM.url)

    def test_nothing_public_offers_the_item_refs_alone(self):
        for refs in (ItemRefs.for_objects([UPLOAD]),
                     ItemRefs([Ref('playlist', 'p.1', 'One')]),
                     ItemRefs.for_objects([Item({'id': 'p.pl1', 'kind': 'playlist',
                                                 'title': 'Road Trip'})])):
            formats = dnd.provider(refs).ref_formats()
            self.assertEqual(list(formats.get_gtypes()), [ItemRefs.__gtype__])
            self.assertEqual(list(formats.get_mime_types()), [])

    def test_a_source_offers_the_links_too(self):
        from gi.repository import Gtk

        box = Gtk.Box()
        refs = ItemRefs.for_objects([SONG])
        source = dnd.attach_source(box, lambda x, y: (refs, box))
        content = source.emit('prepare', 2.0, 3.0)
        self.assertTrue(content.ref_formats().contain_mime_type(dnd.URI_LIST))
        # No application here, so no storefront: the address is made in 'us'.
        self.assertEqual(self.read(content, 'text/plain'),
                         'https://music.apple.com/us/song/1000000001')


if __name__ == '__main__':
    unittest.main()
