# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's charts, the catalog's genres and Replay's music summaries as ranked shelves.

charts_shelves() and catalog_genres() for the Charts page, replay_page() and its helpers for
Replay, whose shelves are a chart's (_chart_items()). The standard library only.
"""

from . import api
from .normalize import _shelf_item


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


def catalog_genres(raw, cache_dir=None):
    """`genres`' answer from the catalog's genres (`/v1/catalog/<storefront>/genres`):
    {genres: [{id, title}]}, the genres the Charts page offers, in Apple's order, each once.
    The genre the others belong to (Music, every genre's: a genre without a parent that is
    another's parent) is left out, as are a genre without a name and an id that
    api.is_genre_id refuses."""
    data = raw.get('data') if isinstance(raw, dict) else None
    resources = [entry for entry in data if isinstance(entry, dict)] if isinstance(
        data, list) else []
    parents = set()
    for resource in resources:
        parent = (resource.get('attributes') or {}).get('parentId')
        if parent is not None:
            parents.add(str(parent))
    genres = []
    seen = set()
    for resource in resources:
        attrs = resource.get('attributes') or {}
        genre_id = str(resource.get('id') or '')
        title = ' '.join(str(attrs.get('name') or '').split())
        if resource.get('type') not in (None, 'genres') or not title or genre_id in seen:
            continue
        if not api.is_genre_id(genre_id):
            continue
        if attrs.get('parentId') is None and genre_id in parents:
            continue  # Music: what the charts are without a genre
        seen.add(genre_id)
        genres.append({'id': genre_id, 'title': title})
    return {'genres': genres}


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


# Replay's views, by the name each has in the summary's `views`, in the page's order, and the
# `chart` each shelf is (the app names a shelf Apple leaves untitled by it).
REPLAY_VIEWS = (('top-songs', 'songs'), ('top-artists', 'artists'), ('top-albums', 'albums'))
# The chart of the shelf of each year's Replay playlist.
REPLAY_PLAYLISTS = 'replay-playlists'
# The relationship each view's period summaries hold their song, artist or album in, by chart.
REPLAY_WRAPS = {'songs': 'song', 'artists': 'artist', 'albums': 'album'}
# The shape a Replay answer is kept in, its `basis` (Engine.replay): a newer one makes the
# kept answers of an older shape be asked again. Bump it when replay_page reads Apple's
# answers anew.
REPLAY_SHAPE = 'replay-2'


def replay_page(raw, cache_dir):
    """`replay`'s answer from Apple's music summaries: {year, years, shelves}. `raw` is
    {summary, songs, years, year}: the summary read (`/v1/me/music-summaries` with `views`,
    a past year's `/v1/me/music-summaries/year-<YYYY>`; None when Apple had none), the
    catalog read of its top songs by id (replay_song_ids(); None without it), the years read
    (`/v1/me/music-summaries/search`; None without it) and the year asked ('' for the
    latest). `year` is the summary's (its `attributes.year`, else its id's, `year-<YYYY>`),
    else the one asked ('' when neither says); `years` every year Apple lists a Replay of,
    newest first, as strings (replay_years()). The shelves are the summary's views with
    something in them, in REPLAY_VIEWS' order, each `{key, title, items, chart, ranked}`
    keyed `replay-<chart>` (`songs`, `artists`, `albums`), titled as Apple titles the view
    ('' without one: the app names it by `chart`), the items the song, artist or album each
    of the view's period summaries holds, in rank order, as a chart's (each once, a song
    with its album's name; a song the catalog read did not answer is left out), Top Songs
    `form: 'songs'`; then, when the years read lists their playlists, one shelf of them,
    newest first (`replay-playlists`, untitled)."""
    raw = raw if isinstance(raw, dict) else {}
    summary = _first_resource(raw.get('summary'))
    year = _replay_year(summary) if summary else ''
    if not year:
        year = str(raw.get('year') or '')
    if not api.is_replay_year(year):
        year = ''
    views = summary.get('views') if summary else None
    views = views if isinstance(views, dict) else {}
    songs = {str(song.get('id')): song for song in _resources(raw.get('songs'))}
    shelves = []
    for name, chart in REPLAY_VIEWS:
        view = views.get(name)
        data = view.get('data') if isinstance(view, dict) else None
        if not isinstance(data, list):
            continue
        items = _chart_items(_replay_resources(data, REPLAY_WRAPS[chart], songs), cache_dir)
        if not items:
            continue
        title = (view.get('attributes') or {}).get('title')
        shelf = {'key': f'replay-{chart}', 'title': str(title or '').strip(), 'items': items,
                 'chart': chart, 'ranked': True}
        if chart == 'songs':
            shelf['form'] = 'songs'
        shelves.append(shelf)
    years = replay_years(raw.get('years'), cache_dir)
    playlists = [entry['playlist'] for entry in years if entry['playlist'] is not None]
    if playlists:
        shelves.append({'key': REPLAY_PLAYLISTS, 'title': '', 'items': playlists,
                        'chart': REPLAY_PLAYLISTS})
    return {'year': year, 'years': [entry['year'] for entry in years], 'shelves': shelves}


def replay_song_ids(summary):
    """The catalog ids of a Replay summary's top songs, in rank order, each once: the songs
    its `top-songs` period summaries hold as an id alone (`relationships.song.data[0]`, no
    attributes), which the catalog is asked for (api.replay_songs_params)."""
    resource = _first_resource(summary)
    views = resource.get('views') if resource else None
    view = views.get('top-songs') if isinstance(views, dict) else None
    data = view.get('data') if isinstance(view, dict) else None
    found = []
    for entry in _replay_resources(data if isinstance(data, list) else [], 'song', None):
        song_id = str(entry.get('id') or '')
        if not entry.get('attributes') and song_id.isdigit() and song_id not in found:
            found.append(song_id)
    return found


def _replay_resources(data, wraps, songs):
    """The resources a Replay view's items stand for, in rank order: each period summary's
    (`<kind>-period-summaries`) `relationships.<wraps>.data[0]`, an item of another type as
    it is. With `songs` (the catalog's songs by id), a song Apple gives as its id alone is
    the catalog's, and left out when the catalog did not answer it."""
    found = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if str(entry.get('type') or '').endswith('-period-summaries'):
            related = entry.get('relationships')
            related = related.get(wraps) if isinstance(related, dict) else None
            entry = next(iter(_resources(related)), None)
            if entry is None:
                continue
        if songs is not None and entry.get('type') == 'songs' and not entry.get('attributes'):
            entry = songs.get(str(entry.get('id')))
            if entry is None:
                continue
        found.append(entry)
    return found


def _replay_year(resource):
    """A music summary's year, a string: its `attributes.year`, else its id's (`year-<YYYY>`),
    else ''."""
    year = str((resource.get('attributes') or {}).get('year') or '')
    if not year:
        year = str(resource.get('id') or '').removeprefix('year-')
    return year if api.is_replay_year(year) else ''


def _resources(answer):
    """The resources (dicts) of an answer's `data`, in order."""
    data = answer.get('data') if isinstance(answer, dict) else None
    return [resource for resource in data if isinstance(resource, dict)] if isinstance(
        data, list) else []


def replay_years(raw, cache_dir=None):
    """The years Apple lists a Replay of (`/v1/me/music-summaries/search?period=year` with
    `include[music-summaries]=playlist`: a `music-summaries` resource a year, id
    `year-<YYYY>`), newest first, each once: [{year, playlist}], `year` a string
    (api.is_replay_year; its `attributes.year`, else its id's), `playlist` the year's Replay
    playlist as a shelf item (its `relationships.playlist`, with its attributes in the
    answer), or None. A summary of another period than a year is left out."""
    data = raw.get('data') if isinstance(raw, dict) else None
    found = {}
    for resource in data if isinstance(data, list) else []:
        if not isinstance(resource, dict):
            continue
        attrs = resource.get('attributes') or {}
        if attrs.get('period') not in (None, 'year'):
            continue
        year = _replay_year(resource)
        if not year or year in found:
            continue
        playlist = None
        related = ((resource.get('relationships') or {}).get('playlist') or {}).get('data')
        for entry in related if isinstance(related, list) else []:
            if isinstance(entry, dict) and entry.get('type') in ('playlists',
                                                                   'library-playlists'):
                playlist = _shelf_item(entry, cache_dir, curators=False)
                if playlist is not None:
                    break
        found[year] = {'year': year, 'playlist': playlist}
    return [found[year] for year in sorted(found, reverse=True)]


def _first_resource(answer):
    """The first resource (a dict) of an answer's `data`, or None."""
    data = answer.get('data') if isinstance(answer, dict) else None
    for resource in data if isinstance(data, list) else []:
        if isinstance(resource, dict):
            return resource
    return None
