# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicTile: an Item as a grid tile, its artwork, title and subtitle."""

from gi.repository import Adw, Gtk

from . import artwork
from .util import connect_weak

# The placeholder's icon and size: a music note until the cover arrives, and a playlist
# folder's big folder icon, which no cover replaces.
PLACEHOLDER = ('music-note-symbolic', 48)
FOLDER = ('folder-symbolic', 72)

# The cover's edge in logical pixels (tile.blp): the texture asked for is this times the
# scale factor. A music video's frame in a shelf is as tall and 16:9 wide, so a shelf that
# mixes videos with albums keeps one height (and its artwork, decoded by its shorter edge,
# the same size). A grid of videos (pages/grid.py) has smaller frames, GRID_VIDEO_SIZE, so
# three columns fit beside the sidebar at the default window width, two at middle widths and
# one in a 360 px window, each cell left with little room after its tile.
ART_SIZE = 160
VIDEO_WIDTH = 284
VIDEO_SIZE = (VIDEO_WIDTH, ART_SIZE)
GRID_VIDEO_SIZE = (240, 135)

# The tile's shapes: a square cover, an artist's round portrait, a music video's 16:9 frame.
COVER = 'cover'
ARTIST = 'artist'
VIDEO = 'video'


def shape_for(item):
    """The shape a tile shows `item` in: its kind's, a square cover for most."""
    kind = item.kind
    return kind if kind in (ARTIST, VIDEO) else COVER


