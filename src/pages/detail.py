# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicDetailPage: an album or a playlist, its cover, titles, Play and Shuffle over its
tracks; a playlist's as a table (title, artist, album, time) in a wide window.

One Gtk.ListView holds the whole page. Its model flattens a store of sections
(Gtk.FlattenListModel, whose sections are its models): first a store of one marker item, whose
row the factory fills with the page's hero, then each group's store of tracks, headed "Disc 1",
"Disc 2"… when there is more than one. Why not the hero above a list per group in a box: a
Gtk.ListView recycles its rows only as the scrollable child of a Gtk.ScrolledWindow; in a box it
builds a row for every track, up to 200, and leaves the rest blank, and a playlist can hold
thousands of songs. Why not the hero in a list header: Tab never reaches the buttons of a
header, where it does reach an item's.

A playlist's tracks are a table while the page is at least 720sp wide (`table`, which
follows detail.blp's table_breakpoint): each row's title, artist and album in columns
(TrackRow's table rows, the artist and the album links), under a header of column titles
(the tracks' section's list header, TrackTableHeader). An album's stay a numbered list, and
so does any page in a narrower window.

Under a playlist the user can change (wants_suggestions()), the songs Apple suggests adding
to it (Engine.playlist_suggestions), as music.apple.com shows them: one more section after
the tracks, a store of one marker item whose row holds a SongShelf of them
(offer_suggestions: an Add button on each, and Refresh), less the songs the playlist holds
(suggested_items()). The section is left out while there are none to show, the engine
unable to answer among them: a failure is only logged.
"""

import bisect
import logging
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from ..backend.errors import EngineError
from ..library import Item, ShelfModel, Track
from ..related import catalog_target
from ..remote import fetch_cover, fetch_shelf_art, remote_item
from ..widgets import context_menu, track_links
from ..widgets.cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from ..widgets.engine_status import EngineStatus
from ..widgets.labels import track_label
from ..widgets.song_shelf import SongShelf
from ..widgets.track_row import PlayingMark, TrackRow, TrackTableHeader
from ..widgets.util import HeaderTitle, MappedHandlers, connect_weak, weak_method
from . import SignInOffer, app, show_notes

log = logging.getLogger(__name__)

# The kinds whose tracks the engine's item() fetches when an Item came without them.
FETCHED_KINDS = ('album', 'playlist')


def resolve_artist(library, item):
    """The artist Item an album's subtitle names, for the link to their page: by the artist
    id the album carries, if any, else the library's artist of that name (case folded), else
    None (the subtitle stays plain text). Only albums: a playlist's subtitle is its curator."""
    if item is None or item.kind != 'album' or not item.subtitle:
        return None
    artist_id = item.raw.get('artistId')
    if artist_id:
        found = library.by_id('artist', artist_id)
        if found is not None:
            return found
    name = item.subtitle.casefold()
    return next((artist for artist in library.artists if artist.title.casefold() == name),
                None)


def links_catalog_artist(item):
    """Whether an album's subtitle links to its catalog artist, which the engine looks up
    (related.catalog_target): a catalog album with an artist's name, outside the demo."""
    application = app()
    return (item is not None and item.kind == 'album' and bool(item.subtitle)
            and catalog_target(item) is not None
            and application is not None and not application.demo)


def should_fetch(item, fetched):
    """Whether a page showing `item` asks the engine for its tracks: it came without them (a
    shelf's, a search's, an artist's album the library lacks), it is of a kind the engine
    fetches, and this page has not asked for this Item already (`fetched`): an answer
    without tracks (an empty album or playlist) is shown as such, not asked for again."""
    return (item is not None and not item.groups and item.kind in FETCHED_KINDS
            and fetched is not item)


def wants_suggestions(item):
    """Whether a page showing `item` offers the songs Apple suggests adding to it: a library
    playlist the user can change (Item.editable: not Favourite Songs, not one of Apple's), as
    music.apple.com offers them."""
    return item is not None and item.kind == 'playlist' and item.editable


def held_songs(item):
    """The ids of the songs a playlist holds: its tracks' catalog ids and their own."""
    held = set()
    for group in item.groups:
        for track in group.entries:
            held.update(song_id for song_id in (track.catalog_id, track.id) if song_id)
    return held


def suggested_items(items, held, dropped=()):
    """The suggested song Items to show: those the playlist does not hold (`held`, by id)
    and that were not added from the page (`dropped`), in Apple's order."""
    return [item for item in items if item.id not in held and item.id not in dropped]


class _Hero(GObject.Object):
    """The first item of a detail page's list: where the hero goes."""

    __gtype_name__ = 'AppleMusicDetailHero'


class _Suggestions(GObject.Object):
    """The last item of a playlist's list, while it has suggestions: where they go."""

    __gtype_name__ = 'AppleMusicDetailSuggestions'


class _Row(Gtk.Box):
    """A row of a detail page's list: a TrackRow, or a widget of the page's (the hero, the
    suggestions) in its place."""

    def __init__(self):
        super().__init__()
        self.track_row = TrackRow(hexpand=True)
        self.append(self.track_row)

    def show_widget(self, widget):
        self._remove_widgets(keep=widget)
        parent = widget.get_parent()
        if parent is not self:
            if parent is not None:
                parent.remove(widget)
            self.append(widget)
        self.track_row.set_visible(False)

    def show_track(self, track, album_artist, table=False, playing=False):
        self._remove_widgets()
        self.track_row.set_visible(True)
        self.track_row.bind(track, album_artist, table, playing)

    def clear(self):
        self._remove_widgets()
        self.track_row.unbind()

    def _remove_widgets(self, keep=None):
        child = self.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            if child is not self.track_row and child is not keep:
                self.remove(child)
            child = following


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/detail.ui')
class DetailPage(Adw.NavigationPage):
    """An album's or a playlist's page.

    DetailPage(library, item) shows item, pushed over the page it was opened from, and titled
    by it. As a destination's root page (Favourite Songs, a sidebar playlist),
    DetailPage(library, find=function, root=True, title=…) shows whatever find() returns,
    asked again whenever the library changes: a spinner while it loads, an empty state
    (icon_name, empty_title, empty_description) when find() has nothing.

    Either way the page follows the Item it shows while it is shown: a reload keeps the Item
    and tells what changed, through `notify` (the hero's labels and cover) and
    `groups-changed` (the tracks), and do_map catches up with what changed while it was
    hidden. An Item that came without its tracks has them fetched once (should_fetch());
    the fetch is cancelled when the page is hidden (do_hidden), and asked again when it
    shows. The Player is followed the same way (`notify::track`, while shown): the rows of
    the track playing are marked (TrackRow's play icon and bold title, "Playing" as the
    row's accessible description), every bound row again as the item changes. A click on a
    track plays its group from it, as Enter does (the list's single-click-activate).

    The hero: an album's artist links to what the library holds of them when it has them
    (resolve_artist(), window.open_item()), else to Apple Music's page of them when the
    catalog can say (links_catalog_artist()), as Go to Artist opens it
    (window.item_actions.go_to()); a More Options menu
    button offers the item's own menu (window.item_actions), and the notes show three lines,
    with More for the whole text. The header bar shows the title once the hero's has scrolled
    away (HeaderTitle). Tab from the hero's last button goes on into the tracks, and Shift+Tab
    from the first track back to it.
    """

    __gtype_name__ = 'AppleMusicDetailPage'

    _table = False  # the `table` property

    def _get_table(self):
        return self._table

    def _set_table(self, table):
        if table != self._table:
            self._table = table
            self._update_headers()
            for list_item in self._bound:
                self._show_track(list_item, list_item.get_item())

    table = GObject.Property(type=bool, default=False, getter=_get_table, setter=_set_table,
                             nick='Table', blurb="A playlist's tracks as a table (wide)")

    table_breakpoint = Gtk.Template.Child()
    header_bar = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()
    list_view = Gtk.Template.Child()
    hero = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    subtitle_label = Gtk.Template.Child()
    artist_button = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()
    caption_label = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    shuffle_button = Gtk.Template.Child()
    more_button = Gtk.Template.Child()
    summary_box = Gtk.Template.Child()
    summary_label = Gtk.Template.Child()
    more_notes_button = Gtk.Template.Child()
    scrolled_window = Gtk.Template.Child()
    status_box = Gtk.Template.Child()
    status_icon = Gtk.Template.Child()
    status_spinner = Gtk.Template.Child()
    status_title = Gtk.Template.Child()
    status_description = Gtk.Template.Child()
    status_button = Gtk.Template.Child()

    def __init__(self, library, item=None, find=None, root=False, title=None, icon_name=None,
                 empty_title=None, empty_description=None):
        super().__init__(title=title or (item.title if item is not None else ''))
        self.item = None  # what the page shows
        self._library = library
        self._find = find
        self._root = root
        self._album_artist = None  # an album's artist, whose name its rows leave out
        self._groups = 0  # the sections of tracks shown
        self._bound = set()  # the list items bound to tracks: shown again as `table` changes
        self._starts = []  # the list position of each section of tracks
        self._headings = []  # and its heading
        self._fetched = None  # the Item this page asked the engine for (once: should_fetch)
        self._fetch_task = None
        self._shown_groups = None  # item.groups when the tracks were shown: a new list is new
        self._artist = None  # the library's artist Item the subtitle names, if any
        self._painted = None  # (frame clock, handler): the notes' More follows each paint
        self._focused = False  # the page has put the focus on Play once, as it was pushed
        # The songs Apple suggests (wants_suggestions): the Items of its last answer, those
        # added from here, the Item they were asked for, those shown, and the shelf that
        # shows them, made when there are some (_suggestions_shelf()).
        self._suggestion_items = []
        self._dropped = set()
        self._suggested_for = None
        self._suggestions_task = None
        self._suggestion_art_task = None
        self._suggestions = None
        self.suggestions_shelf = None
        # What the status box says when the engine cannot answer, and what its button does.
        self._engine_status = EngineStatus(app(), self._show_status, self._refetch, {
            'engine-down': _('Start the engine to load the songs'),
            'not-signed-in': _('The songs appear once you sign in to Apple Music'),
            'failed': _('Could Not Load the Songs'),
        })

        self.empty_page.set_icon_name(icon_name)
        self.empty_page.set_title(empty_title or self.get_title())
        self.empty_page.set_description(empty_description)
        if root:  # a destination's page (Favourite Songs): Sign In… while signed out
            self._sign_in = SignInOffer(self.empty_page)

        # Every signal of a child or of an object the page holds is connected weakly
        # (widgets/util.py): a bound method would keep the page alive once popped.
        factory = Gtk.SignalListItemFactory()
        connect_weak(factory, 'setup', self._on_setup)
        connect_weak(factory, 'bind', self._on_bind)
        connect_weak(factory, 'unbind', self._on_unbind)
        self.list_view.set_factory(factory)
        connect_weak(self.list_view, 'activate', self._on_activate)
        context_menu.attach(self.list_view, drag=True)  # the tracks' menus, dragged to playlists
        track_links.attach(self.list_view)  # a table's artist and album links
        self._header_factory = Gtk.SignalListItemFactory()
        connect_weak(self._header_factory, 'setup', self._on_setup_header)
        connect_weak(self._header_factory, 'bind', self._on_bind_header)
        self._table_header_factory = Gtk.SignalListItemFactory()
        connect_weak(self._table_header_factory, 'setup', self._on_setup_table_header)
        connect_weak(self._table_header_factory, 'bind', self._on_bind_table_header)
        connect_weak(self.table_breakpoint, 'apply', self._on_table_apply)
        connect_weak(self.table_breakpoint, 'unapply', self._on_table_unapply)
        connect_weak(self.play_button, 'clicked', self._on_play_clicked)
        connect_weak(self.shuffle_button, 'clicked', self._on_shuffle_clicked)
        connect_weak(self.status_button, 'clicked', self._on_status_clicked)
        connect_weak(self.artist_button, 'clicked', self._on_artist_clicked)
        connect_weak(self.more_notes_button, 'clicked', self._on_more_notes_clicked)
        self.more_button.set_create_popup_func(weak_method(self._on_more_popup))
        self._header_title = HeaderTitle(self.header_bar, self.title_label, self.scrolled_window)
        # Tab from the hero's last button goes on into the tracks (_on_list_key_pressed).
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        connect_weak(keys, 'key-pressed', self._on_list_key_pressed)
        self.list_view.add_controller(keys)

        # The library, the Item shown (_watch) and the Player's item, followed while the
        # page is shown (a test's stand-in application may have no player).
        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._follow)
        self._handlers.add(library, 'changed', self._follow)
        self._playing = PlayingMark(getattr(app(), 'player', None))
        if self._playing.player is not None:
            self._handlers.add(self._playing.player, 'notify::track', self._on_track_changed)

        self._hero_section = Gio.ListStore(item_type=GObject.Object)
        self._hero_section.append(_Hero())
        self._suggestions_section = Gio.ListStore(item_type=GObject.Object)
        self._suggestions_section.append(_Suggestions())
        self._suggestions_start = None  # the list position of the suggestions, while shown
        self._sections = Gio.ListStore(item_type=Gio.ListModel)
        self._rows = Gtk.FlattenListModel(model=self._sections)
        self.list_view.set_model(Gtk.NoSelection(model=self._rows))

        self._show(item)

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        self._follow()  # what a reload changed while the page was hidden
        self._update_playing()  # and the item playing now
        self._engine_status.watch()
        if should_fetch(self.item, self._fetched):
            self._fetch(self.item)  # a fetch cancelled when the page was hidden
        self._suggest()
        clock = self.get_frame_clock()
        if clock is not None and self._painted is None:
            self._painted = (clock, connect_weak(clock, 'after-paint', self._on_painted))

    def do_unmap(self):
        self._engine_status.unwatch()
        if self._painted is not None:
            clock, handler = self._painted
            clock.disconnect(handler)
            self._painted = None
        Adw.NavigationPage.do_unmap(self)

    def do_shown(self):
        # A push focuses the page's first button, the artist's link: Play is the hero's.
        if not self._focused:
            self._focused = True
            focus = self.get_root().get_focus() if self.get_root() is not None else None
            if focus is not None and (focus is self.artist_button
                                      or focus.is_ancestor(self.artist_button)):
                self.play_button.grab_focus()
        Adw.NavigationPage.do_shown(self)

    def do_hidden(self):
        # Left (popped, covered, or another destination shown), not just unmapped (a push
        # maps, unmaps and maps a page again): the fetch stops, asked again when shown.
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
            self._fetch_task = None
            self._fetched = None
            self._engine_status.clear()
        for task in (self._suggestions_task, self._suggestion_art_task):
            if task is not None and not task.done():
                task.cancel()
        if not self._suggestion_items:
            self._suggested_for = None  # asked again when shown: none came this time
        Adw.NavigationPage.do_hidden(self)

    def _follow(self, *_args):
        item = self._find() if self._find is not None else self.item
        if item is not self.item or (item is not None and item.groups is not self._shown_groups):
            self._show(item)
        self._update_state()

    def _update_state(self):
        if self.item is not None:
            name = 'item'
        elif self._library.state == 'loading':
            name = 'loading'
        else:
            name = 'empty'
        self.stack.set_visible_child_name(name)

    def _watch(self, old, item):
        """Follow the Item shown (and no longer the one shown before)."""
        if old is not None:
            self._handlers.remove(old)
        if item is not None:
            self._handlers.add(item, 'groups-changed', self._on_groups_changed)
            self._handlers.add(item, 'notify', self._on_item_notify)

    def _on_groups_changed(self, item):
        if item is self.item:
            self._show(item)

    def _on_item_notify(self, item, _pspec):
        if item is self.item:
            self._show_hero(item)

    def _show(self, item):
        if item is not self.item:
            self._watch(self.item, item)
            self.item = item
        if item is None:
            self._shown_groups = None
            self._suggestions_start = None
            self._sections.remove_all()
            self._update_state()
            return
        self._album_artist = item.subtitle if item.kind == 'album' else None
        self._show_hero(item)

        self._shown_groups = item.groups
        groups = [group for group in item.groups if group.entries.get_n_items()]
        self._starts = []
        self._headings = []
        position = 1  # after the hero
        for number, group in enumerate(groups, 1):
            self._starts.append(position)
            self._headings.append(self._heading(item, group, number))
            position += group.entries.get_n_items()

        # An item that came without its tracks (a shelf's) gets them from the engine, once.
        if should_fetch(item, self._fetched):
            self._fetch(item)
        elif groups:
            self._engine_status.clear()
        elif self._engine_status.status is None:
            self._show_empty()  # no tracks: none came, or an answer brought none
        self.status_box.set_visible(not groups)
        self._update_buttons()

        self._groups = len(groups)
        self._update_headers()
        sections = [self._hero_section] + [group.entries for group in groups]
        self._suggestions_start = None
        if groups and wants_suggestions(item):
            self._suggest()
            shown = suggested_items(self._suggestion_items, held_songs(item), self._dropped)
            if shown or self._suggestions is not None:
                self._suggestions_shelf()
                self._suggestions.update(self._suggestions.title, shown)
            if shown:
                self._suggestions_start = position
                sections.append(self._suggestions_section)
        self._sections.splice(0, self._sections.get_n_items(), sections)
        self._update_state()

    # The songs Apple suggests adding to a playlist.

    def _suggestions_shelf(self):
        """The shelf of suggestions (and its model), made the first time there are some."""
        if self.suggestions_shelf is None:
            # Translators: the title of the songs Apple Music suggests adding to a playlist,
            # shown under its songs.
            self._suggestions = ShelfModel('suggested', _('Suggested Songs'), [])
            shelf = SongShelf(margin_top=18, margin_bottom=12)
            # Translators: the line under a playlist's Suggested Songs.
            shelf.offer_suggestions(_('Based on what’s in this playlist'))
            shelf.set_inset()  # in a track list's row, which keeps the page's margins
            shelf.bind_shelf(self._suggestions)
            connect_weak(shelf, 'add-song', self._on_add_suggestion)
            connect_weak(shelf, 'refresh', self._on_refresh_suggestions)
            self.suggestions_shelf = shelf
        return self.suggestions_shelf

    def _suggest(self):
        """Ask for the suggestions of the playlist shown, once (wants_suggestions), while
        the page is mapped."""
        item = self.item
        if not wants_suggestions(item) or self._suggested_for is item or not self.get_mapped():
            return
        if self._suggested_for is not None:
            self._suggestion_items = []
            self._dropped = set()
        self._suggested_for = item
        self._fetch_suggestions(item)

    def _fetch_suggestions(self, item, refresh=False):
        if self._suggestions_task is not None and not self._suggestions_task.done():
            self._suggestions_task.cancel()
        self._suggestions_task = app().spawn(self._load_suggestions(item, refresh))

    async def _load_suggestions(self, item, refresh):
        try:
            answer = await app().engine.playlist_suggestions(item.id, refresh=refresh)
        except EngineError as error:
            log.info('suggestions for playlist %s: %s', item.id, error)
            return
        if self.item is not item:
            return
        self._suggestion_items = [
            Item(remote_item(entry)) for entry in answer.get('items') or []
            if isinstance(entry, dict) and entry.get('id') and entry.get('kind') == 'song']
        self._dropped = set()
        self._show(item)
        if self._suggestion_art_task is not None and not self._suggestion_art_task.done():
            self._suggestion_art_task.cancel()
        if self._suggestions is not None:
            self._suggestion_art_task = app().spawn(fetch_shelf_art([self._suggestions]))

    def _on_refresh_suggestions(self, _shelf):
        if wants_suggestions(self.item):
            self._fetch_suggestions(self.item, refresh=True)

    def _on_add_suggestion(self, _shelf, song):
        """Add a suggested song to the playlist (the item actions' Add to Playlist, which
        fetches the playlist again), and take it out of the suggestions."""
        actions = getattr(self.get_root(), 'item_actions', None)
        if actions is None or self.item is None:
            return
        if actions.add_to_playlist(self.item.id, song.id, song.title) is not None:
            self._dropped.add(song.id)
            self._show(self.item)

    def _on_table_apply(self, _breakpoint):
        self.table = True

    def _on_table_unapply(self, _breakpoint):
        self.table = False

    def _is_table(self):
        """Whether the tracks show as a table: a playlist's (not an album's) one list of
        them (several would each want their own column titles), wide."""
        return (self._table and self._groups == 1 and self.item is not None
                and self.item.kind != 'album')

    def _update_headers(self):
        """The list's section headers: an album's discs ("Disc 2"), a table's column titles,
        or none."""
        if self._groups > 1:
            factory = self._header_factory
        elif self._is_table():
            factory = self._table_header_factory
        else:
            factory = None
        if self.list_view.get_header_factory() is not factory:
            self.list_view.set_header_factory(factory)

    def _show_hero(self, item):
        """The hero's cover, labels and buttons for item."""
        if not self._root:
            self.set_title(item.title)
        self.cover.set_paths(item.art, item.thumb)  # the 640 px cover, else the thumbnail
        if item.raw.get('artUrl'):
            # A sync fetches thumbnails only: the cover comes now, if it is not on disk yet.
            app().spawn(self._fetch_cover(item))
        self.title_label.set_label(item.title)
        self._artist = resolve_artist(self._library, item)
        linked = self._artist is not None or links_catalog_artist(item)
        self.subtitle_label.set_label(item.subtitle)
        self.subtitle_label.set_visible(bool(item.subtitle) and not linked)
        self.artist_label.set_label(item.subtitle)
        self.artist_button.set_visible(linked)
        details = [item.genre, str(item.year) if item.year else None, item.count_label]
        self.caption_label.set_label(' · '.join(detail for detail in details if detail))
        self.caption_label.set_visible(any(details))
        self.summary_label.set_label(item.summary or '')
        self.summary_box.set_visible(bool(item.summary))
        self._update_buttons()

    def _update_buttons(self):
        """Play and Shuffle: with something to play, and tracks to play (or on their way: the
        engine plays an item by its id)."""
        item = self.item
        playable = item is not None and bool(item.play) and (
            any(group.entries.get_n_items() for group in item.groups)
            or self._engine_status.status == 'loading')
        self.play_button.set_sensitive(playable)
        self.shuffle_button.set_sensitive(playable)

    async def _fetch_cover(self, item):
        if await fetch_cover(item) and self.item is item:
            self.cover.refresh()

    # Fetching the tracks of an item that came without them.

    def _fetch(self, item):
        self._fetched = item
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._engine_status.loading()
        self._fetch_task = app().spawn(self._fetch_groups(item))

    def _refetch(self):
        """EngineStatus's retry (Try Again, the engine up, signed in): ask again."""
        self._fetched = None
        if self.item is not None:
            self._fetch(self.item)

    async def _fetch_groups(self, item):
        try:
            answer = await app().engine.item(item.kind, item.id)
        except EngineError as error:
            log.info('tracks of %s %s: %s', item.kind, item.id, error)
            if self.item is item:
                self._engine_status.fail(error)
            return
        if self.item is not item:
            return  # the page shows something else now
        self._engine_status.clear()
        item.merge(answer)  # new groups emit groups-changed, which shows them while mapped
        if item.groups is not self._shown_groups or not item.groups:
            self._show(item)

    def _show_empty(self):
        self._engine_status.clear()
        self._show_status('empty', _('No Songs'), '', None)

    def _show_status(self, status, title, description, button):
        """The status box: EngineStatus's states or 'empty' (no tracks at all), or for
        'loading' the spinner alone, as every page's loading state is."""
        loading = status == 'loading'
        self.status_spinner.set_visible(loading)
        self.status_icon.set_visible(not loading)
        self.status_title.set_label(title or '')
        self.status_title.set_visible(not loading)
        self.status_description.set_label(description or '')
        self.status_description.set_visible(bool(description))
        self.status_button.set_label(button or '')
        self.status_button.set_visible(bool(button))
        self._update_buttons()

    def _on_status_clicked(self, _button):
        self._engine_status.activate()

    def _heading(self, item, group, number):
        """An album's discs are numbered, whatever their groups are called; anything else's
        groups keep their names."""
        if item.kind == 'album':
            disc = group.entries.get_item(0).disc_number or number
            # Translators: the heading over one disc's songs on an album's page: {number}
            # is the disc's number ("Disc 2").
            return _('Disc {number}').format(number=disc)
        return group.name

    # The list.

    def _on_setup(self, _factory, list_item):
        list_item.set_child(_Row())

    def _on_bind(self, _factory, list_item):
        entry = list_item.get_item()
        row = list_item.get_child()
        is_track = isinstance(entry, Track)
        list_item.set_activatable(is_track)
        # The hero's and the suggestions' buttons take the focus, not their rows.
        list_item.set_focusable(is_track)
        if is_track:
            self._bound.add(list_item)
            self._show_track(list_item, entry)
        else:
            self._bound.discard(list_item)
            if isinstance(entry, _Suggestions):
                row.show_widget(self.suggestions_shelf)
            else:
                row.show_widget(self.hero)
            list_item.set_accessible_label('')
            list_item.set_accessible_description('')

    def _show_track(self, list_item, track):
        """A track's row, in a table or not, marked when its track is the one playing, and
        its name: the artist when the row shows one (not an album's own: TrackRow's rule),
        the album too in a table."""
        table = self._is_table()
        playing = self._playing.matches(track)
        list_item.get_child().show_track(track, self._album_artist, table, playing)
        show_artist = self._album_artist is None or track.artist != self._album_artist
        list_item.set_accessible_label(track_label(track, show_artist, show_album=table))
        list_item.set_accessible_description(self._playing.description(track, playing))

    def _on_track_changed(self, _player, _pspec):
        self._update_playing()

    def _update_playing(self):
        """Mark the rows of the track playing now, and no other, when the item changed."""
        if not self._playing.update():
            return
        for list_item in self._bound:
            track = list_item.get_item()
            playing = self._playing.matches(track)
            list_item.get_child().track_row.set_playing(playing)
            list_item.set_accessible_description(self._playing.description(track, playing))

    def _last_button(self):
        """The hero's last button that takes the focus: More Options, Shuffle or Play."""
        for button in (self.more_button, self.shuffle_button, self.play_button):
            if button.get_visible() and button.get_sensitive():
                return button
        return None

    def _on_list_key_pressed(self, _controller, keyval, _keycode, state):
        """Tab from the hero's last button into the tracks, and Shift+Tab from the first
        track back to it; Tab from a track on to the suggestions, when there are some, and
        Shift+Tab from their first button back to the last track. The list's Tab leaves it
        after the focused item (tab-behavior item), and the hero and the suggestions are
        its first and last items, so the tracks would otherwise be reached only with Down,
        the hero's buttons backwards only with Up, and the suggestions only with Down from
        the last track."""
        mods = state & Gtk.accelerator_get_default_mod_mask()
        forward = keyval in (Gdk.KEY_Tab, Gdk.KEY_KP_Tab) and not mods
        backward = (keyval == Gdk.KEY_ISO_Left_Tab
                    or (keyval in (Gdk.KEY_Tab, Gdk.KEY_KP_Tab)
                        and mods == Gdk.ModifierType.SHIFT_MASK))
        if not (forward or backward) or self._rows.get_n_items() < 2:
            return False
        focus = self.get_root().get_focus() if self.get_root() is not None else None
        last = self._last_button()
        if focus is None or last is None:
            return False
        if forward and (focus is last or focus.is_ancestor(last)):
            self.list_view.scroll_to(1, Gtk.ListScrollFlags.FOCUS, None)
            return True
        row = focus if isinstance(focus, _Row) else focus.get_ancestor(_Row)
        if row is None and focus.get_first_child() is not None:
            row = focus.get_first_child()  # the list item's own widget: its row inside
        on_track = isinstance(row, _Row) and row.track_row.context_item is not None
        start = self._suggestions_start
        if start is not None:
            first_button = self.suggestions_shelf.refresh_button
            if forward and on_track:
                self.list_view.scroll_to(start, Gtk.ListScrollFlags.FOCUS, None)
                first_button.grab_focus()
                return True
            if backward and (focus is first_button or focus.is_ancestor(first_button)):
                self.list_view.scroll_to(start - 1, Gtk.ListScrollFlags.FOCUS, None)
                return True
        if backward and on_track and row.track_row.context_item is self._rows.get_item(1):
            last.grab_focus()
            return True
        return False

    def _on_unbind(self, _factory, list_item):
        self._bound.discard(list_item)
        list_item.get_child().clear()

    def _on_setup_header(self, _factory, header):
        label = Gtk.Label(xalign=0, margin_start=24, margin_end=24, margin_top=18,
                          margin_bottom=6, ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class('heading')
        header.set_child(label)

    def _on_setup_table_header(self, _factory, header):
        header.set_child(TrackTableHeader(margin_start=24, margin_end=24, margin_top=6,
                                          margin_bottom=6))

    def _on_bind_table_header(self, _factory, header):
        # The tracks' section only: the hero's and the suggestions' have none.
        header.get_child().set_visible(isinstance(header.get_item(), Track))

    def _on_bind_header(self, _factory, header):
        label = header.get_child()
        section = bisect.bisect_right(self._starts, header.get_start()) - 1
        if not isinstance(header.get_item(), Track):
            section = -1  # the hero's and the suggestions' sections have no heading
        label.set_visible(section >= 0)
        label.set_label(self._headings[section] if section >= 0 else '')

    def _on_activate(self, _list_view, position):
        track = self._rows.get_item(position)
        if isinstance(track, Track):
            self.get_root().play_request(track.play, start_with=track.index,
                                         start_id=track.id)

    # The hero's links and menus.

    def _on_artist_clicked(self, _button):
        # What the library holds of the artist when it has them (window.open_item); else as
        # Go to Artist does, Apple Music's artist page.
        if self._artist is not None:
            self.get_root().open_item(self._artist)
        elif self.item is not None:
            self.get_root().item_actions.go_to(self.item, 'artist')

    def _on_more_popup(self, button):
        """The item's menu, made as it opens: whether it is a favourite is asked then."""
        actions = getattr(self.get_root(), 'item_actions', None)
        button.set_menu_model(actions.menu_for(self.item) if actions and self.item else None)

    def _on_more_notes_clicked(self, _button):
        if self.item is not None:
            show_notes(self, self.item.title, self.item.summary or '')

    def _on_painted(self, _clock):
        """More under the notes, while they are cut to their three lines."""
        layout = self.summary_label.get_layout()
        cut = self.summary_label.get_mapped() and layout is not None and layout.is_ellipsized()
        if cut != self.more_notes_button.get_visible():
            self.more_notes_button.set_visible(cut)

    def _on_play_clicked(self, _button):
        self.get_root().play_request(self.item.play, shuffle=False)

    def _on_shuffle_clicked(self, _button):
        self.get_root().play_request(self.item.play, shuffle=True)
