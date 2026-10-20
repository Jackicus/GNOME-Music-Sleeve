# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's answers as the library's data, and the artwork cache.

Pure functions turn Apple Music API answers into the Item, Track and shelf shapes that
README.md describes: normalize_album() and the other normalize_* functions, the search and
shelf shapers the engine's commands answer with, and group_songs_into_albums_and_artists() for
the sync. They write data, never words: counts are numbers (trackCount, durationMs,
albumCount), a shelf the app names is a key with an empty title, a missing name is '', and
the app makes and translates the words (library.py, the pages). Beside them, the artwork
cache (a file name for each artwork URL, fetching what is missing, pruning what nothing
names), library.json, and the answers the engine keeps for a day. The standard library only;
the thread pool and urllib are imported where they are used.
"""

import hashlib
import html
import json
import logging
import os
import re
import time
from datetime import UTC, datetime

from . import api, config, store

log = logging.getLogger(__name__)

# What download_art raises when it gives up (store.CacheGone, a wiped cache, is one too).
Cancelled = store.Cancelled

# How long a kept answer (landing, a category, the New page, Made for You, Charts) is answered
# from the cache before Apple is asked again, and a song's lyrics (Apple replaces plain lyrics
# with synced ones, and corrects them).
ANSWER_MAX_AGE = 24 * 60 * 60
LYRICS_MAX_AGE = 30 * 24 * 60 * 60
# How long prune_caches() leaves a kept answer: past its day it is no longer fresh, but it is
# what the engine answers, marked stale, when Apple cannot be asked (the engine down, signed
# out, offline), so it stays until an answer from Apple replaces it, or for this long.
ANSWER_KEEP_AGE = 30 * 24 * 60 * 60

# What prune_caches() leaves of the caches that only grow: the covers the pages fetch
# themselves, and the lyrics of the songs played last.
REMOTE_ART_BUDGET = 32 * 1024 * 1024
LYRICS_KEEP = 2000
# The day-long answers in the cache's top folder, beside categories/.
KEPT_ANSWERS = ('landing.json', 'browse.json', 'made-for-you.json', 'radio.json', 'charts.json',
                'recent-played.json')
# The folders of day-long answers, one file an item.
ANSWER_FOLDERS = ('categories', 'artists', 'albums', 'suggestions', 'credits')

# Scaling a cached cover down to its thumbnail, without fetching it again,
# takes an image library, and nothing in the backend imports gi. The app
# installs one here: a callable scale_image(src_path, dest_path, size) that
# writes a JPEG at most size x size to dest_path and raises on failure
# (GdkPixbuf, in the app). Without one, thumbnails are downloaded instead.
scale_image = None


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
# Artwork templating, caching, and pruning
# ---------------------------------------------------------------------------


def template_artwork_url(url_template, width=None, height=None):
    """Format an Apple Music artwork URL template by replacing dimensions and formats.

    Replaces {w} with width, {h} with height (the cover's size unless given).
    Also {f} with 'jpg', {c} with 'bb' if present.
    """
    if not url_template:
        return ''
    width = width or ART_SIZES['cover']
    height = height or ART_SIZES['cover']
    return (
        url_template.replace('{w}x{h}', f'{width}x{height}')
        .replace('{w}', str(width))
        .replace('{h}', str(height))
        .replace('{f}', 'jpg')
        .replace('{c}', 'bb')
    )


def format_artwork_url(artwork_obj, width=None, height=None):
    """Convenience wrapper for dict artwork object or string template."""
    if not artwork_obj:
        return None
    if isinstance(artwork_obj, dict):
        url = artwork_obj.get('url')
    else:
        url = str(artwork_obj)
    if not url:
        return None
    return template_artwork_url(url, width, height)


def artwork_filename(url):
    """Return the SHA-1 cache filename for an artwork URL."""
    if not url:
        return ''
    digest = hashlib.sha1(url.encode('utf-8')).hexdigest()
    return f'{digest}.jpg'


def artwork_cache_path(url, cache_dir):
    """Return the absolute path in the cache directory for an artwork URL."""
    return os.path.join(cache_dir, 'art', artwork_filename(url))


# The two sizes artwork is kept at, in pixels. The cover is the hero of a detail page; the
# thumbnail is the copy the tiles and the track rows draw, so a page of tiles decodes small
# files. Named after the same URL as the full-size file, so <cache>/thumb/<x>.jpg is the
# thumbnail of <cache>/art/<x>.jpg. These are the defaults, from config; a sync sets them
# with apply_art_sizes, and the marker file beside the covers records what a cache was built
# at (load_art_sizes reads it once, at startup).
DEFAULT_ART_SIZES = {'cover': config.COVER_SIZE, 'thumb': config.THUMB_SIZE}
ART_SIZES = dict(DEFAULT_ART_SIZES)
ART_SIZE_LIMITS = {'cover': (256, 1024), 'thumb': (96, 512)}


def _art_sizes_marker(cache_dir):
    return os.path.join(cache_dir, 'art', '.sizes')


def _read_art_sizes_marker(cache_dir):
    """What the cache was built at, or the defaults where nothing says."""
    sizes = dict(DEFAULT_ART_SIZES)
    try:
        with open(_art_sizes_marker(cache_dir), encoding='utf-8') as f:
            marker = json.load(f)
    except FileNotFoundError:
        return sizes
    except (OSError, ValueError) as error:
        log.debug('art sizes marker: %s', error)
        return sizes
    if isinstance(marker, dict):
        for key in sizes:
            if isinstance(marker.get(key), int) and marker[key] > 0:
                sizes[key] = marker[key]
    return sizes


def load_art_sizes(cache_dir):
    """The sizes the cache at `cache_dir` was built at, from its marker, taken as this
    process's ART_SIZES so every URL it names agrees with the files on disk. A tiny file read,
    once at startup (the app's install_scaler)."""
    ART_SIZES.update(_read_art_sizes_marker(cache_dir))
    return dict(ART_SIZES)


def wanted_art_sizes(cover, thumb):
    """{'cover', 'thumb'}: the sizes asked for, within ART_SIZE_LIMITS (one that is not a
    number keeps ART_SIZES'). Nothing is set or written."""
    wanted = {}
    for key, value in (('cover', cover), ('thumb', thumb)):
        low, high = ART_SIZE_LIMITS[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = ART_SIZES[key]
        wanted[key] = max(low, min(high, value))
    return wanted


def apply_art_sizes(cache_dir, cover, thumb, generation=None):
    """Set the sizes a sync builds at, and record them in the marker. A
    thumbnail size that differs from the marker's wipes <cache>/thumb/:
    the files keep their names whatever the size, so nothing else would
    tell a stale one from a right one, and they are rebuilt from the
    covers without a fetch. A cover size that differs needs nothing: the
    new size is a new URL, hence a new name, and the old files go with
    the next prune as unreferenced."""
    wanted = wanted_art_sizes(cover, thumb)
    previous = _read_art_sizes_marker(cache_dir)
    if wanted['thumb'] != previous['thumb']:
        thumb_dir = os.path.join(cache_dir, 'thumb')
        try:
            for entry in os.listdir(thumb_dir):
                try:
                    os.remove(os.path.join(thumb_dir, entry))
                except OSError as error:
                    log.debug('stale thumbnail: %s', error)
        except OSError as error:
            log.debug('stale thumbnails: %s', error)
    try:
        store.atomic_write(_art_sizes_marker(cache_dir), lambda f: json.dump(wanted, f),
                           root=cache_dir, text=True, generation=generation)
    except OSError as error:
        log.warning('could not write the art sizes marker: %s', error)
    ART_SIZES.update(wanted)
    return dict(ART_SIZES)


def thumb_cache_path(url, cache_dir):
    """The thumbnail's path for a full-size artwork URL."""
    return os.path.join(cache_dir, 'thumb', artwork_filename(url))


def make_thumbnail(src_path, dest_path, cache_dir, size=None, generation=None):
    """Scale the cover at `src_path` down to `dest_path` (in the cache at
    `cache_dir`), atomically. False without a scale_image installed, when the
    source is not an image, or when `generation` moved (store.py)."""
    if scale_image is None:
        return False
    size = size or ART_SIZES['thumb']
    try:
        return store.atomic_create(dest_path, lambda temp: scale_image(src_path, temp, size),
                                   root=cache_dir, generation=generation) is not None
    except Exception as error:  # the scaler's own errors (GLib.Error) as well as OSError
        log.debug('could not scale %s: %s', src_path, error)
        return False


def cache_thumbnail(url, cache_dir, dest_path, generation=None):
    """The thumbnail at `dest_path`: scaled from the cached full-size cover
    when that is on disk, fetched at the thumbnail size from `url` otherwise."""
    if not url or not dest_path:
        return None
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return dest_path
    full = os.path.join(cache_dir, 'art', os.path.basename(dest_path))
    if not _art_missing(full) and make_thumbnail(full, dest_path, cache_dir,
                                                 generation=generation):
        return dest_path
    return cache_artwork(url, cache_dir, dest_path=dest_path, generation=generation)


def cache_artwork(url_or_obj, cache_dir, timeout=10.0, dest_path=None, generation=None):
    """Download artwork via urllib.request and save it atomically to <cache_dir>/art/
    (or to `dest_path`, for a thumbnail; a `dest_path` outside the cache is refused).

    Accepts either an artwork URL string or an Apple Music artwork dictionary.
    Written through a temporary file renamed over the target (store.atomic_write), without an
    fsync: a copy of what is on Apple's servers, which counts as missing if a crash left it
    empty. Returns the absolute local file path on success, or None when it failed (logged,
    with the reason) or `generation` moved (the cache was cleared: store.py).
    """
    if not url_or_obj or not cache_dir:
        return None

    if isinstance(url_or_obj, dict):
        url = format_artwork_url(url_or_obj)
    else:
        url = str(url_or_obj)

    if not url:
        return None

    dest_path = os.path.abspath(dest_path or artwork_cache_path(url, cache_dir))
    if not store.inside(dest_path, cache_dir):
        log.warning('artwork: %s is outside the cache, not written', dest_path)
        return None

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return dest_path
    if not store.current(generation):
        return None

    import shutil
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'AppleMusicGNOME/1.0'}
    )

    def fetch(file):
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, 'status', 200)
            if status != 200:
                raise _FetchError(f'HTTP {status}')
            shutil.copyfileobj(resp, file, 64 * 1024)

    try:
        return store.atomic_write(dest_path, fetch, root=cache_dir, fsync=False,
                                  generation=generation)
    except Exception as error:  # urllib's HTTPError, URLError and timeouts, OSError
        if isinstance(error, urllib.error.HTTPError):
            error.close()  # it holds the answer's connection
        log.warning('artwork: could not fetch %s: %s', url, error)
        return None


