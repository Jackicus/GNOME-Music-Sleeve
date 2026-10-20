# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A track list's selection mode (docs/decisions.md), as GNOME Music and Files have one: the
Songs table, an album's and a playlist's songs (Favourite Songs' too).

    mode = SelectionMode(page, header_bar, toolbar_view, view, shown, focus_return)
    header_bar.pack_end(mode.select_button); header_bar.pack_end(mode.cancel_button)
    mode.set_header_title(header_title); mode.set_filter_bar(filter_bar)
    mode.set_available(has_tracks)        # Select shown; no tracks leaves the mode
    mode.set_context(playlist, library, favourites)   # which batch actions the bar offers
    mode.set_narrow(narrow)               # the bar's narrow layout (a page breakpoint's)
    if mode.activated(track): return      # the list's activate: a click or Enter
    mode.prune()                          # after a filter's or a sync's change
    mode.selection                        # selection.Selection: has(track) in a bind

A click plays a song, as before: the lists stay `Gtk.NoSelection` and single-click-activate.
The mode is entered by the header bar's Select button (`selection-mode-symbolic`), by a
Ctrl+click or a Shift+click on a row (activated() reads the keyboard's modifiers, as
dnd.shift_held() does: no gesture of its own, so a drag is a drag), and by Ctrl+A on a row; in
it a click or Enter toggles the row and Shift extends from the last toggled. The window's key
controller asks keyboard.selection_key() for Space (toggle), Shift+Space, Ctrl+A,
Ctrl+Shift+A and Escape (leave) and calls key(). It is left by Cancel, Escape, an action of
the bar, and the page hidden or emptied.

In the mode the header bar shows the count as its title, a menu of Select All and Select
None (HeaderTitle held), and Cancel in place of Select (Back, and the filter's button, which
set_filter_bar() names, and the page's own Sort leave it their room at 360 px); a
Gtk.ActionBar under the page (`[bottom]` of its toolbar view) holds the batch actions, which
go through the window's item actions with the selected tracks in the order shown: Play Next,
Play Later, Add to Playlist (the playlists, then New Playlist…), Remove from Playlist (a
playlist of the user's: one write, Undo on its toast), or on Favourite Songs Remove from
Favourites in its place (each song unloved, Undo on the toast), and Remove from Library…
(one confirmation). In the narrow layout Play Later and the removals are in a More menu, and
so is Remove from Library… beside Remove from Playlist or Remove from Favourites
(_layout()). They are a `selection` action group on the page. The count is announced as it
changes. A row's look is the page's: a check box in the
row (`.selection-mode`), "Selected" in its description, both from selection.has().

The page holds this object, which holds the page's widgets it made, the view and the
selection; it holds the page only weakly (its hooks through weak_method()), and every child's
signal is connected weakly: a page that can be dropped is freed with it.
"""

from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..selection import Selection
from . import dnd, track_links
from .util import connect_weak, weak_method

_words = {}


def selection_words():
    """("Selected", "Not Selected"): a row's description in the mode, looked up once (rows
    are bound by the thousand)."""
    if not _words:
        _words['selected'] = _('Selected')
        _words['unselected'] = _('Not Selected')
    return _words['selected'], _words['unselected']


def row_description(selecting, selected, description):
    """A row's accessible description: in the mode "Selected, …" or "Not Selected, …" before
    what it says otherwise (its time, or "Playing")."""
    if not selecting:
        return description
    words = selection_words()[0 if selected else 1]
    return f'{words}, {description}' if description else words


def count_title(count):
    """The header bar's title in the mode."""
    if not count:
        return _('Select Songs')
    return ngettext('{count} Selected', '{count} Selected', count).format(count=f'{count:n}')


class SelectionMode(GObject.Object):
    """The selection mode of a page's track list: see the module. `shown()` answers the
    Tracks the list shows, in order; `focus_return(track)` puts the focus on track's row (or
    the first) and answers whether it could, as a filter bar's does."""

    __gtype_name__ = 'AppleMusicSelectionMode'

    def __init__(self, page, header_bar, toolbar, view, shown, focus_return):
        super().__init__()
        self.selection = Selection()
        self._header_bar = header_bar
        self._view = view
        self._shown = weak_method(shown)
        self._focus_return = weak_method(focus_return)
        self._header_title = None  # the page's HeaderTitle, held while the mode is on
        self._filter_bar = None  # the page's FilterBar, whose button the mode leaves out
        self._playlist = None  # the playlist of the user's the list shows (Remove from Playlist)
        self._favourites = False  # the list is Favourite Songs (Remove from Favourites)
        self._library = False  # the list may hold the library's songs (Remove from Library)
        self._narrow = False
        self._available = False  # the list has tracks: Select offered
        connect_weak(self.selection, 'changed', self._on_changed)

        self.select_button = Gtk.Button(icon_name='selection-mode-symbolic',
                                        tooltip_text=_('Select'), visible=False)
        self.select_button.update_property([Gtk.AccessibleProperty.LABEL], [_('Select')])
        connect_weak(self.select_button, 'clicked', self._on_select_clicked)
        self.cancel_button = Gtk.Button(label=_('_Cancel'), use_underline=True, visible=False)
        connect_weak(self.cancel_button, 'clicked', self._on_cancel_clicked)

        menu = Gio.Menu()
        menu.append(_('Select _All'), 'selection.select-all')
        menu.append(_('Select _None'), 'selection.select-none')
        # The count ("3 Selected", or "Select Songs" for none yet), as the header bar's title:
        # a label that ellipsizes, so a long translation still fits beside Cancel at 360 px.
        self._title_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END)
        self._title_label.add_css_class('title')
        self.title_button = Gtk.MenuButton(menu_model=menu, always_show_arrow=True,
                                           child=self._title_label, css_classes=['flat'])

        self.actions = Gio.SimpleActionGroup()
        self._actions = {}
        for name, handler, parameter in (
                ('select-all', self._on_select_all, None),
                ('select-none', self._on_select_none, None),
                ('play-next', self._on_play_next, None),
                ('play-later', self._on_play_later, None),
                ('add-to-playlist', self._on_add_to_playlist, GLib.VariantType.new('s')),
                ('new-playlist', self._on_new_playlist, None),
                ('remove-from-playlist', self._on_remove_from_playlist, None),
                ('remove-from-favourites', self._on_remove_from_favourites, None),
                ('remove-from-library', self._on_remove_from_library, None)):
            action = Gio.SimpleAction.new(name, parameter)
            connect_weak(action, 'activate', handler)
            self.actions.add_action(action)
            self._actions[name] = action
        page.insert_action_group('selection', self.actions)

        self.bar = Gtk.ActionBar(revealed=False)
        self._play_next = Gtk.Button(label=_('Play _Next'), use_underline=True,
                                     action_name='selection.play-next')
        self._play_later = Gtk.Button(label=_('Play _Later'), use_underline=True,
                                      action_name='selection.play-later')
        # Raised as the bar's text buttons are (an action bar's menu buttons are flat).
        self._add = Gtk.MenuButton(label=_('Add to Pla_ylist'), use_underline=True,
                                   always_show_arrow=True, css_classes=['raised'])
        self._add.set_create_popup_func(weak_method(self._on_add_popup))
        self._remove_playlist = Gtk.Button(label=_('_Remove from Playlist'), use_underline=True,
                                           action_name='selection.remove-from-playlist',
                                           css_classes=['destructive-action'], visible=False)
        self._remove_favourites = Gtk.Button(label=_('_Remove from Favourites'),
                                             use_underline=True,
                                             action_name='selection.remove-from-favourites',
                                             css_classes=['destructive-action'], visible=False)
        self._remove_library = Gtk.Button(label=_('Remove from Li_brary…'), use_underline=True,
                                          action_name='selection.remove-from-library',
                                          visible=False)
        self._more = Gtk.MenuButton(icon_name='view-more-symbolic', tooltip_text=_('More'),
                                    visible=False)
        self._more.update_property([Gtk.AccessibleProperty.LABEL], [_('More')])
        self._more.set_create_popup_func(weak_method(self._on_more_popup))
        for button in (self._play_next, self._play_later, self._add):
            self.bar.pack_start(button)
        for button in (self._more, self._remove_library, self._remove_playlist,
                       self._remove_favourites):
            self.bar.pack_end(button)
        toolbar.add_bottom_bar(self.bar)
        self._update_actions()

    # -- what the page tells it --------------------------------------------------------------

    @property
    def title(self):
        """What the header bar's title says in the mode."""
        return self._title_label.get_label()

    @property
    def active(self):
        return self.selection.active

    def set_header_title(self, header_title):
        """The page's widgets.util.HeaderTitle: held (the title shown) while in the mode."""
        self._header_title = header_title

    def set_filter_bar(self, filter_bar):
        """The page's widgets.filter_bar.FilterBar: its button is left out of the header bar
        while in the mode (Cancel takes the room)."""
        self._filter_bar = filter_bar

    def set_available(self, available):
        """Offer the mode (Select shown) while the list has tracks; none leaves it."""
        self._available = bool(available)
        self.select_button.set_visible(self._available and not self.active)
        if not available:
            self.leave()

    def set_context(self, playlist=None, library=False, favourites=False):
        """What the bar offers: Remove from Playlist for `playlist` (the user's playlist the
        list shows, or None), Remove from Favourites in its place when the list is Favourite
        Songs (`favourites`), Remove from Library… when the list may hold the library's songs
        (`library`)."""
        self._playlist = playlist
        self._favourites = bool(favourites) and playlist is None
        self._library = bool(library)
        self._update_bar()

    def set_narrow(self, narrow):
        """The bar's narrow layout (360 px wide): Play Next and Add to Playlist, the rest in
        a More menu."""
        self._narrow = bool(narrow)
        self._update_bar()

    def selectable(self):
        """The tracks the list shows, in order."""
        return list(self._shown() or ())

    def prune(self):
        """The list changed (a filter, a sync): only what it still shows stays selected."""
        if self.active:
            self.selection.keep(self._shown() or ())

    # -- entering, leaving -------------------------------------------------------------------

    def start(self):
        """Enter the mode, nothing selected."""
        self.selection.start()

    def leave(self):
        """Leave the mode, the selection cleared; the focus back on the list when it was on
        the mode's own widgets, which hide."""
        if not self.active:
            return
        root = self._view.get_root()
        focus = root.get_focus() if root is not None else None
        anchor = self.selection.ordered(self._shown() or ())[:1]
        in_list = focus is not None and (focus is self._view or focus.is_ancestor(self._view))
        self.selection.stop()
        if not in_list and focus is not None and (
                focus.is_ancestor(self.bar) or focus.is_ancestor(self._header_bar)):
            self._focus_return(anchor[0] if anchor else None)

    def activated(self, track):
        """The list's activate for track (a click, Enter): True when the mode took it (a
        toggle, a Shift range, or a Ctrl+click or Shift+click that enters the mode); False,
        and the page plays the song, for a plain one outside the mode."""
        modifiers = dnd.modifiers(self._view)
        shift = bool(modifiers & Gdk.ModifierType.SHIFT_MASK)
        control = bool(modifiers & Gdk.ModifierType.CONTROL_MASK)
        if not self.active and not (shift or control):
            return False
        if shift:
            self.selection.extend(self._shown() or (), track)
        else:
            self.selection.toggle(track)
        return True

    def key(self, name, track=None):
        """A key keyboard.selection_key() named: 'toggle' or 'extend' the focused row's
        `track`, 'select-all', 'select-none' or 'leave'. True when it was taken."""
        if name == 'leave':
            if not self.active:
                return False
            self.leave()
            return True
        if name == 'select-all':
            self._select_all()
            return True
        if name == 'select-none':
            self.selection.select_none()
            return self.active
        if track is None:
            return False
        if name == 'extend':
            self.selection.extend(self._shown() or (), track)
        else:
            self.selection.toggle(track)
        return True

    def drag_objects(self, obj):
        """What a drag of obj's row carries in the mode: the whole selection, in the order
        shown, when obj is in it; None (obj alone) otherwise."""
        if not self.active or not self.selection.has(obj):
            return None
        return self.selection.ordered(self._shown() or ())

    # -- the selection's changes -------------------------------------------------------------

    def _on_changed(self, selection):
        active = selection.active
        self.select_button.set_visible(not active and self._available)
        self.cancel_button.set_visible(active)
        self.bar.set_revealed(active)
        self._header_bar.set_show_back_button(not active)
        if self._filter_bar is not None:
            self._filter_bar.hide_button(active)
        track_links.set_inert(self._view, active)
        if self._header_title is not None:
            self._header_title.hold(active)
        if active:
            self._title_label.set_label(count_title(selection.count))
            if self._header_bar.get_title_widget() is not self.title_button:
                self._header_bar.set_title_widget(self.title_button)
        elif self._header_bar.get_title_widget() is self.title_button:
            self._header_bar.set_title_widget(None)
        self._update_actions()
        if active:
            self._announce(count_title(selection.count) if selection.count
                           else _('Selection mode'))

    def _announce(self, text):
        root = self._view.get_root()
        announce = getattr(root, 'announce', None)
        if announce is not None and self._view.get_mapped():
            announce(text, Gtk.AccessibleAnnouncementPriority.MEDIUM)

    def _update_actions(self):
        some = self.selection.count > 0
        for name in ('play-next', 'play-later', 'add-to-playlist', 'new-playlist',
                     'remove-from-library', 'select-none'):
            self._actions[name].set_enabled(some)
        self._actions['remove-from-playlist'].set_enabled(some and self._playlist is not None)
        self._actions['remove-from-favourites'].set_enabled(some and self._favourites)
        self._actions['select-all'].set_enabled(self.active)
        self._add.set_sensitive(some)
        self._more.set_sensitive(some)

    def _layout(self):
        """(the bar's buttons shown, the More menu's entries) as (action, label) pairs: Play
        Next and Add to Playlist always; Play Later, Remove from Playlist (or Remove from
        Favourites) and Remove from Library… on the bar where there is room (not `narrow`;
        Remove from Library… there only without one of the others beside it), else in
        More."""
        later = ('selection.play-later', _('Play _Later'))
        from_library = ('selection.remove-from-library', _('Remove from Li_brary…'))
        if self._playlist is not None:
            first = [('selection.remove-from-playlist', _('_Remove from Playlist'))]
        elif self._favourites:
            first = [('selection.remove-from-favourites', _('_Remove from Favourites'))]
        else:
            first = []
        removals = first + ([from_library] if self._library else [])
        if self._narrow:
            return [], [later, *removals]
        if first:
            return [later, *first], removals[1:]
        return [later, *removals], []

    def _update_bar(self):
        shown, _more = self._layout()
        names = {action for action, _label in shown}
        self._play_later.set_visible('selection.play-later' in names)
        self._remove_playlist.set_visible('selection.remove-from-playlist' in names)
        self._remove_favourites.set_visible('selection.remove-from-favourites' in names)
        self._remove_library.set_visible('selection.remove-from-library' in names)
        self._more.set_visible(bool(_more))
        self._update_actions()

    # -- the header bar and the bar ----------------------------------------------------------

    def _on_select_clicked(self, _button):
        self.start()
        self._view.grab_focus()

    def _on_cancel_clicked(self, _button):
        self.leave()

    def _select_all(self):
        self.selection.select_all(self._shown() or ())

    def _on_select_all(self, _action, _parameter):
        self._select_all()

    def _on_select_none(self, _action, _parameter):
        self.selection.select_none()

    def _chosen(self):
        """The selected tracks in the order shown, and the window's item actions; the mode
        left (an action of the bar ends it, its toast saying what happened)."""
        tracks = self.selection.ordered(self._shown() or ())
        actions = getattr(self._view.get_root(), 'item_actions', None)
        self.leave()
        return tracks, actions

    def _on_play_next(self, _action, _parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.queue_objects(tracks, later=False)

    def _on_play_later(self, _action, _parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.queue_objects(tracks, later=True)

    def _on_add_to_playlist(self, _action, parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.add_items_to_playlist(parameter.get_string(), tracks)

    def _on_new_playlist(self, _action, _parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.new_playlist_of(tracks)

    def _on_remove_from_playlist(self, _action, _parameter):
        playlist = self._playlist
        tracks, actions = self._chosen()
        if tracks and actions is not None and playlist is not None:
            actions.remove_entries(playlist, tracks)

    def _on_remove_from_favourites(self, _action, _parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.remove_favourites(tracks)

    def _on_remove_from_library(self, _action, _parameter):
        tracks, actions = self._chosen()
        if tracks and actions is not None:
            actions.ask_remove_from_library(tracks)

    def _playlist_menu(self):
        """Add to Playlist's menu, made as it opens: the library's playlists that take songs
        (not the one shown), each folder's in a section, then New Playlist…."""
        from ..actions import playlist_submenu
        actions = getattr(self._view.get_root(), 'item_actions', None)
        menu = Gio.Menu()
        playlists = getattr(actions, 'playlists', None)
        if playlists is not None:
            named = ('playlist', self._playlist.id) if self._playlist is not None else None
            listed = playlist_submenu(playlists(), named,
                                      action='selection.add-to-playlist')
            if listed.get_n_items():
                menu.append_section(None, listed)
        created = Gio.Menu()
        created.append(_('Ne_w Playlist…'), 'selection.new-playlist')
        menu.append_section(None, created)
        return menu

    def _on_add_popup(self, button):
        button.set_menu_model(self._playlist_menu())

    def _on_more_popup(self, button):
        menu = Gio.Menu()
        for action, label in self._layout()[1]:
            menu.append(label, action)
        button.set_menu_model(menu)
