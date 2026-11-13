# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""mini_player.py: the mini player's layout (the cover, and where Favourite, Shuffle, Repeat
and Volume go at each size), its panes (how a window with one divides, what is remembered of
its size, the lending and its order: Panes with stand-ins), and its host with stand-ins
(one window at a time, the main window put away and back, its size kept, closing it as
leaving it); then the window itself following a real Player (the item, live radio, the low
layout, the extras and the volume keys) and letting go of it. That a closed mini player is freed is
test_page_lifetime's; its keys are scripts/a11y_check.py's. Last, the panes with the real
Now Playing sheet: its one LyricsView and one QueueView lent and given back, active in one
place at a time, and Up Next's edits and menus reaching the main window's actions."""

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
from applemusic.mini_player import MiniPlayerHost, Panes, layout_for, split  # noqa: E402
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


class SplitTest(unittest.TestCase):
    def test_the_body_keeps_its_height_and_the_pane_has_the_rest(self):
        self.assertEqual(split(820, 500), (500, 320))
        self.assertEqual(split(920, 500), (500, 420))  # dragged taller: the pane's
        self.assertEqual(split(700, 500), (500, 200))

    def test_a_window_too_low_gives_the_pane_its_least_and_the_body_the_rest(self):
        least = mini_player.PANE_MIN
        self.assertEqual(split(500 + least, 500), (500, least))
        self.assertEqual(split(600, 500), (600 - least, least))
        self.assertEqual(split(500, 500), (500 - least, least))  # it never grew
        self.assertEqual(split(100, 500), (0, 100))


class FakeView:
    """A view the sheet lends (the LyricsView, the QueueView): set_active() recorded."""

    def __init__(self, calls, name):
        self.calls = calls
        self.name = name

    def set_active(self, active):
        self.calls.append((self.name, 'active' if active else 'inactive'))


class FakeSheet:
    """The Now Playing sheet as the host and the panes see it."""

    def __init__(self, calls):
        self.calls = calls
        self.views = {'lyrics': FakeView(calls, 'lyrics'), 'queue': FakeView(calls, 'queue')}
        self.out = set()

    def set_covered(self, covered):
        self.calls.append(('sheet', 'covered' if covered else 'uncovered'))

    def _lend(self, name):
        if name in self.out:
            return None
        self.out.add(name)
        self.calls.append(('sheet', 'lend', name))
        return self.views[name]

    def _return(self, name, view):
        assert view is self.views[name]
        self.out.discard(name)
        self.calls.append(('sheet', 'return', name))

    def lend_lyrics(self):
        return self._lend('lyrics')

    def lend_queue(self):
        return self._lend('queue')

    def return_lyrics(self, view):
        self._return('lyrics', view)

    def return_queue(self, view):
        self._return('queue', view)


class FakeWindow:
    """A window as the host and the panes see it: what it was asked, recorded."""

    def __init__(self, calls, name, size=(0, 0)):
        self.calls = calls
        self.name = name
        self.size = size
        self.fixed = False
        self.showable = {'lyrics', 'queue'}
        self.pane = None       # (name, the widget, base) of the pane shown
        self.panes = None

    def can_show(self, pane):
        return pane in self.showable

    def set_lender(self, sheet, main, base):
        self.calls.append((self.name, 'lender'))
        if sheet is not None:
            self.panes = Panes(self, sheet, self.settings, base)

    def fixed_size(self):
        return self.fixed

    def show_pane(self, name, widget, base):
        self.pane = (name, widget, base)
        self.calls.append((self.name, 'show', name, self.size))

    def hide_pane(self):
        if self.pane is not None:
            self.calls.append((self.name, 'hide', self.pane[0]))
        self.pane = None

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


PANE_KEYS = ('mini-player-width', 'mini-player-height', 'mini-player-pane',
             'mini-player-pane-height')


class PanesTest(unittest.TestCase):
    """Panes with a stand-in window and sheet: a window 320 by 500, the pane 320."""

    def setUp(self):
        self.calls = []
        self.settings = Gio.Settings.new(SCHEMA_ID)
        for key in PANE_KEYS:
            self.addCleanup(self.settings.reset, key)
        self.window = FakeWindow(self.calls, 'mini', (320, 500))
        self.sheet = FakeSheet(self.calls)
        self.panes = Panes(self.window, self.sheet, self.settings, 500)

    def test_opening_lends_shows_grows_then_makes_active(self):
        self.assertTrue(self.panes.show('lyrics'))
        self.assertEqual(self.calls, [('sheet', 'lend', 'lyrics'),
                                      ('mini', 'show', 'lyrics', (320, 820)),
                                      ('lyrics', 'active')])
        self.assertEqual(self.panes.shown, 'lyrics')
        self.assertEqual(self.window.pane[2], 500)  # the body keeps the window's height
        self.assertEqual(self.settings.get_string('mini-player-pane'), 'lyrics')

    def test_closing_makes_inactive_returns_then_shrinks(self):
        self.panes.show('queue')
        self.calls.clear()
        self.panes.close()
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue')])
        self.assertEqual(self.window.size, (320, 500))
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.settings.get_string('mini-player-pane'), '')
        self.panes.close()  # nothing to close
        self.assertEqual(len(self.calls), 3)

    def test_the_other_toggle_swaps_with_no_resize(self):
        self.panes.show('lyrics')
        self.calls.clear()
        self.panes.toggle('queue')
        self.assertEqual(self.calls, [('lyrics', 'inactive'), ('mini', 'hide', 'lyrics'),
                                      ('sheet', 'return', 'lyrics'),
                                      ('sheet', 'lend', 'queue'),
                                      ('mini', 'show', 'queue', (320, 820)),
                                      ('queue', 'active')])
        self.assertEqual(self.sheet.out, {'queue'})
        self.panes.toggle('queue')  # the one shown: closed
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.sheet.out, set())
        self.assertEqual(self.window.size, (320, 500))

    def test_a_resize_with_a_pane_open_is_the_panes(self):
        self.panes.show('lyrics')
        self.window.size = (360, 920)  # dragged 100 px taller, and wider
        self.panes.close()
        self.assertEqual(self.window.size, (360, 500))  # the mini player as it was
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 420)
        self.panes.show('queue')
        self.assertEqual(self.window.size, (360, 920))  # and the pane as it was left

    def test_dragged_lower_than_its_base_the_body_gives_way(self):
        self.panes.show('lyrics')
        self.window.size = (320, 400)
        self.panes.close()
        least = mini_player.PANE_MIN
        self.assertEqual(self.window.size, (320, 400 - least))
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), least)

    def test_the_window_resized_without_a_pane_is_the_base_it_grows_from(self):
        self.window.size = (320, 300)
        self.panes.show('lyrics')
        self.assertEqual(self.window.size, (320, 620))
        self.assertEqual(self.window.pane[2], 300)

    def test_a_window_that_cannot_grow_keeps_its_size_and_remembers_nothing(self):
        self.window.fixed = True
        self.panes.show('lyrics')
        self.assertEqual(self.window.size, (320, 500))
        self.assertEqual(self.calls[-1], ('lyrics', 'active'))
        self.panes.close()
        self.assertEqual(self.window.size, (320, 500))
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 320)

    def test_nothing_to_lend_shows_nothing(self):
        self.sheet.out.add('lyrics')  # the full-screen player has it
        self.assertFalse(self.panes.show('lyrics'))
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.window.size, (320, 500))
        self.assertFalse(Panes(self.window, None, self.settings, 500).show('queue'))
        self.assertFalse(self.panes.show('videos'))

    def test_giving_back_as_the_mini_player_goes_keeps_the_pane_for_next_time(self):
        self.panes.show('queue')
        self.window.size = (340, 900)
        self.calls.clear()
        self.assertEqual(self.panes.give_back(), (340, 500))
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue')])
        self.assertEqual(self.settings.get_string('mini-player-pane'), 'queue')
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 400)
        self.assertIsNone(self.panes.give_back())  # nothing lent any more


class FakeHostApp:
    def __init__(self, calls):
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.main = FakeWindow(calls, 'main')
        self.main.now_playing = FakeSheet(calls)

    def main_window(self):
        return self.main


class HostTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.app = FakeHostApp(self.calls)
        for key in PANE_KEYS:
            self.addCleanup(self.app.settings.reset, key)
        self.made = []

        def make_window(app):
            self.assertIs(app, self.app)
            window = FakeWindow(self.calls, f'mini{len(self.made)}')
            window.settings = app.settings
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
        # The sheet of the hidden window covered: its views inactive, to lend.
        self.assertEqual(self.calls, [('mini0', 'present'), ('main', 'put_away'),
                                      ('sheet', 'covered'), ('mini0', 'lender')])

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
        self.assertEqual(self.calls, [('sheet', 'uncovered'), ('main', 'present'),
                                      ('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-width'), 340)
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 380)
        self.host.leave()  # nothing to leave
        self.assertEqual(len(self.calls), 3)

    def test_the_pane_it_last_had_opens_with_it_at_the_grown_size(self):
        settings = self.app.settings
        settings.set_string('mini-player-pane', 'queue')
        settings.set_int('mini-player-pane-height', 300)
        self.host.enter()
        mini = self.made[0]
        # Made at its grown size, lent only once the main window is away and covered.
        self.assertEqual(self.calls, [('mini0', 'present'), ('main', 'put_away'),
                                      ('sheet', 'covered'), ('mini0', 'lender'),
                                      ('sheet', 'lend', 'queue'),
                                      ('mini0', 'show', 'queue', (320, 800)),
                                      ('queue', 'active')])
        self.assertEqual(mini.pane[2], 500)

    def test_a_pane_with_nothing_to_show_stays_closed_but_remembered(self):
        self.app.settings.set_string('mini-player-pane', 'lyrics')
        shown = []

        def make_window(app):
            window = FakeWindow(self.calls, 'mini')
            window.settings = app.settings
            window.showable = {'queue'}  # a song without lyrics
            shown.append(window)
            return window

        host = MiniPlayerHost(self.app, make_window)
        host.enter()
        self.assertEqual(shown[0].size, (320, 500))
        self.assertIsNone(shown[0].pane)
        self.assertEqual(self.app.settings.get_string('mini-player-pane'), 'lyrics')

    def test_leaving_with_a_pane_open_gives_the_view_back_first(self):
        self.app.settings.set_string('mini-player-pane', 'lyrics')
        self.host.enter()
        mini = self.made[0]
        mini.size = (320, 900)  # the user made the pane taller
        self.calls.clear()
        self.host.leave()
        self.assertEqual(self.calls, [('lyrics', 'inactive'), ('mini0', 'hide', 'lyrics'),
                                      ('sheet', 'return', 'lyrics'), ('sheet', 'uncovered'),
                                      ('main', 'present'), ('mini0', 'release')])
        settings = self.app.settings
        self.assertEqual(settings.get_int('mini-player-height'), 500)
        self.assertEqual(settings.get_int('mini-player-pane-height'), 400)
        self.assertEqual(settings.get_string('mini-player-pane'), 'lyrics')

    def test_quitting_with_a_pane_open_gives_the_view_back_and_stays_covered(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.host.enter()
        self.calls.clear()
        self.host.quit()
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini0', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue'), ('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 500)

    def test_no_main_window_no_panes(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.app.main = None
        self.host.enter()
        self.assertEqual(self.made[0].size, (320, 500))
        self.assertIsNone(self.made[0].panes)
        self.host.leave()
        self.assertEqual(self.calls[-1], ('mini0', 'release'))

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


FIXTURES = ROOT / 'tests' / 'fixtures'
QUEUE = {'index': 0, 'items': [
    dict(SONG, index=0),
    dict(SONG, id='i.demo0002', catalogId='1000000002', title='Pilot Light', index=1),
    dict(SONG, id='i.demo0003', catalogId='1000000003', title='Shoreline', index=2),
]}


class FakeItemActions:
    """The main window's item actions, as a context menu asks them."""

    def __init__(self):
        self.asked = []

    def menu_for(self, obj, **kwargs):
        self.asked.append((obj, kwargs))
        menu = Gio.Menu()
        menu.append('Go to Album', 'win.item-go-to-album')
        return menu


