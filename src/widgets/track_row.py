# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicTrackRow: a track of an album or playlist, as a detail page's list shows it, and
the header over a playlist's table (TrackTableHeader); is_playing(), how the pages tell the
row of the track playing."""

from gettext import gettext as _

from gi.repository import Gtk

from ..song_columns import year_text
from .cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from .track_links import TrackLink

# The thumbnail's edge in a playlist's rows (track_row.blp's cover), which the header's first
# column leaves room for.
COVER_SIZE = 40
# A favourite's heart before a row's time (track_row.blp's favourite_icon), which the header
# leaves room for before Time.
FAVOURITE_SIZE = 12
# A table's Year column (song_columns.py), its rows' years and the header's title alike:
# four digits, or "Year" in the header's caption-heading.
YEAR_WIDTH = 40

_words = {}


def playing_ids(now_playing):
    """What marks the rows of the item playing (player.track, a NowPlaying): its library id
    and its catalog id, each '' when it has none; None for nothing playing. A page computes
    it once per track change and compares it in every bind (is_playing())."""
    if now_playing is None:
        return None
    return now_playing.id or '', now_playing.catalog_id or ''


def is_playing(track, playing):
    """Whether `track` (a library Track) is the item playing, `playing` as playing_ids() gives
    it: the same library id (a library song MusicKit plays by its own id), or the same catalog
    id (the same song played from the catalog, or in another album or playlist)."""
    if playing is None:
        return False
    playing_id, catalog_id = playing
    if playing_id and track.id == playing_id:
        return True
    return bool(catalog_id) and track.catalog_id == catalog_id


def _word(key):
    """A row's words, looked up once: rows are bound by the thousand."""
    if not _words:
        _words['playing'] = _('Playing')
        # Translators: a track of a pre-release album that is not out yet: its row's
        # tooltip and description (it cannot be played).
        _words['unreleased'] = _('Not yet released')
    return _words[key]


def playing_description():
    """"Playing": a row's accessible description while its track is the one playing (the
    play icon it shows is decoration)."""
    return _word('playing')


def unreleased_description():
    """"Not yet released": the tooltip and accessible description of the row of a track
    not out yet (Track.unreleased), which is dimmed and does not play."""
    return _word('unreleased')


