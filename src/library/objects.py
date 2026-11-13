# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The GObjects the pages bind: Item, its Groups and their Tracks, and ShelfModel, read from
their raw dicts.

Their properties are real GObject properties read from `raw` at each access
(raw_property(), model_property()). A playlist's songs in a new order (Item.reorder()) and the
pure functions behind it are here too.
"""

import collections

from gi.repository import Gio, GObject

from .diff import apply_diff
from .records import (TrackRecord, _dicts, _entries, _is_count, _number, _reader, _text,
                      added_seconds, release_passed)
from .text_keys import search_key
from .words import albums_text, songs_text, unknown_title


# The key in a playlist's raw `attributes` that marks it as Favourite Songs, the playlist of the
# songs the user loves. Not part of the README's Item shape: the demo library sets it, and the
# sync maps Apple's own flag onto it.
FAVOURITES = 'isFavourites'

# The key in a playlist's raw `attributes` that is false when songs cannot be added to it
# (Apple's canEdit, which the sync copies there when it is false).
EDITABLE = 'canEdit'

# The key in a playlist's raw `attributes` that is false when it cannot be removed from the
# library (Apple's canDelete, which the sync copies there when it is false).
REMOVABLE = 'canDelete'

# The key in a playlist's raw `attributes` that is true when it is public: shown on the
# account's profile and in search (Apple's isPublic, which the sync copies there when it is
# true). The playlist dialog shows it, and Edit Details… changes it.
PUBLIC = 'isPublic'


# A track's kind by the API resource `type` its entry carries: what it is rated and added as.
TRACK_KINDS = {'songs': 'song', 'library-songs': 'song',
               'music-videos': 'video', 'library-music-videos': 'video'}

# The Item properties that views over the stores sort and filter by (pages/grid.py's SORTS,
# the search page's filters, a genre's page). When a reload changes one, the stores holding
# the Item splice it over itself so that those models place it again.
SORT_KEYS = frozenset(('title', 'subtitle', 'year', 'added', 'genre'))


def model_property(name, type, default=None):
    """A read-write GObject property kept in the plain attribute `_<name>`.

    Wrapping assigns the attributes directly: handing properties to GObject.Object.__init__
    crosses into C and back into Python for each one, which made a Track cost about 50 µs
    instead of under 10 (a second and a half for 30,000 songs). Reads from GTK (a
    Gtk.PropertyExpression) and later writes (which notify) go through the getter and setter.
    """
    attribute = '_' + name

    def getter(self):
        return getattr(self, attribute)

    def setter(self, value):
        setattr(self, attribute, value)

    return GObject.Property(type=type, default=default, getter=getter, setter=setter)


def raw_property(key, type, default=None, writable=False):
    """A GObject property read from the object's `raw` dict at each access, as _text() or
    _number() normalise it (JSON null is the default, or 0 for a number); `writable`, set
    into the dict (and notified, as any property set is).

    An object keeps no copy of its fields: read from the dict it is wrapped around, 40,000
    Tracks cost 300 bytes each instead of 750 and wrap in 3 µs instead of 7 (the Songs page
    builds them all), and 3,000 Items wrap in 8 ms instead of 20, before the first frame.
    Reads from GTK (a Gtk.PropertyExpression) and from the pages go through the getter; the
    hot loops in SongOrder read the dicts directly.
    """
    if type is bool:
        def getter(self):
            return bool(self.raw.get(key))
    elif type is int:
        def getter(self):
            return _number(self.raw.get(key))
    else:
        def getter(self):
            return _text(self.raw.get(key)) or default

    if not writable:
        return GObject.Property(type=type, default=default, getter=getter,
                                flags=GObject.ParamFlags.READABLE)

    def setter(self, value):
        self.raw[key] = value

    return GObject.Property(type=type, default=default, getter=getter, setter=setter)


class Track(GObject.Object):
    """One entry of a group: the Track shape, read from `raw`, the source dict.

    `thumb` is the track's own thumbnail (a playlist's rows) or else its album's, and `play` is
    its group's play target, the queue `index` counts in: a row plays play with start-with index.
    `kind` is 'song' or 'video' by the entry's API `type` (TRACK_KINDS), '' when it has none.
    """

    __gtype_name__ = 'AppleMusicTrack'

    id = raw_property('id', str)
    catalog_id = raw_property('catalogId', str)
    title = raw_property('title', str, '')
    artist = raw_property('artist', str, '')
    album = raw_property('album', str, '')
    track_number = raw_property('trackNumber', int, 0)
    disc_number = raw_property('discNumber', int, 0)
    duration_ms = raw_property('durationMs', int, 0)
    duration_label = raw_property('durationLabel', str, '')
    explicit = raw_property('explicit', bool, False)
    index = raw_property('index', int, 0)
    # A track of a pre-release album that is not out yet (`unreleased`): shown, not played.
    # It is out once its album's release date (`_release`, its Group's) has come, before a
    # sync says so (release_passed()).
    unreleased = GObject.Property(
        type=bool, default=False, flags=GObject.ParamFlags.READABLE,
        getter=lambda self: (bool(self.raw.get('unreleased'))
                             and not release_passed(self._release)))
    _release = None  # the release date of its album when that is to come (Group's `release`)
    # Its genre (the first of Apple's genreNames) and its release's year: the tables' Genre
    # and Year columns. '' and 0 for a library.json from before version 5.
    genre = raw_property('genre', str, '')
    year = raw_property('year', int, 0)
    kind = GObject.Property(type=str, default='',
                            getter=lambda self: TRACK_KINDS.get(_text(self.raw.get('type')), ''),
                            flags=GObject.ParamFlags.READABLE)
    thumb = GObject.Property(type=str, getter=lambda self: self._thumb,
                             flags=GObject.ParamFlags.READABLE)

    def __init__(self, data, play=None, thumb=None):
        super().__init__()
        self.raw = data
        self._thumb = _text(data.get('thumb')) or thumb
        self.play = play or {}
        self._search_key = None

    @property
    def search_key(self):
        """Title, artist and album as search_key() joins them: what the Songs filter and a
        playlist's look for a folded search in. Made on first use and kept."""
        if self._search_key is None:
            self._search_key = track_search_key(self.raw)
        return self._search_key