@requires_gtk
class PaneWindowTest(unittest.TestCase):
    """The real Now Playing sheet in a main window and the real mini player, through the
    host: the sheet's one LyricsView and one QueueView in the panes."""

    def setUp(self):
        from gi.repository import Adw, GLib, Gtk

        from applemusic.widgets.mini_player import MiniPlayer
        from applemusic.widgets.now_playing import NowPlayingSheet

        self.app = FakeApp(RatingEngine())
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        for key in PANE_KEYS:
            self.addCleanup(self.app.settings.reset, key)
        self.player = Player(self.app)
        self.player.track_grace_ms = 0
        self.sheet = NowPlayingSheet()
        self.bottom_sheet = Adw.BottomSheet(sheet=self.sheet, content=Gtk.Label())
        self.stack = Gtk.Stack()
        self.stack.add_named(self.bottom_sheet, 'main')
        # The main window: its sheet, its item actions, and the two Up Next runs.
        self.main = Gtk.ApplicationWindow(default_width=900, default_height=640,
                                          child=self.stack)
        self.addCleanup(self.main.destroy)
        self.main.now_playing = self.sheet
        self.main.item_actions = FakeItemActions()
        self.main.put_away = lambda: self.main.set_visible(False)
        self.ran = []
        for name, kind in (('item-move-in-queue', '(iis)'), ('item-remove-from-queue', '(is)')):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new(kind))
            action.connect('activate', lambda action, parameter: self.ran.append(
                (action.get_name(), parameter.unpack())))
            self.main.add_action(action)
        self.sheet.set_player(self.player, self.app, self.bottom_sheet)
        self.main.present()
        self.assertTrue(wait_for(self.main.get_mapped))
        self.app.main_window = lambda: self.main

        def make_window(app):
            window = MiniPlayer()
            window.set_player(app.player, app)
            return window

        self.app.player = self.player
        self.host = MiniPlayerHost(self.app, make_window)
        self.addCleanup(self.host.quit)
        self.mini = None
        self.lyrics = self.sheet.lyrics_view
        self.queue = self.sheet.queue_view
        self.active = []
        for name, view in (('lyrics', self.lyrics), ('queue', self.queue)):
            def set_active(active, name=name, view=view, real=view.set_active):
                self.active.append((name, active, self.place(view)))
                real(active)
            view.set_active = set_active

    def place(self, view):
        parent = view.get_parent()
        if parent in (self.sheet.lyrics_slot, self.sheet.queue_slot):
            return 'sheet'
        if self.mini is not None and parent is self.mini.view.pane_slot:
            return 'mini'
        return None

    def of(self, name):
        """What `name`'s view was told (the sheet tells both of its own as it changes)."""
        return [event for event in self.active if event[0] == name]

    def play(self, lyrics='lyrics_syllable.json'):
        import json

        answer = None
        if lyrics:
            with open(FIXTURES / lyrics, encoding='utf-8') as file:
                answer = json.load(file)
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 40,
                           'duration': 214, 'lyrics': answer, 'queue': QUEUE})

    def enter(self):
        self.host.enter()
        self.mini = self.host.window  # kept: the host forgets it as it leaves
        self.assertTrue(wait_for(self.mini.get_mapped))
        return self.mini

    def toggle(self, mini, tab):
        mini.activate_action('win.' + ('show-lyrics' if tab == 'lyrics' else 'show-queue'),
                             None)

    def pressed(self, mini):
        return tuple(mini.pane_actions[tab].get_state().get_boolean()
                     for tab in ('lyrics', 'queue'))

    def test_the_toggles_are_off_until_there_is_something_to_show(self):
        mini = self.enter()
        view = mini.view
        self.assertFalse(view.lyrics_button.get_sensitive())
        self.assertFalse(view.queue_button.get_sensitive())
        self.play(lyrics=None)
        self.assertFalse(view.lyrics_button.get_sensitive())  # a song without lyrics
        self.assertTrue(view.queue_button.get_sensitive())
        self.play()
        self.assertTrue(view.lyrics_button.get_sensitive())
        self.assertEqual(self.pressed(mini), (False, False))
        self.assertFalse(view.pane_slot.get_visible())
        self.assertEqual(view.lyrics_button.get_tooltip_text(), 'Lyrics (Shift+Ctrl+L)')
        self.assertEqual(view.queue_button.get_tooltip_text(), 'Up Next (Shift+Ctrl+U)')

    def test_one_lyrics_view_active_in_one_place(self):
        """The sheet open on Lyrics, the mini player, its lyrics pane, back: the sheet's
        own view, active only where it shows."""
        self.play()
        self.bottom_sheet.set_open(True)
        self.assertTrue(wait_for(lambda: self.lyrics._active))
        self.active.clear()
        mini = self.enter()
        # The window hidden: its sheet covered, the view inactive there, lent to no one.
        self.assertEqual(self.of('lyrics'), [('lyrics', False, 'sheet')])
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.active.clear()
        self.toggle(mini, 'lyrics')
        self.assertEqual(self.of('lyrics'), [('lyrics', True, 'mini')])
        self.assertIs(mini.view.pane_slot.get_child(), self.lyrics)
        self.assertTrue(mini.view.pane_slot.get_visible())
        self.assertEqual(self.pressed(mini), (True, False))
        self.assertEqual(mini.get_default_size(), (320, 500 + 320))
        self.active.clear()
        self.toggle(mini, 'lyrics')  # again: closed, the view back and inactive
        self.assertEqual(self.of('lyrics'), [('lyrics', False, 'mini')])
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.assertEqual(self.pressed(mini), (False, False))
        self.assertEqual(mini.get_default_size(), (320, 500))
        self.assertEqual(self.lyrics._next_change_source, 0)
        self.assertIsNone(self.lyrics._sweep_tick)
        # Open again, and leave with it open: back in the sheet, active there (it is open
        # on Lyrics), after the mini player let it go.
        self.toggle(mini, 'lyrics')
        self.active.clear()
        self.host.leave()
        self.assertEqual(self.of('lyrics'),
                         [('lyrics', False, 'mini'), ('lyrics', True, 'sheet')])
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.assertTrue(self.main.get_visible())

    def test_the_other_toggle_swaps_the_views(self):
        self.play()
        mini = self.enter()
        self.toggle(mini, 'queue')
        self.assertEqual(self.place(self.queue), 'mini')
        self.assertEqual(self.pressed(mini), (False, True))
        size = mini.get_default_size()
        self.active.clear()
        self.toggle(mini, 'lyrics')
        self.assertEqual(self.active, [('queue', False, 'mini'), ('lyrics', True, 'mini')])
        self.assertEqual(self.place(self.queue), 'sheet')
        self.assertEqual(self.place(self.lyrics), 'mini')
        self.assertEqual(self.pressed(mini), (True, False))
        self.assertEqual(mini.get_default_size(), size)
        self.host.leave()
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.assertEqual(self.place(self.queue), 'sheet')
        self.assertFalse(self.lyrics._active)  # the sheet is closed
        self.assertEqual(self.app.settings.get_string('mini-player-pane'), 'lyrics')

    def test_the_pane_remembered_opens_with_the_mini_player(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.app.settings.set_int('mini-player-pane-height', 240)
        self.play()
        mini = self.enter()
        self.assertEqual(self.place(self.queue), 'mini')
        self.assertEqual(mini.get_default_size(), (320, 740))
        self.assertEqual(self.pressed(mini), (False, True))
        # The controls keep the layout of the window without the pane.
        self.assertTrue(wait_for(lambda: mini.view.shown_layout is not None))
        self.assertEqual(mini.view.shown_layout, layout_for(320, 500 - 46))

    def test_no_full_screen_while_a_view_is_lent(self):
        from applemusic.fullscreen import FullscreenHost

        fullscreen = FullscreenHost(self.main, self.stack, self.sheet, self.player, self.app)
        self.addCleanup(fullscreen.release)
        self.play()
        mini = self.enter()
        self.toggle(mini, 'lyrics')
        self.assertFalse(self.sheet.holds_lyrics())
        self.assertIsNone(self.sheet.lend_lyrics())  # one borrower at a time
        fullscreen.enter()
        self.assertFalse(fullscreen.shown)
        self.assertEqual(self.place(self.lyrics), 'mini')
        self.host.leave()
        fullscreen.enter()
        self.assertTrue(fullscreen.shown)
        fullscreen.leave()

    def test_up_next_in_the_pane_runs_the_main_windows_actions(self):
        from gi.repository import GLib

        self.play()
        mini = self.enter()
        self.toggle(mini, 'queue')
        self.assertTrue(wait_for(self.queue.list_view.get_mapped))
        # Alt+Down, a drop (QueueView.move()) and Delete activate win.item-*: the main
        # window's, through the pane slot's group, not the mini player's own `win`.
        self.queue.move(1, 2, 'i.demo0002')
        self.queue.list_view.activate_action('win.item-remove-from-queue',
                                             GLib.Variant('(is)', (2, 'i.demo0003')))
        self.assertEqual(self.ran, [('item-move-in-queue', (1, 2, 'i.demo0002')),
                                    ('item-remove-from-queue', (2, 'i.demo0003'))])
        # The header's toggles are outside the slot: the mini player's own actions.
        self.assertTrue(mini.view.queue_button.get_sensitive())
        self.assertIsNone(mini.lookup_action('item-move-in-queue'))

    def test_an_entrys_menu_is_the_main_windows(self):
        from applemusic.widgets import context_menu

        self.play()
        mini = self.enter()
        self.toggle(mini, 'queue')
        self.assertTrue(wait_for(self.queue.list_view.get_mapped))
        entry = self.player.queue.get_item(1)
        popover = context_menu.popup(self.queue.list_view, entry)
        self.assertIsNotNone(popover)
        self.assertEqual(self.main.item_actions.asked[0][0], entry)
        popover.popdown()
        self.assertTrue(wait_for(lambda: popover.get_parent() is None))

    def test_the_keys_toggle_the_panes(self):
        from gi.repository import Gdk

        self.play()
        mini = self.enter()
        mini.get_application = lambda: self.app
        self.app.lookup_action = lambda _name: None
        mods = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        mini.view.play_button.grab_focus()
        self.assertTrue(mini._on_key_pressed(None, Gdk.KEY_U, 0, mods))
        self.assertEqual(self.pressed(mini), (False, True))
        self.assertTrue(mini._on_key_pressed(None, Gdk.KEY_L, 0, mods))
        self.assertEqual(self.pressed(mini), (True, False))
        self.assertTrue(mini._on_key_pressed(None, Gdk.KEY_L, 0, mods))
        self.assertEqual(self.pressed(mini), (False, False))

    def test_closing_a_pane_that_holds_the_focus_puts_it_on_its_toggle(self):
        self.play()
        mini = self.enter()
        self.toggle(mini, 'queue')
        self.assertTrue(wait_for(self.queue.history_button.get_mapped))
        self.assertTrue(self.queue.history_button.grab_focus())
        self.toggle(mini, 'queue')
        self.assertIs(mini.get_focus(), mini.view.queue_button)

    def test_released_with_a_pane_open_the_view_is_back_in_the_sheet(self):
        # Whatever closes the window: never a lent view in a window being destroyed.
        self.play()
        mini = self.enter()
        self.toggle(mini, 'lyrics')
        self.host.window = None
        mini.release()
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.assertFalse(self.lyrics._active)


if __name__ == '__main__':
    unittest.main()
