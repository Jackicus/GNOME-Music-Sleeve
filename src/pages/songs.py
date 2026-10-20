# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSongsPage: every song in the library as a table, sorted by any column and filtered
as you type.

The chain is library.songs → the songs in the chosen column's order (library.SongOrder) → those
matching the filter → a Gio.ListStore of the rows shown → Gtk.NoSelection →
Gtk.ColumnView. Ordering and filtering happen in Python rather than in a Gtk.SortListModel and
Gtk.FilterListModel because GTK's are slow over Python objects; measured on 30,000 songs
(scripts/demo_library.py --albums 2500):

- GTK's sorters and filters read each track's properties from C, about 3 µs a read into Python.
  The view's Gtk.ColumnViewSorter has no sort keys, so a Gtk.SortListModel over it compares
  pairs and reads both tracks at every comparison: 1.6 to 6 s a click. SongOrder sorts with
  keys it computes once: 5 to 60 ms.
- A Gtk.AnyFilter of three Gtk.StringFilters refilters once per sub-filter it changes: up to
  1.1 s a keystroke; one Gtk.StringFilter over the three fields still takes 60 ms a pass.
  Testing each track's folded search key (Track.search_key) in Python takes 13 ms.
- Whichever model filters, a Gtk.ColumnView keeps 200 rows of widgets alive, and when a change
  removes the items they show it destroys them and builds new ones, about 0.5 ms a row: 100 ms
  and more on the first keystroke. _show() replaces the rows in an order that lets it recycle
  them instead (inserting, moving the view, then removing), so it only rebinds them.

In all, a click re-sorts the table in 30 to 50 ms and a keystroke refilters it in 10 to 50 ms,
rebinding included.

Clicking a column header, or choosing in the header's Sort By menu (the keyboard's way: the
headers take no focus), re-sorts. The filter is the library pages' filter bar
(widgets/filter_bar.py: Filter Songs, Ctrl+F through focus_filter(), typing on the page,
Escape), matching each song's search_key; typing in it refilters (after the entry's own short
delay), Favourites Only and the text both apply, and the new count ("36 of 460 songs") is
announced. A sync that changes the songs brings the rows up
to date with the fewest splices (library.apply_diff), so the table keeps its scroll position;
only a new sort or filter starts it again from the top. Activating a row (Enter, a click: the
view's single-click-activate, docs/decisions.md) asks the window to play it; a right click, a
long press or the Menu key opens its context menu, and a row drags onto a sidebar playlist
(widgets/context_menu.py). The artist and the album are links to their pages
(widgets/track_links.py); in a narrow window, the album's column hidden and the artist's
too, the artist is a dimmed line under the title (SongTitle.set_stacked()), so that the title
keeps its room. The table keeps no selection (a Gtk.NoSelection): GTK selects the
hovered row of a single-click list, which would have followed the pointer around. Songs are
selected in the table's selection mode instead (widgets/selection_mode.py: Select in the
header bar, a Ctrl+click or Shift+click, Ctrl+A), whose bar acts on them all; its check box is
in the title cell (SongTitle), and a row's description says whether it is selected.

Play and Shuffle, beside the title (under it in a narrow window), play what the table shows,
in its order and under its filter and Favourites Only: Play from its first song, Shuffle a
random draw of them, shuffled; at most PLAY_LIMIT songs either way (play_target()).

