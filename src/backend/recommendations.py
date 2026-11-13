# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's recommendations as shelves: Home's, Made for You's, and Recently Played.

recommendation_shelves() for the sync's Home, made_for_you_shelves() for the Made for You
page, both from /v1/me/recommendations, and recently_played() from /v1/me/recent/played.
The standard library only.
"""

from .normalize import _shelf_item


def _is_made_for_you(raw_item):
    """A personal mix (Favourites Mix, Chill Mix, New Music Mix…, playlists
    of `playlistType` personal-mix) or a station: what Made for You holds."""
    if not isinstance(raw_item, dict):
        return False
    if raw_item.get('type') == 'stations':
        return True
    attrs = raw_item.get('attributes') or {}
    return raw_item.get('type') == 'playlists' and attrs.get('playlistType') == 'personal-mix'


def made_for_you_shelves(raw_recs, cache_dir=None):
    """The Made for You page from `/v1/me/recommendations`: the
    recommendations (a group's members each on their own, as
    recommendation_shelves has them) made up entirely of the personal mixes
    and stations, each a shelf titled as Apple titles it, in Apple's order;
    the rest of the recommendations (albums for you, recently played) are
    Home's, not this page's. Items as a shelf's, without their track lists.

    Shelf = {"key": "rec-<id>", "title": "…", "items": [Item]}
    """
    return _recommendation_shelves(
        raw_recs, cache_dir, accept=lambda contents: all(map(_is_made_for_you, contents)),
        settle=True)


def _recommendation_shelves(raw_recs, cache_dir, accept, settle, art_urls=None):
    """The shelves of Apple's recommendations, in Apple's order: one per
    recommendation whose contents `accept(contents)` takes, a group's members
    each a shelf of their own, its items through _shelf_item (no curators:
    a category tile is the Search page's) with `settle`; a recommendation
    with nothing in it is left out. Titled as Apple titles it (in the
    account's language), '' when it does not: the page has the words."""
    shelves = []

    def walk(rec):
        if not isinstance(rec, dict):
            return
        attrs = rec.get('attributes') or {}
        rel = rec.get('relationships') or {}
        members = (rel.get('recommendations') or {}).get('data') or []
        if members:
            for member in members:
                walk(member)
            return
        contents = [c for c in (rel.get('contents') or {}).get('data') or [] if isinstance(c, dict)]
        if not contents or not accept(contents):
            return
        items = [_shelf_item(raw_item, cache_dir, settle=settle, curators=False,
                             art_urls=art_urls) for raw_item in contents]
        items = [item for item in items if item is not None]
        if not items:
            return
        title = _display_string(attrs.get('title'))
        key = rec.get('id') or len(shelves)
        shelf = {'key': f'rec-{key}', 'title': title, 'items': items}
        reason = recommendation_reason(attrs)
        if reason:
            shelf['subtitle'] = reason
        shelves.append(shelf)

    for rec in raw_recs or []:
        walk(rec)
    return shelves


def _display_string(value):
    """An attribute Apple gives as {stringForDisplay} (or as a bare string): its text, or ''."""
    if isinstance(value, dict):
        value = value.get('stringForDisplay')
    return value if isinstance(value, str) else ''


def recommendation_reason(attrs):
    """A recommendation's `reason` (Apple's documented `reason.stringForDisplay`, in the
    account's language: why it is offered), or '' without one, or when it only says the
    title again. Home shows it under the shelf's title (its `subtitle`)."""
    attrs = attrs if isinstance(attrs, dict) else {}
    reason = ' '.join(_display_string(attrs.get('reason')).split())
    title = ' '.join(_display_string(attrs.get('title')).split())
    return reason if reason.casefold() != title.casefold() else ''


def recently_played(raw, cache_dir=None):
    """Home's Recently Played from `/v1/me/recent/played` (api.RECENT_PLAYED_ENDPOINT, the
    pages read: a list of resources, newest first): {items: [Item]}, each once (by kind and
    id), as a shelf's items are (no track lists, their artwork as a search hit's: the sync's
    files where they exist, else a small catalog URL); a curator, an editorial item or
    anything else the app has no tile for is left out."""
    items = []
    seen = set()
    for raw_item in raw if isinstance(raw, list) else []:
        item = _shelf_item(raw_item, cache_dir, settle=True, curators=False)
        if item is None or (item['kind'], item['id']) in seen:
            continue
        seen.add((item['kind'], item['id']))
        items.append(item)
    return {'items': items}


def recommendation_shelves(raw_recs, cache_dir=None, art_urls=None):
    """Apple's home page as shelves: one per recommendation, in the order
    the API sends them, titled as Apple titles it ("New Releases for You",
    "Stations for You", "More from …", a genre, a decade). A group
    recommendation is its members, each a shelf of its own. Items are
    normalised without their track lists, as a shelf's are, their artwork
    the files the sync fetches (registered in `art_urls`); what the app has
    no tile for (a curator, an editorial item) is left out, as is a
    recommendation with nothing in it.

    Shelf = {"key": "rec-<id>", "title": "…", "items": [Item]}
    """
    return _recommendation_shelves(raw_recs, cache_dir, accept=lambda contents: True,
                                   settle=False, art_urls=art_urls)
