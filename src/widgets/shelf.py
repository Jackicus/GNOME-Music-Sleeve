# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicShelf: a titled, horizontally scrolling row of tiles; RankedTile: a chart's
tile, numbered; ShelfColumn: a page's shelves, one under another; PagedRow: the paging arrows
and See All, which song_shelf.py's grid of songs shares."""

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from . import banner_tile, context_menu
from .banner_tile import BannerTile
from .hero_tile import HeroTile
from .labels import bind_label, unbind_label
from .tile import Tile, shape_for
from .util import connect_weak, each_frame, grown, next_frame, rows_kept, weak_method

# The tiles a shelf's row shows at most: See All opens the whole shelf. A horizontal
# Gtk.ListView makes a tile for every item up to about 200, whatever is on screen (100 items
# made 100 tiles, 2.4 MB and 15-20 ms), and music.apple.com's rows show about this many.
ROW_LIMIT = 30

# The tiles a row is given at once (what a maximized window shows of it), then MORE_TILES a
# frame up to ROW_LIMIT: a page's first shelves are built in one frame, and their every tile
# is made then whether it shows or not.
FIRST_TILES = 10
MORE_TILES = 6

# How long a click on a paging arrow takes to scroll the row, in milliseconds.
PAGE_DURATION = 250


class PagedRow:
    """A shelf's row controls, for a widget with `scrolled_window` (scrolling sideways only),
    `previous_button`, `next_button`, `see_all_button`, `_see_all` (See All offered) and its
    row's view as `_row`: See All while the row does not show everything (`_truncated()`,
    or wider than the window); the arrows while it overflows, at any width (the row shows
    no scrollbar: they are what shows that it scrolls), each sensitive while there is more
    that way; a click on one scrolls a width and focuses the first item wholly shown. All
    of it follows the row's horizontal adjustment, which the scrolled window keeps whatever
    its scrollbar policy.

    give_items() makes the row's model: the first of the items at once and the rest a few
    a frame (its row makes a widget for each item up to rows_kept() as it gets it, whether it
    shows or not), which stop_growing() stops."""

    _animation = None
    _slice = None  # the row's items: its first ones, then more a frame (give_items())
    _growing = None  # [the tick callback's id, the items a frame, the most, drawn] meanwhile

    def _truncated(self):
        return False

    def give_items(self, items, first, step, most=GLib.MAXUINT32):
        """A Gtk.SliceListModel of `items` (a list model) for the row: its first `first`
        now, then `step` more at each frame after the one that draws them, up to `most` (all
        of them by default: "the rest", gtk-notes.md, so items added later show too)."""
        self.stop_growing()
        self._slice = Gtk.SliceListModel(model=items, offset=0, size=min(first, most))
        if items.get_n_items() > first and most > first:
            self._growing = [each_frame(self._row, self._grow), step, most, False]
        else:
            self._slice.set_size(most)
        return self._slice

    def stop_growing(self):
        if self._growing is not None:
            self._row.remove_tick_callback(self._growing[0])
            self._growing = None

    def _grow(self):
        """At a frame while the row has some of its items: more, or the rest (once its view
        makes no more widgets for them: widgets.util.grown()). False when done."""
        _tick, step, most, drawn = self._growing
        if not drawn:  # the frame that lays out and draws the first ones: nothing more
            self._growing[3] = True
            return True
        model = self._slice
        total = min(model.get_model().get_n_items(), most)
        size = grown(model.get_size(), total, step, rows_kept(self._row))
        if size < total:
            model.set_size(size)
            return True
        model.set_size(most)
        self._growing = None
        return False

    def _update_controls(self):
        adjustment = self.scrolled_window.get_hadjustment()
        value, upper = adjustment.get_value(), adjustment.get_upper()
        page = adjustment.get_page_size()
        overflows = page > 0 and upper - page > 1
        self.see_all_button.set_visible(self._see_all and (self._truncated() or overflows))
        self.previous_button.set_visible(overflows)
        self.next_button.set_visible(overflows)
        self.previous_button.set_sensitive(value > 1)
        self.next_button.set_sensitive(value < upper - page - 1)

    def _on_adjustment_changed(self, _adjustment, _pspec):
        self._update_controls()

    def _on_page_clicked(self, _button, direction):
        """Scroll the row one width that way, then focus the first item wholly shown."""
        adjustment = self.scrolled_window.get_hadjustment()
        page = adjustment.get_page_size()
        target = min(max(adjustment.get_value() + direction * page, adjustment.get_lower()),
                     adjustment.get_upper() - page)
        if self._animation is not None:
            self._animation.skip()
        # Not Adw.TimedAnimation.new(): its new reference is annotated (transfer none),
        # so PyGObject takes one more and the animation is never freed.
        animation = Adw.TimedAnimation(
            widget=self.scrolled_window, value_from=adjustment.get_value(), value_to=target,
            duration=PAGE_DURATION, easing=Adw.Easing.EASE_OUT_CUBIC,
            target=Adw.PropertyAnimationTarget.new(adjustment, 'value'))
        connect_weak(animation, 'done', self._on_paged)
        self._animation = animation
        animation.play()

    def _on_paged(self, _animation):
        self._animation = None
        child = self._row.get_first_child()
        while child is not None:
            found, bounds = child.compute_bounds(self.scrolled_window)
            if child.get_visible() and found and bounds.get_x() >= -1:
                child.grab_focus()
                return
            child = child.get_next_sibling()

    def _connect_controls(self):
        """Connect the controls (weakly: a page drops its shelves)."""
        connect_weak(self.previous_button, 'clicked', self._on_page_clicked, -1)
        connect_weak(self.next_button, 'clicked', self._on_page_clicked, 1)
        adjustment = self.scrolled_window.get_hadjustment()
        for signal in ('notify::value', 'notify::upper', 'notify::page-size'):
            connect_weak(adjustment, signal, self._on_adjustment_changed)


