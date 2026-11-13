# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""mini_player.py: the mini player's layout (the cover, and where Favourite, Shuffle, Repeat
and Volume go at each size), and its host with stand-ins (one window at a
time, the main window put away and back, its size kept, closing it as leaving it); then the
window itself following a real Player (the item, live radio, the low layout, the extras and
the volume keys) and letting go of it. That a closed mini player is freed is
test_page_lifetime's; its keys are scripts/a11y_check.py's."""

import unittest

import gi

from tests import ROOT  # noqa: F401  registers src/ as applemusic

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gio  # noqa: E402

from tests.gtk import SCHEMA_ID, requires_gtk, wait_for  # noqa: E402
from tests.test_player import TRACK, FakeApp  # noqa: E402
from tests.test_transport import RatingEngine  # noqa: E402

from applemusic import mini_player  # noqa: E402
from applemusic.mini_player import MiniPlayerHost, layout_for  # noqa: E402
from applemusic.player import Player  # noqa: E402

# No artwork URL: nothing is fetched.
SONG = dict(TRACK, artUrl=None)
STATION = {'id': 'ra.demo001', 'title': 'Invented FM', 'kind': 'radioStation', 'isLive': True,
           'artUrl': None, 'index': 0}


class LayoutTest(unittest.TestCase):
    def test_the_default_size_has_the_cover_over_the_titles(self):
        layout = layout_for(320, 450)
        self.assertFalse(layout.short)
        self.assertLessEqual(layout.art_size, 320 - 2 * mini_player.MARGIN)
        self.assertLessEqual(layout.art_size + mini_player.BELOW_ART + mini_player.EXTRAS_ROW
                             + mini_player.TOP_MARGIN, 450)
        self.assertEqual(layout.art_size % 8, 0)

    def test_the_cover_grows_with_the_window_up_to_its_file(self):
        self.assertGreater(layout_for(400, 600).art_size, layout_for(320, 450).art_size)
        self.assertEqual(layout_for(2000, 2000).art_size, mini_player.MAX_ART)

    def test_a_low_or_narrow_window_puts_a_small_cover_beside_the_titles(self):
        for width, height in ((320, 220), (480, 280), (150, 600)):
            layout = layout_for(width, height)
            self.assertTrue(layout.short, (width, height))
            self.assertEqual(layout.art_size, mini_player.SMALL_ART)

    def test_the_extras_at_each_window_size(self):
        # The window's sizes, its header bar (46 px) taken off the height: what the cover
        # is and where Favourite, Shuffle, Repeat and Volume go.
        header = 46
        for (width, height), expected in {
                (280, 240): (True, 56, 'none'),      # the minimum: the transport alone
                (280, 290): (True, 56, 'row'),
                (280, 420): (False, 152, 'row'),
                (320, 500): (False, 232, 'row'),     # the default
                (372, 240): (True, 56, 'inline'),
                (480, 640): (False, 416, 'inline')}.items():
            self.assertEqual(tuple(layout_for(width, height - header)), expected,
                             (width, height))

    def test_the_extras_go_inline_from_the_width_the_seven_buttons_take(self):
        self.assertEqual(layout_for(mini_player.INLINE_WIDTH - 1, 600).extras, 'row')
        self.assertEqual(layout_for(mini_player.INLINE_WIDTH, 600).extras, 'inline')
        self.assertEqual(layout_for(mini_player.INLINE_WIDTH, 100).extras, 'inline')

    def test_the_row_shows_once_the_short_layout_has_room_for_it(self):
        fits = mini_player.SHORT_HEIGHT + mini_player.EXTRAS_ROW
        self.assertEqual(layout_for(300, fits - 1), (True, mini_player.SMALL_ART, 'none'))
        self.assertEqual(layout_for(300, fits), (True, mini_player.SMALL_ART, 'row'))

    def test_the_row_outranks_a_larger_cover(self):
        # Room for a 128 px cover over the titles without the row, not with it: the row and
        # the small cover.
        height = mini_player.TOP_MARGIN + mini_player.BELOW_ART + mini_player.MIN_ART
        self.assertEqual(layout_for(300, height), (True, mini_player.SMALL_ART, 'row'))
        with_row = layout_for(300, height + mini_player.EXTRAS_ROW)
        self.assertEqual(with_row, (False, mini_player.MIN_ART, 'row'))


class FakeWindow:
    """A window as the host sees it: what it was asked, recorded."""

    def __init__(self, calls, name, size=(0, 0)):
        self.calls = calls
        self.name = name
        self.size = size

    def set_default_size(self, width, height):
        self.size = (width, height)

    def get_default_size(self):
        return self.size

    def present(self):
        self.calls.append((self.name, 'present'))

    def put_away(self):
        self.calls.append((self.name, 'put_away'))

    def release(self):
        self.calls.append((self.name, 'release'))


class FakeHostApp:
    def __init__(self, calls):
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.main = FakeWindow(calls, 'main')

    def main_window(self):
        return self.main


class HostTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.app = FakeHostApp(self.calls)
        for key in ('mini-player-width', 'mini-player-height'):
            self.addCleanup(self.app.settings.reset, key)
        self.made = []

        def make_window(app):
            self.assertIs(app, self.app)
            window = FakeWindow(self.calls, f'mini{len(self.made)}')
            self.made.append(window)
            return window

        self.host = MiniPlayerHost(self.app, make_window)

    def test_entering_shows_it_at_its_size_and_puts_the_main_window_away(self):
        self.app.settings.set_int('mini-player-width', 300)
        self.app.settings.set_int('mini-player-height', 420)
        self.host.enter()
        self.assertTrue(self.host.shown)
        self.assertIs(self.host.window, self.made[0])
        self.assertEqual(self.made[0].size, (300, 420))
        self.assertEqual(self.calls, [('mini0', 'present'), ('main', 'put_away')])

    def test_one_at_a_time(self):
        self.host.enter()
        self.host.enter()
        self.assertEqual(len(self.made), 1)
        self.assertEqual(self.calls[-1], ('mini0', 'present'))

    def test_leaving_brings_the_main_window_back_and_keeps_the_size(self):
        self.host.enter()
        self.made[0].size = (340, 380)  # the user resized it
        self.calls.clear()
        self.host.leave()
        self.assertFalse(self.host.shown)
        self.assertEqual(self.calls, [('main', 'present'), ('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-width'), 340)
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 380)
        self.host.leave()  # nothing to leave
        self.assertEqual(len(self.calls), 2)

    def test_toggle(self):
        self.host.toggle()
        self.assertTrue(self.host.shown)
        self.host.toggle()
        self.assertFalse(self.host.shown)
        self.host.toggle()  # a new window: the last was destroyed
        self.assertEqual(len(self.made), 2)

    def test_quitting_closes_it_and_leaves_the_main_window_hidden(self):
        self.host.enter()
        self.made[0].size = (300, 300)
        self.calls.clear()
        self.host.quit()
        self.assertEqual(self.calls, [('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 300)
        self.host.quit()
        self.assertEqual(len(self.calls), 1)


@requires_gtk
class WindowTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gdk, Gtk

        from applemusic.widgets.mini_player import MiniPlayer

        # The app's stylesheet: the sizes layout_for() counts on are its buttons' and its
        # seek row's.
        display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_resource('/io/github/jackicus/MusicSleeve/style.css')
        Gtk.StyleContext.add_provider_for_display(display, css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, css)
        self.app = FakeApp(RatingEngine())
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        self.player = Player(self.app)
        self.player.track_grace_ms = 0
        self.window = MiniPlayer(default_width=320, default_height=450)
        self.addCleanup(self.close)
        self.window.set_player(self.player, self.app)
        self.view = self.window.view
        self.window.present()
        self.assertTrue(wait_for(self.window.get_mapped))

    def close(self):
        if self.window is not None:
            self.window.release()
            self.window = None

    def test_nothing_playing(self):
        self.assertEqual(self.view.title_label.get_label(), 'Not Playing')
        self.assertFalse(self.view.subtitle_label.get_visible())
        self.assertFalse(self.view.seek_box.get_sensitive())
        self.assertEqual(self.window.get_title(), 'Mini Player')

    def test_the_item_playing(self):
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 65,
                           'duration': 214})
        self.assertEqual(self.view.title_label.get_label(), 'Harbour Lights')
        self.assertEqual(self.view.subtitle_label.get_label(),
                         'The Invented Band — Fictional Album')
        self.assertTrue(self.view.seek_box.get_sensitive())
        self.assertEqual(self.view.play_button.get_tooltip_text(), 'Pause')
        self.assertEqual(self.view.elapsed_label.get_label(), '1:05')
        self.assertTrue(wait_for(lambda: self.view.shown_layout is not None))
        self.assertFalse(self.view.shown_layout.short)
        self.assertEqual(self.view.cover.size, self.view.shown_layout.art_size)

    def test_a_live_station(self):
        self.player.apply({'state': 'playing', 'track': STATION, 'position': 0,
                           'duration': 0})
        self.assertIs(self.view.live_label.get_parent().get_visible_child(),
                      self.view.live_label)
        self.assertFalse(self.view.elapsed_label.get_visible())
        self.assertEqual(self.view.play_button.get_tooltip_text(), 'Stop')

    def test_a_low_window_has_the_cover_beside_the_titles(self):
        self.window.set_default_size(320, 250)
        self.assertTrue(wait_for(lambda: self.view.shown_layout is not None
                                 and self.view.shown_layout.short))
        self.assertEqual(self.view.cover.size, mini_player.SMALL_ART)
        self.assertEqual(self.view.title_label.get_xalign(), 0)
        tall = layout_for(320, 450)
        self.view.apply_layout(tall)  # as a taller window would have it
        self.assertEqual(self.view.cover.size, tall.art_size)
        self.assertEqual(self.view.title_label.get_xalign(), 0.5)
        self.assertTrue(self.view.cover.has_css_class('large'))
        self.assertFalse(self.view.cover.has_css_class('small'))

    def controls(self):
        """The view's buttons in the order they are laid out, across then down: Tab's."""
        view = self.view
        buttons = (view.heart_button, view.shuffle_button, view.previous_button,
                   view.play_button, view.next_button, view.repeat_button,
                   view.volume_button)

        def place(button):
            _ok, bounds = button.compute_bounds(view)
            return round(bounds.get_y() + bounds.get_height() / 2), bounds.get_x()

        return [button for button in sorted(buttons, key=place) if button.get_mapped()]

    def test_the_extras_follow_the_player(self):
        view = self.view
        for button in (view.heart_button, view.shuffle_button, view.repeat_button,
                       view.volume_button):
            self.assertFalse(button.get_sensitive())  # nothing plays
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 65,
                           'duration': 214, 'shuffle': True, 'repeat': 'one',
                           'volume': 0.4})
        for button in (view.heart_button, view.shuffle_button, view.repeat_button,
                       view.volume_button):
            self.assertTrue(button.get_sensitive())
        self.assertTrue(view.shuffle_button.get_active())
        self.assertEqual(view.repeat_button.get_tooltip_text(), 'Repeat One')
        self.assertAlmostEqual(view.volume_adjustment.get_value(), 0.4)
        self.assertFalse(view.heart_button.get_active())
        # The heart is lazy: it reads nothing as the item changes, and shows the answer to
        # another heart's read (the bar's).
        self.assertEqual(self.app.engine.calls, [])
        self.app.engine.emit('rated', 'song', SONG.get('catalogId') or SONG['id'], 1)
        self.assertTrue(view.heart_button.get_active())
        self.assertEqual(view.heart_button.get_tooltip_text(), 'Remove from Favourites')

    def test_a_live_station_has_no_shuffle_or_repeat(self):
        self.player.apply({'state': 'playing', 'track': STATION, 'position': 0,
                           'duration': 0})
        self.assertFalse(self.view.shuffle_button.get_sensitive())
        self.assertFalse(self.view.repeat_button.get_sensitive())
        self.assertTrue(self.view.volume_button.get_sensitive())

    def test_the_extras_are_a_row_at_the_default_size(self):
        view = self.view
        self.assertTrue(wait_for(lambda: view.shown_layout is not None))
        self.assertEqual(view.shown_layout.extras, 'row')
        self.assertTrue(view.extras_box.get_mapped())
        self.assertEqual(self.controls(),
                         [view.previous_button, view.play_button, view.next_button,
                          view.heart_button, view.shuffle_button, view.repeat_button,
                          view.volume_button])

    def test_a_low_narrow_window_keeps_the_transport_alone(self):
        view = self.view
        self.window.set_default_size(300, 250)
        # Sized before its first allocation: the header bar's height is taken off even
        # then (the toolbar view does not know it yet).
        self.assertTrue(wait_for(lambda: view.shown_layout is not None
                                 and view.shown_layout.extras == 'none'))
        self.assertFalse(view.extras_box.get_visible())
        self.assertFalse(view.heart_button.get_mapped())
        self.assertEqual(self.controls(),
                         [view.previous_button, view.play_button, view.next_button])

    def test_a_wide_window_has_the_extras_around_the_transport(self):
        view = self.view
        view.apply_layout(layout_for(mini_player.INLINE_WIDTH, 250))
        self.assertEqual(view.extras, 'inline')
        self.assertFalse(view.extras_box.get_visible())
        order = []
        child = view.transport_box.get_first_child()
        while child is not None:
            order.append(child)
            child = child.get_next_sibling()
        self.assertEqual(order, [view.heart_button, view.shuffle_button,
                                 view.previous_button, view.play_button, view.next_button,
                                 view.repeat_button, view.volume_button])
        # And back to their row, in the order they read; they still follow the Player.
        view.apply_layout(layout_for(320, 454))
        self.assertTrue(view.extras_box.get_visible())
        self.assertIs(view.heart_button.get_parent(), view.extras_box)
        self.assertIs(view.extras_box.get_first_child(), view.heart_button)
        self.assertIs(view.extras_box.get_last_child(), view.volume_button)
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 1,
                           'duration': 214, 'shuffle': True})
        self.assertTrue(view.shuffle_button.get_active())

    def test_the_focus_stays_on_an_extra_that_is_moved(self):
        view = self.view
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 1,
                           'duration': 214})
        self.assertTrue(wait_for(lambda: view.shown_layout is not None))
        self.assertTrue(view.shuffle_button.grab_focus())
        view.apply_layout(layout_for(mini_player.INLINE_WIDTH, 250))
        self.assertIs(self.window.get_focus(), view.shuffle_button)

    def test_the_layouts_fit_the_sizes_the_rule_gives_them(self):
        # layout_for()'s measures against the widgets': each layout's content is no taller
        # or wider (its margins counted) than the least size the rule shows it at.
        from gi.repository import Gtk

        view = self.view
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 1,
                           'duration': 214})
        fits = mini_player.SHORT_HEIGHT + mini_player.EXTRAS_ROW
        for width, height in ((280, 194), (280, fits), (mini_player.INLINE_WIDTH, 194),
                              (320, 454)):
            layout = layout_for(width, height)
            view.apply_layout(layout)
            needed_height = view.content_box.measure(Gtk.Orientation.VERTICAL, -1)[0]
            needed_width = view.content_box.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            self.assertLessEqual(needed_height, height, (width, height, layout))
            self.assertLessEqual(needed_width, width, (width, height, layout))

    def test_the_volume_keys_step_the_volume(self):
        from gi.repository import Gdk

        self.app.player = self.player
        self.window.get_application = lambda: self.app
        self.app.lookup_action = lambda _name: None
        commands = []

        async def set_volume(level):
            commands.append(level)

        self.player.set_volume = set_volume
        self.app.player_command = lambda coro, on_error=None: self.spawned(coro)
        control = Gdk.ModifierType.CONTROL_MASK
        self.assertFalse(self.window._on_key_pressed(None, Gdk.KEY_Up, 0, control))  # no item
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 1,
                           'duration': 214, 'volume': 0.5})
        self.view.play_button.grab_focus()
        self.assertTrue(self.window._on_key_pressed(None, Gdk.KEY_Up, 0, control))
        self.assertAlmostEqual(self.view.volume_adjustment.get_value(), 0.6)
        self.assertTrue(self.window._on_key_pressed(None, Gdk.KEY_Down, 0, control))
        self.assertTrue(self.window._on_key_pressed(None, Gdk.KEY_Down, 0, control))
        self.assertAlmostEqual(self.view.volume_adjustment.get_value(), 0.4)
        # On the seek slider the keys are the slider's own.
        self.view.seek_scale.grab_focus()
        self.assertFalse(self.window._on_key_pressed(None, Gdk.KEY_Up, 0, control))
        self.assertEqual([round(level, 2) for level in commands], [0.6, 0.5, 0.4])

    def spawned(self, coro):
        """A command run as far as its first wait (the volume's is sent at once)."""
        try:
            coro.send(None)
        except StopIteration:
            pass
        else:
            coro.close()

    def test_closing_is_leaving(self):
        class Host:
            def __init__(self, window):
                self.window = window
                self.left = 0

            def leave(self):
                self.left += 1

        host = Host(self.window)
        self.app.mini_player = host
        self.window.close()
        self.assertEqual(host.left, 1)
        self.assertTrue(self.window.get_visible())  # the host destroys it, not the close

    def test_released_it_follows_nothing(self):
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 65,
                           'duration': 214})
        view = self.view
        self.close()
        self.player.apply({'state': 'paused', 'track': dict(SONG, id='i.demo0002',
                                                            title='Pilot Light'),
                           'position': 3, 'duration': 200})
        self.assertEqual(view.title_label.get_label(), 'Harbour Lights')

    def test_released_its_extras_follow_nothing(self):
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 65,
                           'duration': 214, 'volume': 0.4})
        view = self.view
        self.close()
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 66,
                           'duration': 214, 'shuffle': True, 'repeat': 'all',
                           'volume': 0.9})
        self.app.engine.emit('rated', 'song', SONG.get('catalogId') or SONG['id'], 1)
        self.assertFalse(view.shuffle_button.get_active())
        self.assertFalse(view.repeat_button.get_active())
        self.assertFalse(view.heart_button.get_active())
        self.assertAlmostEqual(view.volume_adjustment.get_value(), 0.4)

    def test_released_it_closes_the_dialog_over_it(self):
        # Preferences (or the sign-in) opened over the mini player by its key: the app keeps
        # the one it has until its `closed`, which a dialog only destroyed with its window
        # never emitted, so Preferences never opened again and the toasts went nowhere.
        from gi.repository import Adw

        closed = []
        dialog = Adw.Dialog(child=Adw.Bin())
        dialog.connect('closed', lambda _dialog: closed.append(True))
        dialog.present(self.window)
        self.assertTrue(wait_for(dialog.get_mapped))
        self.close()
        self.assertTrue(wait_for(lambda: closed))


if __name__ == '__main__':
    unittest.main()
