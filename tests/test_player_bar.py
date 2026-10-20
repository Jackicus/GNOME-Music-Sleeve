# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The player bar as a widget: what it shows with and without an item, the compact
layout (a phone's: the item first, Play and Next at the end, in Tab order too), and its
drops. The
bar's reveal is the window's (Window._reveal_player_bar: shown only while something plays), which
scripts/a11y_check.py walks on the real window."""

import unittest

from tests.gtk import requires_gtk
from tests.test_player import SESSION, TRACK, FakeApp
from tests.test_transport import RatingEngine

from applemusic.player import Player


@requires_gtk
class PlayerBarTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw, Gtk

        from applemusic.player_bar import PlayerBar

        self.app = FakeApp(RatingEngine())
        self.player = Player(self.app)
        self.player.track_grace_ms = 0
        self.bar = PlayerBar()
        # As the window holds it: a bottom sheet's bar, wrapped in the sheet's own button.
        self.sheet = Adw.BottomSheet(bottom_bar=self.bar, content=Gtk.Label())
        self.window = Adw.Window(content=self.sheet)
        self.addCleanup(self.window.destroy)
        self.bar.set_player(self.player, self.app)

    def test_with_nothing_playing_the_slider_and_the_heart_are_hidden(self):
        self.assertEqual(self.bar.title_label.get_label(), 'Not Playing')
        self.assertFalse(self.bar.seek_box.get_visible())
        self.assertFalse(self.bar.heart_button.get_visible())
        self.assertFalse(self.bar.explicit_badge.get_visible())

    def test_an_item_shows_its_titles_the_slider_and_the_heart(self):
        self.player.apply({'state': 'playing', 'track': dict(TRACK, explicit=True),
                           'position': 10, 'duration': 214})
        self.assertEqual(self.bar.title_label.get_label(), 'Harbour Lights')
        self.assertTrue(self.bar.subtitle_label.get_visible())
        self.assertTrue(self.bar.seek_box.get_visible())
        self.assertTrue(self.bar.heart_button.get_visible())
        self.assertTrue(self.bar.explicit_badge.get_visible())
        self.player.apply(None)
        self.assertEqual(self.bar.title_label.get_label(), 'Not Playing')
        self.assertFalse(self.bar.seek_box.get_visible())
        self.assertFalse(self.bar.explicit_badge.get_visible())

    def test_the_last_session_restored_shows_paused_where_it_stopped(self):
        self.player.restore(SESSION)
        self.assertEqual(self.bar.title_label.get_label(), 'Harbour Lights')
        self.assertTrue(self.bar.seek_box.get_visible())
        self.assertEqual(self.bar.seek_adjustment.get_value(), 83.0)
        self.assertEqual(self.bar.elapsed_label.get_label(), '1:23')
        self.assertEqual(self.bar.remaining_label.get_label(), '-2:11')
        self.assertEqual(self.bar.play_button.get_icon_name(), 'transport-play-symbolic')
        self.assertTrue(self.bar.repeat_button.get_active())  # repeat all, as it was
        self.assertFalse(self.bar.shuffle_button.get_active())

    def row(self):
        """The bar's row of boxes, in order, by the names the bar gives them."""
        names = {self.bar.transport_box: 'transport', self.bar.item_box: 'item',
                 self.bar.controls_box: 'controls'}
        child = self.bar.transport_box.get_parent().get_first_child()
        order = []
        while child is not None:
            order.append(names[child])
            child = child.get_next_sibling()
        return order

    def test_compact_puts_the_item_first_and_play_and_next_at_the_end(self):
        """A phone's bar: artwork and titles, then Play and Next; no Previous, slider, times
        or right-hand box. Back to wide, the bar is as it was."""
        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214})
        self.assertEqual(self.row(), ['transport', 'item', 'controls'])
        self.bar.props.compact = True
        self.assertEqual(self.row(), ['item', 'transport', 'controls'])
        self.assertFalse(self.bar.previous_button.get_visible())
        self.assertTrue(self.bar.play_button.get_visible())
        self.assertTrue(self.bar.next_button.get_visible())
        self.assertFalse(self.bar.seek_box.get_visible())
        self.assertFalse(self.bar.controls_box.get_visible())
        self.assertFalse(self.bar.elapsed_label.get_visible())
        self.assertFalse(self.bar.remaining_label.get_visible())
        self.assertEqual(self.bar.cover.size, 44)  # the room Previous and the slider left
        self.bar.props.compact = True  # set again (each breakpoint's setters): still in order
        self.assertEqual(self.row(), ['item', 'transport', 'controls'])
        self.bar.props.compact = False
        self.assertEqual(self.row(), ['transport', 'item', 'controls'])
        self.assertTrue(self.bar.previous_button.get_visible())
        self.assertTrue(self.bar.seek_box.get_visible())
        self.assertTrue(self.bar.controls_box.get_visible())
        self.assertTrue(self.bar.elapsed_label.get_visible())

    def test_the_compact_bar_keeps_a_live_stations_badge(self):
        """No slider, but LIVE under the titles, and Stop for Play."""
        self.bar.props.compact = True
        self.player.apply({'state': 'playing', 'track': dict(TRACK, isLive=True),
                           'position': 10, 'duration': 214})
        self.assertTrue(self.player.live)
        self.assertTrue(self.bar.seek_box.get_visible())
        self.assertIs(self.bar.live_label.get_parent().get_visible_child(), self.bar.live_label)
        self.assertEqual(self.bar.play_button.get_tooltip_text(), 'Stop')
        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214})
        self.assertFalse(self.bar.seek_box.get_visible())

    def lay_out(self, direction):
        """Present the window in `direction` (the default text direction, as a locale sets
        it), the transport's app.* actions there, and wait for the bar's layout. The x of
        the item's box, Play and Next, in the window."""
        from gi.repository import Gio, Gtk

        from tests.gtk import pump, wait_for

        Gtk.Widget.set_default_direction(direction)
        self.addCleanup(Gtk.Widget.set_default_direction, Gtk.TextDirection.LTR)
        group = Gio.SimpleActionGroup()
        for name in ('previous', 'play-pause', 'next'):
            group.add_action(Gio.SimpleAction.new(name, None))
        self.window.insert_action_group('app', group)
        self.window.set_default_size(360, 200)
        self.window.present()
        self.assertTrue(wait_for(lambda: self.bar.next_button.get_width() > 0))
        pump()

        def x(widget):
            ok, bounds = widget.compute_bounds(self.window)
            self.assertTrue(ok)
            return bounds.get_x()
        return x(self.bar.item_box), x(self.bar.play_button), x(self.bar.next_button)

    def tab_order(self):
        """The bar's transport in Tab order from the bar itself (the sheet's button around
        it, which opens Now Playing)."""
        from gi.repository import Gtk

        names = {self.bar.get_parent(): 'bar', self.bar.previous_button: 'previous',
                 self.bar.play_button: 'play', self.bar.next_button: 'next'}
        self.bar.get_parent().grab_focus()
        order = []
        while (focus := self.window.get_focus()) in names and names[focus] not in order:
            order.append(names[focus])
            self.window.child_focus(Gtk.DirectionType.TAB_FORWARD)
        return order

    def test_tab_follows_the_compact_order(self):
        """Tab from the bar reaches Play, then Next, as they are shown: after the item."""
        from gi.repository import Gtk

        from tests.gtk import pump, wait_for

        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214})
        self.bar.props.compact = True
        item, play, next_ = self.lay_out(Gtk.TextDirection.LTR)
        self.assertLess(item, play)
        self.assertLess(play, next_)
        self.assertEqual(self.tab_order(), ['bar', 'play', 'next'])
        self.bar.props.compact = False
        self.assertTrue(wait_for(lambda: self.bar.previous_button.get_width() > 0))
        pump()
        self.assertEqual(self.tab_order(), ['bar', 'previous', 'play', 'next'])

    def test_the_compact_bar_mirrors_right_to_left(self):
        """Right to left, the item at the right, Next at the far left; Tab reaches the two
        and nothing else of the bar (in GTK's order for a horizontal box, which is left to
        right in either direction: gtk-notes.md)."""
        from gi.repository import Gtk

        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214})
        self.bar.props.compact = True
        item, play, next_ = self.lay_out(Gtk.TextDirection.RTL)
        self.assertGreater(item, play)
        self.assertGreater(play, next_)
        order = self.tab_order()
        self.assertEqual(order[0], 'bar')
        self.assertEqual(sorted(order[1:]), ['next', 'play'])

    def test_focus_on_previous_moves_to_the_bar_as_the_bar_turns_compact(self):
        from tests.gtk import wait_for

        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214})
        self.window.present()
        self.assertTrue(wait_for(self.bar.previous_button.get_mapped))
        self.bar.previous_button.grab_focus()
        self.bar.props.compact = True
        self.assertIs(self.window.get_focus(), self.bar.get_parent())

    def test_lyrics_and_up_next_name_themselves_and_their_keys(self):
        """Their tooltips add the shortcut; the accessible name is the plain one. (What they
        do is test_now_playing.py's.)"""
        from gi.repository import Gtk

        from applemusic.player_bar import tooltip_with_keys

        self.assertEqual(self.bar.lyrics_button.get_tooltip_text(), 'Lyrics (Shift+Ctrl+L)')
        self.assertEqual(self.bar.queue_button.get_tooltip_text(), 'Up Next (Shift+Ctrl+U)')
        self.assertEqual(self.bar.lyrics_button.get_action_name(), 'win.show-lyrics')
        self.assertEqual(self.bar.queue_button.get_action_name(), 'win.show-queue')
        self.assertIsInstance(self.bar.queue_button, Gtk.ToggleButton)
        self.assertEqual(tooltip_with_keys('Lyrics', 'not a key'), 'Lyrics')
        # In the right-hand box, which the compact bar drops whole; the narrow bar drops
        # them alone.
        self.assertTrue(self.bar.lyrics_button.is_ancestor(self.bar.controls_box))
        self.assertTrue(self.bar.queue_button.is_ancestor(self.bar.controls_box))
        self.assertTrue(self.bar.queue_button.get_visible())
        self.bar.props.narrow = True
        self.assertFalse(self.bar.lyrics_button.get_visible())
        self.assertFalse(self.bar.queue_button.get_visible())
        self.assertTrue(self.bar.controls_box.get_visible())
        self.bar.props.narrow = False
        self.assertTrue(self.bar.lyrics_button.get_visible())
        self.assertTrue(self.bar.queue_button.get_visible())


