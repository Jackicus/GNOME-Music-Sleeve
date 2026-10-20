# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicNowPlayingSheet: the bottom sheet's Now Playing view, following the Player.

The window hands it the Player, the app and the Adw.BottomSheet it sits in (set_player)
once, after the template is built. The artwork, titles, transport, seek slider, toggles,
heart and volume follow the Player as the player bar's do (the pieces are shared:
widgets/transport.py); the Lyrics and Up Next tabs are a LyricsView and a QueueView (built
here: GtkBuilder does not run a Python widget's __init__) in an Adw.ViewStack an inline
view switcher switches. More Options is the item playing's menu (the window's item actions:
Go to Album, Go to Artist, Add to Playlist…, without Play), made as it opens. Beside the
volume, while the lyrics have translations or pronunciations, a menu of Show Translations
and Show Pronunciations (those the lyrics have: the `lyrics-translations` and
`lyrics-pronunciations` settings' actions), and Fullscreen (win.fullscreen-player: the
full-screen player, fullscreen.py), which borrows the LyricsView out of the Lyrics tab's
`lyrics_slot` while it shows (lend_lyrics(), return_lyrics()), the sheet covered meanwhile
(set_covered(): its views inactive, open or not). The close
button sets the bottom sheet's `open` false; Escape and a swipe down are the bottom sheet's
own; Go to Album and Go to Artist close the sheet too (window.open_item).

The tabs from outside: `shown-tab` is the tab in sight ('lyrics' or 'queue': the sheet open
and not covered, '' otherwise) and show_tab() switches to one. TabActions, the window's
win.show-lyrics and win.show-queue (the player bar's Lyrics and Up Next toggle buttons,
Ctrl+Shift+L and Ctrl+Shift+U), opens the sheet on a tab through them, closes it when it
shows that tab already, and keeps each action's state on whether its tab is in sight.

