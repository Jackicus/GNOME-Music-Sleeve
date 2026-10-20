# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicQueueView: the Now Playing sheet's Up Next tab, the Player's queue from the
entry playing on, with its edits, and the History of what played before it.

Up Next is a Gtk.ListView over a Gtk.SliceListModel of player.queue (a Gio.ListStore of
NowPlaying) that starts at the entry playing (slice_offset) and runs to the queue's end
(slice_size), so a row at list position p is the queue's entry at the slice's offset plus p
(queue_index_at()). The slice is given up to three sections by QueueSections (a
GtkSectionModel): the entry playing; what the user queued after it, under a "Playing Next"
header; and, from the first entry autoplay added (NowPlaying.autoplay), the rest of the queue
under an "Autoplay" header (the header-factory titles them); the bounds (section_bounds())
are found again with every change of the queue or of the entry playing, the rows left as
they are, and the headers bound are titled again then: whether the first section is the
entry playing's changes with the entry playing alone (a queue of one, spliced in before its
index is set), and the list binds a header again only when its section moves. Each row
shows the entry's cover (EntryArt finds it), its title (with the explicit badge), its
artist and its duration; the entry playing has a play symbol over its cover and
a bold title. Activating a row (a double click, or Enter) plays that entry
(player.queue_jump). A right click, a long press or the Menu key opens a row's menu
(widgets/context_menu.py: the entry's, without Play, with Remove from Up Next on an entry after
the one playing while the queue may be edited: its context_queue_entry); Delete
(shortcuts.QUEUE_REMOVE) on a focused row does the same, and the focus then goes to the row
that took its place (or the one before, at the end). An entry after the one playing moves
within its section (Playing Next, or Autoplay: Player.move_range()): Move Up and Move Down in
its menu (its context_queue_moves), Alt+Up and Alt+Down on its row (keyboard.move_step(), as
on a playlist's page; the focus goes with it), or dragged (dnd.attach_source(), MOVE only, a
mouse's drag: a touchscreen's scrolls) and dropped in its section, where an insertion line
shows the place (dnd.DropFeedback, the list scrolling near its edges; drop_place()). Each goes
through win.item-move-in-queue, which announces where it went; the list keeps its scroll (Up
Next does not go back to the entry playing as it does for other changes) and, when the focus
was on the entry, moves it with the entry (Player.moving names it as the move starts).
Above the list, History (a toggle) at
the start, and at the end Autoplay (a toggle of the `autoplay` setting; insensitive while
MusicKit allows none, or repeat is on, when it would not start) and Clear (everything after
the entry playing, with an Undo toast: app.undo-clear-up-next; the focus on it goes to the
entry playing as it goes insensitive). An empty queue shows a compact
status page. The list is named "Up Next" for assistive technology, each row by
labels.track_label, described as playing or as autoplay's.