class _FetchError(Exception):
    """An answer that is not the image: its status."""


# The artwork registry, `art_urls`: every artwork path the normalisers hand out, and the URL
# it is fetched from (the cover-sized one for a cover, the thumbnail-sized one for its
# thumbnail). A job that fetches what it normalised (a sync, the engine's item()) makes one
# dict and passes it to the normalisers, then to collect_art_urls() or download_item_art();
# one that only names files passes nothing and a throwaway dict is used. Normalisation only
# names the file; nothing is fetched until download_art() runs over a finished library (or
# download_item_art() over one item), so a sync's hundreds of downloads happen together, in
# threads, rather than one at a time in the middle of building each item.


def place_in_remote_art(item, art_urls, cache_dir):
    """Point an item fetched on demand (the engine's item(): a catalog album, playlist or
    artist, mostly not in the library) at <cache>/remote-art/ for the artwork the library
    does not have on disk. art/ and thumb/ belong to library.json and are pruned against it
    after every sync, which would take the files from under an open page; remote-art/ is
    trimmed only to its budget. Each file is named after its URL's hash, as the pages' own
    remote art is (the app's remote.remote_art_path), so the player bar and a page share one.
    Rewrites the item's `art`, `thumb` and rows' `thumb` in place and returns the registry of
    what it points at: {path: url}, for download_item_art."""
    remote = os.path.join(cache_dir, 'remote-art')
    placed = {}

    def place(path):
        url = art_urls.get(path) if path else None
        if url is None:
            return path
        if not _art_missing(path):
            placed[path] = url  # the library's copy, on disk already
            return path
        moved = os.path.join(remote, artwork_filename(url))
        placed[moved] = url
        return moved

    for key in ('art', 'thumb'):
        if item.get(key):
            item[key] = place(item[key])
    for group in item.get('groups') or []:
        for entry in group.get('entries') or []:
            if isinstance(entry, dict) and entry.get('thumb'):
                entry['thumb'] = place(entry['thumb'])
    return placed


def _is_thumb_path(path, cache_dir):
    thumbs = os.path.abspath(os.path.join(cache_dir, 'thumb'))
    return os.path.dirname(os.path.abspath(path)) == thumbs


def _art_missing(path):
    try:
        return os.path.getsize(path) <= 0
    except OSError:
        return True


def collect_art_urls(library_data, art_urls):
    """{path: url} for every artwork the library refers to that `art_urls` knows."""
    return {p: art_urls[p] for p in collect_art_paths(library_data) if p in art_urls}


def download_art(urls, cache_dir, workers=8, progress=None, cancelled=None, generation=None):
    """Fetch the artwork of a {path: url} map (collect_art_urls') that is not in
    the cache yet.

    Returns {"wanted", "fetched", "failed"}. Failures are logged (by
    cache_artwork, with the reason) and otherwise ignored: the UI treats a
    path that is not on disk as no artwork. `progress(done, total)` is called
    (on this thread) after each fetch, and `cancelled()` is asked before each
    result is waited for: once it answers True, the fetches not started yet are
    given up, the running ones finish, and Cancelled is raised, so a caller
    never takes a cancelled download for a finished one. When the cache's
    generation moves from `generation` (it was cleared: store.py), the same,
    with store.CacheGone (a Cancelled), and the running ones write nothing.
    """
    todo = {p: u for p, u in urls.items() if _art_missing(p)}
    counts = {'wanted': len(urls), 'fetched': 0, 'failed': 0}
    if not todo:
        return counts
    import concurrent.futures
    for folder in ('art', 'thumb'):
        if not store.make_dirs(os.path.join(cache_dir, folder), root=cache_dir,
                               generation=generation):
            raise store.CacheGone(cache_dir)
    # The covers first, the thumbnails after: a thumbnail is scaled from its
    # cover when that is on disk, and fetched only when it is not.
    covers = {p: u for p, u in todo.items() if not _is_thumb_path(p, cache_dir)}
    thumbs = {p: u for p, u in todo.items() if _is_thumb_path(p, cache_dir)}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for batch, fetch in (
                (covers, lambda p, u: cache_artwork(u, cache_dir, generation=generation)),
                (thumbs, lambda p, u: cache_thumbnail(u, cache_dir, p, generation=generation))):
            if cancelled and cancelled():
                raise Cancelled('artwork')
            futures = {pool.submit(fetch, path, url): url for path, url in batch.items()}
            for fut in concurrent.futures.as_completed(futures):
                gone = not store.current(generation)
                if gone or (cancelled and cancelled()):
                    for pending in futures:
                        pending.cancel()  # the pool still waits for the running ones
                    raise store.CacheGone(cache_dir) if gone else Cancelled('artwork')
                ok = False
                try:
                    ok = bool(fut.result())
                except Exception as error:
                    log.warning('artwork: could not fetch %s: %s', futures[fut], error)
                if ok:
                    counts['fetched'] += 1
                else:
                    counts['failed'] += 1
                done += 1
                if progress:
                    progress(done, len(todo))
    return counts


def download_item_art(item, cache_dir, art_urls, generation=None):
    """Fetch what one item refers to and lacks (its cover, its thumbnail and
    its rows' thumbnails, a playlist's), from the URLs `art_urls` holds for
    them (the registry it was normalised with), in threads. Nothing more once
    the cache's generation moves from `generation` (store.py)."""
    if not isinstance(item, dict):
        return item
    paths = _item_art_paths(item)
    try:
        download_art({p: art_urls[p] for p in paths if p in art_urls}, cache_dir,
                     generation=generation)
    except store.CacheGone:
        log.debug('item %s: the cache was cleared, its artwork left', item.get('id'))
    return item


def _item_art_paths(item):
    """Every artwork path an item refers to: its own, and its rows' thumbnails."""
    paths = set()
    for key in ('art', 'thumb'):
        if item.get(key):
            paths.add(os.path.abspath(item[key]))
    for group in item.get('groups') or []:
        for entry in group.get('entries') or []:
            if isinstance(entry, dict) and entry.get('thumb'):
                paths.add(os.path.abspath(entry['thumb']))
    return paths


def collect_art_paths(library_data):
    """Collect all referenced local artwork paths — covers and thumbnails —
    from a library data dict."""
    paths = set()
    for sec_items in library_data.get('sections', {}).values():
        for item in sec_items:
            paths |= _item_art_paths(item)
    for shelf in library_data.get('shelves', []):
        for item in shelf.get('items', []):
            paths |= _item_art_paths(item)
    return paths


def prune_art(library_data, cache_dir):
    """Remove artwork files in <cache_dir>/art/ and <cache_dir>/thumb/ that
    the library no longer refers to. Returns the count of pruned files."""
    if not cache_dir:
        return 0

    norm_refs = set()
    for p in collect_art_paths(library_data):
        norm_refs.add(os.path.abspath(p))
        norm_refs.add(os.path.basename(p))

    pruned = 0
    for folder in ('art', 'thumb'):
        art_dir = os.path.join(cache_dir, folder)
        if not os.path.isdir(art_dir):
            continue
        try:
            for entry in os.listdir(art_dir):
                file_path = os.path.join(art_dir, entry)
                # The sizes marker lives here too, and is nobody's artwork; a temporary file
                # is a download in progress, or a crash's leftover once it is old.
                if entry.startswith('.'):
                    if store.is_stale_temp(file_path) and _remove(file_path):
                        pruned += 1
                    continue
                abs_path = os.path.abspath(file_path)
                if abs_path not in norm_refs and entry not in norm_refs:
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.remove(file_path)
                            pruned += 1
                    except OSError as error:
                        log.debug('prune: %s', error)
        except OSError as error:
            log.debug('prune: %s', error)

    return pruned


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


def _extract_artwork(attrs, raw_item, cache_dir, art_urls):
    """Extract the local cached cover path, its thumbnail's, and the hex
    background color; the files' URLs go into `art_urls`."""
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
            art, thumb = _register_artwork(url, cache_dir, art_urls)
        bg = artwork.get('bgColor')
        if bg and not art_color:
            art_color = format_color(bg)

    return art, thumb, art_color


