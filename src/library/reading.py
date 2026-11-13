# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Reading library.json in the library's thread: the parse in pieces (parse()), the strings
its tracks share, and what a load leaves out (leave_out())."""

import json
import logging
import re
import time

from .records import (TrackRecord, _dicts, _entries, _entries_of, _entry_ids, _is_count,
                      _number)

log = logging.getLogger(__name__)


def _compact_tracks(item):
    """Make the track dicts of an Item dict's groups TrackRecords (in place)."""
    for group in _dicts(item.get('groups')):
        entries = group.get('entries')
        if isinstance(entries, list):
            group['entries'] = [TrackRecord(entry) if isinstance(entry, dict) else entry
                                for entry in entries]


# The longest a parse waits for resume_reading() in all, in seconds: a hold never released
# (an app started for an action, with no window) only delays it.
HOLD_LIMIT = 1.0


def _read_library(path, reading=None):
    """Parse library.json (in a thread). Returns (data or None, the Songs page's count, the
    file's state: 'ok', 'missing' or 'unreadable'). `reading`, a threading.Event, holds the
    parse between list elements while it is clear, for HOLD_LIMIT seconds at most in all."""
    albums = set()
    songs = set()  # the ids of the albums' tracks and the loose songs: the Songs page's count
    strings = {}
    held = [0.0]  # seconds waited for `reading` so far

    def element(key, value):
        if reading is not None and not reading.is_set() and held[0] < HOLD_LIMIT:
            waited = time.monotonic()
            reading.wait(HOLD_LIMIT - held[0])
            held[0] += time.monotonic() - waited
        # The artists' duplicate track lists go as each artist is decoded (see
        # _drop_artist_tracks), so they never add to the parse's peak: library.json lists the
        # albums first. Anything left (artists before albums) goes after the parse. Each
        # album's, playlist's and loose song's tracks share one string object for the
        # names and labels they repeat (_share_strings), and are kept as TrackRecords.
        if not isinstance(value, dict):
            return value
        if key == 'albums':
            albums.add(value.get('id'))
            songs.update(entry.get('id') for group in _dicts(value.get('groups'))
                         for entry in _dicts(group.get('entries')))
        elif key == 'artists' and albums:
            _drop_artist_tracks({'albums': (), 'artists': [value]}, albums)
        if key in ('albums', 'playlists', 'songs'):
            _share_strings(value, strings)
        if key == 'songs':
            if value.get('id'):
                songs.add(value.get('id'))
            return TrackRecord(value)
        if key in ('albums', 'playlists', 'artists'):
            _compact_tracks(value)
        return value

    started = time.monotonic()
    log.debug('Library: reading %s', path)
    try:
        with open(path, 'rb') as file:
            raw = file.read()
        text = raw.decode(json.detect_encoding(raw), 'surrogatepass')  # as json.loads does
        del raw
        data = parse(text, element)
        log.debug('Library: parsed %d characters in %.0f ms', len(text),
                  (time.monotonic() - started) * 1000)
    except FileNotFoundError:
        log.info('No library at %s', path)
        return None, 0, 'missing'
    except (OSError, ValueError, RecursionError) as error:  # RecursionError: nested too deep
        log.warning('Cannot read %s: %s', path, error)
        return None, 0, 'unreadable'
    if not isinstance(data, dict):
        log.warning('Cannot read %s: not a JSON object', path)
        return None, 0, 'unreadable'
    sections = data.get('sections') if isinstance(data.get('sections'), dict) else {}
    _drop_artist_tracks(sections)
    return data, len(songs), 'ok'


def _drop_artist_tracks(sections, albums=None):
    """Empty the track lists of the artists' groups whose album is in the albums section
    (or in `albums`, a set of ids): they repeat the album's, which the artist page shows
    (pages/artist.py finds the album by the group's play target). A group whose album the
    library lacks keeps its tracks, for the page that is made up from it. Halves what a
    parsed library keeps: 40,000 tracks of 3,000 albums are 45 MB of dicts."""
    if albums is None:
        albums = {album.get('id') for album in _dicts(sections.get('albums'))}
    for artist in _dicts(sections.get('artists')):
        for group in _dicts(artist.get('groups')):
            play = group.get('play')
            if (isinstance(play, dict) and play.get('kind') == 'album'
                    and play.get('id') in albums and group.get('entries')):
                group['entries'] = []


