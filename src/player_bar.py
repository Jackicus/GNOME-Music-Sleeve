# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicPlayerBar: the transport bar, following the Player.

The window hands it the Player (set_player) once, after the template is built, and reveals
the bar only while the Player has an item (Window._reveal_player_bar): "Not Playing" is
what the bar shows while hidden, and on its way out. Everything
shown comes from the Player's properties: the play button's icon from `state`, the title,
artist and artwork from `track` (the artwork fetched by remote.fetch_remote at the cover
size, so the Now Playing sheet and MPRIS find the same file), the seek slider and the times
from `position` and `duration` (a LIVE badge in their place for a live radio station, whose
play button is Stop: transport.py), the toggles from `shuffle` and `repeat`, the volume button
from `volume`, the heart from the engine's rating of the track (HeartControl). The previous,
play and next buttons run the app's actions (app.previous, app.play-pause, app.next: enabled
while something plays, Next and Previous while MusicKit allows them); the toggles and the
sliders call the Player's coroutines, and a failure is toasted by the app. The play button,
the seek slider, the toggles, the volume, the heart and the artwork are the pieces
widgets/transport.py holds, shared with the Now Playing sheet. Lyrics and Up Next are
toggle buttons over the window's win.show-lyrics and
win.show-queue (widgets/now_playing.py's TabActions): they open the sheet on that tab, show
pressed while it is in sight, and Lyrics is off for a song without lyrics; their tooltips
name their keys (shortcuts.NOW_PLAYING_TABS). Below the window's 640sp breakpoint
(`narrow`) the title needs their room, and the sheet the bar opens has the tabs.

Below 600sp (`compact`) the bar is a phone's, as Apple Music's mini player is: the
artwork and the titles first, then Play (Stop for a live station) and Next at the end, the
transport box moved after the item's (in a right-to-left locale the whole row mirrors), and
no Previous, seek slider, times or right-hand box (the sheet the bar opens has them). A
live station keeps its LIVE badge under the titles. GTK's Tab order follows where the
children are laid out, not their order, so Tab goes from the bar to Play, then Next.

A right click, a long press or the Menu key on the bar opens the item playing's menu (its
`context_item`: context_menu on the bar's button), as the Now Playing sheet's More Options
button does.

The bar takes drops (widgets/dnd.py, library.ItemRefs: drags that start in the app): songs,
music videos, albums and playlists dragged onto it are queued at the end, as Play Later
does, or after the item playing with Shift held, as Play Next does
(ItemActions.queue_drop, actions.queue_targets); the bar is highlighted while a drag it
takes is over it. A drag carrying anything that cannot be queued (a folder) is refused.

For assistive technology: the bar announces each new item (Gtk.Accessible.announce, "Now
playing …", "Now playing live: …" for a live radio station, whose LIVE badge no focus
reaches); the button Adw.BottomSheet puts around the bar (a click on the bar opens the
sheet) is named "Now Playing" and described by the item playing, where it would otherwise be
named after everything in the bar; the volume button and its slider are named "Volume" and
read their level as a percentage (VolumeControl), which the window's volume keys step
(step_volume(): Ctrl+Up, Ctrl+Down, keyboard.volume_step); the seek slider reads "1:05 of 3:40"
(SeekControl).
"""

from gettext import gettext as _

from gi.repository import Adw, Gdk, GObject, Gtk

from . import shortcuts
from .actions import now_playing_track, queue_targets
from .library import ItemRefs
from .widgets import context_menu, dnd
from .widgets.cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .widgets.transport import (HeartControl, ModeControl, PlayButton, RemoteCover, SeekControl,
                                TrackTitles, VolumeControl, track_subtitle)

@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/player_bar.ui')
class PlayerBar(Adw.Bin):
    """The transport bar under the content. See the module."""

    __gtype_name__ = 'AppleMusicPlayerBar'

    # The item playing's menu is a queued one: no Play (context_menu).
    context_queued = True

    transport_box = Gtk.Template.Child()
    previous_button = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    next_button = Gtk.Template.Child()
    item_box = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    explicit_badge = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    seek_box = Gtk.Template.Child()
    seek_scale = Gtk.Template.Child()
    seek_adjustment = Gtk.Template.Child()
    elapsed_label = Gtk.Template.Child()
    remaining_label = Gtk.Template.Child()
    live_label = Gtk.Template.Child()
    controls_box = Gtk.Template.Child()
    heart_button = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    repeat_button = Gtk.Template.Child()
    volume_button = Gtk.Template.Child()
    volume_adjustment = Gtk.Template.Child()
    lyrics_button = Gtk.Template.Child()
    queue_button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._player = None
        self._app = None
        self._compact = False
        self._narrow = False
        self._announced = None      # the id of the item last announced
        self._play = PlayButton(self.play_button)
        self._titles = TrackTitles(self.title_label, self.subtitle_label,
                                   sensitive=(self.seek_box, self.volume_button))
        self._seek = SeekControl(self.seek_scale, self.seek_adjustment, self.elapsed_label,
                                 self.remaining_label, self.live_label)
        self._modes = ModeControl(self.shuffle_button, self.repeat_button)
        self._heart = HeartControl(self.heart_button)
        self._art = RemoteCover(self.cover)
        self._volume = VolumeControl(self.volume_button, self.volume_adjustment)
        for button, action in ((self.lyrics_button, 'show-lyrics'),
                               (self.queue_button, 'show-queue')):
            button.set_tooltip_text(tooltip_with_keys(button.get_tooltip_text(),
                                                      shortcuts.NOW_PLAYING_TABS[action][0]))
        # Drops queue what they carry (see the module). The bar lives as long as the window,
        # so its own methods may handle its controller's signals.
        self._drop_feedback = dnd.DropFeedback()
        drop = Gtk.DropTarget.new(ItemRefs.__gtype__,
                                  Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect('accept', self._on_drop_accept)
        drop.connect('enter', self._on_drop_motion)
        drop.connect('motion', self._on_drop_motion)
        drop.connect('leave', self._on_drop_leave)
        drop.connect('drop', self._on_drop)
        self.add_controller(drop)

    def _get_compact(self):
        return self._compact

    def _set_compact(self, compact):
        # A phone's bar (see the module): Play and Next after the item, the right-hand box
        # gone whole (its spacing with it), no Previous and no slider. The Now Playing sheet,
        # which the bar opens, has them all.
        self._compact = compact
        self.previous_button.set_visible(not compact)
        self.transport_box.get_parent().reorder_child_after(
            self.transport_box, self.item_box if compact else None)
        self.controls_box.set_visible(not compact)
        self._seek.set_times_shown(not compact)
        self._show_playing_controls()

    compact = GObject.Property(type=bool, default=False, getter=_get_compact, setter=_set_compact,
                               nick='Compact',
                               blurb='The item first, then Play and Next; no Previous, slider, '
                                     'volume, heart, shuffle, repeat, Lyrics or Up Next (narrow)')

    def _get_narrow(self):
        return self._narrow

    def _set_narrow(self, narrow):
        # Below the window's 640sp breakpoint, Lyrics and Up Next would cut the title short:
        # they go first, before the rest of the right-hand box goes at 600sp (compact).
        self._narrow = narrow
        for button in (self.lyrics_button, self.queue_button):
            button.set_visible(not narrow)
        self._show_playing_controls()

    narrow = GObject.Property(type=bool, default=False, getter=_get_narrow, setter=_set_narrow,
                              nick='Narrow', blurb='No Lyrics or Up Next buttons (the title '
                                                   'needs their room)')

    def set_player(self, player, app):
        """Follow `player`; `app` spawns the commands and reports their failures."""
        self._player = player
        self._app = app
        self._play.attach(player)
        self._titles.attach(player)
        self._seek.attach(player, app)
        self._modes.attach(player, app)
        self._heart.attach(player, app)
        self._art.attach(player, app)
        self._volume.attach(player, app)
        self._strings = {
            'now-playing': _('Now Playing'),
            'not-playing': _('Not Playing'),
            'announce': _('Now playing: {title} by {artist}'),
            'announce-title': _('Now playing: {title}'),
            # Translators: announced as a live radio station starts; {title} is its name.
            'announce-live': _('Now playing live: {title}'),
        }
        button = self._bar_button()
        if button is not None:
            button.update_property([Gtk.AccessibleProperty.LABEL], [self._strings['now-playing']])
            context_menu.attach(button)  # on the button: the Menu key reaches it, focused
        player.connect('notify::track', lambda *_: self._update_track())
        self._update_track()

    @property
    def context_item(self):
        """The item playing, as the Track its menu is for (actions.now_playing_track), or
        None."""
        return now_playing_track(self._player.track if self._player is not None else None)

    def _bar_button(self):
        """The button Adw.BottomSheet puts around the bar (a click on it opens the sheet),
        or None."""
        parent = self.get_parent()
        return parent if isinstance(parent, Gtk.Button) else None

    def step_volume(self, step):
        """A volume key (the window's Ctrl+Up or Ctrl+Down): the volume a step up (1) or down
        (-1), sent as the volume button's slider sends it. The new level, 0 to 1."""
        return self._volume.step(step)

    def grab_bar_focus(self):
        """Put the focus on the bar itself (it opens Now Playing): win.focus-player when the
        bar's own buttons are off, or the focus was on a control that has gone."""
        button = self._bar_button()
        return button.grab_focus() if button is not None else self.grab_focus()

    # -- drops -----------------------------------------------------------------------------

    @staticmethod
    def takes(refs):
        """Whether a drop of `refs` (a library.ItemRefs) is queued here: all it carries can
        be (actions.queue_targets)."""
        return queue_targets(refs) is not None

    def show_drop_target(self, shown=True):
        """Highlight the bar as where a drop goes, as a drag over it that it takes does
        (False: not highlighted)."""
        self._drop_feedback.highlight(self if shown else None)

    def _on_drop_accept(self, _target, _drop):
        return self.takes(dnd.current())

    def _on_drop_motion(self, target, _x, _y):
        """A drag over the bar: the action a drop would do (COPY, or MOVE when the source
        offers nothing else, or Shift held makes it one), the bar highlighted when it takes
        the drag."""
        drop = target.get_current_drop()
        action = (dnd.choose_action(drop.get_actions())
                  if drop is not None and self.takes(dnd.current()) else 0)
        self.show_drop_target(bool(action))
        return action

    def _on_drop_leave(self, _target):
        self._drop_feedback.clear()

    def _on_drop(self, target, value, _x, _y):
        """What was dropped, queued (ItemActions.queue_drop): after the item playing with
        Shift held (dnd.shift_held), else at the end."""
        self._drop_feedback.clear()
        refs = dnd.current() or value  # the drag's own ItemRefs, with its objects
        actions = getattr(self.get_root(), 'item_actions', None)
        if actions is None or not self.takes(refs):
            return False
        drop = target.get_current_drop()
        selected = drop.get_actions() if drop is not None else 0
        return actions.queue_drop(refs, next_up=dnd.shift_held(selected, dnd.offered(),
                                                                dnd.modifiers(self)))

    # -- following the Player --------------------------------------------------------------

    def _update_track(self):
        """What the bar adds to TrackTitles: the explicit badge, the controls that show only
        with an item, the bar button's description, and the announcement of a new item
        (once per item; the same song after a stop is announced again)."""
        track = self._player.track if self._player is not None else None
        playing = track is not None
        self.explicit_badge.set_visible(playing and track.explicit)
        self._show_playing_controls()
        button = self._bar_button()
        if button is not None:
            description = (', '.join(part for part in (track.title, track_subtitle(track))
                                     if part) if playing else self._strings['not-playing'])
            button.update_property([Gtk.AccessibleProperty.DESCRIPTION], [description])
        if not playing:
            self._announced = None
        elif track.id != self._announced:
            self._announced = track.id
            self._announce(track)

    def _show_playing_controls(self):
        """The seek slider and the heart only with an item (the bar on its way out shows no
        dead slider), and in the compact bar no slider, only a live station's LIVE badge; the
        focus, if it was on a control now hidden or insensitive, moves to the bar itself (the
        Now Playing button), never off the window. When the bar itself goes with the item,
        the window moves the focus on into the page."""
        playing = self._player is not None and self._player.track is not None
        self.seek_box.set_visible(playing and (not self._compact or self._player.live))
        self.heart_button.set_visible(playing)
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        if (focus is not None and focus.is_ancestor(self)
                and not (focus.get_mapped() and focus.is_sensitive())):
            self.grab_bar_focus()

    def _announce(self, track):
        """Tell assistive technology what plays now, as a screen reader user cannot see the
        bar change. Through the window: GTK drops an announcement from a widget whose
        accessible object no client has asked for yet (the bar's, usually), and the window's
        always is."""
        title = self.title_label.get_label()
        if track.live:
            message = self._strings['announce-live'].format(title=title)
        elif track.artist:
            message = self._strings['announce'].format(title=title, artist=track.artist)
        else:
            message = self._strings['announce-title'].format(title=title)
        (self.get_root() or self).announce(message, Gtk.AccessibleAnnouncementPriority.MEDIUM)


def tooltip_with_keys(tooltip, accel):
    """A button's tooltip followed by its shortcut: "Lyrics (Shift+Ctrl+L)" for "Lyrics" and
    '<primary><shift>l' (the key as GTK names it, as in its menus)."""
    ok, key, mods = Gtk.accelerator_parse(accel)
    if not ok:
        return tooltip
    # Translators: a button's tooltip with its shortcut: {tooltip} is what it does
    # ("Lyrics"), {keys} its key ("Shift+Ctrl+L").
    return _('{tooltip} ({keys})').format(tooltip=tooltip,
                                          keys=Gtk.accelerator_get_label(key, mods))
