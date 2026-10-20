# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Charts page: Apple Music's charts of the account's storefront (engine.charts()) as
shelves, in music.apple.com's order: Top Songs as a numbered list of songs (a SongShelf,
which plays them as one queue from the song activated), Top Albums and Top Playlists as
numbered tiles, the Daily Top 100 and City Charts as playlist tiles that open their pages,
and Top Music Videos, numbered. A ShelvesPage pushed over the page it was opened from, not a
destination: as on music.apple.com, it is reached from New (More to Explore: Top Charts,
or Apple's own link to the charts, src/explore.py) and from Search's Browse Categories,
through the Top Charts tile (explore.charts_item(), which window.open_item opens). Kept a
day, as the other editorial pages are.
"""

from gettext import gettext as _

from ..explore import CHARTS_KIND as KIND
from ..explore import charts_item
from . import app
from .shelves import ShelvesPage

__all__ = ('ICON_NAME', 'KIND', 'charts_item', 'create')

ICON_NAME = 'view-list-ordered-symbolic'


def create(item):
    """The Charts page, pushed for `item` (charts_item()'s, or a link's to the charts,
    titled as Apple labels it)."""
    page = ShelvesPage(item.title, lambda refresh: app().engine.charts(refresh=refresh),
                       root=False, icon_name=ICON_NAME, hero=False,
                       empty_title=_('No Charts'),
                       empty_description=_('Apple Music has no charts to show right now'))
    page.item = item
    return page