class RankedTile(Gtk.Overlay):
    """A chart's tile (a shelf whose ShelfModel is `ranked`): an AppleMusicTile, `tile`, with
    its place in the chart over its cover's corner (set_rank()). A Python class of its own
    (its Python attributes stay with the widget) and not a template's: a template class
    cannot be subclassed. The number is decoration: the list item's name says it
    (labels.bind_label()'s `rank`)."""

    def __init__(self):
        super().__init__()
        self.tile = Tile()
        self.set_child(self.tile)
        # Over the cover's top corner: the tile's margin, then a little in.
        self.rank = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.START, margin_top=12,
                              margin_start=6, can_target=False,
                              accessible_role=Gtk.AccessibleRole.PRESENTATION,
                              css_classes=['osd', 'chart-rank', 'numeric'])
        self.add_overlay(self.rank)

    @property
    def context_item(self):
        """The tile's Item, for its context menu (widgets/context_menu.py)."""
        return self.tile.context_item

    def set_rank(self, rank):
        self.rank.set_label(str(rank))


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/shelf.ui')
class Shelf(PagedRow, Gtk.Box):
    """A shelf of Items (a library.ShelfModel, or any object with `key`, `title` and `items`,
    bound with bind_shelf()) as a row of tiles under its title, with paging arrows while the
    row overflows and a "See All" button (`see-all`: offered, and shown when the row does
    not show everything: more items than ROW_LIMIT, or wider than the window; always for an
    artist page's In Your Library, which has a page of its own), which opens the shelf as a
    grid (window.open_shelf). Activating a tile opens its item (window.open_item); a right
    click, a long press or the Menu key opens its context menu (context_menu.py), and a tile
    drags (widgets/dnd.py: an album or a playlist onto a sidebar playlist or the player bar).

    The row is a horizontal Gtk.ListView of the first ROW_LIMIT items (FIRST_TILES at once,
    the rest over the next frames: give_items()), the scrolled window's own child. It builds
    a tile for each of them, but only the tiles on screen are mapped and ask for their
    artwork. With `hero`, the tiles are 260 px AppleMusicHeroTiles, the cover over a band
    in its colour; with `banners`, wide AppleMusicBannerTiles (a featured shelf whose items
    have Apple's banners: widgets/banner_tile.py); otherwise 160 px AppleMusicTiles, round
    for artists and 16:9 for music videos (as tall as the rest), each numbered (a
    RankedTile) when the ShelfModel
    is `ranked` (a chart's: remote.remote_shelves). The shelf follows its ShelfModel's title,
    its subtitle (a recommendation's reason, a dimmed line under the title, when there is one)
    and its items as they change.

    Scrolling: the row's scrolled window scrolls only horizontally, and GtkScrolledWindow
    handles a scroll event only along an axis it can scroll, so a vertical wheel over the row
    goes on to the page's scrolled window, and a horizontal one (a touchpad, a tilting wheel,
    Shift and the wheel) moves the row. The row shows no scrollbar (`hscrollbar-policy:
    external`), which the pointer kept landing on as it scrolled the page; it still scrolls
    by those, by a finger, and as the focus moves along it (the list view scrolls the item
    focused into view), and the paging arrows, shown whenever it overflows, page it. A row
    that fits scrolls neither way and shows no arrows.

    GtkBuilder builds some (search.blp): it calls __init__ without arguments and
    sets the properties after it, where a Python caller's are set before __init__'s body
    runs, so the state the property setters read starts as class attributes.
    """

    __gtype_name__ = 'AppleMusicShelf'

    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    previous_button = Gtk.Template.Child()
    next_button = Gtk.Template.Child()
    see_all_button = Gtk.Template.Child()
    scrolled_window = Gtk.Template.Child()
    list_view = Gtk.Template.Child()

    shelf = None  # the ShelfModel shown
    _hero = False
    _banners = False
    _banner_width = banner_tile.BANNER_WIDTH  # the banner cards' width, the row's
    _fit_idle = None
    _fitted_to = -1  # the row's width the banner cards were last fitted to
    _ranked = False  # the tiles numbered: the shelf shown is a chart's
    _see_all = False
    _followed = ()  # (object, handler id) pairs on the shelf shown

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Every signal of a child or of an object the shelf holds is connected weakly
        # (util.py): a bound method would keep a shelf that a page drops alive.
        factory = Gtk.SignalListItemFactory()
        connect_weak(factory, 'setup', self._on_setup)
        connect_weak(factory, 'bind', self._on_bind)
        connect_weak(factory, 'unbind', self._on_unbind)
        self.list_view.set_factory(factory)
        connect_weak(self.list_view, 'activate', self._on_activate)
        connect_weak(self.see_all_button, 'clicked', self._on_see_all_clicked)
        self._connect_controls()
        self._row = self.list_view
        context_menu.attach(self.list_view, drag=True)  # tiles onto playlists and the bar

    def _get_hero(self):
        return self._hero

    def _set_hero(self, hero):
        if hero == self._hero:
            return
        self._hero = hero
        self._rebuild_rows()

    def _rebuild_rows(self):
        """New rows, built with the other kind of tile (none before __init__ has made the
        factory, when a Python caller passes hero=True)."""
        factory = self.list_view.get_factory()
        if factory is not None:
            self.list_view.set_factory(None)
            self.list_view.set_factory(factory)

    hero = GObject.Property(type=bool, default=False, getter=_get_hero, setter=_set_hero,
                            nick='Hero', blurb='Whether the tiles are large cards')

    def _get_banners(self):
        return self._banners

    def _set_banners(self, banners):
        if banners == self._banners:
            return
        self._banners = banners
        self._rebuild_rows()

    banners = GObject.Property(type=bool, default=False, getter=_get_banners,
                               setter=_set_banners, nick='Banners',
                               blurb='Whether the tiles are wide banner cards')

    def _get_see_all(self):
        return self._see_all

    def _set_see_all(self, see_all):
        self._see_all = see_all
        self._update_controls()

    see_all = GObject.Property(type=bool, default=False, getter=_get_see_all,
                               setter=_set_see_all, nick='See All',
                               blurb='Whether the shelf offers to open its items as a grid')

    def bind_shelf(self, shelf):
        """Show a shelf: its title, and its first ROW_LIMIT items, which the row follows as
        they change (and the title too, for a ShelfModel)."""
        if shelf is self.shelf:
            return
        self.clear()
        self.shelf = shelf
        ranked = bool(getattr(shelf, 'ranked', False))
        if ranked != self._ranked:
            self._ranked = ranked
            self._rebuild_rows()
        followed = [(shelf.items, connect_weak(shelf.items, 'items-changed',
                                               self._on_items_changed))]
        if isinstance(shelf, GObject.Object):
            followed.append((shelf, connect_weak(shelf, 'notify::title', self._on_title)))
            if shelf.find_property('subtitle') is not None:
                followed.append((shelf, connect_weak(shelf, 'notify::subtitle',
                                                     self._on_title)))
        self._followed = followed
        self._show_title()
        self.list_view.set_model(Gtk.NoSelection(
            model=self.give_items(shelf.items, FIRST_TILES, MORE_TILES, ROW_LIMIT)))
        self.scrolled_window.get_hadjustment().set_value(0)  # a new shelf starts at its start
        self._update_controls()

    def clear(self):
        """Show nothing, and follow nothing (a spare widget a page keeps for later)."""
        for obj, handler in self._followed:
            obj.disconnect(handler)
        self._followed = ()
        self.shelf = None
        self.stop_growing()
        self.list_view.set_model(None)

    def _show_title(self):
        title = self.shelf.title if self.shelf is not None else ''
        subtitle = getattr(self.shelf, 'subtitle', '') or ''
        self.title_label.set_label(title)
        self.title_label.set_visible(bool(title))
        self.subtitle_label.set_label(subtitle)
        self.subtitle_label.set_visible(bool(subtitle))
        self.list_view.update_property([Gtk.AccessibleProperty.LABEL], [title])
        self.list_view.update_property([Gtk.AccessibleProperty.DESCRIPTION], [subtitle])

    def _on_title(self, _shelf, _pspec):
        self._show_title()

    def _on_items_changed(self, _items, _position, _removed, _added):
        self._update_controls()

    def _truncated(self):
        """More items than the row shows (ROW_LIMIT), more that Apple has (`more`), or a
        page of its own to show (an artist page's In Your Library: `library_artist`)."""
        return self.shelf is not None and (
            self.shelf.items.get_n_items() > ROW_LIMIT
            or bool(getattr(self.shelf, 'more', False))
            or getattr(self.shelf, 'library_artist', None) is not None)

    def _update_controls(self):
        PagedRow._update_controls(self)
        if (self._banners and self._fit_idle is None
                and self.scrolled_window.get_width() != self._fitted_to):
            # Not from inside the allocation that changed the width: in an idle.
            self._fit_idle = GLib.idle_add(weak_method(self._fit_banners))

    def _fit_banners(self):
        """Give the banner cards the width that fits the row (banner_tile.card_width()):
        narrower in a shelf narrower than one."""
        self._fit_idle = None
        self._fitted_to = self.scrolled_window.get_width()
        width = banner_tile.card_width(self._fitted_to)
        if width != self._banner_width:
            self._banner_width = width
            row = self.list_view.get_first_child()
            while row is not None:
                card = row.get_first_child()
                if isinstance(card, BannerTile):
                    card.set_width(width)
                row = row.get_next_sibling()
        return GLib.SOURCE_REMOVE

    def _on_setup(self, _factory, list_item):
        if self._banners:
            list_item.set_child(BannerTile(width=self._banner_width))
        elif self._hero:
            list_item.set_child(HeroTile())
        else:
            list_item.set_child(RankedTile() if self._ranked else Tile())

    def _on_bind(self, _factory, list_item):
        item = list_item.get_item()
        child = list_item.get_child()
        rank = None
        if isinstance(child, RankedTile):
            rank = list_item.get_position() + 1
            child.set_rank(rank)
            child = child.tile
        if not (self._hero or self._banners):
            child.set_shape(shape_for(item))
        child.bind(item)
        bind_label(list_item, item, rank=rank)

    def _on_unbind(self, _factory, list_item):
        child = list_item.get_child()
        (child.tile if isinstance(child, RankedTile) else child).unbind()
        unbind_label(list_item)

    def _on_activate(self, list_view, position):
        item = list_view.get_model().get_item(position)
        if item is not None:
            self.get_root().open_item(item)

    def _on_see_all_clicked(self, _button):
        if self.shelf is not None:
            self.get_root().open_shelf(self.shelf)