Sizing: an AdwBottomSheet gives its sheet its natural height (clamped to the window less a
margin), so this widget asks for a tall one (SHEET_NATURAL_HEIGHT) and the tabs' lists take
what is left under the controls. It measures and allocates its child itself: an Adw.Bin's
layout manager answers gtk_widget_measure before the class's measure vfunc, so the bin's is
dropped (set_layout_manager(None)). The window's breakpoints set three properties: `wide`
(900sp and up) lays the item and the tabs side by side; `compact` (600sp and under) shrinks
the artwork so a phone-sized window keeps room for the tabs; `short` (a window too low for
the artwork over the titles: window.blp's height conditions) puts a small cover beside the
titles instead, so the transport is never cut off and the tabs keep a few lines.
"""

from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from ..actions import now_playing_track
from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .lyrics import LyricsView
from .queue import QueueView
from .transport import (HeartControl, ModeControl, PlayButton, RemoteCover, SeekControl,
                        TrackTitles, VolumeControl)

SHEET_NATURAL_HEIGHT = 10000   # as tall as the window allows
COVER_SIZE = 320
COVER_SIZE_COMPACT = 240
COVER_SIZE_SHORT = 96          # beside the titles, in a short window

# The window actions that show a tab (shortcuts.NOW_PLAYING_TABS), by the tab's name.
TAB_ACTIONS = {'lyrics': 'show-lyrics', 'queue': 'show-queue'}


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/now_playing.ui')
class NowPlayingSheet(Adw.Bin):
    """The Now Playing sheet. See the module."""

    __gtype_name__ = 'AppleMusicNowPlayingSheet'

    toast_overlay = Gtk.Template.Child()
    close_button = Gtk.Template.Child()
    more_button = Gtk.Template.Child()
    heart_button = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    volume_adjustment = Gtk.Template.Child()
    lyrics_button = Gtk.Template.Child()
    fullscreen_button = Gtk.Template.Child()
    layout = Gtk.Template.Child()
    player_column = Gtk.Template.Child()
    item_box = Gtk.Template.Child()
    titles_box = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    seek_box = Gtk.Template.Child()
    seek_scale = Gtk.Template.Child()
    seek_adjustment = Gtk.Template.Child()
    elapsed_label = Gtk.Template.Child()
    remaining_label = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    repeat_button = Gtk.Template.Child()
    tab_stack = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_layout_manager(None)  # do_measure and do_size_allocate below
        self._player = None
        self._bottom_sheet = None
        self._open = False
        self._wide = False
        self._compact = False
        self._short = False
        self._covered = False   # the full-screen player shows over the window
        self._shown_tab = ''
        self.lyrics_view = LyricsView()
        self.queue_view = QueueView()
        # The Lyrics tab holds the LyricsView in a slot, out of which the full-screen
        # player borrows it while it shows (lend_lyrics()), the tab's page staying.
        self.lyrics_slot = Adw.Bin(child=self.lyrics_view)
        self.tab_stack.add_titled(self.lyrics_slot, 'lyrics', _('Lyrics'))
        self.tab_stack.add_titled(self.queue_view, 'queue', _('Up Next'))
        self.tab_stack.connect('notify::visible-child-name', lambda *_: self._on_open_changed())
        self._play = PlayButton(self.play_button)
        self._titles = TrackTitles(self.title_label, self.subtitle_label,
                                   sensitive=(self.seek_box, self.shuffle_button,
                                              self.repeat_button, self.volume_button),
                                   tooltips=True)
        self._seek = SeekControl(self.seek_scale, self.seek_adjustment, self.elapsed_label,
                                 self.remaining_label)
        self._modes = ModeControl(self.shuffle_button, self.repeat_button)
        self._heart = HeartControl(self.heart_button)
        self._volume = VolumeControl(self.volume_button, self.volume_adjustment)
        self._art = RemoteCover(self.cover)
        self.more_button.set_create_popup_func(self._on_more_popup)
        self._apply_layout()

    # -- layout ------------------------------------------------------------------------------

    def _get_wide(self):
        return self._wide

    def _set_wide(self, wide):
        if wide != self._wide:
            self._wide = wide
            self._apply_layout()

    wide = GObject.Property(type=bool, default=False, getter=_get_wide, setter=_set_wide,
                            nick='Wide', blurb='The item and the tabs side by side')

    def _get_compact(self):
        return self._compact

    def _set_compact(self, compact):
        if compact != self._compact:
            self._compact = compact
            self._apply_layout()

    compact = GObject.Property(type=bool, default=False, getter=_get_compact,
                               setter=_set_compact, nick='Compact', blurb='Smaller artwork')

    def _get_short(self):
        return self._short

    def _set_short(self, short):
        if short != self._short:
            self._short = short
            self._apply_layout()

    short = GObject.Property(type=bool, default=False, getter=_get_short, setter=_set_short,
                             nick='Short', blurb='A small cover beside the titles')

    def _apply_layout(self):
        wide, short = self._wide, self._short
        self.layout.set_orientation(
            Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL)
        self.layout.set_spacing(36 if wide else 12 if self._compact or short else 18)
        self.player_column.set_valign(Gtk.Align.CENTER if wide else Gtk.Align.START)
        self.player_column.set_spacing(12 if (self._compact or short) and not wide else 18)
        self.player_column.set_hexpand(False)
        self.player_column.set_halign(Gtk.Align.FILL if short and not wide
                                      else Gtk.Align.CENTER)
        # The cover beside the titles (short), else over them.
        self.item_box.set_orientation(Gtk.Orientation.HORIZONTAL if short
                                      else Gtk.Orientation.VERTICAL)
        self.item_box.set_spacing(12 if short else 18)
        self.item_box.set_halign(Gtk.Align.FILL if short else Gtk.Align.CENTER)
        self.titles_box.set_hexpand(short)
        self.titles_box.set_halign(Gtk.Align.START if short else Gtk.Align.CENTER)
        for label in (self.title_label, self.subtitle_label):
            label.set_xalign(0 if short else 0.5)
            label.set_justify(Gtk.Justification.LEFT if short else Gtk.Justification.CENTER)
        self.cover.set_property(
            'size', COVER_SIZE_SHORT if short
            else COVER_SIZE_COMPACT if self._compact and not wide else COVER_SIZE)

    def do_measure(self, orientation, for_size):
        child = self.get_child()
        if child is None:
            return 0, 0, -1, -1
        minimum, natural, minimum_baseline, natural_baseline = child.measure(orientation,
                                                                             for_size)
        if orientation == Gtk.Orientation.VERTICAL:
            natural = max(natural, SHEET_NATURAL_HEIGHT)
        return minimum, natural, minimum_baseline, natural_baseline

    def do_size_allocate(self, width, height, baseline):
        child = self.get_child()
        if child is not None:
            child.allocate(width, height, baseline, None)

    # -- the tabs ----------------------------------------------------------------------------

    def _get_shown_tab(self):
        return self._shown_tab

    shown_tab = GObject.Property(type=str, default='', getter=_get_shown_tab,
                                 flags=GObject.ParamFlags.READABLE, nick='Shown tab',
                                 blurb="The tab in sight ('lyrics' or 'queue'), or '' while "
                                       'the sheet is closed or covered')

    def show_tab(self, tab):
        """Switch to `tab` ('lyrics' or 'queue'), open or not."""
        self.tab_stack.set_visible_child_name(tab)

    # -- the Player --------------------------------------------------------------------------

    def set_player(self, player, app, bottom_sheet):
        """Follow `player`; `app` spawns the commands and reports their failures;
        `bottom_sheet` is the Adw.BottomSheet this is the sheet of."""
        self._player = player
        self._bottom_sheet = bottom_sheet
        self._play.attach(player)
        self._titles.attach(player)
        self._seek.attach(player, app)
        self._modes.attach(player, app)
        self._heart.attach(player, app)
        self._volume.attach(player, app)
        self._art.attach(player, app)
        self.lyrics_view.set_player(player, app)
        self.queue_view.set_player(player, app)
        bottom_sheet.connect('notify::open', lambda *_: self._on_open_changed())
        player.connect('notify::track', lambda *_: self._update_more())
        player.connect('notify::lyrics', lambda *_: self._update_lyrics_button())
        self._on_open_changed()
        self._update_more()
        self._update_lyrics_button()

    def _playing_track(self):
        """The item playing as the Track its menu is for, or None (actions)."""
        return now_playing_track(self._player.track if self._player is not None else None)

    def _update_more(self):
        """More Options only while an item with a menu plays (not a station's segment)."""
        self.more_button.set_sensitive(self._playing_track() is not None)

    def _on_more_popup(self, button):
        """The item playing's menu, made as it opens (whether it is a favourite is asked
        then)."""
        actions = getattr(self.get_root(), 'item_actions', None)
        track = self._playing_track()
        button.set_menu_model(actions.menu_for(track, queued=True)
                              if actions is not None and track is not None else None)

    def _update_lyrics_button(self):
        """The Translation and Pronunciation menu, while the lyrics have either."""
        menu = lyrics_menu(self._player.lyrics if self._player is not None else None)
        self.lyrics_button.set_menu_model(menu)
        self.lyrics_button.set_visible(menu is not None)

    def set_covered(self, covered):
        """The full-screen player shows over the window (fullscreen.FullscreenHost): the
        sheet, open or not, is out of sight, its views inactive."""
        self._covered = covered
        self._on_open_changed()

    def lend_lyrics(self):
        """The LyricsView, out of the Lyrics tab, for the full-screen player (inactive, as
        the sheet is covered first)."""
        self.lyrics_slot.set_child(None)
        return self.lyrics_view

    def return_lyrics(self, view):
        """The LyricsView back in its tab; the sheet makes it active again when it is
        open on that tab (set_covered(False)), which centres the current line."""
        self.lyrics_slot.set_child(view)

    def _on_open_changed(self):
        is_open = self._bottom_sheet is not None and self._bottom_sheet.get_open()
        seen = is_open and not self._covered
        shown = self.tab_stack.get_visible_child_name()
        if self.lyrics_view.get_parent() is self.lyrics_slot:  # else the full screen's
            self.lyrics_view.set_active(seen and shown == 'lyrics')
        self.queue_view.set_active(seen and shown == 'queue')
        shown_tab = (shown or '') if seen else ''
        if shown_tab != self._shown_tab:
            self._shown_tab = shown_tab
            self.notify('shown-tab')
        if is_open and not self._open:
            # The bottom sheet puts the focus on the sheet's first focusable widget (the seek
            # slider); the play button is where the keyboard wants to start. After the
            # sheet's own grab, from an idle.
            GLib.idle_add(self._focus_on_open)
        self._open = is_open

    def _focus_on_open(self):
        if self._bottom_sheet is not None and self._bottom_sheet.get_open():
            self.focus_controls()
        return GLib.SOURCE_REMOVE

    def focus_controls(self):
        """Put the focus on the play button, or on the close button with nothing playing
        (Ctrl+3 while the sheet is open, and as it opens)."""
        if not self.play_button.grab_focus():
            self.close_button.grab_focus()

    def add_toast(self, toast):
        self.toast_overlay.add_toast(toast)

    # -- the user ----------------------------------------------------------------------------

    @Gtk.Template.Callback()
    def on_close_clicked(self, _button):
        if self._bottom_sheet is not None:
            self._bottom_sheet.set_open(False)


class TabActions:
    """The window's win.show-lyrics and win.show-queue (TAB_ACTIONS): each opens the sheet on
    its tab, or closes it when it shows that tab already; from the full-screen player, back
    to the sheet, open on the tab. Stateful: an action's state is whether its tab is in sight
    (the sheet's `shown-tab`), which the player bar's toggle buttons show. Enabled while
    there is something to show there (can_show_tab()), and while the window lets its
    actions run (set_free(): no dialog over it). It lives as long as the window."""

    def __init__(self, sheet, bottom_sheet, player, fullscreen_host):
        self._sheet = sheet
        self._bottom_sheet = bottom_sheet
        self._player = player
        self._host = fullscreen_host
        self._free = True
        self.actions = {}
        for tab, name in TAB_ACTIONS.items():
            action = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(False))
            action.connect('activate', lambda _action, _parameter, tab=tab: self.toggle(tab))
            self.actions[tab] = action
        sheet.connect('notify::shown-tab', lambda *_: self.update())
        for name in ('track', 'lyrics', 'lyrics-loading'):
            player.connect('notify::' + name, lambda *_: self.update())
        self.update()

    def toggle(self, tab):
        """The sheet open on `tab`, or closed when it shows that tab already."""
        if self._host.shown:
            self._host.leave(restore_focus=False)
        elif self._sheet.shown_tab == tab:
            self._bottom_sheet.set_open(False)
            return
        self._sheet.show_tab(tab)  # before it opens: it slides in on the tab
        self._bottom_sheet.set_open(True)

    def set_free(self, free):
        """Whether the window lets its actions run (False while a dialog is over it)."""
        self._free = free
        self.update()

    def update(self):
        shown = self._sheet.shown_tab
        player = self._player
        for tab, action in self.actions.items():
            state = shown == tab
            if action.get_state().get_boolean() != state:
                action.set_state(GLib.Variant.new_boolean(state))
            action.set_enabled(self._free and can_show_tab(
                tab, shown, player.track, player.lyrics, player.lyrics_loading))


def can_show_tab(tab, shown_tab, track, lyrics, lyrics_loading):
    """Whether the sheet has something to show on `tab`: Up Next while an item plays, the
    lyrics while it has some or they are being read (a song without them: no); or `tab` is
    the one shown, so that it can be closed again."""
    if tab == shown_tab:
        return True
    if track is None:
        return False
    return tab != 'lyrics' or lyrics is not None or lyrics_loading


def lyrics_menu(lyrics):
    """The Translation and Pronunciation menu for `lyrics`: Show Translations when they have
    translations, Show Pronunciations when they have pronunciations; None for neither."""
    if lyrics is None or not (lyrics.has_translations or lyrics.has_pronunciations):
        return None
    menu = Gio.Menu()
    if lyrics.has_translations:
        menu.append(_('Show _Translations'), 'app.lyrics-translations')
    if lyrics.has_pronunciations:
        menu.append(_('Show _Pronunciations'), 'app.lyrics-pronunciations')
    return menu
