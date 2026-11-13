# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What can be done to an album, playlist, song, station, artist or video: the window's item
actions, the menus that offer them, and what a drop on the sidebar or the player bar does.

    actions = ItemActions(window, app)     # made once by the window; adds the win.* actions
    menu = actions.menu_for(obj)           # a Gio.Menu for an Item or a Track, or None
    menu = actions.menu_for(track, queued=True)   # the item playing's, or Up Next's
    actions.go_to(obj, 'album')            # obj's album's page ('artist': its artist's)
    actions.show_artist(obj)               # a link's artist: the library's page of them
    actions.add_to_library(item)           # a catalog album's or playlist's page's Add button
    actions.favourite_artist(artist, True) # an artist page's star (quiet=True: no toast)
    actions.known_rating(('artist', id))   # 1, 0, -1 as the engine last said, or None
    actions.drop(playlist, refs)           # a library.ItemRefs dropped on a sidebar playlist
    actions.add_items_to_playlist(playlist_id, [album])   # its songs, in order, one toast
    actions.queue_drop(refs, next_up=False)   # dropped on the player bar: queued
    actions.move_in_playlist(playlist, 3, 1)   # its 4th song 2nd (playlist_order.py)
    actions.queue_objects(tracks, later=False)  # a selection's Play Next (or Later)
    actions.remove_entries(playlist, tracks)    # a selection's Remove from Playlist, Undo
    actions.remove_favourites(tracks)           # Favourite Songs' Remove from Favourites, Undo

The actions, each on the window (win.*) with a GLib.Variant target "(ss)", the (kind, id) of
what it acts on (an Item's kind and id, or 'song' and a Track's id):

    item-play            the item, or a track's album or playlist from the track
    item-play-next       queued after the item playing (mk.playNext)
    item-play-later      queued at the end (mk.playLater)
    item-love            loved: a song goes into Favourite Songs (a Suggest Less replaced);
                         an artist made a favourite (their star, which is not a rating:
                         Engine.favourite_artist)
    item-unlove          the love taken back
    item-suggest-less    Apple's Suggest Less: the rating -1, which replaces a favourite
    item-undo-suggest-less   the Suggest Less taken back
    item-add-to-library  a catalog item added to the library
    item-remove-from-library   a song, album, music video or playlist of Apple's taken out
                         of the library, once a dialog confirms
    item-create-station  the station Apple seeds from a song or an artist, played at once
    item-go-to-album     the page of the album a song is on (related.py finds it)
    item-go-to-artist    the page of the artist a song, video or album is by
    item-view-credits    a song's credits, in a dialog (dialogs/credits.py), by its catalog
                         id (credits_target)
    item-open-in-browser its music.apple.com page, in the default browser (Gtk.UriLauncher)
    item-copy-link       that page's address, on the clipboard

and item-add-to-playlist, "(sss)" (playlist id, kind, id): a song or a music video added to a
library playlist, or every song of an album or a playlist (tracks_of(): the library's, else
the engine's read of them), in order, in batches, with one toast that counts them; the same
add is not made twice while it runs. The playlists' own, each through a dialog
(dialogs/playlist.py, dialogs/add_songs.py) but Duplicate:

    item-new-playlist    a playlist made in the playlist dialog (its name, description,
                         folder and whether it is public): holding the song or video of the
                         target (an album's or a playlist's songs, named after it), or in
                         the folder it names ('folder', 'root': the top level)
    item-rename          a playlist's Edit Details… (the playlist dialog, filled in: its
                         name, description, folder and whether it is public), or a folder's
                         Rename… (its name)
    item-delete          a playlist, or a folder with what is in it, once a dialog confirms
    item-new-folder      a folder named in a dialog, in the folder the target names
                         ('folder', 'root': the top level)
    item-duplicate       a library playlist copied into a new playlist of the user's, named
                         "<name> Copy" (duplicate_name()), in its folder, its page shown
    item-add-songs       a playlist of the user's: songs of the library and of Apple Music's
                         catalogue picked in a dialog (dialogs/add_songs.py), added in one
                         write (add_items_to_playlist())

