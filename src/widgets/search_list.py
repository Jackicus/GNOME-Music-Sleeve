# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSearchList: one kind of a catalog search's hits as a list that loads more as it
is scrolled (a search_pager.SearchPager's), for the Search page's filter by kind and a search
shelf's See All (pages/search_all.py)."""

from gettext import gettext as _
from gettext import ngettext

from gi.repository import Adw, Gio, GObject, Gtk

from ..library import Item
from . import context_menu
from .cover import Cover
from .labels import bind_label, unbind_label
from .util import connect_weak

# A result's cover, in logical pixels, as a top hit's row has it.
COVER_SIZE = 40
# The footer's height: a result row's (its cover), so a state change never moves the list.
FOOTER_HEIGHT = COVER_SIZE
# The next page is asked for once less than this many screens are left below the view.
MORE_WITHIN = 1.0


def end_text(kind, count):
    """What the end of a list of `count` hits of `kind` (a search shelf's key) says."""
    texts = {
        # Translators: the end of a search's list of one kind of results, as each
        # of these: how many were found.
        'songs': lambda: ngettext('{count} song', '{count} songs', count),
        'albums': lambda: ngettext('{count} album', '{count} albums', count),
        'artists': lambda: ngettext('{count} artist', '{count} artists', count),
        'playlists': lambda: ngettext('{count} playlist', '{count} playlists', count),
        'music-videos': lambda: ngettext('{count} music video', '{count} music videos', count),
        'stations': lambda: ngettext('{count} station', '{count} stations', count),
        'radio-shows': lambda: ngettext('{count} radio show', '{count} radio shows', count),
        'curators': lambda: ngettext('{count} curator', '{count} curators', count),
    }
    text = texts.get(kind, lambda: ngettext('{count} result', '{count} results', count))()
    return text.format(count=f'{count:n}')


class PagerFooter(GObject.Object):
    """The list's last item, after the hits: where the next page's spinner, its failure
    (with Try Again) or the end shows."""

    __gtype_name__ = 'AppleMusicPagerFooter'


class ResultRow(Gtk.Box):
    """A recycled row of hits: the cover (round for an artist), the title and its subtitle,
    each a Gtk.Inscription (not measured again at a rebind). While bound, the row follows the
    Item (a thumbnail that arrives, notify::thumb); the Item is its `context_item`."""

    __gtype_name__ = 'AppleMusicResultRow'

    def __init__(self):
        super().__init__(spacing=12, css_classes=['search-result'])
        self._item = None
        self._handler = None
        self.cover = Cover(size=COVER_SIZE, valign=Gtk.Align.CENTER)
        self.cover.add_css_class('small')
        self.title = Gtk.Inscription(xalign=0, nat_chars=24, hexpand=True,
                                     text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END)
        self.subtitle = Gtk.Inscription(xalign=0, nat_chars=24, hexpand=True,
                                        css_classes=['caption', 'dimmed'],
                                        text_overflow=Gtk.InscriptionOverflow.ELLIPSIZE_END)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         valign=Gtk.Align.CENTER, hexpand=True)
        labels.append(self.title)
        labels.append(self.subtitle)
        self.append(self.cover)
        self.append(labels)

    @property
    def context_item(self):
        return self._item

    def bind(self, item):
        if self._item is not None:
            self.unbind()
        self._item = item
        self._handler = connect_weak(item, 'notify', self._on_item_notify)
        if item.kind == 'artist':
            self.cover.add_css_class('artist')
        else:
            self.cover.remove_css_class('artist')
        self.title.set_text(item.title)
        self.subtitle.set_text(item.subtitle or '')
        self.cover.set_paths(item.thumb, item.art)

    def unbind(self):
        if self._handler is not None:
            self._item.disconnect(self._handler)
            self._handler = None
        self._item = None
        self.cover.set_paths()

    def _on_item_notify(self, item, pspec):
        if pspec.name == 'title':
            self.title.set_text(item.title)
        elif pspec.name == 'subtitle':
            self.subtitle.set_text(item.subtitle or '')
        elif pspec.name in ('thumb', 'art') and not self.cover.set_paths(item.thumb, item.art):
            self.cover.refresh()


