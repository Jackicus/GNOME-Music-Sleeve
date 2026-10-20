# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicArtworkBackdrop: the item playing's artwork, blurred, as a background.

One widget for both places that colour themselves from the artwork, over the same fields
(artwork.field_for(): the cover shrunk and blurred in a thread, kept for the last few
covers, so the sheet and the full-screen player share them):

- the full-screen player's (widgets/fullscreen_player.py, `tint` false): the field stretched
  over the view on libadwaita's dark window colour (BASE), under a black scrim deep enough
  for its white text (artwork.scrim_alpha());
- the Now Playing sheet's (widgets/now_playing.py, `tint` true): the field drawn faintly
  over the widget's own CSS background, the sheet's colour (style.css's
  .artwork-backdrop.tint, which also sets the widget's `color` to it, so the backdrop knows
  the colour it draws over), at the opacity Field.tint_for() finds for that colour and the
  sheet's text colour (its parent's `color`): the most, up to artwork.TINT_MAX, at which the
  sheet's labels keep reading at WCAG AA (artwork.tint_alpha()); none at all with the
  high-contrast setting, or when no opacity will do. The colours are read as it draws, so
  a change of colour scheme draws it again at that scheme's opacity.

show_field() crossfades from the field shown to another (FADE_MS, an Adw.TimedAnimation:
at once with animations off); show_artwork(path) awaits the field for a cover file first,
the last call winning. The backdrop is its own widget, under the content, so the lyrics'
redraws over it never draw it again.
"""

from gi.repository import Adw, Gdk, GObject, Graphene, Gsk, Gtk

from . import artwork
from .util import weak_method

FADE_MS = 400               # a new item's field crossfading in
# Under the full-screen field (and alone, without artwork): libadwaita's dark window colour,
# so the white text reads with no artwork.
BASE = Gdk.RGBA()
BASE.parse('#222226')


def _rgb(rgba):
    """A Gdk.RGBA as an (r, g, b) tuple, rounded so that one colour is one key."""
    return (round(rgba.red, 4), round(rgba.green, 4), round(rgba.blue, 4))


class ArtworkBackdrop(Gtk.Widget):
    """A field (artwork.Field) stretched over the widget, as a tint or under a scrim. See the
    module."""

    __gtype_name__ = 'AppleMusicArtworkBackdrop'

    tint = GObject.Property(type=bool, default=False, nick='Tint',
                            blurb="Faintly over the widget's own background, as far as the "
                                  'text over it reads; else on BASE under a scrim')

    def __init__(self, **kwargs):
        super().__init__(can_target=False, accessible_role=Gtk.AccessibleRole.PRESENTATION,
                         **kwargs)
        self.add_css_class('artwork-backdrop')
        self.connect('notify::tint', lambda *_: self._on_tint())
        self._on_tint()  # set while constructed, before the handler
        self.field = None
        self._previous = None
        self._mix = 1.0
        self._wanted = None      # the cover path the last show_artwork() asked for
        self._animation = Adw.TimedAnimation(
            widget=self, value_from=0.0, value_to=1.0, duration=FADE_MS,
            easing=Adw.Easing.EASE_OUT_CUBIC,
            target=Adw.CallbackAnimationTarget.new(weak_method(self._on_fade)))

    def _on_tint(self):
        if self.tint:
            self.add_css_class('tint')
        else:
            self.remove_css_class('tint')
        self.queue_draw()

    def show_field(self, field):
        """Show `field` (an artwork.Field, or None for none), crossfading from the one
        shown."""
        if field is self.field:
            return
        self._previous, self.field = self.field, field
        self._animation.reset()
        self._animation.play()

    async def show_artwork(self, path):
        """Show the field of the cover file at `path` (None: none), once it is made (in a
        thread, with its tint for the colours shown now), unless another call has come
        since."""
        self._wanted = path
        field = None
        if path:
            field = await artwork.field_for(path, self.colours() if self.tint else None)
        if path == self._wanted:
            self.show_field(field)

    def colours(self):
        """(base, text) as Field.tint_for() takes them: the colour this draws over (its CSS
        `color`, which style.css makes its background's) and the text drawn over it (its
        parent's `color`, with its alpha)."""
        parent = self.get_parent()
        text = parent.get_color() if parent is not None else self.get_color()
        return _rgb(self.get_color()), (_rgb(text), round(text.alpha, 4))

    def tint_alpha(self, field):
        """The opacity `field` is drawn at as a tint, for the colours shown now."""
        if field is None or Adw.StyleManager.get_default().get_high_contrast():
            return 0.0
        return field.tint_for(*self.colours())

    def _on_fade(self, value):
        self._mix = value
        if value >= 1.0:
            self._previous = None
        self.queue_draw()

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        bounds = Graphene.Rect().init(0, 0, width, height)
        side = max(width, height)
        square = Graphene.Rect().init((width - side) / 2, (height - side) / 2, side, side)
        if self.tint:
            # Over the CSS background GTK has drawn: each field at its own tint, the one
            # going fading out as the new one fades in.
            for field, weight in ((self._previous, 1.0 - self._mix), (self.field, self._mix)):
                opacity = weight * self.tint_alpha(field)
                if opacity > 0:
                    snapshot.push_opacity(opacity)
                    snapshot.append_scaled_texture(field.texture, Gsk.ScalingFilter.LINEAR,
                                                   square)
                    snapshot.pop()
            return
        snapshot.append_color(BASE, bounds)
        layers = ((self._previous, 1.0 - self._mix), (self.field, self._mix))
        scrim = sum(field.scrim * weight for field, weight in layers if field is not None)
        for field, opacity in ((self._previous, 1.0), (self.field, self._mix)):
            if field is None or opacity <= 0:
                continue
            snapshot.push_opacity(opacity)
            snapshot.append_scaled_texture(field.texture, Gsk.ScalingFilter.LINEAR, square)
            snapshot.pop()
        if scrim > 0:
            colour = Gdk.RGBA()
            colour.red = colour.green = colour.blue = 0.0
            colour.alpha = scrim
            snapshot.append_color(colour, bounds)