class PlayingMark:
    """What a page keeps to mark the rows of the track playing: the Player's item, as
    playing_ids() reduces it, read again by update() (on the Player's `notify::track`, and
    as the page maps) and compared in every bind by matches(). `player` may be None (a
    test's stand-in application without one): nothing is playing then.

        self._playing = PlayingMark(getattr(app(), 'player', None))
        row.bind(track, playing=self._playing.matches(track))
        list_item.set_accessible_description(self._playing.description(track, playing))
        if self._playing.update():        # the item changed: mark the bound rows again
    """

    def __init__(self, player):
        self.player = player
        self.ids = None  # playing_ids() of the item playing, as last read

    def update(self):
        """Read the item playing again: True when it is not the one read before, so that a
        page marks its bound rows again only then."""
        ids = playing_ids(self.player.track) if self.player is not None else None
        if ids == self.ids:
            return False
        self.ids = ids
        return True

    def matches(self, track):
        """Whether track is the item playing, as last read."""
        return is_playing(track, self.ids)

    @staticmethod
    def description(track, playing):
        """A row's accessible description: "Playing" while its track is the one playing,
        "Not yet released" for a track not out yet, else the track's duration."""
        if playing:
            return playing_description()
        if getattr(track, 'unreleased', False):
            return unreleased_description()
        return track.duration_label or ''


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/track_row.ui')
class TrackRow(Gtk.Box):
    """A leading track number (albums) or 40 px thumbnail (playlists), the title with an
    explicit badge, the artist under it when it says something, and the duration; or, as a
    playlist's table row (`table`), the thumbnail, the title, the artist and the album in
    three equal columns (the artist and the album links: widgets/track_links.py), the genre
    as a fourth and the year before the duration when the table shows those columns
    (bind()'s `columns`: song_columns.OPTIONAL names), and the duration.

    bind() and unbind() are called by a list factory as rows are recycled; the thumbnail is
    drawn only while the row is on screen (Cover). Activating the row is the list's business:
    the page plays the track's group from the track (window.play_request). The Track bound is
    the row's `context_item`: the view's context menu and drag (widgets/context_menu.py).

    In the list's selection mode the row starts with a check box (set_selected(), as the
    page reads the selection: widgets/selection_mode.py), shown only in the mode.

    The row of a track not out yet (Track.unreleased: a pre-release album's) is dimmed and
    says "Not yet released" in its tooltip; the page plays nothing for it.

    The row of the track playing (`playing`, set by bind() or set_playing() as the page
    follows the Player) shows a play icon in the number's slot, or over the thumbnail, and
    its title bold (style.css's `.playing`): nothing that changes its size. A favourite's row
    has a heart before the time (`favourite`, bind() or set_favourite()), shown by its opacity.
    """

    __gtype_name__ = 'AppleMusicTrackRow'

    _track = None
    _playing = False
    _favourite = False
    _selecting = False
    _selected = False
    _unreleased = False

    number_stack = Gtk.Template.Child()
    number_label = Gtk.Template.Child()
    cover_slot = Gtk.Template.Child()
    check = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    playing_scrim = Gtk.Template.Child()
    columns = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    explicit_badge = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()
    favourite_icon = Gtk.Template.Child()
    duration_label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # A table's artist and album columns, made here (GtkBuilder runs no Python __init__).
        self.artist_link = TrackLink('artist', hexpand=True, visible=False)
        self.album_link = TrackLink('album', hexpand=True, visible=False)
        self.columns.append(self.artist_link)
        self.columns.append(self.album_link)
        # The optional columns, made the first time the row shows them (_optional_labels():
        # most rows never do): the genre among the equal ones, the year beside the time.
        self.genre_label = None
        self.year_label = None
        self._table = False
        self._columns = frozenset()  # the optional columns the row shows

    @property
    def context_item(self):
        """The Track shown, for its context menu and its drag (widgets/context_menu.py)."""
        return self._track

    @property
    def playing(self):
        """Whether the row is marked as the track playing."""
        return self._playing

    def bind(self, track, album_artist=None, table=False, playing=False, favourite=False,
             columns=frozenset()):
        """Show track. album_artist given: an album's row, numbered, with the artist shown only
        when it is not the album's; None: a playlist's row, with thumbnail and artist, under
        the title, or with `table`, in a column of its own beside the album's, and the
        optional `columns` (song_columns.OPTIONAL names) the table shows. `playing`: the
        track is the one playing (is_playing()); `favourite`: one of the account's
        (Library.is_favourite), a heart before the time."""
        self._track = track
        album = album_artist is not None
        table = table and not album
        self._set_table(table, columns)
        self.number_stack.set_visible(album)
        self.cover_slot.set_visible(not album)
        if album:
            self.number_label.set_text(str(track.track_number) if track.track_number else '')
            show_artist = bool(track.artist) and track.artist != album_artist
        else:
            self.cover.set_paths(track.thumb)
            show_artist = bool(track.artist) and not table
        self.title_label.set_text(track.title)
        self.explicit_badge.set_visible(track.explicit)
        self.artist_label.set_visible(show_artist)
        self.artist_label.set_text(track.artist if show_artist else None)
        if table:
            self.artist_link.show(track)
            self.album_link.show(track)
            if 'genre' in self._columns:
                self.genre_label.set_text(track.genre)
            if 'year' in self._columns:
                self.year_label.set_text(year_text(track.year))
        self.duration_label.set_text(track.duration_label)
        self.set_playing(playing)
        self.set_favourite(favourite)
        self._set_unreleased(getattr(track, 'unreleased', False))

    def _set_unreleased(self, unreleased):
        """Dim the row of a track not out yet, with its tooltip, or not (only when it
        changes)."""
        unreleased = bool(unreleased)
        if unreleased == self._unreleased:
            return
        self._unreleased = unreleased
        if unreleased:
            self.add_css_class('dimmed')
        else:
            self.remove_css_class('dimmed')
        self.set_tooltip_text(unreleased_description() if unreleased else None)

    def set_selected(self, selecting, selected=False):
        """In the list's selection mode (`selecting`) show the check box, ticked when
        `selected`; out of it, none. Only what changes is set: a check box shown or hidden
        lays the list out again, which the mode's start and end do once."""
        selecting = bool(selecting)
        selected = selecting and bool(selected)
        if selecting != self._selecting:
            self._selecting = selecting
            self.check.set_visible(selecting)
        if selected != self._selected:
            self._selected = selected
            self.check.set_active(selected)

    def set_favourite(self, favourite):
        """Show the heart of a favourite, or not: by its opacity, only when it changes."""
        favourite = bool(favourite)
        if favourite != self._favourite:
            self._favourite = favourite
            self.favourite_icon.set_opacity(1 if favourite else 0)

    def set_playing(self, playing):
        """Mark the row as the track playing, or not (only when it changes: a style change
        has the title measured again)."""
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        self.number_stack.set_visible_child_name('playing' if playing else 'number')
        self.playing_scrim.set_opacity(1 if playing else 0)
        if playing:
            self.add_css_class('playing')
        else:
            self.remove_css_class('playing')

    def _set_table(self, table, columns=frozenset()):
        """The table's columns, the optional ones among them, or the list's title and artist
        (only when it changes: a row shown or hidden lays the list out again)."""
        columns = frozenset(columns) if table else frozenset()
        if columns != self._columns:
            self._columns = columns
            self._optional_labels()
            self.genre_label.set_visible('genre' in columns)
            self.year_label.set_visible('year' in columns)
            if 'genre' not in columns:
                self.genre_label.set_text(None)
            if 'year' not in columns:
                self.year_label.set_text(None)
        if table == self._table:
            return
        self._table = table
        self.columns.set_homogeneous(table)
        self.artist_link.set_visible(table)
        self.album_link.set_visible(table)
        if not table:
            self.artist_link.show(None)
            self.album_link.show(None)

    def _optional_labels(self):
        """Make the optional columns' inscriptions, once."""
        if self.genre_label is not None:
            return
        self.genre_label = Gtk.Inscription(xalign=0, valign=Gtk.Align.CENTER, hexpand=True,
                                           text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END,
                                           visible=False)
        self.columns.append(self.genre_label)
        self.year_label = Gtk.Inscription(xalign=0, valign=Gtk.Align.CENTER,
                                          width_request=YEAR_WIDTH, visible=False,
                                          css_classes=['numeric'])
        self.insert_child_after(self.year_label, self.columns)

    def unbind(self):
        self._track = None
        self.cover.set_paths()


