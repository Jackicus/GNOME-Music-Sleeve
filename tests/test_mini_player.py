# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""mini_player.py: the mini player's layout, and its host with stand-ins (one window at a
time, the main window put away and back, its size kept, closing it as leaving it); then the
window itself following a real Player (the item, live radio, the low layout) and letting go
of it. That a closed mini player is freed is test_page_lifetime's; its keys are
scripts/a11y_check.py's."""

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
        self.assertLessEqual(layout.art_size + mini_player.BELOW_ART + mini_player.TOP_MARGIN,
                             450)
        self.assertEqual(layout.art_size % 8, 0)

    def test_the_cover_grows_with_the_window_up_to_its_file(self):
        self.assertGreater(layout_for(400, 600).art_size, layout_for(320, 450).art_size)
        self.assertEqual(layout_for(2000, 2000).art_size, mini_player.MAX_ART)

    def test_a_low_or_narrow_window_puts_a_small_cover_beside_the_titles(self):
        for width, height in ((320, 220), (480, 280), (150, 600)):
            layout = layout_for(width, height)
            self.assertTrue(layout.short, (width, height))
            self.assertEqual(layout.art_size, mini_player.SMALL_ART)


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
        from applemusic.widgets.mini_player import MiniPlayer

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


if __name__ == '__main__':
    unittest.main()
