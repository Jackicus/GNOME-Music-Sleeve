# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The items and rows of a detail page's list (pages/detail.py): the marker items of the
sections that hold no tracks (the hero, the suggestions, the footer, the catalog's shelves), and
_Row, a row that shows a track or one of the page's widgets in their place."""

from gi.repository import GObject, Gtk

from ..widgets.track_row import TrackRow


class _Hero(GObject.Object):
    """The first item of a detail page's list: where the hero goes."""

    __gtype_name__ = 'AppleMusicDetailHero'


class _Suggestions(GObject.Object):
    """The last item of a playlist's list, while it has suggestions: where they go."""

    __gtype_name__ = 'AppleMusicDetailSuggestions'


class _Footer(GObject.Object):
    """The item after an album's tracks: where its release footer goes."""

    __gtype_name__ = 'AppleMusicDetailFooter'


class _Shelves(GObject.Object):
    """The last item of an album's or a catalog playlist's list, while the catalog has
    shelves of it: where they go."""

    __gtype_name__ = 'AppleMusicDetailShelves'


class _Row(Gtk.Box):
    """A row of a detail page's list: a TrackRow, or a widget of the page's (the hero, the
    suggestions) in its place."""

    def __init__(self):
        # Vertical, though it shows one child at a time: a horizontal box measures its
        # children's height without the width (for its minimum), and the suggestions' grid
        # is taller the narrower it is, which made the row's minimum height above its natural
        # one (GTK's "natural size must be >= min size").
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        # Given the row's whole height (the list's rows keep a minimum, style.css), which
        # the track row centres itself in: a vertical box would otherwise leave the rest
        # under it.
        self.track_row = TrackRow(hexpand=True, vexpand=True)
        self.append(self.track_row)

    def show_widget(self, widget):
        self._remove_widgets(keep=widget)
        parent = widget.get_parent()
        if parent is not self:
            if parent is not None:
                parent.remove(widget)
            self.append(widget)
        self.track_row.set_visible(False)

    def show_track(self, track, album_artist, table=False, playing=False, favourite=False,
                   columns=frozenset()):
        self._remove_widgets()
        self.track_row.set_visible(True)
        self.track_row.bind(track, album_artist, table, playing, favourite, columns)

    def clear(self):
        self._remove_widgets()
        self.track_row.unbind()

    def _remove_widgets(self, keep=None):
        child = self.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            if child is not self.track_row and child is not keep:
                self.remove(child)
            child = following


def _row_of(widget):
    """The _Row a widget is in (picked or focused in the list: the list item's own widget
    holds its row), or None."""
    row = widget if isinstance(widget, _Row) else widget.get_ancestor(_Row)
    if row is None and isinstance(widget.get_first_child(), _Row):
        row = widget.get_first_child()
    return row
