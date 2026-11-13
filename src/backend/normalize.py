# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's resources as the library's Item and Track shapes.

Pure functions turn Apple Music API resources into the Item and Track shapes that README.md
describes: normalize_album() and the other normalize_* functions, normalize_item() for any
resource, _shelf_item() for a shelf's, and group_songs_into_albums_and_artists() for the
sync. They write data, never words: counts are numbers (trackCount, durationMs,
albumCount), a missing name is '', and the app makes and translates the words (library.py,
the pages). The answers made of them are shaped beside this module (search, editorial,
charts, recommendations, item_pages); the artwork files they name are art_cache.py's. The
standard library only.
"""

import hashlib
import html
import os
import re

from .art_cache import (
    ART_SIZES,
    artwork_cache_path,
    template_artwork_url,
    thumb_box,
    thumb_cache_path,
)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_duration(duration_ms):
    """Format milliseconds into 'm:ss' or 'h:mm:ss'.

    e.g. 216000 -> '3:36', 3661000 -> '1:01:01', 0 -> '0:00'.
    """
    if duration_ms is None or duration_ms <= 0:
        return '0:00'

    total_seconds = round(duration_ms / 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f'{hours}:{minutes:02d}:{seconds:02d}'
    return f'{minutes}:{seconds:02d}'


def format_color(bg_color):
    """Normalize hex color string to #rrggbb or None."""
    if not bg_color:
        return None
    bg_color = bg_color.strip()
    if not bg_color:
        return None
    if not bg_color.startswith('#'):
        return f'#{bg_color}'
    return bg_color