The row of the song playing is marked (SongTitle's play icon and bold title, "Playing" as
the row's accessible description): the page follows the Player's `notify::track` while it is
shown, through the title cells and the rows it has bound (widgets/track_row.py's
PlayingMark), and catches up as it maps.
"""

import random
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Adw, Gio, GLib, Gtk

from ..discography import PLAY_LIMIT
from ..library import SongOrder, Track, apply_diff
from ..widgets import context_menu, track_links
from ..widgets.filter_bar import FilterBar
from ..widgets.selection_mode import SelectionMode, row_description
from ..widgets.labels import track_label
from ..widgets.song_title import SongTitle
from ..widgets.track_links import TrackLink
from ..widgets.track_row import PlayingMark
from ..widgets.util import (GrowBack, HeaderTitle, MappedHandlers, connect_weak,
                            focus_position, rows_kept, weak_method)
from . import SignInOffer, app, mark_bound

# The columns' names in the Sort By menu's targets and SongOrder's keys.
COLUMNS = ('title', 'artist', 'album', 'time')

# The rows the table is given at a frame while it grows back to many (_show()): each about
# 1.5 ms to make, bind and lay out (twelve made a frame of 18-27 ms).
GROW_ROWS = 6

# The texts whose matches the filter keeps (_filter()): a Backspace back to one of them, or
# the same key typed again, filters nothing.
KEPT_SEARCHES = 16


def _string_sorter(name):
    return Gtk.StringSorter(expression=Gtk.PropertyExpression.new(Track, None, name))


def resized_fixed_width(width, start_width, share, others):
    """The fixed width that, expanding, keeps a column dragged to `width` as wide.

    The drag began at `start_width`, the column then holding `share` of the spare room; while
    dragged it did not expand, so the `others` expanding columns shared the room left as it
    grew or shrank. Expanding again from `width` less what each of them now holds gives every
    column the same share and leaves all their widths as they are. None when that would be
    less than nothing (the column dragged narrower than its share): it stays as dragged.
    """
    if others < 1:
        return None
    left = max(share - round((width - start_width) / others), 0)
    return width - left if left <= width else None


def play_target(tracks, shuffle=False, limit=PLAY_LIMIT, sample=random.sample):
    """What Play (or with `shuffle`, Shuffle) plays of `tracks`, the songs the table shows in
    its order: their ids, {'kind': 'songs', 'id': 'i.…,i.…'} as the bridge takes them, or
    None without a song to play.

    MusicKit looks a queue of songs up by id before it plays, so the queue is `limit` songs
    at most (a day's listening), never the library's 40,000: Play takes the first of them,
    Shuffle a random draw (`sample(population, k)`) from all of them, so that a shuffle
    reaches the whole of what is shown, not only its first songs. Only the songs queued are
    read (a Track's id is a GObject property: 40,000 reads would take a click 100 ms)."""
    if shuffle and len(tracks) > limit:
        tracks = sample(tracks, limit)
    ids = []
    for track in tracks:
        track_id = track.id
        if track_id:
            ids.append(track_id)
            if len(ids) >= limit:
                break
    return {'kind': 'songs', 'id': ','.join(ids)} if ids else None


def narrows(old, new):
    """Whether everything the folded filter text `new` matches matched `old` too, so that
    only `old`'s matches need testing again: `old` is part of `new` (a key typed, at the end
    or anywhere), and was some text (no text matched everything without a test)."""
    return bool(old) and old in new


def songs_state(total, library_state, songs_ready, song_count, syncing=False):
    """What the Songs page shows: 'items' once it has ordered songs (`total`); 'loading' while
    the library loads, before the songs are built, while songs exist that are not ordered yet
    (`song_count`: SongOrder.prepare() runs over frames), and while the first sync fills an
    empty library (`syncing`); 'empty' when there are no songs at all."""
    if total:
        return 'items'
    if (library_state == 'loading' or not songs_ready or song_count
            or (library_state == 'empty' and syncing)):
        return 'loading'
    return 'empty'


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/songs.ui')
class SongsPage(Adw.NavigationPage):
    """The Songs destination: library.songs, which it asks the library to build when it is
    first shown."""

    __gtype_name__ = 'AppleMusicSongsPage'

    toolbar = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    sort_button = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    count_label = Gtk.Template.Child()
    results_stack = Gtk.Template.Child()
    no_results_page = Gtk.Template.Child()
    column_view = Gtk.Template.Child()
    title_column = Gtk.Template.Child()
    artist_column = Gtk.Template.Child()
    album_column = Gtk.Template.Child()
    time_column = Gtk.Template.Child()
    narrow_breakpoint = Gtk.Template.Child()
    heading_box = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()

    def __init__(self, library, title, icon_name=None):
        super().__init__(title=title)
        self._library = library
        self._songs_handler = None
        self._order = None  # a SongOrder over the songs as they are, made when first needed
        self._ordered = []  # every song, in the chosen order
        self._search = ''  # the filter's text, folded
        self._favourites_only = False  # the menu's Favourites Only
        self._matches = []  # the ordered songs that match it
        # The matches of the texts filtered by lately ({text: matches}), of these songs
        # ordered and Favourites Only: (the songs, Favourites Only, the texts' matches).
        self._kept = (None, False, {})
        self._shown = []  # what the table's rows hold, or will once they have grown back
        self._follow = False  # the songs changed: the rows follow, keeping their place
        self._prepare_task = None  # the SongOrder being prepared
        self._quiet = False  # the page is changing the sort itself
        self._bound = False  # a row has been bound (the startup timing's mark)
        self._title_cells = set()  # the title cells bound: marked again as the item playing changes
        self._row_items = set()  # and the rows bound (their descriptions)
        self._favourites_restored = False  # Favourites Only as last chosen, once mapped
        self._stacked = False  # the narrow table's: the artist under the title, not beside it

        self.title_label.set_label(title)
        self._header_title = HeaderTitle(self.header_bar, self.title_label)  # while loading
        # The filter bar, under the header bar; a key typed anywhere on the page (a row, a
        # header button) shows it and lands in its entry.
        # The table's selection mode (widgets/selection_mode.py): Select beside Sort and
        # Filter, the batch actions in a bar under the table.
        self.selection_mode = SelectionMode(self, self.header_bar, self.toolbar,
                                            self.column_view, self._selectable,
                                            self._focus_table)
        self.selection_mode.set_header_title(self._header_title)
        self.selection_mode.set_context(None, library=True)
        self.header_bar.pack_end(self.selection_mode.select_button)
        self.header_bar.pack_end(self.selection_mode.cancel_button)
        connect_weak(self.selection_mode.selection, 'changed', self._on_selection_changed)
        self.filter_bar = FilterBar(_('Filter Songs'))
        self.toolbar.add_top_bar(self.filter_bar)
        self.header_bar.pack_end(self.filter_bar.button)
        self.selection_mode.set_filter_bar(self.filter_bar)
        connect_weak(self.filter_bar, 'changed', self._on_filter_changed)
        self.filter_bar.set_focus_return(self._focus_table)
        connect_weak(self.play_button, 'clicked', self._on_play_clicked, False)
        connect_weak(self.shuffle_button, 'clicked', self._on_play_clicked, True)
        self.empty_page.set_icon_name(icon_name)
        self.empty_page.set_title(_('No Songs'))
        self.empty_page.set_description(_('Songs in your library appear here'))
        self._sign_in = SignInOffer(self.empty_page)  # Sign In… while signed out

        # column -> its SongOrder key. The sorters make the headers clickable and say what the
        # order is; SongOrder does the sorting.
        self._columns = {
            self.title_column: 'title',
            self.artist_column: 'artist',
            self.album_column: 'album',
            self.time_column: 'time',
        }
        self.title_column.set_sorter(_string_sorter('title'))
        self.artist_column.set_sorter(_string_sorter('artist'))
        self.album_column.set_sorter(_string_sorter('album'))
        self.time_column.set_sorter(Gtk.NumericSorter(
            expression=Gtk.PropertyExpression.new(Track, None, 'duration_ms')))

        self.title_column.set_factory(self._factory(self._setup_title, self._bind_title,
                                                    self._unbind_title))
        self.artist_column.set_factory(self._link_factory('artist'))
        self.album_column.set_factory(self._link_factory('album'))
        self.time_column.set_factory(self._text_factory('duration_label', numeric=True))

        # Each row reads its title, artist and album to assistive technology (labels.py),
        # the time (or "Playing") as its description.
        row_factory = Gtk.SignalListItemFactory()
        row_factory.connect('bind', self._bind_row)
        row_factory.connect('unbind', self._unbind_row)
        self.column_view.set_row_factory(row_factory)
        # The narrow table has no Artist column: the title cells show the artist under the
        # title while its breakpoint applies.
        connect_weak(self.narrow_breakpoint, 'apply', self._set_stacked, True)
        connect_weak(self.narrow_breakpoint, 'unapply', self._set_stacked, False)

        # Dragging a divider: GTK sets the column's fixed width to its allocated width, which
        # for an expanding column already holds its share of the spare room, then adds the
        # share again, and the divider would jump away from the pointer. So the column stops
        # expanding while it is dragged (its width is then the fixed width alone), and on
        # release expands again from a fixed width less its share (resized_fixed_width()):
        # nothing moves, and every column still follows the window's width. The gesture, in
        # the capture phase, sees the press before the view's own.
        self._dragging = False
        self._resize = None  # (column, its width as the drag began, its share of the room then)
        self._fixed = {}  # column -> its fixed width, the one before a drag's
        drag = Gtk.GestureDrag(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        connect_weak(drag, 'drag-begin', self._on_drag_begin)
        connect_weak(drag, 'drag-end', self._on_drag_end)
        self.column_view.add_controller(drag)
        for column in (self.title_column, self.artist_column, self.album_column):
            self._fixed[column] = column.get_fixed_width()
            connect_weak(column, 'notify::fixed-width', self._on_fixed_width)

        self._rows = Gio.ListStore(item_type=Track)
        # The rows a filter brings back, a few a frame (_show()).
        self._grow = GrowBack(self.column_view, self._replace_rows, GROW_ROWS)
        self.column_view.set_model(Gtk.NoSelection(model=self._rows))
        # Every cell of a row finds the row's Track in its title cell (SongTitle.context_item).
        context_menu.attach(self.column_view, drag=True)
        context_menu.set_drag_objects(self.column_view,
                                      weak_method(self.selection_mode.drag_objects))
        track_links.attach(self.column_view)

        # The Sort By menu's actions (songs.sort-column, songs.sort-order), following the
        # headers too; the songs are put in this order when the page is realized.
        self._sort_column = Gio.SimpleAction.new_stateful(
            'sort-column', GLib.VariantType.new('s'), GLib.Variant('s', 'title'))
        self._sort_order = Gio.SimpleAction.new_stateful(
            'sort-order', GLib.VariantType.new('s'), GLib.Variant('s', 'ascending'))
        actions = Gio.SimpleActionGroup()
        for action in (self._sort_column, self._sort_order):
            connect_weak(action, 'change-state', self._on_sort_chosen)
            actions.add_action(action)
        # Favourites Only (songs.favourites-only, a check item), remembered as the grids'
        # is (grid.favourites_only()), under this page's key.
        self._favourites_action = Gio.SimpleAction.new_stateful(
            'favourites-only', None, GLib.Variant('b', False))
        connect_weak(self._favourites_action, 'change-state', self._on_favourites_only)
        actions.add_action(self._favourites_action)
        self.insert_action_group('songs', actions)
        self.column_view.sort_by_column(self.title_column, Gtk.SortType.ASCENDING)
        self.column_view.get_sorter().connect('changed', self._on_sort_changed)
        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._update_state)
        self._handlers.add(library, 'notify::songs-ready', self._update_state)
        self._handlers.add(library, 'notify::syncing', self._update_state)
        self._handlers.add(library, 'favourites-changed', self._on_favourites_changed)
        # The item playing (a test's stand-in application may have no player).
        self._playing = PlayingMark(getattr(app(), 'player', None))
        if self._playing.player is not None:
            self._handlers.add(self._playing.player, 'notify::track', self._on_track_changed)
        self._update_state()

    # The library and the player outlive the window, so the page listens to them only while
    # it is shown (self._handlers), and to the songs store, which the rows must follow even
    # while the page is hidden, while it is realized.

    def do_realize(self):
        Adw.NavigationPage.do_realize(self)
        self._songs_handler = self._library.songs.connect('items-changed',
                                                          self._on_songs_changed)
        self._on_songs_changed()

    def do_unrealize(self):
        self._library.songs.disconnect(self._songs_handler)
        self._songs_handler = None
        self._cancel_prepare()
        Adw.NavigationPage.do_unrealize(self)

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        if not self._favourites_restored:
            self._favourites_restored = True
            from .grid import favourites_only
            if favourites_only(self.get_tag()):
                self._favourites_action.change_state(GLib.Variant('b', True))
        if not self._library.songs_ready:
            app().spawn(self._library.build_songs())
        self._update_state()
        self._update_playing()  # the item playing now, changed or not while hidden
        self._on_favourites_changed()  # and the favourites, changed or not while hidden

    def do_hidden(self):
        self.selection_mode.leave()  # the mode is the page's while it shows
        Adw.NavigationPage.do_hidden(self)

    # Order and filter.

    def _on_songs_changed(self, *_args):
        self._order = None
        self._cancel_prepare()
        self._follow = True  # a sync's change: the rows keep their place
        self._sort()

    def _cancel_prepare(self):
        if self._prepare_task is not None and not self._prepare_task.done():
            self._prepare_task.cancel()
        self._prepare_task = None

    def _on_drag_begin(self, _gesture, _x, _y):
        self._dragging = True

    def _on_fixed_width(self, column, _pspec):
        """A drag's first width is the column's allocation: the fixed width before it plus the
        column's share of the spare room. The column stops expanding until the drag ends."""
        width = column.get_fixed_width()
        if self._dragging and self._resize is None and column.get_expand():
            self._resize = (column, width, max(width - self._fixed[column], 0))
            column.set_expand(False)
        self._fixed[column] = width

    def _on_drag_end(self, _gesture, _x, _y):
        self._dragging = False
        if self._resize is None:
            return
        column, start_width, share = self._resize
        self._resize = None
        others = sum(1 for other in self._fixed
                     if other is not column and other.get_visible() and other.get_expand())
        fixed = resized_fixed_width(column.get_fixed_width(), start_width, share, others)
        if fixed is not None:  # else it keeps the width it was dragged to
            column.set_fixed_width(fixed)
            column.set_expand(True)

    def _on_sort_changed(self, sorter, _change):
        if self._quiet:
            return
        column = self._columns.get(sorter.get_primary_sort_column())
        if column is not None:  # the menu follows a header's click
            descending = sorter.get_primary_sort_order() == Gtk.SortType.DESCENDING
            self._sort_column.set_state(GLib.Variant('s', column))
            self._sort_order.set_state(
                GLib.Variant('s', 'descending' if descending else 'ascending'))
        self._follow = False
        self._sort()

    def _on_sort_chosen(self, action, value):
        """The Sort By menu: sort as a header click would, its arrow on its column."""
        action.set_state(value)
        column = next(column for column, key in self._columns.items()
                      if key == self._sort_column.get_state().get_string())
        order = (Gtk.SortType.DESCENDING
                 if self._sort_order.get_state().get_string() == 'descending'
                 else Gtk.SortType.ASCENDING)
        self._quiet = True
        try:
            self.column_view.sort_by_column(None, order)  # the previous column's arrow goes
        finally:
            self._quiet = False
        self.column_view.sort_by_column(column, order)

    def _sort(self):
        sorter = self.column_view.get_sorter()
        key = self._columns.get(sorter.get_primary_sort_column())
        if key is None:
            self._ordered = list(self._library.songs)
        else:
            if self._order is None:
                # A new order over new songs: its keys are made a few thousand tracks at a
                # time with frames between (SongOrder.prepare), then this runs again. Sorting
                # by a column whose keys exist (a header click) is immediate.
                self._order = SongOrder(self._library.songs)
                self._prepare_task = app().spawn(self._prepare(self._order, key))
                return
            descending = sorter.get_primary_sort_order() == Gtk.SortType.DESCENDING
            self._ordered = self._order.tracks(key, descending)
        self._filter()

    async def _prepare(self, order, key):
        await order.prepare(key)
        if self._order is order:  # the songs have not changed meanwhile
            self._sort()

    def _filter(self):
        search = self._search
        ordered, favourites_only, kept = self._kept
        if ordered is not self._ordered or favourites_only != self._favourites_only:
            kept = {}
            self._kept = (self._ordered, self._favourites_only, kept)
        # A text filtered by lately (a Backspace, or a key typed again) matches what it did.
        matches = kept.get(search) if search else None
        if matches is None:
            # A longer text (a key typed): only what a shorter one it holds matched can
            # match it (the longest of those kept: the text before, as a rule).
            within = max((text for text in kept if narrows(text, search)), key=len,
                         default=None)
            if within is not None:
                matches = [track for track in kept[within] if search in track.search_key]
            else:
                matches = self._ordered
                if self._favourites_only:
                    is_favourite = self._library.is_favourite
                    matches = [track for track in matches if is_favourite(track)]
                if search:  # library.filter_matches(), inline: 40,000 calls fewer
                    matches = [track for track in matches if search in track.search_key]
        if search:
            kept.pop(search, None)
            kept[search] = matches  # the latest last
            while len(kept) > KEPT_SEARCHES:
                del kept[next(iter(kept))]
        self._matches = matches
        # With no matches the rows stay as they were, hidden behind "No Results Found": the
        # next matches can then recycle their widgets rather than build new ones.
        if self._matches or not self._ordered:
            self._show(self._matches)
        self._update_state()
        self.selection_mode.prune()  # what the filter hides is no longer selected

    def _show(self, tracks):
        """Make the table's rows tracks: where they were, after a sync changed the songs
        (the fewest splices, library.apply_diff: runs of the same tracks stay, and the view
        its scroll position); from the top, after a new sort or filter.

        Replacing the rows in one splice would make the view destroy the widgets of rows
        whose tracks it no longer has and build new ones. Inserted at the front instead, the
        new rows push the old ones down with the view following them; moving the view back to
        the top leaves the old rows' widgets out of view, where the view recycles them for the
        new rows; removing the old rows then removes rows without widgets.

        That recycles only the rows pushed past the 200 the view keeps. Fewer rows than that
        (a filter that left 69 songs) growing back to many (a Backspace: 5,817) would have
        the view make a row for every new track up to 200, 130 ms at once: when every row
        shown stays, the new tracks go in between them instead, GROW_ROWS at once and
        GROW_ROWS a frame (widgets.util.GrowBack).
        """
        follow, self._follow = self._follow, False
        if tracks == self._shown:
            return
        if follow and self._shown:
            self._grow.finish()
            apply_diff(self._rows, tracks, old=self._shown)
            self._shown = tracks
            return
        old = self._rows.get_n_items()
        if 0 < old < rows_kept(self.column_view):  # not the first rows: the page's first build
            shown = self._shown
            if self._grow.pending:  # the rows an earlier growth has given so far
                shown = [self._rows.get_item(position) for position in range(old)]
            if self._grow.start(shown, tracks):
                self._shown = tracks
                if tracks:
                    self.column_view.scroll_to(0, None, Gtk.ListScrollFlags.NONE, None)
                return
        self._grow.stop()
        self._rows.splice(0, 0, tracks)
        if tracks:
            self.column_view.scroll_to(0, None, Gtk.ListScrollFlags.NONE, None)
        self._rows.splice(len(tracks), old, [])
        self._shown = tracks

    def _replace_rows(self, position, removed, tracks):
        """GrowBack's change: tracks at position, in place of `removed` rows."""
        self._rows.splice(position, removed, tracks)

    def _update_state(self, *_args):
        total = len(self._ordered)
        library = self._library
        name = songs_state(total, library.state, library.songs_ready,
                           library.songs.get_n_items(), library.syncing)
        self.stack.set_visible_child_name(name)
        self.filter_bar.set_available(name == 'items', self)
        self.sort_button.set_visible(name == 'items' and not self.selection_mode.active)
        self.selection_mode.set_available(name == 'items')
        if name == 'empty':
            # No songs to filter any more (a sign-out): the bar goes with its button. Not
            # while loading, which a filter set before the songs are built (set_filter)
            # waits through.
            self.filter_bar.close()
        if name != 'items':
            return
        shown = len(self._matches)
        self.results_stack.set_visible_child_name('table' if shown else 'no-results')
        self.play_button.set_sensitive(shown > 0)
        self.shuffle_button.set_sensitive(shown > 0)
        if not shown:
            favourites = self._favourites_only and not self._search
            self.no_results_page.set_icon_name(
                'heart-outline-symbolic' if favourites else 'edit-find-symbolic')
            self.no_results_page.set_title(
                _('No Favourite Songs') if favourites else _('No Results Found'))
            self.no_results_page.set_description(
                _('Songs you mark as favourites appear here') if favourites
                else _('Try a different filter'))
        if self._search or self._favourites_only:
            label = ngettext('{shown} of {total} song', '{shown} of {total} songs', total)
        else:
            label = ngettext('{total} song', '{total} songs', total)
        self.count_label.set_label(label.format(shown=f'{shown:n}', total=f'{total:n}'))

    def set_filter(self, text):
        """Filter the table by `text` at once, as typing it in the filter bar would after the
        entry's short delay (See All from a search's songs: the whole table must not show
        first), the bar shown with the text in it; closed, and the filter cleared, for no
        text."""
        self.filter_bar.set_text(text)

    def focus_content(self):
        """Ctrl+2 (win.focus-content): the focus in the table, as on the other library pages
        it goes to the list, from Play and Shuffle above it too (Shift+Tab reaches them);
        nothing moves when the focus is in the table already."""
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        if focus is not None and (focus is self.results_stack
                                  or focus.is_ancestor(self.results_stack)):
            return
        if (self.stack.get_visible_child_name() == 'items'
                and self.results_stack.get_visible_child_name() == 'table'
                and self.column_view.child_focus(Gtk.DirectionType.TAB_FORWARD)):
            return
        if not self.stack.child_focus(Gtk.DirectionType.TAB_FORWARD):
            self.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def focus_filter(self):
        """Show the filter bar with the cursor in its entry and its text selected (Ctrl+F on
        this page); False when the page has no songs to filter yet."""
        return self.filter_bar.focus()

    def _on_filter_changed(self, bar):
        self._search = bar.search
        self._follow = False
        self._filter()
        self._announce_count()

    def _announce_count(self):
        """Say the new count once the typing has paused (the entry's own delay), not at
        every keystroke."""
        if self.count_label.get_mapped():
            self.filter_bar.announce(self.count_label.get_label())

    def _focus_table(self, track):
        """Where Escape puts the focus once the filter bar has closed: the track's row (the
        one the focus was on), else the first; False while the table does not show."""
        if (not self.get_mapped() or self.results_stack.get_visible_child_name() != 'table'
                or not self._rows.get_n_items()):
            return False
        self._grow.finish()  # every row there, if the table was growing back
        found, position = self._rows.find(track) if track is not None else (False, 0)
        focus_position(self.column_view, position if found else 0)
        return True

    @Gtk.Template.Callback()
    def on_activate(self, _column_view, position):
        """A row activated (a click, Enter): played, or in the selection mode (a Ctrl+click
        or Shift+click enters it) toggled or extended to."""
        track = self._rows.get_item(position)
        if track is not None and not self.selection_mode.activated(track):
            self.get_root().play_request(track.play, start_with=track.index,
                                         start_id=track.id)

    def _on_play_clicked(self, _button, shuffle):
        """Play or Shuffle: the songs shown, in order (play_target()); Play turns shuffle
        off, Shuffle on, as an album's buttons do."""
        play = play_target(self._matches, shuffle)
        if play is not None:
            self.get_root().play_request(play, shuffle=shuffle)

    # Cells. The time is a Gtk.Inscription: its size comes from its line count, not its text,
    # so rebinding it redraws it without laying it out again; in tabular figures, so that
    # the digits line up, and on the left, under its column's title, which a Gtk.ColumnView
    # cannot align (Nautilus's list view does the same). The title, the artist and the
    # album are one-line labels (the badge follows the title's text, a link is only its
    # text), which a single line keeps cheap to measure again.

    def _factory(self, setup, bind, unbind=None):
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', setup)
        factory.connect('bind', bind)
        if unbind is not None:
            factory.connect('unbind', unbind)
        return factory

    def _text_factory(self, name, numeric=False):
        def setup(_factory, cell):
            # Centred at its one line's height: given the row's height, it would wrap text
            # too long for the column onto a second line.
            inscription = Gtk.Inscription(xalign=0, valign=Gtk.Align.CENTER,
                                          text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END)
            if numeric:
                inscription.add_css_class('numeric')
            cell.set_child(inscription)

        def bind(_factory, cell):
            cell.get_child().set_text(getattr(cell.get_item(), name))

        return self._factory(setup, bind)

    def _link_factory(self, kind):
        """The artist's or the album's cells: TrackLinks, one-line labels as wide as their
        text, so that only the text is the link."""
        def setup(_factory, cell):
            cell.set_child(TrackLink(kind))

        def bind(_factory, cell):
            cell.get_child().show(cell.get_item())

        return self._factory(setup, bind)

    def _bind_row(self, _factory, row):
        track = row.get_item()
        self._row_items.add(row)
        row.set_accessible_label(track_label(track, favourite=self._library.is_favourite(track)))
        selection = self.selection_mode.selection
        row.set_accessible_description(row_description(
            selection.active, selection.has(track),
            self._playing.description(track, self._playing.matches(track))))

    def _unbind_row(self, _factory, row):
        self._row_items.discard(row)

    def _setup_title(self, _factory, cell):
        cell.set_child(SongTitle())

    def _bind_title(self, _factory, cell):
        track = cell.get_item()
        self._title_cells.add(cell)
        selection = self.selection_mode.selection
        title = cell.get_child()
        title.bind(track, self._playing.matches(track), self._library.is_favourite(track),
                   self._stacked)
        title.set_selected(selection.active, selection.has(track))
        if not self._bound:
            self._bound = True
            mark_bound(self)

    def _unbind_title(self, _factory, cell):
        self._title_cells.discard(cell)
        cell.get_child().unbind()

    def _set_stacked(self, _breakpoint, stacked):
        """The narrow breakpoint applied (`stacked`) or not: the bound title cells show the
        artist under the title, or not, and the cells bound from now on follow."""
        self._stacked = stacked
        for cell in self._title_cells:
            cell.get_child().set_stacked(stacked)
        self.selection_mode.set_narrow(stacked)  # the selection bar's narrow layout too

    # Favourites.

    def _on_favourites_only(self, action, value):
        """The menu's Favourites Only: the table shows the favourites alone, or every song;
        remembered for the page (grid.remember_favourites_only)."""
        action.set_state(value)
        favourites = value.get_boolean()
        if favourites == self._favourites_only:
            return
        self._favourites_only = favourites
        from .grid import remember_favourites_only
        remember_favourites_only(self.get_tag(), favourites)
        self._follow = False
        self._filter()
        self._announce_count()

    def _on_favourites_changed(self, *_args):
        """The account's favourites changed (a sync, or a heart here): the bound rows show
        them again, and Favourites Only shows the new ones, keeping its place."""
        is_favourite = self._library.is_favourite
        self._kept = (None, False, {})  # the favourites the matches were of are not these
        for cell in self._title_cells:
            cell.get_child().set_favourite(is_favourite(cell.get_item()))
        for row in self._row_items:
            track = row.get_item()
            row.set_accessible_label(track_label(track, favourite=is_favourite(track)))
        if self._favourites_only and self._ordered:
            self._follow = True
            self._filter()

    # The song playing.

    def _on_track_changed(self, _player, _pspec):
        self._update_playing()

    def _update_playing(self):
        """Mark the row of the song playing now, and no other, when the item changed."""
        if not self._playing.update():
            return
        for cell in self._title_cells:
            cell.get_child().set_playing(self._playing.matches(cell.get_item()))
        self._describe_rows()

    def _describe_rows(self):
        selection = self.selection_mode.selection
        for row in self._row_items:
            track = row.get_item()
            row.set_accessible_description(row_description(
                selection.active, selection.has(track),
                self._playing.description(track, self._playing.matches(track))))

    # The selection mode.

    def _selectable(self):
        """The songs the table shows, in order: what the selection mode selects among."""
        return self._matches if self.stack.get_visible_child_name() == 'items' else []

    def _on_selection_changed(self, selection):
        """The bound rows' check boxes and descriptions; Sort and Filter left out of the
        header bar in the mode, for Cancel."""
        self.sort_button.set_visible(self.stack.get_visible_child_name() == 'items'
                                     and not selection.active)
        for cell in self._title_cells:
            cell.get_child().set_selected(selection.active, selection.has(cell.get_item()))
        self._describe_rows()

    def focused_track(self, focus):
        """The Track of the row with the focus `focus` in the table, or None (the window's
        selection keys: keyboard.selection_key())."""
        track = context_menu.focused(self.column_view, focus)
        return track if isinstance(track, Track) else None