def _register_artwork(url_template, cache_dir, art_urls):
    """Name the cover and thumbnail files for an artwork URL template and
    record in `art_urls` what each is fetched from."""
    cover, small = ART_SIZES['cover'], ART_SIZES['thumb']
    full = template_artwork_url(url_template, cover, cover)
    art = artwork_cache_path(full, cache_dir)
    thumb = thumb_cache_path(full, cache_dir)
    art_urls[art] = full
    art_urls[thumb] = template_artwork_url(url_template, small, small)
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
      "type": "songs" | "library-songs" | "music-videos" | "library-music-videos" | ""
    }

    `type` is the API's, so a music video in a playlist is rated and added as one.

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
    }


def normalize_album(raw_album, cache_dir=None, tracks=None, art_urls=None):
    """Turn an Apple Music API album into the Item shape with kind='album'.

    `tracks` are the album's songs when the caller fetched them separately;
    otherwise the album's own `tracks` relationship is read. Tracks are
    grouped by disc: groups = [{"name": "Disc 1", "play": {...}, "entries": [...]}].
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
            normalize_track(t, index=len(normalized_tracks) + idx)
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

    return _with_added({
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
    }, attrs)


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
    """A third party's curator (type `curators`: a label's, a magazine's editors) as
    normalize_item answers one: the app has no page for it (category_page reads Apple's
    curators only), so it is a `link` Item, opened on music.apple.com (its `url`), with
    nothing to play and its name; kind `unknown` without an https page."""
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


def normalize_song_as_item(raw_song, cache_dir=None, art_urls=None):
    """Normalize an Apple Music song into the Item shape (e.g. for search results)."""
    attrs = raw_song.get('attributes') or {}
    item_id = str(raw_song.get('id') or '')
    catalog_id = _extract_catalog_id(attrs, raw_song, 'songs')

    art, thumb, art_color = _extract_artwork(attrs, raw_song, cache_dir,
                                             {} if art_urls is None else art_urls)
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
        item = normalize_song_as_item(raw_item, cache_dir=cache_dir, art_urls=art_urls)
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


# The shelves a search can answer with, as MusicKit names them, in the order they take when
# the answer does not say (Apple's own for a search of this kind, as its `meta.results.order`
# has it). Each is keyed by its kind without the "library-" (`top` for `topResults`, the
# catalog's own pick of its best few hits across every kind, asked for `with=topResults`,
# which Apple Music's own search page puts first) and untitled: the Search page has the
# words. Apple's curators make two shelves, `radio-shows` (those of kind Show) and
# `curators` (the rest, with the third parties' `curators`): category tiles (curator_item)
# and, for a third party's, a link (curator_link), each marked with `curatorKind` ('show' or
# 'curator') for the page's words.
SEARCH_SHELF_ORDER = [
    'topResults', 'artists', 'library-artists', 'songs', 'library-songs',
    'albums', 'library-albums', 'playlists', 'library-playlists', 'music-videos', 'stations',
    'apple-curators', 'curators',
]


def _search_shelf_key(section, raw_item):
    """The key of the shelf a hit in an answer's `section` goes on (search_results)."""
    if section == 'topResults':
        return 'top'
    if section == 'apple-curators':
        kind = (raw_item.get('attributes') or {}).get('kind')
        return 'radio-shows' if kind == 'Show' else 'curators'
    return section.removeprefix('library-')


def search_results(raw, cache_dir, kind=None):
    """Engine.search()'s answer from MusicKit's: `shelves`, one per kind that
    answered, each `{key, title: '', items, next}` (key `top`, `artists`,
    `albums`, `songs`, `playlists`, `music-videos`, `stations`, `radio-shows`
    or `curators`), in the order Apple's own search page shows them
    (`meta.results.order`, or SEARCH_SHELF_ORDER without it) with the top
    results first. `next` is the offset of Apple's next page of the kind
    (api.next_offset of its section's `next` link), or None when Apple has
    no more. With `kind` (a search for that kind alone), only its shelf,
    even with nothing on it (a page of Apple's curators holding no radio show
    still names the next).

    A search never waits on a download, so a hit's `art` is its cached
    cover when the sync has fetched it and a small catalog URL otherwise,
    which the Search page fetches on its own; its `thumb` only ever names a
    file that is on disk."""
    results = (raw or {}).get('results') or {}
    order = ((raw or {}).get('meta') or {}).get('results', {}).get('order')
    if not isinstance(order, list):
        order = []
    keys = [k for k in order if k in SEARCH_SHELF_ORDER]
    keys += [k for k in SEARCH_SHELF_ORDER if k not in keys]
    shelves = {}  # by key, in the order they are made

    def shelf(key):
        return shelves.setdefault(key, {'key': key, 'title': '', 'items': [], 'next': None})

    for key in keys:
        section = results.get(key)
        if not isinstance(section, dict):
            continue
        targets = (('radio-shows', 'curators') if key == 'apple-curators'
                   else (_search_shelf_key(key, {}),))
        for target in targets:
            shelf(target)
        for raw_item in section.get('data') or []:
            if not isinstance(raw_item, dict):
                continue
            item = normalize_item(raw_item, cache_dir, include_groups=False)
            _settle_search_art(item, raw_item)
            shelf_key = _search_shelf_key(key, raw_item)
            if key in ('apple-curators', 'curators'):  # the page words what it is
                item['curatorKind'] = 'show' if shelf_key == 'radio-shows' else 'curator'
            shelf(shelf_key)['items'].append(item)
        following = api.next_offset(section.get('next'))
        if following is not None:
            for target in targets:
                current = shelves[target]['next']
                shelves[target]['next'] = following if current is None else min(current,
                                                                                 following)
    if kind is not None:
        return {'shelves': [found for found in shelves.values() if found['key'] == kind]}
    return {'shelves': [found for found in shelves.values() if found['items']]}


def search_suggestions(raw, cache_dir):
    """Engine.suggest()'s answer from MusicKit's `search/suggestions`:
    `terms`, the few searches Apple would complete the typed one to, each
    `{term, display}` — `term` what to search for, `display` as Apple
    shows it — with no repeats; and `items`, its best few hits for what is
    typed so far, as `search_results` has its hits (no groups, art as it
    stands)."""
    suggestions = ((raw or {}).get('results') or {}).get('suggestions') or []
    terms = []
    items = []
    seen_terms = set()
    seen_items = set()
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        kind = suggestion.get('kind')
        if kind == 'terms':
            term = str(suggestion.get('searchTerm') or suggestion.get('displayTerm') or '').strip()
            if not term or term.lower() in seen_terms:
                continue
            seen_terms.add(term.lower())
            display = str(suggestion.get('displayTerm') or term).strip()
            terms.append({'term': term, 'display': display})
        elif kind == 'topResults':
            content = suggestion.get('content')
            if not isinstance(content, dict):
                continue
            item = normalize_item(content, cache_dir, include_groups=False)
            _settle_search_art(item, content)
            if (item['kind'], item['id']) in seen_items:
                continue
            seen_items.add((item['kind'], item['id']))
            items.append(item)
    return {'terms': terms, 'items': items}


def search_landing(raw, cache_dir):
    """Engine.landing()'s answer from Apple's search-landing recommendations:
    `categories`, the rooms Apple Music's own search page offers to browse
    before anything is typed (Rock, Hip-Hop, Chill, the decades…), in
    Apple's order across every recommendation in the set, each
    `{id, kind: "category", title, subtitle, art, artColor, url}` — `title`
    the short name on the tile ("Rock"), `subtitle` the curator's own
    ("Apple Music Rock"), `art` a small catalog URL the Search page fetches
    on its own, `artColor` the tile's colour behind it. Only Apple's curators
    are categories: an editorial item in the set is a banner with nothing
    behind it, and is left out."""
    categories = []
    seen = set()
    for rec in (raw or {}).get('data') or []:
        if not isinstance(rec, dict):
            continue
        contents = ((rec.get('relationships') or {}).get('contents') or {}).get('data') or []
        for content in contents:
            if not isinstance(content, dict) or content.get('type') != 'apple-curators':
                continue
            category = normalize_category(content)
            if not category or category['id'] in seen:
                continue
            seen.add(category['id'])
            categories.append(category)
    return {'categories': categories}


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


def category_page(raw, cache_dir):
    """Engine.category()'s answer from a curator with its grouping and its
    playlists (a genre's, or a radio show's: its episodes, albums and
    playlists): the category's `id` and `title`, and its `shelves` — the
    grouping's one tab's editorial elements, each `{key, title, items}` in
    Apple's order, items normalised as a search hit is (no groups, art as it
    stands), then the curator's own playlists (_curator_playlists); an
    element with no title or nothing in it is left out."""
    data = (raw or {}).get('data') or []
    curator = data[0] if data and isinstance(data[0], dict) else {}
    attrs = curator.get('attributes') or {}
    title = str(attrs.get('shortName') or attrs.get('name') or '').strip()
    shelves = []
    groupings = ((curator.get('relationships') or {}).get('grouping') or {}).get('data') or []
    for grouping in groupings:
        if isinstance(grouping, dict):
            shelves.extend(_grouping_shelves(grouping, cache_dir, 'cat'))
    playlists = _curator_playlists(curator, cache_dir, shelves)
    if playlists is not None:
        shelves.append(playlists)
    return {'id': str(curator.get('id') or ''), 'title': title, 'shelves': shelves}


