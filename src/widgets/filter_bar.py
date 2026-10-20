# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicFilterBar: a library page's filter, as GNOME's apps have one. The Songs table,
the Albums and Music Videos grids, the Artists list and a playlist's songs (Favourite Songs'
too) each have one, and behave alike:

- a Gtk.SearchBar under the page's header bar, its entry at a readable width, centred;
- shown by the header's toggle button (`button`, which the page packs), by Ctrl+F (the
  window's win.search asks the page's focus_filter(), which calls focus(): the cursor in the
  entry, its text selected) and by typing on the page (the bar's key-capture widget, given
  to set_available());
- closed by Escape in the entry, by Escape on the page while it shows (`capture`'s key
  controller: a pushed page's Escape would otherwise go back), or by the button: closing
  clears the entry and so the filter, and the focus goes back to the page's list
  (set_focus_return(), from an idle, once the list shows again): to the row or tile of the
  item the focus was on as the bar opened (or as Escape closed it, from the list), scrolled
  into view (widgets.util.focus_position()), else to the first, else (no list shown) to
  the button;
- typing refilters after the entry's own short delay (search-delay, 150 ms: a fast typist's
  keys refilter once), and a cleared entry at once.

`search` is the entry's text folded (library.fold): case and accents ignored. A page shows
what holds the whole of it in one of the texts of its `search_key` (library.filter_matches):
a Track's title, artist and album, an Item's title and subtitle (an album's or a video's
artist). The pages over a Gtk.FilterListModel filter with text_filter(), a Gtk.StringFilter
over that key, which matches in C, refilters only what matched when the text grows
(GTK_FILTER_CHANGE_MORE_STRICT) and, for no text, matches everything without reading a key,
set through a SearchText, which leaves the models alone on a Backspace known to bring
nothing back; they show the change through a ShownModel, which keeps or recycles the rows
(and gives a list growing back its rows a few a frame). The Songs page tests the keys
itself (pages/songs.py). The filter combines with the page's
Favourites Only (both must match), and the page announces the new count once the typing has
paused (announce()).

    bar = FilterBar(_('Filter Albums'))
    toolbar_view.add_top_bar(bar)           # under the header bar
    header_bar.pack_end(bar.button)
    connect_weak(bar, 'changed', self._on_filter_changed)   # bar.search
    bar.set_focus_return(self._focus_list)  # _focus_list(obj): True when it took it
    bar.set_available(True, self)           # the button shown; typing on the page starts it
