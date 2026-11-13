# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's editorial groupings as pages of shelves and links: New, a
category, a grouping, a multiroom, a room, and Radio.

The groupings' tabs and elements as shelves (_grouping_parts(), _element_parts()), their
links as what the app opens (editorial_link(), element_links()), and Radio's live stations
and programmes (radio_shelves()). The standard library only.
"""

import re
from datetime import UTC, datetime

from . import api
from .banner_art import curator_banner, featured_extras
from .cache_files import STAMP_FORMAT
from .normalize import _shelf_item


def category_page(raw, cache_dir):
    """Engine.category()'s answer from a curator with its grouping and its
    playlists (a genre's, or a radio show's: its episodes, albums and
    playlists): the category's `id` and `title`, a show's `host` (its
    `showHostName`; '' for any other kind, or a show without one), its
    `banner` (curator_banner, or None), and its `shelves` — the
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
    host = str(attrs.get('showHostName') or '').strip() if attrs.get('kind') == 'Show' else ''
    return {'id': str(curator.get('id') or ''), 'title': title, 'host': host,
            'banner': curator_banner(attrs), 'shelves': shelves}


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
    return _grouping_parts(grouping, cache_dir, prefix, featured)[0]


def _grouping_parts(grouping, cache_dir, prefix, featured=False, banners=False):
    """A grouping's shelves (_grouping_shelves) and its link rows (element_links), as
    _element_parts makes them of each of its tabs' elements in turn."""
    shelves = []
    links = []
    tabs = ((grouping.get('relationships') or {}).get('tabs') or {}).get('data') or []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        children = ((tab.get('relationships') or {}).get('children') or {}).get('data') or []
        wanted = featured and not any(shelf.get('featured') for shelf in shelves)
        found, found_links = _element_parts(children, cache_dir, prefix, wanted, banners)
        shelves.extend(found)
        links.extend(found_links)
    return shelves, links


def _element_parts(elements, cache_dir, prefix, featured=False, banners=False):
    """Editorial elements (a grouping tab's, a multiroom's children) as (shelves, links):

    - shelves: each element that has a title and something in it, as `{key, title, items}`
      in Apple's order, keyed `<prefix>-<element id>` (its place without an id); with
      `featured`, the first untitled element made of other elements (the hero row) too,
      untitled and marked `featured: true`, and with `banners` that shelf's items carry
      what their banners show (featured_extras), the shelf `form: 'banners'` when one of
      them has a banner of its own;
    - links: each element with `links` (More to Explore, the genres' row) as element_links
      makes it, keyed as a shelf would be, in Apple's order."""
    shelves = []
    links = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        key = f"{prefix}-{element.get('id') or index}"
        section = element_links(element, key)
        if section is not None:
            links.append(section)
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
        if not items:
            continue
        shelf = {'key': key, 'title': shelf_title, 'items': items}
        if is_featured:
            shelf['featured'] = True
            featured = False  # one featured shelf
            if banners:
                extras = featured_extras(element)
                for item in items:
                    item.update(extras.get((item['kind'], item['id'])) or {})
                if any(item.get('banner') for item in items):
                    shelf['form'] = 'banners'
        shelves.append(shelf)
    return shelves, links


# The links of the editorial pages (README.md, "New's banners and More to Explore"): what
# each of the web player's routes opens, by the last part of the URL's path, and the query
# key (lower-cased) that names it. A collection's page names its room by fcId too.
LINK_ROUTES = {'viewroom': ('room', 'fcid'), 'viewgrouping': ('grouping', 'id'),
               'viewmultiroom': ('multiroom', 'fcid'), 'viewtop': ('charts', 'genreid')}
_COLLECTION_PATH = re.compile(r'/collection/[^/]*/id\d+$', re.IGNORECASE)


def editorial_link(link):
    """One of an editorial element's `links` ({label, url, target?}) as what the app opens,
    {title, kind, id, url}, `kind` one of

    - 'room' (`…/viewRoom?fcId=<id>`, a collection's `…/collection/<slug>/id<n>?fcId=<id>`,
      the web player's `music.apple.com/<sf>/room/<id>`): Engine.room(id), a grid of its
      contents;
    - 'grouping' (`…/viewGrouping?id=<id>`): Engine.grouping(id), a page of shelves;
    - 'multiroom' (`…/viewMultiRoom?fcId=<id>`): Engine.multiroom(id), a page of shelves;
    - 'charts' (`…/viewTop?genreId=<n>`, `music.apple.com/<sf>/charts`): the Charts page,
      `genre` the genre's id when the link names one other than Music (api.ROOT_GENRE,
      every genre's);
    - 'link' (any other https URL, and one marked `target: 'external'`): opened in the
      browser, `id` and `url` the URL.

    None without a label, or without a URL the app can open (one of the routes without its
    id, a URL that is not https)."""
    if not isinstance(link, dict):
        return None
    label = ' '.join(str(link.get('label') or '').split())
    url = str(link.get('url') or '').strip()
    if not label or not url:
        return None
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https'):
        return None
    if (host == 'apple.com' or host.endswith('.apple.com')) and link.get('target') != 'external':
        query = {key.lower(): values[0]
                 for key, values in parse_qs(parts.query).items() if values}
        path = parts.path.rstrip('/')
        route = LINK_ROUTES.get(path.rpartition('/')[2].lower())
        if route is None and _COLLECTION_PATH.search(path):
            route = LINK_ROUTES['viewroom']
        segments = path.strip('/').split('/')
        if route is None and host == 'music.apple.com' and len(segments) >= 2:
            # The web player's own pages: /<sf>/charts, /<sf>/room/<id>.
            if segments[1] == 'charts':
                return {'title': label, 'kind': 'charts', 'id': 'charts', 'url': None}
            if segments[1] == 'room' and len(segments) >= 3:
                query['fcid'] = segments[-1]
                route = LINK_ROUTES['viewroom']
        if route is not None:
            kind, name = route
            found = query.get(name, '')
            if kind == 'charts':
                answer = {'title': label, 'kind': 'charts', 'id': 'charts', 'url': None}
                if api.chart_genre(found):  # Music's own is every genre's: All Genres
                    answer['genre'] = found
                return answer
            if not api.is_editorial_id(found):
                return None
            return {'title': label, 'kind': kind, 'id': found, 'url': None}
    if parts.scheme != 'https':
        return None
    return {'title': label, 'kind': 'link', 'id': url, 'url': url}


