# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""fullscreen.py: the full-screen player's layout and idle decisions, and its host with the
real view and the Now Playing sheet: entering and leaving, the window put back, the one
LyricsView moved in and back (active in one place at a time, centred again in the sheet), the
player staying from one song to the next and through a pause and leaving when nothing plays
any more, idle hiding, and nothing left running or fetched while it is not shown; the item
playing's menu by a right click, a long press or the menu keys, in the sheet and the player,
and Window._close_sheet(), which its Go to Album and Go to Artist run. The window's own
wiring (F11, the actions, the focus) is scripts/a11y_check.py's."""

import json
import unittest
from unittest import mock

from tests import ROOT
from tests.gtk import SCHEMA_ID, requires_gtk, wait_for
from tests.test_player import TRACK, FakeApp
from tests.test_transport import RatingEngine

from applemusic import fullscreen
from applemusic.fullscreen import layout_for, should_hide
from applemusic.player import Player

FIXTURES = ROOT / 'tests' / 'fixtures'
SECOND = dict(TRACK, id='i.demo0002', catalogId='1000000002', title='Pilot Light', index=3,
              artUrl='https://example.invalid/art2/256x256bb.jpg')


class LayoutTest(unittest.TestCase):
    def test_wide_with_lyrics_the_artwork_beside_them(self):
        layout = layout_for(1920, 1080, True)
        self.assertFalse(layout.portrait)
        self.assertTrue(layout.lyrics)
        self.assertLessEqual(layout.art_size, 1920 * fullscreen.ART_SHARE)
        self.assertGreaterEqual(layout.art_size, 480)

    def test_the_artwork_alone_is_larger_and_never_past_its_file(self):
        alone = layout_for(1280, 1000, False)
        beside = layout_for(1280, 1000, True)
        self.assertGreater(alone.art_size, beside.art_size)
        self.assertLessEqual(layout_for(3840, 2160, False).art_size, fullscreen.MAX_ART)

    def test_the_artwork_leaves_room_for_the_titles_and_the_controls(self):
        for width, height in ((1100, 760), (1280, 720), (1024, 600)):
            layout = layout_for(width, height, True)
            self.assertLessEqual(layout.art_size + fullscreen.BELOW_ART + fullscreen.TOP_MARGIN,
                                 height, (width, height))

    def test_narrow_or_portrait_is_one_column(self):
        for width, height in ((360, 640), (800, 1280), (700, 900)):
            layout = layout_for(width, height, True)
            self.assertTrue(layout.portrait, (width, height))
            self.assertEqual(layout.art_size, fullscreen.SMALL_ART)
        self.assertEqual(layout_for(360, 640, True).margin, fullscreen.MARGIN_NARROW)
        # Without lyrics, one column is the artwork as large as the width leaves.
        alone = layout_for(360, 640, False)
        self.assertTrue(alone.portrait)
        self.assertLessEqual(alone.art_size, 360 - 2 * alone.margin)
        self.assertGreater(alone.art_size, fullscreen.SMALL_ART)


class IdleTest(unittest.TestCase):
    def test_hides_only_when_idle_long_enough_and_nothing_is_in_use(self):
        idle = fullscreen.IDLE_SECONDS
        self.assertTrue(should_hide(True, False, False, False, idle))
        self.assertFalse(should_hide(True, False, False, False, idle - 0.1))
        self.assertFalse(should_hide(False, False, False, False, idle))  # paused
        self.assertFalse(should_hide(True, True, False, False, idle))    # a menu open
        self.assertFalse(should_hide(True, False, True, False, idle))    # pointer on them
        self.assertFalse(should_hide(True, False, False, True, idle))    # keyboard on them


