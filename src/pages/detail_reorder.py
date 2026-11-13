# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Moving and removing a playlist's own songs on its page: a drag dropped back on it,
Alt+Up, Alt+Down, Alt+Home and Alt+End, and Delete.

On a playlist of the user's (PlaylistOrder.can_reorder(): not Favourite Songs, nor one of
Apple's) a song moves within the list: dragged (the row's own drag, widgets/dnd.py, dropped
here as a MOVE: an insertion line where it would go, the list scrolling near its edges, a
drop written at once) or with Alt+Up, Alt+Down, Alt+Home and Alt+End on the focused song
(keyboard.move_step(), the focus following it), as the row's menu's Move Up, Move Down, Move
to Top and Move to Bottom do; all through
ItemActions.move_in_playlist(), which announces where it went. A click without a drag
still plays the song: the drag starts only past GTK's drag threshold, and then cancels the
row's click. Delete on the focused song takes it out of the playlist (remove_focused():
keyboard.remove_key(), ItemActions.remove_entries()'s one write with Undo; in the selection
mode, the songs selected), one removal at a time, the focus going to the row in its place
once the songs show again; an empty playlist of the user's offers Add Songs… in its status.
"""

from gi.repository import Gdk, Graphene, Gtk

from .. import keyboard
from ..item_targets import is_manageable
from ..library import TRACK_REF_KINDS, Track, drop_index
from ..playlist_order import PlaylistOrder
from ..widgets import dnd
from ..widgets.filter_bar import ShownModel
from ..widgets.util import weak_method
from .detail_rows import _row_of
from .detail_sort_filter import OWN_ORDER


class ReorderPart:
    """DetailPage's moves and Delete (a mixin of pages/detail.py's DetailPage). It works on
    what DetailPage.__init__ makes: its state (_removing, _refocus), the drop target's
    _drop_feedback, the list (list_view, scrolled_window, hero, _bound, _starts,
    _track_models), selection_mode, filter_bar, _order, _groups and item; the songs show
    again with the focus through DetailPage._take_refocus()."""

    # Moving a playlist's songs.

    def can_reorder(self):
        """Whether the songs shown can be moved: a playlist of the user's with its one list
        (PlaylistOrder.can_reorder()), shown in its own order, first to last (no Sort By),
        and all of it (no filter), and not while its selection mode is on."""
        return (self._groups == 1 and self._order == OWN_ORDER and not self.filter_bar.search
                and not self.selection_mode.active and PlaylistOrder.can_reorder(self.item))

    def _move(self, from_index, to_index, at_once=False):
        """Move the song at from_index to to_index (ItemActions.move_in_playlist()): False
        when it did not move."""
        actions = getattr(self.get_root(), 'item_actions', None)
        move = getattr(actions, 'move_in_playlist', None)
        return move is not None and move(self.item, from_index, to_index, at_once)

    def _move_focused(self, focus, step):
        """Alt+Up or Alt+Down: the focused song one place up (-1) or down (1); Alt+Home or
        Alt+End: to the top or the bottom (keyboard.TOP, BOTTOM); the focus going with it.
        False (the key not taken) when the focus is on no song or the songs cannot be moved;
        True otherwise, at either end too, where nothing moves."""
        row = _row_of(focus) if focus is not None else None
        track = row.track_row.context_item if row is not None else None
        if not isinstance(track, Track) or not self.can_reorder():
            return False
        index, count = track.index, len(self.item.track_ids())
        to_index = keyboard.move_place(step, index, 0, count - 1)
        if to_index is not None and self._move(index, to_index):
            self.list_view.scroll_to(self._starts[0] + to_index, Gtk.ListScrollFlags.FOCUS,
                                     None)
        return True

    # Delete: a song taken out of the playlist.

    def removes_songs(self):
        """Whether Delete takes songs out of the playlist shown: one of the user's (not
        Favourite Songs, nor one of Apple's), in whatever order and filter it shows."""
        item = self.item
        return item is not None and item.kind == 'playlist' and is_manageable(item)

    def remove_focused(self, focus):
        """Delete on a song: Remove from Playlist (ItemActions.remove_entries(): one write,
        Undo on its toast) of the focused song or, in the selection mode, of the songs
        selected (the bar's Remove from Playlist); the focus goes to the row in its place
        once the songs show again. False (the key not taken) when the focus is on no song or
        the playlist is not the user's; True otherwise, while a removal is under way too,
        when nothing more is asked (one at a time: a second would be made on a list Apple
        has changed meanwhile)."""
        row = _row_of(focus) if focus is not None else None
        track = row.track_row.context_item if row is not None else None
        actions = getattr(self.get_root(), 'item_actions', None)
        if not isinstance(track, Track) or not self.removes_songs() or actions is None:
            return False
        if self._removing is not None and not self._removing.done():
            return True
        position = self._shown_position(track)
        if self.selection_mode.active:
            tracks = self.selection_mode.selection.ordered(self._selectable())
            if not tracks:
                return True
            self.selection_mode.leave()
        else:
            tracks = [track]
        task = actions.remove_entries(self.item, tracks)
        if task is None:
            return True  # the demo library, which says so
        self._removing = task
        self._refocus = (self.item, position) if position is not None else None
        done = weak_method(self._on_removed)
        task.add_done_callback(lambda finished: done(finished))
        return True

    def _shown_position(self, track):
        """The list position of the row showing `track` (among the tracks shown), or None."""
        for start, model in zip(self._starts, self._track_models, strict=True):
            index = model.find(track) if isinstance(model, ShownModel) else None
            if index is not None:
                return start + index
        return None

    def _on_removed(self, task):
        """Delete's removal ended: when it failed (reported already), the focus stays as it
        is; either way, no later showing of the songs moves it."""
        if self._removing is task:
            self._removing = None
        self._refocus = None

    def dragged_index(self):
        """The index of the song the in-app drag in progress carries (dnd.current()) when it
        is one of this playlist's own, to move within it; else None."""
        refs = dnd.current()
        if refs is None or len(refs) != 1 or not self.can_reorder():
            return None
        ref = refs.refs[0]
        if refs.origin != ('playlist', self.item.id) or ref.kind not in TRACK_REF_KINDS:
            return None
        ids = self.item.track_ids()
        return ref.index if 0 <= ref.index < len(ids) and ids[ref.index] == ref.id else None

    def drop_place(self, x, y):
        """Where a song dropped at (x, y) in the list goes: (gap, row, after), `gap` 0
        before the first song to n after the last of n, `row` the row the insertion line is
        drawn on (None when it is not made) and `after` whether on its bottom edge. Over a
        song, the gap above it or below it, by the half; over the hero, before the first;
        anywhere else (the suggestions, the footer, below the list), after the last."""
        count = len(self.item.track_ids() or ())
        picked = self.list_view.pick(x, y, Gtk.PickFlags.DEFAULT)
        row = _row_of(picked) if picked is not None else None
        track = row.track_row.context_item if row is not None else None
        if isinstance(track, Track) and 0 <= track.index < count:
            point = Graphene.Point()
            point.x, point.y = x, y
            ok, local = self.list_view.compute_point(row, point)
            after = ok and local.y >= row.get_height() / 2
            return track.index + (1 if after else 0), row, after
        if row is not None and self.hero.get_parent() is row:
            return 0, self._row_at(0), False
        return count, self._row_at(count - 1), True

    def show_insertion(self, index, after=False):
        """Draw the insertion line on the top (or, `after`, the bottom) edge of the row of
        the song at index, as a drag over it does (scripts/screenshot.py's --drop-line: no
        headless script can drag). False when the songs cannot be moved or the row is not
        made."""
        row = self._row_at(index) if self.can_reorder() else None
        if row is None:
            return False
        self._drop_feedback.insert(row.get_parent() or row, after)
        return True

    def _row_at(self, index):
        """The row showing the song at index, or None when the list has not made it."""
        position = self._starts[0] + index if self._starts else -1
        for list_item in self._bound:
            if list_item.get_position() == position:
                return list_item.get_child()
        return None

    def _on_drop_accept(self, _target, _drop):
        return self.dragged_index() is not None

    def _on_drop_motion(self, _target, x, y):
        """A drag over the list: the insertion line where the song would go (none in the
        gaps beside it, where it is), the list scrolled near its edges; the action."""
        from_index = self.dragged_index()
        if from_index is None:
            self._drop_feedback.clear()
            return 0
        point = Graphene.Point()
        point.x, point.y = x, y
        ok, scrolled = self.list_view.compute_point(self.scrolled_window, point)
        if ok:
            self._drop_feedback.motion(scrolled.y)
        gap, row, after = self.drop_place(x, y)
        if drop_index(from_index, gap) is None or row is None:
            self._drop_feedback.highlight(None)
            return 0
        # On the list's row, around the song's own padding: on the song's widget the line
        # would run behind its cover.
        self._drop_feedback.insert(row.get_parent() or row, after)
        return Gdk.DragAction.MOVE

    def _on_drop_leave(self, _target):
        self._drop_feedback.clear()

    def _on_drop(self, _target, _value, x, y):
        """A song of this playlist dropped on it: moved there, written at once."""
        self._drop_feedback.clear()
        from_index = self.dragged_index()
        if from_index is None:
            return False
        to_index = drop_index(from_index, self.drop_place(x, y)[0])
        return to_index is not None and self._move(from_index, to_index, at_once=True)