def _curator_playlists(curator, cache_dir, shelves):
    """A curator's own playlists (its `playlists` relationship) as the category page's last
    shelf, keyed `playlists` and untitled (the app names it), less those its grouping's
    `shelves` show already; None when none is left."""
    shown = {(item['kind'], item['id']) for shelf in shelves for item in shelf['items']}
    relationship = (curator.get('relationships') or {}).get('playlists') or {}
    items = []
    for raw_item in relationship.get('data') or []:
        item = _shelf_item(raw_item, cache_dir, curators=False)
        if item is None or item['kind'] != 'playlist' or (item['kind'], item['id']) in shown:
            continue
        shown.add((item['kind'], item['id']))
        items.append(item)
    return {'key': 'playlists', 'title': '', 'items': items} if items else None


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


def _element_contents(element):
    """What an editorial element holds: its contents, or, for one made of
    other elements (the banners at the top of the New page, each with one
    item), the contents of each of those in turn."""
    rel = element.get('relationships') or {}
    contents = (rel.get('contents') or {}).get('data') or []
    if contents:
        return [c for c in contents if isinstance(c, dict)]
    out = []
    for child in (rel.get('children') or {}).get('data') or []:
        if isinstance(child, dict):
            child_rel = child.get('relationships') or {}
            child_contents = (child_rel.get('contents') or {}).get('data') or []
            out.extend(c for c in child_contents if isinstance(c, dict))
    return out


def _grouping_shelves(grouping, cache_dir, prefix, featured=False):
    """The shelves of a grouping (a curator's, or the editorial one behind
    the New page): each editorial element of its tabs that has a title and
    something in it, as `{key, title, items}` in Apple's order, keyed
    `<prefix>-<element id>`. With `featured`, the first untitled element
    made of other elements (the banners at the top of the New page) becomes
    a shelf too, untitled and marked `featured: true`; untitled elements are
    otherwise left out, as are link rows and empty ones."""
    shelves = []
    tabs = ((grouping.get('relationships') or {}).get('tabs') or {}).get('data') or []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        children = ((tab.get('relationships') or {}).get('children') or {}).get('data') or []
        for index, element in enumerate(children):
            if not isinstance(element, dict):
                continue
            element_attrs = element.get('attributes') or {}
            shelf_title = str(element_attrs.get('title') or element_attrs.get('name') or '').strip()
            own = ((element.get('relationships') or {}).get('contents') or {}).get('data') or []
            is_featured = not shelf_title
            if is_featured and (own or not featured):
                continue
            items = []
            seen = set()
            for raw_item in _element_contents(element):
                item = _shelf_item(raw_item, cache_dir)
                if item is None or (item['kind'], item['id']) in seen:
                    continue
                seen.add((item['kind'], item['id']))
                items.append(item)
            if items:
                shelf = {'key': f"{prefix}-{element.get('id') or index}", 'title': shelf_title,
                         'items': items}
                if is_featured:
                    shelf['featured'] = True
                    featured = False  # one featured shelf
                shelves.append(shelf)
    return shelves


def editorial_shelves(raw, cache_dir):
    """`browse`'s answer from the editorial groupings behind Apple Music's
    own New page (`/v1/editorial/<storefront>/groupings` with `name=music`,
    `platform=web`): `shelves`, the grouping's editorial elements in
    Apple's order — the featured banners first as one shelf marked
    `featured` (and untitled: the page names it), then Best New Songs, New
    Releases, playlists, stations, videos… — each `{key, title, items}` with
    items as `search` has them (no groups, art as it stands; a curator among
    them a category tile)."""
    shelves = []
    for grouping in (raw or {}).get('data') or []:
        if isinstance(grouping, dict):
            shelves.extend(_grouping_shelves(grouping, cache_dir, 'new', featured=True))
    return {'shelves': shelves}


# The Radio grouping's elements the page puts apart (README.md, "The editorial groupings"): the
# hero row and the live stations, each made of children holding one item.
RADIO_HERO_KIND = '316'
RADIO_LIVE_KIND = '488'
# The least time a Radio answer is fresh for, whatever its programmes say: one whose
# programmes have all ended is not asked for again at every visit.
RADIO_MIN_AGE = 5 * 60
STAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def radio_shelves(raw, cache_dir, now=None):
    """`radio`'s answer from the editorial grouping behind Apple Music's own
    Radio page (`/v1/editorial/<storefront>/groupings` with `name=radio`,
    asked as New's is, with the stations' `events` and `radio-show`):
    `shelves` as editorial_shelves has them (_grouping_shelves, keyed
    `radio-<element id>`), but for

    - the live stations (the element of kind 488): their shelf first, keyed
      as the rest and titled as Apple titles it, marked `live`; the hero row
      (316, the featured shelf) after it, less the stations it already
      shows, and left out when that leaves nothing;
    - a station with programmes (a live one): `events`, [{title, start,
      end}] in order, the times UTC stamps (`cached`'s format): what is on
      air and next, for the page to pick from as it is shown. Its own
      subtitle stays the station's;
    - an episode of a show (a station with `radio-show`): subtitled with
      the show's name;
    - a show (an Apple curator of kind Show): a category tile, as every
      curator on a shelf is (its page is its grouping), subtitled with its
      host.

    With live programmes, `expires`: when the first live station's last
    programme known ends (at least RADIO_MIN_AGE from `now`), after which
    the answer is not fresh (answer_expired()), whatever its age."""
    groupings = [grouping for grouping in (raw or {}).get('data') or []
                 if isinstance(grouping, dict)]
    shelves = []
    for grouping in groupings:
        shelves.extend(_grouping_shelves(grouping, cache_dir, 'radio', featured=True))
    kinds, resources = _radio_elements(groupings)
    for shelf in shelves:
        for item in shelf['items']:
            _radio_item(item, resources)
    live = next((shelf for shelf in shelves if kinds.get(shelf['key']) == RADIO_LIVE_KIND),
                None)
    if live is not None:
        live['live'] = True
        shelves.remove(live)
        hero = next((shelf for shelf in shelves if shelf.get('featured')), None)
        if hero is not None:
            shown = {(item['kind'], item['id']) for item in live['items']}
            hero['items'] = [item for item in hero['items']
                             if (item['kind'], item['id']) not in shown]
            if not hero['items']:
                shelves.remove(hero)
        shelves.insert(0, live)
    answer = {'shelves': shelves}
    expires = _radio_expiry(shelves, now)
    if expires is not None:
        answer['expires'] = expires
    return answer


def _radio_elements(groupings):
    """The Radio grouping's shelves' element kinds, by the key _grouping_shelves gives
    them (`radio-<element id or place>`), and every resource its elements hold, by (type,
    id): the first copy of it with relationships (the stations' events and shows), where
    the hero's copy of a live station may have none."""
    kinds = {}
    resources = {}
    for grouping in groupings:
        tabs = ((grouping.get('relationships') or {}).get('tabs') or {}).get('data') or []
        for tab in tabs:
            if not isinstance(tab, dict):
                continue
            children = ((tab.get('relationships') or {}).get('children') or {}).get('data') or []
            for index, element in enumerate(children):
                if not isinstance(element, dict):
                    continue
                kind = (element.get('attributes') or {}).get('editorialElementKind')
                kinds[f"radio-{element.get('id') or index}"] = str(kind or '')
                for resource in _element_contents(element):
                    key = (resource.get('type'), str(resource.get('id') or ''))
                    known = resources.get(key)
                    if known is None or (resource.get('relationships')
                                         and not known.get('relationships')):
                        resources[key] = resource
    return kinds, resources


def _radio_item(item, resources):
    """Add to a Radio shelf's item what its resource says beyond the shelf item's shape: a
    station's programmes and an episode's show, a show's host."""
    if item.get('kind') == 'station':
        raw = resources.get(('stations', item['id'])) or {}
        rel = raw.get('relationships') or {}
        events = _station_events(rel.get('events'))
        if events:
            item['events'] = events
        show = next((entry for entry in (rel.get('radio-show') or {}).get('data') or []
                     if isinstance(entry, dict)), None)
        name = str(((show or {}).get('attributes') or {}).get('name') or '').strip()
        if name:
            item['subtitle'] = name
    elif item.get('kind') == 'category':
        attrs = (resources.get(('apple-curators', item['id'])) or {}).get('attributes') or {}
        host = str(attrs.get('showHostName') or '').strip()
        if attrs.get('kind') == 'Show' and host:
            item['subtitle'] = host


def _station_events(relationship):
    """A station's `events` (station-events) as [{title, start, end}] by start time, the
    times UTC stamps; one without a title or either time is left out."""
    events = []
    for event in (relationship or {}).get('data') or []:
        if not isinstance(event, dict):
            continue
        attrs = event.get('attributes') or {}
        title = str(attrs.get('title') or '').strip()
        start, end = _utc_stamp(attrs.get('startTime')), _utc_stamp(attrs.get('endTime'))
        if title and start and end and start < end:
            events.append({'title': title, 'start': start, 'end': end})
    events.sort(key=lambda event: event['start'])
    return events