def leave_out(data, hidden):
    """Take out of a parsed library.json (`data`, changed in place) what `hidden` names, as
    Apple takes it out of the library: a set of (kind, id), the kinds 'album', 'playlist' and
    'video' naming Items by id, and 'song' a song's or music video's entries by their id or
    catalog id ('video' names those entries too).

    An album goes with its tracks, and each of its tracks' ids and catalog ids is left out
    wherever else it is; an entry goes from every album, playlist and artist that holds it
    (their `trackCount` and `durationMs` counted down), and an album or an artist's group
    left with no entries goes too, and an artist left with no groups, as the library's
    albums and artists are made from its songs. A playlist's place in the folders goes with
    it (PlaylistTree leaves out what names nothing). Shelves lose the Items that went.
    Returns (found, removed): the refs of `hidden` met in `data` (with others), and the ids
    of the album tracks and loose songs taken out (the Songs page's count)."""
    sections = data.get('sections') if isinstance(data.get('sections'), dict) else {}
    found = set()
    removed = set()
    gone = {'album': set(), 'playlist': set(), 'video': set()}
    entries = set()  # entry ids and catalog ids to leave out
    for kind, item_id in hidden:
        if kind in gone:
            gone[kind].add(item_id)
        if kind in ('song', 'video'):
            entries.add(item_id)

    def kept_items(name, kind):
        items = sections.get(name)
        if not isinstance(items, list):
            return
        kept = []
        for item in items:
            if isinstance(item, dict) and item.get('id') in gone[kind]:
                found.add((kind, item.get('id')))
                if kind == 'album':
                    for entry in _entries_of(item):
                        removed.add(entry.get('id'))
                        entries.update(_entry_ids(entry))
                continue
            kept.append(item)
        sections[name] = kept

    kept_items('albums', 'album')
    kept_items('playlists', 'playlist')
    kept_items('videos', 'video')

    def leave(entry, album):
        """Whether the entry is left out (noted as found, and as removed for an album's)."""
        ids = _entry_ids(entry)
        if entries.isdisjoint(ids):
            return False
        for entry_id in ids & entries:
            found.update((('song', entry_id), ('video', entry_id)))
        if album:
            removed.add(entry.get('id'))
        return True

    def without_entries(item, album=False):
        """Leave the hidden entries out of the Item dict's groups, its counts counted down
        and the groups emptied by it dropped: whether it held entries and holds none now."""
        groups = _dicts(item.get('groups'))
        kept_groups = []
        held = taken = duration = 0
        for group in groups:
            listed = _entries(group.get('entries'))
            kept = []
            for entry in listed:
                if leave(entry, album):
                    duration += _number(entry.get('durationMs'))
                else:
                    kept.append(entry)
            held += len(listed)
            taken += len(listed) - len(kept)
            if len(kept) < len(listed):
                group['entries'] = kept
            if kept or not listed:
                kept_groups.append(group)
        if not taken:
            return False
        item['groups'] = kept_groups
        for key, less in (('trackCount', taken), ('durationMs', duration)):
            if _is_count(item.get(key)):
                item[key] = max(0, item[key] - less)
        return held == taken

    if entries:
        albums = sections.get('albums') or []
        kept = []
        for album in albums:
            if isinstance(album, dict) and without_entries(album, album=True):
                gone['album'].add(album.get('id'))
            else:
                kept.append(album)
        sections['albums'] = kept
        for playlist in _dicts(sections.get('playlists')):
            without_entries(playlist)
        loose = sections.get('songs')
        if isinstance(loose, list):
            sections['songs'] = [entry for entry in loose
                                 if not (isinstance(entry, (dict, TrackRecord))
                                         and leave(entry, True))]
    artists = sections.get('artists')
    if isinstance(artists, list) and (entries or gone['album']):
        kept_artists = []
        for artist in artists:
            if isinstance(artist, dict) and _without_albums(artist, gone['album']):
                continue  # nothing of theirs is left
            if isinstance(artist, dict) and entries and without_entries(artist):
                if not artist.get('groups'):
                    continue
            kept_artists.append(artist)
        sections['artists'] = kept_artists
    for shelf in _dicts(data.get('shelves')):
        items = shelf.get('items')
        if isinstance(items, list):
            shelf['items'] = [item for item in items if not _left_out(item, gone, entries)]
    return found, removed


def _without_albums(artist, albums):
    """Drop an artist dict's groups of the albums `albums` (ids), its albumCount counted
    down: whether it had groups and has none now."""
    groups = _dicts(artist.get('groups'))
    kept = [group for group in groups if not (
        isinstance(group.get('play'), dict) and group['play'].get('kind') == 'album'
        and group['play'].get('id') in albums)]
    if len(kept) == len(groups):
        return False
    artist['groups'] = kept
    if _is_count(artist.get('albumCount')):
        artist['albumCount'] = max(0, artist['albumCount'] - (len(groups) - len(kept)))
    return not kept


