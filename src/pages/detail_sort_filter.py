# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A playlist page's Sort By and filter: which of its songs the page shows, and in what
order, never the playlist's own.

A playlist's Sort By (sort_button, the header bar's, beside the filter's: PLAYLIST_SORTS,
Genre and Year among them, either way round) orders what the page shows, never the
playlist: each group's store passes through a Gtk.SortListModel of playlist_sorter() before
the filter, a text's descending order shown backwards (ShownModel), as the grids sort. It
lasts for the page's life; in any order but Playlist Order, first to last, no song moves
(can_reorder()).

A playlist's songs (Favourite Songs' too) have the library pages' filter bar
(widgets/filter_bar.py: Filter Songs, Ctrl+F through focus_filter(), typing on the page,
Escape), matching each song's title, artist and album: each group's store passes through a
Gtk.FilterListModel of the bar's text, shown through a ShownModel (filters_songs(); an
album's tracks are never filtered), and the sections' positions are worked out again as it
changes. While it filters, the songs cannot be moved (can_reorder()): the order shown is not
the playlist's. A filter that leaves none shows No Results Found in the status box, and the
new count is announced. Go to Current Song (reveal_playing()) clears a filter that hides the
song playing.
"""

import contextlib
from gettext import gettext as _
from gettext import ngettext

from gi.repository import GLib, Gtk

from ..library import Track
from ..widgets.filter_bar import ShownModel
from ..widgets.util import focus_position

# A playlist's Sort By, the order its page shows (never the playlist's own: Duplicate, Play
# and a reorder keep that): key -> (its menu label, the Track properties compared in turn;
# none, the playlist's order). Labels are looked up when a page is built; their mnemonics
# differ from one another's and from grid.sort_labels()' directions, as they share a menu.
PLAYLIST_SORTS = {
    'playlist': (lambda: _('_Playlist Order'), ()),
    'title': (lambda: _('_Title'), ('title', 'artist', 'album')),
    'artist': (lambda: _('_Artist'), ('artist', 'album', 'disc-number', 'track-number')),
    'album': (lambda: _('Al_bum'), ('album', 'disc-number', 'track-number')),
    'genre': (lambda: _('_Genre'), ('genre', 'artist', 'album', 'disc-number', 'track-number')),
    'year': (lambda: _('_Year'), ('year', 'artist', 'album', 'disc-number', 'track-number')),
    'time': (lambda: _('T_ime'), ('duration-ms', 'title')),
}
# The Track properties compared as numbers; the rest are text.
TRACK_NUMBERS = frozenset({'disc-number', 'track-number', 'duration-ms', 'year'})
# Playlist Order, first to last: the one order a playlist's songs can be moved in.
OWN_ORDER = ('playlist', False)


def playlist_sorter(key, descending=False):
    """The Gtk.Sorter that shows a playlist's songs by PLAYLIST_SORTS[key] (None for its own
    order), and whether that order is shown backwards (ShownModel), as grid.make_sorter()
    does: a number first (Time) is sorted the other way, its ties as they are; a text's or
    the playlist's own order is shown last to first."""
    names = PLAYLIST_SORTS[key][1]
    if not names:
        return None, descending
    sorter = Gtk.MultiSorter()
    for name in names:
        expression = Gtk.PropertyExpression.new(Track, None, name)
        if name in TRACK_NUMBERS:
            down = descending and name == names[0]
            sorter.append(Gtk.NumericSorter(
                expression=expression,
                sort_order=Gtk.SortType.DESCENDING if down else Gtk.SortType.ASCENDING))
        else:
            sorter.append(Gtk.StringSorter(expression=expression))
    return sorter, descending and names[0] not in TRACK_NUMBERS


def filters_songs(item):
    """Whether a page showing `item` offers a filter of its songs: a playlist's, not an
    album's (its tracks are a disc's, numbered)."""
    return item is not None and item.kind == 'playlist'