def cut_short(inscription):
    """Whether a Gtk.Inscription's text is wider than the inscription (so ellipsized): its
    text laid out on one line, in the inscription's own font."""
    text = inscription.get_text()
    if not text:
        return False
    width = inscription.create_pango_layout(text).get_pixel_size()[0]
    return width > inscription.get_width()


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/tile.ui')
class Tile(Gtk.Box):
    """A 160 px square cover over a title and a dim subtitle, one line each; in the ARTIST
    shape, a round portrait over a centred name; in the VIDEO shape, a 284×160 frame, a play
    symbol over it under the pointer or the keyboard focus (`video_size`, (width, height):
    VIDEO_SIZE, or a video grid's GRID_VIDEO_SIZE). With year=True the line under the
    title is the year (an artist's own albums, where the artist goes without saying). A line
    too long for the tile ends in an ellipsis, and the tooltip shows the whole of both; the
    list item's accessible label has them too (labels.bind_label()).

    A playlist folder (an Item of kind 'folder') has no cover: its tile shows a folder icon.
    bind(item) and unbind() are called by a list factory as tiles are recycled; the Item bound
    is the tile's `context_item`, whose menu the view shows (widgets/context_menu.py). While
    bound, the tile follows the Item's notify signals: a list does not rebind an item that
    changed in place (a reload's new title or thumbnail, a fetched thumbnail). The cover is
    asked for by an artwork.ArtworkSlot: only while the tile is mapped, which in a Gtk.GridView
    means on screen, and let go of when it is unmapped, so the textures alive are about the
    ones on screen plus the Artwork cache; in an idle after the frame, not as the tile is
    mapped or bound (a grid creates and maps over a hundred tiles at once and unmaps all but
    the visible dozen in its first layout, and a tile scrolling past is rebound many times a
    second); and decoded at the size drawn (ART_SIZE times the scale factor, the shorter edge).
    """

    __gtype_name__ = 'AppleMusicTile'

    cover = Gtk.Template.Child()
    art_box = Gtk.Template.Child()
    placeholder_icon = Gtk.Template.Child()
    picture = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()

    def __init__(self, shape=COVER, year=False, video_size=VIDEO_SIZE, **kwargs):
        super().__init__(**kwargs)
        self._year = year
        self._video_size = video_size
        self._shape = COVER
        self._folder = False
        self._item = None
        self._handler = None  # the bound Item's notify handler
        self.avatar = None  # the artist shape's portrait, made when first wanted
        self.play_symbol = None  # the video shape's play symbol, made when first wanted
        # Decoded by the shorter edge, so at the frame's height for a video (no taller than
        # a cover: a grid's tile is only ever a video, a shelf's as tall as a cover).
        self._slot = artwork.ArtworkSlot(self._set_art, min(ART_SIZE, video_size[1]))
        self._slot.follow_scale(self)
        # A handler on the tile itself, which holds no reference back through C.
        self.connect('query-tooltip', self._on_query_tooltip)
        self.set_shape(shape)

    @property
    def shape(self):
        return self._shape

    def set_shape(self, shape):
        """Show a square cover (COVER), an artist's round portrait (ARTIST) or a music video's
        frame (VIDEO). A grid page's tiles are all one; a shelf, which can mix them, switches
        a tile as it binds it (before bind(): shape_for(item)). Only a change lays the tile
        out again."""
        if shape == self._shape:
            return
        self._slot.set_paths()  # the one showing lets go of its texture
        self._shape = shape
        artist = shape == ARTIST
        video = shape == VIDEO
        if artist and self.avatar is None:
            # A silhouette until the picture arrives. Not initials: they are a label that
            # would be laid out again at every rebind. Made only for artist tiles: an
            # Adw.Avatar costs 18 KB and a third of a tile's making, and most tiles are
            # covers.
            self.avatar = Adw.Avatar(size=ART_SIZE,
                                     accessible_role=Gtk.AccessibleRole.PRESENTATION)
            self.insert_child_after(self.avatar, self.cover)
        if video and self.play_symbol is None:
            # Shown under the pointer and with the focus (style.css), never laid out again:
            # its opacity changes, not its visibility.
            self.play_symbol = Gtk.Box(
                halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, can_target=False,
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
                css_classes=['osd', 'tile-play'])
            self.play_symbol.append(Gtk.Image(
                icon_name='transport-play-symbolic', pixel_size=24,
                accessible_role=Gtk.AccessibleRole.PRESENTATION))
            self.cover.add_overlay(self.play_symbol)
        self.cover.set_visible(not artist)
        if self.avatar is not None:
            self.avatar.set_visible(artist)
        if self.play_symbol is not None:
            self.play_symbol.set_visible(video)
        self.art_box.set_size_request(*(self._video_size if video else (ART_SIZE, ART_SIZE)))
        # An artist's name, centred under the portrait, has no line under it.
        self.title_label.set_xalign(0.5 if artist else 0)
        self.subtitle_label.set_visible(not artist)

    @property
    def context_item(self):
        """The Item shown, for its context menu (widgets/context_menu.py)."""
        return self._item

    def bind(self, item):
        if self._item is not None:
            self.unbind()
        self._item = item
        # The Item outlives the tile (the library's, a shelf's): it holds the tile weakly.
        self._handler = connect_weak(item, 'notify', self._on_item_notify)
        folder = item.kind == 'folder'
        if folder != self._folder:  # only then: setting an icon costs a relayout
            self._folder = folder
            icon_name, size = FOLDER if folder else PLACEHOLDER
            self.placeholder_icon.set_from_icon_name(icon_name)
            self.placeholder_icon.set_pixel_size(size)
        self._show_label(item)
        self._slot.set_paths(item.thumb or item.art)

    def _show_label(self, item):
        self.title_label.set_text(item.title)
        if self._year:
            subtitle = str(item.year) if item.year else ''
        else:
            subtitle = item.subtitle or ''
        self.subtitle_label.set_text(subtitle)

    def unbind(self):
        if self._handler is not None:
            self._item.disconnect(self._handler)
            self._handler = None
        self._item = None
        self._slot.set_paths()

    def _on_item_notify(self, item, pspec):
        """Follow the Item: a reload merges new values into it, and a fetch says a thumbnail
        has arrived (notify::thumb, the path unchanged); a list does not rebind for either."""
        name = pspec.name
        if name in ('title', 'subtitle', 'year'):
            self._show_label(item)
        elif name in ('thumb', 'art') and not self._slot.set_paths(item.thumb or item.art):
            self._slot.refresh()

    def _on_query_tooltip(self, _tile, _x, _y, _keyboard, tooltip):
        """The whole title and subtitle, when either line is cut short; nothing otherwise.
        Worked out as the pointer rests on the tile, so bind costs nothing for it."""
        if self._item is None:
            return False
        labels = [label for label in (self.title_label, self.subtitle_label)
                  if label.get_visible() and label.get_text()]
        if not any(cut_short(label) for label in labels):
            return False
        tooltip.set_text('\n'.join(label.get_text() for label in labels))
        return True

    def do_map(self):
        Gtk.Box.do_map(self)
        self._slot.map(self.get_scale_factor())

    def do_unmap(self):
        self._slot.unmap()
        Gtk.Box.do_unmap(self)

    def _set_art(self, paintable, found):
        if self._shape == ARTIST:
            self.avatar.set_custom_image(paintable if found else None)
        else:
            # Never None, and the icon faded rather than hidden: either would lay the grid
            # out again (artwork.empty()).
            self.picture.set_paintable(paintable)
            self.placeholder_icon.set_opacity(0 if found else 1)
