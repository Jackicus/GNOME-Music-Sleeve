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
(the tracks' section's list header, TrackTableHeader), and the optional Genre and Year
columns chosen in Sort By (song_columns.py, the song-columns setting the Songs table shares),
whose items Sort By lists only while the songs are a table. An album's stay a numbered list,
and so does any page in a narrower window.

The page's parts with a state and requests of their own are mixins beside it, each described
there: a playlist's Sort By and filter (detail_sort_filter.py), what the catalog shows under
the tracks (detail_catalog.py), the songs Apple suggests adding (detail_suggestions.py), and
moving and removing a playlist's songs (detail_reorder.py); the list's rows are
detail_rows.py's.

The tracks have the selection mode of the track lists (widgets/selection_mode.py): Select
in the header bar, a Ctrl+click or Shift+click on a song, Ctrl+A; the hero, the footer and the
suggestions are never selected (the mode selects among _selectable(), the tracks shown), a
playlist of the user's offers Remove from Playlist, and while selecting no song moves
(can_reorder()). The bar's narrow layout follows the hero's narrow breakpoints.
"""

import bisect
import logging
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from ..backend.api import is_library_id
from .. import keyboard, song_columns
from ..backend.errors import EngineError
from ..library import HELD_KINDS, ItemRefs, Track
from ..item_targets import adds_to, is_manageable
from ..related import catalog_target
from ..release import (album_artist, curator, hero_caption, is_prerelease, playlist_target,
                       released_play, unbroken)
from ..remote import fetch_cover
from ..selection import Places
from ..widgets import context_menu, dnd, track_links
from ..widgets.cover import Cover  # noqa: F401  registers $AppleMusicCover for the template
from ..widgets.engine_status import EngineStatus
from ..widgets.filter_bar import FilterBar, SearchText, ShownModel
from ..widgets.selection_mode import SelectionMode, row_description
from ..widgets.labels import track_label
from ..widgets.track_row import PlayingMark, TrackTableHeader, is_playing
from ..widgets.util import (HeaderTitle, MappedHandlers, connect_weak, focus_position,
                            next_frame, shared_section, weak_method)
from . import SignInOffer, app, show_notes
from .detail_catalog import FETCHED_KINDS, CatalogPart
from .detail_reorder import ReorderPart
from .detail_rows import _Footer, _Hero, _Row, _row_of, _Shelves, _Suggestions
from .detail_sort_filter import (OWN_ORDER, PLAYLIST_SORTS, SortFilterPart, filters_songs,
                                 playlist_sorter)
from .detail_suggestions import SuggestionsPart, held_songs, wants_suggestions

log = logging.getLogger(__name__)

# Frames Go to Current Song waits, at most, for the row of the song playing to take the focus
# (the list lays the row out a frame after scroll_to()).
REVEAL_FRAMES = 10
# The songs a playlist's filter gives the list at a frame as it grows back (ShownModel): a
# row about 1.5 ms to make, bind and lay out (twelve made frames of 17-21 ms).
GROW_TRACKS = 5

# The width from which a playlist's tracks are a table: detail.blp's table_breakpoint.
TABLE_WIDTH = 720  # sp


def expects_table(width, text_scale=1.0):
    """Whether a page `width` px wide will be past the table's breakpoint (TABLE_WIDTH sp,
    an sp being `text_scale` px): what the page assumes before its first layout, so that its
    rows are bound once, as the table has them (the breakpoint applies only as the page is
    laid out, after the rows it shows first are bound)."""
    return bool(width) and width > 0 and width >= TABLE_WIDTH * text_scale


def text_scale():
    """px to an sp: the text scale factor (gtk-xft-dpi over 96 dpi), as a breakpoint's sp."""
    settings = Gtk.Settings.get_default()
    dpi = settings.get_property('gtk-xft-dpi') if settings is not None else 0
    return dpi / (96 * 1024) if dpi and dpi > 0 else 1.0


def playing_ordinal(tracks, ids, index):
    """Where the song playing is among a page's tracks (in the page's order): the place of
    the track playing_ids() `ids` names, the one at the queue's `index` when that one is it
    (the same song twice in a playlist), else the first; None when none is."""
    found = None
    for ordinal, track in enumerate(tracks):
        if is_playing(track, ids):
            if ordinal == index:
                return ordinal
            if found is None:
                found = ordinal
    return found


def resolve_artist(library, item):
    """The artist Item an album is by (album_artist(): a shelf's album is subtitled with its
    year), for the link to their page: by the artist id the album carries, if any, else the
    library's artist of that name (case folded), else None (the name stays plain text). Only
    albums: a playlist's subtitle is its curator."""
    name = album_artist(item)
    if not name:
        return None
    artist_id = item.raw.get('artistId')
    if artist_id:
        found = library.by_id('artist', artist_id)
        if found is not None:
            return found
    name = name.casefold()
    return next((artist for artist in library.artists if artist.title.casefold() == name),
                None)


def links_catalog_artist(item):
    """Whether an album's artist links to its catalog artist, which the engine looks up
    (related.catalog_target): a catalog album with an artist's name, outside the demo."""
    application = app()
    return (item is not None and item.kind == 'album' and bool(album_artist(item))
            and catalog_target(item) is not None
            and application is not None and not application.demo)


def library_state(library, item):
    """What the hero says of the library for `item`: 'add' for an album or playlist of the
    catalog's that the library does not hold (the Add button), 'held' for one it holds (In
    Library: Library.holds(), which knows one just added ahead of Apple's listing), None for
    the library's own (its page is the library's) and anything else."""
    if (item is None or item.kind not in HELD_KINDS or not item.id
            or is_library_id(item.id)):
        return None
    return 'held' if library.holds(item) else 'add'


