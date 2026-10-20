# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Now Playing sheet's tabs from outside (widgets/now_playing.py): `shown-tab` and
TabActions, the window's win.show-lyrics and win.show-queue, with the player bar's Lyrics
and Up Next toggle buttons over them: a click opens the sheet on that tab, another closes
it, the toggles follow what the sheet shows however it got there, from the full-screen
player back to the sheet, Lyrics off for a song without lyrics, and both off while a
dialog is over the window. (The sheet's lyrics are test_lyrics_view.py's.)"""

import unittest

from tests.gtk import SCHEMA_ID, pump, requires_gtk, wait_for
from tests.test_player import LYRICS, TRACK, FakeApp
from tests.test_transport import RatingEngine

from applemusic.lyrics import Lyrics
from applemusic.player import Player


def can_show_tab(*args):
    from applemusic.widgets.now_playing import can_show_tab

    return can_show_tab(*args)


@requires_gtk  # the module's template needs the compiled resource
class CanShowTabTest(unittest.TestCase):
    def test_up_next_while_an_item_plays(self):
        self.assertTrue(can_show_tab('queue', '', object(), None, False))
        self.assertFalse(can_show_tab('queue', '', None, None, False))

    def test_lyrics_while_there_are_some_or_they_are_being_read(self):
        lyrics = Lyrics(LYRICS)
        self.assertTrue(can_show_tab('lyrics', '', object(), lyrics, False))
        self.assertTrue(can_show_tab('lyrics', '', object(), None, True))
        self.assertFalse(can_show_tab('lyrics', '', object(), None, False))
        self.assertFalse(can_show_tab('lyrics', '', None, None, True))

    def test_the_tab_shown_can_always_be_closed(self):
        self.assertTrue(can_show_tab('lyrics', 'lyrics', object(), None, False))
        self.assertTrue(can_show_tab('queue', 'queue', None, None, False))
        self.assertFalse(can_show_tab('lyrics', 'queue', object(), None, False))


class FakeHost:
    """The full-screen player's host as TabActions asks of it."""

    def __init__(self, sheet):
        self.sheet = sheet
        self.shown = False
        self.left = 0

    def leave(self, restore_focus=True):
        self.left += 1
        self.shown = False
        self.sheet.set_covered(False)


