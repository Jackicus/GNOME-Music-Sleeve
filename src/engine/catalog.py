# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's catalog as the pages read it: a search and its suggestions, a full Item, an
artist's, album's or playlist's page and their views whole, a playlist's suggested songs, a
song's credits, and what a library item stands for in the catalog."""

import asyncio
import logging

from .. import cache
from ..backend import api, normalize, store
from ..backend.api import is_library_id
from ..backend.errors import EngineError
from .reads import READ_TIMEOUT, SEARCH_TIMEOUT, _raise_api_errors, _Unkept

log = logging.getLogger(__name__)

RELATIONSHIP_PAGES = 50   # pages of an item's relationship followed past the first, at most
CATALOG_ARTIST_TRIES = 3  # a library artist's songs asked for their artists, at most
ALBUM_BATCH = 25          # an artist's albums asked of the page at once
SEARCH_LIMIT = 20         # hits per kind
SUGGEST_LIMIT = 10        # completions and top hits while typing
SUGGESTIONS_LIMIT = 16    # a playlist's first suggested songs: the most shown (12), 4 spare

# The relationship of an item() answer that holds its groups' contents, which Apple pages
# (25 albums, 100 tracks), giving a `next` link for the rest.
GROUP_RELATIONSHIPS = {'album': 'tracks', 'playlist': 'tracks', 'artist': 'albums'}


def _shape_item(raw, cache_dir, generation):
    """In a thread: the API's resource as an Item with groups, its artwork fetched into
    <cache>/remote-art/ (normalize.place_in_remote_art; for the cache of `generation`:
    store.py)."""
    art_urls = {}
    item = normalize.normalize_item(raw, cache_dir, include_groups=True, art_urls=art_urls)
    return _fetch_item_art(item, art_urls, cache_dir, generation)


def _fetch_item_art(item, art_urls, cache_dir, generation):
    placed = normalize.place_in_remote_art(item, art_urls, cache_dir)
    normalize.download_item_art(item, cache_dir, placed, generation=generation)
    return item


def _shape_artist(raw, item_id, stubs, answers, cache_dir, generation):
    """In a thread: an artist resource plus its albums' answers (apiAll's list, a failed one
    None in its place, the stub standing in) as an artist Item, one group per album."""
    artist = {'id': item_id, 'type': raw.get('type', 'artists'),
              'attributes': raw.get('attributes') or {}}
    albums = []
    for position, stub in enumerate(stubs):
        answer = answers[position] if position < len(answers) else None
        data = answer.get('data') if isinstance(answer, dict) else None
        albums.append(data[0] if isinstance(data, list) and data else stub)
    art_urls = {}
    item = normalize.normalize_artist(artist, cache_dir, albums=albums, art_urls=art_urls)
    return _fetch_item_art(item, art_urls, cache_dir, generation)


# The demo's Top Results: the first hit of each of its first kinds, at most this many.
DEMO_TOP = 4


def demo_search(catalog, term, limit, kind=None, offset=0):
    """A search of the demo's invented catalog (scripts/demo_library.py's demo-search.json,
    {shelves: [{key, items}]}) shaped as Engine.search() answers Apple's: the items whose
    title or subtitle holds every word of `term` (case aside), `limit` of each kind, each
    shelf's `next` the offset of the rest (None: none). Top Results are the first hit of
    each kind, DEMO_TOP at most. With `kind`, that kind alone from `offset`."""
    words = term.casefold().split()

    def matches(item):
        text = f"{item.get('title') or ''} {item.get('subtitle') or ''}".casefold()
        return all(word in text for word in words)

    shelves = []
    for shelf in catalog.get('shelves') or []:
        if not isinstance(shelf, dict) or (kind is not None and shelf.get('key') != kind):
            continue
        found = [item for item in shelf.get('items') or []
                 if isinstance(item, dict) and matches(item)]
        start = offset if kind is not None else 0
        page = found[start:start + limit]
        if page:
            following = start + limit if start + limit < len(found) else None
            shelves.append({'key': shelf.get('key'), 'title': '', 'items': page,
                            'next': following})
    if kind is None and shelves:
        top = [shelf['items'][0] for shelf in shelves[:DEMO_TOP]]
        shelves.insert(0, {'key': 'top', 'title': '', 'items': top, 'next': None})
    return {'shelves': shelves}