"""

import contextlib

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from ..library import fold
from . import context_menu
from .util import GrowBack, connect_weak, holds_in_order, rows_kept, weak_method


def _search_key(obj):
    return obj.search_key


def text_filter():
    """A Gtk.StringFilter over its items' `search_key` (a Track's or an Item's), for a folded
    search (set_search(bar.search)): one Python call an item, and none for no text."""
    expression = Gtk.ClosureExpression.new(GObject.TYPE_STRING, _search_key, None)
    return Gtk.StringFilter(expression=expression,
                            match_mode=Gtk.StringFilterMatchMode.SUBSTRING, ignore_case=False)


def widens(old, new):
    """Whether the folded filter text `new` matches everything `old` matched (`new` is part
    of `old`: a Backspace), so that it can only bring items back."""
    return new in old


class SearchText:
    """A page's filter text as its Gtk.FilterListModels filter by it: `filter`, a
    text_filter() for them, set through set_search().

    A shorter text (a Backspace) makes GTK test every item the longer one left out, one Python
    call each (7 to 9 ms on 3,000 albums), though often it brings none back: from "midnight"
    to "mid" every key matched the same five albums. A text cannot match fewer items than a
    longer one containing it, so when it is known to have matched as many as show now it
    matches the same ones, and the models are left as they are: the filter's `changed` is
    stopped before it reaches them (this object's handler, connected first, stops it). What
    each text matched is known from the keys before, until the items or the page's other
    filters change: forget(), or watch() what says so."""

    def __init__(self):
        self.filter = text_filter()
        self.search = ''
        self._counts = {}  # text -> how many items it matched, since the items last changed
        self._setting = False  # within set_search(): the changes are its own
        self._quiet = False  # the filter's change stops before the models
        # Connected before any model is given the filter: it runs first.
        connect_weak(self.filter, 'changed', self._on_changed)

    def set_search(self, search, models):
        """Filter by the folded text `search` (none: everything). `models` are the
        Gtk.FilterListModels over the filter: their items are what it matches."""
        old, self.search = self.search, search
        known = self._counts.get(search)
        self._quiet = (bool(search) and known is not None and widens(old, search)
                       and known == self._count(models))
        self._setting = True
        try:
            self.filter.set_search(search or None)
        finally:
            self._setting = self._quiet = False
        self._counts[search] = self._count(models)

    def forget(self, *_args):
        """The items, or what the page's other filters let through, changed: what each
        text matched is not known any more."""
        if not self._setting:
            self._counts.clear()

    def watch(self, obj, signal):
        """forget() whenever obj emits signal, but for set_search()'s own changes (a source
        model's items-changed, another filter's changed)."""
        connect_weak(obj, signal, self.forget)

    @staticmethod
    def _count(models):
        return sum(model.get_n_items() for model in models)

    def _on_changed(self, string_filter, _change):
        if self._quiet:
            string_filter.stop_emission_by_name('changed')


# The items a ShownModel growing back gives its view at a frame by default (widgets.util.
# GrowBack): a tile about 0.7 ms to make, bind and lay out.
GROW_STEP = 12


class ShownModel(GObject.Object, Gio.ListModel):
    """`model`'s items as a list or grid shows them: in its own order or, set `backwards`,
    from the last to the first (a grid's descending text order: grid.make_sorter()), and a
    change made under replacing() shown so that its view keeps or recycles its rows.

    A Gtk.GridView or Gtk.ListView destroys the rows of the items a change removes and builds
    new ones for the items it adds, about half a millisecond a tile: a filter's change of a
    grid of 3,000 albums built a hundred and more, 50 ms a key and up. Under replacing(), a
    change that adds and removes is shown as SongsPage._show() shows a new order: the new
    items inserted in front of the old ones (the view keeps showing the old, which have
    moved down), `scroll()` (the view back to the top, onto the new: the old rows, out of
    view now, are rebound to them), then the old ones removed, rows and all gone already.

    That recycles only rows that the insertion pushes past the rows the view keeps
    (widgets.util.rows_kept()). A list of a few items keeps a row for each, and when a change
    brings many back (a Backspace from five albums to three hundred) the view would make a
    row for every new one up to the rows it keeps, 65 to 135 ms in one frame. Given its
    `view`, the model shows that change in place instead, when everything shown still is
    (widgets.util.holds_in_order()): the old items keep their rows, and the new ones go in
    between, `step` at once and `step` more at each of the view's frames until the
    view would make no more rows (widgets.util.GrowBack), `scroll()` after the first. Until
    then it shows fewer items than its model has (`growing`); finish() shows them all at
    once, and any other change does first. find() answers where an item will be.

    The model's items are kept in a list (a position here is one in it, mapped for
    `backwards`), so that the old ones can be shown beside the new while it changes."""

    def __init__(self, model, view=None, step=GROW_STEP):
        super().__init__()
        self._model = model
        self._items = [model.get_item(n) for n in range(model.get_n_items())]
        self._backwards = False
        self._scroll = None  # while replacing(): the view's move to the top
        # What shows while it is not the items in order: a replacement's new and old items,
        # or those a growth back has given the view so far.
        self._shown = None
        self._view = view.weak_ref() if view is not None else None  # it holds this model
        self._grow = GrowBack(view, self._replace, step) if view is not None else None
        connect_weak(model, 'items-changed', self._on_items_changed)

    @property
    def backwards(self):
        return self._backwards

    @property
    def growing(self):
        """Whether it shows fewer items than its model has, on their way."""
        return self._grow is not None and self._grow.pending

    def set_backwards(self, backwards):
        if backwards == self._backwards:
            return
        self.finish()
        self._backwards = backwards
        count = len(self._items)
        if count > 1:
            self.items_changed(0, count, count)

    @contextlib.contextmanager
    def replacing(self, scroll):
        """Show the model's changes meanwhile as replacements, or growing back (see the
        class), calling scroll() once the first new items show."""
        self._scroll = scroll
        try:
            yield
        finally:
            self._scroll = None

    def find(self, item):
        """The position `item` is shown at (once grown back, if it is growing: finish()
        first for a row to focus), or None."""
        try:
            index = self._items.index(item)
        except ValueError:
            return None
        return len(self._items) - 1 - index if self._backwards else index

    def finish(self):
        """Show every item now, if it was growing back."""
        if self.growing:
            self._grow.finish()

    def do_get_item_type(self):
        return self._model.get_item_type()

    def do_get_n_items(self):
        return len(self._shown if self._shown is not None else self._items)

    def do_get_item(self, position):
        if self._shown is not None:
            return self._shown[position] if position < len(self._shown) else None
        count = len(self._items)
        if position >= count:
            return None
        return self._items[count - 1 - position if self._backwards else position]

    def _in_order(self, items):
        """`items` (in the model's order) as shown."""
        return items[::-1] if self._backwards else items

    def _replace(self, position, removed, items):
        """GrowBack's change: items shown at position, in place of `removed`."""
        self._shown[position:position + removed] = items
        if not self._grow.pending:
            self._shown = None  # all of them: the items in order
        self.items_changed(position, removed, len(items))

    def _on_items_changed(self, model, position, removed, added):
        new = [model.get_item(n) for n in range(position, position + added)]
        if self._scroll is not None and (removed or added):
            old = self._shown if self._shown is not None else self._in_order(self._items)
            items = self._items[:position] + new + self._items[position + removed:]
            view = self._view() if self._view is not None else None
            if (view is not None and len(old) < rows_kept(view)
                    and holds_in_order(old, self._in_order(items))):
                # In place, a few a frame: the old items keep their rows (from what an
                # earlier growth showed).
                self._items, self._shown = items, list(old)
                self._grow.start(old, self._in_order(items))
                if not self._grow.pending:
                    self._shown = None
                self._scroll()
                return
            if removed and added:
                # The new items in front of the old, the view moved onto them, the old gone.
                if self._grow is not None:
                    self._grow.stop()  # what an earlier growth showed is the old
                head = self._in_order(items)
                self._shown = head + old
                self.items_changed(0, 0, len(head))
                self._scroll()
                self._shown = None
                self._items = items
                self.items_changed(len(head), len(old), 0)
                return
        self.finish()
        self._items[position:position + removed] = new
        if self._backwards:
            position = len(self._items) - position - added
        self.items_changed(position, removed, added)


class FilterBar(Gtk.SearchBar):
    """The filter bar of a page (see the module), named `label` ("Filter Albums"): the
    entry's placeholder and name, and the button's tooltip and name."""

    __gtype_name__ = 'AppleMusicFilterBar'

    __gsignals__ = {
        # The folded text (`search`) changed: the page filters again.
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, label):
        super().__init__()
        self.search = ''
        self._focus_return = None
        # The Item or Track whose row or tile had the focus as the bar opened (the focus
        # followed while the bar is closed), where Escape puts it back.
        self._focused = None
        self._returning = False  # from Escape until the focus is back
        self._root = None  # while mapped: the window, and its focus handler
        self._root_handler = None
        self._escape = None  # the Escape controller on the page whose keys start the filter
        self._available = False  # the page has something to filter
        self._button_hidden = False  # the button left out of the header bar for now
        self.entry = Gtk.SearchEntry(placeholder_text=label, hexpand=True)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], [label])
        self.set_child(Adw.Clamp(maximum_size=400, child=self.entry))
        # Before the bar's own handler, which closes it (and so moves the focus).
        connect_weak(self.entry, 'stop-search', self._on_stop_search)
        # The entry is the bar's own: Escape in it closes the bar, which clears it.
        self.connect_entry(self.entry)
        self.button = Gtk.ToggleButton(icon_name='edit-find-symbolic', tooltip_text=label,
                                       visible=False)
        self.button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        self.bind_property('search-mode-enabled', self.button, 'active',
                           GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        # The bar is a page's child: its children's signals are connected weakly
        # (widgets/util.py), or a popped page would never be freed.
        connect_weak(self.entry, 'search-changed', self._on_search_changed)

    @property
    def available(self):
        """Whether the page has something to filter (the button shows, unless hidden)."""
        return self._available

    def hide_button(self, hidden):
        """Leave the button out of the header bar (a list's selection mode, whose header bar
        has no room for it at 360 px), or put it back while the filter is offered. The
        filter itself stays as it is (Ctrl+F, typing on the page)."""
        self._button_hidden = bool(hidden)
        self.button.set_visible(self._available and not self._button_hidden)

    def set_available(self, available, capture=None):
        """Offer the filter (the button, and typing on `capture`, the page, starting it) or
        not (a page with nothing to filter yet). The bar stays as it is: close() closes it."""
        self._available = bool(available)
        self.button.set_visible(self._available and not self._button_hidden)
        capture = capture if available else None
        # The controller, not the page: the bar is the page's child, and holding the page
        # would keep it alive.
        widget = self._escape.get_widget() if self._escape is not None else None
        if capture is widget:
            return
        self.set_key_capture_widget(capture)
        if self._escape is not None:
            widget.remove_controller(self._escape)
            self._escape = None
        if capture is not None:
            self._escape = Gtk.EventControllerKey()
            connect_weak(self._escape, 'key-pressed', self._on_key_pressed)
            capture.add_controller(self._escape)

    def set_focus_return(self, focus):
        """Where the focus goes once Escape has closed the bar: focus(obj), a page's method
        (held weakly: the page holds the bar), puts it on obj's row or tile (the Item or
        Track the focus was on, or None: the first) and answers True, or False when the page
        shows no list to put it in (the button takes it then)."""
        self._focus_return = weak_method(focus)

    def focus(self):
        """Show the bar with the cursor in its entry, its text selected (Ctrl+F); False when
        the page has nothing to filter (the window's Ctrl+F goes to Search then)."""
        if not self.available:
            return False
        self.set_search_mode(True)
        self.entry.grab_focus()
        self.entry.select_region(0, -1)
        return True

    def set_text(self, text):
        """Filter by `text` at once, as typing it would after the entry's delay, the bar
        shown with the text in it; closed, and the filter cleared, for no text."""
        self.set_search_mode(bool(text))
        self.entry.set_text(text)
        self._on_search_changed(self.entry)

    def close(self):
        """Close the bar, which clears its entry and so the filter."""
        self.set_search_mode(False)

    def announce(self, text):
        """Say `text` (the page's new count) to assistive technology, through the window,
        while the page shows."""
        root = self.get_root()
        announce = getattr(root, 'announce', None)
        if announce is not None and self.get_mapped():
            announce(text, Gtk.AccessibleAnnouncementPriority.LOW)

    def _on_search_changed(self, entry):
        search = fold(entry.get_text())
        if search != self.search:
            self.search = search
            self.emit('changed')

    def do_map(self):
        Gtk.SearchBar.do_map(self)
        # What the focus is on, followed while the page shows: the bar opens (Ctrl+F, the
        # key capture's first key, the button) with the focus already in its entry.
        root = self.get_root()
        if root is not None:
            self._root = root
            self._root_handler = connect_weak(root, 'notify::focus-widget', self._on_focus)

    def do_unmap(self):
        Gtk.SearchBar.do_unmap(self)
        root, handler = self._root, self._root_handler
        self._root = self._root_handler = None
        if handler is not None and root.handler_is_connected(handler):
            root.disconnect(handler)

    def _on_focus(self, root, _pspec):
        """The focus moved: what it is on, while the bar is closed (not the moves of its
        opening, into the entry, or of its closing, before the focus goes back)."""
        if self._returning or self.get_search_mode():
            return
        focus = root.get_focus()
        if focus is None or not focus.is_ancestor(self):
            self._focused = self._focused_object()

    def _focused_object(self):
        """The Item or Track whose row or tile on the page has the focus, or None."""
        page = self._escape.get_widget() if self._escape is not None else None
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        if page is None or focus is None or not focus.is_ancestor(page):
            return None
        found = context_menu.find(page, focus)
        return found[1] if found is not None else None

    def _on_stop_search(self, _entry):
        # Gtk.SearchBar closes itself and clears the entry; the focus goes back to the page.
        self._returning = True
        GLib.idle_add(self._return_focus)

    def _on_key_pressed(self, _controller, keyval, _keycode, state):
        """Escape on the page (not in the entry, which stops the search itself) while the bar
        shows closes it, before a pushed page's Escape goes back."""
        if (keyval != Gdk.KEY_Escape or state & Gtk.accelerator_get_default_mod_mask()
                or not self.get_search_mode()):
            return False
        # From the list filtered: the item focused there, if the focus is on one.
        self._focused = self._focused_object() or self._focused
        self._returning = True
        self.close()
        GLib.idle_add(self._return_focus)
        return True

    def _return_focus(self):
        focused, self._returning = self._focused, False
        if self._focus_return is not None and self.get_mapped():
            if not self._focus_return(focused) and self.button.get_visible():
                self.button.grab_focus()
        return GLib.SOURCE_REMOVE
