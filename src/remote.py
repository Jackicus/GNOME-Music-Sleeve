# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Remote artwork and the engine's shelves: where the artwork the library does not hold is
kept, and fetching it. No GTK here: the widgets decode what this puts on disk
(widgets/artwork.py).

A sync fetches only thumbnails; the covers (an Item's `art`, 640 px) are fetched here on
demand, by what shows one: `await fetch_cover(item)` downloads it into <cache>/art/ from the
`artUrl` the sync kept in the Item, and answers True when this call brought the file (the
widget then looks again). Artwork the library does not name (the item playing, a search hit)
comes through `await fetch_remote(url, size)`: the URL re-sized to `size` px square, fetched
into <cache>/remote-art/ (named by the sized URL's hash; the sync trims that directory to a
budget) and answered as its path.

The engine's search, suggest, category, browse, radio and made-for-you answers name a catalog
URL as an item's `art` when the sync has not fetched its cover (and no `thumb`):
`remote_item(data)` gives such a dict the paths fetch_remote() would use (`thumb` at
THUMB_SIZE, `art` at COVER_SIZE, with `thumbUrl` and `artUrl` to fetch them by), so a tile
shows the thumbnail once `await fetch_thumb(item)` has brought it and a detail page's
fetch_cover() the cover. remote_items() wraps such dicts as Items, remote_shelves() makes the
engine's shelf dicts into ShelfModel objects of them, titled in the app's words (shelf_title()),
and fetch_shelf_art() (fetch_items_art() for a list of Items) brings their thumbnails a few at
a time, each Item notifying `thumb` as its file arrives: the tiles
showing it follow their Item (widgets/tile.py).

Downloads run in a pool of their own (FETCH_WORKERS threads), not in asyncio's default
executor, where the artwork is decoded: a page's thumbnails downloading on a slow connection
never hold up the covers on screen. Whether a file is on disk already is asked there too, off
the main loop (on_disk()). Only https URLs are fetched, and normalize.cache_artwork writes only
inside the cache. Concurrent requests for one file share its download. Nothing here needs the
engine.
"""

import asyncio
import concurrent.futures
import logging
import os
import re
from gettext import gettext as _

from .backend import config, normalize, store
from .library import N_, Item, ShelfModel

log = logging.getLogger(__name__)

# Threads downloading artwork at once, for the whole app.
FETCH_WORKERS = 6
# Thumbnails one page of shelves asks for at once: the rest wait their turn outside the pool,
# so another page's (or the player's) downloads are not queued behind all of them.
ART_CONCURRENCY = 6

# The size at the end of an Apple artwork URL ("…/256x256bb.jpg", "…/600x600bb-60.jpg"), to
# re-size one; a template ("{w}x{h}") is filled by the backend first.
ART_SIZE_RE = re.compile(r'/(\d+)x(\d+)([a-z]{0,3}(?:-\d+)?)(\.[A-Za-z0-9]+)$')

# The headings of a search's shelves, by the key the engine gives each (normalize.search_results).
SEARCH_TITLES = {
    # Translators: the first shelf of a search's results: Apple's best few hits of any kind.
    'top': N_('Top Results'),
    'artists': N_('Artists'),
    'albums': N_('Albums'),
    'songs': N_('Songs'),
    'playlists': N_('Playlists'),
    'music-videos': N_('Music Videos'),
    'stations': N_('Stations'),
    'radio-shows': N_('Radio Shows'),
    'curators': N_('Curators'),
}


def is_url(value):
    """Whether `value` is an https URL: the only artwork this app fetches."""
    return isinstance(value, str) and value.startswith('https://')


def sized_url(url, size):
    """`url` naming a `size`×`size` px image: Apple's templates and sized URLs both take it;
    any other URL is left as it is."""
    if not url:
        return None
    url = normalize.template_artwork_url(str(url), size, size)
    return ART_SIZE_RE.sub(lambda match: f'/{size}x{size}{match.group(3)}{match.group(4)}', url)


def remote_art_path(url, size=config.COVER_SIZE):
    """Where fetch_remote keeps the image at `url` re-sized to `size`: under <cache>/remote-art/,
    named by the sized URL's hash. None without a URL."""
    url = sized_url(url, size)
    if not url:
        return None
    return os.path.join(str(config.cache_dir()), 'remote-art', normalize.artwork_filename(url))


def remote_item(data):
    """An Item dict from the engine's search, category, browse, radio or made-for-you
    answers with its artwork where this app fetches it: when `art` is a catalog URL (the sync
    has not fetched the cover), a copy naming fetch_remote()'s files instead (`thumb` at
    THUMB_SIZE unless the dict names one, `art` at COVER_SIZE) and the URLs to fetch them by
    (`thumbUrl`, `artUrl`, for fetch_thumb() and fetch_cover()). A dict whose artwork is a
    file, or that has none, is returned as it is."""
    url = data.get('art') if isinstance(data, dict) else None
    if not is_url(url):
        return data
    item = dict(data)
    item['thumbUrl'] = sized_url(url, config.THUMB_SIZE)
    item['artUrl'] = sized_url(url, config.COVER_SIZE)
    if not item.get('thumb'):
        item['thumb'] = remote_art_path(url, config.THUMB_SIZE)
    item['art'] = remote_art_path(url, config.COVER_SIZE)
    return item


def needs_thumb(item):
    """Whether an Item (remote_item's) names a thumbnail it can fetch: a path and an https URL.
    Whether the file is on disk already is fetch_thumb()'s to find out, off the main loop."""
    raw = item.raw if isinstance(item.raw, dict) else {}
    return bool(item.thumb and is_url(raw.get('thumbUrl')))


def on_disk(path):
    """Whether an artwork file is on disk, and not empty. It asks the file system: call it
    in a thread."""
    try:
        return os.path.getsize(path) > 0
    except (OSError, TypeError, ValueError):
        return False


# -- fetching ------------------------------------------------------------------------------

_executor = None
_fetches = {}  # path -> the asyncio.Task fetching it


def _fetch_executor():
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=FETCH_WORKERS, thread_name_prefix='art-fetch')
    return _executor


