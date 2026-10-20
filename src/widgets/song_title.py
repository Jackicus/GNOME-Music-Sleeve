# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSongTitle: the Songs table's title cell, a thumbnail, the title and an explicit
badge, a play icon over the thumbnail while the song is the one playing, a favourite's heart,
and in the narrow table, which has no Artist column, the artist under the title."""

from gi.repository import Gtk

from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/song_title.ui')
class SongTitle(Gtk.Box):
    """A track's 32 px thumbnail (its own, else its album's), its title and, for explicit
    tracks, an "E" badge; the title bold and a play icon over the thumbnail while the track
    is the one playing (`playing`, set by bind() or set_playing() as the Songs page follows
    the Player: style.css's `.playing`), and a heart at the cell's end for a favourite
    (`favourite`, shown by its opacity), none of which changes the cell's size. With
    set_stacked(True) (the narrow table, every cell at once) the artist shows in a dimmed
    line under the title.

    bind(track) and unbind() are called by the column's factory as rows are recycled. The
    thumbnail is an AppleMusicCover: asked for only while the cell is on screen, in an idle
    after the frame (a view creates and maps 200 rows at a time and shows a dozen; a re-sort
    rebinds them all), let go of when it is unmapped, and decoded at 32 px times the scale
    factor, which the Artwork cache holds thousands of.
    """

    __gtype_name__ = 'AppleMusicSongTitle'

    cover = Gtk.Template.Child()
    playing_scrim = Gtk.Template.Child()
    label = Gtk.Template.Child()
    explicit_badge = Gtk.Template.Child()
    favourite_icon = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()

    _track = None
    _playing = False
    _favourite = False
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

    def bind(self, track, playing=False, favourite=False, stacked=False):
        self._track = track
        self.cover.set_paths(track.thumb)
        self.label.set_text(track.title)
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
        self.artist_label.set_text(self._track.artist if self._stacked and self._track
                                   else None)
        self.artist_label.set_visible(self._stacked)

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
        self.playing_scrim.set_opacity(1 if playing else 0)
        if playing:
            self.add_css_class('playing')
        else:
            self.remove_css_class('playing')

    def unbind(self):
        self._track = None
        self.cover.set_paths()
