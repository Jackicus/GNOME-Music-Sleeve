# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSuggestedSongs: a playlist's Suggested Songs (pages/detail.py), its title, a line
under it and a Refresh button over a grid of the songs, as music.apple.com shows them under
a playlist; AppleMusicSuggestionGrid, that grid; AppleMusicSuggestionRow, one song in it.

The grid shows every song it is given (six or twelve: suggestions.py), in as many columns as
fit the width and divide their number (suggestions.columns_for()), so its rows are full and
nothing scrolls sideways. set_items() keeps a row where its song stays and binds a row again
in place of a song that went, so a song added gives its place to the next one there.

Each row is a flat button with the song's cover, title and artist and album, which plays it
(`play-song`: in full, or its preview, as the page decides), and an Add button beside it
(`add-song`); Refresh emits `refresh`. set_previewing(id) marks the row of the song whose
preview plays: a stop icon over its cover, "Previewing" as its description. A right
click, a long press or the Menu key opens a song's context menu (context_menu.attach()).
"""

from gettext import gettext as _

from gi.repository import Gdk, GObject, Gtk, Pango

from ..suggestions import columns_for
from . import context_menu
from .labels import suggestion_label
from .song_shelf import SongRow
from .util import connect_weak, weak_method

COLUMN_WIDTH = 300  # a song's narrowest column: two fit a 720 px window's content, one 360
COLUMN_SPACING = 12
ROW_SPACING = 0


class SuggestionRow(Gtk.Box):
    """A suggested song: the button that plays it (`play_button`, a SongRow inside) and its
    Add button (`add_button`). bind(item) and unbind()."""

    __gtype_name__ = 'AppleMusicSuggestionRow'

    def __init__(self):
        super().__init__(spacing=6)
        self.song_row = SongRow(suggestion=True)
        self.play_button = Gtk.Button(child=self.song_row, hexpand=True)
        self.play_button.add_css_class('flat')
        self.play_button.add_css_class('suggestion')
        self.append(self.play_button)
        self.add_button = Gtk.Button(icon_name='list-add-symbolic',
                                     tooltip_text=_('Add to Playlist'),
                                     valign=Gtk.Align.CENTER)
        self.add_button.add_css_class('flat')
        self.add_button.add_css_class('circular')
        self.append(self.add_button)

    @property
    def context_item(self):
        """The song shown, for its context menu (widgets/context_menu.py)."""
        return self.song_row.context_item

    def bind(self, item):
        self.song_row.bind(item)
        self.play_button.update_property([Gtk.AccessibleProperty.LABEL],
                                         [suggestion_label(item)])
        self.set_previewing(False)

    def unbind(self):
        self.song_row.unbind()
        self._previewing = None

    _previewing = None  # whether the row shows its song's preview playing (None: unbound)

    def set_previewing(self, previewing):
        """Mark the row as the song whose preview plays, or not."""
        previewing = bool(previewing)
        if previewing == self._previewing:
            return
        self._previewing = previewing
        self.song_row.set_previewing(previewing)
        # Translators: a suggested song's description while its 30-second preview plays.
        self.play_button.update_property([Gtk.AccessibleProperty.DESCRIPTION],
                                         [_('Previewing') if previewing else ''])


class SuggestionGrid(Gtk.Widget):
    """The rows of the suggested songs, laid out in columns_for() columns of equal width,
    row by row in their order (which is also Tab's)."""

    __gtype_name__ = 'AppleMusicSuggestionGrid'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rows = []  # SuggestionRow, one a song, in order
        self.make_row = SuggestionRow  # a new row (the section connects its buttons)

    def set_items(self, items):
        """Show `items` (song Items), keeping each row whose song stays in its place."""
        for index, item in enumerate(items):
            if index == len(self.rows):
                row = self.make_row()
                row.set_parent(self)
                self.rows.append(row)
            row = self.rows[index]
            if row.context_item is not item:
                row.bind(item)
        while len(self.rows) > len(items):
            row = self.rows.pop()
            row.unbind()
            row.unparent()
        self.queue_resize()

    def clear(self):
        self.set_items([])

    def columns(self, width):
        return columns_for(width, len(self.rows), COLUMN_WIDTH, COLUMN_SPACING)

    def do_dispose(self):
        self.clear()
        Gtk.Widget.do_dispose(self)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _row_height(self, width):
        return max((row.measure(Gtk.Orientation.VERTICAL, width)[1] for row in self.rows),
                   default=0)

    def _column_width(self, width, columns):
        return max((width - (columns - 1) * COLUMN_SPACING) // columns, 0)

    def do_measure(self, orientation, for_size):
        if not self.rows:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum = max(row.measure(orientation, -1)[0] for row in self.rows)
            natural = max(minimum, COLUMN_WIDTH)
            return minimum, natural, -1, -1
        width = for_size if for_size >= 0 else COLUMN_WIDTH
        columns = self.columns(width)
        lines = -(-len(self.rows) // columns)
        height = (lines * self._row_height(self._column_width(width, columns))
                  + (lines - 1) * ROW_SPACING)
        return height, height, -1, -1

    def do_size_allocate(self, width, _height, _baseline):
        if not self.rows:
            return
        columns = self.columns(width)
        column_width = self._column_width(width, columns)
        row_height = self._row_height(column_width)
        for index, row in enumerate(self.rows):
            line, column = divmod(index, columns)
            rect = Gdk.Rectangle()
            rect.x = column * (column_width + COLUMN_SPACING)
            rect.y = line * (row_height + ROW_SPACING)
            rect.width, rect.height = column_width, row_height
            row.size_allocate(rect, -1)


class SuggestedSongs(Gtk.Box):
    """A playlist's Suggested Songs: set_items(items) shows them (see the module)."""

    __gtype_name__ = 'AppleMusicSuggestedSongs'

    __gsignals__ = {
        'play-song': (GObject.SignalFlags.RUN_FIRST, None, (GObject.Object,)),
        'add-song': (GObject.SignalFlags.RUN_FIRST, None, (GObject.Object,)),
        'refresh': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, **kwargs)
        self.add_css_class('suggested-songs')
        header = Gtk.Box(spacing=6)
        header.add_css_class('shelf-header')
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                       hexpand=True)
        # Translators: the title of the songs Apple Music suggests adding to a playlist,
        # shown under its songs.
        self.title_label = Gtk.Label(label=_('Suggested Songs'), xalign=0,
                                     ellipsize=Pango.EllipsizeMode.END)
        self.title_label.add_css_class('title-2')
        text.append(self.title_label)
        # Translators: the line under a playlist's Suggested Songs.
        self.subtitle_label = Gtk.Label(label=_('Based on what’s in this playlist'), xalign=0,
                                        wrap=True)
        self.subtitle_label.add_css_class('dimmed')
        text.append(self.subtitle_label)
        header.append(text)
        self.refresh_button = Gtk.Button(icon_name='view-refresh-symbolic',
                                         tooltip_text=_('Suggest Other Songs'),
                                         valign=Gtk.Align.CENTER)
        self.refresh_button.add_css_class('flat')
        self.refresh_button.add_css_class('circular')
        header.append(self.refresh_button)
        self.append(header)

        self.grid = SuggestionGrid()
        # Held by the grid, a child: a bound method would keep this section alive.
        self.grid.make_row = weak_method(self._make_row)
        self.grid.update_property([Gtk.AccessibleProperty.LABEL], [_('Suggested Songs')])
        self.append(self.grid)
        connect_weak(self.refresh_button, 'clicked', self._on_refresh_clicked)
        context_menu.attach(self.grid)

    @property
    def items(self):
        """The songs shown, in their order."""
        return [row.context_item for row in self.grid.rows]

    def set_items(self, items):
        self.grid.set_items(items)
        self.set_previewing(self._previewing)

    _previewing = ''  # the catalog id of the song whose preview plays, or ''

    def set_previewing(self, song_id):
        """Mark the row of the song `song_id` (a catalog id; '' for none) as previewing."""
        self._previewing = song_id or ''
        for row in self.grid.rows:
            item = row.context_item
            row.set_previewing(bool(self._previewing) and item is not None
                               and item.id == self._previewing)

    def _make_row(self):
        # The row's buttons are connected weakly, and the row found from the button: a
        # handler holding the row (or this section) would keep it alive through its child.
        row = SuggestionRow()
        connect_weak(row.play_button, 'clicked', self._on_play_clicked)
        connect_weak(row.add_button, 'clicked', self._on_add_clicked)
        return row

    @staticmethod
    def _song(button):
        row = button.get_ancestor(SuggestionRow)
        return row.context_item if row is not None else None

    def _on_play_clicked(self, button):
        song = self._song(button)
        if song is not None:
            self.emit('play-song', song)

    def _on_add_clicked(self, button):
        song = self._song(button)
        if song is not None:
            self.emit('add-song', song)

    def _on_refresh_clicked(self, _button):
        self.emit('refresh')
