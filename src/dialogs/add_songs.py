# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicAddSongsDialog: Add Songs… of a playlist of the user's (presented by the item
actions' ask_add_songs()).

    AddSongsDialog(app, library, playlist_title, done).present(window)

Songs are picked from one of two lists, as the Search page's toggle chooses where it looks:
Your Library, every song the library holds (Library.songs, built first when no page has
asked for it yet) narrowed by what is typed (filter_bar.text_filter(): the title, the artist
and the album, as the Songs filter matches), and Apple Music, the catalogue's songs for what
is typed (Engine.search of kind 'songs', a page at a time as the list is scrolled:
search_pager.SearchPager in a PickList, widgets/search_list.py's SearchList with rows of its
own). A click or Enter on a song picks it or unpicks it: its check box, "Selected" in its
description, the count in the header bar's subtitle, announced. The picks (selection.Picks)
are kept across both lists and every search, in the order picked. Add hands them to
done(objects) (ItemActions.add_items_to_playlist(): one write, one toast) and closes;
Cancel, and Escape once the entry is empty, close without adding. The focus starts in the
entry, and Enter there moves it to the list's first song. Nothing else typed goes to the
entry (no key capture: it would take the list's own keys, Enter's release among them).

Apple Music's states are widgets.engine_status.EngineStatus's: the spinner while the engine
starts, Start Engine, Sign In…, Try Again (the demo's invented catalogue answers searches);
with nothing typed it says what to do, and a search that finds nothing says so. A dialog can
be dropped: its children's signals are connected weakly (widgets/util.py), and the library
is followed only while it is open.
"""

import logging
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Adw, Gtk

from ..library import Item, Track, fold
from ..search_pager import SearchPager
from ..selection import Picks
from ..widgets.engine_status import EngineStatus
from ..widgets.filter_bar import text_filter
from ..widgets.labels import track_label
from ..widgets.search_list import PagerFooter, ResultRow, SearchList
from ..widgets.selection_mode import selection_words
from ..widgets.util import connect_weak, focus_position

log = logging.getLogger(__name__)

LIBRARY = 'library'
CATALOG = 'catalog'


def picked_text(count, playlist=''):
    """The header bar's subtitle: how many songs are picked, or the playlist they go to."""
    if count:
        return ngettext('{count} song selected', '{count} songs selected',
                        count).format(count=f'{count:n}')
    # Translators: under Add Songs in its dialog's header bar: the playlist they go to.
    return _('To “{playlist}”').format(playlist=playlist) if playlist else ''


def track_subtitle(track):
    """A library song's second line: its artist and album, each that is there."""
    return ' · '.join(part for part in (track.artist, track.album) if part)


class PickRow(ResultRow):
    """A song to pick: the result row (cover, title, subtitle) after a check box, which
    shows whether it is picked; the row's own description says so (the box is
    decoration). A library Track or a catalogue song Item."""

    __gtype_name__ = 'AppleMusicPickRow'

    def __init__(self):
        super().__init__()
        self.check = Gtk.CheckButton(can_focus=False, can_target=False,
                                     valign=Gtk.Align.CENTER,
                                     accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.prepend(self.check)

    def bind_track(self, track):
        """Show a library Track (which has no notify the row follows: its title and its
        album's thumbnail are the library's)."""
        if self._item is not None:
            self.unbind()
        self._item = track
        self.cover.remove_css_class('artist')
        self.title.set_text(track.title)
        self.subtitle.set_text(track_subtitle(track))
        self.cover.set_paths(track.thumb)

    def set_picked(self, picked):
        if self.check.get_active() != picked:
            self.check.set_active(picked)


def _describe(list_item, picked):
    selected, unselected = selection_words()
    list_item.set_accessible_description(selected if picked else unselected)


class PickList(SearchList):
    """Apple Music's songs for a search, as SearchList pages them, in PickRows marked from
    `picks` (set_picks()): the rows bound are marked again whenever the picks change."""

    __gtype_name__ = 'AppleMusicPickList'

    row_type = PickRow

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.picks = None
        self._bound = set()

    def set_picks(self, picks):
        self.picks = picks
        connect_weak(picks, 'changed', self._on_picks_changed)

    def _on_bind(self, factory, list_item):
        SearchList._on_bind(self, factory, list_item)
        item = list_item.get_item()
        if isinstance(item, PagerFooter) or self.picks is None:
            self._bound.discard(list_item)
            return
        self._bound.add(list_item)
        picked = self.picks.has(item)
        list_item.get_child().set_picked(picked)
        _describe(list_item, picked)

    def _on_unbind(self, factory, list_item):
        self._bound.discard(list_item)
        SearchList._on_unbind(self, factory, list_item)

    def _on_picks_changed(self, picks):
        for list_item in self._bound:
            picked = picks.has(list_item.get_item())
            list_item.get_child().set_picked(picked)
            _describe(list_item, picked)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/add_songs.ui')
class AddSongsDialog(Adw.Dialog):
    """Add Songs… (see the module): `done(objects)` gets the songs picked, in order."""

    __gtype_name__ = 'AppleMusicAddSongsDialog'

    window_title = Gtk.Template.Child()
    cancel_button = Gtk.Template.Child()
    add_button = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    scope_toggle = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    library_view = Gtk.Template.Child()
    catalog_list = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    status_button = Gtk.Template.Child()

    def __init__(self, app, library, playlist_title='', done=None):
        super().__init__()
        self._app = app
        self._library = library
        self._playlist_title = playlist_title
        self._done = done
        self._parent = None  # the window presented over: its announce()
        self.picks = Picks()
        self.term = ''  # what is typed, its spaces collapsed
        self._pager = None  # Apple Music's songs for `term`, once asked
        self._topped = None  # the pager whose first page the list was scrolled to
        self._bound = set()  # the library list's items bound
        self._songs_handler = None  # the library's songs-ready, while it is awaited
        self.status = None  # what the status page shows, when it shows
        self._engine_status = EngineStatus(app, self._show_status, self._search_catalog, {
            'engine-down': _('Start the engine to search Apple Music'),
            'not-signed-in': _('Songs from Apple Music appear once you sign in'),
            'failed': _('Could Not Search Apple Music'),
            'demo': _('Search Apple Music for songs of the demo’s invented catalogue'),
        })

        # The library's songs, narrowed by what is typed (filtered a little at a time, so a
        # big library never holds a frame).
        self._text_filter = text_filter()
        self._library_model = Gtk.FilterListModel(model=self._library.songs,
                                                  filter=self._text_filter, incremental=True)
        factory = Gtk.SignalListItemFactory()
        # Weakly (widgets/util.py): a bound method would keep every closed dialog alive.
        connect_weak(factory, 'setup', self._on_setup)
        connect_weak(factory, 'bind', self._on_bind)
        connect_weak(factory, 'unbind', self._on_unbind)
        self.library_view.set_factory(factory)
        self.library_view.set_model(Gtk.NoSelection(model=self._library_model))
        connect_weak(self.library_view, 'activate', self._on_library_activate)
        connect_weak(self._library_model, 'items-changed', self._on_library_changed)
        connect_weak(self._library_model, 'notify::pending', self._on_library_changed)

        self.catalog_list.set_picks(self.picks)
        connect_weak(self.catalog_list, 'item-activated', self._on_catalog_activated)
        connect_weak(self.picks, 'changed', self._on_picks_changed)
        connect_weak(self.search_entry, 'search-changed', self._on_search_changed)
        connect_weak(self.search_entry, 'stop-search', self._on_stop_search)
        connect_weak(self.search_entry, 'activate', self._on_entry_activate)
        connect_weak(self.scope_toggle, 'notify::active-name', self._on_scope_changed)
        connect_weak(self.cancel_button, 'clicked', self._on_cancel_clicked)
        connect_weak(self.add_button, 'clicked', self._on_add_clicked)
        connect_weak(self.status_button, 'clicked', self._on_status_clicked)
        self.set_focus(self.search_entry)
        self.connect('closed', AddSongsDialog._on_closed)
        self._update_title()
        self._show_scope()

    @property
    def scope(self):
        """Where the songs come from: LIBRARY or CATALOG."""
        return self.scope_toggle.get_active_name() or LIBRARY

    def present(self, parent=None):
        self._parent = parent
        if not self._library.songs_ready:
            # Built a few albums at a time; the spinner until it is there.
            self._songs_handler = connect_weak(self._library, 'notify::songs-ready',
                                               self._on_library_changed)
            self._app.spawn(self._library.build_songs())
        Adw.Dialog.present(self, parent)
        self._show_scope()

    def do_map(self):
        Adw.Dialog.do_map(self)
        self._engine_status.watch()

    def do_unmap(self):
        self._engine_status.unwatch()
        Adw.Dialog.do_unmap(self)

    # What is typed, and where it looks.

    def _on_search_changed(self, entry):
        term = ' '.join(entry.get_text().split())
        if term == self.term:
            return
        self.term = term
        self._text_filter.set_search(fold(term) or None)
        if self.scope == CATALOG:
            self._search_catalog()
        else:
            self._pager_stop()  # asked again for this text if Apple Music is shown
        self._show_scope()

    def _on_scope_changed(self, *_args):
        if self.scope == CATALOG and (self._pager is None or self._pager.term != self.term):
            self._search_catalog()
        self._show_scope()

    def _on_stop_search(self, entry):
        """Escape in the entry: what is typed cleared, or, with nothing typed, the dialog
        closed (Escape anywhere else closes it at once)."""
        if entry.get_text():
            entry.set_text('')
        else:
            self.close()

    def _on_entry_activate(self, _entry):
        """Enter in the entry: the focus on the first song shown."""
        view = self.library_view if self.scope == LIBRARY else self.catalog_list.list_view
        model = view.get_model()
        if model is not None and model.get_n_items() and view.get_mapped():
            focus_position(view, 0)

    def _search_catalog(self):
        """Ask Apple Music for its songs for what is typed (again: Try Again, the engine up),
        a page now and more as the list is scrolled."""
        self._pager_stop()
        self._engine_status.clear()
        self._pager = None
        if self.term:
            engine = self._app.engine
            self._pager = SearchPager(self.term, 'songs', search=engine.search,
                                      spawn=self._app.spawn)
            connect_weak(self._pager, 'notify::state', self._on_pager_state)
        self.catalog_list.set_pager(self._pager)
        if self._pager is not None:
            self._pager.request()
        self._show_scope()

    def _pager_stop(self):
        if self._pager is not None:
            self._pager.cancel()

    def _on_pager_state(self, pager, _pspec):
        if pager is not self._pager:
            return
        if pager.state == 'failed' and not pager.items.get_n_items():
            self._engine_status.fail(pager.error)  # the status page says what it means
            return
        if pager.items.get_n_items() and self._topped is not pager:
            # The first page in, ahead of the footer the list showed alone: the list kept
            # to the footer as they came, so from the top.
            self._topped = pager
            self.catalog_list.list_view.scroll_to(0, Gtk.ListScrollFlags.NONE, None)
        self._show_scope()

    def _on_library_changed(self, *_args):
        if self._songs_handler is not None and self._library.songs_ready:
            self._library.disconnect(self._songs_handler)
            self._songs_handler = None
        if self.scope == LIBRARY:
            self._show_scope()

    def _show_scope(self):
        """What the dialog shows for where it looks and what is typed: the list, the
        spinner, or the status page's words."""
        if self.scope == LIBRARY:
            if not self._library.songs_ready:
                self._show('loading')
            elif self._library_model.get_n_items() or self._library_model.get_pending():
                self._show(LIBRARY)
            elif self.term:
                self._show_page('no-results', 'edit-find-symbolic', _('No Results Found'),
                                _('No song in your library matches'))
            else:
                self._show_page('empty', 'music-note-symbolic', _('No Songs'),
                                _('Your library has no songs yet'))
            return
        if not self.term:
            self._show_page('search', 'edit-find-symbolic', _('Search Apple Music'),
                            _('Find songs to add to the playlist'))
            return
        if self._engine_status.status is not None:
            return  # EngineStatus shows its state (or the spinner while the engine starts)
        pager = self._pager
        if pager is not None and pager.items.get_n_items():
            self._show(CATALOG)
        elif pager is None or pager.state in ('idle', 'loading'):
            self._show('loading')
        else:
            self._show_page('no-results', 'edit-find-symbolic', _('No Results Found'),
                            _('Try a different search'))

    def _show(self, name):
        self.status = None
        self.stack.set_visible_child_name(name)

    def _show_page(self, status, icon_name, title, description, button=None):
        self.status = status
        self.status_page.set_icon_name(icon_name)
        self.status_page.set_title(title or '')
        self.status_page.set_description(description or '')
        self.status_button.set_label(button or '')
        self.status_button.set_visible(bool(button))
        self.stack.set_visible_child_name('status')

    def _show_status(self, status, title, description, button):
        """EngineStatus's states, while Apple Music is shown."""
        if self.scope != CATALOG:
            return
        if status == 'loading':
            self._show('loading')
            return
        self._show_page(status, 'edit-find-symbolic', title, description, button)

    def _on_status_clicked(self, _button):
        self._engine_status.activate()

    # The library's songs.

    def _on_setup(self, _factory, list_item):
        list_item.set_child(PickRow())

    def _on_bind(self, _factory, list_item):
        track = list_item.get_item()
        row = list_item.get_child()
        row.bind_track(track)
        picked = self.picks.has(track)
        row.set_picked(picked)
        list_item.set_accessible_label(track_label(track))
        _describe(list_item, picked)
        self._bound.add(list_item)

    def _on_unbind(self, _factory, list_item):
        self._bound.discard(list_item)
        list_item.get_child().unbind()

    def _on_library_activate(self, _view, position):
        track = self._library_model.get_item(position)
        if isinstance(track, Track):
            self.picks.toggle(track)

    def _on_catalog_activated(self, _list, item):
        if isinstance(item, Item):
            self.picks.toggle(item)

    # The picks.

    def _on_picks_changed(self, picks):
        for list_item in self._bound:
            picked = picks.has(list_item.get_item())
            list_item.get_child().set_picked(picked)
            _describe(list_item, picked)
        self._update_title()
        announce = getattr(self._parent, 'announce', None)
        if announce is not None and self.get_mapped():
            announce(picked_text(picks.count) or _('No songs selected'),
                     Gtk.AccessibleAnnouncementPriority.MEDIUM)

    def _update_title(self):
        self.window_title.set_subtitle(picked_text(self.picks.count, self._playlist_title))
        self.add_button.set_sensitive(self.picks.count > 0)

    def _on_add_clicked(self, _button):
        objects = self.picks.objects()
        done, self._done = self._done, None
        self.close()
        if objects and done is not None:
            done(objects)

    def _on_cancel_clicked(self, _button):
        self.close()

    def _on_closed(self):
        self._engine_status.unwatch()
        self._pager_stop()
        if self._songs_handler is not None:
            self._library.disconnect(self._songs_handler)
            self._songs_handler = None
        self._done = None  # the actions it holds go with the dialog
        # Once shown for a frame, the dialog's own content stayed behind it, held by the
        # sheet libadwaita 1.9 showed it in (tests/test_page_lifetime.py): let go of it
        # here, after the closing animation.
        self.set_child(None)