def should_fetch(item, fetched):
    """Whether a page showing `item` asks the engine for its tracks: it came without them (a
    shelf's, a search's, an artist's album the library lacks), it is of a kind the engine
    fetches, and this page has not asked for this Item already (`fetched`): an answer
    without tracks (an empty album or playlist) is shown as such, not asked for again."""
    return (item is not None and not item.groups and item.kind in FETCHED_KINDS
            and fetched is not item)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/detail.ui')
class DetailPage(SortFilterPart, CatalogPart, SuggestionsPart, ReorderPart, Adw.NavigationPage):
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

    A pre-release album (release.is_prerelease()) says when it comes out in the caption and
    the footer ("Coming 4 December 2026"); its tracks not out yet are dimmed, described "Not
    yet released", and play nothing; Play, Shuffle and the other rows play the tracks out
    already, as one list (release.released_play()), and Play and Shuffle are insensitive
    while none is. Its Add is Pre-Add.

    The hero: under the title, an album's artist or a playlist's curator (release.curator():
    the account's name for one of the user's; a catalog playlist's a link to the curator's
    page once Engine.playlist_page has named them), then the caption (release.hero_caption(): a
    playlist's "Updated" date and its songs, an album's genre, year and songs). Beside Play
    and Shuffle, an album or playlist of the catalog's has Add, which adds it to the library
    (window.item_actions.add_to_library()), or In Library once the library holds it
    (library_state(); the page follows Library's `item-added` and `changed`). An album's
    artist links to what the library holds of them when it has them
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
            self._update_columns()  # the rows shown again, as the table has them or not

    table = GObject.Property(type=bool, default=False, getter=_get_table, setter=_set_table,
                             nick='Table', blurb="A playlist's tracks as a table (wide)")

    table_breakpoint = Gtk.Template.Child()
    hero_breakpoint = Gtk.Template.Child()
    phone_breakpoint = Gtk.Template.Child()
    toolbar = Gtk.Template.Child()
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
    add_button = Gtk.Template.Child()
    add_content = Gtk.Template.Child()
    in_library_box = Gtk.Template.Child()
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
    footer_label = Gtk.Template.Child()
    shelves_box = Gtk.Template.Child()

    def __init__(self, library, item=None, find=None, root=False, title=None, icon_name=None,
                 empty_title=None, empty_description=None):
        super().__init__(title=title or (item.title if item is not None else ''))
        self.item = None  # what the page shows
        self._library = library
        self._find = find
        self._root = root
        self._album_artist = None  # an album's artist, whose name its rows leave out
        self._groups = 0  # the sections of tracks shown
        self._track_models = []  # and their models: the groups' stores, or a playlist's filtered
        self._track_total = 0  # the tracks of the groups shown, filtered or not
        self._bound = set()  # the list items bound to tracks: shown again as `table` changes
        self._starts = []  # the list position of each section of tracks
        self._headings = []  # and its heading
        self._fetched = None  # the Item this page asked the engine for (once: should_fetch)
        self._fetch_task = None
        self._shown_groups = None  # item.groups when the tracks were shown: a new list is new
        self._artist = None  # the library's artist Item the subtitle names, if any
        self._painted = None  # (frame clock, handler): the notes' More follows each paint
        self._focused = False  # the page has put the focus on Play once, as it was pushed
        self._visible = False  # between do_shown and do_hidden: the navigation view's page
        self._reveal_wanted = False  # Go to Current Song asked for the playing song's row
        self._reveal_task = None
        self._adding = None  # the Item whose add to the library is under way (Add)
        self._status = None  # what the status box shows ('empty': No Songs, Add Songs…)
        # A playlist's Sort By (PLAYLIST_SORTS key, descending), for the page's life, and the
        # Item it was chosen for; the groups' Gtk.SortListModels of it.
        self._order = OWN_ORDER
        self._ordered_for = None
        self._sorted = []
        # Delete's last removal while it is under way, the shown places of the rows each
        # removal under way takes ({task: [position]}), and where the focus goes each time
        # the songs show again until they have all ended: (Item, position).
        self._removing = None
        self._going = {}
        self._refocus = None
        # The songs Apple suggests (wants_suggestions): the Item they were asked for, what
        # is shown of them (a Suggestions), the requests under way, and the section that
        # shows them, made when there are some (_suggestions_widget()).
        self._suggested_for = None
        self._suggestions = None
        self._suggestions_task = None
        self._more_task = None
        self._suggestion_art_task = None
        self.suggested_songs = None
        # What the catalog shows under an album's or a catalog playlist's tracks
        # (Engine.album_page, Engine.playlist_page): the Item it was asked for, the request
        # under way and the art's, its answer, its shelves, shown by a ShelfColumn in
        # shelves_box, made with the first of them (a library playlist's page, the first
        # page built, never imports the shelves), and a playlist's curator, the Item its
        # link opens (release.curator_item()).
        self._catalog_asked_for = None
        self._catalog_task = None
        self._catalog_art_task = None
        self._catalog_answer = None
        self._catalog_shelves = []
        self._curator = None
        self._shelf_column = None
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
        # A playlist's own song dropped back on it moves there (can_reorder()).
        self._drop_feedback = dnd.DropFeedback(self.scrolled_window)
        drop = Gtk.DropTarget.new(ItemRefs.__gtype__, Gdk.DragAction.MOVE)
        connect_weak(drop, 'accept', self._on_drop_accept)
        connect_weak(drop, 'enter', self._on_drop_motion)
        connect_weak(drop, 'motion', self._on_drop_motion)
        connect_weak(drop, 'leave', self._on_drop_leave)
        connect_weak(drop, 'drop', self._on_drop)
        self.list_view.add_controller(drop)
        track_links.attach(self.list_view)  # a table's artist and album links
        self._header_factory = Gtk.SignalListItemFactory()
        connect_weak(self._header_factory, 'setup', self._on_setup_header)
        connect_weak(self._header_factory, 'bind', self._on_bind_header)
        self._table_header_factory = Gtk.SignalListItemFactory()
        connect_weak(self._table_header_factory, 'setup', self._on_setup_table_header)
        connect_weak(self._table_header_factory, 'bind', self._on_bind_table_header)
        self._table_headers = set()  # the table's headers bound: room for the check boxes
        # Told from the content pane's width before the first layout (expects_table()); the
        # first paint puts it right if that was wrong (_on_painted).
        window = app().get_active_window() if app() is not None else None
        content_width = getattr(window, 'content_width', None)
        self._table = expects_table(content_width() if content_width is not None else 0,
                                    text_scale())
        self._table_checked = False
        connect_weak(self.play_button, 'clicked', self._on_play_clicked)
        connect_weak(self.shuffle_button, 'clicked', self._on_shuffle_clicked)
        connect_weak(self.add_button, 'clicked', self._on_add_clicked)
        connect_weak(self.status_button, 'clicked', self._on_status_clicked)
        connect_weak(self.artist_button, 'clicked', self._on_artist_clicked)
        connect_weak(self.more_notes_button, 'clicked', self._on_more_notes_clicked)
        self.more_button.set_create_popup_func(weak_method(self._on_more_popup))
        self._header_title = HeaderTitle(self.header_bar, self.title_label, self.scrolled_window)
        # The tracks' selection mode (widgets/selection_mode.py): Select at the header bar's
        # end, the batch actions in a bar under the list. A track is selected by its song's
        # id and which of that song's entries it is (selection.Places), so a reload that
        # changes the item, which makes new Tracks, keeps it selected.
        self._places = Places(weak_method(self._all_tracks))
        self.selection_mode = SelectionMode(self, self.header_bar, self.toolbar, self.list_view,
                                            self._selectable, self._focus_tracks,
                                            key=self._places.key)
        self.selection_mode.set_header_title(self._header_title)
        # A playlist's Sort By at the header bar's end, then Select and the filter's button,
        # in the order the Songs page and the grids have them (its menu is made below).
        self.sort_button = Gtk.MenuButton(icon_name='view-sort-descending-symbolic',
                                          tooltip_text=_('Sort By'), visible=False)
        self.sort_button.update_property([Gtk.AccessibleProperty.LABEL], [_('Sort By')])
        self.header_bar.pack_end(self.sort_button)
        self.header_bar.pack_end(self.selection_mode.select_button)
        self.header_bar.pack_end(self.selection_mode.cancel_button)
        connect_weak(self.selection_mode.selection, 'changed', self._on_selection_changed)
        # A reorder (Item.reorder(): the same Tracks, new records) happens outside the mode:
        # the places are worked out again as it starts.
        connect_weak(self.selection_mode.selection, 'notify::active', self._on_selecting)
        context_menu.set_drag_objects(self.list_view,
                                      weak_method(self.selection_mode.drag_objects))
        # The table and the selection bar's narrow layout follow the bin's current breakpoint,
        # not the breakpoints' own apply and unapply: libadwaita 1.9 and 1.10 never free a
        # bin's breakpoints, which would keep a handler on each, and its closure, for good
        # (docs/notes.md, Memory). A handler on the bin goes with the bin.
        connect_weak(self.get_child(), 'notify::current-breakpoint', self._on_breakpoint)
        # A playlist's filter: the bar under the header bar, the text filtering every group.
        self._text = SearchText()  # a Backspace that brings nothing back filters nothing
        self._filtered = []  # the groups' Gtk.FilterListModels of it, while it filters
        self.filter_bar = FilterBar(_('Filter Songs'))
        self.toolbar.add_top_bar(self.filter_bar)
        self.header_bar.pack_end(self.filter_bar.button)
        self.selection_mode.set_filter_bar(self.filter_bar)
        connect_weak(self.filter_bar, 'changed', self._on_filter_changed)
        self.filter_bar.set_focus_return(self._focus_tracks)
        # A playlist's Sort By (packed above): radio items of the stateful tracks.sort and
        # tracks.sort-order actions (the view's order only).
        self._sort_action = Gio.SimpleAction.new_stateful(
            'sort', GLib.VariantType.new('s'), GLib.Variant('s', OWN_ORDER[0]))
        self._order_action = Gio.SimpleAction.new_stateful(
            'sort-order', GLib.VariantType.new('s'), GLib.Variant('s', 'ascending'))
        connect_weak(self._sort_action, 'change-state', self._on_sort_chosen)
        connect_weak(self._order_action, 'change-state', self._on_order_chosen)
        sort_actions = Gio.SimpleActionGroup()
        sort_actions.add_action(self._sort_action)
        sort_actions.add_action(self._order_action)
        self.insert_action_group('tracks', sort_actions)
        # Its sections are every page's (shared_section(): GTK keeps a popover's sections).
        sort_menu = Gio.Menu()
        sort_menu.append_section(None, shared_section(
            (label(), f'tracks.sort::{key}') for key, (label, _names) in PLAYLIST_SORTS.items()))
        sort_menu.append_section(None, shared_section((
            (_('Asc_ending'), 'tracks.sort-order::ascending'),
            (_('Desce_nding'), 'tracks.sort-order::descending'))))
        # The table's optional columns (song_columns.py, the song-columns setting the Songs
        # table shares), offered while the songs show as a table.
        self._settings = getattr(app(), 'settings', None)
        self._optional = song_columns.shown(self._settings)
        self._column_actions = song_columns.make_actions(
            sort_actions, weak_method(self._on_column_chosen))
        sort_menu.append_section(None, song_columns.menu_section('tracks'))
        song_columns.show_states(self._column_actions, self._optional, False)
        self.sort_button.set_menu_model(sort_menu)
        # Tab from the hero's last button goes on into the tracks (_on_list_key_pressed).
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        connect_weak(keys, 'key-pressed', self._on_list_key_pressed)
        self.list_view.add_controller(keys)

        # The library, the Item shown (_watch) and the Player's item, followed while the
        # page is shown (a test's stand-in application may have no player).
        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._follow)
        self._handlers.add(library, 'changed', self._follow)
        self._handlers.add(library, 'item-added', self._on_item_added)
        self._handlers.add(library, 'favourites-changed', self._update_favourites)
        self._playing = PlayingMark(getattr(app(), 'player', None))
        if self._playing.player is not None:
            self._handlers.add(self._playing.player, 'notify::track', self._on_track_changed)
            self._handlers.add(self._playing.player, 'notify::preview',
                               self._on_preview_changed)
        self._previewing = ''  # the song whose preview this page started, while it may play
        if self._settings is not None:
            self._handlers.add(self._settings, 'changed::more-suggestions',
                               self._on_count_changed)
            self._handlers.add(self._settings, 'changed::' + song_columns.SETTING,
                               self._on_columns_changed)

        self._hero_section = Gio.ListStore(item_type=GObject.Object)
        self._hero_section.append(_Hero())
        self._suggestions_section = Gio.ListStore(item_type=GObject.Object)
        self._suggestions_section.append(_Suggestions())
        self._suggestions_start = None  # the list position of the suggestions, while shown
        self._footer_section = Gio.ListStore(item_type=GObject.Object)
        self._footer_section.append(_Footer())
        self._shelves_section = Gio.ListStore(item_type=GObject.Object)
        self._shelves_section.append(_Shelves())
        self._shelves_start = None  # the list position of the catalog's shelves, while shown
        self._sections = Gio.ListStore(item_type=Gio.ListModel)
        self._rows = Gtk.FlattenListModel(model=self._sections)
        self.list_view.set_model(Gtk.NoSelection(model=self._rows))

        self._show(item)

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        self._follow()  # what a reload changed while the page was hidden
        self._update_playing()  # and the item playing now
        self._update_favourites()  # and the favourites
        self._engine_status.watch()
        if should_fetch(self.item, self._fetched):
            self._fetch(self.item)  # a fetch cancelled when the page was hidden
        self._suggest()
        self._ask_catalog()
        self._on_columns_changed()  # the columns chosen while the page was hidden
        if self._suggestions is not None and self._suggestions.count != self._count():
            self._on_count_changed()  # the setting changed while the page was hidden
        self._on_preview_changed()  # a preview that ended while the page was hidden
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
        self._visible = True
        if self._reveal_wanted:
            self._start_reveal()  # again, past the push's own move of the focus
        Adw.NavigationPage.do_shown(self)

    def do_hidden(self):
        # Left (popped, covered, or another destination shown), not just unmapped (a push
        # maps, unmaps and maps a page again): the fetch stops, asked again when shown.
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
            self._fetch_task = None
            self._fetched = None
            self._engine_status.clear()
        for task in (self._suggestions_task, self._more_task, self._suggestion_art_task,
                     self._catalog_task, self._catalog_art_task):
            if task is not None and not task.done():
                task.cancel()
        if self._suggestions is None or not self._suggestions.shown:
            self._suggested_for = None  # asked again when shown: none came this time
        if self._catalog_answer is None:
            self._catalog_asked_for = None  # the same
        self._stop_preview()
        self.selection_mode.leave()  # the mode is the page's while it shows
        self._visible = False
        self._reveal_wanted = False
        if self._reveal_task is not None and not self._reveal_task.done():
            self._reveal_task.cancel()
        Adw.NavigationPage.do_hidden(self)

    def _follow(self, *_args):
        item = self._find() if self._find is not None else self.item
        if item is not self.item or (item is not None and item.groups is not self._shown_groups):
            self._show(item)
        self._update_state()
        self._update_library_state()  # an album or playlist added, or listed at last

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
        # New groups or another item: their songs' places, before a row is bound for them.
        self._places.forget()
        if item is None:
            self._shown_groups = None
            self._suggestions_start = None
            self._shelves_start = None
            self._sections.remove_all()
            # No songs show: the filter and Sort By go with them (a root page whose playlist
            # went, Favourite Songs after a sign-out).
            self._sorted, self._filtered, self._track_models = [], [], []
            self._starts, self._headings, self._groups = [], [], 0
            self._update_state()
            self._update_filter()
            self.selection_mode.set_available(False)
            return
        self._album_artist = album_artist(item) if item.kind == 'album' else None
        self._show_hero(item)

        self._shown_groups = item.groups
        groups = [group for group in item.groups if group.entries.get_n_items()]
        # New groups (or another item): what each text matched is not known for them.
        self._text.forget()
        if filters_songs(item):  # in the Sort By's order, through the filter bar's text
            if self._ordered_for is not item:  # another playlist: in its own order
                self._ordered_for = item
                self._set_order_state(OWN_ORDER)
            sorter, backwards = playlist_sorter(*self._order)
            # Sorted, then filtered (a filter's change never sorts again). Shown through a
            # ShownModel, which a filter's change recycles the rows for, and which gives the
            # list a few a frame when it grows back (the sections after it placed again as
            # it does).
            self._sorted = [Gtk.SortListModel(model=group.entries, sorter=sorter)
                            for group in groups]
            self._filtered = [Gtk.FilterListModel(model=model, filter=self._text.filter)
                              for model in self._sorted]
            self._track_models = [ShownModel(model, self.list_view, GROW_TRACKS)
                                  for model in self._filtered]
            for model in self._track_models:
                model.set_backwards(backwards)
                connect_weak(model, 'items-changed', self._place_sections)
        else:
            self._sorted = []
            self._filtered = []
            self._track_models = [group.entries for group in groups]
        self._starts = []
        self._headings = []
        position = 1  # after the hero
        for number, (group, model) in enumerate(zip(groups, self._track_models, strict=True), 1):
            self._starts.append(position)
            self._headings.append(self._heading(item, group, number))
            position += model.get_n_items()

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
        song_columns.show_states(self._column_actions, self._optional, self._is_table())
        self._track_total = sum(group.entries.get_n_items() for group in groups)
        sections = [self._hero_section] + self._track_models
        self._suggestions_start = None
        self._shelves_start = None
        if groups and item.kind == 'album':
            # The footer, then the catalog's shelves once they have come (_take_album).
            if self._catalog_asked_for is not item:
                self._forget_catalog()
            self._update_footer(item, groups)
            sections.append(self._footer_section)
            position += 1
            if self._catalog_shelves:
                self._shelves_start = position
                sections.append(self._shelves_section)
        elif groups and playlist_target(item) is not None:
            # The catalog's shelves once they have come (_take_playlist), no footer.
            if self._catalog_asked_for is not item:
                self._forget_catalog()
            if self._catalog_shelves:
                self._shelves_start = position
                sections.append(self._shelves_section)
        shown = []
        if groups and wants_suggestions(item):
            self._suggest()
            if self._suggestions is not None and self._suggested_for is item:
                self._suggestions.drop_held(held_songs(item))
                shown = self._suggestions.shown
            if shown or self.suggested_songs is not None:
                self._suggestions_widget().set_items(shown)
            if shown:
                self._suggestions_start = position
                sections.append(self._suggestions_section)
        self._sections.splice(0, self._sections.get_n_items(), sections)
        self._update_state()
        self._update_filter()
        self._update_selection(item)
        if shown:
            self._want_more()
        if groups:
            self._ask_catalog()
            if self._reveal_wanted:
                self._start_reveal()  # the tracks Go to Current Song waited for
        self._take_refocus(item)

    def _place_sections(self, *_args):
        """The positions of the sections of tracks, and of the suggestions or the catalog's
        shelves after them, as the filter changes what they show."""
        if len(self._starts) != len(self._track_models):
            return  # the sections are being made (_show_item places them)
        position = 1  # after the hero
        for index, model in enumerate(self._track_models):
            self._starts[index] = position
            position += model.get_n_items()
        if self._suggestions_start is not None:
            self._suggestions_start = position
        if self._shelves_start is not None:  # after an album's footer
            footer = self.item is not None and self.item.kind == 'album'
            self._shelves_start = position + (1 if footer else 0)

    def _shown_tracks(self):
        return sum(model.get_n_items() for model in self._track_models)

    def _on_breakpoint(self, bin_, _pspec):
        """The bin's breakpoint changed: a playlist's table from the wide one, the selection
        bar's narrow layout from either narrow one (only the last that matches applies)."""
        current = bin_.get_current_breakpoint()
        self.table = current is self.table_breakpoint
        self.selection_mode.set_narrow(current in (self.hero_breakpoint, self.phone_breakpoint))

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
        self._show_curator(item)
        caption = hero_caption(item)
        self.caption_label.set_label(unbroken(caption))
        self.caption_label.set_visible(bool(caption))
        self.summary_label.set_label(item.summary or '')
        self.summary_box.set_visible(bool(item.summary))
        self._update_buttons()
        self._update_library_state()

    def _show_curator(self, item):
        """The line under the title: an album's artist or a playlist's curator, a link to
        their page when there is one to open (the library's artist, the catalog's, a catalog
        playlist's curator once Engine.playlist_page has named them), else plain text."""
        subtitle = curator(item, self._account_name())
        if item.kind == 'album':
            linked = self._artist is not None or links_catalog_artist(item)
            link_text = album_artist(item)
        else:
            curator_link = self._curator if self._catalog_asked_for is item else None
            link_text = subtitle or (curator_link.title if curator_link is not None else '')
            linked = curator_link is not None and bool(link_text)
        if not linked and self.artist_button.is_focus():
            self.play_button.grab_focus()
        self.subtitle_label.set_label(subtitle)
        self.subtitle_label.set_visible(bool(subtitle) and not linked)
        self.artist_label.set_label(link_text)
        self.artist_button.set_visible(linked)

    def _account_name(self):
        """The account's name, which a playlist of the user's shows as its curator ('' when
        unknown: the sign-in has not read it, or a stand-in application)."""
        application = app()
        key = getattr(application, 'account_key', None)
        if self._settings is None or key is None:
            return ''
        return self._settings.get_string(key('account-name'))

    def _update_library_state(self):
        """Add or In Library, as library_state() says for the item shown; neither for the
        library's own. The focus moves to More Options when Add, focused, gives way to In
        Library."""
        state = library_state(self._library, self.item)
        if state != 'add' and self.add_button.is_focus():
            self.more_button.grab_focus()
        if state == 'add':
            # A pre-release album is pre-added, as Apple Music words it: its songs come into
            # the library as they come out.
            prerelease = is_prerelease(self.item)
            self.add_content.set_label(
                # Translators: a button that adds an album not out yet to the library (its
                # songs come as they are released); keep it short.
                _('Pre-Add') if prerelease
                # Translators: the button that adds an album or a playlist to the library.
                else _('Add'))
            self.add_button.set_tooltip_text(
                _('Pre-Add to Library') if prerelease else _('Add to Library'))
        self.add_button.set_visible(state == 'add')
        self.in_library_box.set_visible(state == 'held')

    def _on_item_added(self, _library, kind, item_id):
        if self.item is not None and (self.item.kind, self.item.id) == (kind, item_id):
            self._update_library_state()

    def _on_add_clicked(self, _button):
        """Add the album or playlist to the library (the item actions' Add to Library, which
        notes it in the library once Apple has taken it: In Library then shows)."""
        actions = getattr(self.get_root(), 'item_actions', None)
        item = self.item
        if (actions is None or item is None or self._adding is item
                or library_state(self._library, item) != 'add'):
            return  # nothing to add, or its add is under way already (a second click)
        task = actions.add_to_library(item)
        if task is None:
            return  # nothing to add, or the demo library (which says so)
        self._adding = item
        # The task outlives a page that may be popped meanwhile: it holds the page weakly.
        done = weak_method(self._on_add_done)
        task.add_done_callback(lambda _task: done(item))

    def _on_add_done(self, item):
        """The add ended: Add can be clicked again when it failed (reported already); In
        Library shows when the library holds the item (Library's `item-added`)."""
        if self._adding is item:
            self._adding = None
            self._update_library_state()

    def _update_buttons(self):
        """Play and Shuffle: with something to play, and tracks to play (or on their way: the
        engine plays an item by its id); not for a pre-release album none of whose tracks is
        out yet (release.released_play())."""
        item = self.item
        has_tracks = item is not None and any(group.entries.get_n_items()
                                               for group in item.groups)
        playable = item is not None and bool(item.play) and (
            (has_tracks and released_play(item) is not None)
            or (not has_tracks and self._engine_status.status == 'loading'))
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
        """No Songs; on a playlist of the user's, with Add Songs…."""
        self._engine_status.clear()
        if adds_to(self.item):
            self._show_status('empty', _('No Songs'),
                              _('Add songs from your library or Apple Music'), _('Add Songs…'))
        else:
            self._show_status('empty', _('No Songs'), '', None)

    def _show_status(self, status, title, description, button):
        """The status box: EngineStatus's states or 'empty' (no tracks at all), or for
        'loading' the spinner alone, as every page's loading state is."""
        self._status = status
        loading = status == 'loading'
        self.status_spinner.set_visible(loading)
        self.status_icon.set_visible(not loading)
        self.status_icon.set_from_icon_name(
            'edit-find-symbolic' if status == 'no-results' else 'music-note-symbolic')
        self.status_title.set_label(title or '')
        self.status_title.set_visible(not loading)
        self.status_description.set_label(description or '')
        self.status_description.set_visible(bool(description))
        self.status_button.set_label(button or '')
        self.status_button.set_visible(bool(button))
        self._update_buttons()

    def _on_status_clicked(self, _button):
        actions = getattr(self.get_root(), 'item_actions', None)
        if self._status == 'empty' and adds_to(self.item) and actions is not None:
            actions.ask_add_songs(self.item)  # an empty playlist's Add Songs…
            return
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
                row.show_widget(self.suggested_songs)
            elif isinstance(entry, _Footer):
                row.show_widget(self.footer_label)
            elif isinstance(entry, _Shelves):
                row.show_widget(self.shelves_box)
            else:
                row.show_widget(self.hero)
            list_item.set_accessible_label('')
            list_item.set_accessible_description('')

    def _show_track(self, list_item, track):
        """A track's row, in a table or not, marked when its track is the one playing, and
        its name: the artist when the row shows one (not an album's own: TrackRow's rule),
        the album too in a table, and the optional columns it shows."""
        table = self._is_table()
        playing = self._playing.matches(track)
        favourite = self._library.is_favourite(track)
        row = list_item.get_child()
        row.show_track(track, self._album_artist, table, playing, favourite,
                       self._shown_columns(table))
        selection = self.selection_mode.selection
        selected = selection.has(track)
        row.track_row.set_selected(selection.active, selected)
        list_item.set_accessible_label(self._track_label(track, table, favourite))
        list_item.set_accessible_description(row_description(
            selection.active, selected, self._playing.description(track, playing)))

    def _track_label(self, track, table, favourite):
        show_artist = self._album_artist is None or track.artist != self._album_artist
        return track_label(track, show_artist, show_album=table, favourite=favourite,
                           columns=self._shown_columns(table))

    # The table's optional columns (song_columns.py).

    def _shown_columns(self, table):
        """The optional columns a table shows (none but in a table)."""
        return self._optional if table else frozenset()

    def _on_column_chosen(self, name, show):
        """Genre Column or Year Column in Sort By: the setting, which every song table
        follows (this one at once)."""
        song_columns.set_shown(self._settings, name, show)
        self._on_columns_changed()

    def _on_columns_changed(self, *_args):
        optional = song_columns.shown(self._settings)
        if optional != self._optional:
            self._optional = optional
            self._update_columns()

    def _update_columns(self):
        """The menu's column items (offered in a table), the table's column titles and the
        bound rows, after the table came or went or the columns chosen changed."""
        table = self._is_table()
        song_columns.show_states(self._column_actions, self._optional, table)
        for header in self._table_headers:
            if header.get_child() is not None:
                header.get_child().set_columns(self._shown_columns(table))
        for list_item in self._bound:
            self._show_track(list_item, list_item.get_item())

    def _update_favourites(self, *_args):
        """The account's favourites changed (a sync, or a heart): the bound rows' hearts and
        names again."""
        table = self._is_table()
        for list_item in self._bound:
            track = list_item.get_item()
            favourite = self._library.is_favourite(track)
            list_item.get_child().track_row.set_favourite(favourite)
            list_item.set_accessible_label(self._track_label(track, table, favourite))

    def _on_track_changed(self, _player, _pspec):
        self._update_playing()

    def _update_playing(self):
        """Mark the rows of the track playing now, and no other, when the item changed."""
        if not self._playing.update():
            return
        selection = self.selection_mode.selection
        for list_item in self._bound:
            track = list_item.get_item()
            playing = self._playing.matches(track)
            list_item.get_child().track_row.set_playing(playing)
            list_item.set_accessible_description(row_description(
                selection.active, selection.has(track),
                self._playing.description(track, playing)))

    def _last_button(self):
        """The hero's last button that takes the focus: More Options, Add, Shuffle or Play."""
        for button in (self.more_button, self.add_button, self.shuffle_button,
                       self.play_button):
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
        the last track. Before them, the focused song's own keys: Alt+Up, Alt+Down, Alt+Home and
        Alt+End move it (keyboard.move_step()), Delete takes it out of the playlist
        (remove_key())."""
        mods = state & Gtk.accelerator_get_default_mod_mask()
        root = self.get_root()
        focused = root.get_focus() if root is not None else None
        get_dialog = getattr(root, 'get_visible_dialog', None)
        dialog_open = get_dialog is not None and get_dialog() is not None
        in_popover = focused is not None and focused.get_ancestor(Gtk.Popover) is not None
        step = keyboard.move_step(keyval, mods, type(focused), dialog_open, in_popover)
        if step is not None:
            return self._move_focused(focused, step)
        if keyboard.remove_key(keyval, mods, type(focused), dialog_open, in_popover):
            return self.remove_focused(focused)
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
            if not self._shown_tracks():
                return False  # a filter left none
            self.list_view.scroll_to(1, Gtk.ListScrollFlags.FOCUS, None)
            return True
        row = _row_of(focus)
        on_track = isinstance(row, _Row) and row.track_row.context_item is not None
        shelves = self._shelves_start
        if shelves is not None:
            if forward and on_track:
                self.list_view.scroll_to(shelves, Gtk.ListScrollFlags.FOCUS, None)
                if not (self.shelves_box.get_mapped()
                        and self.shelves_box.child_focus(Gtk.DirectionType.TAB_FORWARD)):
                    # Their row is made at the list's next layout.
                    app().spawn(self._focus_shelves())
                return True
            if backward and (focus is self.shelves_box or focus.is_ancestor(self.shelves_box)):
                # Back through the shelves, then from the first of them to the last track
                # (an album's footer between them takes no focus).
                if not self.shelves_box.child_focus(Gtk.DirectionType.TAB_BACKWARD):
                    footer = self.item is not None and self.item.kind == 'album'
                    self.list_view.scroll_to(shelves - (2 if footer else 1),
                                             Gtk.ListScrollFlags.FOCUS, None)
                return True
        start = self._suggestions_start
        if start is not None:
            first_button = self.suggested_songs.refresh_button
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

    # Go to Current Song.

    def reveal_playing(self):
        """Go to Current Song (the window's Ctrl+L): scroll to the row of the song playing
        and put the focus on it, once the page shows and its tracks are there (fetched, for
        an album or playlist that came without them). A filter on a playlist's songs that
        hides the song is cleared first; one it matches stays. Nothing when the page lacks
        the song."""
        self._reveal_wanted = True
        self._start_reveal()

    def _start_reveal(self):
        if self._reveal_task is None or self._reveal_task.done():
            self._reveal_task = app().spawn(self._reveal())

    def _playing_position(self):
        """The list position of the row of the song playing, or None."""
        player = self._playing.player
        if player is None or player.track is None or not self._starts:
            return None
        for model in self._track_models:
            if isinstance(model, ShownModel):
                model.finish()  # every song the filter leaves shown, if it was growing back
        self._playing.update()
        tracks = (self._rows.get_item(position)
                  for position in range(self._starts[0], self._track_end()))
        ordinal = playing_ordinal(tracks, self._playing.ids, player.track.index)
        return None if ordinal is None else self._starts[0] + ordinal

    def _track_end(self):
        """The list position after the last track shown (the tracks' sections are one run
        after the hero, each as its filter leaves it)."""
        if self.item is None or not self._starts:
            return 0
        return self._starts[0] + self._shown_tracks()

    def _filtered_out(self):
        """Whether the filter hides the song playing, which the playlist holds."""
        player = self._playing.player
        if not self.filter_bar.search or player is None or player.track is None:
            return False
        tracks = (track for group in self.item.groups for track in group.entries)
        return playing_ordinal(tracks, self._playing.ids, player.track.index) is not None

    async def _reveal(self):
        """reveal_playing()'s work: scroll_to() the row with the focus, a frame or more
        apart until the row has it (REVEAL_FRAMES at most), the wish kept until the page has
        been shown (a push moves the focus into the page itself) and while the tracks may
        still come."""
        for _attempt in range(REVEAL_FRAMES):
            if not self._reveal_wanted:
                return
            position = self._playing_position()
            if position is None and self._starts and self._filtered_out():
                self.filter_bar.set_text('')  # every song shown again, the one playing too
                position = self._playing_position()
            if position is None:
                if self._starts:  # the tracks are there, and the song is not among them
                    self._reveal_wanted = False
                return
            if self.list_view.get_mapped():
                # scroll_to() moves the focus itself only while the list holds it; else it
                # moves the list's focus item, and the list's grab_focus() focuses that.
                self.list_view.scroll_to(position, Gtk.ListScrollFlags.FOCUS, None)
                if not self._has_focus_at(position):
                    self.list_view.grab_focus()
            await next_frame(self.list_view)
            if self._has_focus_at(position):
                if self._visible:
                    self._reveal_wanted = False
                return

    def _has_focus_at(self, position):
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        row = _row_of(focus) if focus is not None and focus.is_ancestor(self.list_view) else None
        return row is not None and row.track_row.context_item is self._rows.get_item(position)

    # The selection mode.

    def _all_tracks(self):
        """Every track of the item shown, its filter aside, in its groups' order: what a
        selected track's place among its song's entries counts in (selection.Places)."""
        item = self.item
        if item is None:
            return []
        return [track for group in item.groups for track in group.entries]

    def _selectable(self):
        """The tracks shown, in order: what the selection mode selects among. A filtered
        list growing back (ShownModel) counts whole: its rows still to come are shown as
        far as a selection goes, so a filter loosened keeps what was selected."""
        tracks = []
        for model in self._track_models:
            if isinstance(model, ShownModel):
                tracks.extend(model.items())
            else:
                tracks.extend(model.get_item(position)
                              for position in range(model.get_n_items()))
        return tracks

    def _update_selection(self, item):
        """Offer the mode while tracks show; which batch actions apply (Remove from Playlist
        on a playlist of the user's, Remove from Favourites on Favourite Songs, Remove from
        Library… on the library's album or playlist); what is no longer shown leaves the
        selection."""
        mode = self.selection_mode
        mode.set_available(bool(self._track_models))
        playlist = item if item.kind == 'playlist' and is_manageable(item) else None
        mode.set_context(playlist, library=is_library_id(item.id or ''),
                         favourites=item.kind == 'playlist' and item.favourites)
        mode.prune()

    def _on_selecting(self, _selection, _pspec):
        self._places.forget()

    def _on_selection_changed(self, selection):
        """The bound rows' check boxes and descriptions, and the table header's room."""
        for list_item in self._bound:
            track = list_item.get_item()
            selected = selection.has(track)
            list_item.get_child().track_row.set_selected(selection.active, selected)
            list_item.set_accessible_description(row_description(
                selection.active, selected,
                self._playing.description(track, self._playing.matches(track))))
        for header in list(self._table_headers):
            if header.get_child() is not None:
                header.get_child().set_selecting(selection.active)
        self._update_sort_button()

    def focused_track(self, focus):
        """The Track of the row with the focus `focus` in the list, or None (the window's
        selection keys: keyboard.selection_key())."""
        track = context_menu.focused(self.list_view, focus)
        return track if isinstance(track, Track) else None

    def _take_refocus(self, item):
        """The songs show again after Delete's removal: the focus, lost with its row, goes to
        the row now in its place (the last when it was the last), while it is nowhere else;
        again at the next showing while more removals are under way."""
        refocus = self._refocus
        if not self._going:
            self._refocus = None
        if refocus is None or refocus[0] is not item or not self._starts:
            return
        app().spawn(self._refocus_at(refocus[1]))

    async def _refocus_at(self, position):
        """_take_refocus()'s work, from the next frame (the list makes the new rows at its
        layout, and drops the one that had the focus), a frame apart until the row has it
        (REVEAL_FRAMES at most)."""
        for _attempt in range(REVEAL_FRAMES):
            await next_frame(self.list_view)
            root = self.get_root()
            focus = root.get_focus() if root is not None else None
            if focus is not None and not (focus is self.list_view
                                          or focus.is_ancestor(self.list_view)):
                return  # the focus went elsewhere meanwhile: left there
            end = self._track_end()
            if not self._starts or end <= self._starts[0] or not self.list_view.get_mapped():
                return
            target = min(position, end - 1)
            if self._has_focus_at(target):
                return
            focus_position(self.list_view, target)

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
        header.get_child().set_selecting(self.selection_mode.active)
        header.get_child().set_columns(self._shown_columns(True))
        self._table_headers.add(header)

    def _on_bind_header(self, _factory, header):
        label = header.get_child()
        section = bisect.bisect_right(self._starts, header.get_start()) - 1
        if not isinstance(header.get_item(), Track):
            section = -1  # the hero's and the suggestions' sections have no heading
        label.set_visible(section >= 0)
        label.set_label(self._headings[section] if section >= 0 else '')

    def _on_activate(self, _list_view, position):
        track = self._rows.get_item(position)
        if isinstance(track, Track) and not self.selection_mode.activated(track):
            # A track not out yet plays nothing (its row says so); the others of an album
            # with such tracks play among the released ones (release.released_play()).
            target = released_play(self.item, track)
            if target is not None:
                play, start_with, start_id = target
                self.get_root().play_request(play, start_with=start_with, start_id=start_id)

    # The hero's links and menus.

    def _on_artist_clicked(self, _button):
        # A playlist's curator: their page (window.open_item: an Apple curator's category
        # page, a third party's page in the browser). An album's artist: what the library
        # holds of them when it has them (window.open_item); else as Go to Artist does,
        # Apple Music's artist page.
        if self.item is not None and self.item.kind == 'playlist':
            if self._curator is not None:
                self.get_root().open_item(self._curator)
        elif self._artist is not None:
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
        """More under the notes, while they are cut to their three lines; at the first paint,
        the table as its breakpoint has it (the page assumed it before: expects_table())."""
        if not self._table_checked:
            self._table_checked = True
            current = self.get_child().get_current_breakpoint()
            self.table = current is self.table_breakpoint
        layout = self.summary_label.get_layout()
        cut = self.summary_label.get_mapped() and layout is not None and layout.is_ellipsized()
        if cut != self.more_notes_button.get_visible():
            self.more_notes_button.set_visible(cut)

    def _on_play_clicked(self, _button):
        self._play(shuffle=False)

    def _on_shuffle_clicked(self, _button):
        self._play(shuffle=True)

    def _play(self, shuffle):
        """Play the item, or (a pre-release album) the tracks of it that are out already."""
        target = released_play(self.item)
        if target is not None:
            self.get_root().play_request(target[0], shuffle=shuffle)
