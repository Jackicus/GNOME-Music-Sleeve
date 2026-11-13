# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The artwork cache: what each artwork's files are called, at what size,
and fetching what is missing.

A cover in <cache>/art/ and its thumbnail in <cache>/thumb/, each named after its URL's
hash; the sizes they are kept at (ART_SIZES, recorded in a marker beside the covers);
thumbnails scaled from their covers (scale_image, which the app installs) or fetched; the
`art_urls` registry the normalisers fill and download_art() fetches in threads; and
place_in_remote_art() for an item fetched on demand. Pruning is cache_files.py's. The
standard library only; the thread pool and urllib are imported where they are used.
"""

import hashlib
import json
import logging
import os

from . import config, store

log = logging.getLogger(__name__)


# What download_art raises when it gives up (store.CacheGone, a wiped cache, is one too).
Cancelled = store.Cancelled


# Scaling a cached cover down to its thumbnail, without fetching it again,
# takes an image library, and nothing in the backend imports gi. The app
# installs one here: a callable scale_image(src_path, dest_path, width, height)
# that writes a JPEG at most width x height, the image's shape kept, to
# dest_path and raises on failure (GdkPixbuf, in the app). Without one,
# thumbnails are downloaded instead.
scale_image = None


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
# thumbnail of <cache>/art/<x>.jpg (a video's is <x>-wide.jpg: thumb_box() below). These are
# the defaults, from config; a sync sets them
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


# A music video's artwork is 16:9 (wide_art(): a video's, a link's to one), and its tile
# draws it by its shorter edge (widgets/tile.py: a frame 160 px high, 320 device pixels at a
# scale of 2). Its thumbnail is asked for in a box VIDEO_ASPECT times the thumbnail size wide
# and the size high, which Apple's `bb` and the scaler fill in the image's own shape (569 x 320
# for a 16:9 video, where the square box gave 320 x 180, drawn 1.8 times enlarged at 2x), and
# it is kept under a name of its own (WIDE_SUFFIX before the extension), so a cache whose
# videos were thumbnailed in the square box fetches them again rather than keeping them.
VIDEO_ASPECT = 16 / 9
WIDE_SUFFIX = '-wide'


def thumb_box(size, wide=False):
    """(width, height): the box a thumbnail of `size` is asked for and scaled into, the
    square, or for wide artwork (a video's) VIDEO_ASPECT times as wide."""
    return (round(size * VIDEO_ASPECT), size) if wide else (size, size)


def wide_art(item):
    """Whether an Item dict's artwork is a video's 16:9 frame: a music video's, or a link's
    to a video about an artist (_link_item's, marked `video`)."""
    if not isinstance(item, dict):
        return False
    kind = item.get('kind')
    return kind == 'video' or (kind == 'link' and item.get('video') is True)


def is_wide_thumb(path):
    """Whether a thumbnail's file is a wide one (thumb_cache_path(wide=True)'s)."""
    return os.path.splitext(os.path.basename(path or ''))[0].endswith(WIDE_SUFFIX)


def thumb_name(cover_name, wide=False):
    """A thumbnail's file name: its cover's, with WIDE_SUFFIX for a wide one (a video's, in
    its thumb_box())."""
    if not wide:
        return cover_name
    stem, extension = os.path.splitext(cover_name)
    return f'{stem}{WIDE_SUFFIX}{extension}'


def thumb_cache_path(url, cache_dir, wide=False):
    """The thumbnail's path for a full-size artwork URL (thumb_name())."""
    return os.path.join(cache_dir, 'thumb', thumb_name(artwork_filename(url), wide))


def cover_of_thumb(thumb_path, cache_dir):
    """The cover a thumbnail is scaled from: the file of the same name in <cache>/art/,
    without a wide thumbnail's WIDE_SUFFIX."""
    stem, extension = os.path.splitext(os.path.basename(thumb_path))
    if stem.endswith(WIDE_SUFFIX):
        stem = stem[:-len(WIDE_SUFFIX)]
    return os.path.join(cache_dir, 'art', stem + extension)


def make_thumbnail(src_path, dest_path, cache_dir, size=None, generation=None, wide=None):
    """Scale the cover at `src_path` down into its thumb_box() at `dest_path` (in the
    cache at `cache_dir`), atomically: wide when `wide` says so, or (None) when the
    destination's name does. False without a scale_image installed, when the source is not
    an image, or when `generation` moved (store.py)."""
    if scale_image is None:
        return False
    size = size or ART_SIZES['thumb']
    width, height = thumb_box(size, is_wide_thumb(dest_path) if wide is None else wide)
    try:
        return store.atomic_create(
            dest_path, lambda temp: scale_image(src_path, temp, width, height),
            root=cache_dir, generation=generation) is not None
    except Exception as error:  # the scaler's own errors (GLib.Error) as well as OSError
        log.debug('could not scale %s: %s', src_path, error)
        return False


def cache_thumbnail(url, cache_dir, dest_path, generation=None):
    """The thumbnail at `dest_path`: scaled from the cached full-size cover
    (cover_of_thumb()) when that is on disk, fetched at the thumbnail size from `url`
    otherwise."""
    if not url or not dest_path:
        return None
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return dest_path
    full = cover_of_thumb(dest_path, cache_dir)
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
    folders = {os.path.dirname(os.path.abspath(p)) for p in todo}
    for folder in sorted(f for f in folders if store.inside(f, cache_dir, or_root=True)):
        if not store.make_dirs(folder, root=cache_dir, generation=generation):
            raise store.CacheGone(cache_dir)
    # The covers first, the thumbnails after: a thumbnail in <cache>/thumb/ is scaled from
    # its cover when that is on disk, and fetched only when it is not. Anything else (a
    # cover, or what item() placed in remote-art/, rows' thumbnails among it) is fetched to
    # the very path it was given, which is the one the item reads.
    covers = {p: u for p, u in todo.items() if not _is_thumb_path(p, cache_dir)}
    thumbs = {p: u for p, u in todo.items() if _is_thumb_path(p, cache_dir)}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for batch, fetch in (
                (covers, lambda p, u: cache_artwork(u, cache_dir, dest_path=p,
                                                    generation=generation)),
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
                except OSError as error:  # the disk (the fetch's own errors were caught)
                    log.warning('artwork: could not fetch %s: %s', futures[fut], error)
                except Exception:  # one artwork's bug is not the end of the others
                    log.exception('artwork: fetching %s failed', futures[fut])
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
