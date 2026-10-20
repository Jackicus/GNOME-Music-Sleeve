# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicArtistBanner: the wide image at the top of an artist's page, under a scrim."""

import math

from gi.repository import Adw, Gio, GLib, Graphene, Gtk

from .. import remote
from . import artwork
from .util import connect_weak

# The banner's height, in logical pixels, for its width: the width over remote.BANNER_ASPECT
# (the shape a `vf` cut is fetched at), no lower than MIN_HEIGHT (a phone's 360 px shows the
# middle of the image) and no higher than MAX_HEIGHT (a maximized window keeps room for the
# top songs). What is drawn over it may make it taller still (the page measures both).
MIN_HEIGHT = 240
MAX_HEIGHT = 440
# The image fades in over this long once it has decoded.
FADE_MS = 250


def banner_height(width):
    """The banner's height for a width, both in logical pixels."""
    if width <= 0:
        return MIN_HEIGHT
    return max(MIN_HEIGHT, min(MAX_HEIGHT, round(width / remote.BANNER_ASPECT)))


def drawn_edge(width, height, aspect):
    """The shorter edge, in logical pixels, of an image of `aspect` (width to height) drawn to
    cover a width x height box: what it is decoded at (artwork.ArtworkSlot's size)."""
    if width <= 0 or height <= 0 or aspect <= 0:
        return 0
    return max(height, math.ceil(width / aspect))


class ArtistBanner(Gtk.Widget):
    """The artist's banner (normalize.artist_banner's dict, set_banner()) filling the width it
    is given, as tall as banner_height() says, the image cut to cover it (centred). Until the
    image is there, Apple's colour for it (or the card colour, style.css's `.artist-banner`)
    holds its place, so nothing moves when it comes; then it fades in. A scrim (style.css's
    `.banner-scrim`), dark at the foot, keeps white text drawn over its lower part readable
    in either colour scheme, whatever the image.

    The image is fetched for the width allocated times the scale factor
    (remote.fetch_banner, into remote-art/, in steps: a wider window asks again, a narrower
    one keeps what it has), while the banner is mapped, and decoded off the main thread by an
    artwork.ArtworkSlot at the size it is drawn; a banner dict with `art`, a file on disk
    (the demo's invented banners), shows that instead. Decorative: the page's title names
    the artist."""

    __gtype_name__ = 'AppleMusicArtistBanner'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_css_class('artist-banner')
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True,
                                   accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.picture.set_opacity(0)
        self.picture.set_parent(self)
        self.scrim = Gtk.Box(can_target=False, css_classes=['banner-scrim'])
        self.scrim.set_parent(self)
        self._banner = None  # the banner dict shown
        self._colour = None  # its colour, a Gdk.RGBA, or None
        self._paths = []  # the files fetched for it, the widest first
        self._asked = 0  # the widest width (pixels) asked for it
        self._shown = False  # its image has faded in
        self._fade = None
        self._idle = None  # the idle that follows a new allocation
        self._allocated = (0, 0)
        self._slot = artwork.ArtworkSlot(self._set_art, 0)
        self._slot.follow_scale(self)
        # A class function, not a bound method: a handler on the widget holding it is a cycle.
        self.connect('notify::scale-factor', ArtistBanner._on_scale_factor)

    @property
    def banner(self):
        return self._banner

    def set_banner(self, banner):
        """Show this banner dict (or none): its colour at once, its image once fetched."""
        if banner == self._banner:
            return
        self._banner = banner
        self._colour = artwork.art_colour(banner.get('color')) if banner else None
        # A banner on disk already (the demo's invented ones, as `art`) is shown as it is.
        art = banner.get('art') if banner else None
        self._paths = [art] if art else []
        self._asked = 0
        self._shown = False
        if self._fade is not None:
            self._fade.skip()
        self.picture.set_opacity(0)
        self._slot.set_paths(*self._paths)
        self._update_size()
        self.queue_draw()

    # Layout: as wide as given, banner_height() tall.

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 0, 0, -1, -1
        height = banner_height(for_size)
        return height, height, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self.picture.allocate(width, height, baseline, None)
        self.scrim.allocate(width, height, baseline, None)
        if (width, height) != self._allocated:
            self._allocated = (width, height)
            # Not from inside the allocation: the slot may hand the picture a new paintable.
            if self._idle is None:
                self._idle = GLib.idle_add(self._on_allocated)

    def _on_allocated(self):
        self._idle = None
        self._update_size()
        return GLib.SOURCE_REMOVE

    def _update_size(self):
        """Decode at the size drawn; fetch for the width allocated, when mapped."""
        width, height = self._allocated
        banner = self._banner
        aspect = remote.banner_aspect(banner) if banner else remote.BANNER_ASPECT
        self._slot.set_size(drawn_edge(width, height, aspect))
        if banner and self.get_mapped() and width > 0:
            self._want(width * self.get_scale_factor())

    def _want(self, pixels):
        if not self._banner.get('url'):
            return  # nothing to fetch: the demo's, on disk
        wanted = remote.banner_size(self._banner, pixels)[0]
        if wanted <= self._asked:
            return
        self._asked = wanted
        app = Gio.Application.get_default()
        spawn = getattr(app, 'spawn', None)
        if spawn is not None:
            spawn(self._fetch(self._banner, pixels))

    async def _fetch(self, banner, pixels):
        path = await remote.fetch_banner(banner, pixels)
        if path is None or banner is not self._banner or path in self._paths:
            return
        self._paths.insert(0, path)  # each fetch is wider than the one before
        self._slot.set_paths(*self._paths)

    def do_map(self):
        Gtk.Widget.do_map(self)
        self._slot.map(self.get_scale_factor())
        self._update_size()

    def do_unmap(self):
        self._slot.unmap()
        Gtk.Widget.do_unmap(self)

    def _on_scale_factor(self, _pspec):
        self._update_size()

    def _set_art(self, paintable, found):
        self.picture.set_paintable(paintable)
        if not found or self._shown:
            return
        self._shown = True
        if not self.get_mapped():
            self.picture.set_opacity(1)
            return
        if self._fade is None:
            self._fade = Adw.TimedAnimation.new(
                self, 0, 1, FADE_MS, Adw.PropertyAnimationTarget.new(self.picture, 'opacity'))
            self._fade.set_easing(Adw.Easing.EASE_OUT_CUBIC)
            connect_weak(self._fade, 'done', self._on_faded)
        self._fade.play()

    def _on_faded(self, _animation):
        self.picture.set_opacity(1 if self._shown else 0)

    def do_snapshot(self, snapshot):
        # Apple's colour for the image, under it (and under the CSS background's fallback).
        if self._colour is not None:
            bounds = Graphene.Rect().init(0, 0, self.get_width(), self.get_height())
            snapshot.append_color(self._colour, bounds)
        Gtk.Widget.do_snapshot(self, snapshot)

    def do_dispose(self):
        if self._idle is not None:
            GLib.source_remove(self._idle)
            self._idle = None
        for child in (self.picture, self.scrim):
            if child.get_parent() is not None:
                child.unparent()
        Gtk.Widget.do_dispose(self)