class HostCase(unittest.TestCase):
    """The real Now Playing sheet in an Adw.BottomSheet and the host, in a presented
    window that has the window's win.fullscreen-player."""

    def setUp(self):
        from gi.repository import Adw, Gio, Gtk

        from applemusic.fullscreen import FullscreenHost
        from applemusic.widgets.now_playing import NowPlayingSheet

        self.app = FakeApp(RatingEngine())
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        self.player = Player(self.app)
        self.player.track_grace_ms = 0
        self.sheet = NowPlayingSheet()
        self.bottom_sheet = Adw.BottomSheet(sheet=self.sheet, content=Gtk.Label())
        self.stack = Gtk.Stack()
        self.stack.add_named(self.bottom_sheet, 'main')
        self.window = Gtk.Window(default_width=900, default_height=640, child=self.stack)
        self.addCleanup(self.window.destroy)
        self.sheet.set_player(self.player, self.app, self.bottom_sheet)
        self.host = FullscreenHost(self.window, self.stack, self.sheet, self.player, self.app)
        self.addCleanup(self.host.release)
        # win.fullscreen-player, as the window has it (the buttons, Escape).
        actions = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new('fullscreen-player', None)
        action.connect('activate', lambda *_: self.host.toggle())
        actions.add_action(action)
        self.window.insert_action_group('win', actions)
        self.window.present()
        self.assertTrue(wait_for(self.window.get_mapped))
        self.lyrics = self.sheet.lyrics_view
        self.active = []
        real = self.lyrics.set_active

        def set_active(active):
            self.active.append((active, self.place()))
            real(active)

        self.lyrics.set_active = set_active

    def place(self):
        parent = self.lyrics.get_parent()
        if parent is self.sheet.lyrics_slot:
            return 'sheet'
        if self.host.view is not None and parent is self.host.view.lyrics_slot:
            return 'fullscreen'
        return None

    def play(self, track=TRACK, lyrics='lyrics_syllable.json', state='playing', position=40):
        with open(FIXTURES / lyrics, encoding='utf-8') as file:
            answer = json.load(file)
        self.player.apply({'state': state, 'track': track, 'position': position,
                           'duration': 214, 'lyrics': answer})


