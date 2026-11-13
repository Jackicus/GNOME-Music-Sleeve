# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The rest of an item's page beyond its tracks: an artist's page, an album's and a
catalog playlist's shelves, a song's related items, credits and suggested songs.

artist_page(), album_page() and playlist_page() with their views' items, related(),
song_credits() and playlist_suggestions(). Items are shaped as a search's are
(normalize._shelf_item). The standard library only.
"""

from . import api
from .banner_art import artist_banner
from .normalize import (
    RELEASE_DATE,
    _link_item,
    _settle_search_art,
    _shelf_item,
    curator_link,
    in_favourites,
    normalize_artist,
    normalize_curator,
    strip_html,
)


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


# ---------------------------------------------------------------------------
# An album's page under its tracks
# ---------------------------------------------------------------------------

# The shelves under an album's tracks, in the order music.apple.com shows them: its views
# (api.ALBUM_VIEWS), titled as Apple titles them, and More By, its first artist's albums,
# which the app titles ("More By <artist>").
ALBUM_SHELVES = ('other-versions', 'related-videos', 'more-by-artist', 'appears-on',
                 'you-might-also-like')
MORE_BY = 'more-by-artist'


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


# ---------------------------------------------------------------------------
# A catalog playlist's page under its tracks
# ---------------------------------------------------------------------------

# The shelves under a catalog playlist's tracks, in the order music.apple.com shows them:
# its views (api.PLAYLIST_VIEWS), titled as Apple titles them.
PLAYLIST_SHELVES = ('featured-artists', 'more-by-curator', 'you-might-also-like')


def playlist_page(raw, cache_dir):
    """The rest of a catalog playlist's page (Engine.playlist_page()'s answer, from
    {playlist: api.PLAYLIST_ENDPOINT's answer, curatorPlaylists: a page of its Apple
    curator's playlists, api.CURATOR_PLAYLISTS_ENDPOINT's, or None}), as
    {id, curator, shelves}:

    - `id`: the catalog playlist's id.
    - `curator`: who made it, for the link under its title (playlist_curator()): an Apple
      curator's category tile (its page is the category page), a third party's or a shared
      playlist's listener's `link` (their page on music.apple.com), or None.
    - `shelves`: [{key, title, items, more}] in PLAYLIST_SHELVES's order, titled as Apple
      titles the views ('' without a title: the app names it), `more` True when Apple has
      more than it sent. More By the curator is the curator's playlists (Apple sends its
      view empty) unless the view holds some. The curator's playlists and those like it
      leave the playlist itself out; a shelf with nothing the app can show is left out.

    Items are shaped as a search's are (_shelf_item: an artist, a playlist with its
    curator)."""
    raw = raw if isinstance(raw, dict) else {}
    playlist = raw.get('playlist')
    data = playlist.get('data') if isinstance(playlist, dict) else None
    resource = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    attrs = resource.get('attributes') if isinstance(resource.get('attributes'), dict) else {}
    playlist_id = str(resource.get('id') or '')
    views = resource.get('views') if isinstance(resource.get('views'), dict) else {}
    found = {}
    for name, view in views.items():
        if name not in PLAYLIST_SHELVES or not isinstance(view, dict):
            continue
        title = (view.get('attributes') or {}).get('title')
        found[name] = {'key': name, 'title': title.strip() if isinstance(title, str) else '',
                       'items': playlist_view_items(view.get('data'), playlist_id, cache_dir),
                       'more': bool(view.get('next'))}
    more_by = found.get('more-by-curator')
    curator_playlists = raw.get('curatorPlaylists')
    if (playlist_id and isinstance(curator_playlists, dict)
            and (more_by is None or not more_by['items'])):
        found['more-by-curator'] = {
            'key': 'more-by-curator', 'title': more_by['title'] if more_by else '',
            'items': playlist_view_items(curator_playlists.get('data'), playlist_id,
                                         cache_dir),
            'more': bool(curator_playlists.get('next'))}
    curator_name = attrs.get('curatorName') if isinstance(attrs.get('curatorName'), str) else ''
    return {
        'id': playlist_id,
        'curator': playlist_curator(resource, curator_name.strip()),
        'shelves': [found[name] for name in PLAYLIST_SHELVES
                    if name in found and found[name]['items']],
    }


def playlist_curator(resource, name=''):
    """Who made a catalog playlist, from its `curator` relationship (`include=curator`): an
    Apple curator (`apple-curators`) as its category tile (normalize_curator) titled with its
    whole name, not a tile's short one (named `name`, the playlist's curatorName, when Apple
    sent its id alone), a third party (`curators`) or a shared playlist's listener
    (`social-profiles`) as a `link` to their page on music.apple.com (curator_link); None for
    anything else, one with no id, or one of those without an https page."""
    relationships = resource.get('relationships') if isinstance(resource, dict) else None
    curator = relationships.get('curator') if isinstance(relationships, dict) else None
    data = curator.get('data') if isinstance(curator, dict) else None
    raw = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    if not str(raw.get('id') or ''):
        return None
    if raw.get('type') == 'apple-curators':
        item = normalize_curator(raw)
        if item is None:
            if not name:
                return None
            item = {'id': str(raw['id']), 'kind': 'category', 'title': name, 'subtitle': None,
                    'art': None, 'artColor': None, 'url': None}
        full = str((raw.get('attributes') or {}).get('name') or '').strip()
        if full:  # the page the link opens is titled with the whole name, not a tile's
            item.update(title=full, subtitle=None)
        return item
    if raw.get('type') in ('curators', 'social-profiles'):
        item = curator_link(raw)
        return item if item['kind'] == 'link' else None
    return None


def playlist_view_items(resources, playlist_id, cache_dir):
    """The Items of one of a playlist's views whole (See All), or of its curator's playlists,
    as playlist_page() has them: the playlist itself left out (none without a
    `playlist_id`), what the app cannot show too."""
    items = []
    for resource in resources if isinstance(resources, list) else []:
        item = _shelf_item(resource, cache_dir, curators=False)
        if item is not None and not (playlist_id and str(playlist_id) in (
                item['id'], item.get('catalogId'))):
            items.append(item)
    return items
