# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""More to Explore: the rows of links Apple's editorial pages end with (the engine's `links`:
normalize.element_links), as the Items the window opens and the sections a page shows. No
GTK here (widgets/explore.py draws them).

    sections(answer.get('links'))            # [Section(key, title, items)] in Apple's order
    sections(links, charts=True)             # New's: Top Charts among them
    link_item(link)                          # one link as an Item: window.open_item opens it
    charts_item()                            # the Top Charts tile's and link's Item

A link is a room (a grid of its contents: Engine.room), a grouping or a multiroom (a page of
shelves: Engine.grouping, Engine.multiroom), the Charts page (`charts`, under Apple's label)
or a web page (`link`, opened in the browser). An untitled row (Apple's genres) keeps no
heading.
"""

from collections import namedtuple
from gettext import gettext as _

from .library import Item

# What a link opens, by its kind (normalize.editorial_link's); window.PAGE_KINDS has those
# with a page of their own.
LINK_KINDS = ('room', 'grouping', 'multiroom', 'charts', 'link')
# The key of the section New makes for Top Charts when Apple's links have no titled row.
EXPLORE_KEY = 'explore'
# The Charts page's Item kind (pages/charts.py): what its tiles show and the window's
# double-push guard compares.
CHARTS_KIND = 'charts'

Section = namedtuple('Section', ('key', 'title', 'items'))


def charts_item():
    """The Item a Top Charts tile or link shows and window.open_item opens (kind 'charts'): a
    category tile's shape, without artwork."""
    return Item({'id': CHARTS_KIND, 'kind': CHARTS_KIND, 'title': _('Top Charts'),
                 'subtitle': None, 'art': None, 'thumb': None, 'artColor': None, 'url': None,
                 'play': {}, 'groups': []})


def link_item(link):
    """A link dict ({title, kind, id, url}) as an Item the window opens, or None for one of
    a kind it does not know, or without a title or an id."""
    if not isinstance(link, dict) or link.get('kind') not in LINK_KINDS:
        return None
    title = str(link.get('title') or '').strip()
    item_id = str(link.get('id') or '')
    if not title or not item_id:
        return None
    data = {'id': item_id, 'kind': link['kind'], 'title': title, 'subtitle': None,
            'art': None, 'thumb': None, 'artColor': None, 'url': link.get('url'), 'play': {},
            'groups': []}
    if link['kind'] == CHARTS_KIND and link.get('genre'):
        data['genre'] = str(link['genre'])
    return Item(data)


def sections(links, charts=False):
    """The engine's rows of links ([{key, title, links}]) as Sections of Items (link_item;
    a row left with none is left out), in Apple's order. With `charts` (New's), Top Charts
    (charts_item()) leads the first titled row when no link opens the charts, or makes a
    More to Explore row of its own, first, when no row is titled."""
    found = []
    for row in links or []:
        if not isinstance(row, dict):
            continue
        items = [item for item in (link_item(link) for link in row.get('links') or [])
                 if item is not None]
        if items:
            found.append(Section(str(row.get('key') or ''), str(row.get('title') or ''),
                                 items))
    if charts and not any(item.kind == CHARTS_KIND for section in found
                          for item in section.items):
        found = _with_charts(found)
    return found


def _with_charts(found):
    item = charts_item()
    for position, section in enumerate(found):
        if section.title:
            found = list(found)
            found[position] = section._replace(items=[item, *section.items])
            return found
    # Translators: the heading of the New page's links to other pages of Apple Music (Top
    # Charts, its collections), as music.apple.com's New page ends.
    return [Section(EXPLORE_KEY, _('More to Explore'), [item]), *found]


def same_links(old, new):
    """Whether two lists of Sections show the same links: a page keeps the widgets it has
    for them."""
    def shape(found):
        return [(section.key, section.title,
                 [(item.kind, item.id, item.title) for item in section.items])
                for section in found]
    return shape(old or []) == shape(new or [])
