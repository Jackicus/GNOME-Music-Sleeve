# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The New destination: Apple Music's editorial New page (engine.browse(): the featured
banners, Best New Songs, New Releases, playlists, stations, videos) as shelves, then More to
Explore, the way on to the Charts page (a Top Charts tile: pages/charts.py), as Apple's New
page ends with its links."""

from gettext import gettext as _

from gi.repository import Gtk, Pango

from ..widgets.category_tile import CategoryTile
from ..widgets.labels import accessible_label, flow_child
from . import app
from .charts import charts_item
from .shelves import ShelvesPage


def create(destination):
    page = ShelvesPage(destination.title, lambda refresh: app().engine.browse(refresh=refresh),
                       icon_name=destination.icon_name, hero=True,
                       empty_title=_('Nothing New'),
                       empty_description=_('Apple Music has nothing new to show right now'))
    page.shelves_box.append(more_to_explore())
    return page


def more_to_explore():
    """More to Explore: a heading over a flow box of category tiles, Top Charts, after the
    shelves (the page's ShelfColumn keeps its shelves before it). Its handler holds nothing
    of the page."""
    tiles = Gtk.FlowBox(homogeneous=True, selection_mode=Gtk.SelectionMode.NONE,
                        activate_on_single_click=True, min_children_per_line=2,
                        max_children_per_line=6, column_spacing=12, row_spacing=12,
                        valign=Gtk.Align.START, margin_start=24, margin_end=24)
    item = charts_item()
    tile = CategoryTile()
    tile.bind(item)
    tiles.append(flow_child(tile, accessible_label(item)))
    tiles.connect('child-activated', _on_activated, item)
    # Translators: the heading of the New page's last section: links to other pages of
    # Apple Music (Top Charts), as music.apple.com's New page ends.
    heading = _('More to Explore')
    title = Gtk.Label(label=heading, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                      margin_start=24, margin_end=24, css_classes=['title-2'])
    tiles.update_property([Gtk.AccessibleProperty.LABEL], [heading])
    section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    section.append(title)
    section.append(tiles)
    return section


def _on_activated(flow_box, _child, item):
    flow_box.get_root().open_item(item)
