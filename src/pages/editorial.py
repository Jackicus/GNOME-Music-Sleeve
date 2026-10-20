# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The pages More to Explore's links open (src/explore.py), pushed over the page the link
was on, each titled with the link's label and kept a day, as the other editorial pages are:

- a room (a collection: engine.room(id)): its contents as a grid, a GridPage that fetches
  (its `fetch`);
- a grouping (engine.grouping(id), New's shape) or a multiroom (engine.multiroom(id)): a
  ShelvesPage, the grouping's banners as New's are, and its own links after its shelves.

window.open_item opens them for a link's Item (kind 'room', 'grouping' or 'multiroom'); the
Charts page and a web page are the window's own (charts.py, the browser).
"""

from gettext import gettext as _

from . import app
from .shelves import ShelvesPage

ICON_NAME = 'view-grid-symbolic'


def create(library, item):
    """The page for a link's Item, by its kind; KeyError for another kind."""
    return {'room': room_page, 'grouping': grouping_page,
            'multiroom': multiroom_page}[item.kind](library, item)


def room_page(library, item):
    """A room's page: its contents as a grid of tiles."""
    from .grid import GridPage

    item_id = item.id
    page = GridPage(library, item.title, None, root=False, icon_name=ICON_NAME,
                    empty_title=_('Nothing Here'),
                    empty_description=_('This collection has nothing to show right now'),
                    fetch=lambda refresh: app().engine.room(item_id, refresh=refresh))
    page.item = item
    return page


def grouping_page(library, item):
    """A grouping's page: its shelves, then its links."""
    item_id = item.id
    page = ShelvesPage(item.title,
                       lambda refresh: app().engine.grouping(item_id, refresh=refresh),
                       root=False, icon_name=ICON_NAME, hero=False,
                       empty_title=_('Nothing Here'),
                       empty_description=_('This page has nothing to show right now'))
    page.item = item
    return page


def multiroom_page(library, item):
    """A multiroom's page: its shelves, then its links."""
    item_id = item.id
    page = ShelvesPage(item.title,
                       lambda refresh: app().engine.multiroom(item_id, refresh=refresh),
                       root=False, icon_name=ICON_NAME, hero=False,
                       empty_title=_('Nothing Here'),
                       empty_description=_('This page has nothing to show right now'))
    page.item = item
    return page
