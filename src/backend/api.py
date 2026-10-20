# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Apple Music API as the app knows it, apart from any connection to it: which ids are the
library's, the path that answers with one item, the resource type a kind is rated and added
under, the resources of one page of an answer, and Apple's error answers as an EngineError.
The standard library only; engine.py and actions.py use it.

    is_library_id('l.abc')              # True: under /v1/me/library, not the catalog
    item_endpoint('album', id, 'gb')    # '/v1/catalog/gb/albums/<id>?include=tracks,artists'
    resource_type('song', 'i.1')        # 'library-song' (the singular: callers add the "s")
    track_type('song', 'i.1')           # 'library-songs': what a playlist takes it as
    LIBRARY_ROUTES['video']             # 'music-videos': DELETE /v1/me/library/<that>/<id>
    library_twin(answer)                # the library id a relate=library read answers
    is_deleted(resource)                # a deleted playlist or folder Apple still lists
    first_related_id(answer, 'artists') # an answer's first resource's first artist's id
    page_data(answer)                   # the page's resources: its `data` list's dicts
    api_error(answer, 'search')         # EngineError('api', 'search: 404 Not Found: …',
                                        # status=404) for Apple's {errors: [...]}, else None
    lyrics_languages('ja_JP.UTF-8')     # {'lyrics': 'ja-JP', 'script': 'ja-Kana'}: what a
                                        # lyrics request asks its translations and
                                        # pronunciations in
    can_move_to_folder('playlist', 'p.1')   # whether Apple is known to take that folder move
