# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicFullscreenPlayer: the item playing, full screen, following the Player.

Built once, on the first enter, by fullscreen.FullscreenHost, which shows it as the window's
stack's second page and moves the Now Playing sheet's LyricsView into its `lyrics_slot`
(take_lyrics()/give_lyrics()) and out; set_shown() says when it is the page shown, and only
then does it do anything: the LyricsView active, the artwork and the backdrop's field fetched
for the item, the idle timer. A song changing while it is hidden costs nothing; the item is
caught up with as it shows again.

What it shows: the artwork, the title and the artist (the sheet's TrackTitles), the seek bar
(LIVE in its place for a live radio station) and the transport, and a flat header bar with
Leave Fullscreen, More Options (the item playing's menu), the heart, the volume and, while
the lyrics have translations or pronunciations, the Translation and Pronunciation menu
(now_playing.lyrics_menu()) — the pieces of widgets/transport.py, as the bar's and the
sheet's are; and the lyrics beside the
artwork while the song has some (or they are being read), larger (style.css, for a
LyricsView inside .fullscreen-player). Without lyrics the artwork and the controls are
centred on their own. The places follow the view's size (fullscreen.layout_for(), applied
as the view is allocated: it measures and allocates its child itself, so its Adw.Bin layout
manager is dropped): the artwork beside the lyrics, or in one column (narrow, or portrait) a
small cover beside the titles over the lyrics, the controls at the bottom.

The background is an ArtworkBackdrop (widgets/backdrop.py, shared with the Now Playing
sheet's tint): the artwork shrunk, blurred and stretched over the view (artwork.field_for(),
in a thread, kept for the last few covers) under a black scrim deep enough for the text over
it to read at WCAG AA (artwork.scrim_alpha()), drawn by a widget of its own so that the
lyrics' redraws never draw it again; a new item's field crossfades in (at once with
animations off).
The view carries libadwaita's `osd` class: white text and controls styled for an on-screen
display, as GNOME Videos' are, dark whatever the colour scheme.

Idle: after fullscreen.IDLE_SECONDS with no pointer motion (at new coordinates: GTK sends
motion as the cursor or the layout changes) and no key (the window's key handler calls
wake()), while the music plays, with no popover open, the pointer off the controls and the
header bar and the keyboard focus not shown on them (fullscreen.should_hide()), the header
bar slides away (`reveal-top-bars`), the controls fade (`idle`, an opacity transition: they
keep their room and stay focusable) and the cursor hides. One timeout at a time, only while
shown and playing. Escape leaves (win.fullscreen-player), after the focus widget and any
popover have had it.
"""

import logging
import time

from gi.repository import Adw, Gdk, GLib, Gtk

from .. import fullscreen
from ..actions import now_playing_track
from ..backend import config
from ..remote import fetch_remote
from . import artwork
from .backdrop import ArtworkBackdrop  # noqa: F401  registers it for the template
from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .now_playing import lyrics_menu
from .transport import (HeartControl, ModeControl, PlayButton, SeekControl, TrackTitles,
                        VolumeControl)

log = logging.getLogger(__name__)

# The artwork fetched larger than the cover file (COVER_SIZE) when it is drawn larger than
# that in device pixels (a HiDPI screen).
LARGE_ART_SIZE = 1200
LAYOUT_TITLE = {False: 'title-1', True: 'title-3'}   # one column with lyrics: beside the cover


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/fullscreen_player.ui')
class FullscreenPlayer(Adw.Bin):
    """The full-screen player. See the module."""

    __gtype_name__ = 'AppleMusicFullscreenPlayer'

    overlay = Gtk.Template.Child()
    backdrop = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    toolbar = Gtk.Template.Child()
    header = Gtk.Template.Child()
    leave_button = Gtk.Template.Child()
    more_button = Gtk.Template.Child()
    heart_button = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    volume_adjustment = Gtk.Template.Child()
    lyrics_button = Gtk.Template.Child()
    grid = Gtk.Template.Child()
    item_box = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    titles_box = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    controls_box = Gtk.Template.Child()
    seek_box = Gtk.Template.Child()
    seek_scale = Gtk.Template.Child()
    seek_adjustment = Gtk.Template.Child()
    elapsed_label = Gtk.Template.Child()
    remaining_label = Gtk.Template.Child()
    live_label = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    repeat_button = Gtk.Template.Child()
    lyrics_slot = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_layout_manager(None)  # do_measure and do_size_allocate below
        self.overlay.set_measure_overlay(self.toast_overlay, True)
        self._player = None
        self._app = None
        self.shown = False
        self.layout = None              # the fullscreen.Layout applied
        self.lyrics_view = None         # the sheet's LyricsView, while it is here
        self._item_url = None           # the artwork URL whose cover and field are shown
        self._item_task = None
        self.idle = False
        self._idle_source = 0
        self._last_activity = 0.0
        self._pointer = None            # where the pointer last moved to
        self._play = PlayButton(self.play_button)
        self._titles = TrackTitles(self.title_label, self.subtitle_label,
                                   sensitive=(self.seek_box, self.volume_button),
                                   tooltips=True)
        self._seek = SeekControl(self.seek_scale, self.seek_adjustment, self.elapsed_label,
                                 self.remaining_label, self.live_label)
        self._modes = ModeControl(self.shuffle_button, self.repeat_button)
        self._heart = HeartControl(self.heart_button, lazy=True)  # the bar's reads
        self._volume = VolumeControl(self.volume_button, self.volume_adjustment)
        self.more_button.set_create_popup_func(self._on_more_popup)

        motion = Gtk.EventControllerMotion()
        motion.connect('motion', self._on_motion)
        self.add_controller(motion)
        self._on_controls = []
        for widget in (self.controls_box, self.header):
            hover = Gtk.EventControllerMotion()
            hover.connect('leave', lambda *_: self.wake())
            widget.add_controller(hover)
            self._on_controls.append(hover)
        for button in (self.more_button, self.lyrics_button, self.volume_button):
            button.connect('notify::active', lambda *_: self.wake())
        # Escape leaves, once the focus widget and any popover have had it.
        shortcuts = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.BUBBLE)
        shortcuts.add_shortcut(Gtk.Shortcut(
            trigger=Gtk.KeyvalTrigger(keyval=Gdk.KEY_Escape, modifiers=0),
            action=Gtk.NamedAction(action_name='win.fullscreen-player')))
        self.add_controller(shortcuts)

    def set_player(self, player, app):
        """Follow `player`; `app` spawns the commands and the fetches."""
        self._player = player
        self._app = app
        self._play.attach(player)
        self._titles.attach(player)
        self._seek.attach(player, app)
        self._modes.attach(player, app)
        self._heart.attach(player, app)
        self._volume.attach(player, app)
        player.connect('notify::track', lambda *_: self._on_track())
        player.connect('notify::lyrics', lambda *_: self._on_lyrics())
        player.connect('notify::lyrics-loading', lambda *_: self._on_lyrics())
        player.connect('notify::state', lambda *_: self._on_state())
        self._on_track()
        self._on_lyrics()

    # -- the host's -------------------------------------------------------------------------

    def take_lyrics(self, view):
        """Hold the LyricsView (the sheet's) while shown."""
        self.lyrics_view = view
        self.lyrics_slot.set_child(view)

    def give_lyrics(self):
        """The LyricsView, out of the view again."""
        view, self.lyrics_view = self.lyrics_view, None
        self.lyrics_slot.set_child(None)
        return view

    def set_shown(self, shown):
        """Whether the view is the page shown: only then is the LyricsView active, the item
        followed and the idle timer armed."""
        if shown == self.shown:
            return
        self.shown = shown
        if self.lyrics_view is not None:
            self.lyrics_view.set_active(shown)
        if shown:
            self._show_item()
            self._heart.catch_up()
            self.wake()
        else:
            self._disarm_idle()
            self.set_idle(False)
            self._pointer = None
            if self._item_task is not None and not self._item_task.done():
                self._item_task.cancel()     # no field made for a view no one sees
                self._item_url = None        # fetched again as it shows
            self._item_task = None

    def focus_controls(self):
        """The focus on the play button (Leave Fullscreen with nothing to play)."""
        if not self.play_button.grab_focus():
            self.leave_button.grab_focus()

    def add_toast(self, toast):
        self.toast_overlay.add_toast(toast)

    # -- the item ---------------------------------------------------------------------------

    def _on_track(self):
        self.more_button.set_sensitive(self._playing_track() is not None)
        if self.shown:
            self._show_item()

    def _show_item(self):
        """The item's artwork and field, fetched and made only while shown, and only when
        the item's artwork differs from what is shown."""
        track = self._player.track if self._player is not None else None
        url = track.artwork_url if track is not None else None
        if url == self._item_url:
            return
        self._item_url = url
        if self._item_task is not None:
            self._item_task.cancel()
            self._item_task = None
        if not url or self._app is None:
            self.cover.set_paths()
            self.backdrop.show_field(None)
            return
        self._item_task = self._app.spawn(self._fetch_item(url))

    async def _fetch_item(self, url):
        path = await fetch_remote(url, config.COVER_SIZE)
        if url != self._item_url:
            return
        if not path:
            self.cover.set_paths()
            self.backdrop.show_field(None)
            return
        self.cover.set_paths(path)
        field = await artwork.field_for(path)
        if url != self._item_url:
            return
        self.backdrop.show_field(field)
        if self.cover.size * self.get_scale_factor() > config.COVER_SIZE:
            large = await fetch_remote(url, LARGE_ART_SIZE)
            if url == self._item_url and large:
                self.cover.set_paths(large, path)

    def _playing_track(self):
        return now_playing_track(self._player.track if self._player is not None else None)

    def _on_more_popup(self, button):
        actions = getattr(self.get_root(), 'item_actions', None)
        track = self._playing_track()
        button.set_menu_model(actions.menu_for(track, queued=True)
                              if actions is not None and track is not None else None)

    def _on_lyrics(self):
        player = self._player
        menu = lyrics_menu(player.lyrics if player is not None else None)
        self.lyrics_button.set_menu_model(menu)
        self.lyrics_button.set_visible(menu is not None)
        self.queue_resize()  # the lyrics column comes or goes (do_size_allocate)

    def has_lyrics(self):
        """Whether the lyrics column shows: the song has lyrics, or they are being read."""
        player = self._player
        return player is not None and (player.lyrics is not None or player.lyrics_loading)

    # -- layout -----------------------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        """The child's natural size, but no minimum: the layout for the size given
        (do_size_allocate) is what makes the content fit, down to 360 px, and the minimum
        measured here would be the last layout's."""
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1
        _minimum, natural, _baseline, _natural_baseline = child.measure(orientation, for_size)
        return 0, natural, -1, -1

    def do_size_allocate(self, width, height, baseline):
        layout = fullscreen.layout_for(width, height, self.has_lyrics())
        if layout != self.layout:
            self.apply_layout(layout)
        child = self.get_child()
        if child is not None:
            child.allocate(width, height, baseline, None)

    def apply_layout(self, layout):
        """Place the item, the controls and the lyrics as `layout` (a fullscreen.Layout)
        has them."""
        self.layout = layout
        one_column = layout.portrait and layout.lyrics
        grid = self.grid
        grid.set_margin_start(layout.margin)
        grid.set_margin_end(layout.margin)
        grid.set_margin_top(fullscreen.TOP_MARGIN)
        grid.set_margin_bottom(layout.margin if layout.portrait else fullscreen.MARGIN)
        grid.set_halign(Gtk.Align.FILL if layout.lyrics or layout.portrait
                        else Gtk.Align.CENTER)
        self.lyrics_slot.set_visible(layout.lyrics)
        manager = grid.get_layout_manager()

        def place(widget, column, row, rows=1):
            child = manager.get_layout_child(widget)
            child.set_column(column)
            child.set_row(row)
            child.set_row_span(rows)

        if one_column:
            place(self.item_box, 0, 0)
            place(self.lyrics_slot, 0, 1)
            place(self.controls_box, 0, 2)
        else:
            place(self.item_box, 0, 0)
            place(self.controls_box, 0, 1)
            place(self.lyrics_slot, 1, 0, 2)
        # Two rows that both expand share the height left alike: the item and the controls
        # meet in the middle, so together they are centred.
        self.item_box.set_vexpand(not one_column)
        self.item_box.set_valign(Gtk.Align.START if one_column else Gtk.Align.END)
        self.controls_box.set_vexpand(not one_column)
        self.controls_box.set_valign(Gtk.Align.END if one_column else Gtk.Align.START)
        self.item_box.set_orientation(Gtk.Orientation.HORIZONTAL if one_column
                                      else Gtk.Orientation.VERTICAL)
        self.item_box.set_spacing(12 if one_column else 24)
        self.item_box.set_halign(Gtk.Align.FILL if layout.portrait else Gtk.Align.CENTER)
        self.titles_box.set_hexpand(one_column)
        for label in (self.title_label, self.subtitle_label):
            label.set_xalign(0 if one_column else 0.5)
            label.set_justify(Gtk.Justification.LEFT if one_column
                              else Gtk.Justification.CENTER)
        self.title_label.remove_css_class(LAYOUT_TITLE[not one_column])
        self.title_label.add_css_class(LAYOUT_TITLE[one_column])
        if layout.portrait:
            self.add_css_class('portrait')
        else:
            self.remove_css_class('portrait')
        self.cover.set_property('size', layout.art_size)

    # -- idle -------------------------------------------------------------------------------

    def wake(self):
        """Show the controls and the cursor, and start the idle wait again: any motion or
        key."""
        self._last_activity = time.monotonic()
        if self.idle:
            self.set_idle(False)
        self._arm_idle(fullscreen.IDLE_SECONDS)

    def _on_motion(self, _controller, x, y):
        pointer = (round(x), round(y))
        if pointer != self._pointer:
            self._pointer = pointer
            self.wake()

    def _on_state(self):
        if not self.shown:
            return
        if self._player.active:
            self._arm_idle(fullscreen.IDLE_SECONDS)
        else:
            self._disarm_idle()
            self.set_idle(False)

    def _arm_idle(self, seconds):
        if (not self.shown or self._idle_source or self._player is None
                or not self._player.active):
            return
        self._idle_source = GLib.timeout_add(max(1, round(seconds * 1000)),
                                             self._on_idle_timeout)

    def _disarm_idle(self):
        if self._idle_source:
            GLib.source_remove(self._idle_source)
            self._idle_source = 0

    def _on_idle_timeout(self):
        self._idle_source = 0
        if not self.shown:
            return GLib.SOURCE_REMOVE
        idle_for = time.monotonic() - self._last_activity
        if idle_for < fullscreen.IDLE_SECONDS:
            self._arm_idle(fullscreen.IDLE_SECONDS - idle_for)
        elif fullscreen.should_hide(self._player.active, self._popover_open(),
                                    self._pointer_on_controls(),
                                    self._keyboard_on_controls(), idle_for):
            self.set_idle(True)
        else:
            self._arm_idle(fullscreen.IDLE_SECONDS)   # look again: still in use
        return GLib.SOURCE_REMOVE

    def _popover_open(self):
        return any(button.get_active()
                   for button in (self.more_button, self.lyrics_button, self.volume_button))

    def _pointer_on_controls(self):
        return any(hover.contains_pointer() for hover in self._on_controls)

    def _focus_in(self, *widgets):
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        return focus is not None and any(focus is widget or focus.is_ancestor(widget)
                                         for widget in widgets)

    def _keyboard_on_controls(self):
        root = self.get_root()
        return (root is not None and root.get_focus_visible()
                and self._focus_in(self.controls_box, self.header))

    def set_idle(self, idle):
        """Hide the controls and the cursor (`idle`), or show them."""
        if idle == self.idle:
            return
        self.idle = idle
        if idle and self._focus_in(self.header):
            self.play_button.grab_focus()   # never on a widget sliding away
        self.toolbar.set_reveal_top_bars(not idle)
        if idle:
            self.add_css_class('idle')
        else:
            self.remove_css_class('idle')
        self.set_cursor_from_name('none' if idle else None)
