# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's search answers as the Search page's shelves, suggestions and categories.

search_results() for Engine.search(), search_suggestions() for Engine.suggest(),
search_landing() for Engine.landing(). The standard library only.
"""

from . import api
from .normalize import _settle_search_art, normalize_category, normalize_item


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
