# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The New destination: Apple Music's editorial New page (engine.browse()) as shelves: the
featured banners first (wide banner cards, each with Apple's label over its title, where the
answer has their editorial artwork: widgets.banner_tile), Best New Songs, New Releases,
playlists, stations, videos; then More to Explore, Apple's links to its collections, pages
and charts (src/explore.py, widgets/explore.py, the pages they open: pages/editorial.py),
with Top Charts among them (the Charts page, pages/charts.py) when Apple's have no way there,
as Apple's New page ends with its links."""

from gettext import gettext as _

from .. import explore
from . import app
from .shelves import ShelvesPage


def create(destination):
    return ShelvesPage(destination.title, lambda refresh: app().engine.browse(refresh=refresh),
                       icon_name=destination.icon_name, hero=True,
                       empty_title=_('Nothing New'),
                       empty_description=_('Apple Music has nothing new to show right now'),
                       explore=lambda links: explore.sections(links, charts=True))
