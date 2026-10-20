# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicBannerTile: a featured shelf's wide banner card (New's, a grouping's: a
ShelfModel whose `form` is 'banners'), as Apple's New page opens: Apple's small label over
the title and a line under it, over a wide editorial image."""

import math

from gi.repository import Gio, Graphene, Gtk

from .. import remote
from ..backend import config
from . import artwork
from .util import connect_weak

# The card's width, in logical pixels: two side by side in a window of the default size. In a
# shelf too narrow for one (a phone's 360), as wide as the shelf less its insets (ROW_INSET a
# side: the list's padding, a row's margin and padding), down to MIN_WIDTH. Its image is
# 16:9 (ASPECT).
BANNER_WIDTH = 384
MIN_WIDTH = 240
ROW_INSET = 24
ASPECT = 16 / 9
# What a picture wider than this (width to height) is: a banner, cut to cover the card's
# image; anything squarer is the item's own cover, shown whole on its colour.
WIDE = 1.2


def card_width(row_width):
    """The cards' width in a shelf whose row is `row_width` logical pixels wide (0: not laid
    out yet, BANNER_WIDTH)."""
    if row_width <= 0:
        return BANNER_WIDTH
    return max(MIN_WIDTH, min(BANNER_WIDTH, row_width - 2 * ROW_INSET))


def image_height(width):
    return round(width / ASPECT)


def drawn_edge(width, aspect):
    """The shorter edge, in logical pixels, of an image of `aspect` (width to height) drawn to
    cover a card's image `width` wide: what it is decoded at (artwork.ArtworkSlot's size). A
    cover (no aspect: square) is drawn whole, as tall as the image."""
    height = image_height(width)
    if not aspect or aspect <= 0:
        return height
    return max(height, math.ceil(width / aspect))


class BannerArt(Gtk.Widget):
    """The card's image, `width` (set_width()) by image_height() whatever it shows (a
    recycled card never changes size for what it shows): the Item's banner (`banner`:
    normalize.featured_extras' dict, its file fetched for the widest card,
    remote.fetch_banner, or on disk as `art`, the demo's) cut to cover it, else its cover
    whole on its colour, until then that colour (or the card colour). Decorative: the card's
    name says what it is."""

    __gtype_name__ = 'AppleMusicBannerArt'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_css_class('banner-art')
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                   accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.picture.set_parent(self)
        self._colour = None
        self._banner = None
        self._width = BANNER_WIDTH
        self._slot = artwork.ArtworkSlot(self._set_art, image_height(BANNER_WIDTH))
        self._slot.follow_scale(self)

    def set_width(self, width):
        """The image's width (card_width()), its height following."""
        if width != self._width:
            self._width = width
            self._slot.set_size(self._edge())
            self.queue_resize()

    def _edge(self):
        return drawn_edge(self._width,
                          remote.banner_aspect(self._banner) if self._banner else None)

    def show(self, item):
        """Show the Item's banner, else its cover (None: nothing)."""
        raw = item.raw if item is not None and isinstance(item.raw, dict) else {}
        banner = raw.get('banner') if isinstance(raw.get('banner'), dict) else None
        self._banner = banner
        colour = (banner or {}).get('color') or (item.art_color if item is not None else None)
        self._colour = artwork.art_colour(colour)
        self._slot.set_size(self._edge())
        self._slot.set_paths(*self._paths(item))
        self.queue_draw()

    def _paths(self, item):
        if item is None:
            return ()
        paths = []
        if self._banner is not None:
            paths.append(self._banner.get('art'))  # on disk already: the demo's
            paths.append(remote.banner_path(self._banner, self.pixels()))
        paths += [item.art, item.thumb]
        return paths

    def pixels(self):
        """The widest image's width in device pixels: what its banner is fetched for (one
        file whatever the shelf's width)."""
        return BANNER_WIDTH * self.get_scale_factor()

    def refresh(self):
        """Look for the files again: one has arrived on disk since."""
        self._slot.refresh()

    @property
    def banner(self):
        return self._banner

    def wanted(self):
        """The banner's URL to fetch for the scale drawn at, or None (none, or on disk)."""
        if self._banner is None or self._banner.get('art'):
            return None
        return remote.banner_url(self._banner, self.pixels())

    # Its width by 16:9, the picture allocated all of it.

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation, for_size):
        size = (self._width if orientation == Gtk.Orientation.HORIZONTAL
                else image_height(self._width))
        return size, size, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self.picture.allocate(width, height, baseline, None)

    def do_map(self):
        Gtk.Widget.do_map(self)
        self._slot.map(self.get_scale_factor())

    def do_unmap(self):
        self._slot.unmap()
        Gtk.Widget.do_unmap(self)

    def _set_art(self, paintable, found):
        aspect = paintable.get_intrinsic_aspect_ratio() if found else 0
        self.picture.set_content_fit(Gtk.ContentFit.COVER if aspect > WIDE
                                     else Gtk.ContentFit.CONTAIN)
        self.picture.set_paintable(paintable)

    def do_snapshot(self, snapshot):
        # The colour under the picture (a cover shown whole sits on it), over the CSS
        # background's fallback, inside the rounded clip.
        if self._colour is not None:
            bounds = Graphene.Rect().init(0, 0, self.get_width(), self.get_height())
            snapshot.append_color(self._colour, bounds)
        Gtk.Widget.do_snapshot(self, snapshot)

    def do_dispose(self):
        if self.picture.get_parent() is not None:
            self.picture.unparent()
        Gtk.Widget.do_dispose(self)