def track_search_key(raw):
    """A track's title, artist and album (its dict's, or its TrackRecord's) as search_key()
    joins them."""
    return search_key(_text(raw.get('title')) or '', _text(raw.get('artist')) or '',
                      _text(raw.get('album')) or '')


def moved(count, from_index, to_index):
    """The order (positions, as reorder_entries() takes it) of a list of `count` tracks with
    the one at from_index moved to to_index, every other in its order."""
    order = list(range(count))
    order.insert(to_index, order.pop(from_index))
    return order


def drop_index(from_index, gap):
    """Where a track at from_index goes when it is dropped in `gap` (0 before the first
    track, n after the last of n): its new index, or None for either gap beside it, where it
    already is."""
    to_index = gap if gap <= from_index else gap - 1
    return None if to_index == from_index else to_index


def order_for(entries, ids):
    """The positions in `entries` (track dicts or TrackRecords, or Tracks) that put them in
    the order of `ids`, a song held twice taking its entries in the order they come; None
    when `ids` are not those entries' ids, in some order (another list)."""
    positions = {}
    for position, entry in enumerate(entries):
        entry_id = entry.id if isinstance(entry, Track) else entry.get('id')
        positions.setdefault(entry_id, collections.deque()).append(position)
    order = []
    for entry_id in ids:
        waiting = positions.get(entry_id)
        if not waiting:
            return None
        order.append(waiting.popleft())
    return order if len(order) == len(entries) else None