History shows, in place of Up Next while its toggle is on, the queue's entries before the one
playing (MusicKit's queue keeps them), the most recent first: a second Gtk.ListView over a
HistoryModel, brought up to date (one splice of what differs) only while it shows; activating
a row plays that entry again. Its rows are Up Next's, without Remove. The toggle goes off when
the tab is left. Autoplay and Clear, Up Next's, are hidden meanwhile.

Covers: the bridge gives each entry an artwork URL. EntryArt finds the file for each, once per
URL, on disk (fetch_remote's thumbnail, the library's own thumbnail for the same artwork, or
the cover the bar fetched) in a thread, and fetches the thumbnail of what is not there yet,
a few at a time (never in the demo); it looks only at the URLs of rows still bound, at most
every ART_DELAY_MS, so a fast scroll through a long queue asks for nothing it has passed. A
row binds with the path known for its URL (a dictionary lookup) and its Cover decodes it as
any row's does (artwork.ArtworkSlot: on map, after the frame, let go of on unmap). What it
found is forgotten when the cache is cleared (Clear Cache, a sign-out: the cache's generation
moves), and a look under way then is dropped: the files are looked for again.
"""

import asyncio
from gettext import gettext as _
from gettext import pgettext as C_

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk, Pango

from .. import keyboard, shortcuts
from ..actions import now_playing_track
from ..backend import config, normalize, store
from ..library import ItemRefs, drop_index
from ..player import NowPlaying, format_time
from ..remote import fetch_remote, on_disk, remote_art_path, sized_url
from . import context_menu, dnd
from .labels import track_label
from .util import focus_position, weak_method

# The keys that remove the focused row's entry: the shortcut's, and the keypad's.
REMOVE_KEYS = f'{shortcuts.QUEUE_REMOVE}|KP_Delete'
# A row's cover, in px.
ART_SIZE = 40
# How often at most EntryArt looks for the covers the rows bound since its last look need,
# and how many thumbnails it fetches at once.
ART_DELAY_MS = 100
ART_FETCHES = 4


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
    """(offset, first, split) of Up Next's sections in `entries` (a sequence of NowPlaying),
    as queue indices: the slice from `offset` (the entry playing, or the top); the entry
    playing alone, up to `first` (offset itself when nothing plays); Playing Next, from
    `first` up to `split`, the first entry after the one playing that autoplay added (or the
    end); the Autoplay section from `split` on."""
    offset = slice_offset(queue_index)
    count = len(entries)
    first = min(offset + 1, count) if queue_index >= 0 else offset
    first = max(first, offset)
    for position in range(first, count):
        if entries[position].autoplay:
            return offset, first, position
    return offset, first, max(first, count)


def section_at(position, count, bounds):
    """(start, end) of the section holding list `position` of `count` items, the sections
    divided at `bounds` (list positions, in order; those at 0 or past the end divide
    nothing)."""
    start = 0
    for bound in bounds:
        if bound >= count:
            break
        if position < bound:
            return start, bound
        start = max(start, bound)
    return start, count


def drop_gap(gap, bounds):
    """The gap a drop at `gap` (a queue index: before the entry there) goes to for an entry
    whose section spans the queue indices `bounds` (first, last: Player.move_range()): the
    nearest of the section's own gaps, from before its first entry to after its last."""
    first, last = bounds
    return min(max(gap, first), last + 1)


def line_place(gap, bounds):
    """Where the insertion line for a drop in `gap` (drop_gap()'s) is drawn, inside the
    section spanning `bounds`: (queue index, after), on the top edge of the entry at `gap`,
    or on the bottom edge of the section's last one for the gap after it (never on the entry
    playing above the section, or on the next section's first entry under its header)."""
    _first, last = bounds
    return (gap, False) if gap <= last else (last, True)


def history_entries(queue, queue_index):
    """The entries of `queue` (a Gio.ListModel) before the one at `queue_index`, the most
    recent first: History's."""
    return [queue.get_item(index) for index in range(min(queue_index, queue.get_n_items()) - 1,
                                                     -1, -1)]


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
    changes too) in sections divided at `bounds` (set_bounds(), which tells the list its
    headers changed). Two slices in a Gtk.FlattenListModel would give the sections too, but
    every move of their common bound would take rows out of one and put them into the other,
    building them again, and lose the list's focus."""

    __gtype_name__ = 'AppleMusicQueueSections'

    def __init__(self, model):
        super().__init__()
        self._model = model
        self._bounds = ()
        model.connect('items-changed',
                      lambda _model, position, removed, added: self.items_changed(
                          position, removed, added))

    @property
    def bounds(self):
        return self._bounds

    def set_bounds(self, *bounds):
        """Divide the items at these list positions (in order)."""
        if bounds != self._bounds:
            self._bounds = bounds
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
        return section_at(position, count, self._bounds)


class HistoryModel(GObject.Object, Gio.ListModel):
    """History's entries (NowPlaying), the most recent first, as update() last gave them,
    changed by one splice of what differs (the entries alike at the start and the end, by
    identity): the next entry playing adds one row at the top."""

    __gtype_name__ = 'AppleMusicHistoryModel'

    def __init__(self):
        super().__init__()
        self._items = []

    def do_get_item_type(self):
        return NowPlaying

    def do_get_n_items(self):
        return len(self._items)

    def do_get_item(self, position):
        return self._items[position] if 0 <= position < len(self._items) else None

    def update(self, items):
        old, new = self._items, list(items)
        limit = min(len(old), len(new))
        start = 0
        while start < limit and old[start] is new[start]:
            start += 1
        end = 0
        while end < limit - start and old[-1 - end] is new[-1 - end]:
            end += 1
        self._items = new
        removed, added = len(old) - start - end, len(new) - start - end
        if removed or added:
            self.items_changed(start, removed, added)


def art_candidates(url, cache_dir=None):
    """The files that may hold the artwork at `url`, best first: the thumbnail fetch_remote()
    keeps (what EntryArt fetches), the library's own thumbnail of the same artwork (the
    sync's, named by its cover URL), the cover fetch_remote() keeps (the item playing's).
    None for no URL."""
    if not url:
        return []
    cache_dir = cache_dir or str(config.cache_dir())
    cover_url = sized_url(url, normalize.ART_SIZES['cover'])
    return [path for path in (remote_art_path(url, config.THUMB_SIZE),
                              normalize.thumb_cache_path(cover_url, cache_dir) if cover_url
                              else None,
                              remote_art_path(url, config.COVER_SIZE)) if path]


