# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicMiniPlayer: the mini player's window, and AppleMusicMiniPlayerView, its content,
following the Player.

Made by mini_player.MiniPlayerHost as the mini player shows and destroyed as it goes
(release(): its pieces let go of the Player first, so a closed mini player is freed and
follows nothing). What it shows is the pieces of widgets/transport.py, as the player bar,
the Now Playing sheet and the full-screen player have them: the artwork (RemoteCover), the
title and the artist (TrackTitles, with their full text as tooltips), the seek row
(SeekControl: LIVE in its place for a live radio station), Previous, Play (Stop for a live
station) and Next (app.previous, app.play-pause, app.next) with Favourite (HeartControl,
lazy: it shows the answers to the bar's reads of each item's rating, and reads only as it
is made) and Shuffle before them and Repeat (ModeControl) and Volume (VolumeControl, a
button with its slider in a popover at every size) after, one row of seven at every size
(mini_player.MIN_WIDTH is the width it takes); and Return to Main Window (app.mini-player)
in a flat header bar; under it all the artwork's tint (widgets/backdrop.py, as the sheet's).
With no pane open nothing in it steps or redraws while a song plays but the seek row, once
a second.

The header bar's end has two toggles, Lyrics and Up Next: the window's own win.show-lyrics
and win.show-queue, as the main window's are named (stateful: pressed while its pane shows;
enabled as now_playing.can_show_tab() says, Lyrics off for a song without lyrics), on the
same keys, Ctrl+Shift+L and Ctrl+Shift+U (keyboard.tab_action). Each opens the pane under
the controls, one at a time (mini_player.Panes). The controls (`body`) and the pane
(`pane_slot`) are the two children of a vertical Gtk.Paned, `paned`: its handle is the
divider between them, dragged with the pointer or moved with the keyboard (F8, then the
arrows), and neither side goes under its least height (mini_player.SHORT_HEIGHT, PANE_MIN).
A pane opens inside the window, taking its height from the bottom (mini_player.divide());
only a window with no room for it grows. The pane holds the Now Playing sheet's own
LyricsView or QueueView, lent while it shows: never a second one, which would follow the
Player for good. Up Next's edits and its entries' menus are the main window's item actions,
which the mini player's window does not have: the pane slot carries the main window as its
`win` action group (Alt+Up, Delete, a drop and the menus' items find win.item-* there), and
the window answers `borrowed_item_actions` for context_menu.popup().

The controls' layout follows the room they have (mini_player.layout_for(), applied as
`body`, an AppleMusicMiniPlayerBody, is allocated: it measures and allocates its child
itself): the cover as large as that lets it be over the titles, or, where it is low, small
beside them. So it follows the window with no pane open, and the divider with one.