@requires_gtk
class HostTest(HostCase):
    def test_nothing_without_an_item(self):
        self.host.enter()
        self.assertFalse(self.host.shown)
        self.assertIsNone(self.host.view)  # not even built

    def test_entering_and_leaving(self):
        self.play()
        size = self.window.get_default_size()
        self.host.enter()
        self.assertTrue(self.host.shown)
        self.assertIs(self.stack.get_visible_child(), self.host.view)
        self.assertEqual(self.place(), 'fullscreen')
        self.host.leave()
        self.assertFalse(self.host.shown)
        self.assertIs(self.stack.get_visible_child(), self.bottom_sheet)
        self.assertEqual(self.place(), 'sheet')
        self.assertTrue(wait_for(lambda: not self.window.is_fullscreen()))
        # The width the window had (with no window manager, as on CI's Xvfb, GTK grows the
        # height to what the content asks; a compositor keeps it: scripts/a11y_check.py).
        self.assertEqual(self.window.get_default_size()[0], size[0])
        self.assertFalse(self.window.is_maximized())
        # The view is kept for the next time.
        view = self.host.view
        self.host.enter()
        self.assertIs(self.host.view, view)

    def test_the_window_is_put_back_as_it_was(self):
        """Fullscreened as it enters, and back as it leaves; left full screen when it was
        full screen before (a window manager's own); a window manager taking it out of full
        screen leaves the player too."""
        calls = []
        state = {'fullscreen': False}
        with mock.patch.object(self.window, 'fullscreen', lambda: calls.append('on')), \
                mock.patch.object(self.window, 'unfullscreen', lambda: calls.append('off')), \
                mock.patch.object(self.window, 'is_fullscreen', lambda: state['fullscreen']):
            self.play()
            self.host.enter()
            state['fullscreen'] = True
            self.host.leave()
            self.assertEqual(calls, ['on', 'off'])
            calls.clear()
            self.host.enter()   # full screen already
            self.host.leave()
            self.assertEqual(calls, [])
            state['fullscreen'] = False
            self.host.enter()
            self.assertEqual(calls, ['on'])
            state['fullscreen'] = True
            self.host._on_fullscreened()
            self.assertTrue(self.host.shown)
            state['fullscreen'] = False   # the window manager's shortcut
            self.host._on_fullscreened()
            self.assertFalse(self.host.shown)

    def test_one_song_to_the_next_and_a_pause_keep_it(self):
        self.play()
        self.host.enter()
        self.play(track=SECOND, position=0)
        self.assertTrue(self.host.shown)
        self.player.apply({'state': 'paused'})
        self.assertTrue(self.host.shown)
        # MusicKit's way between queues: a null item, then the next one, within the grace.
        self.player.track_grace_ms = 50
        self.app.engine.emit('event', 'nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.app.engine.emit('event', 'nowPlayingItemDidChange', {'track': TRACK, 'index': 0})
        self.assertFalse(wait_for(lambda: not self.host.shown, timeout=0.15))
        self.assertEqual(self.player.track.id, TRACK['id'])

    def test_nothing_playing_any_more_leaves(self):
        self.play()
        self.host.enter()
        self.player.track_grace_ms = 20
        self.app.engine.emit('event', 'nowPlayingItemDidChange', {'track': None, 'index': -1})
        self.assertTrue(self.host.shown)   # the grace first
        self.assertTrue(wait_for(lambda: not self.host.shown))
        self.assertEqual(self.place(), 'sheet')
        self.play()
        self.host.enter()
        self.player.apply(None)   # the engine gone, a sign-out
        self.assertFalse(self.host.shown)

    def test_one_lyrics_view_active_in_one_place(self):
        """The sheet open on Lyrics, then full screen, then back: the view active only where
        it is shown, never in two places, and centred again as it comes back."""
        self.play()
        self.bottom_sheet.set_open(True)
        self.assertTrue(wait_for(lambda: self.lyrics._active))
        self.active.clear()
        self.host.enter()
        self.assertEqual(self.active, [(False, 'sheet'), (True, 'fullscreen')])
        self.active.clear()
        self.host.leave()
        self.assertEqual(self.active, [(False, 'fullscreen'), (True, 'sheet')])
        # Back in the sheet the current line is brought into view and centred.
        self.assertEqual(self.lyrics._centre_pending, self.lyrics._current)
        self.assertGreater(self.lyrics._current, 0)
        self.assertTrue(wait_for(lambda: self.lyrics._centre_pending is None))
        # The sheet closed: inactive, nothing stepping or sweeping.
        self.bottom_sheet.set_open(False)
        self.assertTrue(wait_for(lambda: not self.lyrics._active))
        self.active.clear()
        self.host.enter()
        self.host.leave()
        self.assertEqual(self.active, [(False, 'sheet'), (True, 'fullscreen'),
                                       (False, 'fullscreen'), (False, 'sheet')])
        self.assertIsNone(self.lyrics._sweep_tick)
        self.assertEqual(self.lyrics._next_change_source, 0)

    def test_the_sheet_does_not_take_the_view_back_while_covered(self):
        self.play()
        self.host.enter()
        self.active.clear()
        self.bottom_sheet.set_open(True)
        self.sheet.tab_stack.set_visible_child_name('queue')
        self.sheet.tab_stack.set_visible_child_name('lyrics')
        self.assertEqual(self.active, [])
        self.assertTrue(self.lyrics._active)
        self.assertFalse(self.sheet.queue_view._active)

    def test_left_it_does_nothing(self):
        """Once left: no idle timer, the lyrics inactive, and a song changing fetches no
        artwork and makes no field (the blur) until it shows again."""
        self.play()
        self.host.enter()
        view = self.host.view
        self.host.leave()
        self.assertEqual(view._idle_source, 0)
        self.assertFalse(self.lyrics._active)

        def fetches():
            return [name for name in self.app.spawned if name.startswith('FullscreenPlayer.')]

        self.assertEqual(fetches(), ['FullscreenPlayer._fetch_item'])
        reads = self.app.spawned.count('HeartControl._read')
        with mock.patch('applemusic.widgets.artwork.load_field') as load_field:
            self.play(track=SECOND)
            self.player.apply({'state': 'paused'})
            self.player.apply({'state': 'playing'})
            self.assertEqual(len(fetches()), 1)
            # The rating read is the sheet's heart's alone: the player's waits to be shown.
            self.assertEqual(self.app.spawned.count('HeartControl._read'), reads + 1)
            self.assertEqual(view._idle_source, 0)
            load_field.assert_not_called()
        self.host.enter()
        self.assertEqual(len(fetches()), 2)   # the new song's, as it shows

    def test_idle_hides_the_controls_and_the_cursor(self):
        self.play()
        with mock.patch.object(fullscreen, 'IDLE_SECONDS', 0.05):
            self.host.enter()
            view = self.host.view
            self.assertTrue(wait_for(lambda: view.idle))
            self.assertTrue(view.has_css_class('idle'))
            self.assertFalse(view.toolbar.get_reveal_top_bars())
            self.assertEqual(view.get_cursor().get_name(), 'none')
            view.wake()   # a key, a motion
            self.assertFalse(view.idle)
            self.assertTrue(view.toolbar.get_reveal_top_bars())
            self.assertIsNone(view.get_cursor())
            # Paused: the controls stay, and no timer runs.
            self.player.apply({'state': 'paused'})
            self.assertEqual(view._idle_source, 0)
            self.assertFalse(wait_for(lambda: view.idle, timeout=0.15))
            # A menu open keeps them too.
            self.player.apply({'state': 'playing'})
            with mock.patch.object(view, '_popover_open', lambda: True):
                self.assertFalse(wait_for(lambda: view.idle, timeout=0.15))
            self.assertTrue(wait_for(lambda: view.idle))
            self.host.leave()
            self.assertFalse(view.idle)
            self.assertEqual(view._idle_source, 0)

    def test_the_lyrics_column_follows_the_song(self):
        self.play()
        self.host.enter()
        view = self.host.view
        self.assertTrue(wait_for(lambda: view.layout is not None and view.layout.lyrics))
        self.assertTrue(view.lyrics_slot.get_visible())
        self.player.apply({'lyrics': None})
        self.assertTrue(wait_for(lambda: not view.layout.lyrics))
        self.assertFalse(view.lyrics_slot.get_visible())



def menu_actions(menu):
    """The actions of a Gio.MenuModel's items, its sections' and submenus' too."""
    found = []
    for position in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(position, 'action', None)
        if action is not None:
            found.append(action.unpack())
        for link in ('section', 'submenu'):
            inner = menu.get_item_link(position, link)
            if inner is not None:
                found.extend(menu_actions(inner))
    return found


class ItemActions:
    """The window's item actions as the menus ask them: the menus asked for, recorded."""

    def __init__(self):
        self.asked = []

    def menu_for(self, obj, queued=False, queue_entry=None, queue_moves=()):
        from applemusic.item_menu import build_menu

        self.asked.append((obj.id, queued))
        return build_menu(obj, queued=queued)


@requires_gtk
class ItemMenuTest(HostCase):
    """The item playing's menu by a right click or a long press over the artwork, the
    titles and the lyrics, and by the menu keys, in the sheet and the full-screen player:
    the menu More Options shows (queued: no Play), and Go to Album or Go to Artist from it
    uncovering the pages (issue 588)."""

    def setUp(self):
        super().setUp()
        self.window.item_actions = self.actions = ItemActions()

    def gesture(self, area, kind):
        from gi.repository import Gdk, Gtk

        model = area.observe_controllers()
        return next(controller for controller in
                    (model.get_item(position) for position in range(model.get_n_items()))
                    if isinstance(controller, kind) and (
                        kind is not Gtk.GestureClick
                        or controller.get_button() == Gdk.BUTTON_SECONDARY))

    def right_click(self, area, x=None, y=None):
        """A right click at (x, y) in area (its middle): the popover it opened, or None."""
        from gi.repository import Gtk

        x = area.get_width() / 2 if x is None else x
        y = area.get_height() / 2 if y is None else y
        self.gesture(area, Gtk.GestureClick).emit('pressed', 1, x, y)
        return self.popover(area)

    def popover(self, widget):
        from gi.repository import Gtk

        child = widget.get_first_child()
        while child is not None and not (isinstance(child, Gtk.PopoverMenu)
                                         and child.get_visible()):
            child = child.get_next_sibling()
        popover = child
        if popover is not None:
            self.addCleanup(popover.popdown)
        return popover

    def open_sheet(self):
        self.play()
        self.bottom_sheet.set_open(True)
        self.assertTrue(wait_for(lambda: self.sheet.shown_tab == 'lyrics'
                                 and self.sheet.lyrics_slot.get_height() > 0
                                 and self.sheet.cover.get_height() > 0))

    def test_a_right_click_over_the_artwork_titles_and_lyrics(self):
        self.open_sheet()
        for area in (self.sheet.item_box, self.sheet.lyrics_slot):
            with self.subTest(area=area.get_name()):
                popover = self.right_click(area)
                self.assertIsNotNone(popover)
                self.assertTrue(wait_for(popover.get_mapped))
                popover.popdown()
        # The menu More Options shows: the item playing's, queued (no Play).
        self.assertEqual(self.actions.asked, [(TRACK['id'], True)] * 2)
        actions = menu_actions(popover.get_menu_model())
        self.assertIn('win.item-go-to-album', actions)
        self.assertIn('win.item-go-to-artist', actions)
        self.assertNotIn('win.item-play', actions)

    def test_nothing_over_a_control_or_with_nothing_playing(self):
        from gi.repository import Gtk

        from applemusic.widgets import context_menu

        box = Gtk.Box()
        button = Gtk.Button(child=Gtk.Label(label='Play'))
        text = Gtk.Label(label='Words', selectable=True)
        plain = Gtk.Label(label='Title')
        for widget in (button, text, plain):
            box.append(widget)
        self.assertTrue(context_menu.keeps_own_press(box, button.get_child()))
        self.assertTrue(context_menu.keeps_own_press(box, text))
        self.assertFalse(context_menu.keeps_own_press(box, plain))
        self.assertFalse(context_menu.keeps_own_press(box, box))
        # Nothing playing: no menu, and the press is not claimed.
        self.bottom_sheet.set_open(True)
        self.assertTrue(wait_for(lambda: self.sheet.cover.get_height() > 0))
        with mock.patch.object(Gtk.Gesture, 'set_state') as set_state:
            self.assertIsNone(self.right_click(self.sheet.item_box))
        set_state.assert_not_called()
        self.assertEqual(self.actions.asked, [])

    def test_a_long_press_on_a_lyric_line_opens_the_menu_and_takes_the_touch(self):
        from gi.repository import Gdk, Graphene, Gtk

        self.open_sheet()
        area = self.sheet.lyrics_slot
        self.assertTrue(wait_for(lambda: self.lyrics.list_view.get_first_child() is not None))
        row = self.lyrics.list_view.get_first_child()
        point = Graphene.Point()
        point.x, point.y = row.get_width() / 2, row.get_height() / 2
        ok, point = row.compute_point(area, point)
        self.assertTrue(ok)
        x, y = point.x, point.y
        press = self.gesture(area, Gtk.GestureLongPress)
        self.assertTrue(press.get_touch_only())
        seeks = []
        self.lyrics.list_view.connect('activate', lambda *_: seeks.append(True))
        with mock.patch.object(Gtk.Gesture, 'set_state') as set_state:
            press.emit('pressed', x, y)
        # Claimed, the touch is the menu's: GTK cancels the row's click, which would seek.
        set_state.assert_called_once_with(Gtk.EventSequenceState.CLAIMED)
        self.assertIsNotNone(self.popover(area))
        self.assertEqual(seeks, [])
        # Only the secondary button opens it: a click (the primary) is the row's, a seek.
        self.assertEqual(self.gesture(area, Gtk.GestureClick).get_button(),
                         Gdk.BUTTON_SECONDARY)

    def test_the_menu_keys_anywhere_in_the_sheet(self):
        from gi.repository import Gtk

        self.open_sheet()
        self.assertTrue(self.sheet.more_button.grab_focus())   # anywhere: the header bar's
        focus = self.window.get_focus()   # the menu button's own button
        model = self.sheet.observe_controllers()
        shortcut = next(
            controller.get_item(0) for controller in
            (model.get_item(position) for position in range(model.get_n_items()))
            if isinstance(controller, Gtk.ShortcutController))
        self.assertEqual(shortcut.get_trigger().to_string(), 'Menu|<Shift>F10')
        self.assertTrue(shortcut.get_action().activate(Gtk.ShortcutActionFlags(0),
                                                       self.sheet, None))
        self.assertIsNotNone(self.popover(focus))
        self.assertEqual(self.actions.asked, [(TRACK['id'], True)])

    def test_in_the_full_screen_player_the_controls_stay_while_it_is_open(self):
        self.play()
        self.host.enter()
        view = self.host.view
        self.assertTrue(wait_for(lambda: view.cover.get_height() > 0))
        popover = self.right_click(view.item_box)
        self.assertIsNotNone(popover)
        self.assertTrue(wait_for(popover.get_mapped))
        self.assertEqual(self.actions.asked, [(TRACK['id'], True)])
        self.assertTrue(view._popover_open())   # fullscreen.should_hide() then says no
        popover.popdown()
        self.assertTrue(wait_for(lambda: not view._popover_open()))

    def test_go_to_album_or_artist_uncovers_the_pages(self):
        """What the menu's Go to Album and Go to Artist run (ItemActions.go_to, then
        Window.open_item or open_artist_page) uncovers the pages through
        Window._close_sheet(): from the full-screen player, full screen is left first, the
        window put back, then the sheet closed."""
        import types

        from applemusic.window import Window

        self.play()
        self.bottom_sheet.set_open(True)
        self.host.enter()
        self.assertTrue(self.host.shown)
        order = []
        self.host.connect_changed(lambda: order.append(('left', self.host.shown)))
        self.bottom_sheet.connect('notify::open', lambda *_: order.append(
            ('sheet', self.bottom_sheet.get_open(), self.host.shown)))
        window = types.SimpleNamespace(fullscreen_host=self.host,
                                       bottom_sheet=self.bottom_sheet)
        Window._close_sheet(window)
        self.assertFalse(self.host.shown)
        self.assertFalse(self.bottom_sheet.get_open())
        self.assertEqual(order, [('left', False), ('sheet', False, False)])
        self.assertTrue(wait_for(lambda: not self.window.is_fullscreen()))
        # From the sheet alone, it closes.
        self.bottom_sheet.set_open(True)
        Window._close_sheet(window)
        self.assertFalse(self.bottom_sheet.get_open())


if __name__ == '__main__':
    unittest.main()
