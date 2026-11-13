# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the commands change in the account, through the bridge's request builder: ratings and
favourite artists, the library's items, its playlists and folders, with the reads that
check them."""

import asyncio
import logging

from ..backend import api, cache_files, normalize, store
from ..backend.api import is_library_id, resource_type
from ..backend.errors import EngineError
from .reads import READ_TIMEOUT, _raise_api_errors

log = logging.getLogger(__name__)

SONG_IDS_PER_READ = 100   # songs looked up by id in one read (songs_found)

# The kinds add_to_library() takes (a station is followed, not added).
ADDABLE_KINDS = ('song', 'album', 'playlist', 'video', 'musicVideo', 'music-video')

# What library.json calls the top level of the playlist folders (library.ROOT_FOLDER), and
# Apple's id for it.
ROOT_FOLDER = api.ROOT_FOLDER
APPLE_ROOT_FOLDER = api.APPLE_ROOT_FOLDER


def _library_playlist(playlist_id):
    """A library playlist's id, as the playlist writes take it: EngineError('usage') for
    anything else (a catalog playlist is not the account's to change)."""
    playlist_id = str(playlist_id or '')
    if not playlist_id.startswith('p.'):
        raise EngineError('usage', f'{playlist_id or "nothing"} is not a library playlist')
    return playlist_id


def _folder(folder_id):
    """A playlist folder's id for Apple, or None for the top level (no id, the library's
    ROOT_FOLDER or Apple's own root). EngineError('usage') for an id that is no folder's."""
    folder_id = str(folder_id or '')
    if folder_id in ('', ROOT_FOLDER, APPLE_ROOT_FOLDER):
        return None
    if not folder_id.startswith('p.'):
        raise EngineError('usage', f'{folder_id} is not a playlist folder')
    return folder_id


def _catalog_artist_id(artist_id):
    """A catalog artist's id as a string; EngineError('usage') for none or a library id
    (only the catalog's artists can be favourites)."""
    artist_id = str(artist_id or '')
    if not artist_id or api.is_library_id(artist_id):
        raise EngineError('usage', 'a favourite artist needs a catalog artist id')
    return artist_id


class AccountEdits:
    """The Engine's writes to the account: a mixin of Engine (core.py), whose
    _require_signed_in(), _api(), api_pages(), _current_storefront(), _favourite_artists,
    cache_dir and demo they use."""

    # -- ratings and the library ---------------------------------------------------------
    # The heart and the item actions' writes, through the bridge's rating(), addToLibrary(),
    # removeFromLibrary() and addToPlaylist() (MusicKit's request builder, judged by the
    # HTTP status: a refusal
    # is EngineError('api') with Apple's "HTTP 403 Forbidden: …"), and the reads beside them
    # (rating, catalog_url), each needing a signed-in engine.

    async def love(self, kind, item_id):
        """Love (favourite) a song, album, playlist, station or music video: PUT
        /v1/me/ratings/<type>s/<id> with the value 1. A library id rates the library item,
        a catalog id the catalog's; loving a song adds it to Favourite Songs."""
        await self._rate(kind, item_id, 1)

    async def suggest_less(self, kind, item_id):
        """Suggest Less of a song, album, playlist, station or music video: the same PUT
        with the value -1. An item has one rating, so this replaces a favourite (and a
        song leaves Favourite Songs), as love() replaces it."""
        await self._rate(kind, item_id, -1)

    async def unlove(self, kind, item_id):
        """Take the rating away, a favourite or a Suggest Less (DELETE
        /v1/me/ratings/<type>s/<id>)."""
        await self._rate(kind, item_id, 0)

    async def _rate(self, kind, item_id, value):
        rated = resource_type(kind, item_id)
        client = await self._require_signed_in('rate items')
        await client.bridge('rating', rated, str(item_id), value)
        self.emit('rated', str(kind), str(item_id), value)

    async def rating(self, kind, item_id):
        """The item's rating: 1 loved, -1 Suggest Less, 0 neither (a read of
        /v1/me/ratings/<type>s?ids=<id>, which answers an empty list for an item without
        one, where the single-item path answers a 404)."""
        rated = resource_type(kind, item_id)
        client = await self._require_signed_in('read ratings')
        answer = await self._api(client, f'/v1/me/ratings/{rated}s', {'ids': str(item_id)},
                                 timeout=READ_TIMEOUT)
        value = 0
        for entry in api.page_data(answer):
            attributes = entry.get('attributes')
            number = attributes.get('value') if isinstance(attributes, dict) else None
            if isinstance(number, int) and not isinstance(number, bool):
                value = max(-1, min(1, number))
                break
        self.emit('rated', str(kind), str(item_id), value)
        return value

    # An artist's favourite is not a rating (src/backend/README.md): the web player's
    # /v1/me/favorites, and the catalog read's inFavorites.

    async def favourite_artist(self, artist_id):
        """Make the catalog artist one of the account's favourites (POST
        /v1/me/favorites?ids[artists]=<id>, the bridge's favourite()). It does not add them
        to the library. `rated('artist', id, 1)` follows, and the artist's kept page says so
        (cache_files.patch_answer). In demo mode only this session remembers it."""
        await self._favourite_artist(artist_id, True)

    async def unfavourite_artist(self, artist_id):
        """The artist no longer one of the account's favourites (the same DELETE)."""
        await self._favourite_artist(artist_id, False)

    async def _favourite_artist(self, artist_id, favourite):
        artist_id = _catalog_artist_id(artist_id)
        if not self.demo:
            generation = store.cache_generation()
            client = await self._require_signed_in('favourite artists')
            await client.bridge('favourite', 'artists', artist_id, favourite)
            await asyncio.to_thread(
                cache_files.patch_answer,
                cache_files.artist_cache_path(str(self.cache_dir), artist_id),
                {'favourite': favourite}, str(self.cache_dir), generation)
        self._favourite_artists[artist_id] = favourite
        self.emit('rated', 'artist', artist_id, 1 if favourite else 0)

    async def is_favourite_artist(self, artist_id):
        """Whether the catalog artist is one of the account's favourites: the catalog read's
        `inFavorites` (api.FAVOURITE_PARAMS) through the bridge's apiFresh (the request
        builder: music() may answer from its cache from before a change). False when Apple
        does not say. `rated('artist', id, 1 or 0)` follows."""
        artist_id = _catalog_artist_id(artist_id)
        client = await self._require_signed_in('read favourites')
        storefront = await self._current_storefront()
        answer = await client.bridge(
            'apiFresh', api.ARTIST_ENDPOINT.format(storefront=storefront, id=artist_id),
            api.FAVOURITE_PARAMS, timeout=READ_TIMEOUT)
        _raise_api_errors(answer, 'favourite')
        favourite = normalize.in_favourites(answer) is True
        self._favourite_artists[artist_id] = favourite
        self.emit('rated', 'artist', artist_id, 1 if favourite else 0)
        return favourite

    async def add_to_library(self, kind, item_id):
        """Add a catalog song, album, playlist or music video to the library (POST
        /v1/me/library?ids[<type>s]=<id>). A library id is refused: it is there already."""
        if kind not in ADDABLE_KINDS or item_id in (None, ''):
            raise EngineError('usage', f'cannot add {kind or "nothing"} to the library')
        if is_library_id(item_id):
            raise EngineError('usage', f'{item_id} is in the library already')
        client = await self._require_signed_in('add to your library')
        await client.bridge('addToLibrary', api.RESOURCE_TYPES[kind], str(item_id))

    async def remove_from_library(self, kind, item_id):
        """Take a song, album, music video or playlist out of the library, on every device
        (DELETE /v1/me/library/<type>/<library id>, the web player's
        requestDeleteFromLibrary; `type` the catalog type, api.LIBRARY_ROUTES). A catalog id
        is first read for its library twin (relate=library: Apple answers a DELETE by
        catalog id with a 500), and is EngineError('api', status 404) when the library has
        none. A song goes from every playlist that held it too, an album with its tracks;
        the library listings drop it some seconds later (in_library()). Answers the library
        id removed."""
        route = api.LIBRARY_ROUTES.get(kind)
        item_id = str(item_id or '')
        if route is None or not item_id:
            raise EngineError('usage', f'cannot remove {kind or "nothing"} from the library')
        client = await self._require_signed_in('remove from your library')
        if not is_library_id(item_id):
            storefront = await self._current_storefront()
            answer = await self._api(
                client, api.LIBRARY_TWIN_ENDPOINT.format(storefront=storefront),
                api.library_twin_params(kind, item_id), timeout=READ_TIMEOUT)
            library_id = api.library_twin(answer)
            if library_id is None:
                raise EngineError('api', f'{kind} {item_id} is not in the library', status=404)
            item_id = library_id
        await client.bridge('removeFromLibrary', route, item_id)
        return item_id

    async def in_library(self, kind, library_id):
        """Whether the library still holds the song, album, music video or playlist
        `library_id`: its read under /v1/me/library through the bridge's libraryHas (the
        request builder: what music() answers may be cached from before a removal), False
        once Apple answers 404. A song was 404 within 2 s of its removal, an album within 7
        (src/backend/README.md)."""
        route = api.LIBRARY_ROUTES.get(kind)
        library_id = str(library_id or '')
        if route is None or not is_library_id(library_id):
            raise EngineError('usage', f'{library_id or "nothing"} is not a library item')
        client = await self._require_signed_in('read your library')
        answer = await client.bridge('libraryHas', route, library_id, timeout=READ_TIMEOUT)
        return not (isinstance(answer, dict) and answer.get('has') is False)

    async def songs_found(self, song_ids):
        """Which of `song_ids` (library "i." ids and catalog ids) Apple still has: read by id,
        SONG_IDS_PER_READ at a time, under /v1/me/library/songs and the storefront's
        /v1/catalog/<storefront>/songs, which answer only the songs that exist (a 404 when
        none does). The set of the ids answered; EngineError when a read fails otherwise."""
        client = await self._require_signed_in('look songs up')
        song_ids = list(dict.fromkeys(str(song_id) for song_id in song_ids if song_id))
        library = [song_id for song_id in song_ids if is_library_id(song_id)]
        catalog = [song_id for song_id in song_ids if not is_library_id(song_id)]
        paths = []
        if library:
            paths.append(('/v1/me/library/songs', library))
        if catalog:
            storefront = await self._current_storefront()
            paths.append((f'/v1/catalog/{storefront}/songs', catalog))

        async def read(path, ids):
            try:
                answer = await self._api(client, path, {'ids': ','.join(ids)},
                                         timeout=READ_TIMEOUT)
            except EngineError as e:
                if e.code == 'api' and e.status == 404:
                    return set()
                raise
            return {entry.get('id') for entry in api.page_data(answer)}

        answers = await asyncio.gather(*(
            read(path, ids[start:start + SONG_IDS_PER_READ])
            for path, ids in paths for start in range(0, len(ids), SONG_IDS_PER_READ)))
        found = set().union(*answers)
        return {song_id for song_id in song_ids if song_id in found}

    async def catalog_url(self, kind, item_id):
        """The music.apple.com page of a library item's catalog equivalent (its
        /v1/me/library/<type>s/<id>/catalog relationship), or None when it has none (a
        playlist of the user's, an upload). A catalog id is refused: its Item has the URL."""
        rated = resource_type(kind, item_id)
        if not rated.startswith('library-') or rated == 'library-station':
            raise EngineError('usage', f'{item_id} is not a library item')
        client = await self._require_signed_in('look items up')
        try:
            answer = await self._api(client, f'/v1/me/library/{rated[len("library-"):]}s/'
                                             f'{item_id}/catalog', timeout=READ_TIMEOUT)
        except EngineError as e:
            if e.code == 'engine-down':
                raise
            log.debug('catalog of %s %s: %s', kind, item_id, e)
            return None
        for entry in api.page_data(answer):
            url = (entry.get('attributes') or {}).get('url')
            if isinstance(url, str) and url.startswith('https://'):
                return url
        return None

    async def add_to_playlist(self, playlist_id, song_id, kind='song'):
        """Add a song, or a music video (`kind` 'video'), to the end of a library playlist
        (POST /v1/me/library/playlists/<id>/tracks): a library id ("i.") as `library-songs`
        or `library-music-videos`, a catalog one as `songs` or `music-videos`."""
        await self.add_tracks_to_playlist(playlist_id, [(kind, song_id)])

    async def add_tracks_to_playlist(self, playlist_id, tracks):
        """Add songs and music videos `tracks` ((kind, id) pairs, as add_to_playlist takes
        one: an album's or a playlist's) to the end of a library playlist, in their order:
        one POST of their list for each api.PLAYLIST_BATCH of them, one after the other.
        Answers how many were added. A failure after some batches went in is raised with
        how many had (the `api` code and Apple's status kept); those stay in the playlist."""
        playlist_id = str(playlist_id or '')
        if not is_library_id(playlist_id):
            raise EngineError('usage', 'add to playlist needs a library playlist and a song '
                                       'or a music video')
        entries = api.playlist_entries_for(tracks)
        if not entries:
            raise EngineError('usage', 'add to playlist needs a song or a music video')
        client = await self._require_signed_in('add to playlists')
        await self._add_entries(client, playlist_id, entries)
        return len(entries)

    async def _add_entries(self, client, playlist_id, entries, added=0):
        """POST `entries` to the playlist's tracks in batches (add_tracks_to_playlist);
        `added`, how many of the whole list went in before these, for the message of a
        failure partway."""
        for batch in api.batches(entries, api.PLAYLIST_BATCH):
            try:
                await client.bridge('addToPlaylist', playlist_id, batch)
            except EngineError as e:
                if not added:
                    raise
                raise EngineError(e.code, f'after {added} tracks: {e.message}',
                                  status=e.status) from e
            added += len(batch)

    # -- managing playlists ----------------------------------------------------------------
    # The writes music.apple.com's web player makes to the account's playlists and folders,
    # through the bridge (src/backend/README.md has the requests and what Apple answered).

    async def create_playlist(self, name, description='', tracks=(), folder_id=None,
                              public=False):
        """A new library playlist named `name` (POST /v1/me/library/playlists), with the
        songs and music videos `tracks` ((kind, id) pairs, as add_to_playlist takes them) in
        it (the first api.PLAYLIST_BATCH with it, the rest added after: _add_entries), in
        the folder `folder_id` (None or 'root': the top level), shown on the account's
        profile and in search when `public` (Apple's isPublic). Answers its id. Apple
        lists a new playlist only seconds later (6.5 s once: src/backend/README.md)."""
        name = str(name or '').strip()
        if not name:
            raise EngineError('usage', 'a playlist needs a name')
        entries = api.playlist_entries_for(tracks)
        attributes = {'name': name}
        if description:
            attributes['description'] = str(description)
        if public:
            attributes['isPublic'] = True
        client = await self._require_signed_in('make playlists')
        first, rest = entries[:api.PLAYLIST_BATCH], entries[api.PLAYLIST_BATCH:]
        answer = await client.bridge('createPlaylist', attributes, first,
                                     _folder(folder_id))
        new_id = answer.get('id') if isinstance(answer, dict) else None
        if not new_id:
            raise EngineError('api', 'the new playlist came back without its id')
        if rest:
            await self._add_entries(client, str(new_id), rest, added=len(first))
        return str(new_id)

    async def edit_playlist(self, playlist_id, name=None, description=None, public=None):
        """A library playlist's name, its description, whether it is public (shown on the
        account's profile and in search: Apple's isPublic), or any of them (PATCH
        /v1/me/library/playlists/<id>); None leaves one as it is, '' clears the
        description. A name cannot be empty."""
        attributes = {}
        if name is not None:
            attributes['name'] = str(name).strip()
            if not attributes['name']:
                raise EngineError('usage', 'a playlist needs a name')
        if description is not None:
            attributes['description'] = str(description)
        if public is not None:
            attributes['isPublic'] = bool(public)
        playlist_id = _library_playlist(playlist_id)
        if not attributes:
            return
        client = await self._require_signed_in('edit playlists')
        await client.bridge('updatePlaylist', playlist_id, attributes)

    async def delete_playlist(self, playlist_id):
        """A library playlist out of the library, on every device (DELETE
        /v1/me/library/playlists/<id>)."""
        playlist_id = _library_playlist(playlist_id)
        client = await self._require_signed_in('delete playlists')
        await client.bridge('deletePlaylist', playlist_id)

    async def remove_from_playlist(self, playlist_id, track_id, index=None):
        """One entry out of a library playlist: the song (or music video) `track_id` that the
        playlist's list has at `index` (its Track.index), or near it.

        The playlist's tracks are read first, as Apple has them now. A song the playlist
        holds once goes the way the web player removes it (DELETE …/tracks?ids[<type>]=<id>
        &mode=all, which takes every entry of that id); a song it holds more than once is
        taken out of the list, which is then put back whole (PUT …/tracks), so its other
        entries stay. The entry is the one at `index` when the list there has that id still,
        else the entry of that id nearest `index`. A song no longer in the playlist is
        nothing to do. Answers whether anything was removed."""
        playlist_id = _library_playlist(playlist_id)
        track_id = str(track_id or '')
        if not track_id:
            raise EngineError('usage', 'remove from playlist needs a track')
        client = await self._require_signed_in('edit playlists')
        try:
            entries = await self.api_pages(f'/v1/me/library/playlists/{playlist_id}/tracks')
        except EngineError as e:
            if e.status != 404:  # Apple's answer for a playlist without tracks
                raise
            entries = []
        listed = [{'id': str(entry.get('id') or ''), 'type': str(entry.get('type') or '')}
                  for entry in entries]
        positions = [position for position, entry in enumerate(listed)
                     if entry['id'] == track_id]
        if not positions:
            log.info('remove from playlist: the track is not in it (any more)')
            return False
        if len(positions) == 1:
            entry = listed[positions[0]]
            await client.bridge('removeFromPlaylist', playlist_id,
                                entry['type'] or 'library-songs', track_id)
            return True
        wanted = index if isinstance(index, int) and not isinstance(index, bool) else 0
        position = min(positions, key=lambda found: (abs(found - wanted), found))
        kept = api.playlist_entries(entries)
        del kept[position]
        await client.bridge('replacePlaylistTracks', playlist_id, kept)
        return True

    async def _playlist_listing(self, playlist_id):
        """A library playlist's tracks as Apple lists them now, every page (none for Apple's
        404, its answer for a playlist without tracks)."""
        try:
            return await self.api_pages(f'/v1/me/library/playlists/{playlist_id}/tracks')
        except EngineError as e:
            if e.status != 404:
                raise
            return []

    async def remove_playlist_entries(self, playlist_id, shown, positions):
        """Several entries out of a library playlist in one write: those at `positions`, places
        in `shown`, the ids of its tracks as the app showed them when they were chosen (a
        selection's Remove from Playlist).

        The tracks are read first, as Apple has them now; nothing is written when Apple's list
        is not `shown` any more (EngineError('conflict'), api.kept_entries()). The entries kept
        are put back whole (PUT …/tracks, as a reorder writes them), so of a song held twice
        only the entry chosen goes; when none is kept, each song goes the way the web player
        removes one (DELETE …/tracks?ids[<type>]=<id>&mode=all), never an empty PUT. Answers
        every entry Apple had before ({id, type}, in order), which
        put_back_playlist_entries() writes back for an Undo."""
        playlist_id = _library_playlist(playlist_id)
        client = await self._require_signed_in('edit playlists')
        listed = await self._playlist_listing(playlist_id)
        kept, removed = api.kept_entries(listed, shown, positions)
        before = api.playlist_entries(listed)
        if kept:
            await client.bridge('replacePlaylistTracks', playlist_id, kept)
            return before
        for entry in {(entry['type'], entry['id']): entry for entry in removed}.values():
            await client.bridge('removeFromPlaylist', playlist_id, entry['type'], entry['id'])
        return before

    async def put_back_playlist_entries(self, playlist_id, kept, entries):
        """Undo a removal of several entries: the playlist's tracks made `entries` again (the
        {id, type} remove_playlist_entries() answered) in one PUT, when Apple still lists the
        ones it kept (`kept`, their ids in order); EngineError('conflict') when the playlist
        changed since, and nothing is written."""
        playlist_id = _library_playlist(playlist_id)
        client = await self._require_signed_in('edit playlists')
        listed = await self._playlist_listing(playlist_id)
        if [str(entry.get('id') or '') for entry in listed] != [str(i) for i in kept]:
            raise EngineError('conflict', 'the playlist changed since the songs were removed')
        await client.bridge('replacePlaylistTracks', playlist_id,
                            [{'id': str(entry['id']), 'type': str(entry['type'])}
                             for entry in entries])

    async def playlist_track_ids(self, playlist_id):
        """The ids of a library playlist's tracks as Apple lists them now, in order (none
        for Apple's 404, its answer for a playlist without tracks): whether a write shows."""
        playlist_id = _library_playlist(playlist_id)
        await self._require_signed_in('read playlists')
        try:
            entries = await self.api_pages(f'/v1/me/library/playlists/{playlist_id}/tracks')
        except EngineError as e:
            if e.status != 404:
                raise
            return []
        return [str(entry.get('id') or '') for entry in entries]

    async def reorder_playlist(self, playlist_id, shown, order):
        """A library playlist's tracks in a new order: `order` is a permutation of positions
        in `shown`, the ids of its tracks as the app showed them when the order was chosen.

        The tracks are read first, as Apple has them now, and put back whole in the new
        order (PUT …/tracks, the web player's reorder): every entry read, those Apple cannot
        play among them, by its own id and type. Nothing is written when Apple's list is not
        `shown` any more (EngineError('conflict'): changed on another device, or since the
        app read it) or an entry came without its id or type ('api'). Positions, not ids,
        say what moved, so of a song held twice the entry moved is the one that moves."""
        playlist_id = _library_playlist(playlist_id)
        client = await self._require_signed_in('edit playlists')
        try:
            entries = await self.api_pages(f'/v1/me/library/playlists/{playlist_id}/tracks')
        except EngineError as e:
            if e.status != 404:  # Apple's answer for a playlist without tracks
                raise
            entries = []
        await client.bridge('replacePlaylistTracks', playlist_id,
                            api.reordered_entries(entries, shown, order))

    async def rename_folder(self, folder_id, name):
        """A playlist folder's name (PATCH /v1/me/library/playlist-folders/<id>)."""
        name = str(name or '').strip()
        folder_id = _folder(folder_id)
        if not name or folder_id is None:
            raise EngineError('usage', 'rename a folder needs a folder and a name')
        client = await self._require_signed_in('edit playlist folders')
        await client.bridge('updateFolder', folder_id, {'name': name})

    async def delete_folder(self, folder_id):
        """A playlist folder out of the library, and every playlist and folder in it, on
        every device. What is in it goes first, one by one (delete_playlist(), and the
        folders in it the same way), then the folder, empty (DELETE
        /v1/me/library/playlist-folders/<id>): Apple deletes a folder that still holds
        playlists, but went on listing those playlists, nameless, long after (more than
        half an hour on 2026-10-03), where a playlist deleted by itself left the
        listing within minutes."""
        folder_id = _folder(folder_id)
        if folder_id is None:
            raise EngineError('usage', 'delete a folder needs a folder')
        client = await self._require_signed_in('delete playlist folders')
        for child in await self.folder_children(folder_id):
            if child['kind'] == 'folder':
                await self.delete_folder(child['id'])
            else:
                await client.bridge('deletePlaylist', child['id'])
        await client.bridge('deleteFolder', folder_id)

    async def create_folder(self, name, folder_id=None):
        """A new playlist folder named `name` (POST /v1/me/library/playlist-folders), in the
        folder `folder_id` (None or 'root': the top level; else a `parent` relationship,
        which Apple honours). Answers its id. Apple lists one at the top level seconds
        later, one inside a folder about a minute later."""
        name = str(name or '').strip()
        if not name:
            raise EngineError('usage', 'a folder needs a name')
        parent = _folder(folder_id)
        client = await self._require_signed_in('make playlist folders')
        answer = await client.bridge('createFolder', {'name': name}, parent)
        new_id = answer.get('id') if isinstance(answer, dict) else None
        if not new_id:
            raise EngineError('api', 'the new folder came back without its id')
        return str(new_id)

    async def move_to_folder(self, kind, item_id, folder_id=None):
        """A library playlist (`kind` 'playlist') or folder ('folder') into the folder
        `folder_id` (None or 'root': the top level, Apple's root folder), as the web player
        moves one (PUT /v1/me/library/playlists/<id>/parent, or playlist-folders/<id>/parent
        for a folder). Only the moves Apple is known to take (api.can_move_to_folder: all of
        these, as long as its switches are on); anything else is EngineError('usage'), as is
        a folder into itself. Apple lists a folder in its new folder about a minute later
        (src/backend/README.md), a playlist or a folder at the top level within seconds."""
        if kind == 'folder':
            item_id = _folder(item_id)
            if item_id is None:
                raise EngineError('usage', 'the top level cannot be moved')
        elif kind == 'playlist':
            item_id = _library_playlist(item_id)
        else:
            raise EngineError('usage', f'cannot move {kind} into a folder')
        target = _folder(folder_id)
        if target == item_id:
            raise EngineError('usage', 'a folder cannot go into itself')
        if not api.can_move_to_folder(kind, target):
            raise EngineError('usage', f'Apple is not known to take this move of a {kind}')
        resource = 'library-playlist-folders' if kind == 'folder' else 'library-playlists'
        client = await self._require_signed_in('move playlists')
        await client.bridge('moveToFolder', resource, item_id, target or APPLE_ROOT_FOLDER)

    async def folder_children(self, folder_id=None):
        """What a playlist folder holds as Apple lists it now (None or 'root': the top
        level), in its order: [{kind: 'playlist' | 'folder', id, name}], without what the
        account deleted that Apple still lists (api.is_deleted). A folder Apple answers 404
        for holds nothing."""
        apple_id = _folder(folder_id) or APPLE_ROOT_FOLDER
        try:
            children = await self.api_pages(
                f'/v1/me/library/playlist-folders/{apple_id}/children', page=100, unique=True)
        except EngineError as e:
            if e.status != 404:
                raise
            log.debug('playlist folder %s answered 404', apple_id)
            return []
        found = []
        for child in children:
            kind = {'library-playlists': 'playlist',
                    'library-playlist-folders': 'folder'}.get(child.get('type'))
            if kind is None or not child.get('id') or api.is_deleted(child):
                continue
            attributes = child.get('attributes') or {}
            found.append({'kind': kind, 'id': str(child['id']),
                          'name': str(attributes.get('name') or '')})
        return found