@requires_gtk
class TabActionsTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw, Gio, Gtk

        from applemusic.player_bar import PlayerBar
        from applemusic.widgets.now_playing import NowPlayingSheet, TabActions

        self.app = FakeApp(RatingEngine())
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        self.player = Player(self.app)
        self.player.track_grace_ms = 0
        self.bar = PlayerBar()
        self.sheet = NowPlayingSheet()
        # As the window holds them: the bar and the sheet of one bottom sheet, the actions
        # in the window's `win` group.
        self.bottom_sheet = Adw.BottomSheet(bottom_bar=self.bar, sheet=self.sheet,
                                            content=Gtk.Label())
        self.window = Gtk.Window(default_width=1000, default_height=700,
                                 child=self.bottom_sheet)
        self.addCleanup(self.window.destroy)
        self.bar.set_player(self.player, self.app)
        self.sheet.set_player(self.player, self.app, self.bottom_sheet)
        self.host = FakeHost(self.sheet)
        self.tabs = TabActions(self.sheet, self.bottom_sheet, self.player, self.host)
        group = Gio.SimpleActionGroup()
        for action in self.tabs.actions.values():
            group.add_action(action)
        self.window.insert_action_group('win', group)
        self.window.present()
        self.assertTrue(wait_for(self.window.get_mapped))

    def play(self, lyrics=LYRICS):
        self.player.apply({'state': 'playing', 'track': TRACK, 'position': 10,
                           'duration': 214, 'lyrics': lyrics})
        pump(50)

    def pressed(self):
        return (self.bar.lyrics_button.get_active(), self.bar.queue_button.get_active())

    def test_nothing_playing_nothing_to_show(self):
        pump(50)
        self.assertFalse(self.bar.lyrics_button.get_sensitive())
        self.assertFalse(self.bar.queue_button.get_sensitive())

    def test_a_click_opens_the_sheet_on_that_tab_and_another_closes_it(self):
        self.play()
        self.assertTrue(self.bar.lyrics_button.get_sensitive())
        self.assertTrue(self.bar.queue_button.get_sensitive())
        self.assertEqual(self.pressed(), (False, False))
        self.bar.queue_button.emit('clicked')
        pump(50)
        self.assertTrue(self.bottom_sheet.get_open())
        self.assertEqual(self.sheet.tab_stack.get_visible_child_name(), 'queue')
        self.assertEqual(self.sheet.shown_tab, 'queue')
        self.assertEqual(self.pressed(), (False, True))
        # The other one switches the tab, the sheet staying open.
        self.bar.lyrics_button.emit('clicked')
        pump(50)
        self.assertTrue(self.bottom_sheet.get_open())
        self.assertEqual(self.sheet.shown_tab, 'lyrics')
        self.assertEqual(self.pressed(), (True, False))
        # Again on the tab shown: closed, neither pressed.
        self.bar.lyrics_button.emit('clicked')
        pump(50)
        self.assertFalse(self.bottom_sheet.get_open())
        self.assertEqual(self.sheet.shown_tab, '')
        self.assertEqual(self.pressed(), (False, False))
        # The sheet remembers its tab, as it does when closed by hand.
        self.assertEqual(self.sheet.tab_stack.get_visible_child_name(), 'lyrics')

    def test_the_toggles_follow_the_sheet_however_it_opens(self):
        self.play()
        self.bottom_sheet.set_open(True)  # the bar's click, a swipe, Ctrl+Shift+N
        pump(50)
        self.assertEqual(self.pressed(), (True, False))
        self.sheet.show_tab('queue')  # its own switcher
        pump(50)
        self.assertEqual(self.pressed(), (False, True))
        self.sheet.on_close_clicked(None)
        pump(50)
        self.assertEqual(self.pressed(), (False, False))

    def test_from_the_full_screen_player_back_to_the_sheet_on_the_tab(self):
        self.play()
        self.bottom_sheet.set_open(True)  # on Lyrics, under the full-screen player
        self.host.shown = True
        self.sheet.set_covered(True)
        pump(50)
        self.assertEqual(self.sheet.shown_tab, '')
        self.assertEqual(self.pressed(), (False, False))
        # Lyrics again: the sheet on Lyrics, not closed because it was open there.
        self.tabs.actions['lyrics'].activate(None)
        pump(50)
        self.assertEqual(self.host.left, 1)
        self.assertTrue(self.bottom_sheet.get_open())
        self.assertEqual(self.sheet.shown_tab, 'lyrics')
        self.assertEqual(self.pressed(), (True, False))

    def test_a_song_without_lyrics_has_no_lyrics_button(self):
        self.play(lyrics=None)
        self.assertFalse(self.bar.lyrics_button.get_sensitive())
        self.assertTrue(self.bar.queue_button.get_sensitive())
        # Open on Lyrics all the same (its own switcher): it can be closed from there.
        self.bottom_sheet.set_open(True)
        pump(50)
        self.assertEqual(self.sheet.shown_tab, 'lyrics')
        self.assertTrue(self.tabs.actions['lyrics'].get_enabled())
        self.play()
        self.assertTrue(self.bar.lyrics_button.get_sensitive())

    def test_a_dialog_over_the_window_turns_them_off(self):
        self.play()
        self.tabs.set_free(False)
        pump(50)
        self.assertFalse(self.bar.lyrics_button.get_sensitive())
        self.assertFalse(self.bar.queue_button.get_sensitive())
        self.tabs.set_free(True)
        pump(50)
        self.assertTrue(self.bar.queue_button.get_sensitive())


if __name__ == '__main__':
    unittest.main()