For the keyboard: the focus starts on Play; the playback keys (Space, Ctrl+Left,
Ctrl+Right: shortcuts.PLAYBACK) are the window's own as in the main window
(keyboard.playback_action), and so are the volume's (Ctrl+Up, Ctrl+Down:
keyboard.volume_step, the level announced, the volume button shown or not); the app's
accelerators work here too (Ctrl+Shift+M back to the main window, Ctrl+W closes it, which is
the same, Ctrl+Q quits). For assistive technology: the window is named "Mini Player", each
new item is announced ("Now playing …", transport.announcement()) through it, the seek
slider reads "1:05 of 3:40", the volume "70%", and the cover is decorative.
"""

from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import keyboard, mini_player, shortcuts
from ..backend import config
from ..remote import fetch_remote
from .backdrop import ArtworkBackdrop  # noqa: F401  registers it for the template
from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .now_playing import TAB_ACTIONS, can_show_tab
from .transport import (Follower, HeartControl, ModeControl, PlayButton, RemoteCover,
                        SeekControl, TrackTitles, VolumeControl, announcement, volume_text)
from .util import connect_weak, has_ancestor



class MiniPlayerBody(Adw.Bin):
    """The mini player's controls, laid out for the size they are given: no less high than
    the short layout, whatever the layout shown measures (the view's arrange() picks the
    one for the allocation, so the last one's minimum is not this one's)."""

    __gtype_name__ = 'AppleMusicMiniPlayerBody'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_layout_manager(None)  # do_measure and do_size_allocate below

    def do_measure(self, orientation, for_size):
        child = self.get_child()
        natural = child.measure(orientation, for_size)[1] if child is not None else 0
        if orientation == Gtk.Orientation.VERTICAL:
            least = mini_player.SHORT_HEIGHT
            return least, max(natural, least), -1, -1
        return 0, natural, -1, -1

    def do_size_allocate(self, width, height, baseline):
        view = self.get_ancestor(MiniPlayerView)
        if view is not None:
            view.arrange(width, height)
        child = self.get_child()
        if child is not None:
            child.allocate(width, height, baseline, None)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/mini_player.ui')
class MiniPlayerView(Adw.Bin):
    """The mini player's content. See the module."""

    __gtype_name__ = 'AppleMusicMiniPlayerView'

    overlay = Gtk.Template.Child()
    backdrop = Gtk.Template.Child()
    toolbar = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    lyrics_button = Gtk.Template.Child()
    queue_button = Gtk.Template.Child()
    paned = Gtk.Template.Child()
    body = Gtk.Template.Child()
    pane_box = Gtk.Template.Child()
    pane_slot = Gtk.Template.Child()
    main_window_button = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    content_box = Gtk.Template.Child()
    item_box = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    titles_box = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    seek_box = Gtk.Template.Child()
    seek_scale = Gtk.Template.Child()
    seek_adjustment = Gtk.Template.Child()
    elapsed_label = Gtk.Template.Child()
    remaining_label = Gtk.Template.Child()
    live_label = Gtk.Template.Child()
    previous_button = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    next_button = Gtk.Template.Child()
    transport_box = Gtk.Template.Child()
    heart_button = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    repeat_button = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    volume_adjustment = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_layout_manager(None)  # do_measure and do_size_allocate below
        self.overlay.set_measure_overlay(self.toolbar, True)
        self.shown_layout = None       # the mini_player.Layout applied
        self._player = None
        self._app = None
        self._announced = None         # the id of the item last announced
        self._backdrop_url = None      # the artwork URL whose tint is shown or being made
        self._backdrop_task = None
        self._own = Follower()         # the view's own handlers on the Player
        self._play = PlayButton(self.play_button)
        self._titles = TrackTitles(self.title_label, self.subtitle_label,
                                   sensitive=(self.seek_box, self.volume_button),
                                   tooltips=True)
        self._seek = SeekControl(self.seek_scale, self.seek_adjustment, self.elapsed_label,
                                 self.remaining_label, self.live_label)
        self._art = RemoteCover(self.cover)
        self._modes = ModeControl(self.shuffle_button, self.repeat_button)
        # Lazy: the bar's heart, which lives as long as the main window, reads each item's
        # rating, and the engine's answer reaches this one too.
        self._heart = HeartControl(self.heart_button, lazy=True)
        self._volume = VolumeControl(self.volume_button, self.volume_adjustment)
        self.pane = ''                 # the pane shown: '', 'lyrics' or 'queue'
        self._pane_wish = None         # the height asked for it, until it is laid out
        self._pane_given = None        # the height it was laid out with as it opened
        # The pane's least height, the paned's own 1 px of handle counted.
        self.pane_box.set_size_request(-1, mini_player.PANE_MIN - 1)
        tabs = shortcuts.NOW_PLAYING_TABS
        for button, accel in ((self.main_window_button, shortcuts.ACCELS['app.mini-player'][0]),
                              (self.lyrics_button, tabs['show-lyrics'][0]),
                              (self.queue_button, tabs['show-queue'][0])):
            ok, key, mods = Gtk.accelerator_parse(accel)
            if ok:
                # Translators: a button's tooltip with its shortcut: {tooltip} is what it
                # does ("Lyrics"), {keys} its key ("Shift+Ctrl+L").
                button.set_tooltip_text(_('{tooltip} ({keys})').format(
                    tooltip=button.get_tooltip_text(),
                    keys=Gtk.accelerator_get_label(key, mods)))

    def set_player(self, player, app):
        """Follow `player`; `app` spawns the commands and the fetches."""
        self._player = player
        self._app = app
        self._play.attach(player)
        self._titles.attach(player)   # before the announcement, which reads the title
        self._seek.attach(player, app)
        self._art.attach(player, app)
        self._modes.attach(player, app)
        self._heart.attach(player, app)
        self._heart.catch_up()        # the item playing as it is made: read once
        self._volume.attach(player, app)
        self._own.follow(player, 'notify::track', lambda *_: self._on_track())
        self._on_track()

    def detach(self):
        """Let go of the Player: the window is going."""
        for piece in (self._play, self._titles, self._seek, self._art, self._modes,
                      self._heart, self._volume, self._own):
            piece.detach()
        if self._backdrop_task is not None and not self._backdrop_task.done():
            self._backdrop_task.cancel()
        self._backdrop_task = None
        self._player = None

    def add_toast(self, toast):
        self.toast_overlay.add_toast(toast)

    def focus_controls(self):
        """The focus on Play (on Return to Main Window with nothing to play)."""
        if not self.play_button.grab_focus():
            self.main_window_button.grab_focus()

    def step_volume(self, step):
        """A volume key (the window's Ctrl+Up or Ctrl+Down): the volume a step up (1) or down
        (-1), sent as the volume button's slider sends it. The new level, 0 to 1."""
        return self._volume.step(step)

    # -- the item ---------------------------------------------------------------------------

    def _on_track(self):
        """A new item: announced once (the same song after a stop is announced again), and
        its artwork's tint made."""
        track = self._player.track if self._player is not None else None
        if track is None:
            self._announced = None
        elif track.id != self._announced:
            self._announced = track.id
            root = self.get_root()
            if root is not None and root.get_visible():
                root.announce(announcement(track, self.title_label.get_label()),
                              Gtk.AccessibleAnnouncementPriority.MEDIUM)
        self._update_backdrop(track)

    def _update_backdrop(self, track):
        url = track.artwork_url if track is not None else None
        if url == self._backdrop_url:
            return
        self._backdrop_url = url
        if self._backdrop_task is not None:
            self._backdrop_task.cancel()
            self._backdrop_task = None
        if not url or self._app is None:
            self.backdrop.show_field(None)
            return
        self._backdrop_task = self._app.spawn(self._fetch_backdrop(url))

    async def _fetch_backdrop(self, url):
        """The cover file (the one the cover shows: one download for both), then its
        field."""
        path = await fetch_remote(url, config.COVER_SIZE)
        if url == self._backdrop_url:
            await self.backdrop.show_artwork(path)

    # -- layout -----------------------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        """The child's size, and the mini player's least: mini_player.MIN_WIDTH across,
        the width the row of buttons is made for, whatever the child measures (a pane's
        view may ask for less or more); MIN_HEIGHT down, or what the header bar, the short
        layout and a pane open need. The least is the content's, so the window's is this
        and whatever border its decoration adds (X11 without a compositor: 5 px a side)."""
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1
        minimum, natural, _baseline, _natural_baseline = child.measure(orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum = mini_player.MIN_WIDTH
        else:
            minimum = max(minimum, mini_player.MIN_HEIGHT)
        return minimum, max(natural, minimum), -1, -1

    def do_size_allocate(self, width, height, baseline):
        if self._pane_wish is not None:
            # A pane just shown: the divider where the pane has the height wished for it,
            # in the height the window has now (grown, when it had to).
            controls, _pane = mini_player.divide(height - self.header_height(),
                                                 self._pane_wish)
            self.paned.set_position(controls)
        child = self.get_child()
        if child is not None:
            child.allocate(width, height, baseline, None)
        if self._pane_wish is not None:
            self._pane_wish = None
            self._pane_given = self._pane_now()

    def header_height(self):
        """The header bar's height as it measures (the toolbar view's top-bar-height is
        the last allocation's, 0 before the first)."""
        return self.header_bar.measure(Gtk.Orientation.VERTICAL, -1)[0]

    def arrange(self, width, height):
        """The controls given `width` x `height` px (the body's allocation): the layout
        for it."""
        layout = mini_player.layout_for(width, height)
        if layout != self.shown_layout:
            self.apply_layout(layout)

    def show_pane(self, name, widget, height):
        """The pane `name` ('lyrics' or 'queue') showing `widget` (the sheet's view, lent)
        under the divider, `height` px of the window wished for it (mini_player.divide()
        says what it gets, as the view is next allocated)."""
        self.pane = name
        self._pane_wish = height
        self._pane_given = None
        self.pane_slot.set_child(widget)
        self.pane_box.set_visible(True)
        self.queue_resize()

    def hide_pane(self):
        """The pane closed, its widget out of it (the caller gives it back)."""
        self.pane = ''
        self._pane_wish = None
        self._pane_given = None
        self.pane_slot.set_child(None)
        self.pane_box.set_visible(False)
        self.queue_resize()

    def _pane_now(self):
        return self.paned.get_height() - self.paned.get_position()

    def pane_height(self):
        """The pane's height, the divider counted, when the user has changed it since it
        opened (the divider dragged, the window resized); else None."""
        if not self.pane or self._pane_wish is not None:
            return None
        height = self._pane_now()
        return height if height > 0 and height != self._pane_given else None

    def apply_layout(self, layout):
        """The cover and the titles as `layout` (a mini_player.Layout) has them."""
        self.shown_layout = layout
        short = layout.short
        self.item_box.set_orientation(Gtk.Orientation.HORIZONTAL if short
                                      else Gtk.Orientation.VERTICAL)
        self.titles_box.set_hexpand(short)
        for label in (self.title_label, self.subtitle_label):
            label.set_xalign(0 if short else 0.5)
            label.set_justify(Gtk.Justification.LEFT if short else Gtk.Justification.CENTER)
        # Rounded by its size: `large` over the titles, `small` at its least beside them.
        for name, wanted in (('large', not short),
                             ('small', layout.art_size <= mini_player.SMALL_ART)):
            if wanted:
                self.cover.add_css_class(name)
            else:
                self.cover.remove_css_class(name)
        self.cover.set_property('size', layout.art_size)


