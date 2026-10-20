# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The player bar as a widget: what it shows with and without an item, the compact
layout's room for the title (a smaller cover, the right-hand box gone), and its drops. The
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

    def test_compact_shrinks_the_cover_and_drops_the_right_hand_box(self):
        from applemusic.player_bar import COMPACT_COVER_SIZE, COVER_SIZE

        self.assertEqual(self.bar.cover.size, COVER_SIZE)
        self.assertTrue(self.bar.controls_box.get_visible())
        self.bar.props.compact = True
        self.assertEqual(self.bar.cover.size, COMPACT_COVER_SIZE)
        self.assertFalse(self.bar.controls_box.get_visible())
        self.assertFalse(self.bar.elapsed_label.get_visible())
        self.assertFalse(self.bar.remaining_label.get_visible())
        self.bar.props.compact = False
        self.assertEqual(self.bar.cover.size, COVER_SIZE)
        self.assertTrue(self.bar.controls_box.get_visible())
        self.assertTrue(self.bar.elapsed_label.get_visible())

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