def reorder_entries(entries, order):
    """A group's track entries (dicts or TrackRecords) in the order `order` gives
    (positions in `entries`), each one's `index` its new position, the queue index a row
    plays from (Track.index): an entry already there is kept as it is, one that moves is
    made again (a TrackRecord as a TrackRecord)."""
    arranged = []
    for position, entry in enumerate(entries[place] for place in order):
        if entry.get('index') != position:
            moved_entry = dict(entry)
            moved_entry['index'] = position
            entry = TrackRecord(moved_entry) if isinstance(entry, TrackRecord) else moved_entry
        arranged.append(entry)
    return arranged


def entries_without(raw, positions):
    """What Item.merge() takes to show the playlist Item dict `raw` without the entries at
    `positions` (places in its one group's list): {'groups': the group with the rest, each
    one's `index` its new place (reorder_entries())}, with `trackCount` and `durationMs`
    counted down where `raw` has them. With none of its positions it is `raw`'s own groups
    and counts as they are (put back). None for an Item dict without exactly one group."""
    groups = _dicts(raw.get('groups'))
    if len(groups) != 1:
        return None
    entries = _entries(groups[0].get('entries'))
    gone = {position for position in positions if 0 <= position < len(entries)}
    if gone:
        kept = [position for position in range(len(entries)) if position not in gone]
        update = {'groups': [dict(groups[0], entries=reorder_entries(entries, kept))]}
    else:
        update = {'groups': raw['groups']}
    duration = sum(_number(entries[position].get('durationMs')) for position in gone)
    for key, less in (('trackCount', len(gone)), ('durationMs', duration)):
        if _is_count(raw.get(key)):
            update[key] = max(0, raw[key] - less)
    return update


class Group(GObject.Object):
    """A disc of an album, a playlist's one list, an album of an artist: {name, play, entries}.

    `entries` is a Gio.ListStore of Track. The library walks the store rather than a list of
    the Tracks kept beside it: a Track's Python wrapper goes while no Python reference holds
    it (its state stays with the object, and a read makes a new wrapper), and a list would
    keep 40,000 wrappers alive, 2.4 MB.
    """

    __gtype_name__ = 'AppleMusicGroup'

    name = model_property('name', str, '')

    def __init__(self, data, thumb=None, release=None):
        super().__init__()
        self._name = _text(data.get('name')) or ''
        self.raw = data
        self.play = data.get('play') or {}
        self.entries = Gio.ListStore(item_type=Track)
        tracks = [Track(entry, self.play, thumb) for entry in _entries(data.get('entries'))]
        if release:  # a pre-release album's: its tracks not out yet are out on that day
            for track in tracks:
                track._release = release
        self.entries.splice(0, 0, tracks)