class FooterRow(Gtk.Box):
    """The footer's row: a spinner while there is more to come, why the next page failed
    with Try Again, or the count at the end; always FOOTER_HEIGHT high."""

    __gtype_name__ = 'AppleMusicPagerFooterRow'

    def __init__(self):
        super().__init__(spacing=12, halign=Gtk.Align.CENTER, height_request=FOOTER_HEIGHT,
                         css_classes=['search-footer'])
        self.spinner = Adw.Spinner(width_request=24, height_request=24,
                                   valign=Gtk.Align.CENTER)
        self.label = Gtk.Label(valign=Gtk.Align.CENTER, css_classes=['dimmed'])
        self.retry_button = Gtk.Button(label=_('Try Again'), valign=Gtk.Align.CENTER,
                                       css_classes=['flat'])
        self.append(self.spinner)
        self.append(self.label)
        self.append(self.retry_button)
        self.context_item = None

    def show_state(self, state, text):
        """'idle' and 'loading' the spinner; 'failed' the words and Try Again; 'done' the
        words alone."""
        self.spinner.set_visible(state in ('idle', 'loading'))
        self.label.set_visible(state in ('failed', 'done'))
        self.label.set_label(text)
        self.retry_button.set_visible(state == 'failed')


class SearchList(Gtk.ScrolledWindow):
    """A pager's hits (set_pager()) as a Gtk.ListView of ResultRows, centred in an
    Adw.ClampScrollable, then the footer (PagerFooter, a FooterRow): a Gtk.FlattenListModel of
    the pager's store and a store of the footer alone, so rows recycle as the hits grow.

    While it is shown, the pager is asked for its next page whenever less than MORE_WITHIN
    screens are left below the view (scrolled, laid out, or the last page in), so a list
    shorter than the window fills it; a pager cancel()ed is asked no more until the list is
    shown again (mapped), which resume()s it. Activating a hit emits `item-activated` (the
    page opens it and remembers it), activating the footer, or its Try Again, asks again
    after a failure. Every signal of a child is connected weakly: a pushed page drops the list.
    A subclass may show its hits in rows of its own (`row_type`, a ResultRow's subclass)."""

    __gtype_name__ = 'AppleMusicSearchList'

    row_type = ResultRow

    __gsignals__ = {
        'item-activated': (GObject.SignalFlags.RUN_FIRST, None, (Item,)),
    }

    def __init__(self, **kwargs):
        # GtkBuilder calls this without arguments on the object it has made: properties given
        # to the chain-up here would make another object, so they are set after it.
        super().__init__(**kwargs)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)
        self.list_view = Gtk.ListView(single_click_activate=True,
                                      tab_behavior=Gtk.ListTabBehavior.ITEM,
                                      css_classes=['track-list', 'search-results'])
        self.set_child(Adw.ClampScrollable(maximum_size=720, tightening_threshold=600,
                                           child=self.list_view))
        self._pager = None
        self._pager_handler = None
        self._footer_store = Gio.ListStore(item_type=PagerFooter)
        self._footer_store.append(PagerFooter())
        self._footer_item = None  # the list item showing the footer, while one does
        factory = Gtk.SignalListItemFactory()
        connect_weak(factory, 'setup', self._on_setup)
        connect_weak(factory, 'bind', self._on_bind)
        connect_weak(factory, 'unbind', self._on_unbind)
        self.list_view.set_factory(factory)
        connect_weak(self.list_view, 'activate', self._on_activate)
        # The adjustment GtkBuilder's construction leaves is not the one made by now: it is
        # followed from map (and set_pager()), and again if it is replaced.
        self._adjustment = None
        self._adjustment_handlers = ()
        self.connect('notify::vadjustment', self._on_adjustment_replaced)
        context_menu.attach(self.list_view)

    @property
    def pager(self):
        return self._pager

    def set_pager(self, pager):
        """Show `pager`'s hits (None: nothing), from the top."""
        if pager is self._pager:
            return
        if self._pager is not None:
            self._pager.disconnect(self._pager_handler)
            self._pager_handler = None
        self._pager = pager
        if pager is None:
            self.list_view.set_model(None)
            return
        self._pager_handler = connect_weak(pager, 'notify::state', self._on_state)
        models = Gio.ListStore(item_type=Gio.ListModel)
        models.append(pager.items)
        models.append(self._footer_store)
        self.list_view.set_model(Gtk.NoSelection(model=Gtk.FlattenListModel(model=models)))
        self._follow_adjustment()
        self.get_vadjustment().set_value(0)
        self._show_footer()
        self._maybe_more()

    def do_map(self):
        Gtk.ScrolledWindow.do_map(self)
        self._follow_adjustment()
        if self._pager is not None:
            self._pager.resume()  # shown again: a page left, and come back to, pages on
        self._maybe_more()

    # Paging.

    def _on_adjustment_replaced(self, *_args):
        self._follow_adjustment()

    def _follow_adjustment(self):
        adjustment = self.get_vadjustment()
        if adjustment is self._adjustment:
            return
        for handler in self._adjustment_handlers:
            self._adjustment.disconnect(handler)
        self._adjustment = adjustment
        self._adjustment_handlers = tuple(
            connect_weak(adjustment, signal, self._on_scrolled)
            for signal in ('value-changed', 'changed'))

    def _on_scrolled(self, *_args):
        self._maybe_more()

    def _on_state(self, _pager, _pspec):
        self._show_footer()
        self._maybe_more()

    def _maybe_more(self):
        pager = self._pager
        if pager is None or pager.state != 'idle' or not self.get_mapped():
            return
        adjustment = self.get_vadjustment()
        page = adjustment.get_page_size()
        if page <= 0:
            return  # not laid out yet: its page size comes with the layout
        left = adjustment.get_upper() - adjustment.get_value() - page
        if left < page * MORE_WITHIN:
            pager.request()

    def _footer_text(self):
        pager = self._pager
        if pager is None:
            return ''
        if pager.state == 'failed':
            return _('Could not load more results')
        if pager.state == 'done':
            return end_text(pager.kind, pager.items.get_n_items())
        return _('Loading more results…')

    def _show_footer(self):
        list_item = self._footer_item
        if list_item is None or self._pager is None:
            return
        state = self._pager.state
        text = self._footer_text()
        list_item.get_child().show_state(state, text)
        list_item.set_accessible_label(text)
        list_item.set_activatable(state == 'failed')

    def _retry(self, *_args):
        if self._pager is not None and self._pager.state == 'failed':
            self._pager.request()

    # Rows.

    def _on_setup(self, _factory, list_item):
        list_item.set_child(self.row_type())

    def _on_bind(self, _factory, list_item):
        item = list_item.get_item()
        row = list_item.get_child()
        if isinstance(item, PagerFooter):
            if not isinstance(row, FooterRow):
                row = FooterRow()
                connect_weak(row.retry_button, 'clicked', self._retry)
                list_item.set_child(row)
            self._footer_item = list_item
            self._show_footer()
            return
        if not isinstance(row, self.row_type):
            row = self.row_type()
            list_item.set_child(row)
        list_item.set_activatable(True)
        row.bind(item)
        bind_label(list_item, item)

    def _on_unbind(self, _factory, list_item):
        if list_item is self._footer_item:
            self._footer_item = None
            return
        row = list_item.get_child()
        if isinstance(row, ResultRow):
            row.unbind()
        unbind_label(list_item)

    def _on_activate(self, list_view, position):
        item = list_view.get_model().get_item(position)
        if isinstance(item, PagerFooter):
            self._retry()
        elif isinstance(item, Item):
            self.emit('item-activated', item)