def _utc_stamp(value):
    """An ISO 8601 time ('2026-10-20T14:00:00Z', with or without its fraction or offset) as
    a UTC stamp in STAMP_FORMAT, which compares as text in time order; None for anything
    else."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime(STAMP_FORMAT)


def _radio_expiry(shelves, now=None):
    """When the first live station runs out of programmes known: the earliest of the
    stations' last programmes' ends, at least RADIO_MIN_AGE after `now`; None without
    programmes."""
    ends = [item['events'][-1]['end'] for shelf in shelves for item in shelf['items']
            if item.get('events')]
    if not ends:
        return None
    now = now or datetime.now(UTC)
    floor = datetime.fromtimestamp(now.timestamp() + RADIO_MIN_AGE, UTC).strftime(STAMP_FORMAT)
    return max(min(ends), floor)


def answer_expired(answer, now=None):
    """Whether a kept answer's `expires` stamp (a Radio answer's: radio_shelves) has passed:
    it is not fresh then, whatever its age. False without one."""
    stamp = answer.get('expires') if isinstance(answer, dict) else None
    if not isinstance(stamp, str):
        return False
    now = now or datetime.now(UTC)
    return now.strftime(STAMP_FORMAT) >= stamp


# The charts the Charts page shows, by the key each comes under in the `results` of Apple's
# charts answer, in the page's order: Top Songs, Top Albums, Top Playlists, the Daily Top 100
# playlists, the City Charts playlists, Top Music Videos. A chart under any other key follows
# them, in Apple's order. The first four kinds and the videos are ranked (their order is the
# chart's); the Daily Top 100 and City Charts are a playlist a place, not a ranking.
CHART_ORDER = ('songs', 'albums', 'playlists', 'dailyGlobalTopCharts', 'cityCharts',
               'music-videos')
RANKED_CHARTS = frozenset({'songs', 'albums', 'playlists', 'music-videos'})


def charts_shelves(raw, cache_dir):
    """`charts`' answer from Apple's catalog charts (`/v1/catalog/<storefront>/charts` with
    `types` and `with`): `shelves`, one per chart with something in it, in CHART_ORDER, each
    `{key, title, items, chart}`: `chart` the key it came under in `results` (`songs`,
    `albums`, `playlists`, `music-videos`, `dailyGlobalTopCharts`, `cityCharts`…), `title`
    Apple's name for it ("Top Songs", in the account's language; '' without one, for the
    app to name by `chart`), keyed `charts-<chart>` (`-<n>` after the first of a kind), the
    items as a search's are (no groups, art as it stands), each once. A ranked chart
    (RANKED_CHARTS) is marked `ranked`, and its songs `form: 'songs'`, a list rather than
    tiles; a song carries its `album`'s name. Each entry of `results` is a list of charts
    (Apple's shape), or one chart."""
    results = (raw or {}).get('results') if isinstance(raw, dict) else None
    if not isinstance(results, dict):
        results = {}
    charts = []
    for position, (name, entries) in enumerate(results.items()):
        entries = entries if isinstance(entries, list) else [entries]
        for index, chart in enumerate(entries):
            if isinstance(chart, dict) and isinstance(chart.get('data'), list):
                rank = CHART_ORDER.index(name) if name in CHART_ORDER else len(CHART_ORDER)
                charts.append(((rank, position, index), str(name), index, chart))
    charts.sort(key=lambda entry: entry[0])
    shelves = []
    for _order, name, index, chart in charts:
        items = _chart_items(chart['data'], cache_dir)
        if not items:
            continue
        shelf = {'key': f'charts-{name}' + (f'-{index}' if index else ''),
                 'title': str(chart.get('name') or '').strip(), 'items': items, 'chart': name}
        if name in RANKED_CHARTS:
            shelf['ranked'] = True
            if name == 'songs':
                shelf['form'] = 'songs'
        shelves.append(shelf)
    return {'shelves': shelves}


def _chart_items(resources, cache_dir):
    """The Items of one chart, in its order, each once; a song with its album's name."""
    items = []
    seen = set()
    for resource in resources:
        item = _shelf_item(resource, cache_dir, curators=False)
        if item is None or (item['kind'], item['id']) in seen:
            continue
        seen.add((item['kind'], item['id']))
        if item['kind'] == 'song':
            item['album'] = str((resource.get('attributes') or {}).get('albumName') or '')
        items.append(item)
    return items


def _is_made_for_you(raw_item):
    """A personal mix (Favourites Mix, Chill Mix, New Music Mix…, playlists
    of `playlistType` personal-mix) or a station: what Made for You holds."""
    if not isinstance(raw_item, dict):
        return False
    if raw_item.get('type') == 'stations':
        return True
    attrs = raw_item.get('attributes') or {}
    return raw_item.get('type') == 'playlists' and attrs.get('playlistType') == 'personal-mix'


def made_for_you_shelves(raw_recs, cache_dir=None):
    """The Made for You page from `/v1/me/recommendations`: the
    recommendations (a group's members each on their own, as
    recommendation_shelves has them) made up entirely of the personal mixes
    and stations, each a shelf titled as Apple titles it, in Apple's order;
    the rest of the recommendations (albums for you, recently played) are
    Home's, not this page's. Items as a shelf's, without their track lists.

    Shelf = {"key": "rec-<id>", "title": "…", "items": [Item]}
    """
    return _recommendation_shelves(
        raw_recs, cache_dir, accept=lambda contents: all(map(_is_made_for_you, contents)),
        settle=True)


def _recommendation_shelves(raw_recs, cache_dir, accept, settle, art_urls=None):
    """The shelves of Apple's recommendations, in Apple's order: one per
    recommendation whose contents `accept(contents)` takes, a group's members
    each a shelf of their own, its items through _shelf_item (no curators:
    a category tile is the Search page's) with `settle`; a recommendation
    with nothing in it is left out. Titled as Apple titles it (in the
    account's language), '' when it does not: the page has the words."""
    shelves = []

    def walk(rec):
        if not isinstance(rec, dict):
            return
        attrs = rec.get('attributes') or {}
        rel = rec.get('relationships') or {}
        members = (rel.get('recommendations') or {}).get('data') or []
        if members:
            for member in members:
                walk(member)
            return
        contents = [c for c in (rel.get('contents') or {}).get('data') or [] if isinstance(c, dict)]
        if not contents or not accept(contents):
            return
        items = [_shelf_item(raw_item, cache_dir, settle=settle, curators=False,
                             art_urls=art_urls) for raw_item in contents]
        items = [item for item in items if item is not None]
        if not items:
            return
        title = _display_string(attrs.get('title'))
        key = rec.get('id') or len(shelves)
        shelf = {'key': f'rec-{key}', 'title': title, 'items': items}
        reason = recommendation_reason(attrs)
        if reason:
            shelf['subtitle'] = reason
        shelves.append(shelf)

    for rec in raw_recs or []:
        walk(rec)
    return shelves


def _display_string(value):
    """An attribute Apple gives as {stringForDisplay} (or as a bare string): its text, or ''."""
    if isinstance(value, dict):
        value = value.get('stringForDisplay')
    return value if isinstance(value, str) else ''


def recommendation_reason(attrs):
    """A recommendation's `reason` (Apple's documented `reason.stringForDisplay`, in the
    account's language: why it is offered), or '' without one, or when it only says the
    title again. Home shows it under the shelf's title (its `subtitle`)."""
    attrs = attrs if isinstance(attrs, dict) else {}
    reason = ' '.join(_display_string(attrs.get('reason')).split())
    title = ' '.join(_display_string(attrs.get('title')).split())
    return reason if reason.casefold() != title.casefold() else ''


def recently_played(raw, cache_dir=None):
    """Home's Recently Played from `/v1/me/recent/played` (api.RECENT_PLAYED_ENDPOINT, the
    pages read: a list of resources, newest first): {items: [Item]}, each once (by kind and
    id), as a shelf's items are (no track lists, their artwork as a search hit's: the sync's
    files where they exist, else a small catalog URL); a curator, an editorial item or
    anything else the app has no tile for is left out."""
    items = []
    seen = set()
    for raw_item in raw if isinstance(raw, list) else []:
        item = _shelf_item(raw_item, cache_dir, settle=True, curators=False)
        if item is None or (item['kind'], item['id']) in seen:
            continue
        seen.add((item['kind'], item['id']))
        items.append(item)
    return {'items': items}


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


def recommendation_shelves(raw_recs, cache_dir=None, art_urls=None):
    """Apple's home page as shelves: one per recommendation, in the order
    the API sends them, titled as Apple titles it ("New Releases for You",
    "Stations for You", "More from …", a genre, a decade). A group
    recommendation is its members, each a shelf of its own. Items are
    normalised without their track lists, as a shelf's are, their artwork
    the files the sync fetches (registered in `art_urls`); what the app has
    no tile for (a curator, an editorial item) is left out, as is a
    recommendation with nothing in it.

    Shelf = {"key": "rec-<id>", "title": "…", "items": [Item]}
    """
    return _recommendation_shelves(raw_recs, cache_dir, accept=lambda contents: True,
                                   settle=False, art_urls=art_urls)


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


def save_library(library_data, cache_dir, indent=2, generation=None):
    """Write library.json atomically and durably (store.atomic_write: a temporary file,
    fsync'd, renamed over the old one), so a reader sees the old file or the new one, never
    half of one, even after a crash. `indent` is json.dump's: None writes the compact form. A
    failure raises, and leaves the old file and no temporary one; store.CacheGone when the
    cache was cleared since `generation` (nothing written)."""
    lib_path = os.path.join(cache_dir, 'library.json')
    written = store.atomic_write(lib_path, lambda f: json.dump(library_data, f, indent=indent),
                                 root=cache_dir, text=True, generation=generation)
    if written is None:
        raise store.CacheGone(cache_dir)


# ---------------------------------------------------------------------------
# An artist's page
# ---------------------------------------------------------------------------

# The shelves of an artist's page, in the order music.apple.com shows them, each one of the
# artist's views (api.ARTIST_VIEWS) titled as Apple titles it. The release and top-songs are
# the page's top row, not shelves; the page puts About before similar-artists, as Apple's.
ARTIST_SHELVES = (
    'featured-albums', 'full-albums', 'music-videos', 'playlists', 'radio-shows', 'singles',
    'live-albums', 'compilation-albums', 'appears-on-albums', 'more-to-hear', 'more-to-see',
    'similar-artists',
)

# The views of the artist's own releases: their cards name the year under the title, where
# another's (Appears On) names its artist.
OWN_RELEASES = {'featured-release', 'latest-release', 'full-albums', 'singles', 'live-albums',
                'compilation-albums', 'music-videos'}

# What a view of an artist may hold beyond what a shelf can (SHELF_RESOURCE_TYPES): videos
# about the artist, which the app opens on music.apple.com, having no player for them.
LINK_RESOURCE_TYPES = {'uploaded-videos', 'music-movies'}

# The views of an artist that hold Apple curators: the radio shows the artist hosts, each
# an `apple-curators` of kind Show, a category tile opening the show's page.
CURATOR_VIEWS = {'radio-shows'}


# An artist's wide header, as music.apple.com makes it (src/backend/README.md, "An artist's
# banner"): the editorial background where Apple has one, cut with its own crop code, else
# the artist's hero portrait cut with the crop Apple recommends for a wide header; else none.
BANNER_EDITORIAL = 'centeredFullscreenBackground'
BANNER_EDITORIAL_CROP = 'sr'
BANNER_HERO_CROP = 'vf'
# The size and crop part of an artwork URL template ("{w}x{h}bb.jpg", "{w}x{h}{c}.{f}").
_TEMPLATE_TAIL = re.compile(r'\{w\}x\{h\}(?:\{c\}|[a-z]{2})?\.(?:\{f\}|[A-Za-z]+)$')


def banner_template(url, crop):
    """An artwork URL template cut with `crop` (Apple's crop code: `vf`, `sr`), its size left
    as {w}x{h} for the app to fill: "…/{w}x{h}bb.jpg" is "…/{w}x{h}vf.jpg". None for a URL
    that is not an https template."""
    if not isinstance(url, str) or not url.startswith('https://'):
        return None
    tail = _TEMPLATE_TAIL.search(url)
    if tail is None:
        return None
    return f'{url[:tail.start()]}{{w}}x{{h}}{crop}.jpg'


def artist_banner(attrs):
    """An artist's wide header from its attributes (`editorialArtwork` and `hero` extended),
    as {url, crop, width, height, color}, or None: `url` the template cut with the crop
    (banner_template), {w}x{h} left to fill; `width` and `height` the source's pixels (no
    bigger is worth asking for; an `sr` cut keeps the source's shape, a `vf` one is cut to
    whatever shape is asked); `color` Apple's background colour for it (#rrggbb) or None.

    The editorial background (BANNER_EDITORIAL) when Apple has one, else the artwork of the
    first hero entry's first content when its `recommendedCropCodes` list BANNER_HERO_CROP
    (some entries have no content), else None: the page keeps the round portrait."""
    attrs = attrs if isinstance(attrs, dict) else {}

    def banner(artwork, crop):
        if not isinstance(artwork, dict):
            return None
        url = banner_template(artwork.get('url'), crop)
        width, height = artwork.get('width'), artwork.get('height')
        if (url is None or not isinstance(width, int) or not isinstance(height, int)
                or width <= 0 or height <= 0):
            return None
        color = artwork.get('bgColor')
        return {'url': url, 'crop': crop, 'width': width, 'height': height,
                'color': format_color(color) if isinstance(color, str) else None}

    editorial = attrs.get('editorialArtwork')
    if isinstance(editorial, dict):
        found = banner(editorial.get(BANNER_EDITORIAL), BANNER_EDITORIAL_CROP)
        if found is not None:
            return found
    hero = attrs.get('hero')
    first = hero[0] if isinstance(hero, list) and hero and isinstance(hero[0], dict) else {}
    content = first.get('content')
    entry = content[0] if isinstance(content, list) and content else None
    artwork = entry.get('artwork') if isinstance(entry, dict) else None
    crops = artwork.get('recommendedCropCodes') if isinstance(artwork, dict) else None
    if isinstance(crops, list) and BANNER_HERO_CROP in crops:
        return banner(artwork, BANNER_HERO_CROP)
    return None


def artist_page(raw, cache_dir):
    """An artist's page (api.ARTIST_ENDPOINT's answer) as
    {id, artist, banner, latest, topSongs, shelves}:

    - `artist`: the artist as an Item without groups, its `summary` the biography
      (artistBio, else the editorial notes), with `origin` (the hometown), `bornOrFormed`
      (Apple's own words: "13 December 1989") and `isGroup` (formed, not born) where Apple
      has them.
    - `banner`: the artist's wide header (artist_banner), or None.
    - `latest`: {key, title, item}: the featured release where the artist has one, else the
      latest, as an Item with its `releaseDate`; or None.
    - `topSongs`: {key, title, items, more}: the top songs as song Items, each with its
      `album` (and the album's year), Apple's `index` order.
    - `shelves`: [{key, title, items, more}] in ARTIST_SHELVES's order, `more` True when
      Apple has more than it sent (artist_view() has the rest); a view with nothing the app
      can show is left out, and so is one with the same title as an earlier one.
    - `favourite`: whether the account has the artist as a favourite (`inFavorites`,
      in_favourites()), or None when Apple did not say.

    Items are shaped as a search's are (artist_view_items)."""
    data = raw.get('data') if isinstance(raw, dict) else None
    resource = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    attrs = resource.get('attributes') or {}
    artist = normalize_artist(resource, cache_dir, albums=[])
    _settle_search_art(artist, resource)
    artist['summary'] = strip_html(attrs.get('artistBio')) or artist.get('summary')
    for key in ('origin', 'bornOrFormed'):
        if isinstance(attrs.get(key), str) and attrs[key].strip():
            artist[key] = attrs[key].strip()
    if isinstance(attrs.get('isGroup'), bool):
        artist['isGroup'] = attrs['isGroup']

    views = resource.get('views') if isinstance(resource.get('views'), dict) else {}

    def view(name):
        found = views.get(name)
        if not isinstance(found, dict):
            return None
        title = (found.get('attributes') or {}).get('title')
        return {'key': name, 'title': title if isinstance(title, str) else '',
                'items': artist_view_items(name, found.get('data'), cache_dir),
                'more': bool(found.get('next'))}

    release = None
    for name in ('featured-release', 'latest-release'):
        found = view(name)
        if found is not None and found['items']:
            release = {'key': name, 'title': found['title'], 'item': found['items'][0]}
            break
    top = view('top-songs')
    shelves = []
    for name in ARTIST_SHELVES:
        shelf = view(name)
        if shelf is not None and shelf['items'] and not any(
                shelf['title'] and kept['title'] == shelf['title'] for kept in shelves):
            shelves.append(shelf)
    return {
        'id': str(resource.get('id') or ''),
        'artist': artist,
        'banner': artist_banner(attrs),
        'latest': release,
        'topSongs': top if top and top['items'] else None,
        'shelves': shelves,
        'favourite': in_favourites(raw),
    }


def artist_view_items(view, resources, cache_dir):
    """The Items of one of an artist's views (api.ARTIST_VIEWS), as a search's are, without
    groups: an album, a single or a video of the artist's own subtitled with its year, one it
    appears on with its artist, an essential album (featured-albums) with Apple's line about
    it; a song with its `album` (top-songs: the album's name) and
    year; a radio episode with its show's name (Apple's notes carry it); a radio show the
    artist hosts as a category tile opening the show's page (_artist_view_item); a video about
    the artist as a `link` Item opening its page (`url`), subtitled with its length. What the
    app cannot show is left out."""
    items = []
    for resource in resources if isinstance(resources, list) else []:
        if not isinstance(resource, dict):
            continue
        item = _artist_view_item(view, resource, cache_dir)
        if item is None:
            continue
        attrs = resource.get('attributes') or {}
        if attrs.get('artistName') and item['kind'] in ('album', 'video', 'song'):
            item['artistName'] = attrs['artistName']  # its subtitle may be a year: Go to Artist
        if view in OWN_RELEASES and item['kind'] in ('album', 'video'):
            item['subtitle'] = str(item['year']) if item.get('year') else ''
        if view == 'featured-albums':
            notes = attrs.get('editorialNotes') or {}
            line = strip_html(notes.get('short')) if isinstance(notes, dict) else None
            if line:
                item['subtitle'] = line
        if view in ('featured-release', 'latest-release') and isinstance(
                attrs.get('releaseDate'), str):
            item['releaseDate'] = attrs['releaseDate']
        if item['kind'] == 'song':
            item['album'] = attrs.get('albumName') or ''
        if item['kind'] == 'station':
            notes = attrs.get('plainEditorialNotes') or attrs.get('editorialNotes') or {}
            show = notes.get('standard') if isinstance(notes, dict) else None
            if isinstance(show, str) and show.strip() and len(show) <= 80:
                item['subtitle'] = show.strip()
        items.append(item)
    return items


def _artist_view_item(view, resource, cache_dir):
    """One entry of an artist's view as a shelf item, or None: a video about the artist as
    a link (_link_item), a radio show the artist hosts (an Apple curator of kind Show, all a
    `radio-shows` view holds) as its category tile (normalize_curator), anything else as a
    shelf's (_shelf_item, which has no tile for a curator elsewhere)."""
    if resource.get('type') in LINK_RESOURCE_TYPES:
        return _link_item(resource)
    if view in CURATOR_VIEWS and resource.get('type') == 'apple-curators':
        return normalize_curator(resource)
    return _shelf_item(resource, cache_dir, curators=False)


def _link_item(resource):
    """A video about an artist (an interview, a film) as an Item the app opens on
    music.apple.com: kind `link`, its page as `url`, its length as the subtitle, nothing to
    play. None without a name or a page."""
    attrs = resource.get('attributes') or {}
    url = attrs.get('postUrl') or attrs.get('url')
    name = attrs.get('name')
    if not (isinstance(url, str) and url.startswith('https://') and isinstance(name, str)
            and name):
        return None
    duration = attrs.get('durationInMilliseconds') or attrs.get('durationInMillis')
    artwork = (attrs.get('artwork') or {}).get('url')
    small = ART_SIZES['thumb']
    return {
        'id': str(resource.get('id') or url),
        'kind': 'link',
        'title': name,
        'subtitle': (format_duration(duration) if isinstance(duration, int) and duration > 0
                     else ''),
        'year': _extract_year(attrs, resource),
        'art': template_artwork_url(artwork, small, small) if artwork else None,
        'thumb': None,
        'url': url,
        'play': {},
        'groups': [],
    }


def related(raw, cache_dir):
    """Engine.related()'s answer from a catalog song's, music video's or album's resource read
    with its relationships (api.RELATED_ENDPOINTS): {album, artists}, `album` the first of its
    albums (None for an album, or a song on none) and `artists` its artists in Apple's order,
    each an Item without groups, shaped as a search's hits are. A relationship entry without
    its attributes (one Apple did not include) is left out."""
    data = raw.get('data') if isinstance(raw, dict) else None
    resource = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    relationships = resource.get('relationships')
    relationships = relationships if isinstance(relationships, dict) else {}

    def items(name, resource_types):
        relationship = relationships.get(name)
        entries = relationship.get('data') if isinstance(relationship, dict) else None
        found = []
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get('type') in resource_types:
                item = _shelf_item(entry, cache_dir, curators=False)
                if item is not None:
                    found.append(item)
        return found

    albums = items('albums', ('albums',)) if resource.get('type') != 'albums' else []
    return {'album': albums[0] if albums else None,
            'artists': items('artists', ('artists',))}


def playlist_suggestions(raw, cache_dir):
    """The songs Apple suggests for a library playlist (the bridge's playlistSuggestions()
    answer, `results.suggested`) as {items}: song Items as an artist's top songs are, each
    with its `album`, and `previewUrl`, the https address of Apple's 30-second preview when
    the song has one (preview_url()), in Apple's order, each id once."""
    results = raw.get('results') if isinstance(raw, dict) else None
    suggested = results.get('suggested') if isinstance(results, dict) else None
    previews = {}
    for resource in suggested if isinstance(suggested, list) else []:
        if isinstance(resource, dict) and resource.get('id'):
            url = preview_url(resource)
            if url:
                previews.setdefault(str(resource['id']), url)
    items = []
    seen = set()
    for item in artist_view_items('top-songs', suggested, cache_dir):
        if item['kind'] == 'song' and item['id'] and item['id'] not in seen:
            seen.add(item['id'])
            if item['id'] in previews:
                item['previewUrl'] = previews[item['id']]
            items.append(item)
    return {'items': items}


def preview_url(resource):
    """The https address of a catalog song's preview (its `attributes.previews[0].url`), or
    None."""
    attributes = resource.get('attributes') if isinstance(resource, dict) else None
    previews = attributes.get('previews') if isinstance(attributes, dict) else None
    first = previews[0] if isinstance(previews, list) and previews else None
    url = first.get('url') if isinstance(first, dict) else None
    return url if isinstance(url, str) and url.startswith('https://') else None


def _credit_categories(raw):
    """The `role-categories` resources of a credits answer: its `data` (the credits read), or
    the song's `relationships.credits.data` (the song read with include=credits)."""
    found = []
    for resource in api.page_data(raw):
        if resource.get('type') == 'role-categories':
            found.append(resource)
            continue
        credits = (resource.get('relationships') or {}).get('credits')
        data = credits.get('data') if isinstance(credits, dict) else None
        found += [entry for entry in data if isinstance(entry, dict)] if isinstance(
            data, list) else []
    return found


def song_credits(raw, cache_dir=None):
    """A catalog song's credits (api.SONG_CREDITS_ENDPOINT's answer, or the song read with
    include=credits) as {categories: [{kind, title, people: [{name, roles}]}]}: Apple's
    role categories in its order, `kind` Apple's (`performer`, `composer-and-lyrics`,
    `production-and-engineering`), `title` Apple's heading for it ('' without one: the app
    names it by kind), each person by name with their `roleNames` as `roles`, in Apple's
    order. Someone without a name, the same person twice in a category, and a category left
    with nobody are left out. A credit's id is not an artist's catalog id, so none is kept.
    `cache_dir` is unused: kept answers are shaped with it."""
    categories = []
    for resource in _credit_categories(raw):
        attributes = resource.get('attributes') if isinstance(resource.get('attributes'),
                                                              dict) else {}
        relationship = (resource.get('relationships') or {}).get('credit-artists')
        entries = relationship.get('data') if isinstance(relationship, dict) else None
        people, seen = [], set()
        for entry in entries if isinstance(entries, list) else []:
            person = entry.get('attributes') if isinstance(entry, dict) else None
            if not isinstance(person, dict):
                continue
            name = ' '.join(str(person.get('name') or '').split())
            roles = person.get('roleNames')
            roles = [' '.join(str(role).split()) for role in roles
                     if isinstance(role, str) and role.strip()] if isinstance(
                roles, list) else []
            if not name or (name, tuple(roles)) in seen:
                continue
            seen.add((name, tuple(roles)))
            people.append({'name': name, 'roles': roles})
        if people:
            categories.append({'kind': str(attributes.get('kind') or ''),
                               'title': ' '.join(str(attributes.get('title') or '').split()),
                               'people': people})
    return {'categories': categories}


def credits_cache_path(cache_dir, song_id):
    """Where a song's credits (song_credits) are kept for a day, by its catalog id."""
    return os.path.join(cache_dir, 'credits', f'{_safe_id(song_id)}.json')


def suggestions_cache_path(cache_dir, playlist_id):
    """Where a playlist's suggested songs (playlist_suggestions) are kept for a day."""
    return os.path.join(cache_dir, 'suggestions', f'{_safe_id(playlist_id)}.json')


def artist_cache_path(cache_dir, artist_id):
    """Where an artist's page (artist_page) is kept for a day."""
    return os.path.join(cache_dir, 'artists', f'{_safe_id(artist_id)}.json')


# ---------------------------------------------------------------------------
# An album's page under its tracks
# ---------------------------------------------------------------------------

# The shelves under an album's tracks, in the order music.apple.com shows them: its views
# (api.ALBUM_VIEWS), titled as Apple titles them, and More By, its first artist's albums,
# which the app titles ("More By <artist>").
ALBUM_SHELVES = ('other-versions', 'related-videos', 'more-by-artist', 'appears-on',
                 'you-might-also-like')
MORE_BY = 'more-by-artist'
RELEASE_DATE = re.compile(r'\d{4}(-\d{2}-\d{2})?')


def album_page(raw, cache_dir):
    """The rest of an album's page, under its tracks (Engine.album_page()'s answer, from
    {album: api.ALBUM_ENDPOINT's answer, moreBy: a page of its first artist's albums,
    api.MORE_BY_VIEW, or None}), as {id, artistId, artistName, release, shelves}:

    - `id`: the catalog album's id; `artistId`, `artistName`: its first artist's, or ''.
    - `release`: what the footer under the tracks says (album_release()): `releaseDate`,
      `copyright` and `recordLabel`, each only where Apple has it.
    - `shelves`: [{key, title, items, more}] in ALBUM_SHELVES's order, titled as Apple titles
      the views (More By has no title: the app names it), `more` True when Apple has more than
      it sent. More By leaves the album itself out; a shelf with nothing the app can show is
      left out.

    Items are shaped as a search's are (album_view_items, and artist_view_items for More
    By)."""
    raw = raw if isinstance(raw, dict) else {}
    album = raw.get('album')
    data = album.get('data') if isinstance(album, dict) else None
    resource = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    attrs = resource.get('attributes') if isinstance(resource.get('attributes'), dict) else {}
    album_id = str(resource.get('id') or '')
    relationships = resource.get('relationships')
    artists = relationships.get('artists') if isinstance(relationships, dict) else None
    artist_data = artists.get('data') if isinstance(artists, dict) else None
    first_artist = (artist_data[0] if isinstance(artist_data, list) and artist_data
                    and isinstance(artist_data[0], dict) else {})
    artist_name = attrs.get('artistName') if isinstance(attrs.get('artistName'), str) else ''

    views = resource.get('views') if isinstance(resource.get('views'), dict) else {}
    found = {}
    for name, view in views.items():
        if name in ALBUM_SHELVES and isinstance(view, dict):
            title = (view.get('attributes') or {}).get('title')
            found[name] = {'key': name, 'title': title if isinstance(title, str) else '',
                           'items': album_view_items(name, view.get('data'), cache_dir),
                           'more': bool(view.get('next'))}
    more_by = raw.get('moreBy')
    if isinstance(more_by, dict):
        items = [item for item in artist_view_items('full-albums', more_by.get('data'),
                                                    cache_dir)
                 if album_id not in (item['id'], item.get('catalogId'))]
        found[MORE_BY] = {'key': MORE_BY, 'title': '', 'items': items,
                          'more': bool(more_by.get('next'))}
    return {
        'id': album_id,
        'artistId': str(first_artist.get('id') or ''),
        'artistName': artist_name.strip(),
        'release': album_release(attrs),
        'shelves': [found[name] for name in ALBUM_SHELVES
                    if name in found and found[name]['items']],
    }


def album_release(attrs):
    """What an album's footer says, from its catalog attributes: `releaseDate` (Apple's
    'YYYY-MM-DD', or a year alone), `copyright` (the line with its ℗ or ©) and
    `recordLabel`, each only where Apple has it as text, its runs of white space one space."""
    release = {}
    attrs = attrs if isinstance(attrs, dict) else {}
    date = attrs.get('releaseDate')
    if isinstance(date, str) and RELEASE_DATE.fullmatch(date.strip()):
        release['releaseDate'] = date.strip()
    for key in ('copyright', 'recordLabel'):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            release[key] = ' '.join(value.split())
    return release


def album_view_items(view, resources, cache_dir):
    """The Items of one of an album's views (api.ALBUM_VIEWS) as a search's are, without
    groups: another version of the album subtitled with its year (it is the same artist's),
    anything else as a search has it (an album or a video with its artist, a playlist with
    its curator). What the app cannot show is left out."""
    items = []
    for resource in resources if isinstance(resources, list) else []:
        item = _shelf_item(resource, cache_dir, curators=False)
        if item is None:
            continue
        attrs = resource.get('attributes') or {}
        if attrs.get('artistName') and item['kind'] in ('album', 'video', 'song'):
            item['artistName'] = attrs['artistName']  # its subtitle may be a year: Go to Artist
        if view == 'other-versions' and item['kind'] == 'album':
            item['subtitle'] = str(item['year']) if item.get('year') else ''
        items.append(item)
    return items


def album_cache_path(cache_dir, album_id):
    """Where an album's page (album_page) is kept for a day, under the id it was asked by: a
    library album's own, or a catalog one."""
    return os.path.join(cache_dir, 'albums', f'{_safe_id(album_id)}.json')


# ---------------------------------------------------------------------------
# The other caches: artwork the pages fetch on their own, and answers kept
# ---------------------------------------------------------------------------


def prune_remote_art(cache_dir, max_bytes=REMOTE_ART_BUDGET):
    """Trim <cache_dir>/remote-art/ — the covers the pages fetch themselves
    (a search hit's, the player's, a category's picture) — to `max_bytes`,
    keeping the newest by mtime. Nothing else ever removes them. Returns
    how many went."""
    folder = os.path.join(cache_dir, 'remote-art')
    pruned = 0
    entries = []
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.startswith('.'):  # a download in progress, or a crash's leftover
                if store.is_stale_temp(path) and _remove(path):
                    pruned += 1
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            if os.path.isfile(path):
                entries.append((st.st_mtime, st.st_size, path))
    except FileNotFoundError:
        return 0
    except OSError as error:
        log.debug('remote art: %s', error)
        return pruned
    entries.sort(reverse=True)
    kept = 0
    for _mtime, size, path in entries:
        if kept + size <= max_bytes:
            kept += size
            continue
        try:
            os.remove(path)
            pruned += 1
        except OSError as error:
            log.debug('remote art: %s', error)
    return pruned


def prune_caches(cache_dir, now=None, remote_bytes=REMOTE_ART_BUDGET, lyrics_keep=LYRICS_KEEP,
                 answer_age=ANSWER_KEEP_AGE):
    """Trim the caches nothing else trims (in a thread, at startup and after a sync):
    remote-art/ to `remote_bytes` (prune_remote_art), lyrics/ to the
    `lyrics_keep` played last (by mtime: a cache hit touches the file), the kept answers
    (categories/, artists/, albums/, suggestions/, credits/, landing, New, Made for You,
    Radio, Charts) written longer than `answer_age` ago (by mtime; ANSWER_KEEP_AGE, well past their
    day, since a stale one is the answer while Apple cannot be asked), an
    items/ folder older versions kept, and the temporary files of writes a crash cut short
    (store.is_stale_temp) in the cache and its folders. Returns {what: how many went}. art/
    and thumb/ are the library's: prune_art keeps them."""
    now = time.time() if now is None else now
    gone = {'remote-art': prune_remote_art(cache_dir, remote_bytes), 'lyrics': 0,
            'answers': 0, 'items': 0, 'temps': 0}

    def files(folder):
        try:
            with os.scandir(folder) as entries:
                return [entry for entry in entries if entry.is_file(follow_symlinks=False)]
        except FileNotFoundError:
            return []
        except OSError as error:
            log.debug('prune: %s', error)
            return []

    for folder in (cache_dir, *(os.path.join(cache_dir, name) for name in
                                ('art', 'thumb', 'remote-art', 'lyrics',
                                 *ANSWER_FOLDERS))):
        for entry in files(folder):
            if store.is_stale_temp(entry.path, now) and _remove(entry.path):
                gone['temps'] += 1

    lyrics = [entry for entry in files(os.path.join(cache_dir, 'lyrics'))
              if not store.is_temp(entry.name)]
    lyrics.sort(key=_mtime, reverse=True)
    for entry in lyrics[max(0, lyrics_keep):]:
        if _remove(entry.path):
            gone['lyrics'] += 1

    answers = [entry for folder in ANSWER_FOLDERS
               for entry in files(os.path.join(cache_dir, folder))
               if not store.is_temp(entry.name)]
    answers += [entry for entry in files(cache_dir) if entry.name in KEPT_ANSWERS]
    for entry in answers:
        if now - _mtime(entry) > answer_age and _remove(entry.path):
            gone['answers'] += 1

    items = os.path.join(cache_dir, 'items')
    if os.path.isdir(items) and not os.path.islink(items):
        import shutil
        try:
            gone['items'] = sum(len(names) for _root, _dirs, names in os.walk(items))
            shutil.rmtree(items)
        except OSError as error:
            log.debug('prune: %s', error)
    if any(gone.values()):
        log.info('caches pruned: %s', ', '.join(f'{count} {what}'
                                               for what, count in gone.items() if count))
    return gone


def _mtime(entry):
    try:
        return entry.stat(follow_symlinks=False).st_mtime
    except OSError:
        return 0


def _remove(path):
    """Delete a file the cache no longer wants; one already gone is fine. True if deleted."""
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        log.debug('prune: %s', error)
        return False


def _safe_id(value):
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(value or ''))