# The shelves a ShelfColumn binds before the page is drawn: the hero cards and what fits
# under them. The rest are bound one a frame after that, below the fold: a library with 21
# shelves made 317 tiles at once, and Home took 210 ms to open.
FIRST_SHELVES = 3


# The forms a ShelfColumn shows a shelf in: a row of tiles, a row of large cards, a row of wide
# banners (a ShelfModel whose `form` is 'banners': New's featured shelf with Apple's banners)
# or a grid of songs (one whose `form` is 'songs': a chart's Top Songs).
TILES = 'tiles'
HEROES = 'heroes'
BANNERS = 'banners'
SONGS = 'songs'


def form_for(shelf, hero):
    """The form a ShelfColumn shows `shelf` in: SONGS or BANNERS for a ShelfModel whose
    `form` says so, else HEROES or TILES as `hero` says."""
    form = getattr(shelf, 'form', '')
    if form in (SONGS, BANNERS):
        return form
    return HEROES if hero else TILES


class ShelfColumn:
    """The shelves of a page, one under another in `box` after `anchor` (a child of the box
    before them, such as the page's title, or None), each an AppleMusicShelf, or an
    AppleMusicSongShelf for a shelf whose `form` is 'songs' (form_for()).

    show(shelves, hero_first, heroes) shows ShelfModels in that order, the first as hero cards
    with `hero_first`, and those in `heroes` too (an artist's Essential Albums). A shelf shown
    before keeps its widget, moved into place (nothing rebuilt,
    its row's scroll position kept); the others are bound to spare or new widgets of their
    form, the first FIRST_SHELVES at once and the rest one a frame (next_frame()), placed as
    they are bound, so the column never shows a shelf twice or one that went. Widgets left
    over are hidden and kept for the next show(). `make_shelf(hero)` makes a widget for a row
    of tiles or cards (a Shelf offering See All by default); a grid of songs is a SongShelf.
    Anything placed in the box after the anchor that the column did not make stays after
    the shelves shown (a page's footer).
    """

    def __init__(self, box, anchor=None, make_shelf=None):
        self._box = box
        self._anchor = anchor
        self._make_shelf = make_shelf or (lambda hero: Shelf(hero=hero, see_all=True))
        self._widgets = {}  # a ShelfModel shown -> its widget
        self._forms = {}  # each widget made -> its form (TILES, HEROES, SONGS)
        self._spare = []  # widgets hidden, for later
        self._task = None  # the staged binding under way
        self.shelves = []  # what show() was last asked for, in order

    @property
    def widgets(self):
        """The widgets showing shelves, in the column's order."""
        return [self._widgets[shelf] for shelf in self.shelves if shelf in self._widgets]

    def widget_for(self, shelf):
        """The widget showing `shelf`, or None while it shows none."""
        return self._widgets.get(shelf)

    def focus(self):
        """Give the focus to the first shelf shown that takes it, in the column's order: True
        when one did. Not the box's own Tab order, which follows where its children were laid
        out: a shelf bound since the last layout (one a frame, after FIRST_SHELVES) has no
        place yet, sorts before the others, and would take the focus from the first."""
        return any(widget.child_focus(Gtk.DirectionType.TAB_FORWARD) for widget in self.widgets)

    def show(self, shelves, hero_first=False, heroes=()):
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        shelves = list(shelves)
        forms = {shelf: form_for(shelf, (hero_first and position == 0) or shelf in heroes)
                 for position, shelf in enumerate(shelves)}
        for shelf, widget in list(self._widgets.items()):
            if shelf not in forms or self._forms[widget] != forms[shelf]:
                del self._widgets[shelf]
                self._retire(widget)
        self.shelves = shelves
        pending = [shelf for shelf in shelves if shelf not in self._widgets]
        app = Gio.Application.get_default()
        spawn = getattr(app, 'spawn', None)
        now = pending if spawn is None else pending[:FIRST_SHELVES]
        for shelf in now:
            self._bind(shelf, forms[shelf])
        self._arrange()
        rest = pending[len(now):]
        if rest:
            self._task = spawn(self._bind_rest(rest, forms))

    async def _bind_rest(self, shelves, forms):
        for shelf in shelves:
            await next_frame(self._box)
            self._bind(shelf, forms[shelf])
            self._arrange()

    def _make(self, form):
        if form == SONGS:
            from .song_shelf import SongShelf  # song_shelf.py imports this module

            return SongShelf()
        if form == BANNERS:
            return Shelf(banners=True, see_all=True)
        return self._make_shelf(form == HEROES)

    def _bind(self, shelf, form):
        widget = next((spare for spare in self._spare if self._forms[spare] == form), None)
        if widget is None:
            widget = self._make(form)
            self._forms[widget] = form
            self._box.append(widget)
        else:
            self._spare.remove(widget)
        widget.bind_shelf(shelf)
        widget.set_visible(True)
        self._widgets[shelf] = widget

    def _retire(self, widget):
        widget.set_visible(False)
        widget.clear()
        self._spare.append(widget)

    def _arrange(self):
        """Put the widgets in the shelves' order, right after the anchor."""
        previous = self._anchor
        for widget in self.widgets:
            if widget.get_prev_sibling() is not previous:
                self._box.reorder_child_after(widget, previous)
            previous = widget
