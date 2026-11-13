# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The music.apple.com addresses of items: the page Open in Browser opens, the link Copy
Link copies and the links a drag offers other applications (actions.py asks the engine for
those only it can find).
"""

from urllib.parse import urlsplit

from . import related
from .backend.api import is_library_id
from .item_targets import _synthetic
from .library import Item, Track

WEB = 'https://music.apple.com'
# The hosts of Apple Music's pages: the only addresses the app opens or copies.
APPLE_HOSTS = frozenset({'music.apple.com', 'geo.music.apple.com'})
# The page of a catalog item without a URL: music.apple.com/<storefront>/<path>/<id>, which
# Apple redirects to the canonical address with the item's name in it.
WEB_PATHS = {'album': 'album', 'playlist': 'playlist', 'song': 'song', 'station': 'station',
             'artist': 'artist', 'video': 'music-video'}
# The web player's own routes for library items (as its sidebar links and its router name
# them): a library playlist's and a library album's pages, which open for the owner only.
LIBRARY_ROUTES = {'playlist': 'library/playlist', 'album': 'library/albums'}


def is_apple_music_url(url):
    """Whether url is a page of music.apple.com over https: the only addresses the app
    opens or copies. An Item's `url` comes from Apple's answers, but is checked all the
    same; anything else falls back to the address made from the item's id."""
    try:
        parts = urlsplit(url or '')
    except ValueError:
        return False
    return parts.scheme == 'https' and (parts.hostname or '').lower() in APPLE_HOSTS


def is_shareable(url):
    """Whether an address opens for anyone: a music.apple.com page that is not one of the
    web player's library routes (those open only for the account signed in)."""
    return is_apple_music_url(url) and not url.startswith(f'{WEB}/library/')


def web_url(obj, storefront=None):
    """The music.apple.com page of obj, or None: the Item's own URL (when it is one of
    Apple's, is_apple_music_url); the web player's page of a library playlist or album; a
    catalog item's page by its id; a track's song page by its catalog id."""
    storefront = storefront or 'us'
    if isinstance(obj, Track):
        song_id = obj.catalog_id or (obj.id if not is_library_id(obj.id) else None)
        path = WEB_PATHS[obj.kind or 'song']
        return f'{WEB}/{storefront}/{path}/{song_id}' if song_id else None
    if not isinstance(obj, Item) or not obj.id:
        return None
    if obj.url and is_apple_music_url(obj.url):
        return obj.url
    if is_library_id(obj.id):
        route = LIBRARY_ROUTES.get(obj.kind)
        if route and not _synthetic(obj.id):
            return f'{WEB}/{route}/{obj.id}'
        if obj.kind == 'song' and obj.catalog_id:
            return f'{WEB}/{storefront}/song/{obj.catalog_id}'
        return None
    path = WEB_PATHS.get(obj.kind)
    return f'{WEB}/{storefront}/{path}/{obj.id}' if path else None


def share_url(obj, storefront=None):
    """The address Copy Link copies, or None: obj's page when anyone can open it
    (is_shareable), never a library route."""
    url = web_url(obj, storefront)
    return url if is_shareable(url) else None


def drag_link(obj, storefront=None):
    """The address a drag of obj offers other applications, or None: share_url(), or for a
    library album without one its catalog page by the album's catalog id (Copy Link asks the
    engine instead, which a drag, answered at once, cannot wait for). A library-only item (an
    upload, a playlist of the user's, a folder) has none."""
    url = share_url(obj, storefront)
    if url is None and needs_catalog_url(obj) and str(obj.catalog_id or '').isdigit():
        url = f'{WEB}/{storefront or "us"}/{WEB_PATHS["album"]}/{obj.catalog_id}'
    return url


def drag_links(objects, storefront=None):
    """The addresses a drag of `objects` (Tracks and Items, in order) offers other
    applications: each one's drag_link(), in order, once each, those without one left out."""
    return list(dict.fromkeys(url for url in (drag_link(obj, storefront) for obj in objects)
                              if url))


def needs_catalog_url(obj):
    """Whether obj's link is better asked of the engine: a library album (real, not made up)
    has a catalog page others can open, where its library route opens only for the owner."""
    return (isinstance(obj, Item) and obj.kind == 'album' and not obj.url
            and is_library_id(obj.id) and not _synthetic(obj.id))


def needs_catalog_artist(obj):
    """Whether obj's page is found through the engine: an artist the library made up from
    its songs' names (no catalog id, no URL), whose catalog artist the engine finds through
    those songs (Engine.catalog_artist, related.artist_song_ids)."""
    return (isinstance(obj, Item) and obj.kind == 'artist' and not obj.url
            and related.artist_catalog_id(obj) is None)