def _left_out(item, gone, entries):
    """Whether a shelf's Item dict is one of what leave_out() takes out."""
    if not isinstance(item, dict):
        return False
    kind, item_id = item.get('kind'), item.get('id')
    if kind in gone and item_id in gone[kind]:
        return True
    return kind in ('song', 'video') and not entries.isdisjoint(_entry_ids(item))


# The keys of a track dict whose values repeat across a library's tracks: an album's
# tracks all name the album and its artist, "3:07" is the length of a great many songs,
# nearly every track's API type is "library-songs", a genre is the genre of many, and so is
# a year (an int past 256 is an object of its own for each track the decoder reads).
SHARED_KEYS = ('artist', 'album', 'durationLabel', 'thumb', 'type', 'genre', 'year')


def _share_strings(item, strings):
    """Make the tracks of an Item dict (or a loose song's dict) share one string (or int)
    object per distinct value of SHARED_KEYS, through `strings` (value -> the object kept):
    the JSON decoder makes a new one for every occurrence, and 40,000 tracks' repeated names
    cost 5 MB that way, their years 1.8 MB more."""
    entries = [item] if 'entries' not in item and 'groups' not in item else [
        entry for group in _dicts(item.get('groups')) for entry in _dicts(group.get('entries'))]
    for entry in entries:
        for key in SHARED_KEYS:
            value = entry.get(key)
            if type(value) is str or type(value) is int:  # not a bool: True would be 1
                entry[key] = strings.setdefault(value, value)


_SPACE = re.compile(r'[ \t\n\r]*')


def parse(text, element=None):
    """json.loads(text), for library.json: the same result, decoded in pieces.

    The top-level object's values, the `sections` object's values and every list met on the
    way (the sections, the shelves, the folders) are decoded an element at a time with
    json.JSONDecoder.raw_decode, one album (or artist, shelf…) a call, about 40 µs each. json's
    C decoder holds the GIL for a whole call, so decoding a 50 MB file in one call from a
    thread freezes the main thread's Python (every signal handler, every vfunc, so every
    frame that needs one) for its 300 ms; between calls the interpreter switches threads as
    usual, within 5 ms. Costs about 10% more than one call. Anything not shaped like that
    (a list at the top level, a scalar) is decoded in one call, as json.loads would.
    `element(key, value)`, when given, is called with each list element as it is decoded
    and the key of the list it is in, and its return value is kept instead."""
    decoder = json.JSONDecoder()
    position = _SPACE.match(text, 0).end()
    if position >= len(text) or text[position] != '{':
        return decoder.decode(text)
    value, end = _parse_object(text, position, decoder, 1, element, None)
    end = _SPACE.match(text, end).end()
    if end != len(text):
        raise ValueError(f'Extra data at position {end}')
    return value


def _parse_object(text, position, decoder, depth, element, key):
    """A JSON object starting at text[position] (a brace): (dict, the position after it).
    Its values that are objects are parsed this way too while depth > 0, its lists element
    by element, and anything else by the decoder."""
    result = {}
    position = _SPACE.match(text, position + 1).end()
    if text[position:position + 1] == '}':
        return result, position + 1
    while True:
        if text[position:position + 1] != '"':
            raise ValueError(f'Expecting a property name at position {position}')
        key, position = decoder.raw_decode(text, position)
        position = _SPACE.match(text, position).end()
        if text[position:position + 1] != ':':
            raise ValueError(f"Expecting ':' at position {position}")
        position = _SPACE.match(text, position + 1).end()
        result[key], position = _parse_value(text, position, decoder, depth, element, key)
        position = _SPACE.match(text, position).end()
        char = text[position:position + 1]
        if char == '}':
            return result, position + 1
        if char != ',':
            raise ValueError(f"Expecting ',' at position {position}")
        position = _SPACE.match(text, position + 1).end()


def _parse_array(text, position, decoder, element, key):
    """A JSON list starting at text[position] (a bracket), each element decoded by the
    decoder (and given to `element` with `key`): (list, the position after it)."""
    result = []
    position = _SPACE.match(text, position + 1).end()
    if text[position:position + 1] == ']':
        return result, position + 1
    while True:
        value, position = decoder.raw_decode(text, position)
        result.append(element(key, value) if element is not None else value)
        position = _SPACE.match(text, position).end()
        char = text[position:position + 1]
        if char == ']':
            return result, position + 1
        if char != ',':
            raise ValueError(f"Expecting ',' at position {position}")
        position = _SPACE.match(text, position + 1).end()


def _parse_value(text, position, decoder, depth, element, key):
    char = text[position:position + 1]
    if char == '{' and depth > 0:
        return _parse_object(text, position, decoder, depth - 1, element, key)
    if char == '[':
        return _parse_array(text, position, decoder, element, key)
    if not char:
        raise ValueError(f'Expecting a value at position {position}')
    return decoder.raw_decode(text, position)