async def fetch_cover(item):
    """The Item's cover (`art`) on disk: True when this call brought it (from the Item's
    `artUrl`), False when it was there already, the Item has no cover URL, or the fetch
    failed (logged; the page keeps the thumbnail). Concurrent calls for one cover share the
    download, and each answers True."""
    raw = item.raw if isinstance(item.raw, dict) else {}
    return await _fetch(item.art, raw.get('artUrl')) is True


async def fetch_thumb(item):
    """The thumbnail of an Item from a search or browse answer (remote_item()) on disk: True
    when this call brought it (from the Item's `thumbUrl`), False when it was there already,
    the Item names none, or the fetch failed."""
    if not needs_thumb(item):
        return False
    return await _fetch(item.thumb, item.raw.get('thumbUrl')) is True


async def fetch_remote(url, size=config.COVER_SIZE):
    """The image at `url` (an Apple artwork URL of any size), re-sized to `size` px square and
    on disk under <cache>/remote-art/: its path, once it is there (fetched when it was not), or
    None without an https URL or when the fetch failed (logged). Concurrent calls for one image
    share the download. The player bar asks at the cover size, so the Now Playing sheet and
    MPRIS find the same file."""
    path = remote_art_path(url, size)
    return path if await _fetch(path, sized_url(url, size)) is not None else None


# An artist's banner (normalize.artist_banner): a `vf` cut is asked at BANNER_ASPECT (width
# to height; Apple cuts it to any shape asked), an `sr` one at its source's shape. Its width
# is asked in steps of BANNER_STEP device pixels, from the first up to the source's width, so
# a window resized a little asks for nothing new and a wide one never for more than Apple has.
BANNER_ASPECT = 3.0
BANNER_STEP = 480


def banner_aspect(banner):
    """The width to height of the image fetched for a banner dict."""
    if banner.get('crop') != 'vf':
        width, height = banner.get('width') or 0, banner.get('height') or 0
        if width > 0 and height > 0:
            return width / height
    return BANNER_ASPECT