def find_art(urls, candidates=art_candidates, exists=on_disk):
    """{url: the first of its candidates on disk} of those of `urls` that have one: in a
    thread (it asks the file system)."""
    found = {}
    for url in urls:
        path = next((path for path in candidates(url) if exists(path)), None)
        if path:
            found[url] = path
    return found


class EntryArt:
    """The cover file of each of the queue's artwork URLs: found on disk, else fetched, once
    per URL, for the rows bound. See the module.

    paths(url) answers at once ((path,) or ()). want(url) notes a URL a row bound has no
    path for; at most every ART_DELAY_MS, those still bound (`bound()`, the URLs of the rows
    bound now) are looked for on disk in a thread (`find`), and those not there fetched
    (`fetch`, an async function of the URL answering a path or None; None: never), ART_FETCHES
    at a time; `on_found(url, path)` tells the view a file is there. A URL that has none is not
    asked about again, until the cache is cleared (its generation moves): then nothing found
    before is known, and what a look under way finds is dropped."""

    def __init__(self, spawn, bound, on_found, fetch=None, find=find_art):
        self._spawn = spawn
        self._bound = bound
        self._on_found = on_found
        self._fetch = fetch
        self._find = find
        self._paths = {}      # url -> its file, or '' for none
        self._asked = set()   # the URLs being looked for or fetched
        self._wanted = {}     # the URLs noted since the last look, in order
        self._source = 0
        self._gate = None
        self._generation = store.cache_generation()  # the cache's that _paths names files of

    def _current(self):
        """Whether the cache is the one the paths were found in; else they are forgotten."""
        generation = store.cache_generation()
        if generation == self._generation:
            return True
        self._generation = generation
        self._paths.clear()
        self._asked.clear()
        return False

    def paths(self, url):
        if not url or not self._current():
            return ()
        path = self._paths.get(url)
        return (path,) if path else ()

    def want(self, url):
        self._current()
        if not url or url in self._paths or url in self._asked:
            return
        self._wanted[url] = None
        if not self._source:
            self._source = GLib.timeout_add(ART_DELAY_MS, self._look)

    def pending(self):
        """How many URLs are noted or being looked for: for tests."""
        return len(self._wanted) + len(self._asked)

    def _look(self):
        self._source = 0
        bound = self._bound()
        urls = [url for url in self._wanted if url in bound]
        self._wanted.clear()
        if urls:
            self._current()
            self._asked.update(urls)
            self._spawn(self._resolve(urls, self._generation))
        return GLib.SOURCE_REMOVE

    async def _resolve(self, urls, generation):
        try:
            found = await asyncio.to_thread(self._find, urls)
        except BaseException:
            self._asked.difference_update(urls)
            raise
        for url in urls:
            path = found.get(url)
            if path:
                self._found(url, path, generation)
        missing = [url for url in urls if url not in found]
        if self._fetch is None:
            for url in missing:
                self._found(url, '', generation)
            return
        if self._gate is None:
            self._gate = asyncio.Semaphore(ART_FETCHES)
        await asyncio.gather(*(self._fetch_one(url, generation) for url in missing))

    async def _fetch_one(self, url, generation):
        try:
            async with self._gate:
                path = await self._fetch(url)
        except BaseException:
            self._asked.discard(url)
            raise
        self._found(url, path or '', generation)

    def _found(self, url, path, generation):
        if not self._current() or generation != self._generation:
            return  # found in a cache cleared since: looked for again when a row wants it
        self._asked.discard(url)
        self._paths[url] = path
        if path:
            self._on_found(url, path)


async def fetch_thumbnail(url):
    """The thumbnail of the artwork at `url`, fetched by remote.fetch_remote: its path, or
    None."""
    return await fetch_remote(url, config.THUMB_SIZE)


