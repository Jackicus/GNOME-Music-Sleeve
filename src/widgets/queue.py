# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicQueueView: the Now Playing sheet's Up Next tab, the Player's queue from the
entry playing on, with its edits.

A Gtk.ListView over a Gtk.SliceListModel of player.queue (a Gio.ListStore of NowPlaying)
that starts at the entry playing (slice_offset) and runs to the queue's end (slice_size), so
a row at list position p is the queue's entry at the slice's offset plus p
(queue_index_at()). The slice is given two sections by QueueSections (a GtkSectionModel): the
entry playing and what the user queued after it, then, from the first entry autoplay added
(NowPlaying.autoplay), the rest of the queue under an "Autoplay" header (the header-factory
titles the second); the split (section_bounds()) is found again with every change of the
queue or of the entry playing, the rows left as they are. The entry playing comes first,
marked with a play icon in place of its number and a bold title. Rows are like a
playlist's track rows (a number, the title with its explicit badge, the artist, the
duration). Activating a row (a double click, or Enter) plays that entry
(player.queue_jump). A right click, a long press or the Menu key opens a row's menu
(widgets/context_menu.py: the entry's, without Play, with Remove from Up Next on an entry after
the one playing while the queue may be edited: its context_queue_entry); Delete
(shortcuts.QUEUE_REMOVE) on a focused row does the same, and the focus then goes to the row
that took its place (or the one before, at the end). Above the list, Autoplay (a toggle of
the `autoplay` setting; insensitive while MusicKit allows none, or repeat is on, when it
would not start) and Clear (everything after the entry playing, with an Undo toast:
app.undo-clear-up-next). An empty queue shows a compact status page. The list is named "Up
Next" for assistive technology, each row by labels.track_label, described as playing or as
autoplay's.
"""

from gettext import gettext as _
from gettext import pgettext as C_

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango

from .. import shortcuts
from ..actions import now_playing_track
from ..player import format_time
from . import context_menu
from .labels import track_label

# The keys that remove the focused row's entry: the shortcut's, and the keypad's.
REMOVE_KEYS = f'{shortcuts.QUEUE_REMOVE}|KP_Delete'


def slice_offset(queue_index):
    """Where the Up Next slice of the queue starts: the entry playing, or the top when
    nothing is (queue_index -1)."""
    return max(queue_index, 0)


def slice_size(offset):
    """The Up Next slice's size from `offset`: the rest of the queue, however long it gets.
    Not GLib.MAXUINT: a Gtk.SliceListModel whose offset plus size passes G_MAXUINT wraps its
    end and ignores the queue's changes after it (a new queue, entries added at its end)."""
    return GLib.MAXUINT32 - offset


def section_bounds(entries, queue_index):
    """(offset, split) of Up Next's two sections in `entries` (a sequence of NowPlaying), as
    queue indices: the first from `offset` (the entry playing, or the top) up to `split`,
    the first entry after the one playing that autoplay added (or the end); the second, the
    Autoplay section, from `split` on."""
    offset = slice_offset(queue_index)
    count = len(entries)
    for position in range(offset + (1 if queue_index >= 0 else 0), count):
        if entries[position].autoplay:
            return offset, position
    return offset, max(offset, count)


class _Entries:
    """A Gio.ListModel read as a sequence (section_bounds())."""

    def __init__(self, model):
        self._model = model

    def __len__(self):
        return self._model.get_n_items()

    def __getitem__(self, position):
        return self._model.get_item(position)


class QueueSections(GObject.Object, Gio.ListModel, Gtk.SectionModel):
    """A list model of NowPlaying (Up Next's slice of the queue, passed through as it is, its
    changes too) in two sections: before `split` and from it on (set_split(), which tells the
    list its headers changed). Two slices in a Gtk.FlattenListModel would give the sections
    too, but every move of their common bound would take rows out of one and put them into
    the other, building them again, and lose the list's focus."""

    __gtype_name__ = 'AppleMusicQueueSections'

    def __init__(self, model):
        super().__init__()
        self._model = model
        self._split = 0
        model.connect('items-changed',
                      lambda _model, position, removed, added: self.items_changed(
                          position, removed, added))

    @property
    def split(self):
        return self._split

    def set_split(self, split):
        if split != self._split:
            self._split = split
            count = self.get_n_items()
            if count:
                self.sections_changed(0, count)

    def do_get_item_type(self):
        return self._model.get_item_type()

    def do_get_n_items(self):
        return self._model.get_n_items()

    def do_get_item(self, position):
        return self._model.get_item(position)

    def do_get_section(self, position):
        count = self._model.get_n_items()
        if position >= count:
            return count, GLib.MAXUINT32
        if position < self._split:
            return 0, min(self._split, count)
        return min(self._split, count), count