def landing_cache_path(cache_dir):
    return os.path.join(cache_dir, 'landing.json')


def demo_search_path(cache_dir):
    """The invented catalog the demo searches (scripts/demo_library.py writes it, marked
    `demo`; Engine.search answers from it in demo mode only): {shelves: [{key, items}]}."""
    return os.path.join(cache_dir, 'demo-search.json')


def category_cache_path(cache_dir, category_id):
    return os.path.join(cache_dir, 'categories', f'{_safe_id(category_id)}.json')


def browse_cache_path(cache_dir):
    """Where the New page's shelves (editorial_shelves) are kept for a day."""
    return os.path.join(cache_dir, 'browse.json')


def made_for_you_cache_path(cache_dir):
    """Where the Made for You shelves (made_for_you_shelves) are kept for a day."""
    return os.path.join(cache_dir, 'made-for-you.json')


def recent_played_cache_path(cache_dir):
    """Where Home's Recently Played (recently_played) is kept: the last answer, shown while
    the next is asked for (a day, as the other answers)."""
    return os.path.join(cache_dir, 'recent-played.json')


def radio_cache_path(cache_dir):
    """Where the Radio page's shelves (radio_shelves) are kept: a day, or until their
    programmes run out (`expires`)."""
    return os.path.join(cache_dir, 'radio.json')