class Item(GObject.Object):
    """An album, artist, playlist, station, video or song: the Item shape.

    `play` is the dict a play command takes and `raw` the source dict. `groups` is a list of
    Group, wrapped from raw on first access. A playlist folder is an Item too, of kind 'folder'
    (made by PlaylistTree from a `folders` entry, with no artwork and no groups), so a grid of a
    folder's contents shows folders and playlists alike.

    A reload keeps the Item and merge()s the new dict into it: each property that changed is
    notified, and `groups-changed` says the groups are new (`groups` is then a new list of new
    Groups), so a widget or page showing the Item follows it by those signals.

    The words are the app's, in its language, never the data's: an album or artist without a
    title is called 'Unknown Album' or 'Unknown Artist' (unknown_title()), and `count-label`
    is made from the counts the sync writes (count_text()).
    """

    __gtype_name__ = 'AppleMusicItem'

    __gsignals__ = {
        'groups-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def _get_title(self):
        return _text(self.raw.get('title')) or unknown_title(_text(self.raw.get('kind')))

    def _set_title(self, value):
        self.raw['title'] = value

    def _get_count_label(self):
        if self._count is None:
            self._count = self.count_text()
        return self._count

    id = raw_property('id', str, writable=True)
    kind = raw_property('kind', str, writable=True)
    title = GObject.Property(type=str, default='', getter=_get_title, setter=_set_title)
    subtitle = raw_property('subtitle', str, '', writable=True)
    year = raw_property('year', int, 0, writable=True)
    genre = raw_property('genre', str, writable=True)
    summary = raw_property('summary', str, writable=True)
    art = raw_property('art', str, writable=True)
    thumb = raw_property('thumb', str, writable=True)
    art_color = raw_property('artColor', str, writable=True)
    count_label = GObject.Property(type=str, default='', getter=_get_count_label,
                                   flags=GObject.ParamFlags.READABLE)
    explicit = raw_property('explicit', bool, False, writable=True)
    catalog_id = raw_property('catalogId', str, writable=True)
    url = raw_property('url', str, writable=True)
    # An album not out yet (Apple's isPrerelease, `prerelease`), out on its `releaseDate`:
    # once that day has come it reads as out (release_passed()), before a sync says so.
    prerelease = GObject.Property(
        type=bool, default=False,
        getter=lambda self: (bool(self.raw.get('prerelease'))
                             and not release_passed(self.raw.get('releaseDate'))),
        setter=lambda self, value: self.raw.__setitem__('prerelease', value))
    # Whether the account has it as a favourite: set by the Library from library.json's
    # `favourites` and as the app favourites it (Library.set_favourite), notified as it
    # changes.
    favourite = model_property('favourite', bool, False)

    def _get_added(self):
        return self.added_seconds()

    # When it was added to the library (`added`), as seconds since the epoch; 0 unknown.
    added = GObject.Property(type=GObject.TYPE_INT64, default=0, getter=_get_added,
                             flags=GObject.ParamFlags.READABLE)

    def __init__(self, data):
        super().__init__()
        self.raw = data
        self.play = data.get('play') or {}
        self._groups = None
        self._count = None  # count-label's text, made when first read (merge() forgets it)
        self._favourite = False
        self._added = None  # `added` in seconds, worked out when first read
        self._search_key = None  # (the title and subtitle it was made of, the key)

    @property
    def search_key(self):
        """The title and the subtitle (an album's or a video's artist) as search_key() joins
        them: what a grid's filter and the Artists list's look for a folded search in. Kept
        while the raw title and subtitle are the ones it was made of, however they changed
        (a reload's merge(), a rename)."""
        raw = self.raw
        texts = (raw.get('title'), raw.get('subtitle'))
        if self._search_key is None or self._search_key[0] != texts:
            self._search_key = (texts, search_key(self.title, self.subtitle or ''))
        return self._search_key[1]

    def added_seconds(self):
        """The `added` property, read without a GObject call (sorting thousands)."""
        if self._added is None:
            self._added = added_seconds(self.raw.get('added'))
        return self._added

    # The raw keys count_text() reads, groups aside.
    _COUNT_KEYS = ('trackCount', 'durationMs', 'albumCount', 'countLabel')

    def count_text(self):
        """The caption's count: an album's or playlist's `trackCount` songs and `durationMs`
        total time ('12 songs, 43 min'), an artist's `albumCount` albums ('3 albums'); else
        the English `countLabel` a library.json from before those counts holds; else the
        counts of its groups; else ''. count-label is this, kept (bind never runs gettext)."""
        raw = self.raw
        kind = raw.get('kind')
        if kind == 'artist' and _is_count(raw.get('albumCount')):
            return albums_text(raw['albumCount'])
        if kind in ('album', 'playlist') and _is_count(raw.get('trackCount')):
            duration = raw.get('durationMs')
            return songs_text(raw['trackCount'], duration if _is_count(duration) else None)
        legacy = _text(raw.get('countLabel'))
        if legacy:
            return legacy
        groups = _dicts(raw.get('groups'))
        if kind == 'artist' and groups:
            return albums_text(len(groups))
        if kind in ('album', 'playlist'):
            entries = [entry for group in groups for entry in _entries(group.get('entries'))]
            if entries:
                return songs_text(len(entries),
                                  sum(_number(entry.get('durationMs')) for entry in entries))
        return ''

    @property
    def favourites(self):
        """Whether this is the Favourite Songs playlist: attributes.isFavourites in the raw Item."""
        attributes = self.raw.get('attributes')
        return isinstance(attributes, dict) and attributes.get(FAVOURITES) is True

    @property
    def editable(self):
        """Whether songs can be added to this: a library playlist (Apple's "p." id, or the
        demo's "l.") that is not Favourite Songs and whose attributes do not say canEdit
        false. A catalog playlist is not."""
        if self.kind != 'playlist' or not str(self.id or '').startswith(('p.', 'l.')):
            return False
        attributes = self.raw.get('attributes')
        if not isinstance(attributes, dict):
            return True
        return attributes.get(FAVOURITES) is not True and attributes.get(EDITABLE) is not False

    @property
    def public(self):
        """Whether this playlist is public, shown on the account's profile and in search:
        attributes.isPublic in the raw Item (PUBLIC)."""
        attributes = self.raw.get('attributes')
        return isinstance(attributes, dict) and attributes.get(PUBLIC) is True

    @property
    def groups(self):
        if self._groups is None:
            # An album's tracks draw the album's cover; an artist's groups are albums, whose
            # covers the artist Item does not have.
            thumb = self.thumb if self.kind == 'album' else None
            release = self.raw.get('releaseDate') if self.raw.get('prerelease') else None
            self._groups = [Group(group, thumb, release)
                            for group in _dicts(self.raw.get('groups'))]
        return self._groups

    # The properties an `item` answer refreshes: the name, the raw key it reads, and how its
    # getter reads the value (merge() compares the raw values so, without a GObject call).
    # count-label is made from several keys (_COUNT_KEYS and the groups).
    _MERGED = tuple((name, key, _reader(type, default)) for name, key, type, default in (
        ('title', 'title', str, ''), ('subtitle', 'subtitle', str, ''),
        ('genre', 'genre', str, None), ('summary', 'summary', str, None),
        ('art', 'art', str, None), ('thumb', 'thumb', str, None),
        ('art-color', 'artColor', str, None), ('catalog-id', 'catalogId', str, None),
        ('url', 'url', str, None), ('year', 'year', int, 0),
        ('explicit', 'explicit', bool, False), ('prerelease', 'prerelease', bool, False)))
    # The keys an album's dict has only while they hold (normalize.normalize_album): a whole
    # answer without them (an item() answer, with its groups) takes them out.
    _RELEASE_KEYS = ('prerelease', 'releaseDate')

    def merge(self, data, replace=False):
        """Take a fresh Item dict for this item into this object: the raw dict updated (or
        replaced by `data`, for a reload's complete dict), the properties that changed
        notified (so bound widgets follow), and, when the groups differ from the ones in
        hand, the groups wrapped again on the next access and `groups-changed` emitted, last
        (the same groups keep their Group and Track objects). An engine item() answer (the
        same shape, with `groups`) merges; a sync's dict replaces. Returns the names of the
        properties that changed (empty when none did).

        A whole answer (with `groups`) of an album out since takes out the `prerelease` and
        `releaseDate` the one in hand had (_RELEASE_KEYS), which a dict has only while they
        hold.

        A dict equal to the one in hand changes nothing, and the one in hand is kept; so are
        its groups when the new ones are equal (`data`'s are replaced by them): the Groups and
        Tracks hold those, and a second, equal copy would be kept alive beside them.
        """
        old = self.raw
        if replace and data == old:
            return []
        groups_changed = False
        if 'groups' in data:
            if data['groups'] == old.get('groups'):
                if 'groups' in old:
                    data['groups'] = old['groups']
            else:
                groups_changed = True
        whole = replace or 'groups' in data
        merged = [entry for entry in self._MERGED if whole or entry[1] in data]
        before = [read(old.get(key)) for _name, key, read in merged]
        added = old.get('added')
        counts = [old.get(key) for key in self._COUNT_KEYS]
        if replace:
            self.raw = data
        else:
            for key, value in data.items():
                if key in ('id', 'kind'):
                    continue
                old[key] = value
            if 'groups' in data:
                for key in self._RELEASE_KEYS:
                    if key not in data:
                        old.pop(key, None)  # out now: an answer of the album as it is
        raw = self.raw
        changed = [name for (name, key, read), value in zip(merged, before, strict=True)
                   if read(raw.get(key)) != value]
        if (replace or 'added' in data) and raw.get('added') != added:
            self._added = None
            changed.append('added')
        if data.get('play'):
            self.play = data['play']
        if self.kind == 'album' and 'thumb' in changed:
            groups_changed = True  # its Tracks hold the album's thumbnail: new ones hold the new
        if groups_changed:
            self._groups = None
        if self._count is not None and (
                groups_changed or counts != [raw.get(key) for key in self._COUNT_KEYS]):
            shown, self._count = self._count, None
            if self.count_label != shown:
                changed.append('count-label')
        for name in changed:
            self.notify(name)
        if groups_changed:
            self.emit('groups-changed')
        return changed


    def track_ids(self):
        """The ids of a playlist's tracks, in the order shown (its one group's), or None for
        anything else: what Library.reorder() and the engine's reorder take."""
        groups = self.groups if self.kind == 'playlist' else ()
        if len(groups) != 1:
            return None
        entries = groups[0].entries
        return [entries.get_item(position).id for position in range(entries.get_n_items())]

    def reorder(self, order):
        """Put a playlist's tracks in the order `order` gives (positions in the list shown,
        a permutation of them), in place: the same Group and Track objects, each moved Track
        given its new entry (its `index` notified), `raw` changed to match, and the group's
        store changed by one splice over the stretch that moved, so a view keeps its rows,
        its scroll position and its focus. No `groups-changed`: nothing is new. False, and
        nothing changed, for anything but a playlist of one group or an order that is not a
        permutation of its tracks. Library.reorder() also holds the order through reloads."""
        groups = self.groups if self.kind == 'playlist' else ()
        if len(groups) != 1:
            return False
        group = groups[0]
        store = group.entries
        count = store.get_n_items()
        order = list(order)
        if sorted(order) != list(range(count)):
            return False
        tracks = [store.get_item(position) for position in range(count)]
        raw_entries = _entries(group.raw.get('entries'))
        if len(raw_entries) != count:
            return False
        entries = reorder_entries(raw_entries, order)
        new_group = dict(group.raw, entries=entries)
        self.raw['groups'] = [new_group if raw is group.raw else raw
                              for raw in self.raw.get('groups') or ()]
        group.raw = new_group
        arranged = [tracks[place] for place in order]
        changed = [position for position, track in enumerate(arranged)
                   if track is not tracks[position]]
        for position, track in enumerate(arranged):
            if track.raw is not entries[position]:
                track.raw = entries[position]
                track.notify('index')
        if changed:
            first, last = changed[0], changed[-1] + 1
            store.splice(first, last - first, arranged[first:last])
        return True


class ShelfModel(GObject.Object):
    """A titled row of Items: Apple's home page recommendations, Heavy Rotation, Recently Added.
    `subtitle` is the line under the title, '' for none (a recommendation's reason, which
    library.json's shelf keeps as its `subtitle`).

    AppleMusicShelf (widgets/shelf.py) is the widget that shows one.
    """

    __gtype_name__ = 'AppleMusicShelfModel'

    key = model_property('key', str, '')
    title = model_property('title', str, '')
    subtitle = model_property('subtitle', str, '')

    def __init__(self, key, title, items, subtitle=''):
        super().__init__()
        self._key = key
        self._title = title
        self._subtitle = subtitle
        self.items = Gio.ListStore(item_type=Item)
        self.items.splice(0, 0, items)

    def update(self, title, items, subtitle=''):
        """A reload's version of this shelf: the title and subtitle set if they changed, the
        store brought to `items` with the fewest changes (the same objects in the same order
        change nothing)."""
        if title != self._title:
            self.title = title
        if subtitle != self._subtitle:
            self.subtitle = subtitle
        apply_diff(self.items, items)