class SortFilterPart:
    """DetailPage's Sort By and filter (a mixin of pages/detail.py's DetailPage). It works on
    what DetailPage.__init__ makes and _show() sets: the filter bar and its SearchText
    (filter_bar, _text), the groups' models (_sorted, _filtered, _track_models), the sort
    actions and button (_sort_action, _order_action, sort_button) and _order, _starts,
    _groups, _track_total, list_view, selection_mode and item."""

    # A playlist's filter.

    def _on_filter_changed(self, bar):
        """The filter's text changed (after the entry's delay): the songs that match it
        shown, the sections after them placed again, the new count announced."""
        with contextlib.ExitStack() as stack:
            for model in self._track_models:
                stack.enter_context(model.replacing(self._scroll_top))
            self._text.set_search(bar.search, self._filtered)
        self._place_sections()
        self._update_filter()
        self.selection_mode.prune()
        if bar.search and self._track_models:
            # The filter's own count: the list may still be growing back to it (ShownModel).
            shown = sum(model.get_n_items() for model in self._filtered)
            total = self._track_total
            words = ngettext('{shown} of {total} song', '{shown} of {total} songs', total)
            bar.announce(words.format(shown=f'{shown:n}', total=f'{total:n}'))

    def _scroll_top(self):
        self.list_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)

    def _update_filter(self):
        """The filter offered while a playlist's songs show (closed otherwise); No Results
        Found in the status box while it leaves none."""
        offered = filters_songs(self.item) and bool(self._track_models)
        self.filter_bar.set_available(offered, self)
        if not offered:
            self.filter_bar.close()
        self._update_sort_button()
        none = offered and bool(self.filter_bar.search) and not self._shown_tracks()
        if none:
            self._show_status('no-results', _('No Results Found'), _('Try a different filter'),
                              None)
        self.status_box.set_visible(none or not self._groups)

    def focus_filter(self):
        """Ctrl+F: the filter bar shown with the cursor in its entry; False on a page with no
        songs to filter (an album's)."""
        return self.filter_bar.focus()

    def _focus_tracks(self, track):
        """Where Escape puts the focus once the filter bar has closed: the track's row (the
        one the focus was on), else the first song's; False while no songs show."""
        if self.stack.get_visible_child_name() != 'item' or not self._shown_tracks():
            return False
        position = None
        for model in self._track_models:
            if isinstance(model, ShownModel):
                model.finish()  # every row there, if the songs were growing back
        for start, model in zip(self._starts, self._track_models, strict=True):
            index = model.find(track) if isinstance(model, ShownModel) else None
            if index is not None:
                position = start + index
                break
        focus_position(self.list_view, self._starts[0] if position is None else position)
        return True

    # A playlist's Sort By: the order shown, not the playlist's.

    @property
    def order(self):
        """The order the songs show in: (PLAYLIST_SORTS key, descending)."""
        return self._order

    def _update_sort_button(self):
        """Sort By while a playlist's songs show, and not while selecting (Cancel takes its
        room, as on Songs)."""
        self.sort_button.set_visible(filters_songs(self.item) and bool(self._track_models)
                                     and not self.selection_mode.active)

    def _set_order_state(self, order):
        self._order = order
        self._sort_action.set_state(GLib.Variant('s', order[0]))
        self._order_action.set_state(GLib.Variant('s', 'descending' if order[1]
                                                  else 'ascending'))

    def _on_sort_chosen(self, _action, value):
        self.sort(value.get_string(), self._order[1])

    def _on_order_chosen(self, _action, value):
        self.sort(self._order[0], value.get_string() == 'descending')

    def sort(self, key, descending=False):
        """Show the songs by `key` (PLAYLIST_SORTS), `descending` or not: the view's order
        only, from the top. In any order but the playlist's own, first to last, no song
        moves (can_reorder())."""
        if key not in PLAYLIST_SORTS:
            return
        order = (key, bool(descending))
        if order == self._order:
            return
        self._set_order_state(order)
        sorter, backwards = playlist_sorter(*order)
        # One change of the same items each (a list keeps their rows), then the backwards.
        for model in self._sorted:
            model.set_sorter(sorter)
        for model in self._track_models:
            if isinstance(model, ShownModel):
                model.set_backwards(backwards)
        if self._track_models:
            self._scroll_top()
