# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""More to Explore's rows (src/explore.py's Sections): each a heading over a flow box of
links, every link a card with its label and a chevron (an arrow out of the window for a web
page), which opens what it names through window.open_item: a room's grid, a grouping's or
multiroom's shelves, the Charts page, or the browser.

    box = ExploreBox()                # a page's, after its shelves
    box.show_sections(sections)       # again only when they changed (explore.same_links)

The flow boxes' handler is a module function and the cards hold only their Items: a page
that drops the box frees it.
"""

from gettext import gettext as _

from gi.repository import Gtk, Pango

from .. import explore

# The narrowest a link's card is, in pixels: the flow box puts as many on a line as fit
# (MAX_PER_LINE at most), one under another at a phone's width.
LINK_WIDTH = 220
MAX_PER_LINE = 4


class LinkChild(Gtk.FlowBoxChild):
    """A link's card: its label and a chevron (an external link's arrow for a web page),
    named by the label. A Python class of its own: its `item` stays with the widget."""

    def __init__(self, item):
        super().__init__(css_classes=['card', 'activatable', 'explore-link'],
                         width_request=LINK_WIDTH)
        self.item = item
        box = Gtk.Box(spacing=12)
        box.append(Gtk.Label(label=item.title, xalign=0, hexpand=True,
                             ellipsize=Pango.EllipsizeMode.END))
        icon = ('adw-external-link-symbolic' if item.kind == 'link' else 'go-next-symbolic')
        box.append(Gtk.Image(icon_name=icon, accessible_role=Gtk.AccessibleRole.PRESENTATION))
        self.set_child(box)
        self.update_property([Gtk.AccessibleProperty.LABEL], [item.title])
        if item.kind == 'link':
            # Translators: said of a link in More to Explore that opens a web page.
            self.update_property([Gtk.AccessibleProperty.DESCRIPTION],
                                 [_('Opens in the web browser')])


def section_widget(section):
    """One Section: its heading (none for an untitled row) over a flow box of its links."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    if section.title:
        box.append(Gtk.Label(label=section.title, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                             margin_start=24, margin_end=24, css_classes=['title-2']))
    links = Gtk.FlowBox(homogeneous=True, selection_mode=Gtk.SelectionMode.NONE,
                        activate_on_single_click=True, min_children_per_line=1,
                        max_children_per_line=MAX_PER_LINE, column_spacing=12,
                        row_spacing=12, valign=Gtk.Align.START, margin_start=24,
                        margin_end=24)
    # Translators: the accessible name of a row of links without a heading of its own on
    # the New page (Apple's genres).
    links.update_property([Gtk.AccessibleProperty.LABEL], [section.title or _('Links')])
    for item in section.items:
        links.append(LinkChild(item))
    links.connect('child-activated', _on_activated)
    box.append(links)
    return box


def _on_activated(_flow_box, child):
    root = child.get_root()
    if root is not None:
        root.open_item(child.item)


class ExploreBox(Gtk.Box):
    """A page's rows of links, one under another (show_sections()); hidden while it has
    none."""

    __gtype_name__ = 'AppleMusicExploreBox'

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, visible=False,
                         **kwargs)
        self._sections = []

    @property
    def sections(self):
        return self._sections

    def show_sections(self, sections):
        """Show these Sections (src/explore.py), in place of the ones shown, unless they
        show the same links."""
        sections = list(sections or [])
        if explore.same_links(self._sections, sections) and self.get_first_child() is not None:
            self._sections = sections
            return
        child = self.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.remove(child)
            child = following
        for section in sections:
            self.append(section_widget(section))
        self._sections = sections
        self.set_visible(bool(sections))