class QueueRow(Gtk.Box):
    """One queue entry: number or play icon, title (and its explicit badge) and artist,
    duration. The entry, as a Track, is its `context_item` (its menu: context_menu), and
    `context_queue_entry` its (index, id) in the queue while Up Next may take it out."""

    # The entry's menu is a queued one: no Play (activating the row plays it).
    context_queued = True

    def __init__(self, view):
        super().__init__(spacing=12)
        self.view = view  # the QueueView, as long-lived as the row
        self.list_item = None  # the Gtk.ListItem bound (its accessible description)
        self._entry = None  # the NowPlaying bound
        self.number_label = Gtk.Inscription(min_chars=2, nat_chars=2, xalign=1,
                                            valign=Gtk.Align.CENTER)
        self.number_label.add_css_class('numeric')
        self.number_label.add_css_class('dimmed')
        self.playing_icon = Gtk.Image(icon_name='media-playback-start-symbolic',
                                      valign=Gtk.Align.CENTER, visible=False,
                                      accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.playing_icon.add_css_class('accent')
        marker = Gtk.Stack(hhomogeneous=True, valign=Gtk.Align.CENTER)
        marker.add_named(self.number_label, 'number')
        marker.add_named(self.playing_icon, 'playing')
        self._marker = marker
        self.append(marker)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                         hexpand=True)
        title_line = Gtk.Box(spacing=6)
        self.title_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                     single_line_mode=True)
        self.title_label.add_css_class('queue-title')
        # The badge marking a song with explicit lyrics, as the track rows show it; the
        # row's accessible name says "explicit" (track_label), so the badge is decoration.
        self.explicit_badge = Gtk.Label(
            # Translators: the badge marking a song with explicit lyrics, as Apple Music shows it
            label=C_('explicit badge', 'E'), tooltip_text=_('Explicit'), visible=False,
            valign=Gtk.Align.CENTER, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.explicit_badge.add_css_class('caption')
        self.explicit_badge.add_css_class('explicit-badge')
        title_line.append(self.title_label)
        title_line.append(self.explicit_badge)
        self.artist_label = Gtk.Inscription(xalign=0,
                                            text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END,
                                            visible=False)
        self.artist_label.add_css_class('caption')
        self.artist_label.add_css_class('dimmed')
        titles.append(title_line)
        titles.append(self.artist_label)
        self.append(titles)

        self.duration_label = Gtk.Inscription(min_chars=5, nat_chars=5, xalign=1,
                                              valign=Gtk.Align.CENTER)
        self.duration_label.add_css_class('numeric')
        self.duration_label.add_css_class('dimmed')
        self.append(self.duration_label)

    @property
    def entry(self):
        return self._entry

    @property
    def context_item(self):
        """The entry bound, as the Track its menu is for (actions.now_playing_track)."""
        return now_playing_track(self._entry)

    @property
    def context_queue_entry(self):
        """(queue index, id) of the entry bound while Up Next may take it out, else None."""
        if self._entry is None or self.list_item is None:
            return None
        return self.view.removable(self.list_item.get_position(), self._entry)

    def bind(self, entry, position, current):
        self._entry = entry
        self.number_label.set_text(str(position + 1))
        self.title_label.set_label(entry.title or _('Unknown Title'))
        self.explicit_badge.set_visible(entry.explicit)
        self.artist_label.set_text(entry.artist)
        self.artist_label.set_visible(bool(entry.artist))
        self.duration_label.set_text(
            format_time(entry.duration_ms / 1000) if entry.duration_ms else '')
        self.set_current(current)

    def unbind(self):
        self._entry = None

    def set_number(self, position):
        self.number_label.set_text(str(position + 1))

    def set_current(self, current):
        self.playing_icon.set_visible(current)  # a stack shows only a visible child
        self._marker.set_visible_child_name('playing' if current else 'number')
        if current:
            self.add_css_class('current')
        else:
            self.remove_css_class('current')


class QueueView(Gtk.Stack):
    """The Up Next tab. See the module."""

    __gtype_name__ = 'AppleMusicQueueView'

    def __init__(self):
        super().__init__(vhomogeneous=True, hhomogeneous=True,
                         transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._player = None
        self._app = None
        self._active = False
        self._rows = set()  # the QueueRows bound
        self._slice = None  # the queue from the entry playing on
        self.model = None  # the slice in its two sections (QueueSections)
        self._refocus = None  # the list position to focus once a removal is in
        # Looked up once: rows are bound often.
        self._playing = _('Playing')
        self._autoplay_title = _('Autoplay')

        self.empty_page = Adw.StatusPage(icon_name='playlist-symbolic', title=_('Nothing Queued'),
                                         description=_('Play something to fill Up Next'))
        self.empty_page.add_css_class('compact')
        self.add_named(self.empty_page, 'empty')

        # Above the list: Autoplay and Clear, at its end.
        self.autoplay_button = Gtk.ToggleButton(icon_name='autoplay-symbolic',
                                                tooltip_text=self._autoplay_title,
                                                valign=Gtk.Align.CENTER)
        self.autoplay_button.add_css_class('flat')
        self.autoplay_button.add_css_class('circular')
        self.clear_button = Gtk.Button(label=_('Clear'), valign=Gtk.Align.CENTER,
                                       tooltip_text=_('Remove Everything After the Song Playing'))
        self.clear_button.add_css_class('flat')
        self.clear_button.connect('clicked', lambda _button: self._on_clear())
        tools = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        tools.add_css_class('queue-tools')
        tools.append(self.autoplay_button)
        tools.append(self.clear_button)

        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._on_setup)
        factory.connect('bind', self._on_bind)
        factory.connect('unbind', self._on_unbind)
        headers = Gtk.SignalListItemFactory()
        headers.connect('setup', self._on_header_setup)
        headers.connect('bind', self._on_header_bind)
        # Tab leaves the list after the entry with the focus; the arrows move between them.
        self.list_view = Gtk.ListView(factory=factory, header_factory=headers,
                                      model=Gtk.NoSelection(),
                                      tab_behavior=Gtk.ListTabBehavior.ITEM)
        self.list_view.add_css_class('queue-list')
        self.list_view.update_property([Gtk.AccessibleProperty.LABEL], [_('Up Next')])
        self.list_view.connect('activate', self._on_activate)
        context_menu.attach(self.list_view)
        keys = Gtk.ShortcutController()
        keys.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(REMOVE_KEYS),
                                           Gtk.CallbackAction.new(self._on_remove_key)))
        self.list_view.add_controller(keys)
        self.scrolled = Gtk.ScrolledWindow(child=self.list_view,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           vexpand=True)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(tools)
        page.append(self.scrolled)
        self.add_named(page, 'list')

    def set_player(self, player, app):
        self._player = player
        self._app = app
        queue = player.queue
        # The slice first: it follows the queue's changes before _on_items_changed moves
        # the sections' split.
        self._slice = Gtk.SliceListModel(model=queue, offset=0, size=slice_size(0))
        self.model = QueueSections(self._slice)
        self.model.connect('items-changed', self._on_rows_changed)
        self.list_view.set_model(Gtk.NoSelection(model=self.model))
        queue.connect('items-changed', lambda *_: self._on_items_changed())
        player.connect('notify::queue-index', lambda *_: self._on_index())
        for name in ('queue-editable', 'can-autoplay', 'repeat'):
            player.connect('notify::' + name, lambda *_: self._update_tools())
        app.settings.bind('autoplay', self.autoplay_button, 'active',
                          Gio.SettingsBindFlags.DEFAULT)
        self._on_index()
        self._update_page()

    def set_active(self, active):
        """Scroll to the entry playing when shown."""
        self._active = active
        if active:
            self._scroll_to_current()

    # -- the slice and its sections -------------------------------------------------------

    def queue_index_at(self, position):
        """The queue index of the row at list `position`."""
        return self._slice.get_offset() + position

    def removable(self, position, entry):
        """(queue index, id) of `entry`, the row at list `position`, when Up Next may take
        it out (Player.can_edit), else None."""
        if self._player is None:
            return None
        index = self.queue_index_at(position)
        if not self._player.can_edit(index, entry.id):
            return None
        return index, entry.id

    def _update_bounds(self):
        """The slice from the entry playing on, and where its Autoplay section begins."""
        offset, split = section_bounds(_Entries(self._player.queue), self._player.queue_index)
        _set_slice(self._slice, offset, slice_size(offset))
        self.model.set_split(split - offset)

    def _update_page(self):
        self.set_visible_child_name('list' if self._player.queue.get_n_items() else 'empty')

    def _update_tools(self):
        player = self._player
        self.clear_button.set_sensitive(player.can_clear())
        if not player.can_autoplay:
            tooltip = _('Autoplay Is Not Available Here')
        elif player.repeat != 'none':
            tooltip = _('Autoplay Is Off While Repeat Is On')
        else:
            tooltip = self._autoplay_title
        self.autoplay_button.set_sensitive(player.can_autoplay and player.repeat == 'none')
        self.autoplay_button.set_tooltip_text(tooltip)

    def _on_items_changed(self):
        """The queue changed: the slice and its sections, the page, the tools, and the entry playing
        on top (a new queue with the same index number fires no index notify)."""
        self._update_bounds()
        self._update_page()
        self._update_tools()
        self._refresh_rows()
        if self._active and self._refocus is None:
            self._scroll_to_current()

    def _on_index(self):
        """The entry playing changed: the slice starts there, and the rows show it."""
        self._update_bounds()
        self._update_tools()
        self._refresh_rows()
        if self._active:
            self._scroll_to_current()

    def _refresh_rows(self):
        """The rows bound, numbered and marked by where they are now (a row that moves is
        not always bound again)."""
        for row in self._rows:
            if row.list_item is not None and row.entry is not None:
                self._show(row, row.list_item.get_position())

    def _show(self, row, position):
        current = position == 0 and self._player.queue_index >= 0
        row.set_number(position)
        row.set_current(current)
        self._describe(row, current)

    def _scroll_to_current(self):
        if (self._player is not None and self._player.queue_index >= 0
                and self.model.get_n_items()):
            self.list_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)

    # -- rows --------------------------------------------------------------------------------

    def _on_setup(self, _factory, list_item):
        row = QueueRow(self)
        row.list_item = list_item
        list_item.set_child(row)

    def _on_bind(self, _factory, list_item):
        position = list_item.get_position()
        row = list_item.get_child()
        self._rows.add(row)
        entry = list_item.get_item()
        current = position == 0 and self._player.queue_index >= 0
        row.bind(entry, position, current)
        list_item.set_accessible_label(track_label(entry, show_artist=True, show_album=False))
        self._describe(row, current)

    def _describe(self, row, current):
        """The entry playing is described as such (its play icon is decoration), and one
        autoplay added as autoplay's (the section's header is not reached by the keys)."""
        entry = row.entry
        description = (self._playing if current
                       else self._autoplay_title if entry is not None and entry.autoplay else '')
        row.list_item.set_accessible_description(description)

    def _on_unbind(self, _factory, list_item):
        row = list_item.get_child()
        row.unbind()
        self._rows.discard(row)

    def _on_header_setup(self, _factory, header):
        label = Gtk.Label(label=self._autoplay_title, xalign=0, visible=False)
        label.add_css_class('heading')
        label.add_css_class('queue-section')
        header.set_child(label)

    def _on_header_bind(self, _factory, header):
        """The Autoplay section's header names it; the first section's shows nothing."""
        entry = header.get_item()
        header.get_child().set_visible(header.get_start() > 0 and entry is not None
                                       and entry.autoplay)

    def _on_activate(self, _list_view, position):
        if self._player is None:
            return
        self._app.player_command(self._player.queue_jump(self.queue_index_at(position)))

    # -- the edits ---------------------------------------------------------------------------

    def _on_remove_key(self, _view, _arguments):
        """Delete on a focused row: its Remove from Up Next, when it has one."""
        root = self.list_view.get_root()
        focus = root.get_focus() if root is not None else None
        found = context_menu.find(self.list_view, focus) if focus is not None else None
        if found is None:
            return False
        row, _obj = found
        entry = getattr(row, 'context_queue_entry', None)
        if entry is None:
            return True  # the entry playing, or a queue that cannot be changed: nothing
        self._refocus = row.list_item.get_position()
        self.list_view.activate_action('win.item-remove-from-queue',
                                       GLib.Variant('(is)', entry))
        return True

    def _on_rows_changed(self, model, position, removed, added):
        """A row taken out while it had the focus (Delete, or its menu's Remove): the focus
        goes to the row that took its place, or the one before at the end, once the list
        has caught up."""
        if removed > added and (self._refocus is not None or self._lost_focus()):
            self._refocus = position if self._refocus is None else self._refocus
            GLib.idle_add(self._focus_again)

    def _lost_focus(self):
        """Whether the focus has fallen out of a row of the list into the list itself (or a
        row's widget no longer shown), as when the row it was on is taken out."""
        root = self.list_view.get_root()
        focus = root.get_focus() if root is not None else None
        if focus is None:
            return False
        if focus is self.list_view:
            return True
        return focus.is_ancestor(self.list_view) and not focus.get_mapped()

    def _focus_again(self):
        position, self._refocus = self._refocus, None
        count = self.model.get_n_items() if self.model is not None else 0
        if position is not None and count:
            self.list_view.scroll_to(min(position, count - 1), Gtk.ListScrollFlags.FOCUS,
                                     None)
        return GLib.SOURCE_REMOVE

    def _on_clear(self):
        if self._player is not None:
            self._app.player_command(self._clear())

    async def _clear(self):
        """Clear, then the toast that can undo it."""
        if await self._player.clear_up_next():
            self._app.toast(_('Up Next cleared'), _('Undo'), 'app.undo-clear-up-next')


def _set_slice(model, offset, size):
    """A slice's offset and size, the smaller size first, so that offset plus size never
    passes G_MAXUINT on the way (slice_size())."""
    if model.get_offset() == offset and model.get_size() == size:
        return
    if size < model.get_size():
        model.set_size(size)
        model.set_offset(offset)
    else:
        model.set_offset(offset)
        model.set_size(size)