class TrackTableHeader(Gtk.Box):
    """The column titles over a playlist's table (Title, Artist, Album, Time, and Genre and
    Year when it shows them: set_columns()), laid out as its rows are (TrackRow with
    `table`), so that each title is over its column, and in the look of the Songs table's
    Gtk.ColumnView header (style.css's `.track-table-header`)."""

    def __init__(self, **kwargs):
        super().__init__(spacing=12, **kwargs)
        self.add_css_class('track-table-header')
        # Over the rows' check boxes in the selection mode: one of them, never seen, so the
        # titles keep over their columns.
        self._check = Gtk.CheckButton(visible=False, opacity=0, can_focus=False,
                                      can_target=False, css_classes=['selection-mode'],
                                      accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.append(self._check)
        self.append(Gtk.Box(width_request=COVER_SIZE))  # over the thumbnails
        self.columns = columns = Gtk.Box(spacing=12, homogeneous=True, hexpand=True)
        for title in (_('Title'), _('Artist'), _('Album')):
            columns.append(self._title(Gtk.Label(label=title, xalign=0)))
        self._genre = self._title(Gtk.Label(label=_('Genre'), xalign=0, visible=False))
        columns.append(self._genre)
        self.append(columns)
        self._year = self._title(Gtk.Label(label=_('Year'), xalign=0, visible=False,
                                           width_request=YEAR_WIDTH))
        self.append(self._year)
        self.append(Gtk.Box(width_request=FAVOURITE_SIZE))  # over the rows' hearts
        # "Time", as wide as the rows' durations: a stack sized by its widest child, an
        # inscription of the rows' duration_label's chars and classes that it never shows
        # (the title's smaller font would make the column narrower than theirs).
        time = Gtk.Stack(hhomogeneous=True)
        sizer = Gtk.Inscription(min_chars=5, nat_chars=7)
        sizer.add_css_class('numeric')
        time.add_child(sizer)
        time.add_child(self._title(Gtk.Label(label=_('Time'), xalign=1)))
        time.set_visible_child(time.get_last_child())
        self.append(time)

    def set_selecting(self, selecting):
        """Leave room for the rows' check boxes (the list's selection mode), or not."""
        self._check.set_visible(bool(selecting))

    def set_columns(self, columns):
        """Title the optional columns the rows show (song_columns.OPTIONAL names)."""
        self._genre.set_visible('genre' in columns)
        self._year.set_visible('year' in columns)

    @staticmethod
    def _title(label):
        label.add_css_class('caption-heading')  # the header's colour is the box's (style.css)
        return label
