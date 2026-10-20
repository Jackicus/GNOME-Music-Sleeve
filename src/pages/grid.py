# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicGridPage: a root page showing a model of Items as a grid of tiles.

The chain is the page's store → Gtk.SortListModel (the header's sort choice, or none) →
Gtk.FilterListModel (a Gtk.EveryFilter of the filter bar's text, on a page that has one:
widgets/filter_bar.text_filter(), matching everything until there is text, and Favourites
Only, on a page that offers it: a Gtk.BoolFilter on Item.favourite) → ShownModel (that
order backwards, for a descending text, and a filter's change shown so that the grid rebinds
its tiles rather than building new ones) → Gtk.NoSelection → Gtk.GridView, whose factory
recycles AppleMusicTiles. Sorting uses
Gtk.StringSorter and Gtk.NumericSorter over Gtk.PropertyExpressions, which compute one key per
item and sort in C: about 10 ms for 2,000 albums, against 25 ms for a Python
Gtk.CustomSorter, whose cost grows with every comparison rather than every item.
"""

from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from ..library import Item
from ..widgets import context_menu
from ..widgets.filter_bar import FilterBar, ShownModel, text_filter
from ..widgets.labels import bind_label, unbind_label
from ..widgets.tile import ARTIST, COVER, GRID_VIDEO_SIZE, VIDEO, Tile
from ..widgets.util import HeaderTitle, MappedHandlers, connect_weak, focus_position
from . import SignInOffer, app, mark_bound


def _string(name):
    return Gtk.StringSorter(expression=Gtk.PropertyExpression.new(Item, None, name))


def _number(name, descending=False):
    return Gtk.NumericSorter(
        expression=Gtk.PropertyExpression.new(Item, None, name),
        sort_order=Gtk.SortType.DESCENDING if descending else Gtk.SortType.ASCENDING)


def _chain(*sorters):
    multi = Gtk.MultiSorter()
    for sorter in sorters:
        multi.append(sorter)
    return multi


# The width of a grid column: a tile (tile.blp, 160 px) and the padding Adwaita gives a grid
# view's child (3 px a side). Gtk.GridView divides its width by it, and a tile sits at the
# start of its column, so the first column's cover is on the grid's margin (grid.blp: 21 px,
# the page's 24 less the child's padding) whatever the width. A grid of music videos has
# columns of its 16:9 tiles (tile.GRID_VIDEO_SIZE, 240 px wide) instead.
COLUMN_WIDTH = 166
VIDEO_COLUMN_WIDTH = 246


def columns_for(width, column_width=COLUMN_WIDTH):
    """The columns a grid of tiles in a page `width` px wide shows, or one more when the
    grid's margins (left out here) tip it: never fewer, so a grid told this many as
    max-columns lays out as it would with no limit."""
    return max(2, width // column_width)


def estimate_columns(column_width=COLUMN_WIDTH):
    """How many columns the content pane fits (columns_for), from its width
    (Window.content_width(), an estimate before the window has laid it out: the page restored
    at startup), or None without a window.

    Gtk.GridView keeps tiles for max-columns columns by about 30 rows (its anchor), however
    few columns it shows: 385 tiles with the default 12, which made opening Artists or All
    Playlists take 200 ms. Told the columns that fit, it makes 30 rows of those: 129 tiles
    at 1100×760, and those pages open in 70 ms."""
    application = app()
    window = application.get_active_window() if application is not None else None
    content_width = getattr(window, 'content_width', None)
    width = content_width() if content_width is not None else 0
    return columns_for(width, column_width) if width and width > 0 else None


# The sort orders a page can offer: key -> (label, the Item properties compared in turn,
# whether the key's own direction is descending). Labels are looked up when a page is built,
# after the launcher has set up gettext; their mnemonics differ from one another's and from
# sort_labels()'s, as they share a menu. An Item's subtitle is its artist; Year is newest
# first unless asked the other way.
SORTS = {
    'title': (lambda: _('_Title'), ('title',), False),
    'artist': (lambda: _('_Artist'), ('subtitle', 'year', 'title'), False),
    'year': (lambda: _('_Year'), ('year', 'title'), True),
    # Newest first: Apple's dateAdded (Item.added), to the second.
    'added': (lambda: _('Date A_dded'), ('added', 'title'), True),
}


def sort_labels():
    """The Sort By menu's other items, with mnemonics of their own beside SORTS' (and the
    Songs page's, songs.blp): Ascending and Descending, and Favourites Only."""
    return {'ascending': _('Asc_ending'), 'descending': _('Desce_nding'),
            'favourites-only': _('_Favourites Only')}
# The properties compared as numbers; the rest are text.
NUMBERS = frozenset({'year', 'added'})


def favourites_only(tag):
    """Whether the root page with that tag was last left showing its favourites only (the
    favourites-only setting); False without one (a pushed page, a test's stand-in)."""
    settings = getattr(app(), 'settings', None)
    if not tag or settings is None:
        return False
    return tag in settings.get_strv('favourites-only')


def remember_favourites_only(tag, favourites):
    """Remember a root page's Favourites Only (the favourites-only setting, by page tag)."""
    settings = getattr(app(), 'settings', None)
    if not tag or settings is None:
        return
    tags = [name for name in settings.get_strv('favourites-only') if name != tag]
    if favourites:
        tags.append(tag)
    settings.set_strv('favourites-only', sorted(tags))


def offered(model, key):
    """Whether the items of `model` have the property `key` sorts first by (SORTS), for a
    sort that is offered only where the data has it (`data_sorts`: a music video's Date
    Added, which Apple may not give): any item with a value (a page of a few items: it
    reads them all when none has one)."""
    name = SORTS[key][1][0]
    for position in range(model.get_n_items()):
        if model.get_item(position).get_property(name):
            return True
    return False


def make_sorter(key, descending=False):
    """The Gtk.Sorter for SORTS[key] in one direction, and whether its order is to be shown
    backwards. Descending turns the first property round and leaves the rest breaking ties as
    they do ascending, as the Songs table's order does (library.SongOrder): a number's
    Gtk.NumericSorter takes the direction, but Gtk.StringSorter sorts one way, so a text's
    descending order is its ascending one shown backwards (ShownModel), ties and all."""
    names = SORTS[key][1]
    backwards = descending and names[0] not in NUMBERS
    sorters = [_number(name, descending and name == names[0]) if name in NUMBERS
               else _string(name) for name in names]
    return (_chain(*sorters) if len(sorters) > 1 else sorters[0]), backwards


def _direction(descending):
    return 'descending' if descending else 'ascending'


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/grid.ui')
class GridPage(Adw.NavigationPage):
    """A destination's grid, or a shelf's (See All).

    `model` is the Gio.ListModel of Items to show, or a function returning it (asked again
    whenever the library changes, for models that a load replaces, like a shelf's; None
    shows nothing, as the missing state: `missing_title`, `missing_description`, a folder
    that is gone). `sorts` are SORTS keys: the first is the initial order, and with more than
    one the header's Sort By menu offers them (the page.sort action) and Ascending or
    Descending (page.sort-order): a key chosen comes its own way round (Year newest first,
    the rest A to Z) and the direction turns it; the key is remembered per root page in the
    grid-sort setting, the direction for the page's life. No keys keeps the model's own
    order. `data_sorts` are keys offered only while the items have data for them (offered():
    a music video's Date Added). `favourites`, (title, description), adds Favourites Only to
    the menu (then Sort and Filter, shown while the filter is on whatever it leaves), with
    the empty state's words for no favourite left; remembered per root page in the
    favourites-only setting. `artist` makes round portrait tiles, `video` music videos' 16:9
    ones (wider columns). `filter_words`, (label, count), gives the page a filter bar
    (widgets/filter_bar.py) named `label` ("Filter Albums"), whose new count is announced in
    the words count(shown, total) chooses ("{shown} of {total} albums", formatted here); a
    filter that leaves nothing shows No Results Found. `root` is false for a page pushed over
    another. Root or pushed, the
    header bar shows the title while the big one is out of view (HeaderTitle). The
    in-content title follows the page's `title`, on the page's margin, where the first
    column's cover is. The loading and empty states follow the library's
    state (the first sync filling an empty library is loading) and the model's item count. A
    playlist folder's page is one too (pages.folder()): its folders are tiles with a folder
    icon. Its tiles are drag sources (widgets/dnd.py): an album or a playlist onto a sidebar
    playlist (its songs added) or the player bar (queued), a playlist or folder onto a
    sidebar folder (moved), a music video as a song is; artists drag nowhere.
    """

    __gtype_name__ = 'AppleMusicGridPage'

    toolbar = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    sort_button = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()
    overlay = Gtk.Template.Child()
    scrolled_window = Gtk.Template.Child()
    grid_view = Gtk.Template.Child()
    title_label = Gtk.Template.Child()

    def __init__(self, library, title, model, sorts=(), artist=False, video=False, root=True,
                 icon_name=None, empty_title=None, empty_description=None, missing_title=None,
                 missing_description=None, data_sorts=(), favourites=None,
                 filter_words=None):
        super().__init__(title=title)
        self._library = library
        self._get_model = model if callable(model) else lambda: model
        self._artist = artist
        self._shape = ARTIST if artist else VIDEO if video else COVER
        self._column_width = VIDEO_COLUMN_WIDTH if video else COLUMN_WIDTH
        self._title_offset = 0
        self._bound = False  # a tile has been bound (the startup timing's mark)
        self.filter_bar = None  # the page's filter bar, on a page with `filter_words`
        self._count_words = None
        self._nothing = Gio.ListStore(item_type=Item)  # shown while `model` returns None
        self._missing = False  # `model` returned None
        self._empty = (empty_title or title, empty_description)
        self._missing_texts = (missing_title or self._empty[0],
                               missing_description or self._empty[1])

        # The page's title, which a folder's page changes when the folder is renamed.
        self.bind_property('title', self.title_label, 'label', GObject.BindingFlags.SYNC_CREATE)
        self._icon_name = icon_name
        self.empty_page.set_icon_name(icon_name)
        self._sign_in = SignInOffer(self.empty_page)  # Sign In… while signed out

        self._all_sorts = tuple(sorts) + tuple(data_sorts)
        self._data_sorts = frozenset(data_sorts)
        self._sort_keys = tuple(sorts)  # those offered now (_update_sorts)
        self._order = (sorts[0], SORTS[sorts[0]][2]) if sorts else None  # (key, descending)
        sorter, backwards = make_sorter(*self._order) if sorts else (None, False)
        # Favourites Only: `favourites` is (empty title, empty description) on a page that
        # offers it, the status page's words when no favourite is left to show.
        self._favourites_texts = favourites
        self._favourites_on = False
        self._favourite_filter = Gtk.BoolFilter(
            expression=Gtk.PropertyExpression.new(Item, None, 'favourite'))
        # The filter bar's text and Favourites Only: an item shows when it passes both. With
        # neither, the Gtk.EveryFilter matches everything without reading an item.
        self._filters = Gtk.EveryFilter()
        self._text_filter = text_filter()
        self._filters.append(self._text_filter)
        # After the sort: a new filter leaves the order as it is, and only takes items out of
        # it and puts them back (a sort over the filter's output would place each again).
        self._sorted = Gtk.SortListModel(model=self._model(), sorter=sorter)
        self._filtered = Gtk.FilterListModel(model=self._sorted, filter=self._filters)
        self._shown = ShownModel(self._filtered)
        self._shown.set_backwards(backwards)
        # Every signal of a child or of an object the page holds is connected weakly
        # (widgets/util.py): a bound method would keep the page alive once popped.
        connect_weak(self._filtered, 'items-changed', self._update_state)

        factory = Gtk.SignalListItemFactory()
        connect_weak(factory, 'setup', self._on_setup)
        connect_weak(factory, 'bind', self._on_bind)
        connect_weak(factory, 'unbind', self._on_unbind)
        self.grid_view.set_factory(factory)
        connect_weak(self.grid_view, 'activate', self._on_activate)
        connect_weak(self.overlay, 'get-child-position', self._on_title_position)
        # Before the model: the grid makes tiles for max-columns columns until it has a
        # width of its own (estimate_columns); _on_title_position keeps it fitting after.
        self._columns_idle = None
        if video:
            self.grid_view.set_min_columns(1)  # two of them are wider than a 360 px window
        self._set_columns(estimate_columns(self._column_width))
        self.grid_view.set_model(Gtk.NoSelection(model=self._shown))
        context_menu.attach(self.grid_view, drag=True)

        # Sort By: a menu of the orders and of the directions, as radio items of the stateful
        # page.sort and page.sort-order actions, and on a page that offers it Favourites
        # Only, a check item of page.favourites-only (the button is Sort and Filter then).
        self._sort_restored = False  # the remembered choice applied (once the page's tag is)
        self._sort_action = Gio.SimpleAction.new_stateful(
            'sort', GLib.VariantType.new('s'), GLib.Variant('s', sorts[0] if sorts else ''))
        self._order_action = Gio.SimpleAction.new_stateful(
            'sort-order', GLib.VariantType.new('s'), GLib.Variant('s', _direction(backwards)))
        self._favourites_action = Gio.SimpleAction.new_stateful(
            'favourites-only', None, GLib.Variant('b', False))
        connect_weak(self._sort_action, 'change-state', self._on_sort_chosen)
        connect_weak(self._order_action, 'change-state', self._on_order_chosen)
        connect_weak(self._favourites_action, 'change-state', self._on_favourites_only)
        actions = Gio.SimpleActionGroup()
        actions.add_action(self._sort_action)
        actions.add_action(self._order_action)
        actions.add_action(self._favourites_action)
        self.insert_action_group('page', actions)
        menu = Gio.Menu()
        self._keys_menu = Gio.Menu()
        menu.append_section(None, self._keys_menu)
        labels = sort_labels()
        directions = Gio.Menu()
        directions.append(labels['ascending'], 'page.sort-order::ascending')
        directions.append(labels['descending'], 'page.sort-order::descending')
        menu.append_section(None, directions)
        if favourites is not None:
            filters = Gio.Menu()
            filters.append(labels['favourites-only'], 'page.favourites-only')
            menu.append_section(None, filters)
            self.sort_button.set_tooltip_text(_('Sort and Filter'))
            self.sort_button.update_property([Gtk.AccessibleProperty.LABEL],
                                             [_('Sort and Filter')])
        self.sort_button.set_menu_model(menu)
        self._update_sorts()

        # The filter bar, under the header bar, its button beside Sort By.
        if filter_words is not None:
            label, self._count_words = filter_words
            self.filter_bar = FilterBar(label)
            self.toolbar.add_top_bar(self.filter_bar)
            self.header_bar.pack_end(self.filter_bar.button)
            connect_weak(self.filter_bar, 'changed', self._on_filter_changed)
            self.filter_bar.set_focus_return(self._focus_grid)

        connect_weak(self.scrolled_window.get_vadjustment(), 'value-changed', self._on_scrolled)
        self._header_title = HeaderTitle(self.header_bar, self.title_label, self.scrolled_window)
        # The library outlives the window: the page follows it only while it is shown.
        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._update_state)
        self._handlers.add(library, 'notify::syncing', self._update_state)
        self._handlers.add(library, 'changed', self._on_library_changed)
        if favourites is not None:
            self._handlers.add(library, 'favourites-changed', self._on_favourites_changed)
        self._update_state()

    def _model(self):
        model = self._get_model()
        self._missing = model is None
        return self._nothing if model is None else model

    def _set_columns(self, columns):
        self._columns_idle = None
        if columns is not None and columns != self.grid_view.get_max_columns():
            self.grid_view.set_max_columns(columns)
        return GLib.SOURCE_REMOVE

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        if not self._sort_restored:
            self._sort_restored = True
            self._update_sorts()
            self._restore_sort()
            if self._favourites_texts is not None and favourites_only(self.get_tag()):
                self._favourites_action.change_state(GLib.Variant('b', True))
        self._on_library_changed()
        self._on_favourites_changed()  # what changed while the page was hidden

    def _on_library_changed(self, *_args):
        model = self._model()
        if model is not self._sorted.get_model():
            self._sorted.set_model(model)
        self._update_sorts()
        self._update_state()

    def _update_sorts(self):
        """The orders the Sort By menu offers: the page's, and those of `data_sorts` the items
        have data for (offered()). An order no longer offered gives way to the first."""
        model = self._sorted.get_model()
        keys = tuple(key for key in self._all_sorts
                     if key not in self._data_sorts or offered(model, key))
        if keys == self._sort_keys and self._keys_menu.get_n_items():
            return
        self._sort_keys = keys
        self._keys_menu.remove_all()
        for key in keys:
            self._keys_menu.append(SORTS[key][0](), f'page.sort::{key}')
        if self._order is not None and self._order[0] not in keys and keys:
            self._sort(keys[0])

    # Favourites Only.

    def _on_favourites_only(self, action, value):
        action.set_state(value)
        favourites = value.get_boolean()
        if favourites != self._favourites_on:
            self._favourites_on = favourites
            with self._shown.replacing(self._scroll_top):
                if favourites:
                    self._filters.append(self._favourite_filter)
                else:
                    self._filters.remove(1)  # after the text's
        remember_favourites_only(self.get_tag(), favourites)
        self._update_state()

    def _on_favourites_changed(self, *_args):
        """The account's favourites changed (a sync, or a heart): Favourites Only shows the
        new ones (the tiles follow their Items' notify::favourite themselves)."""
        if self._favourites_on:
            self._favourite_filter.changed(Gtk.FilterChange.DIFFERENT)

    # The filter bar.

    def _on_filter_changed(self, bar):
        """The filter's text changed (after the entry's delay): the grid shows what matches it
        (and Favourites Only), from the top, and the new count is announced."""
        with self._shown.replacing(self._scroll_top):  # the tiles recycled (ShownModel)
            self._text_filter.set_search(bar.search or None)
        self._update_state()
        self._scroll_top()
        shown, total = self._filtered.get_n_items(), self._sorted.get_n_items()
        words = self._count_words(shown, total) if bar.search else None
        if words:
            bar.announce(words.format(shown=f'{shown:n}', total=f'{total:n}'))

    def _scroll_top(self):
        """Back to the top, where a new filter's items begin."""
        if self._shown.get_n_items():
            self.grid_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)

    def focus_filter(self):
        """Ctrl+F: the filter bar shown with the cursor in its entry; False on a page with no
        filter, or nothing to filter yet."""
        return self.filter_bar is not None and self.filter_bar.focus()

    def _focus_grid(self, obj):
        """Where Escape puts the focus once the filter bar has closed: obj's tile (the one
        the focus was on), else the first; False while the grid does not show."""
        if self.stack.get_visible_child_name() != 'items' or not self._shown.get_n_items():
            return False
        position = self._shown.find(obj) if obj is not None else None
        focus_position(self.grid_view, position or 0)
        return True

    def _update_state(self, *_args):
        library = self._library
        searched = self.filter_bar is not None and bool(self.filter_bar.search)
        filtered = self._favourites_on or searched
        total = 0 if self._missing else self._sorted.get_n_items()
        icon_name = self._icon_name
        if self._filtered.get_n_items():
            name = 'items'
        elif library.state == 'loading' or (library.state == 'empty' and library.syncing):
            name = 'loading'  # the first sync is on its way
        else:
            name = 'empty'
            if self._missing:
                title, description = self._missing_texts
            elif searched and total:  # only the text left none
                title, description = _('No Results Found'), _('Try a different filter')
                icon_name = 'edit-find-symbolic'
            elif filtered and total:
                title, description = self._favourites_texts  # only Favourites Only left none
            else:
                title, description = self._empty
            self.empty_page.set_title(title)
            self._sign_in.set_description(description)
        self.empty_page.set_icon_name(icon_name)
        self.stack.set_visible_child_name(name)
        # Shown while a filter is on, whatever it leaves, so it can be turned off.
        self.sort_button.set_visible(
            (name == 'items' and (len(self._sort_keys) > 1 or self._favourites_texts is not None))
            or (filtered and not self._missing))
        if self.filter_bar is not None:
            # Something to filter, filtered out or not; the bar goes with the last of it.
            self.filter_bar.set_available(total > 0, self)
            if not total and name == 'empty':
                self.filter_bar.close()

    # Sorting.

    def _on_sort_chosen(self, action, value):
        self._sort(value.get_string())
        tag = self.get_tag()
        settings = getattr(app(), 'settings', None)
        if tag and settings is not None:  # a root page: remembered
            sorts = dict(settings.get_value('grid-sort').unpack())
            sorts[tag] = value.get_string()
            settings.set_value('grid-sort', GLib.Variant('a{ss}', sorts))

    def _on_order_chosen(self, action, value):
        self._sort(self._sort_action.get_state().get_string(),
                   descending=value.get_string() == 'descending')

    def _restore_sort(self):
        """The order last chosen on this root page (its tag), if it still offers it."""
        tag = self.get_tag()
        settings = getattr(app(), 'settings', None)
        if not tag or settings is None:
            return
        key = settings.get_value('grid-sort').unpack().get(tag)
        if key in self._sort_keys:
            self._sort(key)

    def _sort(self, key, descending=None):
        """Show the items by `key`, `descending` or not (None: the key's own direction)."""
        if key not in self._sort_keys:
            return
        if descending is None:
            descending = SORTS[key][2]
        if (key, descending) != self._order:
            self._order = (key, descending)
            self._sort_action.set_state(GLib.Variant('s', key))
            self._order_action.set_state(GLib.Variant('s', _direction(descending)))
            sorter, backwards = make_sorter(key, descending)
            self._shown.set_backwards(backwards)
            self._sorted.set_sorter(sorter)
        # Back to the top: the grid would otherwise follow the item it showed to wherever the
        # new order puts it.
        if self._filtered.get_n_items():
            self.grid_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)

    # The tiles.

    def _on_setup(self, _factory, list_item):
        list_item.set_child(Tile(shape=self._shape, video_size=GRID_VIDEO_SIZE))

    def _on_bind(self, _factory, list_item):
        item = list_item.get_item()
        list_item.get_child().bind(item)
        bind_label(list_item, item, self._artist)
        if not self._bound:
            self._bound = True
            mark_bound(self)

    def _on_unbind(self, _factory, list_item):
        list_item.get_child().unbind()
        unbind_label(list_item)

    def _on_activate(self, _grid_view, position):
        item = self._shown.get_item(position)
        if item is not None:
            self.get_root().open_item(item)

    # The title, laid over the grid's top padding.

    def _on_scrolled(self, adjustment):
        # Only while the title is in view: past it, scrolling needs no layout from here.
        offset = min(adjustment.get_value(), self._title_height())
        if offset != self._title_offset:
            self._title_offset = offset
            self.overlay.queue_allocate()

    def _title_height(self):
        return self.title_label.measure(Gtk.Orientation.VERTICAL, -1)[1]

    def _on_title_position(self, overlay, widget, allocation):
        """Place the title at the top of the overlay, as far up as the grid has scrolled; its
        own margins put it on the page's.

        Called at each layout of the overlay, so also where the page learns its width: the
        grid's max-columns follows it, so the grid makes tiles for the columns that fit
        rather than for twelve: more at once (a window that grew paints them in this frame),
        fewer after the layout, in an idle."""
        width = overlay.get_width()
        columns = columns_for(width, self._column_width)
        current = self.grid_view.get_max_columns()
        if columns > current:
            self.grid_view.set_max_columns(columns)
        elif columns < current and self._columns_idle is None:
            self._columns_idle = GLib.idle_add(self._set_columns, columns,
                                               priority=GLib.PRIORITY_HIGH_IDLE)
        allocation.x = 0
        allocation.y = -round(self._title_offset)
        allocation.width = width
        allocation.height = self._title_height()
        return True