def banner_size(banner, pixels):
    """(width, height) in pixels to ask a banner at for a header `pixels` device pixels wide:
    the width rounded up to a BANNER_STEP, no wider than the source (nor narrower than a
    step), the height by banner_aspect()."""
    steps = max(1, -(-int(pixels) // BANNER_STEP))
    source = banner.get('width') or 0
    width = steps * BANNER_STEP
    if source > 0:
        width = min(width, source)
    return width, max(1, round(width / banner_aspect(banner)))


def banner_url(banner, pixels):
    """The banner's URL for a header `pixels` device pixels wide (banner_size), or None
    without an https template."""
    url = banner.get('url') if isinstance(banner, dict) else None
    if not is_url(url):
        return None
    width, height = banner_size(banner, pixels)
    return url.replace('{w}', str(width)).replace('{h}', str(height))


async def fetch_banner(banner, pixels):
    """The banner for a header `pixels` device pixels wide on disk under <cache>/remote-art/
    (named by its sized URL's hash): its path once it is there, or None (no URL, or the fetch
    failed: logged). Concurrent calls for one size share the download."""
    url = banner_url(banner, pixels)
    if url is None:
        return None
    path = os.path.join(str(config.cache_dir()), 'remote-art', normalize.artwork_filename(url))
    return path if await _fetch(path, url) is not None else None


async def _fetch(path, url):
    """Bring `url` to `path` (inside the cache): True when this call's download (or the one
    it shared) brought it, False when it was on disk, None when it could not (no path, not an
    https URL, or a failed download)."""
    if not path or not is_url(url):
        return None
    task = _fetches.get(path)
    if task is None:
        generation = store.cache_generation()  # a wipe from here on keeps this file out
        task = asyncio.get_running_loop().create_task(_download(path, url, generation))
        _fetches[path] = task

        def forget(done):
            if _fetches.get(path) is done:
                del _fetches[path]

        task.add_done_callback(forget)
    return await asyncio.shield(task)


async def _download(path, url, generation):
    def download():
        if on_disk(path):
            return False
        cached = normalize.cache_artwork(url, str(config.cache_dir()), dest_path=path,
                                         generation=generation)
        return True if cached is not None else None

    try:
        fetched = await asyncio.get_running_loop().run_in_executor(_fetch_executor(), download)
    except Exception:
        log.exception('Cannot fetch the artwork %s', path)
        return None
    if fetched:
        log.debug('fetched the artwork %s', path)
    return fetched


# -- the engine's shelves ------------------------------------------------------------------

def shelf_title(data):
    """A shelf's heading in the app's language: the name of its kind for a search's shelf
    (SEARCH_TITLES, by key: the backend leaves them untitled), 'Featured' for the New page's
    banners, Apple's own title for the rest (it comes in the account's language: Radio's
    `radio-shows` keeps it), and 'Made for You' for a recommendation that has none."""
    if data.get('featured'):
        # Translators: the shelf of banners at the top of the New page.
        return _('Featured')
    own = str(data.get('title') or '')
    title = SEARCH_TITLES.get(str(data.get('key') or ''))
    if title is not None and not own:
        return _(title)
    return own or _('Made for You')


def remote_items(dicts):
    """Items for the engine's item dicts, their artwork under remote-art (remote_item()); a
    dict without an id and a kind is left out. Those the backend leaves without a subtitle
    (it writes no words) get the app's: an artist 'Artist', which a card shows under the name
    as an album's shows its artist; a search's curator (`curatorKind`) 'Radio Show' or
    'Curator', a show without its host's name."""
    items = [Item(remote_item(entry)) for entry in dicts or []
             if isinstance(entry, dict) and entry.get('id') and entry.get('kind')]
    words = None
    for item in items:
        raw = item.raw if isinstance(item.raw, dict) else {}
        if item.subtitle or not (item.kind == 'artist' or raw.get('curatorKind')):
            continue
        if words is None:
            words = {
                # Translators: the second line of an artist's card among a search's
                # results, where an album's card names its artist.
                'artist': _('Artist'),
                # Translators: the second line of a radio show's card among a search's
                # results, when Apple names no host.
                'show': _('Radio Show'),
                # Translators: the second line of a curator's card among a search's results
                # (an editor of playlists: Apple's own, or another's).
                'curator': _('Curator'),
            }
        if item.kind == 'artist':
            item.subtitle = words['artist']
        else:
            item.subtitle = words['show' if raw.get('curatorKind') == 'show' else 'curator']
    return items


def remote_shelves(dicts):
    """ShelfModel objects for the engine's shelf dicts ({key, title, items}), titled by
    shelf_title(), the items as remote_items() makes them; a shelf with nothing in it is
    left out. A search's shelf carries the offset of Apple's next page of it as `next` (None
    when Apple has no more), and `more` while there is one, so it offers See All."""
    shelves = []
    for data in dicts or []:
        if not isinstance(data, dict):
            continue
        items = remote_items(data.get('items'))
        if items:
            shelf = ShelfModel(str(data.get('key') or ''), shelf_title(data), items)
            following = data.get('next')
            shelf.next = following if isinstance(following, int) and following > 0 else None
            if shelf.next is not None:
                shelf.more = True
            shelves.append(shelf)
    return shelves


async def fetch_items_art(items):
    """Fetch the thumbnails of the Items (remote_item()'s) that are not on disk,
    ART_CONCURRENCY at a time; each Item whose file arrives notifies `thumb` (its path
    unchanged), and the widgets showing it look again."""
    gate = asyncio.Semaphore(ART_CONCURRENCY)

    async def fetch(item):
        async with gate:
            if await fetch_thumb(item):
                item.notify('thumb')

    await asyncio.gather(*(fetch(item) for item in list(items) if needs_thumb(item)))


async def fetch_shelf_art(shelves):
    """Fetch the thumbnails of the shelves' items that are not on disk, ART_CONCURRENCY at a
    time; each Item whose file arrives notifies `thumb` (its path unchanged), and the tiles
    showing it look again. A store splicing the Item over itself would not do: GTK does not
    rebind a row for that."""
    await fetch_items_art([item for shelf in shelves for item in list(shelf.items)])