and item-remove-from-playlist, "(ssi)" (playlist id, track id, the track's index): one entry
of a playlist taken out; item-move-to-folder, "(sss)" (folder id, kind, id): a playlist (or
folder) moved into the folder ('root': the top level), shown at once (Library.hold()), put
back if Apple refuses, with Undo on its toast; with an empty folder id, into a new folder
named in a dialog and made beside it (Move to Folder's New Folder…); item-remove-from-queue,
"(is)" (the queue index, the entry's id): an Up Next entry after the one playing taken out
of the queue (Player.remove_from_queue); item-move-in-queue, "(iis)" (the queue index, the
index to move it to, the entry's id): an Up Next entry moved within its section
(Player.move_in_queue: Move Up, Move Down, Move to Top, Move to Bottom, an Up Next entry's
Play Next, their keys, a drop), announced to assistive technology; item-move-in-playlist,
"(ssii)" (playlist id, track id, the track's index, the index to move it to): Move Up, Move
Down, Move to Top or Move to Bottom in a playlist of the user's
(playlist_order.PlaylistOrder: shown at once, written after a pause, so a burst is one
write); item-undo-reorder, "s" (playlist id), the toast's Undo of a new order;
item-undo-remove, "s" (playlist id), the toast's Undo of a selection's Remove from Playlist
(the entries put back in one write, unless the playlist changed since);
item-undo-unfavourite, "s" (the toast's token), the toast's Undo of a selection's Remove from
Favourites (the songs loved again).

A track list's selection (widgets/selection_mode.py) acts through the methods above, the
selected tracks in the order shown: Play Next and Play Later queue each run of songs as one
`songs` command (queue_commands(), as a drop on the player bar does too; the Player sends it
again without the songs MusicKit cannot find, and one song at a time goes when MusicKit
refuses the list still); Add to Playlist is add_items_to_playlist(); Remove from
Playlist is one write of the entries kept (Engine.remove_playlist_entries()); Remove from
Library asks once and takes them out one after the other, hidden at once, one toast and one
sync after; Favourite Songs' Remove from Favourites unloves each song (one rating write a song,
RATING_WRITES at once), the hearts and Favourite Songs' rows changed at once and put back
for any write that failed, one toast with Undo, Favourite Songs read again after.

A target names an object the menu was built for (remembered, the last REMEMBERED of them)
or one the library has; failing both, the target's kind and id are used as they are. Each
action awaits the engine (started first when it is down and the account is signed in, as a
play request does) and confirms with a toast, or reports the EngineError
(app.report: signed out, that opens the sign-in). After a song was added to a playlist, or a
song loved or unloved, the playlist (Favourite Songs) is fetched again and merged into the
library's Item, so an open page shows the change at once. After an album or a playlist was
added to the library, the library notes it (Library.note_added(): its page says In Library at
once, ahead of Apple's listing) and a quick sync reads it back.

A track added or removed has its playlist fetched again, then read into
library.json by a playlists pass that reads its tracks
(playlist_order.sync_tracks()); before either, and before a playlist is deleted, its order
still to be written is (PlaylistOrder.flush()).
An item's rating (loved, Suggest Less or neither): a menu shows what the engine said last
this session (its `rated` signal), else whether the library holds it as a favourite
(library.json's favourites, Library.is_favourite), and asks again (engine.rating) as it
opens; an artist's favourite the same way, read by engine.is_favourite_artist. In the demo
an artist's favourite is the session's own (the demo engine remembers it); every other
write says it is not available.

Its parts: playlist_actions.py (PlaylistActions, ItemActions' base: the playlists' and
folders' writes and Remove from Library), item_menu.py (the menus), item_targets.py (what
each action takes of an object), web_links.py (the music.apple.com addresses) and
action_messages.py (what the actions say).

Only Gio, GLib and GObject at import time besides Gtk's UriLauncher, used when a page is
opened: tests build the menus and run the actions with a stand-in window, app and engine.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gio, GLib, Gtk

from . import related
from .action_messages import (added_message, love_messages, not_found_message,
                              queue_message, queue_move_message, removed_message,
                              suggest_less_messages, unfavourited_messages)
from .backend.errors import EngineError
from .backend.api import is_library_id
from .item_menu import build_menu, rating_actions
from .item_targets import (SOURCE_KINDS, _queue_kind, _song_id, _synthetic, adds_songs,
                           container_tracks, credits_target, describe, favourite_places,
                           favourite_target, is_manageable, library_target, move_targets,
                           playlist_song, playlist_track, pre_adds, queue_commands,
                           queue_target, queue_targets, queued_count, rating_target,
                           station_target)
from .library import (FRAME_BUDGET, TRACK_REF_KINDS, Item, ItemRefs, Track, entries_without,
                      yield_to_frames)
from .playlist_actions import PlaylistActions
from .playlist_order import PlaylistOrder, refresh_playlist, sync_tracks
from .web_links import (is_apple_music_url, is_shareable, needs_catalog_artist,
                        needs_catalog_url, web_url)

log = logging.getLogger(__name__)

TARGET = GLib.VariantType.new('(ss)')
PLAYLIST_TARGET = GLib.VariantType.new('(sss)')
ENTRY_TARGET = GLib.VariantType.new('(ssi)')
QUEUE_ENTRY_TARGET = GLib.VariantType.new('(is)')
QUEUE_MOVE_TARGET = GLib.VariantType.new('(iis)')
MOVE_TARGET = GLib.VariantType.new('(ssii)')

# How many of the objects menus were built for are remembered for their actions.
REMEMBERED = 64
# How many rating writes a selection's Remove from Favourites (and its Undo) has under way
# at once: one write a song, a few side by side.
RATING_WRITES = 4


class ItemActions(PlaylistActions):
    """The window's item actions. `window` gives play_request(), get_clipboard() and
    add_action(); `app` the engine, the player, the library, spawn(), toast(), report() and
    refuse_in_demo(). See the module."""

    def __init__(self, window, app):
        self.window = window
        self.app = app
        self._remembered = OrderedDict()  # (kind, id) -> the object a menu was built for
        self._ratings = {}  # rating_target -> 1, 0 or -1, as the engine last said
        self._menu_rated = None  # the rating target of the last menu built
        self._adding = set()  # (playlist id, what) of each add of many songs under way
        # playlist id -> (the ids kept, the entries before, how many went) of a selection's
        # Remove from Playlist, for its toast's Undo
        self._removed = {}
        # the toast's token -> (the rating targets that went, their places, Favourite Songs'
        # Item dict and track ids before, the places that went) of a selection's Remove from
        # Favourites, for its toast's Undo
        self._unfavourited = {}
        self._unfavourite_token = 0
        app.engine.connect('rated', self._on_rated)
        handlers = {
            'item-play': self._on_play,
            'item-play-next': self._on_play_next,
            'item-play-later': self._on_play_later,
            'item-love': self._on_love,
            'item-unlove': self._on_unlove,
            'item-suggest-less': self._on_suggest_less,
            'item-undo-suggest-less': self._on_undo_suggest_less,
            'item-add-to-library': self._on_add_to_library,
            'item-go-to-album': self._on_go_to_album,
            'item-go-to-artist': self._on_go_to_artist,
            'item-open-in-browser': self._on_open_in_browser,
            'item-copy-link': self._on_copy_link,
            'item-new-playlist': self._on_new_playlist,
            'item-rename': self._on_rename,
            'item-delete': self._on_delete,
            'item-new-folder': self._on_new_folder,
            'item-remove-from-library': self._on_remove_from_library,
            'item-create-station': self._on_create_station,
            'item-view-credits': self._on_view_credits,
            'item-duplicate': self._on_duplicate,
            'item-add-songs': self._on_add_songs,
        }
        self.actions = {}
        for name, handler in handlers.items():
            self._add(name, TARGET, handler)
        self._add('item-add-to-playlist', PLAYLIST_TARGET, self._on_add_to_playlist)
        self._add('item-remove-from-playlist', ENTRY_TARGET, self._on_remove_from_playlist)
        self._add('item-move-to-folder', PLAYLIST_TARGET, self._on_move_to_folder)
        self._add('item-remove-from-queue', QUEUE_ENTRY_TARGET, self._on_remove_from_queue)
        self._add('item-move-in-queue', QUEUE_MOVE_TARGET, self._on_move_in_queue)
        self._add('item-move-in-playlist', MOVE_TARGET, self._on_move_in_playlist)
        self._add('item-undo-reorder', GLib.VariantType.new('s'), self._on_undo_reorder)
        self._add('item-undo-remove', GLib.VariantType.new('s'), self._on_undo_remove)
        self._add('item-undo-unfavourite', GLib.VariantType.new('s'),
                  self._on_undo_unfavourite)
        self.playlist_order = PlaylistOrder(app, refresh=self._refresh_playlist)

    def shown_window(self):
        """The window, for what shows a page or a dialog in it: the mini player, which
        takes its place and whose Up Next pane runs these actions, is left first
        (Application.show_main_window()), so the page or the dialog is seen."""
        host = getattr(self.app, 'mini_player', None)
        if host is not None and host.shown:
            self.app.show_main_window()
        return self.window

    def announce(self, text):
        """Tell assistive technology `text` through the window in sight
        (Application.announce(): the mini player while it shows; GTK drops an announcement
        from a hidden window), else through the window."""
        announce = getattr(self.app, 'announce', None)
        if announce is not None:
            announce(text)
        else:
            self.window.announce(text, Gtk.AccessibleAnnouncementPriority.MEDIUM)

    def _add(self, name, parameter_type, handler):
        action = Gio.SimpleAction.new(name, parameter_type)
        action.connect('activate', handler)
        self.window.add_action(action)
        self.actions[name] = action

    @property
    def engine(self):
        return self.app.engine

    @property
    def library(self):
        return self.app.library

    # -- menus -----------------------------------------------------------------------------

    def menu_for(self, obj, queued=False, queue_entry=None, queue_moves=None):
        """The menu for obj (build_menu), obj remembered for its actions; None when nothing
        applies. `queued`: obj is in the player's queue (now_playing_track()); `queue_entry`
        its (index, id) there when Up Next may take it out (build_menu). The rating actions'
        state shows obj's rating, as last known; with the engine up, it is asked again as the
        menu opens."""
        named = describe(obj)
        if named is None:
            return None
        menu = build_menu(obj, self.playlists() if playlist_song(obj) or adds_songs(obj)
                          else (),
                          self._storefront(), here=self._shown(), queued=queued,
                          container=self.container(obj), moves=self.move_targets(obj),
                          removable=self.removal_target(obj), queue_entry=queue_entry,
                          queue_moves=queue_moves,
                          reorder=self._can_reorder(obj),
                          held=isinstance(obj, Item) and self.library.holds(obj))
        if menu is None:
            return None
        self._remember(named, obj)
        rated = rating_target(obj) or favourite_target(obj)
        self._menu_rated = rated
        rating = self._ratings.get(rated) if rated is not None else 0
        if rating is None:  # the engine has not said this session: the library's favourites
            is_favourite = getattr(self.library, 'is_favourite', None)
            rating = 1 if is_favourite is not None and is_favourite(obj) else 0
        self._show_rating(rating)
        if rated is not None and self._engine_ready():
            self.app.spawn(self._refine(rated))
        return menu

    def container(self, obj):
        """The playlist of the user's that the Track obj is shown in (its group plays that
        playlist: a playlist's page), or None: where Remove from Playlist applies."""
        if not isinstance(obj, Track) or obj.play.get('kind') != 'playlist':
            return None
        playlist = self.library.by_id('playlist', obj.play.get('id'))
        return playlist if is_manageable(playlist) else None

    def _can_reorder(self, obj):
        """Whether a menu offers the moves (Move Up and the rest) for the Track obj: not while
        the page shown lists its playlist filtered (DetailPage.can_reorder()), where the
        order shown is not the playlist's."""
        view = getattr(self.window, 'navigation_view', None)
        page = view.get_visible_page() if view is not None else None
        container = self.container(obj)
        if container is None or getattr(page, 'item', None) is not container:
            return True
        can_reorder = getattr(page, 'can_reorder', None)
        return can_reorder is None or can_reorder()

    def move_targets(self, obj):
        """Where a playlist or folder of the library's can be moved (move_targets()), or
        None."""
        return move_targets(self.library.playlist_tree(), obj)

    def playlists(self):
        """The library playlists that take songs, nested in their folders as the sidebar
        has them, for Add to Playlist: a list of (id, title, children), `children` None for a
        playlist and a folder's own entries for a folder. Favourite Songs, the ones Apple
        says cannot be edited and the folders holding none of the rest are left out."""
        def entries(node):
            found = []
            for child in node.children:
                if child.kind == 'folder':
                    inside = entries(child)
                    if inside:
                        found.append((child.id, child.item.title, inside))
                elif child.kind == 'playlist' and child.item.editable:
                    found.append((child.id, child.item.title, None))
            return found
        return entries(self.library.playlist_tree().root)

    def _show_rating(self, value):
        """The rating actions' state (rating_actions()): a menu shows Favourite while the
        item is not loved, Remove from Favourites while it is, Suggest Less while it is
        neither and Undo Suggest Less while it is rated -1."""
        for action, enabled in rating_actions(value).items():
            self.actions[action].set_enabled(enabled)

    def known_rating(self, rated):
        """What the engine last said this session of the rating (or an artist's favourite)
        `rated` (rating_target, favourite_target): 1, 0 or -1, or None."""
        return self._ratings.get(tuple(rated)) if rated is not None else None

    def forget_account(self):
        """Sign-out (Window.forget_account_pages()): the ratings and favourites the engine
        said, the objects menus were built for and the playlists' orders pending and their
        Undo were the account's, not the next one's (the Engine forgets its own as it stops)."""
        self._ratings.clear()
        self._menu_rated = None
        self._remembered.clear()
        self._removed.clear()
        self._unfavourited.clear()
        self.playlist_order.forget()

    async def _refine(self, rated):
        try:
            # Its `rated` signal brings the answer.
            if rated[0] == 'artist':
                await self.engine.is_favourite_artist(rated[1])
            else:
                await self.engine.rating(*rated)
        except EngineError as error:
            log.debug('rating of %s %s: %s', *rated, error)

    def _on_rated(self, _engine, kind, item_id, value):
        self._ratings[(kind, item_id)] = value
        if (kind, item_id) == self._menu_rated:
            self._show_rating(value)

    def _remember(self, named, obj):
        self._remembered[named] = obj
        self._remembered.move_to_end(named)
        while len(self._remembered) > REMEMBERED:
            self._remembered.popitem(last=False)

    def _resolve(self, kind, item_id):
        """The object a target names: one a menu was built for, else the library's."""
        obj = self._remembered.get((kind, item_id))
        if obj is None and kind != 'song':
            obj = self.library.by_id(kind, item_id)
        return obj

    def _unpack(self, parameter):
        kind, item_id = parameter.unpack()
        return self._resolve(kind, item_id), kind, item_id

    def _storefront(self):
        return getattr(self.library, 'storefront', None) or 'us'

    def _shown(self):
        """The Item of the page shown (window.shown_item), or None."""
        shown_item = getattr(self.window, 'shown_item', None)
        return shown_item() if shown_item is not None else None

    def _engine_ready(self):
        return (not self.app.demo and self.engine.state == 'up'
                and bool(self.engine.authorized))

    # -- running -----------------------------------------------------------------------------

    def _run(self, method, args, message=None, ensure=True, after=None, playlist=None,
             demo=False):
        """await method(*args), with the engine up first when `ensure` (started when it is
        down and the account signed in; the Player's own commands do that themselves), then
        toast message and await after(); an EngineError is reported instead (app.report).
        `playlist`: the id of the playlist the write changes, whose order still to be
        written goes first (PlaylistOrder.flush()). The task, whose result says whether the
        method succeeded (False once reported), or None with the demo library (which says
        so), unless `demo` (the demo engine does it: an artist's favourite)."""
        if not demo and self.app.refuse_in_demo():
            return None

        async def run():
            try:
                if ensure:
                    await self.app.player.ensure_engine()
                if playlist:
                    await self.playlist_order.flush(playlist)
                await method(*args)
            except EngineError as error:
                self.app.report(error)
                return False
            if message:
                self.app.toast(message)
            if after is not None:
                await after()
            return True

        return self.app.spawn(run())

    def _on_play(self, _action, parameter):
        obj, kind, item_id = self._unpack(parameter)
        if isinstance(obj, Track):
            if obj.play.get('kind') and obj.play.get('id'):
                self.window.play_request(obj.play, start_with=obj.index, start_id=obj.id)
            else:
                self.window.play_request({'kind': _queue_kind(obj), 'id': _song_id(obj)})
        elif isinstance(obj, Item):
            self.window.play_request(obj.play)
        else:
            self.window.play_request({'kind': kind, 'id': item_id})

    def _on_create_station(self, _action, parameter):
        """Play the station Apple seeds from the song or artist the target names, at once,
        as Apple's players do: a play request of {kind: 'station', id: 'ra.<catalog id>'}
        (station_target; a catalog id the target itself carries when the object is not
        known), which the Player takes as a station."""
        obj, kind, item_id = self._unpack(parameter)
        if obj is not None:
            station = station_target(obj)
        elif kind in ('song', 'artist') and item_id and not is_library_id(item_id):
            station = f'ra.{item_id}'
        else:
            station = None
        if station is None:
            self.app.toast(_('No station can be made from this'))
            return
        self.window.play_request({'kind': 'station', 'id': station})

    def _queue(self, parameter, later):
        obj, kind, item_id = self._unpack(parameter)
        target = queue_target(obj) if obj is not None else (kind, item_id)
        if target is None:
            self.app.toast(_('This cannot be queued'))
            return None
        message = queue_message(obj.title if obj is not None else '', later)
        if later:
            return self._run(self.app.player.play_later, target, message, ensure=False)
        return self._run(self.app.player.play_next, target, message, ensure=False)

    def _on_play_next(self, _action, parameter):
        return self._queue(parameter, later=False)

    def _on_play_later(self, _action, parameter):
        return self._queue(parameter, later=True)

    def _rate(self, parameter, love):
        obj, kind, item_id = self._unpack(parameter)
        if kind == 'artist':
            return self.favourite_artist(obj, love, target=(kind, item_id))
        target = rating_target(obj) if obj is not None else (kind, item_id)
        if target is None:
            self.app.toast(_('This cannot be a favourite'))
            return None
        loved, unloved = love_messages(target[0])
        # A song loved goes into Favourite Songs: that playlist is fetched again.
        after = self._refresh_favourites if target[0] == 'song' else None
        if love:
            return self._run(self.engine.love, target, loved, after=after)
        return self._run(self.engine.unlove, target, unloved, after=after)

    def favourite_artist(self, obj, favourite, quiet=False, target=None):
        """Make the artist Item obj one of the account's favourites (`favourite`), or no
        longer (favourite_target; failing an obj, the ('artist', catalog id) `target`),
        confirmed with a toast unless `quiet` (the page's star shows it); a failure is
        reported. The task, whose result says whether it was done (_run()), or None when
        there is no catalog artist to favourite. In the demo the demo engine remembers it."""
        found = favourite_target(obj) if obj is not None else None
        if found is None and target is not None and not is_library_id(target[1]):
            found = ('artist', str(target[1]))
        if found is None or not found[1]:
            self.app.toast(_('This cannot be a favourite'))
            return None
        loved, unloved = love_messages('artist')
        message = None if quiet else (loved if favourite else unloved)
        method = self.engine.favourite_artist if favourite else self.engine.unfavourite_artist
        return self._run(method, (found[1],), message, ensure=not self.app.demo, demo=True)

    def _on_love(self, _action, parameter):
        return self._rate(parameter, love=True)

    def _on_unlove(self, _action, parameter):
        return self._rate(parameter, love=False)

    def _suggest_less(self, parameter, undo):
        """Suggest Less (the rating -1), or take it back (the rating removed). The menu
        offers no Suggest Less for a favourite, but one chosen before the menu's read
        answered may replace one, and a song is then out of Favourite Songs: that playlist
        is fetched again unless the song was known not to be loved."""
        obj, kind, item_id = self._unpack(parameter)
        target = rating_target(obj) if obj is not None else (kind, item_id)
        if target is None:
            self.app.toast(_('This cannot be rated'))
            return None
        set_message, undone = suggest_less_messages()
        if undo:
            return self._run(self.engine.unlove, target, undone)
        loved = target[0] == 'song' and self._ratings.get(target) not in (0, -1)
        return self._run(self.engine.suggest_less, target, set_message,
                         after=self._refresh_favourites if loved else None)

    def _on_suggest_less(self, _action, parameter):
        return self._suggest_less(parameter, undo=False)

    def _on_undo_suggest_less(self, _action, parameter):
        return self._suggest_less(parameter, undo=True)

    def _on_add_to_library(self, _action, parameter):
        obj, kind, item_id = self._unpack(parameter)
        return self.add_to_library(obj, (kind, item_id))

    def add_to_library(self, obj, target=None):
        """Add obj (an Item or a Track; failing one, the (kind, id) `target`) to the
        library, confirmed with a toast; then an album or playlist is noted as added
        (Library.note_added()) and a quick sync reads it back. The task, whose result says
        whether the add succeeded (_run()), or None (nothing to add, or the demo library)."""
        target = library_target(obj) if obj is not None else target
        if target is None:
            self.app.toast(_('This is in your library already'))
            return None
        title = obj.title if obj is not None else ''
        if pre_adds(obj):
            # Translators: a toast once an album not out yet is added to the library.
            message = _('Pre-added “{title}” to your library').format(title=title)
        else:
            message = (_('Added “{title}” to your library').format(title=title) if title
                       else _('Added to your library'))

        async def after():
            if isinstance(obj, Item):
                self.library.note_added(obj)
            await self._refresh_library()

        return self._run(self.engine.add_to_library, target, message, after=after)

    def _on_go_to_album(self, _action, parameter):
        return self.go_to(self._unpack(parameter)[0], 'album')

    def _on_go_to_artist(self, _action, parameter):
        return self.go_to(self._unpack(parameter)[0], 'artist')

    def go_to(self, obj, kind, then=None):
        """Open the page of the album obj is on (`kind` 'album') or of the artist it is by
        ('artist'). An artist's is Apple Music's while the engine is up and obj has a catalog
        id (the engine names the artist exactly; their page shows the library's albums of
        theirs too); else, and for an album, the library's (related.library_album,
        library_artist) at once, else the catalog's, which the engine looks up (started first
        if need be, as for the other actions). Nothing is opened when that page is the one
        shown. A toast says when there is none. `then()` runs once the page is shown, opened
        or there already (Go to Current Song's: the focus onto the song). The engine's task,
        or None."""
        if obj is None:
            self.app.toast(not_found_message(kind))
            return None
        target = related.catalog_target(obj)
        if kind == 'artist' and target is not None and self._engine_ready():
            return self.app.spawn(self._go_to_catalog(obj, kind, target, then))
        if self._go_to_library(obj, kind, then):
            return None
        if target is None or (kind == 'album' and target[0] == 'album'):
            self.app.toast(not_found_message(kind))
            return None
        if self.app.refuse_in_demo():
            return None
        return self.app.spawn(self._go_to_catalog(obj, kind, target, then))

    async def _go_to_catalog(self, obj, kind, target, then=None):
        try:
            await self.app.player.ensure_engine()
            answer = await self.engine.related(*target)
        except EngineError as error:
            if self._go_to_library(obj, kind, then):
                pass  # the library's page, rather than nothing
            elif error.status == 404:  # gone from the storefront's catalog: nowhere to go
                self.app.toast(not_found_message(kind))
            else:
                self.app.report(error)
            return
        found = related.from_answer(self.library, answer, kind, related.artist_name(obj))
        if found is not None:
            self._show_page(found, then)
        elif not self._go_to_library(obj, kind, then):
            self.app.toast(not_found_message(kind))

    def _go_to_library(self, obj, kind, then=None):
        """Show the library's album or artist of obj's: True when it has one."""
        found = (related.library_album(self.library, obj) if kind == 'album'
                 else related.library_artist(self.library, obj))
        if found is not None:
            self._show_page(found, then)
        return found is not None

    def _show_page(self, item, then=None):
        """Show item's page, unless it is the page shown already: an artist's is Apple
        Music's (window.open_artist_page), for an artist of the library's too. Then then()."""
        if not related.same_page(self._shown(), item):
            if item.kind == 'artist':
                self.shown_window().open_artist_page(item)
            else:
                self.shown_window().open_item(item)
        if then is not None:
            then()

    def show_artist(self, obj):
        """A link's artist (a row's, an album page's): what the library holds of the artist
        obj is by when the library has them (related.library_artist, window.open_item), else
        where Go to Artist goes."""
        found = related.library_artist(self.library, obj)
        if found is not None:
            self.shown_window().open_item(found)
            return None
        return self.go_to(obj, 'artist')

    async def _refresh_library(self):
        """Show what was just added: a quick sync (sync.py), which reads the songs and the
        shelves and keeps the rest of last time's file, so the item is in Songs and in
        Recently Added at once. Apple answers the write with no body, so there is nothing to
        merge in as _refresh_playlist() does; the item has to be read back."""
        self.app.start_sync(quick=True)

    def _on_add_to_playlist(self, _action, parameter):
        playlist_id, kind, item_id = parameter.unpack()
        obj = self._resolve(kind, item_id)
        if kind in SOURCE_KINDS:
            return self.add_items_to_playlist(playlist_id, [self._source(obj, kind, item_id)])
        track = playlist_track(obj) if obj is not None else (kind, item_id)
        if track is None:
            track = (kind, item_id)
        return self.add_to_playlist(playlist_id, track[1], obj.title if obj is not None else '',
                                    kind=track[0])

    def add_to_playlist(self, playlist_id, song_id, title='', kind='song'):
        """Add the song (or music video, `kind` 'video') to the library playlist, confirming
        with a toast that names both, and fetch the playlist again so its page shows it. The
        task, whose result says whether the add succeeded (_run()), or None."""
        if not song_id:
            self.app.toast(_('Only songs can be added to a playlist'))
            return None
        playlist = self.library.by_id('playlist', playlist_id)
        name = playlist.title if playlist is not None else ''
        if title and name:
            message = _('Added “{title}” to “{playlist}”').format(title=title, playlist=name)
        elif name:
            message = _('Added to “{playlist}”').format(playlist=name)
        else:
            message = _('Added to the playlist')
        return self._run(self.engine.add_to_playlist, (playlist_id, song_id, kind), message,
                         after=lambda: self._follow_tracks(playlist_id), playlist=playlist_id)

    def add_items_to_playlist(self, playlist_id, objects):
        """The songs of `objects` (albums, playlists, songs and music videos: Items and
        Tracks, in order; tracks_of()) added to the end of the library playlist in that
        order, in batches (Engine.add_tracks_to_playlist), with one toast for them all
        (added_message()); the playlist is then fetched again, as for one song, also after
        a failure partway (what went in stays). An add of the same things to the same
        playlist while one is under way (a second click) is not made again. The task,
        whose result says whether they were added (False once reported, or when there was
        nothing to add), or None (the demo library, or that add under way)."""
        if self.app.refuse_in_demo():
            return None
        key = (playlist_id, tuple(describe(obj) for obj in objects))
        if key in self._adding:
            log.debug('adding to %s already', playlist_id)
            return None
        self._adding.add(key)
        playlist = self.library.by_id('playlist', playlist_id)
        name = playlist.title if playlist is not None else ''

        async def run():
            sent = False
            try:
                await self.app.player.ensure_engine()
                tracks = await self.tracks_of(objects)
                if not tracks:
                    self.app.toast(_('There are no songs to add'))
                    return False
                await self.playlist_order.flush(playlist_id)
                sent = True
                count = await self.engine.add_tracks_to_playlist(playlist_id, tracks)
            except EngineError as error:
                self.app.report(error)
                if sent:
                    await self._follow_tracks(playlist_id)
                return False
            finally:
                self._adding.discard(key)
            self.app.toast(added_message(count, name))
            await self._follow_tracks(playlist_id)
            return True

        return self.app.spawn(run())

    async def tracks_of(self, objects):
        """The songs and music videos `objects` add to a playlist, in order, as (kind, id):
        a track's own (playlist_track()), an album's or a playlist's (container_tracks();
        one that came without them read through the engine's item(), which has them all,
        however Apple pages them). Raises the engine's EngineError."""
        tracks = []
        paused = time.monotonic()
        for obj in objects:
            if time.monotonic() - paused > FRAME_BUDGET:  # 40,000 songs: 100 ms at once
                await yield_to_frames()
                paused = time.monotonic()
            track = playlist_track(obj)
            if track is not None:
                tracks.append(track)
                continue
            if not adds_songs(obj):
                continue
            found = container_tracks(obj)
            if found is None and not _synthetic(obj.id):
                found = container_tracks(Item(await self.engine.item(obj.kind, obj.id)))
            tracks.extend(found or ())
        return tracks

    @staticmethod
    def _source(obj, kind, item_id):
        """The album or playlist a target names: the object itself, else one made of its
        kind and id, whose songs tracks_of() reads through the engine."""
        if isinstance(obj, Item) and obj.kind == kind:
            return obj
        return Item({'kind': kind, 'id': item_id})

    async def _refresh_playlist(self, playlist_id):
        """Bring a library playlist up to date after it changed on Apple's side
        (playlist_order.refresh_playlist())."""
        await refresh_playlist(self.app, playlist_id)

    async def _follow_tracks(self, playlist_id):
        """After a playlist's tracks changed (a song added or removed): the playlist read
        again at once, then into library.json by a playlists pass reading its tracks, so the
        change is there at the next launch."""
        await self._refresh_playlist(playlist_id)
        await sync_tracks(self.app, playlist_id)

    def move_in_playlist(self, playlist, from_index, to_index, at_once=False):
        """Move the playlist's song at from_index to to_index (PlaylistOrder.move(): shown
        at once, written after a pause or, `at_once`, now), the move announced to assistive
        technology. False when it cannot be moved there."""
        ids = playlist.track_ids() if isinstance(playlist, Item) else None
        if not self.playlist_order.move(playlist, from_index, to_index, at_once):
            return False
        track = playlist.groups[0].entries.get_item(to_index)
        announce = getattr(self.window, 'announce', None)
        if announce is not None:
            # Translators: said to screen reader users as a song is moved in a playlist:
            # “Harbour Lights” moved to position 4 of 12.
            announce(_('“{title}” moved to position {position} of {count}').format(
                title=track.title, position=f'{to_index + 1:n}', count=f'{len(ids):n}'),
                Gtk.AccessibleAnnouncementPriority.MEDIUM)
        return True

    def _on_move_in_playlist(self, _action, parameter):
        playlist_id, track_id, index, to_index = parameter.unpack()
        playlist = self.library.by_id('playlist', playlist_id)
        ids = playlist.track_ids() if playlist is not None else None
        if not ids or not 0 <= index < len(ids) or ids[index] != track_id:
            return False  # the list changed since the menu was made
        return self.move_in_playlist(playlist, index, to_index)

    def _on_undo_reorder(self, _action, parameter):
        return self.playlist_order.undo(parameter.get_string())

    async def _refresh_favourites(self):
        favourites = self.library.favourite_songs()
        if favourites is not None and favourites.id:
            await self._refresh_playlist(favourites.id)

    def can_drop(self, playlist):
        """Whether a track may be dropped on this sidebar playlist Item (one that takes
        songs; not a folder, not a fixed item, not Favourite Songs)."""
        return isinstance(playlist, Item) and playlist.editable

    def can_drop_refs(self, playlist, refs):
        """Whether a drop of `refs` (a library.ItemRefs) on this sidebar playlist Item adds
        what it carries: a playlist that takes songs (can_drop()), and songs, music videos,
        albums and playlists alone, the playlist itself not among them."""
        return (self.can_drop(playlist) and isinstance(refs, ItemRefs)
                and refs.only(*TRACK_REF_KINDS, *SOURCE_KINDS)
                and not any(ref.kind == 'playlist' and ref.id == playlist.id for ref in refs))

    def drop(self, playlist, refs):
        """A library.ItemRefs dropped on a sidebar playlist (can_drop_refs()): one song or
        music video added to it (add_to_playlist(), the toast naming it), or the songs of
        all it carries, albums' and playlists' too (add_items_to_playlist()). False when
        the drop is refused."""
        if not self.can_drop_refs(playlist, refs):
            return False
        if len(refs) == 1 and refs.tracks():
            ref = refs.refs[0]
            self.add_to_playlist(playlist.id, ref.id, ref.title, kind=ref.kind)
        else:
            self.add_items_to_playlist(playlist.id, self._ref_objects(refs))
        return True

    def _ref_objects(self, refs):
        """The objects an ItemRefs names, in order: those its drag source gave
        (ItemRefs.objects), else made of the Refs (the library's album or playlist, or one
        made of its kind and id; a track as an Item of its kind)."""
        if len(refs.objects) == len(refs):
            return refs.objects
        objects = []
        for ref in refs:
            obj = self.library.by_id(ref.kind, ref.id) if ref.kind in SOURCE_KINDS else None
            objects.append(obj if obj is not None else
                           Item({'kind': ref.kind, 'id': ref.id, 'title': ref.title}))
        return objects

    def queue_drop(self, refs, next_up=False):
        """What was dropped on the player bar (a library.ItemRefs) queued, each by its
        queue_targets() target: at the end, as Play Later does, or with `next_up` (Shift
        held) after the item playing, as Play Next does, in the order they were dragged. A
        toast confirms. False when the drop is refused (not all it carries can be
        queued)."""
        targets = queue_targets(refs)
        if targets is None:
            return False
        message = queue_message(refs.refs[0].title, not next_up, len(targets))
        self._run(self._send_queue, (queue_commands(targets), not next_up), message,
                  ensure=False)
        return True

    async def _send_queue(self, commands, later):
        """Queue queue_commands() `commands` in order: at the end (`later`), or after the item
        playing, each Play Next in front of the one after it. A list of songs MusicKit refuses
        ('api') even without the songs it cannot find (the Player's retry) is queued one song
        at a time instead. Raises the engine's EngineError."""
        player = self.app.player
        method = player.play_later if later else player.play_next
        for kind, item_id in (commands if later else list(reversed(commands))):
            try:
                await method(kind, item_id)
            except EngineError as error:
                if kind != 'songs' or error.code != 'api':
                    raise
                log.info('a list of songs was not queued (%s): one at a time instead', error)
                ids = item_id.split(',')
                for song_id in (ids if later else list(reversed(ids))):
                    await method('song', song_id)

    # -- a selection's actions (widgets/selection_mode.py) -----------------------------------

    def queue_objects(self, objects, later=False, total=None):
        """Play Next (or, `later`, Play Later) of several songs and music videos, a
        selection's in the order shown (its first PLAY_LIMIT of `total` selected): their
        queue targets as queue_commands() (a run of songs one command), one toast that
        counts them, and says when they are the first of more: only when `total` is more
        than `objects` (a song left out as it cannot be queued, one not out yet, is not a
        limit reached). The task, or None when none can be queued."""
        targets = [target for target in map(queue_target, objects) if target is not None]
        if not targets:
            self.app.toast(_('This cannot be queued'))
            return None
        commands = queue_commands(targets)
        title = objects[0].title if len(objects) == 1 else ''
        if total is not None and total <= len(objects):
            total = None  # every one selected was taken
        message = queue_message(title, later, queued_count(commands), total)
        return self._run(self._send_queue, (commands, later), message, ensure=False)

    def remove_entries(self, playlist, tracks):
        """A selection's Remove from Playlist, or Delete on a song (DetailPage's
        remove_focused()): the entries `tracks` (Tracks of the playlist Item `playlist`, one
        of the user's, by their places in it: Track.index) taken out in one write
        (Engine.remove_playlist_entries()), the order pending written first; a toast that
        counts them (names one), with Undo (item-undo-remove), then the playlist read again.
        The task, whose result says whether they went, or None (the demo library, or not a
        playlist of the user's)."""
        if not is_manageable(playlist) or playlist.kind != 'playlist':
            return None
        if self.app.refuse_in_demo():
            return None
        tracks = list(tracks)

        async def run():
            try:
                await self.app.player.ensure_engine()
                await self.playlist_order.flush(playlist.id)
                shown = playlist.track_ids() or []
                positions = sorted({track.index for track in tracks
                                    if 0 <= track.index < len(shown)
                                    and shown[track.index] == track.id})
                if not positions:
                    return False
                before = await self.engine.remove_playlist_entries(playlist.id, shown,
                                                                   positions)
            except EngineError as error:
                self.app.report(error)
                return False
            gone = set(positions)
            kept = [entry['id'] for place, entry in enumerate(before) if place not in gone]
            self._removed[playlist.id] = (kept, before, len(positions))
            title = tracks[0].title if len(tracks) == 1 else ''
            self.app.toast(removed_message(len(positions), playlist.title or '', title),
                           _('Undo'), 'win.item-undo-remove', GLib.Variant('s', playlist.id))
            await self._follow_tracks(playlist.id)
            return True

        return self.app.spawn(run())

    def _on_undo_remove(self, _action, parameter):
        """The toast's Undo after a selection's Remove from Playlist: the entries put back
        as they were, in one write, unless the playlist changed since (reported). The task,
        or None (nothing to put back)."""
        playlist_id = parameter.get_string()
        removed = self._removed.pop(playlist_id, None)
        if removed is None:
            return None
        kept, before, count = removed
        playlist = self.library.by_id('playlist', playlist_id)
        name = playlist.title if playlist is not None else ''
        if name:
            message = ngettext('Put back {count} song in “{playlist}”',
                               'Put back {count} songs in “{playlist}”',
                               count).format(count=f'{count:n}', playlist=name)
        else:
            message = ngettext('Put back {count} song', 'Put back {count} songs',
                               count).format(count=f'{count:n}')
        return self._run(self.engine.put_back_playlist_entries, (playlist_id, kept, before),
                         message, after=lambda: self._follow_tracks(playlist_id),
                         playlist=playlist_id)

    def remove_favourites(self, tracks):
        """A selection's Remove from Favourites (Favourite Songs' bar): each of the songs
        `tracks` unloved, one rating write a song (Engine.unlove, RATING_WRITES of them under
        way at once), shown at once: their hearts go (Library.set_favourites) and their rows
        leave Favourite Songs (entries_without()), both put back for the songs whose write
        did not go. One toast counts the songs that went, with Undo (item-undo-unfavourite);
        a failure is reported and the songs not yet written are not tried. Favourite Songs is
        read again after. The task, whose result says whether all went, or None (the demo
        library, or nothing that has a rating)."""
        playlist = self.library.favourite_songs()
        ids = (playlist.track_ids() if playlist is not None else None) or []
        targets, places = favourite_places(tracks, playlist, ids)
        if not targets:
            self.app.toast(_('This cannot be a favourite'))
            return None
        if self.app.refuse_in_demo():
            return None
        before = dict(playlist.raw) if playlist is not None else None
        gone = {place for target in targets for place in places[target]}
        self.library.set_favourites([target[1] for target in targets], False)
        shown = self._show_favourites(playlist, before, gone, ids)

        async def run():
            done, error = await self._rate_all(self.engine.unlove, targets)
            failed = [target for target in targets if target not in done]
            went = {place for target in done for place in places[target]}
            if failed:  # back on the page and in the hearts
                self.library.set_favourites([target[1] for target in failed], True)
                self._show_favourites(playlist, before, went, shown)
            if error is not None:
                self.app.report(error)
            if not done:
                return False
            self._unfavourite_token += 1
            token = str(self._unfavourite_token)
            self._unfavourited[token] = (done, places, before, ids, went)
            self.app.toast(unfavourited_messages(len(done))[0], _('Undo'),
                           'win.item-undo-unfavourite', GLib.Variant('s', token))
            await self._refresh_favourites()
            return not failed

        return self.app.spawn(run())

    def _on_undo_unfavourite(self, _action, parameter):
        """The toast's Undo after a selection's Remove from Favourites: the songs loved again
        (Engine.love, as remove_favourites() unloved them), their hearts and their rows on
        Favourite Songs back at once (the rows only while it lists what the removal left),
        taken away again for any whose write did not go, which is reported. The task, or
        None (nothing to put back)."""
        removed = self._unfavourited.pop(parameter.get_string(), None)
        if removed is None:
            return None
        if self.app.refuse_in_demo():
            return None
        targets, places, before, ids, gone = removed
        playlist = self.library.favourite_songs()
        self.library.set_favourites([target[1] for target in targets], True)
        left = [track_id for place, track_id in enumerate(ids) if place not in gone]
        shown = self._show_favourites(playlist, before, (), left)

        async def run():
            done, error = await self._rate_all(self.engine.love, targets)
            failed = [target for target in targets if target not in done]
            if failed:
                self.library.set_favourites([target[1] for target in failed], False)
                again = {place for target in failed for place in places[target]}
                self._show_favourites(playlist, before, again, shown)
            if error is not None:
                self.app.report(error)
            if done:
                self.app.toast(unfavourited_messages(len(done))[1])
            await self._refresh_favourites()
            return not failed

        return self.app.spawn(run())

    def _show_favourites(self, playlist, before, gone, listed):
        """Favourite Songs (`playlist`) shown as `before`, its Item dict as a selection found
        it, without the entries at the places `gone` (entries_without(); none: as it was),
        while it lists the tracks `listed` (their ids), so a change made since (a sync, a
        read of Apple's) is not undone. The ids it lists then, or None when it was left as
        it is."""
        if playlist is None or before is None or listed is None:
            return None
        if playlist.track_ids() != list(listed):
            return None
        update = entries_without(before, gone)
        if update is None:
            return None
        playlist.merge(update)
        return playlist.track_ids()

    async def _rate_all(self, method, targets):
        """await method(kind, id) for each rating target, RATING_WRITES at once, the engine
        up first: (the targets it went for, in order, the first EngineError or None). After
        a failure no more are started."""
        try:
            await self.app.player.ensure_engine()
        except EngineError as error:
            return [], error
        went = set()
        errors = []
        pending = iter(targets)

        async def writer():
            for target in pending:
                if errors:
                    return
                try:
                    await method(*target)
                except EngineError as error:
                    errors.append(error)
                    return
                went.add(target)

        await asyncio.gather(*(writer() for _ in range(min(RATING_WRITES, len(targets)))))
        return [target for target in targets if target in went], (errors[0] if errors else None)

    def _on_remove_from_playlist(self, _action, parameter):
        playlist_id, track_id, index = parameter.unpack()
        track = self._remembered.get(('song', track_id))
        title = track.title if track is not None else ''
        playlist = self.library.by_id('playlist', playlist_id)
        name = playlist.title if playlist is not None else ''
        if title and name:
            message = _('Removed “{title}” from “{playlist}”').format(title=title,
                                                                    playlist=name)
        else:
            message = _('Removed from the playlist')
        return self._run(self.engine.remove_from_playlist, (playlist_id, track_id, index),
                         message, after=lambda: self._follow_tracks(playlist_id),
                         playlist=playlist_id)

    def _on_remove_from_queue(self, _action, parameter):
        """An Up Next entry taken out of the queue (no toast: the row goes, and assistive
        technology is told)."""
        index, entry_id = parameter.unpack()
        player = self.app.player

        async def remove():
            try:
                removed = await player.remove_from_queue(index, entry_id)
            except EngineError as error:
                self.app.report(error)
                return
            if removed:
                self.announce(_('Removed from Up Next'))

        return self.app.spawn(remove())

    def _on_move_in_queue(self, _action, parameter):
        """An Up Next entry moved within its section (Player.move_in_queue), and where it
        went said to assistive technology (no toast: the row moves)."""
        index, to_index, entry_id = parameter.unpack()
        player = self.app.player
        queue = player.queue
        entry = queue.get_item(index) if 0 <= index < queue.get_n_items() else None

        async def move():
            try:
                moved = await player.move_in_queue(index, to_index, entry_id)
            except EngineError as error:
                self.app.report(error)
                return
            if moved and entry is not None:
                self.announce(queue_move_message(entry.title, entry.index,
                                                 player.queue_index,
                                                 player.queue.get_n_items()))

        return self.app.spawn(move())

    # -- credits -----------------------------------------------------------------------------

    def _on_view_credits(self, _action, parameter):
        """The song's credits in a dialog over the window, which asks the engine for them (a
        song without a catalog id, which has none, toasted). The dialog."""
        from .dialogs.credits import CreditsDialog

        obj, kind, item_id = self._unpack(parameter)
        if obj is None and kind == 'song':
            obj = Item({'kind': 'song', 'id': item_id})
        song_id = credits_target(obj)
        if song_id is None:
            self.app.toast(_('This song has no credits'))
            return None
        dialog = CreditsDialog(self.app, song_id, getattr(obj, 'title', '') or '')
        dialog.present(self.shown_window())
        return dialog

    # -- links -------------------------------------------------------------------------------

    async def link(self, obj, kind=None, item_id=None):
        """obj's music.apple.com page (web_url), a library album's catalog page when the
        engine can say (needs_catalog_url), a library artist's catalog page, which only the
        engine can find (needs_catalog_artist: started first if need be; its EngineError is
        raised), or None."""
        if obj is None:
            obj = Item({'kind': kind, 'id': item_id})
        if needs_catalog_artist(obj):
            return await self._catalog_artist_link(obj)
        if needs_catalog_url(obj) and self._engine_ready():
            try:
                url = await self.engine.catalog_url(obj.kind, obj.id)
            except EngineError as error:
                log.debug('catalog page of %s: %s', obj.id, error)
                url = None
            if url and is_apple_music_url(url):
                return url
        return web_url(obj, self._storefront())

    async def _catalog_artist_link(self, obj):
        songs = related.artist_song_ids(obj, self.library)
        if not songs:
            return None
        await self.app.player.ensure_engine()
        artist_id = await self.engine.catalog_artist(obj.title, songs)
        if not artist_id:
            return None
        return web_url(Item({'kind': 'artist', 'id': artist_id}), self._storefront())

    async def _asked_link(self, obj, kind, item_id):
        """link(), or False when the user has been told why there is none: the demo has no
        engine to ask, or the engine's failure was reported."""
        if needs_catalog_artist(obj) and self.app.refuse_in_demo():
            return False
        try:
            return await self.link(obj, kind, item_id)
        except EngineError as error:
            self.app.report(error)
            return False

    def _on_open_in_browser(self, _action, parameter):
        obj, kind, item_id = self._unpack(parameter)
        return self.app.spawn(self._open(obj, kind, item_id))

    async def _open(self, obj, kind, item_id):
        url = await self._asked_link(obj, kind, item_id)
        if url is False:
            return
        if not url:
            self.app.toast(_('This has no page to open'))
            return
        self.launch(url)

    def launch(self, url):
        """Open url in the default browser (Gtk.UriLauncher), a failure toasted."""
        from gi.repository import Gtk

        log.info('opening %s', url)
        Gtk.UriLauncher.new(url).launch(self.window, None, self._on_launched)

    def _on_launched(self, launcher, result):
        try:
            launcher.launch_finish(result)
        except GLib.Error as error:
            log.warning('could not open %s: %s', launcher.get_uri(), error.message)
            self.app.toast(_('Could not open the browser'))

    def _on_copy_link(self, _action, parameter):
        obj, kind, item_id = self._unpack(parameter)
        return self.app.spawn(self._copy(obj, kind, item_id))

    async def _copy(self, obj, kind, item_id):
        """The link on the clipboard, when it is one anyone can open (a library album's or
        artist's catalog page comes from the engine; without it, the album has only its
        owner's)."""
        url = await self._asked_link(obj, kind, item_id)
        if url is False:
            return
        if not is_shareable(url):
            self.app.toast(_('This has no link to copy'))
            return
        self.window.get_clipboard().set(url)
        self.app.toast(_('Link copied'))