def element_links(element, key):
    """An editorial element's row of links (kind 391, More to Explore, titled; 322, the
    genres', untitled) as {key, title, links}, each link as editorial_link() makes it, each
    once; None for an element without `links`, or none the app can open."""
    attrs = element.get('attributes') or {}
    raw = attrs.get('links')
    if not isinstance(raw, list):
        return None
    links = []
    seen = set()
    for link in raw:
        found = editorial_link(link)
        found_key = None if found is None else (found['kind'], found['id'], found.get('genre'))
        if found_key is None or found_key in seen:
            continue
        seen.add(found_key)
        links.append(found)
    if not links:
        return None
    title = str(attrs.get('title') or attrs.get('name') or '').strip()
    return {'key': key, 'title': title, 'links': links}


def editorial_shelves(raw, cache_dir):
    """`browse`'s answer from the editorial groupings behind Apple Music's
    own New page (`/v1/editorial/<storefront>/groupings` with `name=music`,
    `platform=web`): `shelves`, the grouping's editorial elements in
    Apple's order — the featured banners first as one shelf marked
    `featured` (and untitled: the page names it), each item with its banner's
    `badge`, `banner` and `tagline` (featured_extras; the shelf `form: 'banners'` when
    one has a banner), then Best New Songs, New Releases, playlists, stations, videos… —
    each `{key, title, items}` with items as `search` has them (no groups, art as it
    stands; a curator among them a category tile); and `links`, its rows of links (More
    to Explore, the genres': element_links) in Apple's order."""
    shelves = []
    links = []
    for grouping in (raw or {}).get('data') or []:
        if isinstance(grouping, dict):
            found, found_links = _grouping_parts(grouping, cache_dir, 'new', featured=True,
                                                 banners=True)
            shelves.extend(found)
            links.extend(found_links)
    return {'shelves': shelves, 'links': links}


def editorial_grouping(raw, cache_dir):
    """Engine.grouping()'s answer (`/v1/editorial/<storefront>/groupings/<id>`, a page a
    More to Explore link opens, the same shape as New's): {id, title, shelves, links} as
    editorial_shelves makes them, keyed `grp-<element id>`, `title` the grouping's name
    ('' without one)."""
    data = (raw or {}).get('data') or []
    grouping = data[0] if data and isinstance(data[0], dict) else {}
    attrs = grouping.get('attributes') or {}
    shelves, links = _grouping_parts(grouping, cache_dir, 'grp', featured=True, banners=True)
    return {'id': str(grouping.get('id') or ''),
            'title': str(attrs.get('title') or attrs.get('name') or '').strip(),
            'shelves': shelves, 'links': links}


def editorial_multiroom(raw, cache_dir):
    """Engine.multiroom()'s answer (`/v1/editorial/<storefront>/multirooms/<id>`): {id,
    title, shelves, links}, its children as a grouping's elements are (_element_parts: the
    345 shelves; the 404 header holds nothing and is left out), keyed `mr-<element id>`,
    `title` the multiroom's ('' without one)."""
    data = (raw or {}).get('data') or []
    room = data[0] if data and isinstance(data[0], dict) else {}
    attrs = room.get('attributes') or {}
    children = ((room.get('relationships') or {}).get('children') or {}).get('data') or []
    shelves, links = _element_parts(children, cache_dir, 'mr')
    return {'id': str(room.get('id') or ''),
            'title': str(attrs.get('title') or attrs.get('name') or '').strip(),
            'shelves': shelves, 'links': links}


def editorial_room(raw, cache_dir):
    """Engine.room()'s answer (`/v1/editorial/<storefront>/rooms/<id>`, a More to Explore
    link's collection): {id, title, items}, its `contents` (up to a hundred) in Apple's
    order as a shelf's items are (_shelf_item: no groups, art as it stands), each once,
    `title` the room's ('' without one)."""
    data = (raw or {}).get('data') or []
    room = data[0] if data and isinstance(data[0], dict) else {}
    attrs = room.get('attributes') or {}
    contents = ((room.get('relationships') or {}).get('contents') or {}).get('data') or []
    items = []
    seen = set()
    for raw_item in contents:
        item = _shelf_item(raw_item, cache_dir)
        if item is None or (item['kind'], item['id']) in seen:
            continue
        seen.add((item['kind'], item['id']))
        items.append(item)
    return {'id': str(room.get('id') or ''),
            'title': str(attrs.get('title') or attrs.get('name') or '').strip(),
            'items': items}


# The Radio grouping's elements the page puts apart (README.md, "The editorial groupings"): the
# hero row and the live stations, each made of children holding one item.
RADIO_HERO_KIND = '316'
RADIO_LIVE_KIND = '488'
# The least time a Radio answer is fresh for, whatever its programmes say: one whose
# programmes have all ended is not asked for again at every visit.
RADIO_MIN_AGE = 5 * 60


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
