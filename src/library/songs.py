# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Songs store's songs: SongEntry, the SongModel that makes a Track only for the rows
shown, the filter's matching, and SongOrder, the Songs table's sort."""

import heapq
import time
from array import array

from gi.repository import Gio, GObject

from .objects import Track, track_search_key
from .pacing import FRAME_BUDGET, yield_to_frames
from .records import _ABSENT, _ID, TrackRecord, _number, _text, _tuple_item
from .text_keys import collation_key


class SongEntry:
    """A song of the Songs store (Library.songs) as it is held: `raw`, the TrackRecord (a
    loose song's dict) its Track wraps, `source`, where the Track is (the album Item, the
    number of its group, the group's play target and the album's thumbnail: one tuple for a
    group's songs; no Item for a loose song), and `place`, its place in that group. About 80
    bytes, where a Track costs 560 (its GObject, its wrapper, the wrapper's dict, its place
    in its Group's store): the store holds 40,000 of these, and the albums' groups are
    wrapped only for the songs a view shows (track()).

    It reads as a Track does where every song is read (`raw`, `id`, `title`, `artist`,
    `album`, `search_key`, made once and kept): the Songs page sorts and filters these, the
    Search page and the search provider look through them, and Library.is_favourite() takes
    one. track() is the album's own Track of it (Item.groups: wrapped then, the album's songs
    all at once, as its page wraps them), so a song is one Track wherever it shows; a loose
    song has a Track of its own, made once.
    """

    __slots__ = ('raw', 'source', 'place', '_search_key', '_track')

    def __init__(self, raw, source, place=0):
        self.raw = raw
        self.source = source  # (album Item or None, group number, play, thumb)
        self.place = place  # in the group's entries (not the Track's `index`, its queue's)
        self._search_key = None
        self._track = None

    @property
    def id(self):
        return _text(self.raw.get('id')) or None

    @property
    def title(self):
        return _text(self.raw.get('title')) or ''

    @property
    def artist(self):
        return _text(self.raw.get('artist')) or ''

    @property
    def album(self):
        return _text(self.raw.get('album')) or ''

    @property
    def search_key(self):
        if self._search_key is None:
            self._search_key = track_search_key(self.raw)
        return self._search_key

    def track(self):
        """The song's Track: its album's (wrapping the album's groups the first time), or
        its own, made once, for a loose song or for one whose album's groups have changed
        since the store was filled (the next fill makes it a new entry)."""
        if self._track is not None:
            return self._track
        item, group, play, thumb = self.source
        if item is not None:
            groups = item.groups
            if group < len(groups):
                entries = groups[group].entries
                if self.place < entries.get_n_items():
                    track = entries.get_item(self.place)
                    if track.raw is self.raw:
                        return track
        self._track = Track(self.raw, play, thumb)
        self._track._search_key = self._search_key
        if item is not None and item.raw.get('prerelease'):
            self._track._release = item.raw.get('releaseDate')
        return self._track

    def __repr__(self):
        return f'<SongEntry {self.id}>'


def song_track(song):
    """The Track of a song as a SongModel holds it: a SongEntry's track(), or a Track itself
    (a model may be given Tracks: a test's stand-ins)."""
    return song if isinstance(song, Track) else song.track()


def song_tracks(songs):
    """song_track() of each of `songs`, in order."""
    return [song_track(song) for song in songs]


async def make_song_tracks(songs, budget=FRAME_BUDGET):
    """song_track() of each of `songs`, in order, a frame let in (yield_to_frames) every
    `budget` seconds: a selection of 40,000 songs wraps every album's groups, a quarter of a
    second at once (docs/notes.md)."""
    tracks = []
    paused = time.monotonic()
    for song in songs:
        tracks.append(song_track(song))
        if time.monotonic() - paused > budget:
            await yield_to_frames()
            paused = time.monotonic()
    return tracks


def song_key(song):
    """What a list of songs that may hold SongEntries and their Tracks knows a song by: its
    raw dict's identity, the same for an entry and its Track (SongModel.find())."""
    return id(song.raw)


def selection_key(song):
    """What a selection (selection.Selection) knows a song by through a reload: its own id,
    the same for a SongEntry and its Track and for the new record a changed album or
    playlist gives it (Item.merge()), else, without one, its record's identity. The Songs
    store holds each id once; a list that may hold a song twice (a playlist) tells its
    entries apart by selection.Places. A TrackRecord's id is read straight from the tuple:
    keep() and ordered() run this on each of 40,000 songs (docs/notes.md)."""
    raw = song.raw
    if type(raw) is TrackRecord:
        value = _tuple_item(raw, _ID)
        return value if value is not _ABSENT and value else id(raw)
    return _text(raw.get('id')) or id(raw)


def narrows(old, new):
    """Whether everything the folded filter text `new` matches matched `old` too, so that
    only `old`'s matches need testing again: `old` is part of `new` (a key typed, at the end
    or anywhere), and was some text (no text matched everything without a test)."""
    return bool(old) and old in new


def songs_matching(songs, search, within=None):
    """The songs (SongEntries or Tracks) whose search_key holds `search`, folded (fold()),
    in their order; none for no search. `within`, the matches of a text `search` holds
    (narrows()), are the only songs that can match: only they are tested."""
    if not search:
        return []
    return [song for song in (songs if within is None else within)
            if search in song.search_key]


async def prepare_search_keys(songs, step=1000):
    """Make every song's search_key (each keeps its own) a STEP at a time, with a pause for a
    frame (yield_to_frames) every FRAME_BUDGET: 40,000 songs' words take 60 ms to fold."""
    paused = time.monotonic()
    for start in range(0, len(songs), step):
        for song in songs[start:start + step]:
            song.search_key  # noqa: B018  (made and kept)
        if time.monotonic() - paused > FRAME_BUDGET:
            await yield_to_frames()
            paused = time.monotonic()


class SongModel(GObject.Object, Gio.ListModel):
    """A list model of Tracks held as SongEntries (`entries`, in order; Tracks may be among
    them), each wrapped in its Track only when a view asks for that item (song_track()), so
    a list of 40,000 songs makes Tracks for the rows it shows. splice() changes it as a
    Gio.ListStore's does (apply_diff() takes it), with the entries, and counts itself in
    `changes`; find() looks for a Track or an entry by song_key().

    Library.songs is one, the Songs page's rows another, and the Search page's and Add
    Songs…'s matches others: GLib and Gio only, the item type Track."""

    __gtype_name__ = 'AppleMusicSongModel'

    def __init__(self, entries=()):
        super().__init__()
        self.entries = list(entries)
        # How many splices have changed it: a page that stopped following its items-changed
        # (the Songs page while unrealized) tells by this whether it missed one.
        self.changes = 0

    def do_get_item_type(self):
        return Track.__gtype__

    def do_get_n_items(self):
        return len(self.entries)

    def do_get_item(self, position):
        if position < len(self.entries):
            return song_track(self.entries[position])
        return None

    def splice(self, position, removed, entries):
        """Remove `removed` entries at `position` and put `entries` there (items-changed)."""
        entries = list(entries)
        self.entries[position:position + removed] = entries
        self.changes += 1
        self.items_changed(position, removed, len(entries))

    def find(self, song):
        """(True, its position) for the Track or entry `song`, else (False, 0), as
        Gio.ListStore.find() answers."""
        key = song_key(song)
        for position, entry in enumerate(self.entries):
            if entry is song or id(entry.raw) == key:
                return True, position
        return False, 0


class SongOrder:
    """The Songs table's orders, sorted in Python.

    A column's order is its own key, ascending or descending, with ties broken by the other
    columns, always ascending (by artist, the albums and their tracks stay in order either
    way). GTK's sorters are too slow here: they read a Track's properties from C, which costs
    about 3 µs a read into Python, and a Gtk.ColumnViewSorter has no sort keys, so a
    Gtk.SortListModel sorting by it compares pairs and reads both tracks for every comparison:
    1.6 to 6 s a click on 30,000 songs. Here each key is computed once per track and kept, and
    Python sorts positions.

    A text column's key is a rank: its distinct texts are collated (once each) and sorted, and
    each track keeps the number of its text's place, texts that collate alike sharing one. The
    collation keys go once the column is ranked, and the ranks, the numbers and the tie orders
    are kept in arrays of machine integers: 40,000 songs' four columns keep 3 MB, where
    collation keys and lists of Python objects kept 22. Sorting by ranks orders exactly as
    sorting by the collation keys did. On 40,000 songs (en_GB) the title order's keys are
    prepared in 190 ms, in steps of under 10, and it is sorted in 30 ms; another order takes
    10 to 20 ms (45 for Time's first, which computes its numbers).
    """

    # Column -> the keys that break its ties, most significant first.
    TIES = {
        'title': ('artist', 'album', 'track'),
        'artist': ('album', 'track'),
        'album': ('artist', 'track'),
        'genre': ('artist', 'album', 'track'),
        'year': ('artist', 'album', 'track'),
        'time': ('title', 'artist'),
    }

    # How many tracks (or texts) the keys' computation takes on between two looks at the clock,
    # where prepare() pauses once FRAME_BUDGET has passed: 2 ms of work or less.
    STEP = 1000

    def __init__(self, tracks):
        self._tracks = list(tracks)
        self._keys = {}  # key name -> array: one rank or number per track
        self._ties = {}  # column -> array: positions in the order of its tie-breakers
        self._searched = False  # every track's search_key made (prepare())

    async def prepare(self, column):
        """Compute the keys tracks(column) needs, and make every track's search_key, with a
        pause for a frame (yield_to_frames) every FRAME_BUDGET, so that a page can build a big
        table's first order without a freeze (collating 40,000 titles takes about 100 ms in
        one go) and the first letter typed into its filter does not fold every song's words
        at once (60 ms). tracks() afterwards only sorts."""
        paused = time.monotonic()
        work = [(name, self._computing(name)) for name in (*reversed(self.TIES[column]), column)
                if name not in self._keys]
        if not self._searched:
            work.append((None, self._searching()))
        for name, steps in work:
            while True:
                try:
                    next(steps)
                except StopIteration as done:
                    if name is not None:
                        self._keys[name] = done.value
                    break
                if time.monotonic() - paused > FRAME_BUDGET:
                    await yield_to_frames()
                    paused = time.monotonic()

    def _searching(self):
        """Make every track's search_key (the Track keeps it), yielding after each STEP."""
        for start in range(0, len(self._tracks), self.STEP):
            for track in self._tracks[start:start + self.STEP]:
                track.search_key  # noqa: B018  (made and kept)
            yield
        self._searched = True

    def tracks(self, column, descending=False):
        """The tracks in column's order: 'title', 'artist', 'album', 'genre', 'year' or
        'time'."""
        ties = self._ties.get(column)
        if ties is None:
            order = list(range(len(self._tracks)))
            for name in reversed(self.TIES[column]):  # stable sorts, least significant first
                order.sort(key=self._key(name).__getitem__)
            ties = self._ties[column] = array('l', order)
        order = sorted(ties, key=self._key(column).__getitem__, reverse=descending)
        return [self._tracks[position] for position in order]

    def _key(self, name):
        keys = self._keys.get(name)
        if keys is None:
            steps = self._computing(name)
            while True:
                try:
                    next(steps)
                except StopIteration as done:
                    keys = self._keys[name] = done.value
                    break
        return keys

    def _computing(self, name):
        """Compute the key called `name` of every track, in their order, as a generator that
        yields after each STEP of work (where prepare() may pause) and returns the keys, an
        array. The raw dicts are read, not the properties: a property read costs a
        microsecond, and this reads every track.

        'time' is the duration, 'year' the year (0 unknown), 'track' the disc and track
        numbers as one number, which sorts as the pair does. A text column's key is a rank:
        its distinct texts are collated, sorted in runs of STEP and merged (40,000 distinct
        titles take 40 ms to sort in one go), and each takes the next rank but for one that
        collates as the one before it."""
        tracks, step = self._tracks, self.STEP
        keys = array('l')
        if name in ('time', 'track', 'year'):
            for start in range(0, len(tracks), step):
                if name == 'time':
                    keys.extend(_clamp(_number(track.raw.get('durationMs')))
                                for track in tracks[start:start + step])
                elif name == 'year':
                    keys.extend(_clamp(_number(track.raw.get('year')))
                                for track in tracks[start:start + step])
                else:
                    keys.extend(_clamp(_number(track.raw.get('discNumber')) * 1_000_000
                                       + _number(track.raw.get('trackNumber')))
                                for track in tracks[start:start + step])
                yield
            return keys
        collated = {}  # text -> its collation key, while ranking
        texts = []
        for start in range(0, len(tracks), step):
            for track in tracks[start:start + step]:
                text = _text(track.raw.get(name)) or ''
                texts.append(text)
                if text not in collated:
                    collated[text] = collation_key(text)
            yield
        distinct = list(collated)
        runs = []
        for start in range(0, len(distinct), step):
            runs.append(sorted(distinct[start:start + step], key=collated.__getitem__))
            yield
        ranks = {}
        rank, previous = -1, None
        for count, text in enumerate(heapq.merge(*runs, key=collated.__getitem__), 1):
            key = collated[text]
            if key != previous:
                rank, previous = rank + 1, key
            ranks[text] = rank
            if count % step == 0:
                yield
        del collated, distinct, runs
        for start in range(0, len(texts), step):
            keys.extend(ranks[text] for text in texts[start:start + step])
            yield
        return keys


def _clamp(number):
    """A number as an array('l') element holds it: huge values from a damaged file capped."""
    return max(-2**62, min(number, 2**62))