def charts_cache_path(cache_dir):
    """Where the Charts page's shelves (charts_shelves) are kept for a day."""
    return os.path.join(cache_dir, 'charts.json')


def write_answer(path, answer, cache_dir, generation=None):
    """Keep `answer` at `path` (in the cache at `cache_dir`), atomically, as
    JSON without spaces, stamped `cached` with when; not once the cache's
    generation has moved from `generation` (store.py). Best effort: a cache
    that cannot be written is only a cache."""
    answer = dict(answer)
    answer['cached'] = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        store.atomic_write(path, lambda f: json.dump(answer, f, separators=(',', ':')),
                           root=cache_dir, text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not keep %s: %s', path, error)
    return answer


def patch_answer(path, changes, cache_dir, generation=None):
    """Set `changes` (a dict) in the answer kept at `path`, keeping its `cached` stamp (the
    answer is no fresher for it): a write of the account's that the kept answer has to show
    until it is read again (an artist's page after a favourite). Nothing when there is no
    answer there, or the cache's generation has moved from `generation`; best effort, as
    write_answer."""
    try:
        with open(path, encoding='utf-8') as f:
            answer = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(answer, dict):
        return
    answer.update(changes)
    try:
        store.atomic_write(path, lambda f: json.dump(answer, f, separators=(',', ':')),
                           root=cache_dir, text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not update %s: %s', path, error)


def read_answer(path, max_age_seconds):
    """The answer kept at `path`, or None when there is none, it cannot be
    read, or it was stamped longer than `max_age_seconds` ago."""
    try:
        with open(path, encoding='utf-8') as f:
            answer = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.debug('kept answer %s: %s', path, error)
        return None
    stamp = answer.get('cached') if isinstance(answer, dict) else None
    try:
        when = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
    except (TypeError, ValueError):
        log.debug('kept answer %s: no stamp', path)
        return None
    if (datetime.now(UTC) - when).total_seconds() > max_age_seconds:
        return None
    return answer