class MiniPlayer(Adw.ApplicationWindow):
    """The mini player's window. See the module. `view` is its content."""

    __gtype_name__ = 'AppleMusicMiniPlayer'

    def __init__(self, **kwargs):
        # Its least size is its view's (MiniPlayerView.do_measure).
        super().__init__(title=_('Mini Player'), **kwargs)
        self.view = MiniPlayerView()
        self.set_content(self.view)
        self._app = None
        self._player = None
        self._follows = Follower()     # the window's own handlers on the Player
        self.panes = None              # mini_player.Panes, once there is a lender
        self.borrowed_item_actions = None   # the main window's, for the panes' menus
        self.pane_actions = {}
        for tab, name in TAB_ACTIONS.items():
            action = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(False))
            action.set_enabled(False)
            connect_weak(action, 'activate', self._on_pane_action, tab)
            self.add_action(action)
            self.pane_actions[tab] = action
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        connect_weak(keys, 'key-pressed', self._on_key_pressed)
        self.add_controller(keys)

    def set_player(self, player, app):
        """Follow `player` (the app's); `app` runs the commands, and its mini player host
        takes the window's close."""
        self._app = app
        self._player = player
        self.view.set_player(player, app)
        for name in ('track', 'lyrics', 'lyrics-loading'):
            self._follows.follow(player, 'notify::' + name, lambda *_: self.update_panes())

    # -- the panes --------------------------------------------------------------------------

    def can_show(self, pane):
        """Whether there is something to show in `pane` ('lyrics' or 'queue') now, as the
        sheet's tabs have it (now_playing.can_show_tab())."""
        player = self._player
        return player is not None and can_show_tab(pane, '', player.track, player.lyrics,
                                                   player.lyrics_loading)

    def set_lender(self, sheet, main):
        """The Now Playing sheet that lends the panes their views (None: no panes) and its
        window, whose item actions Up Next's edits and menus run."""
        settings = self._app.settings if self._app is not None else None
        if sheet is None or settings is None:
            return
        self.panes = mini_player.Panes(self, sheet, settings)
        self.borrowed_item_actions = getattr(main, 'item_actions', None)
        if isinstance(main, Gio.ActionGroup):
            self.view.pane_slot.insert_action_group('win', main)
        self.update_panes()

    def fixed_size(self):
        """Whether the window cannot grow for a pane: maximized, full screen or tiled."""
        if self.is_maximized() or self.is_fullscreen():
            return True
        surface = self.get_surface()
        state = surface.get_state() if surface is not None else 0
        return bool(state & Gdk.ToplevelState.TILED)

    def header_height(self):
        """mini_player.Panes': the header bar's height."""
        return self.view.header_height()

    def pane_height(self):
        """mini_player.Panes': the pane's height when the user changed it, else None."""
        return self.view.pane_height()

    def show_pane(self, name, widget, height):
        """mini_player.Panes': the pane in the view, `height` px wished for it."""
        self.view.show_pane(name, widget, height)
        self.update_panes()

    def hide_pane(self):
        """mini_player.Panes': the pane out of the view; the focus that was in it goes to
        its toggle."""
        view = self.view
        if not view.pane:
            return
        focus = self.get_focus()
        button = view.lyrics_button if view.pane == 'lyrics' else view.queue_button
        held = focus is not None and (focus is view.pane_slot
                                      or focus.is_ancestor(view.pane_slot))
        view.hide_pane()
        if held:
            button.grab_focus()
        self.update_panes()

    def update_panes(self):
        """The toggles' state (pressed while its pane shows) and whether they can be used:
        a pane with something to show, or the one shown, to close it."""
        shown = self.view.pane
        player = self._player
        for tab, action in self.pane_actions.items():
            state = shown == tab
            if action.get_state().get_boolean() != state:
                action.set_state(GLib.Variant.new_boolean(state))
            action.set_enabled(self.panes is not None and player is not None and can_show_tab(
                tab, shown, player.track, player.lyrics, player.lyrics_loading))

    def _on_pane_action(self, _action, _parameter, tab):
        if self.panes is not None:
            self.panes.toggle(tab)
            self.update_panes()

    def do_map(self):
        Adw.ApplicationWindow.do_map(self)
        if self.get_focus() is None or self.get_focus() is self.view.main_window_button:
            self.view.focus_controls()

    def add_toast(self, toast):
        """A toast for the user (Application.toast(): this is the window they see)."""
        self.view.add_toast(toast)

    def release(self):
        """The window goes: its dialogs are closed, a view still lent to a pane is given
        back to the sheet (the host has done it already: never left in a window being
        destroyed), the view and the window let go of the Player and of the main window's
        actions, then the window is destroyed."""
        self._close_dialogs()
        if self.panes is not None:
            self.panes.give_back()
            self.panes = None
        self._follows.detach()
        self.view.pane_slot.insert_action_group('win', None)
        self.borrowed_item_actions = None
        self.view.detach()
        self._app = None
        self._player = None
        self.destroy()

    def _close_dialogs(self):
        """Close the dialogs open over the window (Preferences, the sign-in, opened by their
        keys here), and those shown as windows of their own: the app follows their `closed`
        (the one Preferences it has, where its toasts go), which a dialog destroyed with
        its window never emits."""
        closed = None
        while True:
            dialog = self.get_visible_dialog()
            if dialog is None or dialog is closed:
                break
            closed = dialog
            dialog.force_close()
        for toplevel in Gtk.Window.list_toplevels():
            if toplevel is not self and toplevel.get_transient_for() is self:
                toplevel.close()

    def do_close_request(self):
        # Closing is leaving the mini player: the host brings the main window back and
        # destroys this one (mini_player.py).
        host = getattr(self._app, 'mini_player', None)
        if host is not None and host.window is self:
            host.leave()
            return True
        return False

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        """The playback keys, as the main window has them (keyboard.playback_action): left
        to the focus widget where they are its own, and to a dialog open over the window;
        then the volume's (keyboard.volume_step), while something plays."""
        app = self.get_application()
        if app is None:
            return False
        mods = state & Gtk.accelerator_get_default_mod_mask()
        focus = self.get_focus()

        def enabled(name):
            # Next and Previous are the window's keys while an item plays, as Play/Pause.
            action = app.lookup_action('play-pause' if name in ('next', 'previous') else name)
            return action is not None and action.get_enabled()

        name = keyboard.playback_action(keyval, mods, type(focus),
                                        self.get_visible_dialog() is not None,
                                        has_ancestor(focus, Gtk.Popover), enabled)
        if name is not None:
            action = app.lookup_action(name)
            if action is not None and action.get_enabled():
                app.activate_action(name)
            return True
        name = keyboard.tab_action(keyval, mods, type(focus),
                                   self.get_visible_dialog() is not None,
                                   has_ancestor(focus, Gtk.Popover),
                                   lambda name: self.lookup_action(name).get_enabled())
        if name is not None:
            self.activate_action('win.' + name, None)
            return True
        step = keyboard.volume_step(keyval, mods, type(focus),
                                    self.get_visible_dialog() is not None,
                                    has_ancestor(focus, Gtk.Popover))
        if step is not None and app.player.track is not None:
            self.announce(volume_text(self.view.step_volume(step)),
                          Gtk.AccessibleAnnouncementPriority.MEDIUM)
            return True
        return False