def strip_html(text):
    """An HTML snippet (Apple's editorial notes) as plain text, or None: a <br> is a line
    break and a paragraph a blank line, so the words of two never run together."""
    if not text:
        return None
    cleaned = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'</?p(\s[^>]*)?>', '\n\n', cleaned, flags=re.IGNORECASE)
    cleaned = html.unescape(re.sub(r'<[^>]+>', '', cleaned))
    cleaned = re.sub(r'[ \t]*\n[ \t]*', '\n', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned if cleaned else None


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------


def _extract_year(attrs, raw_item):
    """Extract release year from Apple Music attributes or raw item."""
    rel_date = attrs.get('releaseDate') or raw_item.get('releaseDate')
    if rel_date and isinstance(rel_date, str) and len(rel_date) >= 4:
        try:
            return int(rel_date[:4])
        except ValueError:
            pass

    year = attrs.get('year') or raw_item.get('year')
    if year is not None:
        try:
            return int(year)
        except (ValueError, TypeError):
            pass

    # Playlists have no release date; fall back to when they were last
    # modified so the UI still has a year to show.
    mod_date = attrs.get('lastModifiedDate') or raw_item.get('lastModifiedDate')
    if mod_date and isinstance(mod_date, str) and len(mod_date) >= 4:
        try:
            return int(mod_date[:4])
        except ValueError:
            pass

    return None


def _extract_summary(attrs, raw_item):
    """Extract editorial notes or description as plain text."""
    ed = attrs.get('editorialNotes') or raw_item.get('editorialNotes')
    desc = attrs.get('description') or raw_item.get('description')
    summary = None

    if isinstance(ed, dict):
        summary = ed.get('standard') or ed.get('short') or ed.get('name')
    elif isinstance(ed, str):
        summary = ed
    elif isinstance(desc, dict):
        summary = desc.get('standard') or desc.get('short')
    elif isinstance(desc, str):
        summary = desc
    elif raw_item.get('summary'):
        summary = raw_item['summary']

    return strip_html(summary)


def _extract_genre(attrs, raw_item):
    """The first genre name, from the attributes or the raw item."""
    genre_names = attrs.get('genreNames') or raw_item.get('genreNames')
    if isinstance(genre_names, list) and genre_names:
        return genre_names[0]
    if isinstance(genre_names, str):
        return genre_names
    return raw_item.get('genre') or None


def _extract_artwork(attrs, raw_item, cache_dir, art_urls, wide=False):
    """Extract the local cached cover path, its thumbnail's (`wide`: a video's,
    thumb_box()), and the hex background color; the files' URLs go into `art_urls`."""
    art = None
    thumb = None
    art_color = None

    if raw_item.get('art'):
        art = raw_item['art']
    if raw_item.get('thumb'):
        thumb = raw_item['thumb']
    if raw_item.get('artColor'):
        art_color = format_color(raw_item['artColor'])

    artwork = attrs.get('artwork') or raw_item.get('artwork')
    if isinstance(artwork, dict):
        url = artwork.get('url')
        if url and cache_dir:
            art, thumb = _register_artwork(url, cache_dir, art_urls, wide=wide)
        bg = artwork.get('bgColor')
        if bg and not art_color:
            art_color = format_color(bg)

    return art, thumb, art_color


def _register_artwork(url_template, cache_dir, art_urls, wide=False):
    """Name the cover and thumbnail files for an artwork URL template and
    record in `art_urls` what each is fetched from: the thumbnail in its
    thumb_box(), a video's (`wide`) by its shorter edge."""
    cover = ART_SIZES['cover']
    full = template_artwork_url(url_template, cover, cover)
    art = artwork_cache_path(full, cache_dir)
    thumb = thumb_cache_path(full, cache_dir, wide=wide)
    art_urls[art] = full
    art_urls[thumb] = template_artwork_url(url_template, *thumb_box(ART_SIZES['thumb'], wide))
    return art, thumb


# Apple's dateAdded: a year, a date, or a date and time with an optional fraction and zone
# (the documentation says a library album's is a date; the answers seen carry a time).
_DATE_ADDED = re.compile(r'\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?'
                         r'(Z|[+-]\d{2}:?\d{2})?)?)?)?')


def date_added(attrs):
    """A library resource's `dateAdded` as Apple wrote it, when it is one (a year, a date, or
    a date and time: _DATE_ADDED), else None: the Item's `added`."""
    value = attrs.get('dateAdded') if isinstance(attrs, dict) else None
    if isinstance(value, str) and _DATE_ADDED.fullmatch(value):
        return value
    return None


def _with_added(item, attrs):
    """`item` with `added` (date_added()) when the resource carries a date: left out
    otherwise, so a catalog resource's Item is as it was."""
    added = date_added(attrs)
    if added is not None:
        item['added'] = added
    return item


# The catalog type of a library resource type, for the catalog id favourite_ids() records.
_CATALOG_TYPES = {'library-songs': 'songs', 'library-albums': 'albums',
                  'library-playlists': 'playlists', 'library-music-videos': 'music-videos'}


def favourite_ids(resources, songs=False):
    """The ids of the resources (Apple's answers, extended with `inFavorites`) that are the
    account's favourites, and whether any of them carried `inFavorites` at all: (ids, seen).

    A song is recorded by its catalog id, else its library id: the id the app rates a song
    by, so a toggle in the app finds it. Anything else (`songs` false: albums, playlists,
    videos) by its library id and its catalog id when it has one, since the app rates a
    library item by its own id and a catalog page by the catalog's. Each id once, in the
    resources' order."""
    ids = {}
    seen = False
    for raw in resources:
        if not isinstance(raw, dict):
            continue
        attrs = raw.get('attributes')
        if not isinstance(attrs, dict) or 'inFavorites' not in attrs:
            continue
        seen = True
        if attrs.get('inFavorites') is not True:
            continue
        item_id = str(raw.get('id') or '')
        catalog_id = _extract_catalog_id(attrs, raw, _CATALOG_TYPES.get(raw.get('type'), ''))
        if songs:
            found = [catalog_id or item_id]
        else:
            found = [item_id, catalog_id]
        for value in found:
            if value:
                ids[value] = None
    return list(ids), seen


def in_favourites(raw):
    """Whether the first resource of a catalog read with `extend=inFavorites` (an artist's
    page, api.FAVOURITE_PARAMS' read) is one of the account's favourites: its
    `attributes.inFavorites`, or None when the answer does not say."""
    data = raw.get('data') if isinstance(raw, dict) else None
    resource = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    attrs = resource.get('attributes')
    value = attrs.get('inFavorites') if isinstance(attrs, dict) else None
    return value if isinstance(value, bool) else None


def included_albums(songs):
    """The library albums the songs listing (`include=albums`) carries, each once: what the
    albums' favourites are read from."""
    albums = {}
    for raw in songs:
        related = ((raw.get('relationships') or {}).get('albums') or {}).get('data') or []
        for album in related:
            if isinstance(album, dict) and album.get('id'):
                albums.setdefault(album['id'], album)
    return list(albums.values())


def _extract_catalog_id(attrs, raw_item, resource_type):
    """Extract catalog ID from a catalog or library resource."""
    item_id = str(raw_item.get('id') or '')
    if raw_item.get('type') == resource_type:
        return item_id if item_id else None

    if 'relationships' in raw_item:
        cat_data = raw_item['relationships'].get('catalog', {}).get('data', [])
        if cat_data and isinstance(cat_data, list) and len(cat_data) > 0:
            cid = cat_data[0].get('id')
            if cid:
                return str(cid)

    play_params = attrs.get('playParams') or {}
    if 'catalogId' in play_params:
        return str(play_params['catalogId'])
    # A library playlist names the catalog playlist it is (one of Apple's added, or one the
    # user published) as its play parameters' globalId, a "pl." id.
    global_id = play_params.get('globalId')
    if resource_type == 'playlists' and isinstance(global_id, str) and global_id.startswith(
            'pl.'):
        return global_id

    if raw_item.get('catalogId'):
        return str(raw_item['catalogId'])

    # If item_id does not look like a library id (l.*, i.*, p.*, r.*), treat as catalog ID
    if item_id and not item_id.startswith(('l.', 'i.', 'p.', 'r.')):
        return item_id

    return None


# ---------------------------------------------------------------------------
# Item and Track Normalizers
# ---------------------------------------------------------------------------


def normalize_track(raw_track, index=0, cache_dir=None, art_urls=None):
    """Turn an Apple Music API track into the Track shape.

    Track = {
      "id": "...", "catalogId": "..." | null, "title": "...", "artist": "...",
      "album": "...", "trackNumber": int, "discNumber": int, "durationMs": int,
      "durationLabel": "3:36", "explicit": bool, "index": int,
      "thumb": "<cache>/thumb/<x>.jpg" | null,
      "type": "songs" | "library-songs" | "music-videos" | "library-music-videos" | "",
      "genre": "..." | null, "year": int | null
    }

    `type` is the API's, so a music video in a playlist is rated and added as one. `genre`
    is the first of its `genreNames` and `year` its `releaseDate`'s (track_year()): the
    Songs and playlist tables' Genre and Year columns.

    `thumb` is named only when `cache_dir` is given: a playlist's rows show
    their own artwork, an album's tracks share the album's. `art_urls` is the
    artwork registry (see collect_art_urls).
    """
    attrs = raw_track.get('attributes') or {}
    track_id = str(raw_track.get('id') or '')
    thumb = raw_track.get('thumb') or None
    artwork = attrs.get('artwork')
    if cache_dir and isinstance(artwork, dict) and artwork.get('url'):
        _, thumb = _register_artwork(artwork['url'], cache_dir,
                                     {} if art_urls is None else art_urls)

    catalog_id = _extract_catalog_id(attrs, raw_track, 'songs')

    title = attrs.get('name') or raw_track.get('title') or ''
    artist = attrs.get('artistName') or attrs.get('artist') or raw_track.get('artist') or ''
    album = attrs.get('albumName') or attrs.get('album') or raw_track.get('album') or ''

    track_number = attrs.get('trackNumber')
    if track_number is None:
        track_number = raw_track.get('trackNumber', 1)
    disc_number = attrs.get('discNumber')
    if disc_number is None:
        disc_number = raw_track.get('discNumber', 1)
    duration_ms = attrs.get('durationInMillis')
    if duration_ms is None:
        duration_ms = raw_track.get('durationMs', 0)

    try:
        track_number = int(track_number)
    except (ValueError, TypeError):
        track_number = 1

    try:
        disc_number = int(disc_number)
    except (ValueError, TypeError):
        disc_number = 1

    try:
        duration_ms = int(duration_ms)
    except (ValueError, TypeError):
        duration_ms = 0

    duration_label = format_duration(duration_ms)

    content_rating = attrs.get('contentRating') or raw_track.get('contentRating')
    is_explicit = (
        content_rating == 'explicit'
        or attrs.get('explicit') is True
        or raw_track.get('explicit') is True
    )

    return {
        'id': track_id,
        'catalogId': catalog_id,
        'title': title,
        'artist': artist,
        'album': album,
        'trackNumber': track_number,
        'discNumber': disc_number,
        'durationMs': duration_ms,
        'durationLabel': duration_label,
        'explicit': is_explicit,
        'index': int(index),
        'thumb': thumb,
        'type': str(raw_track.get('type') or ''),
        'genre': _extract_genre(attrs, raw_track),
        'year': track_year(attrs, raw_track),
    }


RELEASE_DATE = re.compile(r'\d{4}(-\d{2}-\d{2})?')


def is_prerelease(attrs, raw_item=None):
    """Whether an album is not out yet: its catalog attributes' `isPrerelease` (Apple's), or
    an Item dict's own `prerelease` (one shaped already)."""
    if isinstance(attrs, dict) and attrs.get('isPrerelease') is True:
        return True
    return isinstance(raw_item, dict) and raw_item.get('prerelease') is True


def release_date(attrs, raw_item=None):
    """An album's `releaseDate` (Apple's 'YYYY-MM-DD', or a year alone) from its attributes
    or an Item dict, its white space trimmed; None when it has none."""
    for source in (attrs, raw_item):
        date = source.get('releaseDate') if isinstance(source, dict) else None
        if isinstance(date, str) and RELEASE_DATE.fullmatch(date.strip()):
            return date.strip()
    return None


def track_released(raw_track):
    """Whether a track of a pre-release album can be played already: Apple gives a track
    not out yet no `playParams` (a pre-release single has them). An entry shaped already says
    so by its own `unreleased`; one with no attributes at all counts as released."""
    if not isinstance(raw_track, dict):
        return True
    attrs = raw_track.get('attributes')
    if not isinstance(attrs, dict):
        return raw_track.get('unreleased') is not True
    return bool(attrs.get('playParams'))


def track_year(attrs, raw_track):
    """A track's year: its `releaseDate`'s (a date, or a year alone), else a `year` it
    carries already (a Track dict normalised again); None without one. Unlike an Item's
    (_extract_year), never a playlist's modification date."""
    released = attrs.get('releaseDate') or raw_track.get('releaseDate')
    if isinstance(released, str) and len(released) >= 4 and released[:4].isdigit():
        return int(released[:4])
    year = raw_track.get('year')
    if isinstance(year, int) and not isinstance(year, bool) and year > 0:
        return year
    return None


def normalize_album(raw_album, cache_dir=None, tracks=None, art_urls=None):
    """Turn an Apple Music API album into the Item shape with kind='album'.

    `tracks` are the album's songs when the caller fetched them separately;
    otherwise the album's own `tracks` relationship is read. Tracks are
    grouped by disc: groups = [{"name": "Disc 1", "play": {...}, "entries": [...]}].

    A pre-release album (is_prerelease()) has `prerelease: true` and its `releaseDate`, and
    each of its tracks not out yet (track_released()) `unreleased: true`; other albums and
    tracks have neither key.
    """
    attrs = raw_album.get('attributes') or {}
    item_id = str(raw_album.get('id') or '')
    title = attrs.get('name') or raw_album.get('title') or ''
    subtitle = attrs.get('artistName') or raw_album.get('subtitle') or ''
    year = _extract_year(attrs, raw_album)
    genre = _extract_genre(attrs, raw_album)
    summary = _extract_summary(attrs, raw_album)
    art, thumb, art_color = _extract_artwork(attrs, raw_album, cache_dir,
                                             {} if art_urls is None else art_urls)
    catalog_id = _extract_catalog_id(attrs, raw_album, 'albums')
    url = attrs.get('url') or raw_album.get('url')

    # Resolve track list
    raw_tracks = tracks
    if raw_tracks is None:
        rel_tracks = raw_album.get('relationships', {}).get('tracks', {}).get('data')
        if isinstance(rel_tracks, list):
            raw_tracks = rel_tracks
        else:
            raw_tracks = []

    def track_sort_key(t):
        t_attrs = t.get('attributes') or {}
        d = t_attrs.get('discNumber')
        if d is None:
            d = t.get('discNumber', 1)
        tr = t_attrs.get('trackNumber')
        if tr is None:
            tr = t.get('trackNumber', 1)
        try:
            d_int = int(d)
        except (ValueError, TypeError):
            d_int = 1
        try:
            tr_int = int(tr)
        except (ValueError, TypeError):
            tr_int = 1
        return (d_int, tr_int)

    sorted_tracks = sorted(raw_tracks, key=track_sort_key)
    prerelease = is_prerelease(attrs, raw_album)

    # One group per disc, the entries numbered on from the discs before: every
    # disc's group plays the whole album (setQueue({album, startWith}), which
    # MusicKit queues in disc and track order), so an entry's `index` is its
    # position in the album, not in its disc.
    raw_discs = {}
    for t in sorted_tracks:
        t_attrs = t.get('attributes') or {}
        d = t_attrs.get('discNumber')
        if d is None:
            d = t.get('discNumber', 1)
        try:
            d_int = int(d) if d is not None else 1
        except (ValueError, TypeError):
            d_int = 1
        raw_discs.setdefault(d_int, []).append(t)

    normalized_tracks = []
    groups = []
    for d in sorted(raw_discs.keys()):
        disc_label = f'Disc {d if d > 0 else 1}'
        disc_entries = [
            _with_release(normalize_track(t, index=len(normalized_tracks) + idx), t,
                          prerelease)
            for idx, t in enumerate(raw_discs[d])
        ]
        normalized_tracks.extend(disc_entries)
        groups.append({
            'name': disc_label,
            'play': {'kind': 'album', 'id': item_id},
            'entries': disc_entries,
        })

    song_count = len(normalized_tracks)
    # No tracks in hand (a shelf item, normalised without its list): the
    # count alone, and no total time rather than a 0 that reads as empty.
    total_duration_ms = (sum(t['durationMs'] for t in normalized_tracks)
                         if normalized_tracks else None)
    if song_count == 0 and attrs.get('trackCount'):
        try:
            song_count = int(attrs['trackCount'])
        except (ValueError, TypeError):
            song_count = 0

    content_rating = attrs.get('contentRating') or raw_album.get('contentRating')
    is_explicit = (
        content_rating == 'explicit'
        or attrs.get('explicit') is True
        or raw_album.get('explicit') is True
        or any(t.get('explicit') for t in normalized_tracks)
    )

    album = {
        'id': item_id,
        'kind': 'album',
        'title': title,
        'subtitle': subtitle,
        'year': year,
        'genre': genre,
        'summary': summary,
        'art': art,
        'thumb': thumb,
        'artColor': art_color,
        'trackCount': song_count,
        'durationMs': total_duration_ms,
        'explicit': is_explicit,
        'catalogId': catalog_id,
        'url': url,
        'play': {'kind': 'album', 'id': item_id},
        'groups': groups,
    }
    if prerelease:
        album['prerelease'] = True
        date = release_date(attrs, raw_album)
        if date:
            album['releaseDate'] = date
    return _with_added(album, attrs)


def _with_release(entry, raw_track, prerelease):
    """A pre-release album's track entry marked `unreleased` when it is not out yet
    (track_released()); any other entry as it is."""
    if prerelease and not track_released(raw_track):
        entry['unreleased'] = True
    return entry


def normalize_artist(raw_artist, cache_dir=None, albums=None, art_urls=None):
    """Turn an Apple Music API artist into the Item shape with kind='artist'.

    `albums` are the artist's albums (raw, or already normalized) when the
    caller fetched them; otherwise the `albums` relationship is read.
    subtitle '' (the data has no words: an artist is shown as one), groups=[one group per
    album].
    """
    attrs = raw_artist.get('attributes') or {}
    item_id = str(raw_artist.get('id') or '')
    title = attrs.get('name') or raw_artist.get('title') or ''
    subtitle = ''
    year = None
    genre = _extract_genre(attrs, raw_artist)
    summary = _extract_summary(attrs, raw_artist)
    art_urls = {} if art_urls is None else art_urls
    art, thumb, art_color = _extract_artwork(attrs, raw_artist, cache_dir, art_urls)
    catalog_id = _extract_catalog_id(attrs, raw_artist, 'artists')
    url = attrs.get('url') or raw_artist.get('url')

    raw_albums = albums
    if raw_albums is None:
        rel_albums = raw_artist.get('relationships', {}).get('albums', {}).get('data')
        if isinstance(rel_albums, list):
            raw_albums = rel_albums
        else:
            raw_albums = []

    groups = []
    has_explicit = False
    for alb in raw_albums:
        if alb.get('kind') == 'album' and 'groups' in alb and 'play' in alb:
            all_entries = []
            for g in alb.get('groups', []):
                all_entries.extend(g.get('entries', []))
            groups.append({
                'name': alb.get('title', ''),
                'play': alb.get('play', {'kind': 'album', 'id': alb.get('id')}),
                'entries': all_entries,
            })
            if alb.get('explicit'):
                has_explicit = True
        else:
            norm_alb = normalize_album(alb, cache_dir=cache_dir, art_urls=art_urls)
            all_entries = []
            for g in norm_alb.get('groups', []):
                all_entries.extend(g.get('entries', []))
            groups.append({
                'name': norm_alb.get('title', ''),
                'play': norm_alb.get('play', {'kind': 'album', 'id': norm_alb.get('id')}),
                'entries': all_entries,
            })
            if norm_alb.get('explicit'):
                has_explicit = True

    return {
        'id': item_id,
        'kind': 'artist',
        'title': title,
        'subtitle': subtitle,
        'year': year,
        'genre': genre,
        'summary': summary,
        'art': art,
        'thumb': thumb,
        'artColor': art_color,
        'albumCount': len(groups),
        'explicit': has_explicit,
        'catalogId': catalog_id,
        'url': url,
        'play': {'kind': 'artist', 'id': item_id},
        'groups': groups,
    }


def normalize_playlist(raw_playlist, cache_dir=None, tracks=None, art_urls=None):
    """Turn an Apple Music API playlist into the Item shape with kind='playlist'.

    `tracks` are the playlist's songs when the caller fetched them; otherwise
    the `tracks` relationship is read.
    groups=[{"name": "Tracks", "play": {"kind": "playlist", "id": item_id}, "entries": [...]}]
    `modified` is Apple's lastModifiedDate, when the answer has one: what the page says it was
    updated (the sync keeps its own, the tracks' stamp, in its place).
    """
    attrs = raw_playlist.get('attributes') or {}
    item_id = str(raw_playlist.get('id') or '')
    title = attrs.get('name') or raw_playlist.get('title') or ''
    subtitle = (
        attrs.get('curatorName')
        or attrs.get('artistName')
        or raw_playlist.get('subtitle')
        or ''  # the user's own playlists have no curator
    )
    year = _extract_year(attrs, raw_playlist)
    genre = _extract_genre(attrs, raw_playlist)
    summary = _extract_summary(attrs, raw_playlist)
    art_urls = {} if art_urls is None else art_urls
    art, thumb, art_color = _extract_artwork(attrs, raw_playlist, cache_dir, art_urls)
    catalog_id = _extract_catalog_id(attrs, raw_playlist, 'playlists')
    url = attrs.get('url') or raw_playlist.get('url')

    raw_tracks = tracks
    if raw_tracks is None:
        rel_tracks = raw_playlist.get('relationships', {}).get('tracks', {}).get('data')
        if isinstance(rel_tracks, list):
            raw_tracks = rel_tracks
        else:
            raw_tracks = []

    normalized_tracks = [
        normalize_track(t, index=idx, cache_dir=cache_dir, art_urls=art_urls)
        for idx, t in enumerate(raw_tracks)
    ]

    groups = [
        {
            'name': 'Tracks',
            'play': {'kind': 'playlist', 'id': item_id},
            'entries': normalized_tracks,
        }
    ]

    song_count = len(normalized_tracks)
    # No tracks in hand (a shelf item, normalised without its list): the
    # count alone, and no total time rather than a 0 that reads as empty.
    total_duration_ms = (sum(t['durationMs'] for t in normalized_tracks)
                         if normalized_tracks else None)
    if song_count == 0 and attrs.get('trackCount'):
        try:
            song_count = int(attrs['trackCount'])
        except (ValueError, TypeError):
            song_count = 0

    content_rating = attrs.get('contentRating') or raw_playlist.get('contentRating')
    is_explicit = (
        content_rating == 'explicit'
        or attrs.get('explicit') is True
        or raw_playlist.get('explicit') is True
        or any(t.get('explicit') for t in normalized_tracks)
    )

    item = {
        'id': item_id,
        'kind': 'playlist',
        'title': title,
        'subtitle': subtitle,
        'year': year,
        'genre': genre,
        'summary': summary,
        'art': art,
        'thumb': thumb,
        'artColor': art_color,
        'trackCount': song_count,
        'durationMs': total_duration_ms,
        'explicit': is_explicit,
        'catalogId': catalog_id,
        'url': url,
        'play': {'kind': 'playlist', 'id': item_id},
        'groups': groups,
    }
    modified = attrs.get('lastModifiedDate')
    if isinstance(modified, str) and modified:
        item['modified'] = modified
    return _with_added(item, attrs)


def normalize_station(raw_station, cache_dir=None, art_urls=None):
    """Turn an Apple Music API station into the Item shape with kind='station'.

    groups=[]
    """
    attrs = raw_station.get('attributes') or {}
    item_id = str(raw_station.get('id') or '')
    title = attrs.get('name') or raw_station.get('title') or ''
    subtitle = (
        attrs.get('stationProviderName')
        or attrs.get('curatorName')
        or attrs.get('artistName')
        or raw_station.get('subtitle')
        or ''
    )
    year = None
    genre = _extract_genre(attrs, raw_station)
    summary = _extract_summary(attrs, raw_station)
    art, thumb, art_color = _extract_artwork(attrs, raw_station, cache_dir,
                                             {} if art_urls is None else art_urls)
    catalog_id = _extract_catalog_id(attrs, raw_station, 'stations')
    url = attrs.get('url') or raw_station.get('url')

    content_rating = attrs.get('contentRating') or raw_station.get('contentRating')
    is_explicit = (
        content_rating == 'explicit'
        or attrs.get('explicit') is True
        or raw_station.get('explicit') is True
    )

    return {
        'id': item_id,
        'kind': 'station',
        'title': title,
        'subtitle': subtitle,
        'year': year,
        'genre': genre,
        'summary': summary,
        'art': art,
        'thumb': thumb,
        'artColor': art_color,
        'explicit': is_explicit,
        'catalogId': catalog_id,
        'url': url,
        'play': {'kind': 'station', 'id': item_id},
        'groups': [],
    }


def curator_link(raw):
    """A third party's curator (type `curators`: a label's, a magazine's editors; or a
    shared playlist's listener, `social-profiles`) as normalize_item answers one: the app
    has no page for it (category_page reads Apple's curators only), so it is a `link` Item,
    opened on music.apple.com (its `url`), with nothing to play and its name; kind
    `unknown` without an https page."""
    attrs = raw.get('attributes') or {}
    url = attrs.get('url')
    artwork = (attrs.get('artwork') or {}).get('url')
    small = ART_SIZES['thumb']
    has_page = isinstance(url, str) and url.startswith('https://')
    return {'id': str(raw.get('id') or ''), 'kind': 'link' if has_page else 'unknown',
            'title': str(attrs.get('name') or ''), 'subtitle': '', 'year': None,
            'art': template_artwork_url(artwork, small, small) if artwork else None,
            'thumb': None, 'artColor': None, 'url': url if has_page else None, 'play': {},
            'groups': []}


def normalize_song_as_item(raw_song, cache_dir=None, art_urls=None, wide=False):
    """Normalize an Apple Music song into the Item shape (e.g. for search results); `wide`
    for a music video's, whose thumbnail is 16:9 (thumb_box())."""
    attrs = raw_song.get('attributes') or {}
    item_id = str(raw_song.get('id') or '')
    catalog_id = _extract_catalog_id(attrs, raw_song, 'songs')

    art, thumb, art_color = _extract_artwork(attrs, raw_song, cache_dir,
                                             {} if art_urls is None else art_urls, wide=wide)
    duration_ms = attrs.get('durationInMillis')
    if duration_ms is None:
        duration_ms = raw_song.get('durationMs', 0)
    try:
        duration_ms = int(duration_ms)
    except (ValueError, TypeError):
        duration_ms = 0

    year = _extract_year(attrs, raw_song)
    genre = _extract_genre(attrs, raw_song)

    return {
        'id': item_id,
        'kind': 'song',
        'title': attrs.get('name') or raw_song.get('title') or '',
        'subtitle': attrs.get('artistName') or raw_song.get('artist') or '',
        'year': year,
        'genre': genre,
        'summary': None,
        'art': art,
        'thumb': thumb,
        'artColor': art_color,
        'durationMs': duration_ms,
        'explicit': attrs.get('contentRating') == 'explicit' or attrs.get('explicit') is True,
        'catalogId': catalog_id,
        'url': attrs.get('url') or raw_song.get('url'),
        'play': {'kind': 'song', 'id': item_id},
        'groups': [],
    }


def normalize_item(raw_item, cache_dir=None, include_groups=True, art_urls=None):
    """Normalize any Apple Music resource into an Item (`art_urls`: the artwork
    registry, see collect_art_urls)."""
    raw_type = str(raw_item.get('type', ''))
    raw_kind = str(raw_item.get('kind', ''))

    if raw_type in ('albums', 'library-albums') or raw_kind == 'album':
        item = normalize_album(raw_item, cache_dir=cache_dir, art_urls=art_urls)
    elif raw_type in ('playlists', 'library-playlists') or raw_kind == 'playlist':
        item = normalize_playlist(raw_item, cache_dir=cache_dir, art_urls=art_urls)
    elif raw_type in ('artists', 'library-artists') or raw_kind == 'artist':
        item = normalize_artist(raw_item, cache_dir=cache_dir, art_urls=art_urls)
    elif raw_type == 'apple-curators':
        item = curator_item(raw_item)
    elif raw_type == 'curators':
        item = curator_link(raw_item)
    elif raw_type in ('stations', 'radio-stations') or raw_kind == 'station':
        item = normalize_station(raw_item, cache_dir=cache_dir, art_urls=art_urls)
    elif raw_type in ('songs', 'library-songs') or raw_kind == 'song':
        item = normalize_song_as_item(raw_item, cache_dir=cache_dir, art_urls=art_urls)
    elif raw_type in ('music-videos', 'library-music-videos') or raw_kind == 'video':
        # A music video is a song with a picture: the same fields, played
        # as MusicKit's own `musicVideo` queue kind.
        item = normalize_song_as_item(raw_item, cache_dir=cache_dir, art_urls=art_urls,
                                      wide=True)
        item['kind'] = 'video'
        item['play'] = {'kind': 'musicVideo', 'id': item['id']}
        _with_added(item, raw_item.get('attributes'))
    else:
        attrs = raw_item.get('attributes') or {}
        if 'trackCount' in attrs or 'artistName' in attrs:
            item = normalize_album(raw_item, cache_dir=cache_dir, art_urls=art_urls)
        else:
            # Something the app has no page or queue for (an editorial item, an uploaded
            # video): its name and artwork, and nothing to play.
            item = normalize_station(raw_item, cache_dir=cache_dir, art_urls=art_urls)
            item['kind'] = 'unknown'
            item['play'] = {}

    if not include_groups:
        item['groups'] = []
    return item


def normalize_category(raw):
    """An Apple curator as a category tile. None without a name."""
    attrs = raw.get('attributes') or {}
    item_id = str(raw.get('id') or '')
    name = str(attrs.get('name') or '').strip()
    short = str(attrs.get('shortName') or '').strip()
    if not item_id or not (name or short):
        return None
    artwork = attrs.get('artwork') if isinstance(attrs.get('artwork'), dict) else {}
    url = artwork.get('url')
    return {
        'id': item_id,
        'kind': 'category',
        'title': short or name,
        'subtitle': name if name and name != (short or name) else None,
        'art': template_artwork_url(url, CATEGORY_ART_SIZE, CATEGORY_ART_SIZE) if url else None,
        'artColor': format_color(artwork.get('bgColor')) if artwork.get('bgColor') else None,
        'url': attrs.get('url'),
    }


# A category tile's picture, wide but not big: the Search page draws it cropped
# over the tile's colour.
CATEGORY_ART_SIZE = 320


def normalize_curator(raw):
    """An Apple curator (`apple-curators`: a genre's, a curator's, a radio show's) as a
    category tile (normalize_category), a radio show (attributes.kind `Show`) subtitled with
    its host (`showHostName`) where Apple names one. None without a name. Apple gives a
    curator no playParams: nothing plays it, and its tile opens its page (category_page)."""
    item = normalize_category(raw)
    if item is not None:
        attrs = raw.get('attributes') or {}
        host = str(attrs.get('showHostName') or '').strip()
        if attrs.get('kind') == 'Show' and host:
            item['subtitle'] = host
    return item


def curator_item(raw):
    """An Apple curator as normalize_item answers one: its category tile
    (normalize_curator) with nothing to play and no groups, never a station; a nameless one
    is kind `unknown`."""
    item = normalize_curator(raw)
    if item is None:
        attrs = raw.get('attributes') or {}
        item = {'id': str(raw.get('id') or ''), 'kind': 'unknown',
                'title': str(attrs.get('name') or ''), 'subtitle': None, 'art': None,
                'artColor': None, 'url': attrs.get('url')}
    item.update(play={}, groups=[], thumb=None)
    return item


# The resource types an editorial shelf may hold, and the app can show; what
# else Apple puts on a page (uploaded videos, marketing items) is left out.
SHELF_RESOURCE_TYPES = {
    'albums', 'playlists', 'artists', 'stations', 'songs', 'music-videos',
    'library-albums', 'library-playlists', 'library-artists', 'library-songs',
    'library-music-videos',
}


def _shelf_item(raw_item, cache_dir, settle=True, curators=True, art_urls=None):
    """An editorial element's or a recommendation's content as a shelf item:
    an Apple curator as a category tile (normalize_curator: its page is its
    grouping, as on the search page; None without `curators`), a known resource with a name
    without its groups (its art as a search hit's with `settle`, or the
    files a sync fetches, registered in `art_urls`); anything else None."""
    if not isinstance(raw_item, dict):
        return None
    if raw_item.get('type') == 'apple-curators':
        return normalize_curator(raw_item) if curators else None
    if raw_item.get('type') not in SHELF_RESOURCE_TYPES:
        return None
    if not (raw_item.get('attributes') or {}).get('name'):
        return None
    item = normalize_item(raw_item, cache_dir, include_groups=False, art_urls=art_urls)
    if settle:
        _settle_search_art(item, raw_item)
    return item


def _settle_search_art(item, raw_item):
    """A search hit's artwork as it stands: the sync's files where they
    exist, a thumbnail-sized catalog URL for the cover otherwise, and no thumb
    at all rather than the name of one that was never fetched."""
    if not (item.get('thumb') and os.path.exists(item['thumb'])):
        item['thumb'] = None
    if not (item.get('art') and os.path.exists(item['art'])):
        url = ((raw_item.get('attributes') or {}).get('artwork') or {}).get('url')
        small = ART_SIZES['thumb']
        item['art'] = template_artwork_url(url, small, small) if url else None


def _link_item(resource):
    """A video about an artist (an interview, a film) as an Item the app opens on
    music.apple.com: kind `link`, marked `video` (its tile a 16:9 frame: wide_art()), its
    page as `url`, its length as the subtitle, its artwork's URL in the thumbnail's wide
    box, nothing to play. None without a name or a page."""
    attrs = resource.get('attributes') or {}
    url = attrs.get('postUrl') or attrs.get('url')
    name = attrs.get('name')
    if not (isinstance(url, str) and url.startswith('https://') and isinstance(name, str)
            and name):
        return None
    duration = attrs.get('durationInMilliseconds') or attrs.get('durationInMillis')
    artwork = (attrs.get('artwork') or {}).get('url')
    return {
        'id': str(resource.get('id') or url),
        'kind': 'link',
        'video': True,
        'title': name,
        'subtitle': (format_duration(duration) if isinstance(duration, int) and duration > 0
                     else ''),
        'year': _extract_year(attrs, resource),
        'art': (template_artwork_url(artwork, *thumb_box(ART_SIZES['thumb'], wide=True))
                if artwork else None),
        'thumb': None,
        'url': url,
        'play': {},
        'groups': [],
    }


def stand_in_album_id(album_name, artist_name):
    """The id of the stand-in album the library makes up for the loose songs of that album
    and artist name: `l.alb_` and a hash of the two. The sync's, and how the library's artist
    view finds the album a group of an artist's loose songs is (discography.py)."""
    return f"l.alb_{hashlib.md5(f'{album_name}:{artist_name}'.encode()).hexdigest()[:12]}"


def group_songs_into_albums_and_artists(songs, cache_dir=None, art_urls=None):
    """Group songs from /v1/me/library/songs?include=albums into albums and artists.

    A song in no library album (a loose song) goes under a stand-in album the library makes
    up (`l.alb_<hash of its album and artist names>`), which Apple has no resource for: it
    plays its songs by id, {"kind": "songs", "id": "<song id>,<song id>…"} in its entries'
    order, for the album and each of its groups, so a row's `index` starts at its song."""
    albums_map = {}
    for s in songs:
        s_attrs = s.get('attributes') or {}
        # A missing name stays '': the app has the words for it (library.unknown_title).
        album_name = s_attrs.get('albumName') or ''
        artist_name = s_attrs.get('artistName') or ''

        rel_albums = s.get('relationships', {}).get('albums', {}).get('data', [])
        if rel_albums:
            alb_rel = rel_albums[0]
            alb_id = alb_rel.get('id')
            # A song can point at a library album that no longer answers
            # (the relationship survives the album resource): a stub with
            # no attributes. The song itself knows the album's name, artist
            # and artwork, so the stub is filled in from it rather than
            # becoming a nameless tile.
            alb_attrs = dict(alb_rel.get('attributes') or {})
            if not alb_attrs.get('name'):
                alb_attrs.setdefault('name', album_name)
                alb_attrs.setdefault('artistName', artist_name)
                alb_attrs.setdefault('artwork', s_attrs.get('artwork'))
                alb_attrs.setdefault('releaseDate', s_attrs.get('releaseDate'))
                alb_attrs.setdefault('genreNames', s_attrs.get('genreNames', []))
                alb_attrs.setdefault('contentRating', s_attrs.get('contentRating'))
            alb_obj = dict(alb_rel, attributes=alb_attrs)
        else:
            alb_id = stand_in_album_id(album_name, artist_name)
            alb_obj = {
                'id': alb_id,
                'type': 'library-albums',
                'attributes': {
                    'name': album_name,
                    'artistName': artist_name,
                    'artwork': s_attrs.get('artwork'),
                    'releaseDate': s_attrs.get('releaseDate'),
                    'genreNames': s_attrs.get('genreNames', []),
                    'contentRating': s_attrs.get('contentRating'),
                },
            }

        if alb_id not in albums_map:
            albums_map[alb_id] = {
                'album': alb_obj,
                'songs': [],
                'stand_in': not rel_albums,
            }
        albums_map[alb_id]['songs'].append(s)

    albums_list = []
    artists_map = {}
    for entry in albums_map.values():
        alb_norm = normalize_album(entry['album'], cache_dir=cache_dir, tracks=entry['songs'],
                                   art_urls=art_urls)
        if entry['stand_in']:
            song_ids = ','.join(track['id'] for group in alb_norm['groups']
                                for track in group['entries'])
            alb_norm['play'] = {'kind': 'songs', 'id': song_ids}
            for group in alb_norm['groups']:
                group['play'] = dict(alb_norm['play'])
        albums_list.append(alb_norm)

        art_name = alb_norm['subtitle']
        artists_map.setdefault(art_name, []).append(alb_norm)

    albums_list.sort(key=lambda a: a.get('title', '').lower())

    artists_list = []
    for art_name, art_albums in sorted(artists_map.items(), key=lambda x: x[0].lower()):
        art_id = f"l.art_{hashlib.md5(art_name.encode('utf-8')).hexdigest()[:12]}"
        first_art = art_albums[0]['art'] if art_albums and art_albums[0].get('art') else None
        first_thumb = (art_albums[0].get('thumb')
                       if art_albums and art_albums[0].get('art') else None)
        first_color = art_albums[0].get('artColor') if art_albums else None

        art_obj = {
            'id': art_id,
            'type': 'library-artists',
            'attributes': {
                'name': art_name,
                'genreNames': ([art_albums[0].get('genre')]
                               if art_albums and art_albums[0].get('genre') else []),
            },
        }
        artist_norm = normalize_artist(art_obj, cache_dir=cache_dir, albums=art_albums,
                                       art_urls=art_urls)
        # A library artist carries no artwork of its own: it takes its first
        # album's — the thumbnail with the cover, or the tile would decode
        # the full cover for want of one.
        if not artist_norm['art']:
            artist_norm['art'] = first_art
            artist_norm['thumb'] = first_thumb
            artist_norm['artColor'] = first_color
        artists_list.append(artist_norm)

    return albums_list, artists_list