class StubDrop:
    """A Gdk.Drop as the bar's drop target hands it over: its actions."""

    def __init__(self, actions):
        self.actions = actions

    def get_actions(self):
        return self.actions


class StubTarget:
    """The bar's Gtk.DropTarget, as its handlers ask it: the drop over it."""

    def __init__(self, actions):
        self.drop = StubDrop(actions)

    def get_current_drop(self):
        return self.drop


class StubActions:
    def __init__(self):
        self.queued = []

    def queue_drop(self, refs, next_up=False):
        self.queued.append(([ref.id for ref in refs], next_up))
        return True


@requires_gtk
class DropTest(unittest.TestCase):
    """The bar as a drop target: what it takes (actions.queue_targets), its highlight, and
    the drop handed to the item actions, Shift-drops as Play Next."""

    def setUp(self):
        from gi.repository import Adw, Gdk, Gtk

        from applemusic.player_bar import PlayerBar
        from applemusic.widgets import dnd

        class Window(Adw.Window):
            item_actions = StubActions()

        self.Gdk, self.dnd = Gdk, dnd
        self.bar = PlayerBar()
        self.window = Window(content=Adw.BottomSheet(bottom_bar=self.bar, content=Gtk.Label()))
        self.addCleanup(self.window.destroy)
        self.actions = self.window.item_actions
        self.actions.queued.clear()
        self.addCleanup(dnd._set_current, None)
        modifiers = dnd.modifiers
        dnd.modifiers = lambda _widget: 0  # no key held, whatever the display's keyboard says
        self.addCleanup(setattr, dnd, 'modifiers', modifiers)

    def test_it_takes_what_can_be_queued(self):
        from applemusic.library import Item, ItemRefs, Track

        song = Track({'id': 'i.s1', 'catalogId': '100', 'title': 'Song'})
        playlist = Item({'id': 'p.1', 'kind': 'playlist', 'title': 'List',
                         'play': {'kind': 'playlist', 'id': 'p.1'}})
        folder = Item({'id': 'p.f', 'kind': 'folder', 'title': 'Box'})
        copy, move = self.Gdk.DragAction.COPY, self.Gdk.DragAction.MOVE
        both = StubTarget(copy | move)
        self.assertFalse(self.bar._on_drop_accept(both, None))  # no drag of the app's
        self.assertEqual(self.bar._on_drop_motion(both, 0, 0), 0)
        self.dnd._set_current(ItemRefs.for_objects([song, playlist]))
        self.assertTrue(self.bar._on_drop_accept(both, None))
        self.assertEqual(self.bar._on_drop_motion(both, 0, 0), copy)
        self.assertTrue(self.bar.has_css_class('drop-highlight'))
        self.bar._on_drop_leave(both)
        self.assertFalse(self.bar.has_css_class('drop-highlight'))
        # A sidebar playlist's drag offers MOVE alone.
        self.dnd._set_current(ItemRefs.for_objects([playlist]), move)
        self.assertEqual(self.bar._on_drop_motion(StubTarget(move), 0, 0), move)
        self.dnd._set_current(ItemRefs.for_objects([playlist, folder]))
        self.assertFalse(self.bar._on_drop_accept(both, None))
        self.assertEqual(self.bar._on_drop_motion(both, 0, 0), 0)
        self.assertFalse(self.bar.has_css_class('drop-highlight'))

    def test_a_drop_is_queued_later_or_next_with_shift(self):
        from applemusic.library import ItemRefs, Track

        copy, move = self.Gdk.DragAction.COPY, self.Gdk.DragAction.MOVE
        refs = ItemRefs.for_objects([Track({'id': 'i.s1', 'catalogId': '100', 'title': 'A'})])
        self.dnd._set_current(refs)  # a row's drag: COPY or MOVE
        self.bar.show_drop_target()
        self.assertTrue(self.bar._on_drop(StubTarget(copy), refs, 0, 0))
        self.assertFalse(self.bar.has_css_class('drop-highlight'))
        self.assertTrue(self.bar._on_drop(StubTarget(move), refs, 0, 0))  # Shift: a move
        self.dnd.modifiers = lambda _widget: self.Gdk.ModifierType.SHIFT_MASK
        self.assertTrue(self.bar._on_drop(StubTarget(copy), refs, 0, 0))
        self.assertEqual(self.actions.queued, [(['i.s1'], False), (['i.s1'], True),
                                               (['i.s1'], True)])
        self.dnd._set_current(None)
        self.assertFalse(self.bar._on_drop(StubTarget(copy), None, 0, 0))

    def test_show_drop_target(self):
        self.bar.show_drop_target()
        self.assertTrue(self.bar.has_css_class('drop-highlight'))
        self.bar.show_drop_target(False)
        self.assertFalse(self.bar.has_css_class('drop-highlight'))


if __name__ == '__main__':
    unittest.main()