class BannerTile(Gtk.Box):
    """A featured shelf's card: Apple's label (`badge`, "NEW ALBUM"), the title, the item's
    `tagline` (else its subtitle) over a BannerArt. bind(item) and unbind() are called by a
    list factory, as for AppleMusicTile, and the card follows its Item's notify signals
    while bound. While shown, it fetches what its image wants: the banner at the width drawn
    (remote.fetch_banner), or the item's cover when the thumbnail is too small for it
    (remote.fetch_cover), and looks again once it is there."""

    __gtype_name__ = 'AppleMusicBannerTile'

    _item = None
    _handler = None

    def __init__(self, width=BANNER_WIDTH, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         halign=Gtk.Align.START, valign=Gtk.Align.START, margin_top=6,
                         margin_bottom=6, width_request=width, **kwargs)
        self.add_css_class('banner-tile')
        # Inscriptions, as in the tiles: a rebind redraws them without a new layout. The
        # label's line is kept when there is none, so every card's image starts level.
        self.badge_label = self._line(['caption-heading', 'dimmed', 'banner-badge'])
        self.title_label = self._line(['title-4'])
        self.subtitle_label = self._line(['dimmed'])
        self.art = BannerArt(margin_top=8)
        self.art.set_width(width)
        self.append(self.art)
        # A class function, not a bound method: a handler on the card itself holding the
        # card would be a cycle.
        self.connect('notify::scale-factor', BannerTile._on_scale_factor)

    def _line(self, classes):
        line = Gtk.Inscription(xalign=0, min_lines=1, css_classes=classes,
                               text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END)
        self.append(line)
        return line

    @property
    def context_item(self):
        """The Item shown, for its context menu (widgets/context_menu.py)."""
        return self._item

    def set_width(self, width):
        """The card's width (card_width(): the shelf's), its image's height following."""
        self.set_size_request(width, -1)
        self.art.set_width(width)

    def bind(self, item):
        if self._item is not None:
            self.unbind()
        self._item = item
        # The Item outlives the card: it holds the card weakly.
        self._handler = connect_weak(item, 'notify', self._on_item_notify)
        self._show_text()
        self.art.show(item)
        if self.get_mapped():
            self._fetch()

    def unbind(self):
        if self._handler is not None:
            self._item.disconnect(self._handler)
            self._handler = None
        self._item = None
        self.art.show(None)

    def _show_text(self):
        item = self._item
        raw = item.raw if isinstance(item.raw, dict) else {}
        self.badge_label.set_text(str(raw.get('badge') or ''))
        self.title_label.set_text(item.title)
        self.subtitle_label.set_text(str(raw.get('tagline') or '') or item.subtitle)

    def do_map(self):
        Gtk.Box.do_map(self)
        if self._item is not None:
            self._fetch()

    def _on_scale_factor(self, _pspec):
        if self.get_mapped() and self._item is not None:
            self.art.show(self._item)
            self._fetch()

    def _fetch(self):
        """Fetch what the image wants and is not known to be on disk (asked in the fetch's
        thread): the banner, else the cover when the thumbnail is too small for it."""
        spawn = getattr(Gio.Application.get_default(), 'spawn', None)
        if spawn is None:
            return
        item = self._item
        if self.art.wanted() is not None:
            spawn(self._fetch_banner(item, self.art.banner, self.art.pixels()))
            return
        raw = item.raw if isinstance(item.raw, dict) else {}
        if (self.art.banner is None and item.art and raw.get('artUrl')
                and image_height(BANNER_WIDTH) * self.get_scale_factor()
                > config.THUMB_SIZE):
            spawn(self._fetch_cover(item))

    async def _fetch_banner(self, item, banner, pixels):
        if await remote.fetch_banner(banner, pixels) and self._item is item:
            self.art.refresh()

    async def _fetch_cover(self, item):
        if await remote.fetch_cover(item) and self._item is item:
            self.art.refresh()

    def _on_item_notify(self, item, pspec):
        """Follow the Item (a fetched thumbnail, new words): a list does not rebind an item
        that changed in place."""
        if pspec.name in ('title', 'subtitle'):
            self._show_text()
        elif pspec.name in ('art', 'thumb', 'art-color'):
            self.art.show(item)
            self.art.refresh()