"""

from .errors import EngineError

# Library ids ("l." albums and playlists, "p." playlists, "r." radio, "i." songs and music
# videos) live under /v1/me/library; anything else is the catalog's.
LIBRARY_PREFIXES = ('l.', 'p.', 'r.', 'i.')

# The Apple Music API's resource type for each kind an Item or a Track has (the singular: the
# bridge's rating() and addToLibrary() add the "s"), for the ratings and library writes. A
# library id takes the "library-" type. Artists have no ratings and cannot be added.
RESOURCE_TYPES = {
    'song': 'song',
    'album': 'album',
    'playlist': 'playlist',
    'station': 'station',
    'video': 'music-video',
    'musicVideo': 'music-video',
    'music-video': 'music-video',
}

# What can be removed from the library, and the type each kind goes under in the web player's
# requestDeleteFromLibrary, DELETE /v1/me/library/<type>/<library id>: the catalog type, not
# the library-… one. The same types name a catalog read of the item's library twin
# (library_twin_params).
LIBRARY_ROUTES = {
    'song': 'songs',
    'album': 'albums',
    'video': 'music-videos',
    'musicVideo': 'music-videos',
    'music-video': 'music-videos',
    'playlist': 'playlists',
}
LIBRARY_TWIN_ENDPOINT = '/v1/catalog/{storefront}'

# The New page: the editorial groupings behind music.apple.com's own (the request it makes,
# less its field selections and `format[resources]=map`, which flattens the answer).
# The playlist-folder moves Apple is known to take (src/backend/README.md): a playlist into a
# folder (checked on 2026-10-03). A move to the top level (into Apple's root folder) and a
# folder into another folder are not confirmed yet: the app offers neither, and the engine
# refuses them, until they are switched on here.
MOVE_TO_TOP_LEVEL = False
MOVE_FOLDERS = False
# The id the library calls the top level of the folders (library.ROOT_FOLDER), and Apple's.
ROOT_FOLDER = 'root'
APPLE_ROOT_FOLDER = 'p.playlistsroot'

BROWSE_ENDPOINT = '/v1/editorial/{storefront}/groupings'
BROWSE_PARAMS = {'name': 'music', 'platform': 'web', 'extend': 'editorialArtwork'}
# Made for You: the recommendations, of which the mixes and stations are kept.
RECOMMENDATIONS_ENDPOINT = '/v1/me/recommendations'
RECOMMENDATIONS_PARAMS = {'limit': 25}

# An artist's page, as music.apple.com's views-based artist page asks for it: the artist with
# every view its page shows (each answered with Apple's own title, its first page of
# resources and a `next` link where there are more) and the attributes its About reads.
# featured-release, when an artist has one, is shown in latest-release's place;
# featured-albums is "Essential Albums", more-to-hear the radio episodes about the artist,
# more-to-see the videos about them (uploaded videos and films). top-songs is 24 long, three
# rows of eight, as Apple's.
ARTIST_ENDPOINT = '/v1/catalog/{storefront}/artists/{id}'
ARTIST_VIEWS = (
    'featured-release', 'latest-release', 'top-songs', 'featured-albums', 'full-albums',
    'music-videos', 'playlists', 'radio-shows', 'singles', 'live-albums', 'compilation-albums',
    'appears-on-albums', 'more-to-hear', 'more-to-see', 'similar-artists',
)
ARTIST_PARAMS = {
    'views': ','.join(ARTIST_VIEWS),
    'extend': 'artistBio,bornOrFormed,isGroup,origin',
    'limit[artists:top-songs]': 24,
}
# One of an artist's views whole (See All), a page of it at a time.
ARTIST_VIEW_ENDPOINT = '/v1/catalog/{storefront}/artists/{id}/view/{view}'
ARTIST_VIEW_LIMIT = 100
# An album's page under its tracks, as music.apple.com's asks for it: the album with its
# artists and the views its page shows below the list (each with Apple's own title, its
# first page of resources and a `next` link where there are more), in the page's order but
# for More By, which is no view of the album's but its first artist's albums (MORE_BY_VIEW,
# a page of MORE_BY_LIMIT of them). related-videos is "Music Videos", appears-on the
# playlists the album is on ("Featured On"), related-albums "You Might Also Like".
ALBUM_ENDPOINT = '/v1/catalog/{storefront}/albums/{id}'
ALBUM_VIEWS = ('other-versions', 'related-videos', 'appears-on', 'related-albums')
ALBUM_PARAMS = {'views': ','.join(ALBUM_VIEWS), 'include': 'artists'}
# One of an album's views whole (See All), a page of it at a time.
ALBUM_VIEW_ENDPOINT = '/v1/catalog/{storefront}/albums/{id}/view/{view}'
MORE_BY_VIEW = 'full-albums'
MORE_BY_LIMIT = 30
# A catalog song with its albums: the catalog album a library album is, found through one of
# its songs (a library album carries no catalog id of its own).
SONG_ALBUMS_PARAMS = {'include': 'albums'}
# A catalog song with its artists: how a library artist, which the library makes up from its
# songs' names, finds the catalog artist it stands for.
SONG_ARTISTS_ENDPOINT = '/v1/catalog/{storefront}/songs/{id}'
SONG_ARTISTS_PARAMS = {'include': 'artists'}
# A catalog song or music video with its album and artists, or an album with its artists, by
# kind: where Go to Album and Go to Artist go when the library cannot say (Engine.related).
RELATED_ENDPOINTS = {
    'song': '/v1/catalog/{storefront}/songs/{id}',
    'video': '/v1/catalog/{storefront}/music-videos/{id}',
    'album': '/v1/catalog/{storefront}/albums/{id}',
}
RELATED_PARAMS = {
    'song': {'include': 'albums,artists'},
    'video': {'include': 'albums,artists'},
    'album': {'include': 'artists'},
}

# The script a lyric line's pronunciation (Apple's transliteration) is asked in, by the
# language of the app: music.apple.com's lyrics choose it so (`l[script]`), and Latin for a
# language not listed. A song in the script asked has no pronunciations.
PRONUNCIATION_SCRIPTS = {
    'Cyrl': ('ru', 'uk', 'bg', 'sr', 'mk', 'kk', 'ky', 'be', 'mn'),
    'Arab': ('ar', 'fa', 'ps', 'sd'),
    'Aran': ('ur',),
    'Hans': ('zh',),
    'Kana': ('ja',),
    'Hang': ('ko',),
    'Deva': ('hi', 'ne', 'mr', 'sa'),
    'Beng': ('bn',),
    'Guru': ('pa',),
    'Gujr': ('gu',),
    'Orya': ('or',),
    'Taml': ('ta',),
    'Telu': ('te',),
    'Knda': ('kn',),
    'Mlym': ('ml',),
    'Sinh': ('si',),
    'Thai': ('th',),
    'Laoo': ('lo',),
    'Khmr': ('km',),
    'Mymr': ('my',),
    'Ethi': ('am', 'ti'),
    'Geor': ('ka',),
    'Armn': ('hy',),
    'Hebr': ('he', 'yi'),
    'Grek': ('el',),
    'Tibt': ('bo',),
}
SCRIPT_OF_LANGUAGE = {language: script for script, languages in PRONUNCIATION_SCRIPTS.items()
                      for language in languages}


def lyrics_languages(locale_name):
    """What a lyrics request asks for, given the app's language as a POSIX locale name
    ('en_GB.UTF-8', 'pt_BR', 'sr@latin'; 'C', 'POSIX' or nothing are English):
    {'lyrics': the BCP 47 tag ('en-GB'), 'script': the language and the script its
    pronunciations are written in ('en-Latn'; '@latin' asks for Latin whatever the
    language)}."""
    name = str(locale_name or '')
    latin = name.endswith('@latin')
    name = name.split('@')[0].split('.')[0]
    parts = [part for part in name.replace('-', '_').split('_') if part]
    if not parts or not parts[0].isalpha() or parts[0].upper() in ('C', 'POSIX'):
        parts = ['en']
    language = parts[0].lower()
    tag = '-'.join([language] + [part.upper() for part in parts[1:2] if part.isalpha()])
    script = 'Latn' if latin else SCRIPT_OF_LANGUAGE.get(language, 'Latn')
    return {'lyrics': tag, 'script': f'{language}-{script}'}


def can_move_to_folder(kind, folder_id):
    """Whether a playlist (`kind` 'playlist') or a folder ('folder') may be moved into the
    folder `folder_id` (None, ROOT_FOLDER or Apple's root: the top level), as far as Apple is
    known to take it (MOVE_TO_TOP_LEVEL, MOVE_FOLDERS)."""
    if kind not in ('playlist', 'folder'):
        return False
    if kind == 'folder' and not MOVE_FOLDERS:
        return False
    return MOVE_TO_TOP_LEVEL or folder_id not in (None, '', ROOT_FOLDER, APPLE_ROOT_FOLDER)


def is_library_id(item_id):
    return str(item_id).startswith(LIBRARY_PREFIXES)


def item_endpoint(kind, item_id, storefront):
    """The API path that answers with one full item of `kind` (Engine.item()): library items
    under /v1/me/library, the rest under the catalog."""
    library = is_library_id(item_id)
    if kind == 'album':
        return (f'/v1/me/library/albums/{item_id}?include=tracks,artists' if library
                else f'/v1/catalog/{storefront}/albums/{item_id}?include=tracks,artists')
    if kind == 'playlist':
        return (f'/v1/me/library/playlists/{item_id}?include=tracks' if library
                else f'/v1/catalog/{storefront}/playlists/{item_id}?include=tracks')
    if kind == 'artist':
        return (f'/v1/me/library/artists/{item_id}?include=albums' if library
                else f'/v1/catalog/{storefront}/artists/{item_id}?include=albums')
    if kind == 'station':
        return f'/v1/catalog/{storefront}/stations/{item_id}'
    if kind == 'song':
        return (f'/v1/me/library/songs/{item_id}' if library
                else f'/v1/catalog/{storefront}/songs/{item_id}')
    if RESOURCE_TYPES.get(kind) == 'music-video':
        return (f'/v1/me/library/music-videos/{item_id}' if library
                else f'/v1/catalog/{storefront}/music-videos/{item_id}')
    return f'/v1/catalog/{storefront}/{kind}s/{item_id}'


def album_endpoint(album_id, storefront):
    """The API path of an album with its tracks: an artist's album, fetched for its page."""
    library = str(album_id).startswith(('l.', 'p.'))
    return (f'/v1/me/library/albums/{album_id}?include=tracks' if library
            else f'/v1/catalog/{storefront}/albums/{album_id}?include=tracks')


def first_related_id(answer, name):
    """The id of the first resource of the relationship `name` (an album's `artists`, a
    song's `albums`) of an answer's first resource, or None."""
    data = page_data(answer)
    relationships = data[0].get('relationships') if data else None
    relationship = relationships.get(name) if isinstance(relationships, dict) else None
    related = page_data(relationship)
    found = related[0].get('id') if related else None
    return str(found) if found not in (None, '') else None


def resource_type(kind, item_id):
    """The API type (singular) the ratings of `kind` `item_id` live under: 'song' or
    'library-song', 'album' or 'library-album'… EngineError('usage') for a kind with none."""
    base = RESOURCE_TYPES.get(kind)
    if base is None or item_id in (None, ''):
        raise EngineError('usage', f'no rating for {kind or "nothing"} {item_id or ""}'.strip())
    return f'library-{base}' if is_library_id(item_id) and base != 'station' else base


def is_deleted(resource):
    """Whether a library playlist or playlist folder, as a listing has it, is one the account
    deleted: Apple goes on listing it for a while (seen for minutes on 2026-10-03), with
    neither a name nor a date added, canEdit and canDelete false, and a playlist's
    lastModifiedDate the epoch. Every live one has its name."""
    attributes = resource.get('attributes') if isinstance(resource, dict) else None
    if not isinstance(attributes, dict):
        return False
    return ('name' not in attributes and 'dateAdded' not in attributes
            and attributes.get('canEdit') is False and attributes.get('canDelete') is False)


def track_type(kind, item_id):
    """The resource type (plural) a song or music video (`kind` 'song' or 'video') with that
    id is added to a playlist as: 'library-songs' for a library id, 'songs' for a catalog
    one, 'library-music-videos', 'music-videos'. None for anything else."""
    base = RESOURCE_TYPES.get(kind)
    if base not in ('song', 'music-video') or item_id in (None, ''):
        return None
    return f'{"library-" if is_library_id(item_id) else ""}{base}s'


def library_twin_params(kind, catalog_id):
    """The query of LIBRARY_TWIN_ENDPOINT that answers a catalog item with its library twin
    (relate=library), as the web player reads it before a removal: Apple answers a DELETE
    by catalog id with a 500, so the library id is found first."""
    route = LIBRARY_ROUTES[kind]
    return {f'ids[{route}]': str(catalog_id), 'relate': 'library',
            f'fields[{route}]': 'inLibrary', 'omit[resource]': 'autos'}


def library_twin(answer):
    """The library id in a library_twin_params() answer (its resource's
    `relationships.library.data[0].id`), or None when the library holds no twin."""
    for entry in page_data(answer):
        relationships = entry.get('relationships')
        library = relationships.get('library') if isinstance(relationships, dict) else None
        data = library.get('data') if isinstance(library, dict) else None
        for twin in data if isinstance(data, list) else []:
            twin_id = twin.get('id') if isinstance(twin, dict) else None
            if isinstance(twin_id, str) and is_library_id(twin_id):
                return twin_id
    return None


def page_data(answer):
    """The resources of one page: its `data` list's dicts."""
    data = answer.get('data') if isinstance(answer, dict) else None
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def api_error(answer, what):
    """Apple's answer to a failed request, `{"errors": [...]}` (MusicKit hands it back as if it
    had worked), as EngineError('api', "<what>: <status> <title>: <detail>") with the first
    error's HTTP status as its `status` (None when it gave none); None for any other answer."""
    if not isinstance(answer, dict) or not answer.get('errors'):
        return None
    errors = answer['errors']
    first = errors[0] if isinstance(errors, list) and errors else {}
    if not isinstance(first, dict):
        first = {}
    return EngineError('api', f"{what}: {first.get('status', '?')} "
                              f"{first.get('title', 'error')}: "
                              f"{first.get('detail', '')}".strip(),
                       status=http_status(first.get('status')))


def http_status(value):
    """An HTTP status as Apple writes it in an error ('404', or 404) as an int; None for
    anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 100 <= value < 600 else None
    if isinstance(value, str) and value.strip().isdigit():
        return http_status(int(value.strip()))
    return None


def is_final(error):
    """Whether a failed API read would fail the same way again: Apple's 4xx, bar 429 (too many
    requests), and a timeout (MusicKit retries the network itself). A 5xx, a 429, an error
    without a status, and a request the page itself threw on are worth another try."""
    if error.code == 'timeout':
        return True
    return error.status is not None and 400 <= error.status < 500 and error.status != 429
