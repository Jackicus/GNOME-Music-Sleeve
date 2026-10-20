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
station) and Next (app.previous, app.play-pause, app.next), and Return to Main Window
(app.mini-player) in a flat header bar; under it all the artwork's tint
(widgets/backdrop.py, as the sheet's). No lyrics and no Up Next: nothing in it steps or
redraws while a song plays but the seek row, once a second.

Its layout follows its size (mini_player.layout_for(), applied as the view is allocated: it
measures and allocates its child itself, so its Adw.Bin layout manager is dropped): the
cover as large as the window lets it be over the titles, or, in a low window, small beside
them.

For the keyboard: the focus starts on Play; the playback keys (Space, Ctrl+Left,
Ctrl+Right: shortcuts.PLAYBACK) are the window's own as in the main window
(keyboard.playback_action), and the app's accelerators work here too (Ctrl+Shift+M back to
the main window, Ctrl+W closes it, which is the same, Ctrl+Q quits). For assistive
technology: the window is named "Mini Player", each new item is announced ("Now playing …",
transport.announcement()) through it, the seek slider reads "1:05 of 3:40", and the cover is
decorative.
"""

from gettext import gettext as _

from gi.repository import Adw, Gtk

from .. import keyboard, mini_player, shortcuts
from ..backend import config
from ..remote import fetch_remote
from .backdrop import ArtworkBackdrop  # noqa: F401  registers it for the template
from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .transport import (Follower, PlayButton, RemoteCover, SeekControl, TrackTitles,
                        announcement)
from .util import connect_weak, has_ancestor

# The window's smallest size: the short layout's controls, and a title's room.
MIN_WIDTH = 280
MIN_HEIGHT = 240


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/mini_player.ui')
class MiniPlayerView(Adw.Bin):
    """The mini player's content. See the module."""

    __gtype_name__ = 'AppleMusicMiniPlayerView'

    overlay = Gtk.Template.Child()
    backdrop = Gtk.Template.Child()
    toolbar = Gtk.Template.Child()
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
                                   sensitive=(self.seek_box,), tooltips=True)
        self._seek = SeekControl(self.seek_scale, self.seek_adjustment, self.elapsed_label,
                                 self.remaining_label, self.live_label)
        self._art = RemoteCover(self.cover)
        accel = shortcuts.ACCELS['app.mini-player'][0]
        ok, key, mods = Gtk.accelerator_parse(accel)
        if ok:
            # Translators: a button's tooltip with its shortcut: {tooltip} is what it does
            # ("Lyrics"), {keys} its key ("Shift+Ctrl+L").
            self.main_window_button.set_tooltip_text(_('{tooltip} ({keys})').format(
                tooltip=self.main_window_button.get_tooltip_text(),
                keys=Gtk.accelerator_get_label(key, mods)))

    def set_player(self, player, app):
        """Follow `player`; `app` spawns the commands and the fetches."""
        self._player = player
        self._app = app
        self._play.attach(player)
        self._titles.attach(player)   # before the announcement, which reads the title
        self._seek.attach(player, app)
        self._art.attach(player, app)
        self._own.follow(player, 'notify::track', lambda *_: self._on_track())
        self._on_track()

    def detach(self):
        """Let go of the Player: the window is going."""
        for piece in (self._play, self._titles, self._seek, self._art, self._own):
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
        """The child's natural size, but no minimum: the layout for the size given
        (do_size_allocate) makes the content fit, down to the window's own minimum, and the
        minimum measured here would be the last layout's."""
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1
        _minimum, natural, _baseline, _natural_baseline = child.measure(orientation, for_size)
        return 0, natural, -1, -1

    def do_size_allocate(self, width, height, baseline):
        header = self.toolbar.get_top_bar_height()
        layout = mini_player.layout_for(width, height - header)
        if layout != self.shown_layout:
            self.apply_layout(layout)
        child = self.get_child()
        if child is not None:
            child.allocate(width, height, baseline, None)

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
        self.cover.remove_css_class('small' if not short else 'large')
        self.cover.add_css_class('small' if short else 'large')
        self.cover.set_property('size', layout.art_size)


class MiniPlayer(Adw.ApplicationWindow):
    """The mini player's window. See the module. `view` is its content."""

    __gtype_name__ = 'AppleMusicMiniPlayer'

    def __init__(self, **kwargs):
        super().__init__(title=_('Mini Player'), width_request=MIN_WIDTH,
                         height_request=MIN_HEIGHT, **kwargs)
        self.view = MiniPlayerView()
        self.set_content(self.view)
        self._app = None
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        connect_weak(keys, 'key-pressed', self._on_key_pressed)
        self.add_controller(keys)

    def set_player(self, player, app):
        """Follow `player` (the app's); `app` runs the commands, and its mini player host
        takes the window's close."""
        self._app = app
        self.view.set_player(player, app)

    def do_map(self):
        Adw.ApplicationWindow.do_map(self)
        if self.get_focus() is None or self.get_focus() is self.view.main_window_button:
            self.view.focus_controls()

    def add_toast(self, toast):
        """A toast for the user (Application.toast(): this is the window they see)."""
        self.view.add_toast(toast)

    def release(self):
        """The window goes: the view lets go of the Player, then the window is destroyed."""
        self.view.detach()
        self._app = None
        self.destroy()

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
        to the focus widget where they are its own, and to a dialog open over the window."""
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
        if name is None:
            return False
        action = app.lookup_action(name)
        if action is not None and action.get_enabled():
            app.activate_action(name)
        return True

