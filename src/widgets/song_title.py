# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSongTitle: the Songs table's title cell, a thumbnail, the title and an explicit
badge, a play icon over the thumbnail while the song is the one playing, a favourite's heart,
and in the narrow table, which has no Artist column, the artist under the title."""

from gi.repository import Gtk

from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .track_row import artist_line, check_box, explicit_badge, playing_scrim


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/song_title.ui')
class SongTitle(Gtk.Box):
    """A track's 32 px thumbnail (its own, else its album's), its title and, for explicit
    tracks, an "E" badge; the title bold and a play icon over the thumbnail while the track
    is the one playing (`playing`, set by bind() or set_playing() as the Songs page follows
    the Player: style.css's `.playing`), and a heart at the cell's end for a favourite
    (`favourite`, shown by its opacity), none of which changes the cell's size. With
    set_stacked(True) (the narrow table, every cell at once) the artist shows in a dimmed
    line under the title. In the table's selection mode the cell starts with a check box
    (set_selected(), widgets/selection_mode.py).

    bind(track) and unbind() are called by the column's factory as rows are recycled. The
    thumbnail is an AppleMusicCover: asked for only while the cell is on screen, in an idle
    after the frame (a view creates and maps 200 rows at a time and shows a dozen; a re-sort
    rebinds them all), let go of when it is unmapped, and decoded at 32 px times the scale
    factor, which the Artwork cache holds thousands of.

    The check box, the play icon, the badge and the artist's line are made the first time
    the cell shows one (a view keeps 200 rows and shows a dozen; their widgets were a quarter
    of each row's), and kept for its next tracks.
    """

    __gtype_name__ = 'AppleMusicSongTitle'

    cover_overlay = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    text_box = Gtk.Template.Child()
    title_box = Gtk.Template.Child()
    label = Gtk.Template.Child()
    favourite_icon = Gtk.Template.Child()

    _check = None
    _scrim = None
    _badge = None
    _artist = None

    _track = None
    _playing = False
    _favourite = False
    _selecting = False
    _selected = False
    _stacked = False

    @property
    def context_item(self):
        """The row's Track, for the Songs table's context menu and drag: the other cells of
        a row find it here (widgets/context_menu.py)."""
        return self._track

    @property
    def playing(self):
        """Whether the cell is marked as the track playing."""
        return self._playing

    @property
    def check(self):
        """The selection mode's check box, before the thumbnail (hidden out of the mode)."""
        if self._check is None:
            self._check = check_box()
            self._check.set_visible(False)
            self.prepend(self._check)
        return self._check

    @property
    def playing_scrim(self):
        """The play icon over the thumbnail, shown by its opacity."""
        if self._scrim is None:
            self._scrim = playing_scrim()
            self.cover_overlay.add_overlay(self._scrim)
        return self._scrim

    @property
    def explicit_badge(self):
        if self._badge is None:
            self._badge = explicit_badge()
            self._badge.set_visible(False)
            self.title_box.append(self._badge)
        return self._badge

    @property
    def artist_label(self):
        """The artist's line under the title (the narrow table)."""
        if self._artist is None:
            self._artist = artist_line()
            self._artist.set_visible(False)
            self.text_box.append(self._artist)
        return self._artist

    def bind(self, track, playing=False, favourite=False, stacked=False):
        self._track = track
        self.cover.set_paths(track.thumb)
        self.label.set_text(track.title)
        if track.explicit or self._badge is not None:
            self.explicit_badge.set_visible(track.explicit)
        self.set_playing(playing)
        self.set_favourite(favourite)
        if stacked != self._stacked:
            self.set_stacked(stacked)
        elif stacked:
            self.artist_label.set_text(track.artist)

    def set_stacked(self, stacked):
        """Show the artist in a line under the title (the narrow table, which hides its
        Artist column), or not. The line's text is set only while it shows."""
        self._stacked = bool(stacked)
        if not self._stacked and self._artist is None:
            return
        self.artist_label.set_text(self._track.artist if self._stacked and self._track
                                   else None)
        self.artist_label.set_visible(self._stacked)

    def set_selected(self, selecting, selected=False):
        """In the list's selection mode (`selecting`) show the check box, ticked when
        `selected`; out of it, none. Only what changes is set: a check box shown or hidden
        lays the list out again, which the mode's start and end do once."""
        selecting = bool(selecting)
        selected = selecting and bool(selected)
        if not selecting and self._check is None:
            return
        if selecting != self._selecting:
            self._selecting = selecting
            self.check.set_visible(selecting)
        if selected != self._selected:
            self._selected = selected
            self.check.set_active(selected)

    def set_favourite(self, favourite):
        """Show the heart at the cell's end for one of the account's favourites
        (Library.is_favourite), or not: by its opacity, only when it changes."""
        favourite = bool(favourite)
        if favourite != self._favourite:
            self._favourite = favourite
            self.favourite_icon.set_opacity(1 if favourite else 0)

    def set_playing(self, playing):
        """Mark the cell as the track playing, or not (only when it changes: a style change
        has the title measured again)."""
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        if playing or self._scrim is not None:
            self.playing_scrim.set_opacity(1 if playing else 0)
        if playing:
            self.add_css_class('playing')
        else:
            self.remove_css_class('playing')

    def unbind(self):
        self._track = None
        self.cover.set_paths()
