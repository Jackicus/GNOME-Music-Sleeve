# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""library.json's raw values: each track kept as a TrackRecord, and the readers that turn a
JSON value into what a property shows.

Everything here reads plain dicts, lists and TrackRecords, no GObject: the parse in the
library's thread uses it as much as the objects the pages bind.
"""

import re
from datetime import UTC, datetime

from gi.repository import GLib


# The sections of library.json's `favourites` (sync.FAVOURITE_SECTIONS), read as one set.
FAVOURITE_SECTIONS = ('songs', 'albums', 'playlists', 'videos')


def _text(value):
    """A string property's value: None stays None (JSON null), anything else becomes a str."""
    return value if value is None or isinstance(value, str) else str(value)


def _number(value):
    """An int property's value: JSON null (or anything not a number) is 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


_RELEASE_DAY = re.compile(r'\d{4}(-\d{2}-\d{2})?')


def release_passed(date, today=None):
    """Whether a release date (Apple's releaseDate: '2026-12-04', or a year alone) has come:
    it is `today` or before, a year alone once its year is over. `today` is a 'YYYY-MM-DD'
    (the local date when None: Apple releases at midnight, local time). False for anything
    that is not such a date, so an album with none stays to come until Apple says it is out.
    """
    if not isinstance(date, str):
        return False
    date = date.strip()
    if not _RELEASE_DAY.fullmatch(date):
        return False
    if today is None:
        today = GLib.DateTime.new_now_local().format('%Y-%m-%d')
    return date <= today if len(date) == 10 else date < today[:4]


def _reader(type, default=None):
    """The function turning a raw value into a raw_property's value, as its getter does."""
    if type is bool:
        return bool
    if type is int:
        return _number
    return lambda value: _text(value) or default


def added_seconds(value):
    """An Item's `added` (Apple's dateAdded: a year, a date, or a date and time, UTC when it
    names no zone) as seconds since the epoch, or 0 when it has none or is not one."""
    if not isinstance(value, str) or not value:
        return 0
    try:
        if len(value) == 4 and value.isdigit():
            when = datetime(int(value), 1, 1, tzinfo=UTC)
        else:
            when = datetime.fromisoformat(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
        return int(when.timestamp())
    except (ValueError, OverflowError, OSError):
        return 0


def favourite_set(value):
    """library.json's `favourites` ({section: [id]}, FAVOURITE_SECTIONS) as one frozenset of
    ids: a song's catalog id (else its library id), an album's, playlist's or video's library
    id and catalog id. Nothing from a file before them."""
    if not isinstance(value, dict):
        return frozenset()
    return frozenset(entry for name in FAVOURITE_SECTIONS
                     for entry in (value.get(name) if isinstance(value.get(name), list) else ())
                     if isinstance(entry, str) and entry)


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# The keys of a Track dict (src/backend/README.md's Track shape, and the API `type`), in the
# order a TrackRecord keeps their values.
TRACK_FIELDS = ('id', 'catalogId', 'title', 'artist', 'album', 'trackNumber', 'discNumber',
                'durationMs', 'durationLabel', 'explicit', 'index', 'thumb', 'type', 'genre',
                'year')
_FIELDS = {name: position for position, name in enumerate(TRACK_FIELDS)}
_CATALOG_ID = _FIELDS['catalogId']
_ID = _FIELDS['id']
_tuple_item = tuple.__getitem__
_ABSENT = object()  # a TRACK_FIELDS key the dict did not have
_ALL_ABSENT = (_ABSENT,) * len(TRACK_FIELDS)


class TrackRecord(tuple):
    """A Track dict of library.json as a tuple of its TRACK_FIELDS values, then a dict of any
    other keys (or None), made as the file is parsed: 40,000 tracks as dicts cost 16 MB more.
    A numeric catalogId is kept as an int (half a string's size) and read back as the text.

    It reads as the dict did, for everything that reads a Track's `raw`: get(key, default),
    record[key], `key in record`, keys() and items() (so dict(record) is the dict again).
    Records compare as tuples: equal when the dicts were.
    """

    __slots__ = ()

    def __new__(cls, entry):
        values = list(map(entry.get, TRACK_FIELDS, _ALL_ABSENT))  # 40,000 at parse time
        catalog_id = values[_CATALOG_ID]
        if type(catalog_id) is str:
            if catalog_id.isdigit() and catalog_id.isascii() and catalog_id[0] != '0':
                values[_CATALOG_ID] = int(catalog_id)
        elif type(catalog_id) is int:
            values[_CATALOG_ID] = (catalog_id,)  # a number in the file stays one
        if entry.keys() <= _FIELDS.keys():
            values.append(None)
        else:
            values.append({key: value for key, value in entry.items() if key not in _FIELDS})
        return tuple.__new__(cls, values)

    def get(self, key, default=None):
        position = _FIELDS.get(key)
        if position is None:
            others = tuple.__getitem__(self, -1)
            return default if others is None else others.get(key, default)
        value = tuple.__getitem__(self, position)
        if value is _ABSENT:
            return default
        if position == _CATALOG_ID:
            if type(value) is int:
                return str(value)
            if type(value) is tuple:
                return value[0]
        return value

    def __getitem__(self, key):
        if not isinstance(key, str):
            return tuple.__getitem__(self, key)
        value = self.get(key, _ABSENT)
        if value is _ABSENT:
            raise KeyError(key)
        return value

    def __contains__(self, key):
        return self.get(key, _ABSENT) is not _ABSENT

    def keys(self):
        others = tuple.__getitem__(self, -1)
        return [name for name, value in zip(TRACK_FIELDS, self, strict=False)
                if value is not _ABSENT] + list(others or ())

    def items(self):
        return [(key, self[key]) for key in self.keys()]


def _entries(value):
    """The track entries of a JSON list: its dicts and TrackRecords, or nothing when it is not
    a list."""
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, (dict, TrackRecord))]


def _dicts(value):
    """The dicts of a JSON list, or nothing when it is not one."""
    return [raw for raw in value if isinstance(raw, dict)] if isinstance(value, list) else []


def _entries_of(item):
    """Every track entry of an Item dict's groups."""
    return [entry for group in _dicts(item.get('groups'))
            for entry in _entries(group.get('entries'))]


def _entry_ids(entry):
    """A track entry's id and catalog id, those it has."""
    return {value for value in (_text(entry.get('id')), _text(entry.get('catalogId')))
            if value}
