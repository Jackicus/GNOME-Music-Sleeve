# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""mini_player.py: the mini player's layout (the cover at each size of its controls), its
panes (how a window with one divides, when it grows for one and by how much, what is
remembered of its size, the lending and its order: Panes with stand-ins), and its host with
stand-ins (one window at a time, the main window put away and back, its size kept, closing
it as leaving it); then the window itself following a real Player (the item, live radio,
the low layout, the one row of buttons and the volume keys) and letting go of it. That a
closed mini player is freed is test_page_lifetime's; its keys are scripts/a11y_check.py's.
Last, the panes with the real Now Playing sheet: its one LyricsView and one QueueView lent
and given back, active in one place at a time, the divider between the controls and the
pane, and Up Next's edits and menus reaching the main window's actions."""

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
from applemusic.mini_player import (MiniPlayerHost, Panes, divide,  # noqa: E402
                                    grow_for_pane, layout_for)
from applemusic.player import Player  # noqa: E402

# No artwork URL: nothing is fetched.
SONG = dict(TRACK, artUrl=None)
STATION = {'id': 'ra.demo001', 'title': 'Invented FM', 'kind': 'radioStation', 'isLive': True,
           'artUrl': None, 'index': 0}


HEADER = 46  # the header bar's height, as the stand-in window answers it


class LayoutTest(unittest.TestCase):
    def test_the_default_size_has_the_cover_as_wide_as_the_controls(self):
        # The settings' default window, its header bar taken off: the cover from margin
        # to margin, as the seek row and the row of buttons are.
        schema = Gio.SettingsSchemaSource.get_default().lookup(SCHEMA_ID, True)
        width, height = (schema.get_key(key).get_default_value().get_int32()
                         for key in ('mini-player-width', 'mini-player-height'))
        self.assertEqual((width, height), (360, 548))
        self.assertEqual(width, mini_player.MIN_WIDTH)
        across = width - 2 * mini_player.MARGIN
        for header in (HEADER, HEADER + 1):
            self.assertEqual(tuple(layout_for(width, height - header)), (False, across))

    def test_the_cover_fits_the_room_over_the_controls(self):
        layout = layout_for(360, 450)
        self.assertFalse(layout.short)
        self.assertLessEqual(layout.art_size + mini_player.BELOW_ART
                             + mini_player.TOP_MARGIN, 450)
        self.assertEqual(layout.art_size % 4, 0)

    def test_the_cover_grows_with_the_window_up_to_its_file(self):
        self.assertGreater(layout_for(400, 600).art_size, layout_for(360, 450).art_size)
        self.assertEqual(layout_for(2000, 2000).art_size, mini_player.MAX_ART)

    def test_low_controls_have_the_cover_beside_the_titles(self):
        least = mini_player.SHORT_HEIGHT
        self.assertEqual(layout_for(360, least), (True, mini_player.SMALL_ART))
        self.assertEqual(layout_for(360, least - 40), (True, mini_player.SMALL_ART))
        self.assertEqual(layout_for(800, least), (True, mini_player.SMALL_ART))

    def test_the_cover_beside_the_titles_grows_with_the_room(self):
        least = mini_player.SHORT_HEIGHT
        self.assertEqual(layout_for(520, least + 20), (True, mini_player.SMALL_ART + 20))
        self.assertEqual(layout_for(520, least + 22), (True, mini_player.SMALL_ART + 20))
        # No larger than SIDE_ART, or a third of the width: the titles keep theirs.
        self.assertEqual(layout_for(520, least + 100), (True, mini_player.SIDE_ART))
        self.assertEqual(layout_for(360, least + 100), (True, 108))
        # Then over the titles, from the height that has room for MIN_ART there.
        over = mini_player.TOP_MARGIN + mini_player.BELOW_ART + mini_player.MIN_ART
        self.assertTrue(layout_for(520, over - 1).short)
        self.assertEqual(layout_for(520, over), (False, mini_player.MIN_ART))

    def test_the_least_window_is_the_short_layout(self):
        self.assertGreaterEqual(mini_player.MIN_HEIGHT, HEADER + 1 + mini_player.SHORT_HEIGHT)
        layout = layout_for(mini_player.MIN_WIDTH, mini_player.MIN_HEIGHT - HEADER)
        self.assertTrue(layout.short)
        self.assertLess(layout.art_size, mini_player.SMALL_ART + 8)


class DivideTest(unittest.TestCase):
    def test_a_window_with_the_room_does_not_grow(self):
        need = HEADER + mini_player.SHORT_HEIGHT + mini_player.PANE_OPEN
        self.assertEqual(grow_for_pane(548, HEADER), 0)
        self.assertEqual(grow_for_pane(need, HEADER), 0)
        self.assertEqual(grow_for_pane(2000, HEADER), 0)

    def test_a_low_window_grows_by_what_is_missing(self):
        need = HEADER + mini_player.SHORT_HEIGHT + mini_player.PANE_OPEN
        self.assertEqual(grow_for_pane(need - 1, HEADER), 1)
        self.assertEqual(grow_for_pane(mini_player.MIN_HEIGHT, HEADER),
                         need - mini_player.MIN_HEIGHT)

    def test_the_pane_has_its_wish_and_the_controls_the_rest(self):
        self.assertEqual(divide(500, 320), (180, 320))
        self.assertEqual(divide(900, 320), (580, 320))
        self.assertEqual(divide(500, 200), (300, 200))

    def test_the_controls_keep_the_short_layout(self):
        least = mini_player.SHORT_HEIGHT
        self.assertEqual(divide(400, 320), (least, 400 - least))
        self.assertEqual(divide(least + mini_player.PANE_OPEN, 320),
                         (least, mini_player.PANE_OPEN))  # a window grown for the pane

    def test_the_pane_is_no_lower_than_its_least(self):
        self.assertEqual(divide(500, 20), (500 - mini_player.PANE_MIN, mini_player.PANE_MIN))
        self.assertEqual(divide(100, 320), (mini_player.SHORT_HEIGHT, 0))


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
        self.pane = None       # (name, the widget, the height wished) of the pane shown
        self.left = None       # the pane's height, when the user changed it
        self.panes = None

    def can_show(self, pane):
        return pane in self.showable

    def set_lender(self, sheet, main):
        self.calls.append((self.name, 'lender'))
        if sheet is not None:
            self.panes = Panes(self, sheet, self.settings)

    def fixed_size(self):
        return self.fixed

    def header_height(self):
        return HEADER

    def pane_height(self):
        return self.left if self.pane is not None else None

    def show_pane(self, name, widget, height):
        self.pane = (name, widget, height)
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
# The least height of a window with a pane just opened, and of the mini player.
NEED = HEADER + mini_player.SHORT_HEIGHT + mini_player.PANE_OPEN
LEAST = mini_player.MIN_HEIGHT


class PanesTest(unittest.TestCase):
    """Panes with a stand-in window and sheet: a window 360 by 548, the pane 320."""

    def setUp(self):
        self.calls = []
        self.settings = Gio.Settings.new(SCHEMA_ID)
        for key in PANE_KEYS:
            self.addCleanup(self.settings.reset, key)
        self.window = FakeWindow(self.calls, 'mini', (360, 548))
        self.sheet = FakeSheet(self.calls)
        self.panes = Panes(self.window, self.sheet, self.settings)

    def test_opening_lends_and_shows_in_the_window_as_it_is_then_makes_active(self):
        self.assertTrue(self.panes.show('lyrics'))
        self.assertEqual(self.calls, [('sheet', 'lend', 'lyrics'),
                                      ('mini', 'show', 'lyrics', (360, 548)),
                                      ('lyrics', 'active')])
        self.assertEqual(self.panes.shown, 'lyrics')
        self.assertEqual(self.panes.grown, 0)
        self.assertEqual(self.window.pane[2], 320)  # the height wished: the setting's
        self.assertEqual(self.settings.get_string('mini-player-pane'), 'lyrics')

    def test_closing_makes_inactive_and_returns_the_window_as_it_is(self):
        self.panes.show('queue')
        self.calls.clear()
        self.panes.close()
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue')])
        self.assertEqual(self.window.size, (360, 548))
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.settings.get_string('mini-player-pane'), '')
        self.panes.close()  # nothing to close
        self.assertEqual(len(self.calls), 3)

    def test_a_window_too_low_grows_by_what_is_missing_and_shrinks_back(self):
        self.window.size = (360, LEAST)
        self.panes.show('lyrics')
        self.assertEqual(self.window.size, (360, NEED))
        self.assertEqual(self.panes.grown, NEED - LEAST)
        # Shown once it has grown: one layout, at its new size.
        self.assertEqual(self.calls[1], ('mini', 'show', 'lyrics', (360, NEED)))
        self.panes.close()
        self.assertEqual(self.window.size, (360, LEAST))
        self.assertEqual(self.panes.grown, 0)
        # The pane's height is still the user's wish, not what the low window gave it.
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 320)

    def test_a_window_a_little_short_grows_a_little(self):
        self.window.size = (400, NEED - 30)
        self.panes.show('queue')
        self.assertEqual(self.window.size, (400, NEED))
        self.panes.close()
        self.assertEqual(self.window.size, (400, NEED - 30))

    def test_a_grown_window_resized_shrinks_by_what_it_grew(self):
        self.window.size = (360, LEAST)
        self.panes.show('lyrics')
        self.window.size = (420, NEED + 100)  # dragged larger with the pane open
        self.window.left = mini_player.PANE_OPEN + 100
        self.panes.close()
        self.assertEqual(self.window.size, (420, LEAST + 100))
        self.assertEqual(self.settings.get_int('mini-player-pane-height'),
                         mini_player.PANE_OPEN + 100)
        # Left lower than what it grew by leaves: never under the least.
        self.window.size = (420, LEAST + 10)
        self.panes.show('lyrics')
        self.assertEqual(self.panes.grown, NEED - LEAST - 10)
        self.window.size = (420, NEED - 60)
        self.panes.close()
        self.assertEqual(self.window.size, (420, LEAST))

    def test_the_other_toggle_swaps_with_no_resize(self):
        self.panes.show('lyrics')
        self.calls.clear()
        self.panes.toggle('queue')
        self.assertEqual(self.calls, [('lyrics', 'inactive'), ('mini', 'hide', 'lyrics'),
                                      ('sheet', 'return', 'lyrics'),
                                      ('sheet', 'lend', 'queue'),
                                      ('mini', 'show', 'queue', (360, 548)),
                                      ('queue', 'active')])
        self.assertEqual(self.sheet.out, {'queue'})
        self.panes.toggle('queue')  # the one shown: closed
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.sheet.out, set())
        self.assertEqual(self.window.size, (360, 548))

    def test_a_swap_keeps_the_divider_where_the_user_left_it(self):
        self.panes.show('lyrics')
        self.window.left = 250  # the divider dragged down
        self.panes.toggle('queue')
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 250)
        self.assertEqual(self.window.pane[::2], ('queue', 250))

    def test_a_swap_in_a_grown_window_stays_grown(self):
        self.window.size = (360, LEAST)
        self.panes.show('lyrics')
        self.panes.toggle('queue')
        self.assertEqual(self.window.size, (360, NEED))
        self.assertEqual(self.panes.grown, NEED - LEAST)
        self.panes.close()
        self.assertEqual(self.window.size, (360, LEAST))

    def test_the_divider_dragged_is_the_panes_height_next_time(self):
        self.panes.show('lyrics')
        self.window.left = 180
        self.panes.close()
        self.assertEqual(self.window.size, (360, 548))  # the window is not the pane's
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 180)
        self.panes.show('queue')
        self.assertEqual(self.window.pane[2], 180)

    def test_a_pane_left_as_it_opened_writes_nothing(self):
        self.settings.set_int('mini-player-pane-height', 900)  # more than the window has
        self.panes.show('lyrics')
        self.panes.close()  # the stand-in answers None: unchanged
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 900)

    def test_a_window_that_cannot_grow_keeps_its_size(self):
        self.window.fixed = True
        self.window.size = (360, LEAST)
        self.panes.show('lyrics')
        self.assertEqual(self.window.size, (360, LEAST))
        self.assertEqual(self.panes.grown, 0)
        self.assertEqual(self.calls[-1], ('lyrics', 'active'))
        self.panes.close()
        self.assertEqual(self.window.size, (360, LEAST))

    def test_nothing_to_lend_shows_nothing(self):
        self.window.size = (360, LEAST)
        self.sheet.out.add('lyrics')  # the full-screen player has it
        self.assertFalse(self.panes.show('lyrics'))
        self.assertEqual(self.panes.shown, '')
        self.assertEqual(self.window.size, (360, LEAST))
        self.assertFalse(Panes(self.window, None, self.settings).show('queue'))
        self.assertFalse(self.panes.show('videos'))

    def test_giving_back_as_the_mini_player_goes_keeps_the_pane_for_next_time(self):
        self.panes.show('queue')
        self.window.size = (400, 700)
        self.window.left = 400
        self.calls.clear()
        self.assertEqual(self.panes.give_back(), (400, 700))
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue')])
        self.assertEqual(self.settings.get_string('mini-player-pane'), 'queue')
        self.assertEqual(self.settings.get_int('mini-player-pane-height'), 400)
        self.assertIsNone(self.panes.give_back())  # nothing lent any more

    def test_giving_back_a_grown_window_is_its_size_without_what_it_grew(self):
        self.window.size = (360, LEAST + 40)
        self.panes.show('lyrics')
        self.assertEqual(self.window.size, (360, NEED))
        self.assertEqual(self.panes.give_back(), (360, LEAST + 40))


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
        self.app.settings.set_int('mini-player-width', 400)
        self.app.settings.set_int('mini-player-height', 420)
        self.host.enter()
        self.assertTrue(self.host.shown)
        self.assertIs(self.host.window, self.made[0])
        self.assertEqual(self.made[0].size, (400, 420))
        # The sheet of the hidden window covered: its views inactive, to lend.
        self.assertEqual(self.calls, [('mini0', 'present'), ('main', 'put_away'),
                                      ('sheet', 'covered'), ('mini0', 'lender')])

    def test_a_size_kept_by_an_older_version_is_raised_to_the_least(self):
        self.app.settings.set_int('mini-player-width', 280)
        self.app.settings.set_int('mini-player-height', 200)
        self.host.enter()
        self.assertEqual(self.made[0].size, (mini_player.MIN_WIDTH, mini_player.MIN_HEIGHT))

    def test_one_at_a_time(self):
        self.host.enter()
        self.host.enter()
        self.assertEqual(len(self.made), 1)
        self.assertEqual(self.calls[-1], ('mini0', 'present'))

    def test_leaving_brings_the_main_window_back_and_keeps_the_size(self):
        self.host.enter()
        self.made[0].size = (380, 400)  # the user resized it
        self.calls.clear()
        self.host.leave()
        self.assertFalse(self.host.shown)
        self.assertEqual(self.calls, [('sheet', 'uncovered'), ('main', 'present'),
                                      ('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-width'), 380)
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 400)
        self.host.leave()  # nothing to leave
        self.assertEqual(len(self.calls), 3)

    def test_the_pane_it_last_had_opens_with_it_in_the_window_as_it_was(self):
        settings = self.app.settings
        settings.set_string('mini-player-pane', 'queue')
        settings.set_int('mini-player-pane-height', 300)
        self.host.enter()
        mini = self.made[0]
        # Lent only once the main window is away and covered; the window not resized.
        self.assertEqual(self.calls, [('mini0', 'present'), ('main', 'put_away'),
                                      ('sheet', 'covered'), ('mini0', 'lender'),
                                      ('sheet', 'lend', 'queue'),
                                      ('mini0', 'show', 'queue', (360, 548)),
                                      ('queue', 'active')])
        self.assertEqual(mini.pane[2], 300)
        self.assertEqual(mini.panes.grown, 0)

    def test_a_low_window_is_made_with_the_room_for_the_pane_it_last_had(self):
        settings = self.app.settings
        settings.set_string('mini-player-pane', 'lyrics')
        settings.set_int('mini-player-height', LEAST)
        self.host.enter()
        mini = self.made[0]
        # Made at its grown size, before it is presented: no second resize.
        self.assertEqual(self.calls[0], ('mini0', 'present'))
        self.assertEqual(self.calls[5], ('mini0', 'show', 'lyrics', (360, NEED)))
        self.assertEqual(mini.panes.grown, NEED - LEAST)
        self.host.leave()
        self.assertEqual(settings.get_int('mini-player-height'), LEAST)  # the user's
        self.assertEqual(settings.get_int('mini-player-pane-height'), 320)

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
        self.app.settings.set_int('mini-player-height', LEAST)
        host.enter()
        self.assertEqual(shown[0].size, (360, LEAST))  # not grown for a pane not shown
        self.assertIsNone(shown[0].pane)
        self.assertEqual(self.app.settings.get_string('mini-player-pane'), 'lyrics')

    def test_leaving_with_a_pane_open_gives_the_view_back_first(self):
        self.app.settings.set_string('mini-player-pane', 'lyrics')
        self.host.enter()
        mini = self.made[0]
        mini.size = (360, 900)  # the user made the window taller: the pane's
        mini.left = 672
        self.calls.clear()
        self.host.leave()
        self.assertEqual(self.calls, [('lyrics', 'inactive'), ('mini0', 'hide', 'lyrics'),
                                      ('sheet', 'return', 'lyrics'), ('sheet', 'uncovered'),
                                      ('main', 'present'), ('mini0', 'release')])
        settings = self.app.settings
        self.assertEqual(settings.get_int('mini-player-height'), 900)
        self.assertEqual(settings.get_int('mini-player-pane-height'), 672)
        self.assertEqual(settings.get_string('mini-player-pane'), 'lyrics')

    def test_quitting_with_a_pane_open_gives_the_view_back_and_stays_covered(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.host.enter()
        self.calls.clear()
        self.host.quit()
        self.assertEqual(self.calls, [('queue', 'inactive'), ('mini0', 'hide', 'queue'),
                                      ('sheet', 'return', 'queue'), ('mini0', 'release')])
        self.assertEqual(self.app.settings.get_int('mini-player-height'), 548)

    def test_no_main_window_no_panes(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.app.main = None
        self.host.enter()
        self.assertEqual(self.made[0].size, (360, 548))
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
        self.made[0].size = (380, 300)
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
        self.window = MiniPlayer(default_width=360, default_height=500)
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
        self.window.set_default_size(360, mini_player.MIN_HEIGHT)
        self.assertTrue(wait_for(lambda: self.view.shown_layout is not None
                                 and self.view.shown_layout.short))
        self.assertLess(self.view.cover.size, mini_player.SMALL_ART + 8)
        self.assertEqual(self.view.title_label.get_xalign(), 0)
        self.view.apply_layout(layout_for(360, mini_player.SHORT_HEIGHT))
        self.assertEqual(self.view.cover.size, mini_player.SMALL_ART)
        self.assertTrue(self.view.cover.has_css_class('small'))
        side = layout_for(520, mini_player.SHORT_HEIGHT + 60)
        self.view.apply_layout(side)  # more room: a larger cover, still beside the titles
        self.assertEqual(self.view.cover.size, mini_player.SMALL_ART + 60)
        self.assertEqual(self.view.title_label.get_xalign(), 0)
        self.assertFalse(self.view.cover.has_css_class('small'))
        self.assertFalse(self.view.cover.has_css_class('large'))
        tall = layout_for(360, 450)
        self.view.apply_layout(tall)  # as a taller window would have it
        self.assertEqual(self.view.cover.size, tall.art_size)
        self.assertEqual(self.view.title_label.get_xalign(), 0.5)
        self.assertTrue(self.view.cover.has_css_class('large'))
        self.assertFalse(self.view.cover.has_css_class('small'))

    def controls(self):
        """The view's buttons in the order they are laid out, across then down."""
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

    ROW = ('heart_button', 'shuffle_button', 'previous_button', 'play_button',
           'next_button', 'repeat_button', 'volume_button')

    def sized(self, width, height):
        """Whether the view is laid out for a window made `width` by `height`: that size,
        less the border an X11 window without a compositor counts in its own (CI's), and
        never less than the mini player's least. A predicate."""
        def laid_out():
            view = self.view
            return (view.shown_layout is not None
                    and max(width - 12, mini_player.MIN_WIDTH) <= view.get_width() <= width
                    and max(height - 12, mini_player.MIN_HEIGHT) <= view.get_height()
                    <= height)
        return laid_out

    def test_the_buttons_are_one_row_in_one_order_at_every_size(self):
        from applemusic.widgets.mini_player import MiniPlayer

        # A window made at each size (one resized twice in a row as it maps may keep the
        # first size: the compositor's answer to the map comes in between).
        for width, height in ((360, 500), (mini_player.MIN_WIDTH, mini_player.MIN_HEIGHT),
                              (600, 300), (480, 700)):
            self.close()
            self.window = MiniPlayer(default_width=width, default_height=height)
            self.window.set_player(self.player, self.app)
            self.view = view = self.window.view
            self.window.present()
            self.assertTrue(wait_for(self.sized(width, height)), (width, height))
            row = [getattr(view, name) for name in self.ROW]
            self.assertEqual(self.controls(), row, (width, height))
            places = [button.compute_bounds(view)[1] for button in row]
            centres = {round(bounds.get_y() + bounds.get_height() / 2) for bounds in places}
            self.assertEqual(len(centres), 1, (width, height, centres))
            # Whole inside the view's margins.
            self.assertGreaterEqual(places[0].get_x(), mini_player.MARGIN - 1)
            self.assertLessEqual(places[-1].get_x() + places[-1].get_width(),
                                 view.get_width() - mini_player.MARGIN + 1)
            # And one box holds them, in the order Tab takes: nothing moves between two.
            order, child = [], view.transport_box.get_first_child()
            while child is not None:
                order.append(child)
                child = child.get_next_sibling()
            self.assertEqual(order, row)

    def test_the_least_width_is_the_row_and_the_margins(self):
        # MIN_WIDTH against the widgets, with the app's stylesheet: a button added to the
        # row, or a wider one, has to raise it.
        from gi.repository import Gtk

        row = self.view.transport_box.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        self.assertLessEqual(row + 2 * mini_player.MARGIN, mini_player.MIN_WIDTH)
        self.assertGreater(row + 2 * mini_player.MARGIN, mini_player.MIN_WIDTH - 12)
        # The least is the view's own, so the window's counts whatever border it has.
        self.assertEqual(self.view.measure(Gtk.Orientation.HORIZONTAL, -1)[0],
                         mini_player.MIN_WIDTH)
        self.assertEqual(self.view.measure(Gtk.Orientation.VERTICAL, -1)[0],
                         mini_player.MIN_HEIGHT)
        self.assertGreaterEqual(self.window.measure(Gtk.Orientation.HORIZONTAL, -1)[0],
                                mini_player.MIN_WIDTH)
        header = self.view.header_bar.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        self.assertLessEqual(header, mini_player.MIN_WIDTH)

    def test_the_layouts_fit_the_sizes_the_rule_gives_them(self):
        # layout_for()'s measures against the widgets': each layout's content is no taller
        # or wider (its margins counted) than the least size the rule shows it at.
        from gi.repository import Gtk

        view = self.view
        self.player.apply({'state': 'playing', 'track': SONG, 'position': 1,
                           'duration': 214})
        least = mini_player.SHORT_HEIGHT
        over = mini_player.TOP_MARGIN + mini_player.BELOW_ART + mini_player.MIN_ART
        for width, height in ((360, least), (360, least + 40), (520, least + 64),
                              (360, over - 1), (360, over), (360, 502), (700, 400)):
            layout = layout_for(width, height)
            view.apply_layout(layout)
            needed_height = view.content_box.measure(Gtk.Orientation.VERTICAL, -1)[0]
            needed_width = view.content_box.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            self.assertLessEqual(needed_height, height, (width, height, layout))
            self.assertLessEqual(needed_width, width, (width, height, layout))
        # And the header bar the least window counts is the one measured.
        header = view.header_height()
        self.assertLessEqual(header + least, mini_player.MIN_HEIGHT)

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
        self.assertFalse(view.pane_box.get_visible())
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
        size = mini.get_default_size()
        self.assertEqual(size.height, 548)
        self.toggle(mini, 'lyrics')
        self.assertEqual(self.of('lyrics'), [('lyrics', True, 'mini')])
        self.assertIs(mini.view.pane_slot.get_child(), self.lyrics)
        self.assertTrue(mini.view.pane_box.get_visible())
        self.assertEqual(self.pressed(mini), (True, False))
        self.assertEqual(mini.get_default_size(), size)  # opened inside the window
        self.active.clear()
        self.toggle(mini, 'lyrics')  # again: closed, the view back and inactive
        self.assertEqual(self.of('lyrics'), [('lyrics', False, 'mini')])
        self.assertEqual(self.place(self.lyrics), 'sheet')
        self.assertEqual(self.pressed(mini), (False, False))
        self.assertEqual(mini.get_default_size(), size)
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

    def laid_out(self, mini):
        """The pane placed: the view has allocated since it was shown."""
        self.assertTrue(wait_for(lambda: mini.view.pane and mini.view._pane_wish is None
                                 and mini.view.paned.get_height() > 0))
        return mini.view.paned.get_height(), mini.view.paned.get_position()

    def test_the_pane_remembered_opens_with_the_mini_player(self):
        self.app.settings.set_string('mini-player-pane', 'queue')
        self.app.settings.set_int('mini-player-pane-height', 240)
        self.play()
        mini = self.enter()
        self.assertEqual(self.place(self.queue), 'mini')
        self.assertEqual(mini.get_default_size().height, 548)
        self.assertEqual(self.pressed(mini), (False, True))
        # The pane has its height from the bottom, the controls the layout of the rest.
        height, position = self.laid_out(mini)
        self.assertEqual(height, mini.view.get_height() - mini.header_height())
        self.assertEqual(height - position, 240)
        self.assertTrue(wait_for(
            lambda: mini.view.shown_layout == layout_for(360, position)))

    def test_a_pane_opens_inside_the_window_over_the_short_layout(self):
        self.app.settings.set_int('mini-player-pane-height', 300)
        self.play()
        mini = self.enter()
        self.assertTrue(wait_for(lambda: mini.view.shown_layout is not None
                                 and not mini.view.shown_layout.short))
        window = mini.get_default_size()
        size = (mini.view.get_width(), mini.view.get_height())
        self.assertEqual(window.height, 548)
        self.toggle(mini, 'lyrics')
        height, position = self.laid_out(mini)
        self.assertEqual(mini.get_default_size(), window)  # the window as it was
        self.assertEqual((mini.view.get_width(), mini.view.get_height()), size)
        self.assertEqual(height - position, 300)  # the setting's
        self.assertGreaterEqual(position, mini_player.SHORT_HEIGHT)
        self.assertTrue(wait_for(lambda: mini.view.shown_layout.short))
        self.assertIsNone(mini.pane_height())  # as it opened: nothing to remember
        self.toggle(mini, 'lyrics')
        self.assertTrue(wait_for(lambda: not mini.view.shown_layout.short))
        self.assertEqual(self.app.settings.get_int('mini-player-pane-height'), 300)

    def test_the_divider_stops_at_the_short_layout_and_at_the_panes_least(self):
        self.play()
        mini = self.enter()
        self.toggle(mini, 'queue')
        height, _position = self.laid_out(mini)
        paned = mini.view.paned
        paned.set_position(0)
        self.assertTrue(wait_for(lambda: paned.get_position() == mini_player.SHORT_HEIGHT))
        paned.set_position(5000)
        self.assertTrue(wait_for(
            lambda: paned.get_position() == height - mini_player.PANE_MIN))
        self.assertEqual(mini.pane_height(), mini_player.PANE_MIN)
        self.assertTrue(wait_for(lambda: not mini.view.shown_layout.short))  # a cover again

    def test_the_divider_dragged_is_remembered(self):
        self.play()
        mini = self.enter()
        self.toggle(mini, 'lyrics')
        height, _position = self.laid_out(mini)
        mini.view.paned.set_position(height - 200)
        self.assertTrue(wait_for(lambda: mini.pane_height() == 200))
        self.toggle(mini, 'queue')  # the other pane: the divider where it was
        height, position = self.laid_out(mini)
        self.assertEqual(height - position, 200)
        self.toggle(mini, 'queue')
        self.assertEqual(self.app.settings.get_int('mini-player-pane-height'), 200)
        self.assertEqual(mini.get_default_size().height, 548)

    def test_a_low_window_has_the_room_for_its_pane_and_shrinks_back(self):
        # The pane it last had opens with it: the window is made with the room, so this
        # needs no resize of a window just mapped (which can lose to the compositor's
        # answer to the map). Opening one by its toggle in a low window is PanesTest's,
        # and scripts/a11y_check.py's with real keys.
        least = mini_player.MIN_HEIGHT
        self.app.settings.set_int('mini-player-height', least)
        self.app.settings.set_string('mini-player-pane', 'lyrics')
        self.play()
        mini = self.enter()
        need = mini.header_height() + mini_player.SHORT_HEIGHT + mini_player.PANE_OPEN
        self.assertEqual(mini.get_default_size().height, need)
        self.assertEqual(mini.panes.grown, need - least)
        height, position = self.laid_out(mini)
        # The border an X11 window without a compositor counts in its size (CI's; none
        # on Wayland) comes off the pane.
        border = need - mini.view.get_height()
        self.assertIn(border, range(12))
        self.assertEqual((position, height - position),
                         (mini_player.SHORT_HEIGHT, mini_player.PANE_OPEN - border))
        self.assertIsNone(mini.pane_height())
        self.toggle(mini, 'lyrics')
        self.assertEqual(mini.get_default_size().height, least)
        self.assertEqual(mini.panes.grown, 0)
        self.assertEqual(self.app.settings.get_int('mini-player-pane-height'), 320)
        self.host.leave()
        self.assertIn(self.app.settings.get_int('mini-player-height'),
                      (least, least + border))

    def test_the_panes_fit_the_least_window(self):
        # Each view's least size against the pane's: no wider than the least window, no
        # taller than the least pane (its grip's strip counted).
        from gi.repository import Gtk

        self.play()
        mini = self.enter()
        for tab in ('lyrics', 'queue'):
            self.toggle(mini, tab)
            self.laid_out(mini)
            box = mini.view.pane_box
            self.assertLessEqual(box.measure(Gtk.Orientation.HORIZONTAL, -1)[0],
                                 mini_player.MIN_WIDTH, tab)
            slot = mini.view.pane_slot.measure(Gtk.Orientation.VERTICAL, -1)[0]
            grip = box.get_first_child().measure(Gtk.Orientation.VERTICAL, -1)[0]
            self.assertLessEqual(slot + grip, mini_player.PANE_MIN - 1, tab)

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