class QueueRow(Gtk.Box):
    """One queue entry: its cover (a play symbol over it while it plays), title (and its
    explicit badge) and artist, duration. The entry, as a Track, is its `context_item` (its
    menu: context_menu), and `context_queue_entry` its (index, id) in the queue while Up Next
    may take it out (never in History)."""

    # The entry's menu is a queued one: no Play (activating the row plays it).
    context_queued = True

    def __init__(self, view, history=False):
        # The template module on first use: the rest of this one (section_bounds(),
        # HistoryModel, EntryArt) imports without the app's compiled resource.
        from .cover import Cover

        super().__init__(spacing=12)
        self.view = view  # the QueueView, as long-lived as the row
        self.history = history
        self.list_item = None  # the Gtk.ListItem bound (its accessible description)
        self._entry = None  # the NowPlaying bound
        self._current = False
        self.cover = Cover(size=ART_SIZE, valign=Gtk.Align.CENTER)
        self.cover.add_css_class('small')
        # Over the cover while the entry plays, as a track row's (style.css's playing-scrim):
        # shown and hidden by its opacity, which only redraws it (a child shown or hidden
        # would lay the list out again).
        self.playing_scrim = Gtk.Box(opacity=0, can_target=False,
                                     accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.playing_scrim.add_css_class('osd')
        self.playing_scrim.add_css_class('playing-scrim')
        self.playing_scrim.append(Gtk.Image(icon_name='media-playback-start-symbolic',
                                            hexpand=True,
                                            accessible_role=Gtk.AccessibleRole.PRESENTATION))
        self.cover.add_overlay(self.playing_scrim)
        self.append(self.cover)

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
        if self._entry is None or self.list_item is None or self.history:
            return None
        return self.view.removable(self.list_item.get_position(), self._entry)

    @property
    def context_queue_moves(self):
        """The steps (-1: Move Up, 1: Move Down) the entry bound can take in its section of
        Up Next; () when it cannot move (History, the entry playing, a station's queue)."""
        if self._entry is None or self.list_item is None or self.history:
            return ()
        return self.view.moves(self.list_item.get_position(), self._entry)

    def bind(self, entry, current, paths):
        """Show `entry`, its cover from `paths` (EntryArt.paths())."""
        self._entry = entry
        self.cover.set_paths(*paths)
        self.title_label.set_label(entry.title or self.view.unknown_title)
        self.explicit_badge.set_visible(entry.explicit)
        self.artist_label.set_text(entry.artist)
        self.artist_label.set_visible(bool(entry.artist))
        self.duration_label.set_text(
            format_time(entry.duration_ms / 1000) if entry.duration_ms else '')
        self.set_current(current)

    def unbind(self):
        self._entry = None
        self.cover.set_paths()

    def set_current(self, current):
        if current == self._current:
            return
        self._current = current
        self.playing_scrim.set_opacity(1 if current else 0)
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
        self._rows = set()  # the QueueRows bound, Up Next's and History's
        self._headers = set()  # the Gtk.ListHeaders bound
        self._slice = None  # the queue from the entry playing on
        self.model = None  # the slice in its sections (QueueSections)
        self.history_model = HistoryModel()
        self.art = None  # EntryArt, once there is an app
        self._refocus = None  # the list position to focus once a removal is in
        self._follow = None  # the entry a move took from the focused row, to focus again
        self._drag = None  # (the ItemRefs, the NowPlaying) of the drag started from a row
        self.drop_feedback = None  # the insertion line and auto-scroll of a drag over Up Next
        # Looked up once: rows are bound often.
        self._playing = _('Playing')
        self._autoplay_title = _('Autoplay')
        # Translators: the heading over the songs queued after the one playing, in Up Next
        self._playing_next = _('Playing Next')
        self.unknown_title = _('Unknown Title')

        self.empty_page = Adw.StatusPage(icon_name='playlist-symbolic', title=_('Nothing Queued'),
                                         description=_('Play something to fill Up Next'))
        self.empty_page.add_css_class('compact')
        self.add_named(self.empty_page, 'empty')

        # Above the list: History at its start; Autoplay and Clear at its end.
        self.history_button = Gtk.ToggleButton(icon_name='document-open-recent-symbolic',
                                               tooltip_text=_('History'),
                                               valign=Gtk.Align.CENTER)
        self.history_button.add_css_class('flat')
        self.history_button.add_css_class('circular')
        self.history_button.connect('toggled', lambda _button: self._on_history_toggled())
        self.history_title = Gtk.Label(label=_('History'), xalign=0, visible=False,
                                       valign=Gtk.Align.CENTER,
                                       accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.history_title.add_css_class('heading')
        self.autoplay_button = Gtk.ToggleButton(icon_name='autoplay-symbolic',
                                                tooltip_text=self._autoplay_title,
                                                valign=Gtk.Align.CENTER)
        self.autoplay_button.add_css_class('flat')
        self.autoplay_button.add_css_class('circular')
        self.clear_button = Gtk.Button(label=_('Clear'), valign=Gtk.Align.CENTER,
                                       tooltip_text=_('Remove Everything After the Song Playing'))
        self.clear_button.add_css_class('flat')
        self.clear_button.connect('clicked', lambda _button: self._on_clear())
        tools = Gtk.Box(spacing=6)
        tools.add_css_class('queue-tools')
        tools.append(self.history_button)
        tools.append(self.history_title)
        tools.append(Gtk.Box(hexpand=True))
        tools.append(self.autoplay_button)
        tools.append(self.clear_button)

        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._on_setup)
        factory.connect('bind', self._on_bind)
        factory.connect('unbind', self._on_unbind)
        headers = Gtk.SignalListItemFactory()
        headers.connect('setup', self._on_header_setup)
        headers.connect('bind', self._on_header_bind)
        headers.connect('unbind', self._on_header_unbind)
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
        move_keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        move_keys.connect('key-pressed', self._on_key_pressed)
        self.list_view.add_controller(move_keys)
        self.scrolled = Gtk.ScrolledWindow(child=self.list_view,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           vexpand=True)
        # An entry dragged within its section: the row's own drag (a mouse's), dropped on
        # the list, which shows where it goes.
        dnd.attach_source(self.list_view, weak_method(self._drag_source), Gdk.DragAction.MOVE)
        self.drop_feedback = dnd.DropFeedback(self.scrolled)
        drop = Gtk.DropTarget.new(ItemRefs.__gtype__, Gdk.DragAction.MOVE)
        drop.connect('accept', lambda _target, _drop: self.dragged_index() is not None)
        drop.connect('enter', self._on_drop_motion)
        drop.connect('motion', self._on_drop_motion)
        drop.connect('leave', lambda _target: self.drop_feedback.clear())
        drop.connect('drop', self._on_drop)
        self.list_view.add_controller(drop)

        history_factory = Gtk.SignalListItemFactory()
        history_factory.connect('setup', self._on_history_setup)
        history_factory.connect('bind', self._on_history_bind)
        history_factory.connect('unbind', self._on_unbind)
        self.history_view = Gtk.ListView(factory=history_factory,
                                         model=Gtk.NoSelection(model=self.history_model),
                                         tab_behavior=Gtk.ListTabBehavior.ITEM)
        self.history_view.add_css_class('queue-list')
        self.history_view.update_property([Gtk.AccessibleProperty.LABEL], [_('History')])
        self.history_view.connect('activate', self._on_history_activate)
        context_menu.attach(self.history_view)
        self.history_scrolled = Gtk.ScrolledWindow(child=self.history_view,
                                                   hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                   vexpand=True)
        self.history_empty = Adw.StatusPage(icon_name='document-open-recent-symbolic',
                                            title=_('No History'),
                                            description=_('Songs played before this one in '
                                                          'the queue show here'))
        self.history_empty.add_css_class('compact')

        self.lists = Gtk.Stack(vhomogeneous=True, hhomogeneous=True, vexpand=True,
                               transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.lists.add_named(self.scrolled, 'up-next')
        self.lists.add_named(self.history_scrolled, 'history')
        self.lists.add_named(self.history_empty, 'no-history')
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(tools)
        page.append(self.lists)
        self.add_named(page, 'list')

    def set_player(self, player, app):
        self._player = player
        self._app = app
        self.art = EntryArt(app.spawn, self._bound_urls, weak_method(self._on_art_found),
                            fetch=None if getattr(app, 'demo', False) else fetch_thumbnail)
        queue = player.queue
        # The slice first: it follows the queue's changes before _on_items_changed moves
        # the sections' bounds.
        self._slice = Gtk.SliceListModel(model=queue, offset=0, size=slice_size(0))
        self.model = QueueSections(self._slice)
        self.model.connect('items-changed', self._on_rows_changed)
        self.list_view.set_model(Gtk.NoSelection(model=self.model))
        queue.connect('items-changed', lambda *_: self._on_items_changed())
        player.connect('notify::queue-index', lambda *_: self._on_index())
        player.connect('notify::moving', lambda *_: self._on_moving())
        for name in ('queue-editable', 'can-autoplay', 'repeat'):
            player.connect('notify::' + name, lambda *_: self._update_tools())
        app.settings.bind('autoplay', self.autoplay_button, 'active',
                          Gio.SettingsBindFlags.DEFAULT)
        self._on_index()
        self._update_page()

    def set_active(self, active):
        """Scroll to the entry playing when shown; back to Up Next when left."""
        self._active = active
        if active:
            self._scroll_to_current()
        else:
            self.history_button.set_active(False)

    @property
    def history_shown(self):
        return self.history_button.get_active()

    # -- the slice and its sections -------------------------------------------------------

    def queue_index_at(self, position):
        """The queue index of the Up Next row at list `position`."""
        return self._slice.get_offset() + position

    def history_index_at(self, position):
        """The queue index of the History row at list `position`."""
        return self._player.queue_index - 1 - position

    def removable(self, position, entry):
        """(queue index, id) of `entry`, the row at list `position`, when Up Next may take
        it out (Player.can_edit), else None."""
        if self._player is None:
            return None
        index = self.queue_index_at(position)
        if not self._player.can_edit(index, entry.id):
            return None
        return index, entry.id

    def moves(self, position, entry):
        """The steps (-1, 1) `entry`, the row at list `position`, can take within its
        section (Player.can_move), in that order."""
        if self._player is None:
            return ()
        index = self.queue_index_at(position)
        return tuple(step for step in (-1, 1)
                     if self._player.can_move(index, index + step, entry.id))

    def _update_bounds(self):
        """The slice from the entry playing on, and where its sections begin."""
        offset, first, split = section_bounds(_Entries(self._player.queue),
                                              self._player.queue_index)
        _set_slice(self._slice, offset, slice_size(offset))
        self.model.set_bounds(first - offset, split - offset)
        for header in self._headers:
            self._title_header(header)

    def _update_page(self):
        self.set_visible_child_name('list' if self._player.queue.get_n_items() else 'empty')

    def _update_tools(self):
        player = self._player
        can_clear = player.can_clear()
        if not can_clear and self.clear_button.is_focus():
            self._focus_from_clear()
        self.clear_button.set_sensitive(can_clear)
        if not player.can_autoplay:
            tooltip = _('Autoplay Is Not Available Here')
        elif player.repeat != 'none':
            tooltip = _('Autoplay Is Off While Repeat Is On')
        else:
            tooltip = self._autoplay_title
        self.autoplay_button.set_sensitive(player.can_autoplay and player.repeat == 'none')
        self.autoplay_button.set_tooltip_text(tooltip)

    def _focus_from_clear(self):
        """Clear is about to go insensitive with the focus on it (it has just cleared, from
        the keyboard), and GTK would drop the focus to the window: the focus goes to the
        entry playing, the list's first row, which a screen reader then reads; or to the
        Autoplay toggle, or History's, when the list has none."""
        if self.model is not None and self.model.get_n_items():
            # scroll_to() moves the list's focus item there; the grab focuses its row.
            self.list_view.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
            self.list_view.grab_focus()
            if self.list_view.get_focus_child() is not None:
                return
        if self.autoplay_button.get_sensitive() and self.autoplay_button.grab_focus():
            return
        self.history_button.grab_focus()

    def _on_items_changed(self):
        """The queue changed: the slice and its sections, the page, the tools, History, and
        the entry playing on top (a new queue with the same index number fires no index
        notify), but for a move of Up Next's (Player.moving): the list stays where it is."""
        moving = self._player.moving
        self._update_bounds()
        self._update_page()
        self._update_tools()
        self._refresh_rows()
        self._update_history()
        if self._active and self._refocus is None and moving is None:
            self._scroll_to_current()

    def _on_index(self):
        """The entry playing changed: the slice starts there, and the rows show it."""
        self._update_bounds()
        self._update_tools()
        self._refresh_rows()
        self._update_history()
        if self._active:
            self._scroll_to_current()

    def _refresh_rows(self):
        """The Up Next rows bound, marked by where they are now (a row that moves is not
        always bound again)."""
        for row in self._rows:
            if not row.history and row.list_item is not None and row.entry is not None:
                current = row.list_item.get_position() == 0 and self._player.queue_index >= 0
                row.set_current(current)
                self._describe(row, current)

    def _scroll_to_current(self):
        if self.history_shown:
            return
        if (self._player is not None and self._player.queue_index >= 0
                and self.model.get_n_items()):
            self.list_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)

    # -- History ---------------------------------------------------------------------------

    def _on_history_toggled(self):
        shown = self.history_shown
        self.history_title.set_visible(shown)
        self.autoplay_button.set_visible(not shown)
        self.clear_button.set_visible(not shown)
        if shown:
            self._update_history()
            if self.history_model.get_n_items():
                self.history_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)
        else:
            self.history_model.update(())  # nothing kept, or followed, while hidden
            self.lists.set_visible_child_name('up-next')
            self._scroll_to_current()

    def _update_history(self):
        """History's entries, while it shows."""
        if self._player is None or not self.history_shown:
            return
        self.history_model.update(history_entries(self._player.queue, self._player.queue_index))
        self.lists.set_visible_child_name('history' if self.history_model.get_n_items()
                                          else 'no-history')

    def _on_history_activate(self, _list_view, position):
        if self._player is None:
            return
        index = self.history_index_at(position)
        if index >= 0:
            self._app.player_command(self._player.queue_jump(index))

    # -- rows --------------------------------------------------------------------------------

    def _on_setup(self, _factory, list_item):
        row = QueueRow(self)
        row.list_item = list_item
        list_item.set_child(row)

    def _on_history_setup(self, _factory, list_item):
        row = QueueRow(self, history=True)
        row.list_item = list_item
        list_item.set_child(row)

    def _bind_row(self, list_item, current):
        row = list_item.get_child()
        self._rows.add(row)
        entry = list_item.get_item()
        url = entry.artwork_url
        paths = self.art.paths(url) if self.art is not None else ()
        row.bind(entry, current, paths)
        if not paths and self.art is not None:
            self.art.want(url)
        list_item.set_accessible_label(track_label(entry, show_artist=True, show_album=False))
        return row

    def _on_bind(self, _factory, list_item):
        current = list_item.get_position() == 0 and self._player.queue_index >= 0
        self._describe(self._bind_row(list_item, current), current)

    def _on_history_bind(self, _factory, list_item):
        self._bind_row(list_item, False)
        list_item.set_accessible_description('')

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

    def _bound_urls(self):
        """The artwork URLs of the rows bound now (EntryArt looks only for these)."""
        return {row.entry.artwork_url for row in self._rows if row.entry is not None}

    def _on_art_found(self, url, path):
        for row in self._rows:
            if row.entry is not None and row.entry.artwork_url == url:
                row.cover.set_paths(path)

    def _on_header_setup(self, _factory, header):
        label = Gtk.Label(xalign=0, visible=False)
        label.add_css_class('heading')
        label.add_css_class('queue-section')
        header.set_child(label)

    def _on_header_bind(self, _factory, header):
        self._headers.add(header)
        self._title_header(header)

    def _on_header_unbind(self, _factory, header):
        self._headers.discard(header)

    def _title_header(self, header):
        """Playing Next's and Autoplay's sections are named by their headers; the entry
        playing's shows nothing."""
        entry = header.get_item()
        label = header.get_child()
        playing = header.get_start() == 0 and self._player.queue_index >= 0
        if entry is None or playing:
            label.set_visible(False)
            return
        label.set_label(self._autoplay_title if entry.autoplay else self._playing_next)
        label.set_visible(True)

    def _on_activate(self, _list_view, position):
        if self._player is None:
            return
        self._app.player_command(self._player.queue_jump(self.queue_index_at(position)))

    # -- the edits ---------------------------------------------------------------------------

    def _focused_row(self):
        """The Up Next row with the focus, or None."""
        root = self.list_view.get_root()
        focus = root.get_focus() if root is not None else None
        found = context_menu.find(self.list_view, focus) if focus is not None else None
        return found[0] if found is not None and isinstance(found[0], QueueRow) else None

    def _focused_entry(self):
        row = self._focused_row()
        return row.entry if row is not None else None

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        """Alt+Up or Alt+Down on a row: its entry one place up or down in its section, the
        focus going with it. Not taken on an entry that cannot move (the entry playing, a
        station's queue); taken at either end of its section, where nothing moves."""
        mods = state & Gtk.accelerator_get_default_mod_mask()
        root = self.list_view.get_root()
        focus = root.get_focus() if root is not None else None
        get_dialog = getattr(root, 'get_visible_dialog', None)
        step = keyboard.move_step(keyval, mods, type(focus),
                                  get_dialog is not None and get_dialog() is not None,
                                  focus is not None and focus.get_ancestor(Gtk.Popover) is not None)
        row = self._focused_row() if step is not None else None
        if row is None or row.entry is None or row.history:
            return False
        index = self.queue_index_at(row.list_item.get_position())
        if self._player.move_range(index) is None:
            return False
        if self._player.can_move(index, index + step, row.entry.id):
            self.move(index, index + step, row.entry.id)
        return True

    def move(self, index, to_index, entry_id):
        """The queue's entry at `index` (the entry `entry_id`) to `to_index`, through
        win.item-move-in-queue (the Player, the announcement)."""
        self.list_view.activate_action('win.item-move-in-queue',
                                       GLib.Variant('(iis)', (index, to_index, entry_id)))

    def _on_moving(self):
        """A move starts (Player.moving), before its entry is taken out: when the focus is
        on its row, it goes with the entry to its new place once the move is in."""
        moving = self._player.moving
        if moving is not None and self._focused_entry() is moving:
            self._follow = moving
            GLib.idle_add(self._focus_moved)

    def _focus_moved(self):
        """After a move: the focus on the entry moved, at its new place (taken back into
        the list: the row it was on went as the entry was taken out)."""
        entry, self._follow = self._follow, None
        player = self._player
        if entry is None or player is None or not 0 <= entry.index < player.queue.get_n_items():
            return GLib.SOURCE_REMOVE
        if player.queue.get_item(entry.index) is entry:
            position = entry.index - self._slice.get_offset()
            if 0 <= position < self.model.get_n_items():
                focus_position(self.list_view, position)
        return GLib.SOURCE_REMOVE

    # -- a drag within Up Next ----------------------------------------------------------------

    def _drag_source(self, x, y):
        """dnd.attach_source()'s find: the row under (x, y) when its entry can move (its
        drag carries the entry as a Track, from the queue), and the row as the icon."""
        self._drag = None
        picked = self.list_view.pick(x, y, Gtk.PickFlags.DEFAULT)
        found = context_menu.find(self.list_view, picked) if picked is not None else None
        row = found[0] if found is not None else None
        if not isinstance(row, QueueRow) or row.entry is None or row.history:
            return None
        index = self.queue_index_at(row.list_item.get_position())
        if self._player is None or self._player.move_range(index) is None:
            return None
        track = row.context_item
        refs = ItemRefs.for_objects([track], origin=('queue', row.entry.id)) if track else None
        if refs is None:
            return None
        self._drag = (refs, row.entry)
        return refs, row

    def dragged_index(self):
        """The queue index of the entry the drag in progress carries, when it started on a
        row of Up Next and the entry can still move (it may have begun to play meanwhile);
        else None."""
        refs = dnd.current()
        if refs is None or self._drag is None or refs is not self._drag[0]:
            return None
        entry = self._drag[1]
        queue = self._player.queue
        index = entry.index
        if not 0 <= index < queue.get_n_items() or queue.get_item(index) is not entry:
            return None
        return index if self._player.move_range(index) is not None else None

    def _bound_rows(self):
        """Up Next's rows bound, in list order: (list position, row)."""
        rows = [(row.list_item.get_position(), row) for row in self._rows
                if not row.history and row.list_item is not None and row.entry is not None]
        return sorted(rows, key=lambda pair: pair[0])

    def _row_at(self, index):
        """The row bound for the queue's entry at `index`, or None."""
        position = index - self._slice.get_offset()
        return next((row for at, row in self._bound_rows() if at == position), None)

    def drop_place(self, from_index, x, y):
        """Where the entry at `from_index` dropped at (x, y) in the list goes: (to_index,
        row, after), its index once moved (None: where it is, nothing moves) and the row the
        insertion line is drawn on, at its bottom (`after`) or top edge; None when no row
        is bound. The gap under the pointer (between the rows bound, by their halves) is
        kept to the entry's section (drop_gap(), line_place())."""
        bounds = self._player.move_range(from_index)
        rows = self._bound_rows()
        if bounds is None or not rows:
            return None
        tops, heights = [], []
        for _position, row in rows:
            ok, rect = row.compute_bounds(self.list_view)
            tops.append(rect.get_y() if ok else 0)
            heights.append(rect.get_height() if ok else 0)
        at, after = dnd.insertion_point(tops, heights, y)
        gap = drop_gap(self.queue_index_at(rows[at][0]) + (1 if after else 0), bounds)
        index, below = line_place(gap, bounds)
        return drop_index(from_index, gap), self._row_at(index), below

    def show_insertion(self, index, after=False):
        """Draw the insertion line on the top (or, `after`, the bottom) edge of the row of
        the queue's entry at `index`, as a drag over it does (scripts/screenshot.py's
        --drop-line: no headless script can drag). False when the row is not bound."""
        row = self._row_at(index)
        if row is None:
            return False
        self._mark(row, after)
        return True

    def _mark(self, row, after):
        """The insertion line on the list's row of `row` (its Gtk.ListItem's widget, padded
        round the QueueRow, so the line spans the row and no cover covers it)."""
        self.drop_feedback.insert(row.get_parent() or row, after)

    def _on_drop_motion(self, _target, x, y):
        """A drag over Up Next: the insertion line where the entry would go in its section
        (none beside it, where it is), the list scrolled near its edges; the action."""
        from_index = self.dragged_index()
        if from_index is None:
            self.drop_feedback.clear()
            return 0
        point = Graphene.Point()
        point.x, point.y = x, y
        ok, scrolled = self.list_view.compute_point(self.scrolled, point)
        if ok:
            self.drop_feedback.motion(scrolled.y)
        place = self.drop_place(from_index, x, y)
        if place is None or place[0] is None or place[1] is None:
            self.drop_feedback.highlight(None)
            return 0
        self._mark(place[1], place[2])
        return Gdk.DragAction.MOVE

    def _on_drop(self, _target, _value, x, y):
        """An entry of Up Next dropped on it: moved there."""
        self.drop_feedback.clear()
        from_index = self.dragged_index()
        place = self.drop_place(from_index, x, y) if from_index is not None else None
        if place is None or place[0] is None:
            return False
        self.move(from_index, place[0], self._drag[1].id)
        return True

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
        if self._player is not None and self._player.moving is not None:
            return  # a move's: the focus goes with the entry (_on_moving)
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