class CatalogCommands:
    """The Engine's catalog reads: a mixin of Engine (core.py), whose
    _require_signed_in(), _api(), api_all(), _kept_answer(), _current_storefront(),
    _catalog_artists, _related, _favourite_artists, cache_dir and demo they use."""

    async def item(self, kind, item_id):
        """One full Item of `kind` with its `groups` (an album's discs, a playlist's list, an
        artist's albums), all of them however Apple pages them, its artwork fetched. Needs a
        signed-in engine: EngineError('not-signed-in') otherwise; a file that cannot be
        written is EngineError('api')."""
        generation = store.cache_generation()
        client = await self._require_signed_in('load items')
        storefront = await self._current_storefront()
        answer = await self._api(client, api.item_endpoint(kind, item_id, storefront),
                                 timeout=READ_TIMEOUT)
        data = answer.get('data')
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise EngineError('api', f'item not found: {kind} {item_id}')
        raw = await self._whole_relationship(client, data[0], GROUP_RELATIONSHIPS.get(kind))
        cache_dir = str(self.cache_dir)
        try:
            if kind == 'artist':
                stubs, answers = await self._artist_albums(raw, item_id, storefront)
                return await asyncio.to_thread(_shape_artist, raw, str(item_id), stubs,
                                               answers, cache_dir, generation)
            return await asyncio.to_thread(_shape_item, raw, cache_dir, generation)
        except OSError as e:
            raise EngineError('api', f'{kind} {item_id}: {e.strerror or e}') from e

    async def _whole_relationship(self, client, raw, name):
        """`raw` with its relationship `name` whole: Apple's `next` links followed (at most
        RELATIONSHIP_PAGES of them) and their resources added to its `data`."""
        relationships = raw.get('relationships')
        relationship = relationships.get(name) if isinstance(relationships, dict) else None
        if not isinstance(relationship, dict) or not relationship.get('next'):
            return raw
        data = api.page_data(relationship)
        link = relationship.get('next')
        for _ in range(RELATIONSHIP_PAGES):
            if not isinstance(link, str) or not link.startswith('/v1/'):
                break
            answer = await self._api(client, link, timeout=READ_TIMEOUT)
            page = api.page_data(answer)
            if not page:
                break
            data += page
            link = answer.get('next')
        else:
            log.warning('%s of %s: more than %d pages, the rest left out', name, raw.get('id'),
                        RELATIONSHIP_PAGES)
        whole = {key: value for key, value in relationship.items() if key != 'next'}
        return dict(raw, relationships=dict(relationships, **{name: dict(whole, data=data)}))

    async def _artist_albums(self, raw, item_id, storefront):
        """An artist's album stubs and each album's answer with its tracks, in order (None
        where one failed): ALBUM_BATCH at a time in the page, not one round trip per album."""
        relationships = raw.get('relationships') or {}
        stubs = api.page_data(relationships.get('albums'))
        endpoints = [api.album_endpoint(stub.get('id'), storefront) for stub in stubs]
        answers = []
        for start in range(0, len(endpoints), ALBUM_BATCH):
            batch = endpoints[start:start + ALBUM_BATCH]
            try:
                answers += await self.api_all(batch, timeout=60)
            except EngineError as e:
                if e.code == 'engine-down':
                    raise
                log.warning('the albums of artist %s: %s', item_id, e)
                answers += [None] * len(batch)
        return stubs, answers

    # -- search and browsing -------------------------------------------------------------
    # The Search page's search, suggestions, landing and categories, the New page (browse)
    # and Made for You. Every one needs a signed-in engine, but a kept answer (the landing, a
    # category, browse and made-for-you are kept for normalize.ANSWER_MAX_AGE) is answered
    # without one. The shaping (backend.normalize) runs in a thread: it stats the artwork cache.

    async def search(self, term, limit=SEARCH_LIMIT, kind=None, offset=0):
        """A search of the catalog (the Search page's Apple Music mode): {shelves: [{key,
        title, items: [Item without groups], next}]}, the shelves in Apple's order (Top
        Results first, then every kind of api.SEARCH_KIND_TYPES that answered), `next` the
        offset at which Apple has more of the kind (None: no more). `limit` is per kind.
        With `kind` (one of those keys: the Search page's filter, a shelf's See All), that
        kind alone from `offset`, without Top Results: its one shelf, or none (a page may
        hold nothing but a `next`). A hit's `art` is its cached cover or a thumbnail-sized
        catalog URL (remote.remote_item gives it a place under <cache>/remote-art/);
        `thumb` is on disk or None. The demo searches the invented catalog the demo library
        wrote (demo_search())."""
        term = ' '.join(str(term or '').split())
        if not term:
            raise EngineError('usage', 'search needs a term')
        if kind is not None and kind not in api.SEARCH_KIND_TYPES:
            raise EngineError('usage', f'no search of kind {kind}')
        offset = max(0, int(offset or 0))
        if self.demo:
            catalog = await self._demo_catalog()
            return demo_search(catalog, term, int(limit), kind, offset)
        client = await self._require_signed_in('search')
        if kind is None:
            raw = await client.bridge('search', term, int(limit), api.SEARCH_TYPES, 0, True,
                                      timeout=SEARCH_TIMEOUT)
        else:
            raw = await client.bridge('search', term, int(limit), api.SEARCH_KIND_TYPES[kind],
                                      offset, False, timeout=SEARCH_TIMEOUT)
        _raise_api_errors(raw, 'search')
        return await asyncio.to_thread(normalize.search_results, raw, str(self.cache_dir),
                                       kind)

    async def _demo_catalog(self):
        """The demo's invented catalog (normalize.demo_search_path(), marked `demo`), or
        EngineError('engine-down') without one, as for any other command in the demo."""
        catalog = await asyncio.to_thread(
            cache.read_kept, normalize.demo_search_path(str(self.cache_dir)), allow_stale=True)
        if catalog is None or catalog.get('demo') is not True:
            raise EngineError('engine-down', 'the engine is not running')
        return catalog

    async def suggest(self, term, limit=SUGGEST_LIMIT):
        """Apple's completions of a term half typed: {terms: [{term, display}], items: [Item
        without groups]}, the items its best few hits for the term as it stands. The demo
        answers no terms and the top hits of its invented catalog (demo_search())."""
        term = ' '.join(str(term or '').split())
        if not term:
            raise EngineError('usage', 'suggest needs a term')
        if self.demo:
            shelves = demo_search(await self._demo_catalog(), term, int(limit))['shelves']
            top = shelves[0]['items'] if shelves and shelves[0]['key'] == 'top' else []
            return {'terms': [], 'items': top}
        client = await self._require_signed_in('search')
        raw = await client.bridge('suggest', term, int(limit), timeout=SEARCH_TIMEOUT)
        _raise_api_errors(raw, 'suggestions')
        return await asyncio.to_thread(normalize.search_suggestions, raw, str(self.cache_dir))

    async def artist_page(self, artist_id, refresh=False):
        """A catalog artist's page: {id, artist, banner, latest, topSongs, shelves}
        (normalize.artist_page), every section of it in one read (api.ARTIST_ENDPOINT with
        all of api.ARTIST_VIEWS), the shelves in music.apple.com's order and titled as Apple
        titles them. From <cache>/artists/<id>.json for a day, else fetched and kept."""
        artist_id = str(artist_id or '')
        if not artist_id or api.is_library_id(artist_id):
            raise EngineError('usage', 'artist_page needs a catalog artist id')

        async def fetch(client):
            storefront = await self._current_storefront()
            return await self._api(
                client, api.ARTIST_ENDPOINT.format(storefront=storefront, id=artist_id),
                api.ARTIST_PARAMS, timeout=READ_TIMEOUT)
        answer = await self._kept_answer(
            normalize.artist_cache_path(str(self.cache_dir), artist_id), refresh, fetch,
            normalize.artist_page)
        # The favourite as this session last wrote or read it, over a kept answer's.
        known = self._favourite_artists.get(artist_id)
        if known is not None:
            answer['favourite'] = known
        if isinstance(answer.get('favourite'), bool):
            self.emit('rated', 'artist', artist_id, 1 if answer['favourite'] else 0)
        return answer

    async def artist_view(self, artist_id, view):
        """One of an artist's views (api.ARTIST_VIEWS) whole, for its See All: its Items as
        artist_page() has them, Apple's `next` links followed (RELATIONSHIP_PAGES at most)."""
        artist_id, view = str(artist_id or ''), str(view or '')
        if not artist_id or view not in api.ARTIST_VIEWS:
            raise EngineError('usage', 'artist_view needs a catalog artist id and a view')
        client = await self._require_signed_in('browse')
        storefront = await self._current_storefront()
        path = api.ARTIST_VIEW_ENDPOINT.format(storefront=storefront, id=artist_id, view=view)
        resources = await self._whole_view(client, path)
        return await asyncio.to_thread(normalize.artist_view_items, view, resources,
                                       str(self.cache_dir))

    async def _whole_view(self, client, path, limit=None):
        """The resources of a view (an artist's, an album's) or a relationship, a page of
        `limit` (api.ARTIST_VIEW_LIMIT unless given) at a time: Apple's `next` links followed
        (RELATIONSHIP_PAGES at most)."""
        answer = await self._api(client, path, {'limit': limit or api.ARTIST_VIEW_LIMIT},
                                 timeout=READ_TIMEOUT)
        resources = api.page_data(answer)
        link = answer.get('next')
        for _ in range(RELATIONSHIP_PAGES):
            if not isinstance(link, str) or not link.startswith('/v1/'):
                break
            answer = await self._api(client, link, timeout=READ_TIMEOUT)
            page = api.page_data(answer)
            if not page:
                break
            resources += page
            link = answer.get('next')
        return resources

    async def album_page(self, album_id, song_id=None, refresh=False):
        """The rest of an album's page, under its tracks: {id, artistId, artistName, release,
        shelves} (normalize.album_page): the footer's release date, copyright and label, and
        the shelves in music.apple.com's order (Other Versions, Music Videos, More By, Featured
        On, You Might Also Like), titled as Apple titles them (More By untitled: the page
        names it). Two reads: the catalog album with its views (api.ALBUM_ENDPOINT), then a
        page of its first artist's albums (api.MORE_BY_VIEW; More By is left out when that
        read fails, and the answer is not kept). A library album (an `l.` id) is its
        catalog album, found through `song_id`, one of its songs' catalog ids: one read
        more, the first time. From <cache>/albums/<id>.json for a day, else fetched and
        kept, with the views it asked for as its `basis`: one kept with other views (an
        older app's) is asked again. An album the catalog lacks is Apple's 404
        (EngineError.status)."""
        album_id = str(album_id or '')
        song_id = str(song_id or '')
        if not album_id or (api.is_library_id(album_id) and not song_id):
            raise EngineError('usage', 'album_page needs a catalog album id, or a song id')

        async def fetch(client):
            storefront = await self._current_storefront()
            catalog_id = album_id
            if api.is_library_id(album_id):
                found = await self._api(
                    client, api.RELATED_ENDPOINTS['song'].format(storefront=storefront,
                                                                 id=song_id),
                    api.SONG_ALBUMS_PARAMS, timeout=READ_TIMEOUT)
                catalog_id = api.first_related_id(found, 'albums')
                if catalog_id is None:
                    raise EngineError('api', f'no catalog album for song {song_id}',
                                      status=404)
            album = await self._api(
                client, api.ALBUM_ENDPOINT.format(storefront=storefront, id=catalog_id),
                api.ALBUM_PARAMS, timeout=READ_TIMEOUT)
            more_by = None
            artist_id = api.first_related_id(album, 'artists')
            if artist_id is not None:
                try:
                    more_by = await self._api(
                        client, api.ARTIST_VIEW_ENDPOINT.format(
                            storefront=storefront, id=artist_id, view=api.MORE_BY_VIEW),
                        {'limit': api.MORE_BY_LIMIT}, timeout=READ_TIMEOUT)
                except EngineError as error:
                    if error.code == 'engine-down':
                        raise
                    log.info('the albums of artist %s: %s', artist_id, error)
                    return _Unkept({'album': album, 'moreBy': None})
            return {'album': album, 'moreBy': more_by}
        return await self._kept_answer(
            normalize.album_cache_path(str(self.cache_dir), album_id), refresh, fetch,
            normalize.album_page, basis=api.ALBUM_PARAMS['views'])

    async def album_view(self, album_id, view):
        """One of a catalog album's views (api.ALBUM_VIEWS) whole, for its See All: its
        Items as album_page() has them, Apple's `next` links followed."""
        album_id, view = str(album_id or ''), str(view or '')
        if not album_id or api.is_library_id(album_id) or view not in api.ALBUM_VIEWS:
            raise EngineError('usage', 'album_view needs a catalog album id and a view')
        client = await self._require_signed_in('browse')
        storefront = await self._current_storefront()
        path = api.ALBUM_VIEW_ENDPOINT.format(storefront=storefront, id=album_id, view=view)
        resources = await self._whole_view(client, path)
        return await asyncio.to_thread(normalize.album_view_items, view, resources,
                                       str(self.cache_dir))

    async def playlist_page(self, playlist_id, refresh=False):
        """The rest of a catalog playlist's page, under its tracks: {id, curator, shelves}
        (normalize.playlist_page): the curator its title names, for the link to their page,
        and the shelves in music.apple.com's order (Featured Artists, More By the curator,
        You Might Also Like), titled as Apple titles them. Two reads: the catalog playlist
        with its curator and views (api.PLAYLIST_PARAMS), asked again with the documented
        views alone (api.PLAYLIST_PLAIN_PARAMS) when Apple answers it with a 400, then, for
        an Apple curator's, a page of the curator's playlists, which More By shows (Apple's
        view of it is empty: api.CURATOR_PLAYLISTS_ENDPOINT; More By is left out when that
        read fails, and the answer is not kept). From <cache>/playlists/<id>.json for a
        day, else fetched and kept, with the views it asked for as its `basis`. A playlist
        the catalog lacks is Apple's 404 (EngineError.status); a library playlist's id is
        `usage` (its catalog id is asked by)."""
        playlist_id = str(playlist_id or '')
        if not playlist_id or api.is_library_id(playlist_id):
            raise EngineError('usage', 'playlist_page needs a catalog playlist id')

        async def fetch(client):
            storefront = await self._current_storefront()
            path = api.PLAYLIST_ENDPOINT.format(storefront=storefront, id=playlist_id)
            try:
                playlist = await self._api(client, path, api.PLAYLIST_PARAMS,
                                           timeout=READ_TIMEOUT)
            except EngineError as error:
                if error.status != 400:
                    raise
                log.info('playlist %s with its views: %s; asking for fewer', playlist_id,
                         error)
                playlist = await self._api(client, path, api.PLAYLIST_PLAIN_PARAMS,
                                           timeout=READ_TIMEOUT)
            curator_playlists = None
            curator_id = api.apple_curator_id(playlist)
            if curator_id is not None:
                try:
                    curator_playlists = await self._api(
                        client, api.CURATOR_PLAYLISTS_ENDPOINT.format(storefront=storefront,
                                                                      id=curator_id),
                        {'limit': api.CURATOR_PLAYLISTS_LIMIT}, timeout=READ_TIMEOUT)
                except EngineError as error:
                    if error.code == 'engine-down':
                        raise
                    log.info('the playlists of curator %s: %s', curator_id, error)
                    return _Unkept({'playlist': playlist, 'curatorPlaylists': None})
            return {'playlist': playlist, 'curatorPlaylists': curator_playlists}
        return await self._kept_answer(
            normalize.playlist_cache_path(str(self.cache_dir), playlist_id), refresh, fetch,
            normalize.playlist_page, basis=api.PLAYLIST_PARAMS['views'])

    async def playlist_view(self, playlist_id, view):
        """One of a catalog playlist's views (api.PLAYLIST_READABLE_VIEWS) whole, for its See
        All: its Items as playlist_page() has them (the playlist itself left out), Apple's
        `next` links followed. More By the curator is curator_playlists()."""
        playlist_id, view = str(playlist_id or ''), str(view or '')
        if (not playlist_id or api.is_library_id(playlist_id)
                or view not in api.PLAYLIST_READABLE_VIEWS):
            raise EngineError('usage', 'playlist_view needs a catalog playlist id and a view')
        client = await self._require_signed_in('browse')
        storefront = await self._current_storefront()
        path = api.PLAYLIST_VIEW_ENDPOINT.format(storefront=storefront, id=playlist_id,
                                                 view=view)
        resources = await self._whole_view(client, path)
        return await asyncio.to_thread(normalize.playlist_view_items, resources, playlist_id,
                                       str(self.cache_dir))

    async def curator_playlists(self, curator_id):
        """An Apple curator's playlists whole (api.CURATOR_PLAYLISTS_ENDPOINT), for See All on
        a catalog playlist's More By: Items as playlist_page() has them, every one (the page
        leaves its own playlist out), a page of api.CURATOR_PLAYLISTS_LIMIT at a time,
        Apple's `next` links followed."""
        curator_id = str(curator_id or '')
        if not api.is_curator_id(curator_id):
            raise EngineError('usage', 'curator_playlists needs an Apple curator id')
        client = await self._require_signed_in('browse')
        storefront = await self._current_storefront()
        path = api.CURATOR_PLAYLISTS_ENDPOINT.format(storefront=storefront, id=curator_id)
        resources = await self._whole_view(client, path, api.CURATOR_PLAYLISTS_LIMIT)
        return await asyncio.to_thread(normalize.playlist_view_items, resources, '',
                                       str(self.cache_dir))

    async def playlist_suggestions(self, playlist_id, refresh=False, limit=SUGGESTIONS_LIMIT,
                                   offered=(), selected=(), more=False, basis=None,
                                   previewed=()):
        """The songs Apple suggests adding to a library playlist, as music.apple.com shows
        them under it: {items} (normalize.playlist_suggestions), at most `limit` song Items
        in Apple's order, which may include songs the playlist holds already. One read (the
        bridge's playlistSuggestions()), from <cache>/suggestions/<id>.json for a day, else
        fetched and kept; `refresh` asks Apple for new ones, which are kept instead. `basis`
        names what the playlist holds (suggestions.basis()): an answer kept for another, the
        playlist changed since, is asked for again.
        `offered` (the catalog ids shown so far), `selected` (those of them added) and
        `previewed` (those whose preview was played) tell Apple what not to suggest again,
        and how each was taken, as music.apple.com's Refresh does. `more` asks for a
        few more beside those (nothing kept, nothing read from the file): the demo has none."""
        playlist_id = str(playlist_id or '')
        if not is_library_id(playlist_id):
            raise EngineError('usage', 'playlist_suggestions needs a library playlist id')
        offered = [str(song_id) for song_id in offered if song_id]
        selected = [str(song_id) for song_id in selected if song_id]
        previewed = [str(song_id) for song_id in previewed if song_id]

        async def fetch(client):
            answer = await client.bridge('playlistSuggestions', playlist_id, int(limit),
                                         offered, selected, previewed, timeout=READ_TIMEOUT)
            error = api.api_error(answer, 'suggested songs')
            if error is not None:
                raise error
            return answer if isinstance(answer, dict) else {}
        if more:
            if self.demo:
                raise EngineError('engine-down', 'the engine is not running')
            raw = await fetch(await self._require_signed_in('browse'))
            return await asyncio.to_thread(normalize.playlist_suggestions, raw,
                                           str(self.cache_dir))
        return await self._kept_answer(
            normalize.suggestions_cache_path(str(self.cache_dir), playlist_id), refresh, fetch,
            normalize.playlist_suggestions, basis=basis)

    async def credits(self, song_id, refresh=False):
        """A catalog song's credits, as View Credits shows them: {categories: [{kind, title,
        people: [{name, roles}]}]} (normalize.song_credits), the performers, the composition
        and lyrics, the production and engineering, in Apple's order and titled as Apple
        titles them. One read (api.SONG_CREDITS_ENDPOINT); Apple's 404, a song it has no
        credits for, is no categories. From <cache>/credits/<id>.json for a day, else fetched
        and kept. A library id is EngineError('usage'): a library song is asked by its
        catalog id."""
        song_id = str(song_id or '')
        if not song_id or is_library_id(song_id):
            raise EngineError('usage', 'credits needs a catalog song id')

        async def fetch(client):
            storefront = await self._current_storefront()
            try:
                return await self._api(
                    client, api.SONG_CREDITS_ENDPOINT.format(storefront=storefront, id=song_id),
                    timeout=READ_TIMEOUT)
            except EngineError as error:
                if error.status != 404:
                    raise
                log.info('no credits for song %s', song_id)
                return {'data': []}
        return await self._kept_answer(
            normalize.credits_cache_path(str(self.cache_dir), song_id), refresh, fetch,
            normalize.song_credits)

    async def catalog_artist(self, name, song_ids):
        """The id of the catalog artist a library artist stands for, or None. The library
        makes its artists up from its songs' artist names (an `l.art_` id, no catalog id), so
        the artist is found through its songs: each of `song_ids` (catalog song ids) in turn
        is read with its artists, and the first artist named `name` (case aside) is the one.
        Remembered for the session, a miss too."""
        name = ' '.join(str(name or '').split())
        key = name.casefold()
        if not key:
            return None
        if key in self._catalog_artists:
            return self._catalog_artists[key]
        client = await self._require_signed_in('browse')
        storefront = await self._current_storefront()
        found = None
        for song_id in [str(song_id) for song_id in song_ids if song_id][:CATALOG_ARTIST_TRIES]:
            try:
                answer = await self._api(
                    client, api.SONG_ARTISTS_ENDPOINT.format(storefront=storefront, id=song_id),
                    api.SONG_ARTISTS_PARAMS, timeout=READ_TIMEOUT)
            except EngineError as error:
                if error.code == 'engine-down':
                    raise
                log.debug('the artists of song %s: %s', song_id, error)
                continue
            for song in api.page_data(answer):
                artists = ((song.get('relationships') or {}).get('artists') or {}).get('data')
                for artist in artists if isinstance(artists, list) else []:
                    if not isinstance(artist, dict):
                        continue
                    artist_name = (artist.get('attributes') or {}).get('name') or ''
                    if ' '.join(str(artist_name).split()).casefold() == key and artist.get('id'):
                        found = str(artist['id'])
                        break
                if found:
                    break
            if found:
                break
        self._catalog_artists[key] = found
        return found

    async def related(self, kind, item_id):
        """Where Go to Album and Go to Artist go for a catalog song, music video or album
        (`kind` 'song', 'video' or 'album') the library cannot place: {album, artists}
        (normalize.related), its album (None for an album) and its artists as Items without
        groups, from one read of it with its relationships (api.RELATED_ENDPOINTS).
        Remembered for the session. A library id is EngineError('usage')."""
        item_id = str(item_id or '')
        endpoint = api.RELATED_ENDPOINTS.get(kind)
        if endpoint is None or not item_id or is_library_id(item_id):
            raise EngineError('usage', f'related needs a catalog song, video or album: '
                                       f'{kind} {item_id}'.strip())
        key = (kind, item_id)
        if key in self._related:
            return self._related[key]
        client = await self._require_signed_in('look items up')
        storefront = await self._current_storefront()
        answer = await self._api(client, endpoint.format(storefront=storefront, id=item_id),
                                 api.RELATED_PARAMS[kind], timeout=READ_TIMEOUT)
        # Off the loop: a hit's artwork is looked for on disk, as a search's are.
        found = await asyncio.to_thread(normalize.related, answer, str(self.cache_dir))
        self._related[key] = found
        return found
