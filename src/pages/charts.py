# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Charts page: Apple Music's charts of the account's storefront (engine.charts()) as
shelves, in music.apple.com's order: Top Songs as a numbered list of songs (a SongShelf,
which plays them as one queue from the song activated), Top Albums and Top Playlists as
numbered tiles, the Daily Top 100 and City Charts as playlist tiles that open their pages,
and Top Music Videos, numbered. A ShelvesPage pushed over the page it was opened from, not a
destination: as on music.apple.com, it is reached from New (More to Explore, new.py) and
from Search's Browse Categories, through the Top Charts tile (charts_item(), which
window.open_item opens). Kept a day, as the other editorial pages are.
"""

from gettext import gettext as _

from ..library import Item
from . import app
from .shelves import ShelvesPage

# The Charts page's Item: what its tiles show and the window's double-push guard compares.
KIND = 'charts'
ICON_NAME = 'view-list-ordered-symbolic'


def charts_item():
    """The Item a Top Charts tile shows and window.open_item opens (kind 'charts'): a
    category tile's shape, without artwork."""
    return Item({'id': KIND, 'kind': KIND, 'title': _('Top Charts'), 'subtitle': None,
                 'art': None, 'thumb': None, 'artColor': None, 'url': None, 'play': {},
                 'groups': []})


def create(item):
    """The Charts page, pushed for `item` (charts_item()'s)."""
    page = ShelvesPage(item.title, lambda refresh: app().engine.charts(refresh=refresh),
                       root=False, icon_name=ICON_NAME, hero=False,
                       empty_title=_('No Charts'),
                       empty_description=_('Apple Music has no charts to show right now'))
    page.item = item
    return page
