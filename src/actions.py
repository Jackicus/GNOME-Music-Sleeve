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
    actions.drop_new_playlist(refs)        # songs dropped on All Playlists: a new playlist
    actions.queue_drop(refs, next_up=False)   # dropped on the player bar: queued
    actions.move_to_folder(obj, folder_id) # a playlist (or folder) into a folder, at once
    actions.new_folder(parent_id)          # a folder named in a dialog ('root': top level)
    actions.move_in_playlist(playlist, 3, 1)   # its 4th song 2nd (playlist_order.py)
    actions.queue_objects(tracks, later=False)  # a selection's Play Next (or Later)
    actions.remove_entries(playlist, tracks)    # a selection's Remove from Playlist, Undo
    actions.remove_favourites(tracks)           # Favourite Songs' Remove from Favourites, Undo
    actions.ask_remove_from_library(tracks)     # one confirmation, then all of them
    actions.new_playlist_of(tracks)             # New Playlist… holding them
    actions.duplicate(playlist)                 # a copy, "<name> Copy", beside it, shown
    actions.ask_add_songs(playlist)             # Add Songs…: songs picked, added in one write

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

    item-new-playlist    a playlist named in a dialog: holding the song or video of the
                         target (an album's or a playlist's songs, named after it), or in
                         the folder it names ('folder', 'root': the top level)
    item-rename          a playlist's name and description, or a folder's name
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
(Player.move_in_queue: Move Up, Move Down, Alt+Up, Alt+Down, a drop), announced to assistive
technology; item-move-in-playlist, "(ssii)" (playlist id, track
id, the track's index, -1 or 1): Move Up or Move Down, one place in a playlist of the user's
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

The menus are built in code, per kind (build_menu): Play, Play Next, Play Later (none for a
pre-release album's track not out yet: Track.unreleased), Create
Station (a song's or an artist's whose catalog id is known: station_target), and for an Up
Next entry Move Up, Move Down (where it can go in its section) and Remove from Up Next; Go to
Album, Go to Artist (not where the page shown is that album or artist already), View Credits
(a song's whose catalog id is known: credits_target); Favourite or Remove from Favourites,
then Suggest Less or Undo Suggest Less (all four, of which the menu shows those whose actions
are enabled: rating_actions(), by the item's rating; as on Apple's players, a favourite
offers no Suggest Less; an artist whose catalog id is known has Favourite or Remove from
Favourites alone: favourite_items()), Add to Library (not what the
library holds already: a catalog album or playlist by Library.holds(), the test its page's
In Library makes; Pre-Add to Library for an album not out yet: pre_adds()), Add to
Playlist (a song's, a video's, an album's or a playlist's: the
library's playlists that take songs, each folder's in a section headed by its name, a
playlist not offered to itself, then New Playlist…), Move to Folder (a playlist's or
folder's: Top Level, the folders it can go into in one list, then New Folder…:
move_targets(); in neither is a folder a submenu: playlist_submenu()), Remove from
Playlist and, where it can go, Move Up and Move Down (a track shown in a playlist of the
user's: `container`); Open in Browser, Copy Link (only an address anyone can open: not
the web player's library routes; a library artist's is the catalog artist's page, which
the engine finds through their songs); Add Songs… (a playlist of the user's: adds_to()),
Duplicate (a library playlist: duplicates()), Rename… and Delete Playlist… or Delete
Folder… (a playlist of the user's, Item.editable; a folder of theirs),
Remove from Library… (what the library holds: removal_target; a playlist of Apple's, which
cannot be deleted as the user's own are; a catalog album or playlist held, as the library's
own it was found as, Library.held_item()); a folder's menu starts with New Playlist… and New
Folder… (in it); each only where it applies. A category (an Apple curator: a genre's page, a
radio show) has Open in Browser and Copy Link alone (curator_menu): Apple gives a curator
nothing to play or favourite.

Remove from Library takes the item out of the library's models at once (Library.hide), then
asks Apple; a refusal puts it back and is reported. Apple takes a song out of every playlist
too, and an album with its songs; its library listings drop them only seconds later, so the
library keeps leaving them out until a load no longer meets them, and the quick pass of a
sync that follows starts once Apple's read of the item answers 404 (wait_removed).

After a playlist or folder was made, renamed or deleted, the window leaves the pages of what
is gone (Window.leave), the sidebar shows a new name at once, and the library follows Apple's
listing once it shows the change (wait_listed: a new playlist takes seconds to be listed, a
folder made in or moved into a folder about a minute), through the playlists pass of a sync
(sync.py). A track added or removed has its playlist fetched again, then read into
library.json by a playlists pass that reads its tracks
(playlist_order.sync_tracks()); before either, and before a playlist is deleted, its order
still to be written is (PlaylistOrder.flush()).
The menus of the player's queue (the item playing's in the Now Playing sheet and the player
bar, Up Next's) have no Play, which would replace the queue: activating the row plays it.
An item's rating (loved, Suggest Less or neither): a menu shows what the engine said last
this session (its `rated` signal), else whether the library holds it as a favourite
(library.json's favourites, Library.is_favourite), and asks again (engine.rating) as it
opens; an artist's favourite the same way, read by engine.is_favourite_artist. In the demo
an artist's favourite is the session's own (the demo engine remembers it); every other
write says it is not available.

Only Gio, GLib and GObject at import time besides Gtk's UriLauncher, used when a page is
opened: tests build the menus and run the actions with a stand-in window, app and engine.
"""

import asyncio
import logging
from collections import OrderedDict
from gettext import gettext as _
from gettext import ngettext
from urllib.parse import urlsplit

from gi.repository import Gio, GLib, Gtk

from . import related
from .backend import api
from .backend.errors import EngineError
from .backend.api import is_library_id
from .library import (REMOVABLE, ROOT_FOLDER, TRACK_KINDS, TRACK_REF_KINDS, Item, ItemRefs,
                      Track, TreeChange, entries_without, track_ref)
from .playlist_order import PlaylistOrder, refresh_playlist, sync_tracks

log = logging.getLogger(__name__)

TARGET = GLib.VariantType.new('(ss)')
PLAYLIST_TARGET = GLib.VariantType.new('(sss)')
ENTRY_TARGET = GLib.VariantType.new('(ssi)')
QUEUE_ENTRY_TARGET = GLib.VariantType.new('(is)')
QUEUE_MOVE_TARGET = GLib.VariantType.new('(iis)')
MOVE_TARGET = GLib.VariantType.new('(ssii)')

# After a playlist write, how long to wait before each look at Apple's listing, in seconds,
# until it shows the change: a new playlist was listed 4 to 6.5 s after it was made, a
# rename or a deletion within a second (2026-10-03); a playlist moved into a folder or out
# to the top level, and a folder out to the top level, 3 to 6 s after (2026-10-21). Then the
# library follows regardless.
SETTLE_DELAYS = (0.5, 1, 1, 1, 2, 2, 3, 3)
# The same for a folder made in a folder or moved into one: Apple lists it there only about
# a minute later (59 and 61 s, 2026-10-21), having stopped listing a moved one where it was
# within 6 s. So the sync that follows waits for it, up to a minute and a half.
FOLDER_SETTLE_DELAYS = SETTLE_DELAYS + (5,) * 15

# After a removal from the library, how long to wait before each look at Apple's library
# read of the item, in seconds, until it answers 404: a song's did within 2 s, an album's
# within 7 (2026-10-20). Then the library's listings, which dropped them within 2 to 7 s,
# are given LISTING_LAG more before the sync reads them.
REMOVAL_DELAYS = (1, 1, 1, 2, 2, 3, 3, 4)
LISTING_LAG = 2

# How many of the objects menus were built for are remembered for their actions.
REMEMBERED = 64
# The songs one queue command (Play Next, Play Later of several) sends at most.
QUEUE_BATCH = 100
# How many rating writes a selection's Remove from Favourites (and its Undo) has under way
# at once: one write a song, a few side by side.
RATING_WRITES = 4

WEB = 'https://music.apple.com'
# The hosts of Apple Music's pages: the only addresses the app opens or copies.
APPLE_HOSTS = frozenset({'music.apple.com', 'geo.music.apple.com'})
# The page of a catalog item without a URL: music.apple.com/<storefront>/<path>/<id>, which
# Apple redirects to the canonical address with the item's name in it.
WEB_PATHS = {'album': 'album', 'playlist': 'playlist', 'song': 'song', 'station': 'station',
             'artist': 'artist', 'video': 'music-video'}
# The web player's own routes for library items (as its sidebar links and its router name
# them): a library playlist's and a library album's pages, which open for the owner only.
LIBRARY_ROUTES = {'playlist': 'library/playlist', 'album': 'library/albums'}

# Ids the library makes up for what Apple gave none (backend.normalize groups songs into albums
# and artists): nothing of Apple's answers to them.
SYNTHETIC_PREFIXES = ('l.alb_', 'l.art_')

MENU_KINDS = ('album', 'playlist', 'song', 'station', 'artist', 'video', 'folder')
QUEUE_KINDS = ('album', 'playlist')
# The Items whose songs Add to Playlist and a drop on a sidebar playlist add, all of them.
SOURCE_KINDS = ('album', 'playlist')
RATED_KINDS = ('album', 'playlist', 'station', 'video')
LIBRARY_KINDS = ('song', 'album', 'playlist', 'video')

def action_labels():
    """The menu's labels, by action, translated on call (after gettext is set up). Each has
    a mnemonic (GtkPopoverMenu shows them with use-underline), no two the same letter."""
    return {
        'item-play': _('_Play'),
        'item-play-next': _('Play _Next'),
        'item-play-later': _('Play _Later'),
        'item-love': _('_Favourite'),
        'item-unlove': _('_Remove from Favourites'),
        'item-suggest-less': _('_Suggest Less'),
        'item-undo-suggest-less': _('_Undo Suggest Less'),
        'item-add-to-library': _('_Add to Library'),
        'item-add-to-playlist': _('Add to Pla_ylist'),
        'item-go-to-album': _('_Go to Album'),
        'item-go-to-artist': _('Go to Ar_tist'),
        'item-open-in-browser': _('_Open in Browser'),
        'item-copy-link': _('_Copy Link'),
        'item-remove-from-playlist': _('Remo_ve from Playlist'),
        'item-remove-from-queue': _('Remove from Up Ne_xt'),
        'item-new-playlist': _('Ne_w Playlist…'),
        'item-rename': _('Rena_me…'),
        'item-delete': _('_Delete Playlist…'),
        'item-move-to-folder': _('Mov_e to Folder'),
        'item-new-folder': _('New _Folder…'),
        'item-remove-from-library': _('Remove from Li_brary…'),
        'item-create-station': _('Create Stat_ion'),
        'item-move-up': _('_Move Up'),
        'item-move-down': _('Move _Down'),
        'item-view-credits': _('Vi_ew Credits'),
        'item-duplicate': _('Dupl_icate'),
        'item-add-songs': _('Add Son_gs…'),
    }


def pre_adds(obj):
    """Whether Add to Library pre-adds obj: an album not out yet (Item.prerelease, Apple's
    isPrerelease), whose songs come into the library as they come out."""
    return isinstance(obj, Item) and obj.kind == 'album' and obj.prerelease


def pre_add_label():
    """Add to Library's label for an album it pre-adds (pre_adds()); its mnemonic is Add to
    Library's."""
    # Translators: Add to Library for an album not out yet (its songs come as they are
    # released); keep the mnemonic of "_Add to Library".
    return _('Pre-_Add to Library')


def delete_label(kind):
    """Delete's label for a playlist, or for a folder (kind 'folder')."""
    return _('_Delete Folder…') if kind == 'folder' else action_labels()['item-delete']


def _synthetic(item_id):
    return str(item_id or '').startswith(SYNTHETIC_PREFIXES)


def describe(obj):
    """(kind, id) naming obj in an action target: an Item's kind and id, 'song' and a
    Track's id; None for anything else, or anything without an id."""
    if isinstance(obj, Track):
        item_id = obj.id or obj.catalog_id
        return ('song', item_id) if item_id else None
    if isinstance(obj, Item) and obj.kind and obj.id:
        return obj.kind, obj.id
    return None


def _song_id(obj):
    """The id a song is queued and rated by: its catalog id, else its own."""
    return obj.catalog_id or obj.id


def _queue_kind(obj):
    """The MusicKit queue kind a song or music video plays as alone: 'musicVideo' for a
    video (an Item's kind, a Track's by its API type), else 'song'."""
    return 'musicVideo' if obj.kind == 'video' else 'song'


def can_play(obj):
    """Whether obj has something to play: a track, or an album, playlist, song, music video
    or station with a play target, or a catalog artist (its top songs; a library artist's
    id is the library's own invention)."""
    if isinstance(obj, Track):
        return bool(obj.id or obj.catalog_id) and not obj.unreleased
    if not isinstance(obj, Item) or not obj.play.get('kind') or not obj.play.get('id'):
        return False
    if obj.kind == 'artist':
        return not is_library_id(obj.id)
    return obj.kind in ('album', 'playlist', 'song', 'video', 'station')


def queue_target(obj):
    """(kind, id) that Play Next and Play Later queue, or None: a song by its catalog id, a
    music video (an Item, or a Track that is one) by its catalog id as MusicKit's
    'musicVideo', an album or playlist by its play target."""
    if isinstance(obj, Track) and obj.unreleased:
        return None  # a pre-release album's track not out yet: nothing to queue
    if isinstance(obj, Track) or (isinstance(obj, Item) and obj.kind in ('song', 'video')):
        song_id = _song_id(obj)
        return (_queue_kind(obj), song_id) if song_id else None
    if isinstance(obj, Item) and obj.kind in QUEUE_KINDS and not _synthetic(obj.id):
        kind, item_id = obj.play.get('kind'), obj.play.get('id')
        return (kind, item_id) if kind and item_id else None
    return None


def queue_targets(refs):
    """What a drop of `refs` (a library.ItemRefs) on the player bar queues: each object's
    queue_target(), in order (a song by its catalog id, an album or a playlist by its play
    target, as Play Later queues it); None when refs is no ItemRefs, names no objects, or
    names one that cannot be queued (a folder, a song with no id to play by)."""
    objects = refs.objects if isinstance(refs, ItemRefs) else ()
    targets = [queue_target(obj) for obj in objects]
    return targets if targets and None not in targets else None


def queue_commands(targets):
    """The queue commands that queue `targets` ((kind, id) as queue_target() gives them), in
    order: a run of songs one ('songs', 'id,id,…') command of at most QUEUE_BATCH (the
    bridge's queueOptions splits it, as a restored session's queue is set), a song alone
    ('song', id), anything else (a music video, an album, a playlist) its own."""
    commands, run = [], []

    def end_run():
        for start in range(0, len(run), QUEUE_BATCH):
            batch = run[start:start + QUEUE_BATCH]
            commands.append(('song', batch[0]) if len(batch) == 1
                            else ('songs', ','.join(batch)))
        run.clear()

    for kind, item_id in targets:
        if kind == 'song':
            run.append(item_id)
            continue
        end_run()
        commands.append((kind, item_id))
    end_run()
    return commands


def queued_count(commands):
    """How many items queue_commands() `commands` queue."""
    return sum(len(item_id.split(',')) if kind == 'songs' else 1 for kind, item_id in commands)


def queue_message(title, later, count=1):
    """The toast after Play Next or Play Later (`later`) of one item called `title`, or of
    `count` of them."""
    if count > 1:
        if later:
            return ngettext('{count} item will play later', '{count} items will play later',
                            count).format(count=count)
        return ngettext('{count} item will play next', '{count} items will play next',
                        count).format(count=count)
    if later:
        return (_('“{title}” will play later').format(title=title) if title
                else _('Playing later'))
    return _('“{title}” will play next').format(title=title) if title else _('Playing next')


def new_playlist_tracks(refs):
    """What the playlist made from a drop of `refs` on All Playlists holds: the songs and
    music videos, in order, as (kind, id) by their own ids (as Add to Playlist adds them);
    None when refs is no ItemRefs or carries anything else (an album: new_playlist_refs();
    playlists are moved there instead)."""
    if not isinstance(refs, ItemRefs) or not refs.only(*TRACK_REF_KINDS):
        return None
    return [(ref.kind, ref.id) for ref in refs]


def new_playlist_refs(refs):
    """Whether a drop of `refs` on All Playlists makes a new playlist of what it carries:
    songs, music videos and albums alone (an album's songs: ItemActions.tracks_of()), not
    playlists or folders (which are moved to the top level instead)."""
    return isinstance(refs, ItemRefs) and refs.only(*TRACK_REF_KINDS, 'album')


def adds_songs(obj):
    """Whether Add to Playlist adds obj's songs: an album or a playlist Item with an id (a
    folder holds playlists, a station no songs)."""
    return isinstance(obj, Item) and obj.kind in SOURCE_KINDS and bool(obj.id)


def container_tracks(item):
    """The songs and music videos of an album or a playlist Item that Add to Playlist adds,
    in its order (every disc of an album), as (kind, id) by their own ids
    (library.track_ref(): a library song's "i." id, a catalog one's); those without an id
    are left out. None when the Item came without its tracks (no groups: a shelf's, a
    search's), which the engine's item() read then gives."""
    groups = item.groups
    if not groups:
        return None
    tracks = []
    for group in groups:
        entries = group.entries
        for position in range(entries.get_n_items()):
            ref = track_ref(entries.get_item(position))
            if ref is not None:
                tracks.append((ref.kind, ref.id))
    return tracks


def added_message(count, playlist='', new=False):
    """The toast after `count` songs (an album's, a playlist's) were added to the playlist
    named `playlist`, or (`new`) to the new playlist of that name."""
    if new:
        return ngettext('Added {count} song to the new playlist “{playlist}”',
                        'Added {count} songs to the new playlist “{playlist}”',
                        count).format(count=count, playlist=playlist)
    if playlist:
        return ngettext('Added {count} song to “{playlist}”',
                        'Added {count} songs to “{playlist}”',
                        count).format(count=count, playlist=playlist)
    return ngettext('Added {count} song to the playlist', 'Added {count} songs to the playlist',
                    count).format(count=count)


def removed_message(count, playlist='', title=''):
    """The toast after `count` songs (a selection's, or Delete's) were taken out of the
    playlist named `playlist`; one song by its `title`, when it has one."""
    if count == 1 and title and playlist:
        return _('Removed “{title}” from “{playlist}”').format(title=title, playlist=playlist)
    if playlist:
        return ngettext('Removed {count} song from “{playlist}”',
                        'Removed {count} songs from “{playlist}”',
                        count).format(count=count, playlist=playlist)
    return ngettext('Removed {count} song from the playlist',
                    'Removed {count} songs from the playlist', count).format(count=count)


def removals_words(count):
    """(heading, body) of the confirmation before Remove from Library takes out `count`
    songs (a selection's), and the toast once they are gone."""
    heading = ngettext('Remove {count} Song from Library?', 'Remove {count} Songs from Library?',
                       count).format(count=count)
    body = ngettext('The song will be removed from your library and from your playlists on '
                    'all your devices.',
                    'The songs will be removed from your library and from your playlists on '
                    'all your devices.', count)
    return heading, body


def library_removed_message(count):
    """The toast once `count` songs (a selection's) were taken out of the library."""
    return ngettext('Removed {count} song from your library',
                    'Removed {count} songs from your library', count).format(count=count)


def station_target(obj):
    """The id of the station Create Station plays for obj, or None: 'ra.' and the catalog id
    of a song (a Track or a song Item; a library song by the catalog id it carries) or of an
    artist (a catalog artist's own id, or the catalog id a library artist carries:
    related.artist_catalog_id). Apple seeds a station from either by that id (its station
    relationship, kind songSeeded or artistSeeded: src/backend/README.md). A music video, a
    song without a catalog id (an upload) and an artist the library made up have none."""
    if isinstance(obj, Track) or (isinstance(obj, Item) and obj.kind == 'song'):
        if obj.kind == 'video':
            return None
        catalog_id = obj.catalog_id or (obj.id if obj.id and not is_library_id(obj.id)
                                        else None)
    elif isinstance(obj, Item) and obj.kind == 'artist':
        catalog_id = related.artist_catalog_id(obj)
    else:
        return None
    if not catalog_id or is_library_id(catalog_id):
        return None
    return f'ra.{catalog_id}'


def station_items(obj):
    """Create Station for obj, when Apple can seed a station from it (station_target)."""
    named = describe(obj)
    if named is None or station_target(obj) is None:
        return []
    return [menu_item('item-create-station', GLib.Variant('(ss)', named))]


def credits_target(obj):
    """The catalog id of the song whose credits View Credits shows for obj, or None: a Track
    or a song Item that is a song (not a music video), by the catalog id it carries, or its
    own id when that is a catalog one. A song without one (an upload) has none: Apple's
    credits are the catalog's."""
    if not (isinstance(obj, Track) or (isinstance(obj, Item) and obj.kind == 'song')):
        return None
    if obj.kind == 'video':
        return None
    catalog_id = obj.catalog_id or (obj.id if obj.id and not is_library_id(obj.id) else None)
    return str(catalog_id) if catalog_id and not is_library_id(catalog_id) else None


def favourite_target(obj):
    """('artist', catalog id) that an artist's favourite is set and read by
    (Engine.favourite_artist, is_favourite_artist), or None: an artist Item whose catalog
    artist is known (related.artist_catalog_id; not one the library made up from its songs'
    names). An artist's favourite is not a rating (rating_target has none)."""
    if not isinstance(obj, Item) or obj.kind != 'artist':
        return None
    catalog_id = related.artist_catalog_id(obj)
    if not catalog_id or is_library_id(catalog_id):
        return None
    return 'artist', str(catalog_id)


def favourite_items(obj):
    """Favourite and Remove from Favourites for an artist (favourite_target), of which a menu
    shows the one whose action is enabled, as rating_items() does: an artist has no Suggest
    Less here (Apple's is a rating, and an artist's rating path is a 404)."""
    named = describe(obj)
    if named is None or favourite_target(obj) is None:
        return []
    return rating_items(GLib.Variant('(ss)', named), ('item-love', 'item-unlove'))


def rating_target(obj):
    """(kind, id) that love, unlove and rating() take for obj, or None when it has no
    rating: a song by its catalog id (the heart's too), a track that is a music video as a
    video (Track.kind), an album, playlist, station or video by its own id. Not Favourite
    Songs itself, nor an item the library made up."""
    if isinstance(obj, Track):
        song_id = _song_id(obj)
        return (obj.kind or 'song', song_id) if song_id else None
    if isinstance(obj, Item) and obj.kind == 'song':
        song_id = _song_id(obj)
        return ('song', song_id) if song_id else None
    if (isinstance(obj, Item) and obj.kind in RATED_KINDS and obj.id
            and not _synthetic(obj.id) and not obj.favourites):
        return obj.kind, obj.id
    return None


def favourite_places(tracks, playlist, ids):
    """What a selection's Remove from Favourites writes and takes off Favourite Songs: the
    rating targets of `tracks` (rating_target()), each once, in order, and {target: the
    places of its rows in Favourite Songs}, a Track's index where the Track is one of
    `playlist`'s (Favourite Songs, None when the library has none) listed there as `ids`
    (its track ids) says."""
    targets, places = [], {}
    playlist_id = playlist.id if playlist is not None else None
    for track in tracks:
        target = rating_target(track)
        if target is None:
            continue
        if target not in places:
            targets.append(target)
            places[target] = []
        index = getattr(track, 'index', -1)
        if (isinstance(track, Track) and playlist_id and track.play.get('id') == playlist_id
                and 0 <= index < len(ids) and ids[index] == track.id):
            places[target].append(index)
    return targets, places


def library_target(obj):
    """(kind, id) that Add to Library adds, or None: only what is not the library's already
    (a catalog id), a song, album, playlist or video."""
    if isinstance(obj, Track):
        return (obj.kind or 'song', obj.id) if obj.id and not is_library_id(obj.id) else None
    if isinstance(obj, Item) and obj.kind in LIBRARY_KINDS and obj.id and not is_library_id(
            obj.id):
        return obj.kind, obj.id
    return None


def is_removable_playlist(obj):
    """Whether obj is a playlist of Apple's or someone else's in the library, which Remove
    from Library takes out: a library playlist the user cannot edit (not Item.editable) that
    is not Favourite Songs and whose attributes do not say canDelete false. The user's own
    playlists are deleted with Delete Playlist… instead."""
    if not isinstance(obj, Item) or obj.kind != 'playlist' or not is_library_id(obj.id or ''):
        return False
    if obj.favourites or obj.editable or _synthetic(obj.id):
        return False
    attributes = obj.raw.get('attributes')
    return not (isinstance(attributes, dict) and attributes.get(REMOVABLE) is False)


def removal_target(obj, library):
    """(kind, library id) that Remove from Library takes out of the library, or None: a song
    or music video the library holds (a Track, or an Item of the kind; found by its id or its
    catalog id, Library.library_id, so a catalog album's track that is in the library too
    has it), a library album (not one the library made up for loose songs), a playlist of
    Apple's in the library (is_removable_playlist). A catalog album or playlist that the
    library holds is taken out as the library's own it was found as (Library.held_item, the
    test the page's In Library makes)."""
    if library is None:
        return None
    if (isinstance(obj, Item) and obj.kind in ('album', 'playlist')
            and not is_library_id(obj.id or '')):
        obj = library.held_item(obj)
        if obj is None or not is_library_id(obj.id or ''):
            return None
    if isinstance(obj, Track) or (isinstance(obj, Item) and obj.kind in ('song', 'video')):
        kind = 'video' if obj.kind == 'video' else 'song'
        if (isinstance(obj, Track) and kind == 'song' and is_library_id(obj.id or '')
                and obj.play.get('kind') == 'album'
                and library.by_id('album', obj.play.get('id')) is not None):
            return 'song', obj.id  # a track of a library album: a library song
        library_id = library.library_id(kind, obj.id, obj.catalog_id)
        return (kind, library_id) if library_id else None
    if isinstance(obj, Item) and obj.kind == 'album':
        if not is_library_id(obj.id or '') or _synthetic(obj.id):
            return None
        return ('album', obj.id) if library.library_id('album', obj.id) else None
    if is_removable_playlist(obj) and library.library_id('playlist', obj.id):
        return 'playlist', obj.id
    return None


def removal_items(obj, removable):
    """Remove from Library… for obj, when `removable` (its removal_target) says it is in
    the library."""
    named = describe(obj)
    if removable is None or named is None:
        return []
    return [menu_item('item-remove-from-library', GLib.Variant('(ss)', named))]


def removal_words(kind, title):
    """(heading, body) of the confirmation before Remove from Library takes out an item of
    `kind` named `title`: what else goes with it."""
    heading = _('Remove from Library?')
    if kind == 'playlist':
        body = (_('“{title}” will be removed from your library on all your devices.')
                if title else _('The playlist will be removed from your library on all your '
                                'devices.'))
    elif kind == 'album':
        body = (_('“{title}” and its songs will be removed from your library and from your '
                  'playlists on all your devices.') if title
                else _('The album and its songs will be removed from your library and from '
                       'your playlists on all your devices.'))
    else:
        body = (_('“{title}” will be removed from your library and from your playlists on '
                  'all your devices.') if title
                else _('It will be removed from your library and from your playlists on all '
                       'your devices.'))
    return heading, body.format(title=title)


def playlist_track(obj):
    """(kind, id) that Add to Playlist and a drop add, or None: a Track's or a song or music
    video Item's own id (a library "i." id, or a catalog one), as a 'song' or a 'video'
    (library.track_ref()'s rule)."""
    ref = track_ref(obj)
    return (ref.kind, ref.id) if ref is not None else None


def playlist_song(obj):
    """The id Add to Playlist and a drop add (playlist_track), or None."""
    track = playlist_track(obj)
    return track[1] if track is not None else None


def is_folder(obj):
    """Whether obj is a playlist folder Item: one of the user's, or the top level
    (ROOT_FOLDER, All Playlists), each with New Playlist… and New Folder… in its menu."""
    return isinstance(obj, Item) and obj.kind == 'folder' and bool(obj.id)


def is_user_folder(obj):
    """Whether obj is one of the user's playlist folders (not the top level, ROOT_FOLDER):
    one that can be renamed and deleted."""
    return (isinstance(obj, Item) and obj.kind == 'folder' and bool(obj.id)
            and obj.id != ROOT_FOLDER)


def is_manageable(obj):
    """Whether obj can be renamed and deleted: a playlist of the user's (Item.editable: not
    Favourite Songs, nor one of Apple's or someone else's), or a folder of theirs."""
    return (isinstance(obj, Item) and obj.kind == 'playlist' and obj.editable) or (
        is_user_folder(obj))


def entry_target(container, obj):
    """The item-remove-from-playlist target for the Track obj shown in the playlist Item
    `container` (one of the user's): (playlist id, track id, its index), or None."""
    if not isinstance(obj, Track) or not is_manageable(container) or not obj.id:
        return None
    if container.kind != 'playlist':
        return None
    return GLib.Variant('(ssi)', (container.id, obj.id, obj.index))


def move_items(container, obj):
    """Move Up and Move Down for the Track obj shown in the playlist Item `container`, where
    its songs can be reordered (PlaylistOrder.can_reorder()): each only where the track can
    go, not up from the first or down from the last. Their targets are
    item-move-in-playlist's (playlist id, track id, its index, -1 or 1)."""
    if not isinstance(obj, Track) or not obj.id or not PlaylistOrder.can_reorder(container):
        return []
    ids = container.track_ids()
    index = obj.index
    if not 0 <= index < len(ids) or ids[index] != obj.id:
        return []
    items = []
    for step, action in ((-1, 'item-move-up'), (1, 'item-move-down')):
        if 0 <= index + step < len(ids):
            item = Gio.MenuItem.new(action_labels()[action], None)
            item.set_action_and_target_value(
                'win.item-move-in-playlist',
                GLib.Variant('(ssii)', (container.id, obj.id, index, step)))
            items.append(item)
    return items


def queue_move_items(queue_entry, steps):
    """Move Up and Move Down for the Up Next entry `queue_entry` ((index, id)), each where
    it is one of `steps` (-1, 1: the entry's context_queue_moves). Their targets are
    item-move-in-queue's (index, the index to move it to, id)."""
    if queue_entry is None:
        return []
    index, entry_id = int(queue_entry[0]), str(queue_entry[1])
    items = []
    for step, action in ((-1, 'item-move-up'), (1, 'item-move-down')):
        if step in steps:
            item = Gio.MenuItem.new(action_labels()[action], None)
            item.set_action_and_target_value(
                'win.item-move-in-queue', GLib.Variant('(iis)', (index, index + step, entry_id)))
            items.append(item)
    return items


def adds_to(obj):
    """Whether Add Songs… applies to obj: a playlist of the user's (Item.editable: not
    Favourite Songs, nor one of Apple's), whose songs are picked in a dialog
    (dialogs/add_songs.py)."""
    return isinstance(obj, Item) and obj.kind == 'playlist' and obj.editable


def duplicates(obj):
    """Whether Duplicate applies to obj: a playlist of the library's (the user's, Favourite
    Songs, one of Apple's added), copied into a new playlist of the user's. A catalog
    playlist is added to the library instead."""
    return (isinstance(obj, Item) and obj.kind == 'playlist' and bool(obj.id)
            and is_library_id(obj.id))


def duplicate_name(name):
    """The name of a playlist's copy (Duplicate), as GNOME's Files names a copy."""
    # Translators: the name Duplicate gives a copy of a playlist: {name} is its name
    # ("Road Trip Copy").
    return _('{name} Copy').format(name=name) if name else _('Untitled Playlist Copy')


def manage_items(obj):
    """Add Songs… (a playlist of the user's), Duplicate (a library playlist), then Rename…
    and Delete Playlist… (or Delete Folder…) for obj, when it is manageable."""
    target = GLib.Variant('(ss)', (obj.kind, obj.id)) if describe(obj) is not None else None
    items = []
    if adds_to(obj):
        items.append(menu_item('item-add-songs', target))
    if duplicates(obj):
        items.append(menu_item('item-duplicate', target))
    if is_manageable(obj):
        items += [menu_item('item-rename', target),
                  menu_item('item-delete', target, label=delete_label(obj.kind))]
    return items


def is_apple_music_url(url):
    """Whether url is a page of music.apple.com over https: the only addresses the app
    opens or copies. An Item's `url` comes from Apple's answers, but is checked all the
    same; anything else falls back to the address made from the item's id."""
    try:
        parts = urlsplit(url or '')
    except ValueError:
        return False
    return parts.scheme == 'https' and (parts.hostname or '').lower() in APPLE_HOSTS


def is_shareable(url):
    """Whether an address opens for anyone: a music.apple.com page that is not one of the
    web player's library routes (those open only for the account signed in)."""
    return is_apple_music_url(url) and not url.startswith(f'{WEB}/library/')


def web_url(obj, storefront=None):
    """The music.apple.com page of obj, or None: the Item's own URL (when it is one of
    Apple's, is_apple_music_url); the web player's page of a library playlist or album; a
    catalog item's page by its id; a track's song page by its catalog id."""
    storefront = storefront or 'us'
    if isinstance(obj, Track):
        song_id = obj.catalog_id or (obj.id if not is_library_id(obj.id) else None)
        path = WEB_PATHS[obj.kind or 'song']
        return f'{WEB}/{storefront}/{path}/{song_id}' if song_id else None
    if not isinstance(obj, Item) or not obj.id:
        return None
    if obj.url and is_apple_music_url(obj.url):
        return obj.url
    if is_library_id(obj.id):
        route = LIBRARY_ROUTES.get(obj.kind)
        if route and not _synthetic(obj.id):
            return f'{WEB}/{route}/{obj.id}'
        if obj.kind == 'song' and obj.catalog_id:
            return f'{WEB}/{storefront}/song/{obj.catalog_id}'
        return None
    path = WEB_PATHS.get(obj.kind)
    return f'{WEB}/{storefront}/{path}/{obj.id}' if path else None


def share_url(obj, storefront=None):
    """The address Copy Link copies, or None: obj's page when anyone can open it
    (is_shareable), never a library route."""
    url = web_url(obj, storefront)
    return url if is_shareable(url) else None


def drag_link(obj, storefront=None):
    """The address a drag of obj offers other applications, or None: share_url(), or for a
    library album without one its catalog page by the album's catalog id (Copy Link asks the
    engine instead, which a drag, answered at once, cannot wait for). A library-only item (an
    upload, a playlist of the user's, a folder) has none."""
    url = share_url(obj, storefront)
    if url is None and needs_catalog_url(obj) and str(obj.catalog_id or '').isdigit():
        url = f'{WEB}/{storefront or "us"}/{WEB_PATHS["album"]}/{obj.catalog_id}'
    return url


def drag_links(objects, storefront=None):
    """The addresses a drag of `objects` (Tracks and Items, in order) offers other
    applications: each one's drag_link(), in order, once each, those without one left out."""
    return list(dict.fromkeys(url for url in (drag_link(obj, storefront) for obj in objects)
                              if url))


def needs_catalog_url(obj):
    """Whether obj's link is better asked of the engine: a library album (real, not made up)
    has a catalog page others can open, where its library route opens only for the owner."""
    return (isinstance(obj, Item) and obj.kind == 'album' and not obj.url
            and is_library_id(obj.id) and not _synthetic(obj.id))


def needs_catalog_artist(obj):
    """Whether obj's page is found through the engine: an artist the library made up from
    its songs' names (no catalog id, no URL), whose catalog artist the engine finds through
    those songs (Engine.catalog_artist, related.artist_song_ids)."""
    return (isinstance(obj, Item) and obj.kind == 'artist' and not obj.url
            and related.artist_catalog_id(obj) is None)


def menu_item(action, target, label=None):
    """A Gio.MenuItem running win.<action> with target, labelled as action_labels() says."""
    item = Gio.MenuItem.new(label or action_labels()[action], None)
    item.set_action_and_target_value(f'win.{action}', target)
    return item


RATING_ACTIONS = ('item-love', 'item-unlove', 'item-suggest-less', 'item-undo-suggest-less')


def rating_actions(value):
    """Which of RATING_ACTIONS are enabled (and so shown) for an item rated `value` (1
    loved, -1 Suggest Less, 0 neither): Favourite or Remove from Favourites, and Suggest Less
    or Undo Suggest Less, but no Suggest Less beside a favourite, as Apple's players have it.
    Favourite replaces a Suggest Less (one rating an item)."""
    return {
        'item-love': value != 1,
        'item-unlove': value == 1,
        'item-suggest-less': value == 0,
        'item-undo-suggest-less': value == -1,
    }


def rating_items(target, actions=RATING_ACTIONS):
    """The rating's items (RATING_ACTIONS, or those of `actions`), of which a menu shows
    those whose actions are enabled (GMenu's hidden-when): ItemActions keeps the actions'
    state as the item's rating (rating_actions()), so the menu follows an answer without its
    items being replaced."""
    items = []
    for action in actions:
        item = menu_item(action, target)
        item.set_attribute_value('hidden-when', GLib.Variant('s', 'action-disabled'))
        items.append(item)
    return items


def mnemonic_escaped(title):
    """A name of the user's as a menu label: its underscores doubled, since the label's
    underscores are mnemonics."""
    return title.replace('_', '__')


def folder_path(titles):
    """A folder's name as a menu shows it, `titles` the names of the folders holding it and
    its own, outermost first: "Evenings › Late Night" for a folder inside another, Untitled
    Folder for one without a name."""
    names = [title or _('Untitled Folder') for title in titles]
    path = names[0]
    for name in names[1:]:
        # Translators: a folder inside another, as Add to Playlist and Move to Folder name
        # it: "Evenings › Late Night".
        path = _('{outer} › {inner}').format(outer=path, inner=name)
    return path


def playlist_submenu(entries, named, action=None):
    """The Add to Playlist items for `entries` ((id, title, children), as
    ItemActions.playlists() lists them), adding the song or video `named` ((kind, id)), or
    an album's or a playlist's songs, to the playlist chosen: the top level's playlists,
    then each folder's in a section headed by its name (folder_path()), a folder inside
    another after that one's own playlists. No folder is a submenu: a Gtk.PopoverMenu names
    a submenu's page by its label, and two of one name (a folder in Move to Folder too, two
    Untitled Folders) would open one page (docs/decisions.md). A playlist is not offered its
    own songs (nor a folder holding only it). With `action` (a full action name that takes
    the playlist's id, "s": a selection's Add to Playlist), each item runs that instead;
    `named` is then only what is not offered (('playlist', id), or None)."""
    menu = Gio.Menu()

    def item_for(entry_id, title):
        label = mnemonic_escaped(title or _('Untitled Playlist'))
        if action is None:
            return menu_item('item-add-to-playlist',
                             GLib.Variant('(sss)', (entry_id, *named)), label=label)
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(action, GLib.Variant('s', entry_id))
        return item

    def add(entries, path):
        section = Gio.Menu()
        folders = []
        for entry_id, title, children in entries:
            if children is not None:
                folders.append((children, (*path, title)))
            elif named is None or tuple(named) != ('playlist', entry_id):
                section.append_item(item_for(entry_id, title))
        if section.get_n_items():
            # A section's header is plain text, not a mnemonic label: the name as it is.
            menu.append_section(folder_path(path) if path else None, section)
        for children, inside in folders:
            add(children, inside)

    add(entries, ())
    return menu


def settle_delays(kind, folder_id):
    """How long to look for a playlist or folder (`kind`) made in or moved into the folder
    folder_id (ROOT_FOLDER: the top level) in Apple's listing: FOLDER_SETTLE_DELAYS for a
    folder into a folder, which Apple lists there only about a minute later, else
    SETTLE_DELAYS."""
    if kind == 'folder' and folder_id not in (None, '', ROOT_FOLDER):
        return FOLDER_SETTLE_DELAYS
    return SETTLE_DELAYS


def move_targets(tree, obj):
    """Where obj, a playlist or folder of the library.PlaylistTree `tree`, can be moved, for
    Move to Folder: (top_level, entries), `top_level` whether it can go to the top level and
    `entries` the folders as (id, title, movable, children), in the sidebar's order:
    `movable` whether obj can go into that folder (not the one it is in), `children` the
    entries of the folders inside it. obj itself, and so whatever is inside it, is left out,
    as is a folder that is neither a target nor holds one. None when obj cannot be moved at
    all: not in the tree, Favourite Songs, the top level itself, or a kind of move Apple is
    not known to take (api.can_move_to_folder: a folder, were MOVE_FOLDERS switched off)."""
    if not isinstance(obj, Item) or obj.kind not in ('playlist', 'folder') or tree is None:
        return None
    node = tree.node(obj.kind, obj.id)
    if node is None or node is tree.root or node.item.favourites:
        return None
    if obj.kind == 'folder' and not api.MOVE_FOLDERS:
        return None

    def entries(folder):
        found = []
        for child in folder.children:
            if child.kind != 'folder' or child is node:
                continue
            inside = entries(child)
            movable = (tree.can_move(obj.kind, obj.id, child.id)
                       and api.can_move_to_folder(obj.kind, child.id))
            if movable or inside:
                found.append((child.id, child.item.title, movable, inside))
        return found

    top_level = (tree.can_move(obj.kind, obj.id, ROOT_FOLDER)
                 and api.can_move_to_folder(obj.kind, ROOT_FOLDER))
    return top_level, entries(tree.root)


def folder_items(entries, named, path=(), menu=None):
    """The Move to Folder items for `entries` (move_targets()'s), moving the playlist or
    folder `named` ((kind, id)), in one list in the sidebar's order: each folder it can go
    into, one inside another named with the folders holding it (folder_path()). No folder
    is a submenu, as in Add to Playlist (playlist_submenu())."""
    menu = Gio.Menu() if menu is None else menu
    for folder_id, title, movable, children in entries:
        inside = (*path, title)
        if movable:
            menu.append_item(menu_item('item-move-to-folder',
                                       GLib.Variant('(sss)', (folder_id, *named)),
                                       label=mnemonic_escaped(folder_path(inside))))
        folder_items(children, named, inside, menu)
    return menu


def move_submenu(moves, named):
    """Move to Folder's submenu for the playlist or folder `named` ((kind, id)), from
    move_targets()'s `moves`: Top Level (when it can go there), the folders
    (folder_items()), then New Folder…, a folder holding it. Never empty."""
    top_level, entries = moves
    submenu = Gio.Menu()
    if top_level:
        top = Gio.Menu()
        top.append_item(menu_item('item-move-to-folder',
                                  GLib.Variant('(sss)', (ROOT_FOLDER, *named)),
                                  label=_('_Top Level')))
        submenu.append_section(None, top)
    listed = folder_items(entries, named)
    if listed.get_n_items():
        submenu.append_section(None, listed)
    created = Gio.Menu()
    created.append_item(menu_item('item-move-to-folder', GLib.Variant('(sss)', ('', *named)),
                                  label=action_labels()['item-new-folder']))
    submenu.append_section(None, created)
    return submenu


def new_items(folder_id):
    """New Playlist… and New Folder…, both in the folder folder_id (ROOT_FOLDER: the top
    level)."""
    target = GLib.Variant('(ss)', ('folder', folder_id))
    return [menu_item('item-new-playlist', target), menu_item('item-new-folder', target)]


def main_menu_section():
    """The main menu's first section: New Playlist… (win.new-playlist, which the menu shows
    with its key, Ctrl+N) and New Folder…, both at the top level."""
    section = Gio.Menu()
    section.append_item(Gio.MenuItem.new(action_labels()['item-new-playlist'],
                                         'win.new-playlist'))
    section.append_item(new_items(ROOT_FOLDER)[1])
    return section


def build_menu(obj, playlists=(), storefront=None, here=None, queued=False, container=None,
               moves=None, removable=None, queue_entry=None, reorder=True, held=False,
               queue_moves=()):
    """The menu for obj (an Item or a Track), or None when nothing applies; a category's is
    curator_menu(). It is the one menu of an item wherever it shows: a tile's or row's, a
    page's More Options, a sidebar row's (a folder's, All Playlists' too: New Playlist… and
    New Folder… in it). `playlists` are the entries the Add to
    Playlist submenu lists (ItemActions.playlists(): (id, title, children), a folder's
    children its own entries, a section); `here` is the Item of the page shown (Go to Album
    and Go to Artist are left out where they would go nowhere: related.shows); `queued`, obj
    is in the player's queue (no Play); `container`, the playlist Item the track obj is
    shown in (Remove from Playlist, when it is one of the user's); `moves`, where a playlist
    or folder can be moved (move_targets(): Move to Folder; None, not at all); `removable`,
    obj's removal_target (Remove from Library…, and no Add to Library); `queue_entry`,
    (index, id) of the queue's entry obj is when it may be taken out of Up Next (Remove from
    Up Next) and `queue_moves` the steps it can take there (-1: Move Up, 1: Move Down, as
    item-move-in-queue moves it); `reorder` false leaves out a playlist's Move Up and Move
    Down (the playlist's page shows a
    filter of its songs); `held`, the library holds obj, a catalog album or playlist
    (Library.holds(), as its page's In Library says: no Add to Library)."""
    if is_curator(obj):
        return curator_menu(obj, storefront)
    named = describe(obj)
    if named is None or (isinstance(obj, Item) and obj.kind not in MENU_KINDS):
        return None
    target = GLib.Variant('(ss)', named)
    sections = [Gio.Menu(), Gio.Menu(), Gio.Menu(), Gio.Menu(), Gio.Menu()]
    play, go, keep, share, manage = sections
    if is_folder(obj):
        for item in new_items(obj.id):
            play.append_item(item)
    if can_play(obj) and not queued:
        play.append_item(menu_item('item-play', target))
    if queue_target(obj) is not None:
        play.append_item(menu_item('item-play-next', target))
        play.append_item(menu_item('item-play-later', target))
    for item in station_items(obj):
        play.append_item(item)
    for item in queue_move_items(queue_entry, queue_moves):
        play.append_item(item)
    if queue_entry is not None:
        play.append_item(menu_item('item-remove-from-queue',
                                   GLib.Variant('(is)', (int(queue_entry[0]),
                                                         str(queue_entry[1])))))
    if related.has_album(obj) and not related.shows(here, obj, 'album'):
        go.append_item(menu_item('item-go-to-album', target))
    if related.has_artist(obj) and not related.shows(here, obj, 'artist'):
        go.append_item(menu_item('item-go-to-artist', target))
    if credits_target(obj) is not None:
        go.append_item(menu_item('item-view-credits', target))
    if rating_target(obj) is not None:
        for item in rating_items(target):
            keep.append_item(item)
    for item in favourite_items(obj):
        keep.append_item(item)
    if library_target(obj) is not None and removable is None and not held:
        keep.append_item(menu_item('item-add-to-library', target,
                                   pre_add_label() if pre_adds(obj) else None))
    if playlist_song(obj) or adds_songs(obj):
        # The playlists that take songs, folders as sections, then New Playlist…, one
        # holding this song (an album's or a playlist's songs).
        submenu = Gio.Menu()
        listed = playlist_submenu(playlists, named)
        if listed.get_n_items():
            submenu.append_section(None, listed)
        created = Gio.Menu()
        created.append_item(menu_item('item-new-playlist', target))
        submenu.append_section(None, created)
        keep.append_submenu(action_labels()['item-add-to-playlist'], submenu)
    if moves is not None:
        keep.append_submenu(action_labels()['item-move-to-folder'], move_submenu(moves, named))
    for item in move_items(container, obj) if reorder else ():
        keep.append_item(item)
    removed = entry_target(container, obj)
    if removed is not None:
        keep.append_item(menu_item('item-remove-from-playlist', removed))
    if web_url(obj, storefront) or needs_catalog_artist(obj):
        share.append_item(menu_item('item-open-in-browser', target))
        # Copy Link: an address anyone can open, or a library album's or artist's catalog
        # page, which the engine can say when the link is asked for.
        if share_url(obj, storefront) or needs_catalog_url(obj) or needs_catalog_artist(obj):
            share.append_item(menu_item('item-copy-link', target))
    for item in manage_items(obj):
        manage.append_item(item)
    for item in removal_items(obj, removable):
        manage.append_item(item)
    menu = Gio.Menu()
    for section in sections:
        if section.get_n_items():
            menu.append_section(None, section)
    return menu if menu.get_n_items() else None


def is_curator(obj):
    """Whether obj is an Apple curator's tile (kind 'category': a genre's page, a radio
    show), which opens its page: Apple gives a curator no playParams, so nothing plays it,
    queues it or favourites it."""
    return isinstance(obj, Item) and obj.kind == 'category' and bool(obj.id)


def curator_menu(obj, storefront=None):
    """A curator's menu: Open in Browser and Copy Link (its music.apple.com page, the
    curator's own `url`: web_url), or None when it has no page."""
    named = describe(obj)
    if named is None or not web_url(obj, storefront):
        return None
    target = GLib.Variant('(ss)', named)
    share = Gio.Menu()
    share.append_item(menu_item('item-open-in-browser', target))
    if share_url(obj, storefront):
        share.append_item(menu_item('item-copy-link', target))
    menu = Gio.Menu()
    menu.append_section(None, share)
    return menu


def queue_move_message(title, index, queue_index, count):
    """What assistive technology is told as an Up Next entry moves: its title, and its place
    among the entries after the one playing (at `queue_index`, of `count` in the queue)."""
    # Translators: said to screen reader users as a song is moved in Up Next: “Harbour
    # Lights” moved to position 2 of 9 in Up Next (1 plays next).
    return _('“{title}” moved to position {position} of {count} in Up Next').format(
        title=title or _('Unknown Title'), position=index - queue_index,
        count=count - queue_index - 1)


def now_playing_track(now_playing):
    """An entry of the player's queue (a player.NowPlaying: the item playing, an Up Next
    row's) as a Track a menu is built for, or None for what has no menu (a station's segment,
    an ad: NowPlaying.kind ''). Its `type` is an API type of its kind (MusicKit names its own
    items 'song'), so it is rated, added and opened as what it is; it has no group to play."""
    if now_playing is None or now_playing.kind not in ('song', 'video'):
        return None
    raw = getattr(now_playing, 'raw', None)
    data = dict(raw) if isinstance(raw, dict) else {}
    data.update(id=now_playing.id, catalogId=now_playing.catalog_id or None,
                title=now_playing.title, artist=now_playing.artist, album=now_playing.album)
    if TRACK_KINDS.get(data.get('type')) != now_playing.kind:
        data['type'] = 'music-videos' if now_playing.kind == 'video' else 'songs'
    track = Track(data)
    return track if track.id or track.catalog_id else None


def not_found_message(kind):
    """The toast when Go to Album (`kind` 'album') or Go to Artist finds nothing."""
    return _('Could not find the album') if kind == 'album' else _('Could not find the artist')


def love_messages(kind):
    """(loved, unloved) toasts for an item of kind: a song goes into Favourite Songs."""
    if kind == 'song':
        return _('Added to Favourite Songs'), _('Removed from Favourite Songs')
    return _('Added to Favourites'), _('Removed from Favourites')


def unfavourited_messages(count):
    """(removed, put back) toasts after a selection's Remove from Favourites took `count`
    songs out of Favourite Songs, and after its Undo put them back."""
    return (ngettext('Removed {count} song from Favourite Songs',
                     'Removed {count} songs from Favourite Songs', count).format(count=count),
            ngettext('Put back {count} song in Favourite Songs',
                     'Put back {count} songs in Favourite Songs', count).format(count=count))


def suggest_less_messages():
    """(set, undone) toasts for Suggest Less and Undo Suggest Less."""
    return _('Apple Music will suggest less like this'), _('Suggest Less undone')


class ItemActions:
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

    def menu_for(self, obj, queued=False, queue_entry=None, queue_moves=()):
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
        """Whether a menu offers Move Up and Move Down for the Track obj: not while the page
        shown lists its playlist filtered (DetailPage.can_reorder()), where the order shown
        is not the playlist's."""
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
                self.window.open_artist_page(item)
            else:
                self.window.open_item(item)
        if then is not None:
            then()

    def show_artist(self, obj):
        """A link's artist (a row's, an album page's): what the library holds of the artist
        obj is by when the library has them (related.library_artist, window.open_item), else
        where Go to Artist goes."""
        found = related.library_artist(self.library, obj)
        if found is not None:
            self.window.open_item(found)
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
        for obj in objects:
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
                title=track.title, position=to_index + 1, count=len(ids)),
                Gtk.AccessibleAnnouncementPriority.MEDIUM)
        return True

    def _on_move_in_playlist(self, _action, parameter):
        playlist_id, track_id, index, step = parameter.unpack()
        playlist = self.library.by_id('playlist', playlist_id)
        ids = playlist.track_ids() if playlist is not None else None
        if not ids or not 0 <= index < len(ids) or ids[index] != track_id:
            return False  # the list changed since the menu was made
        return self.move_in_playlist(playlist, index, index + step)

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

    def can_move_refs(self, refs, folder_id):
        """Whether the playlists and folders a drag carries (an ItemRefs of nothing else)
        may all go into the folder folder_id (ROOT_FOLDER: the top level): the tree takes
        each move (PlaylistTree.can_move: not into itself, a folder inside it, or where it
        is already) and Apple is known to take it (api.can_move_to_folder)."""
        if not isinstance(refs, ItemRefs) or not refs.only('playlist', 'folder'):
            return False
        tree = self.library.playlist_tree()
        for ref in refs:
            node = tree.node(ref.kind, ref.id)
            if (node is None or node.item.favourites or not api.can_move_to_folder(
                    ref.kind, folder_id) or not tree.can_move(ref.kind, ref.id, folder_id)):
                return False
        return True

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

    def queue_objects(self, objects, later=False):
        """Play Next (or, `later`, Play Later) of several songs and music videos, a
        selection's in the order shown: their queue targets as queue_commands() (a run of
        songs one command), one toast that counts them. The task, or None when none can be
        queued."""
        targets = [target for target in map(queue_target, objects) if target is not None]
        if not targets:
            self.app.toast(_('This cannot be queued'))
            return None
        commands = queue_commands(targets)
        title = objects[0].title if len(objects) == 1 else ''
        message = queue_message(title, later, queued_count(commands))
        return self._run(self._send_queue, (commands, later), message, ensure=False)

    def new_playlist_of(self, objects):
        """New Playlist… for a selection: a playlist named in a dialog holding the songs and
        music videos `objects` in their order (create_playlist(objects=…)), shown once made.
        The dialog."""
        objects = list(objects)
        return self.ask_name(
            _('New Playlist'), _('_Create'), '', '',
            lambda name, description: self.create_playlist(name, description, objects=objects,
                                                           show=True))

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
                               count).format(count=count, playlist=name)
        else:
            message = ngettext('Put back {count} song', 'Put back {count} songs',
                               count).format(count=count)
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

    def removals(self, objects):
        """What a selection's Remove from Library takes: (obj, removal_target) for each of
        `objects` the library holds, in order, each library item once."""
        found, seen = [], set()
        for obj in objects:
            target = self.removal_target(obj)
            if target is not None and target not in seen:
                seen.add(target)
                found.append((obj, target))
        return found

    def ask_remove_from_library(self, objects):
        """A selection's Remove from Library…: of `objects`, those the library holds
        (removals()) taken out once one dialog confirms (removal_words() for one,
        removals_words() for several). The dialog, or None when none is in the library."""
        found = self.removals(objects)
        if not found:
            self.app.toast(_('These are not in your library'))
            return None
        if len(found) == 1:
            obj, target = found[0]
            heading, body = removal_words(target[0], obj.title or '')
            return self.ask_confirm(heading, body, _('_Remove'),
                                    lambda: self.remove_from_library(obj, target))
        heading, body = removals_words(len(found))
        return self.ask_confirm(heading, body, _('_Remove'),
                                lambda: self.remove_all_from_library(found))

    def remove_all_from_library(self, found):
        """Take several items out of the library (`found`, removals()' pairs): the library
        leaves them all out at once (Library.hide), Apple is asked for each in turn, and one
        toast counts those it took; a failure brings back the rest (Library.unhide) and is
        reported. The pages of what went are left, and once Apple's read of the last no
        longer has it, one quick sync reads the songs and the playlists that held any of
        them (_follow_removal's, once for all). The task, whose result says whether all
        went, or None (the demo library)."""
        if self.app.refuse_in_demo():
            return None
        parts = [(target, *self._removal_refs(obj, *target)) for obj, target in found]

        async def run():
            self.app.spawn(self.library.hide(set().union(*(part[1] for part in parts))))
            done = 0
            try:
                await self.app.player.ensure_engine()
                for (kind, library_id), *_refs in parts:
                    await self.engine.remove_from_library(kind, library_id)
                    done += 1
            except EngineError as error:
                self.app.spawn(self.library.unhide(set().union(
                    *(part[1] for part in parts[done:]))))
                self.app.report(error)
            if not done:
                return False
            removed = parts[:done]
            self.app.toast(library_removed_message(done))
            gone = set().union(*(part[3] for part in removed))
            if gone:
                self.window.leave(gone)
            kind, library_id = removed[-1][0]
            if await self.wait_removed(kind, library_id):
                await asyncio.sleep(LISTING_LAG)
            holding = set().union(*(set(part[2]) for part in removed))
            task = self.app.start_sync(quick=True,
                                       videos=any(part[0][0] == 'video' for part in removed),
                                       tracks_of=tuple(sorted(holding)))
            if task is not None:
                await asyncio.wait([task])
            return done == len(parts)

        return self.app.spawn(run())

    def drop_new_playlist(self, refs):
        """Songs, music videos or albums (a library.ItemRefs of nothing else) dropped on
        All Playlists: New Playlist's dialog, the name filled in with the first one's title,
        makes a playlist holding them all, an album's songs (create_playlist()), whose page
        is then shown. False when the drop is refused (new_playlist_refs())."""
        if not new_playlist_refs(refs):
            return False
        name = refs.refs[0].title
        tracks = new_playlist_tracks(refs)
        if tracks:
            title, objects = (name if len(tracks) == 1 else ''), None
        else:
            title, objects = '', self._ref_objects(refs)
        self.ask_name(
            _('New Playlist'), _('_Create'), name, '',
            lambda name, description: self.create_playlist(name, description, tracks or (),
                                                           None, title, show=True,
                                                           objects=objects))
        return True

    def drop_into_folder(self, folder_id, refs):
        """An ItemRefs of playlists or folders dropped on a sidebar folder (ROOT_FOLDER:
        All Playlists, the top level): each moved there (move_to_folder()). False when the
        drop is refused (can_move_refs())."""
        if not self.can_move_refs(refs, folder_id):
            return False
        tree = self.library.playlist_tree()
        for ref in refs:
            self.move_to_folder(tree.node(ref.kind, ref.id).item, folder_id)
        return True

    # -- managing playlists and folders ------------------------------------------------------

    def ask_name(self, heading, confirm, name='', description=None, done=None):
        """The name dialog over the window (dialogs/playlist.py's NameDialog): `name` and
        `description` filled in (None: no description to edit); done(name, description) when
        it is confirmed. The dialog."""
        from .dialogs.playlist import NameDialog

        dialog = NameDialog(heading, confirm, name, description, done)
        dialog.present(self.window)
        return dialog

    def ask_confirm(self, heading, body, confirm, done):
        """The confirmation before something is deleted, over the window
        (dialogs/playlist.py's confirm()): done() when it is confirmed. The dialog."""
        from .dialogs.playlist import confirm as confirm_dialog

        return confirm_dialog(self.window, heading, body, confirm, done)

    def _on_new_playlist(self, _action, parameter):
        """A new playlist, named in a dialog: in the folder the target names, or holding the
        song or video it names, or the songs of the album or playlist it names (the name
        filled in with its title)."""
        obj, kind, item_id = self._unpack(parameter)
        if kind in SOURCE_KINDS:
            source = self._source(obj, kind, item_id)
            return self.ask_name(
                _('New Playlist'), _('_Create'), str(source.raw.get('title') or ''), '',
                lambda name, description: self.create_playlist(name, description,
                                                               objects=[source]))
        if kind == 'folder':
            tracks, folder_id, title = (), item_id, ''
        else:
            track = playlist_track(obj) if obj is not None else None
            tracks = (track or (kind, item_id),)
            folder_id, title = None, obj.title if obj is not None else ''
        return self.ask_name(
            _('New Playlist'), _('_Create'), '', '',
            lambda name, description: self.create_playlist(name, description, tracks,
                                                           folder_id, title))

    def create_playlist(self, name, description='', tracks=(), folder_id=None, title='',
                        show=False, objects=None):
        """Make the playlist (Engine.create_playlist), confirm with a toast and follow Apple's
        listing; one made empty (New Playlist), or with `show`, is then shown. `objects`:
        albums, playlists or tracks whose songs it holds in place of `tracks`
        (tracks_of()), counted in the toast; with none to add no playlist is made. The
        task, or None."""
        if self.app.refuse_in_demo():
            return None
        if title:
            message = _('Added “{title}” to the new playlist “{playlist}”').format(
                title=title, playlist=name)
        else:
            message = _('Created “{playlist}”').format(playlist=name)

        async def run():
            nonlocal tracks, message
            try:
                await self.app.player.ensure_engine()
                if objects is not None:
                    tracks = await self.tracks_of(objects)
                    if not tracks:
                        self.app.toast(_('There are no songs to add'))
                        return
                    message = added_message(len(tracks), name, new=True)
                new_id = await self.engine.create_playlist(name, description, tracks,
                                                           folder_id)
            except EngineError as error:
                self.app.report(error)
                return
            self.app.toast(message)
            await self._follow_listing(folder_id or ROOT_FOLDER, new_id, name)
            if (show or not tracks) and self.library.by_id('playlist', new_id) is not None:
                self.window.select_page(f'playlist:{new_id}')  # sidebar.playlist_key

        return self.app.spawn(run())

    def _on_duplicate(self, _action, parameter):
        return self.duplicate(self._unpack(parameter)[0])

    def duplicate(self, playlist):
        """Duplicate: a new playlist of the user's named duplicate_name(), with the
        playlist's description and its songs in its own order (whatever order its page
        shows: a sort is the view's), beside it (in its folder), its page shown once Apple
        lists it (create_playlist()). An empty playlist's copy is made empty. The task, or
        None."""
        if not duplicates(playlist):
            self.app.toast(_('This cannot be duplicated'))
            return None
        name = duplicate_name(playlist.title or '')
        folder_id = self._parent_of(playlist)
        description = playlist.summary or ''
        if playlist.groups and not container_tracks(playlist):
            return self.create_playlist(name, description, (), folder_id, show=True)
        return self.create_playlist(name, description, folder_id=folder_id, show=True,
                                    objects=[playlist])

    def _on_add_songs(self, _action, parameter):
        return self.ask_add_songs(self._unpack(parameter)[0])

    def ask_add_songs(self, playlist):
        """Add Songs…: the dialog (dialogs/add_songs.py) that picks songs from the library
        and Apple Music's catalogue for a playlist of the user's, added in one write once
        chosen (add_items_to_playlist(): one POST of up to api.PLAYLIST_BATCH). The dialog, or
        None."""
        if not adds_to(playlist):
            self.app.toast(_('Songs cannot be added to this playlist'))
            return None
        from .dialogs.add_songs import AddSongsDialog

        playlist_id = playlist.id
        dialog = AddSongsDialog(self.app, self.library, playlist.title or '', lambda objects:
                                self.add_items_to_playlist(playlist_id, objects))
        dialog.present(self.window)
        return dialog

    def _on_rename(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        if not is_manageable(obj):
            self.app.toast(_('This cannot be renamed'))
            return None
        if obj.kind == 'folder':
            return self.ask_name(_('Rename Folder'), _('_Rename'), obj.title, None,
                                 lambda name, _description: self.rename(obj, name))
        return self.ask_name(_('Rename Playlist'), _('_Rename'), obj.title, obj.summary or '',
                             lambda name, description: self.rename(obj, name, description))

    def rename(self, obj, name, description=None):
        """Give a playlist of the user's its name (and its description, unless None), or a
        folder its name: the Item and the sidebar follow at once, the library once Apple
        lists it. The task, or None."""
        if obj.kind == 'folder':
            method, args = self.engine.rename_folder, (obj.id, name)
        else:
            method, args = self.engine.edit_playlist, (obj.id, name, description)
        parent = self._parent_of(obj)

        async def after():
            changes = {'title': name}
            if description is not None:
                changes['summary'] = description
            obj.merge(changes)
            self.library.place_playlists()  # the sidebar retitles and places it now
            await self._follow_listing(parent, obj.id, name)

        return self._run(method, args, after=after)

    def _on_delete(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        if not is_manageable(obj):
            self.app.toast(_('This cannot be deleted'))
            return None
        name = obj.title
        if obj.kind == 'folder':
            count = sum(1 for kind, _id in self._inside(obj) if kind == 'playlist')
            heading = _('Delete Folder?')
            if count:
                body = ngettext(
                    '“{name}” and the playlist in it will be deleted from your library on all '
                    'your devices. This cannot be undone.',
                    '“{name}” and the {count} playlists in it will be deleted from your '
                    'library on all your devices. This cannot be undone.',
                    count).format(name=name, count=count)
            else:
                body = _('“{name}” will be deleted from your library on all your devices. '
                         'This cannot be undone.').format(name=name)
        else:
            heading = _('Delete Playlist?')
            body = _('“{name}” will be deleted from your library on all your devices. This '
                     'cannot be undone.').format(name=name)
        return self.ask_confirm(heading, body, _('_Delete'), lambda: self.delete(obj))

    def delete(self, obj):
        """Delete a playlist of the user's, or a folder with what is in it: the window leaves
        their pages, and the library follows once Apple's listing has them gone. The task,
        or None."""
        if obj.kind == 'folder':
            method = self.engine.delete_folder
        else:
            method = self.engine.delete_playlist
        parent = self._parent_of(obj)
        gone = {(obj.kind, obj.id), *self._inside(obj)}

        async def after():
            self.window.leave(gone, parent)
            await self._follow_listing(parent, obj.id, None)

        return self._run(method, (obj.id,), _('Deleted “{name}”').format(name=obj.title),
                         after=after, playlist=obj.id if obj.kind == 'playlist' else None)

    def _on_move_to_folder(self, _action, parameter):
        folder_id, kind, item_id = parameter.unpack()
        obj = self._resolve(kind, item_id)
        if not folder_id:  # Move to Folder's New Folder…
            return self._ask_new_folder_for(obj)
        return self.move_to_folder(obj, folder_id)

    def move_to_folder(self, obj, folder_id):
        """Move a playlist (or a folder) into the folder folder_id (ROOT_FOLDER: the top
        level). The library shows it there at once (Library.hold(): the sidebar and the
        folders' pages follow); Apple's refusal puts it back (Library.release()) and is
        reported; once Apple takes it, a toast says where it went, with Undo (a move back),
        and the library follows Apple's listing. The task, or None when it cannot be moved
        there (toasted) or with the demo library."""
        if self.app.refuse_in_demo():
            return None
        tree = self.library.playlist_tree()
        if (not isinstance(obj, Item) or move_targets(tree, obj) is None
                or not tree.can_move(obj.kind, obj.id, folder_id)
                or not api.can_move_to_folder(obj.kind, folder_id)):
            self.app.toast(_('This cannot be moved there'))
            return None
        previous = self._parent_of(obj)
        folder = self.library.by_id('folder', folder_id)
        if folder_id == ROOT_FOLDER or folder is None:
            message = _('Moved “{name}” to the top level').format(name=obj.title)
        else:
            message = _('Moved “{name}” to “{folder}”').format(name=obj.title,
                                                               folder=folder.title)
        change = TreeChange.move(obj.kind, obj.id, folder_id)
        self.library.hold(change)

        async def run():
            try:
                await self.app.player.ensure_engine()
                await self.engine.move_to_folder(obj.kind, obj.id, folder_id)
            except EngineError as error:
                self.library.release(change)
                self.app.report(error)
                return False
            if api.can_move_to_folder(obj.kind, previous):
                self.app.toast(message, _('Undo'), 'win.item-move-to-folder',
                               GLib.Variant('(sss)', (previous, obj.kind, obj.id)))
            else:
                self.app.toast(message)
            await self._follow_listing(folder_id, obj.id, obj.title,
                                       settle_delays(obj.kind, folder_id))
            return True

        return self.app.spawn(run())

    def _on_new_folder(self, _action, parameter):
        """A new folder, named in a dialog, in the folder the target names ('folder', its
        id; 'root': the top level)."""
        _obj, kind, item_id = self._unpack(parameter)
        parent = item_id if kind == 'folder' and item_id else ROOT_FOLDER
        return self.ask_name(_('New Folder'), _('_Create'), '', None,
                             lambda name, _description: self.new_folder(parent, name))

    def _ask_new_folder_for(self, obj):
        """Move to Folder's New Folder…: a folder named in a dialog, made in the folder
        that holds obj, and obj moved into it."""
        if not isinstance(obj, Item) or move_targets(self.library.playlist_tree(), obj) is None:
            self.app.toast(_('This cannot be moved there'))
            return None
        parent = self._parent_of(obj)
        return self.ask_name(_('New Folder'), _('_Create'), '', None,
                             lambda name, _description: self.new_folder(parent, name, obj))

    def new_folder(self, parent_id, name, holding=None):
        """Make a folder called `name` in the folder parent_id (ROOT_FOLDER: the top
        level), and, with `holding` (a playlist or folder Item), move that into it. The
        folder is shown as soon as Apple answers with its id (Library.hold()) and its page
        selected; the library then follows Apple's listing. A move that fails keeps the
        folder (the failure is reported). The task, or None with the demo library."""
        if self.app.refuse_in_demo():
            return None

        async def run():
            try:
                await self.app.player.ensure_engine()
                new_id = await self.engine.create_folder(name, parent_id)
            except EngineError as error:
                self.app.report(error)
                return False
            self.library.hold(TreeChange.create(new_id, name, parent_id))
            self.window.select_page(f'folder:{new_id}')  # sidebar.folder_key
            self.app.toast(_('Created “{folder}”').format(folder=name))
            if holding is not None:
                task = self.move_to_folder(holding, new_id)
                if task is not None:
                    await asyncio.wait([task])
            await self._follow_listing(parent_id, new_id, name,
                                       settle_delays('folder', parent_id))
            return True

        return self.app.spawn(run())

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
                self.window.announce(_('Removed from Up Next'),
                                     Gtk.AccessibleAnnouncementPriority.MEDIUM)

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
                self.window.announce(queue_move_message(entry.title, entry.index,
                                                        player.queue_index,
                                                        player.queue.get_n_items()),
                                     Gtk.AccessibleAnnouncementPriority.MEDIUM)

        return self.app.spawn(move())

    def _tree_node(self, obj):
        """obj's node in the library's PlaylistTree, or None."""
        for node in self.library.playlist_tree().flat:
            if node.kind == obj.kind and node.id == obj.id:
                return node
        return None

    def _parent_of(self, obj):
        """The id of the folder holding a playlist or folder (ROOT_FOLDER: the top level)."""
        node = self._tree_node(obj)
        if node is None or node.parent is None or node.parent.parent is None:
            return ROOT_FOLDER
        return node.parent.id

    def _inside(self, obj):
        """(kind, id) of everything in a folder, however deep; nothing for a playlist."""
        node = self._tree_node(obj) if obj.kind == 'folder' else None
        found = []
        stack = list(node.children) if node is not None else []
        while stack:
            child = stack.pop()
            found.append((child.kind, child.id))
            stack.extend(child.children)
        return found

    async def _follow_listing(self, folder_id, item_id, name, delays=None):
        """After a playlist write: wait until Apple lists it (wait_listed), then bring the
        library up to date with the playlists pass of a sync, and wait for that."""
        await self.wait_listed(folder_id, item_id, name, delays)
        task = self.app.start_sync(playlists=True)
        if task is not None:
            await asyncio.wait([task])

    async def wait_listed(self, folder_id, item_id, name, delays=None):
        """Wait until Apple lists the playlist or folder item_id in the folder folder_id
        under `name` (None: not at all), looking again after each of `delays` (None:
        SETTLE_DELAYS; settle_delays() picks them). True once it does; False when it never
        did, or the engine could not say. Right after a deletion Apple can answer for the
        folder with
        nothing at all (a 404, or an empty list) while it still holds other things: for
        `name` None, an empty answer counts only when the folder held nothing else."""
        node = self.library.playlist_tree().folder(folder_id)
        others = node is not None and any(child.id != item_id for child in node.children)
        for delay in SETTLE_DELAYS if delays is None else delays:
            await asyncio.sleep(delay)
            try:
                children = await self.engine.folder_children(folder_id)
            except EngineError as error:
                log.debug('playlist listing not read: %s', error)
                return False
            found = next((child for child in children if child['id'] == item_id), None)
            if name is None and found is None and (children or not others):
                return True
            if name is not None and found is not None and found['name'] == name:
                return True
        log.info('Apple does not list the change yet: the library follows its listing')
        return False

    # -- removing from the library -----------------------------------------------------------

    def removal_target(self, obj):
        """obj's removal_target() in the app's library, or None."""
        return removal_target(obj, self.library)

    def _on_remove_from_library(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        target = self.removal_target(obj) if obj is not None else None
        if target is None:
            self.app.toast(_('This is not in your library'))
            return None
        heading, body = removal_words(target[0], obj.title or '')
        return self.ask_confirm(heading, body, _('_Remove'),
                                lambda: self.remove_from_library(obj, target))

    def remove_from_library(self, obj, target):
        """Take obj out of the library (`target`, its removal_target: (kind, library id)).
        The library leaves it out at once (Library.hide: its stores, its albums and
        playlists, the pages), before Apple has answered; a failure brings it back
        (Library.unhide) and is reported. Once Apple has taken it, the window leaves its
        pages, and the library follows Apple's listings when they no longer hold it
        (_follow_removal). The task, or None."""
        if self.app.refuse_in_demo():
            return None
        kind, library_id = target
        hidden, holding, gone = self._removal_refs(obj, kind, library_id)
        # A catalog playlist's removal takes out the library's (removal_target): its folder.
        parent = (self._parent_of(self.library.by_id('playlist', library_id) or obj)
                  if kind == 'playlist' else None)
        title = obj.title or ''
        message = (_('Removed “{title}” from your library').format(title=title) if title
                   else _('Removed from your library'))

        async def run():
            self.app.spawn(self.library.hide(hidden))
            try:
                await self.app.player.ensure_engine()
                await self.engine.remove_from_library(kind, library_id)
            except EngineError as error:
                self.app.spawn(self.library.unhide(hidden))
                self.app.report(error)
                return False
            self.app.toast(message)
            if gone:
                self.window.leave(gone, parent)
            await self._follow_removal(kind, library_id, parent, holding)
            return True

        return self.app.spawn(run())

    def _removal_refs(self, obj, kind, library_id):
        """What a removal of obj takes with it: (the refs Library.hide leaves out, the ids
        of the playlists holding it, whose tracks the sync reads again, the (kind, id) of the
        pages to leave)."""
        if kind == 'playlist':
            return {('playlist', library_id)}, (), {('playlist', library_id)}
        if kind == 'album':
            album = self.library.by_id('album', library_id)
            ids = set()
            for group in (album.raw.get('groups') or []) if album is not None else ():
                for entry in group.get('entries') or []:
                    ids.update(value for value in (entry.get('id'), entry.get('catalogId'))
                               if value)
            return ({('album', library_id)}, self.library.playlists_holding(ids),
                    {('album', library_id)})
        catalog_id = getattr(obj, 'catalog_id', None)
        hidden = {(kind, library_id)} | ({(kind, catalog_id)} if catalog_id else set())
        gone = {('video', library_id)} if kind == 'video' else set()
        if isinstance(obj, Track) and obj.play.get('kind') == 'album':
            album = self.library.by_id('album', obj.play.get('id'))
            if album is not None and sum(group.entries.get_n_items()
                                         for group in album.groups) <= 1:
                gone.add(('album', album.id))  # its one song: the album goes too
        return (hidden, self.library.playlists_holding({library_id, catalog_id} - {None}),
                gone)

    async def _follow_removal(self, kind, library_id, parent, holding):
        """After a removal Apple took: a playlist's, as a deleted playlist's
        (_follow_listing); anything else's once Apple's library read no longer has it
        (wait_removed), with the quick pass of a sync, which reads the songs, the music
        videos and the tracks of the playlists that held it (`holding`). Until a load no
        longer meets it, the library leaves it out (Library.hide)."""
        if kind == 'playlist':
            await self._follow_listing(parent, library_id, None)
            return
        if await self.wait_removed(kind, library_id):
            await asyncio.sleep(LISTING_LAG)
        task = self.app.start_sync(quick=True, videos=kind == 'video',
                                   tracks_of=tuple(holding))
        if task is not None:
            await asyncio.wait([task])

    async def wait_removed(self, kind, library_id):
        """Wait until Apple's library read answers that library_id is gone (Engine.
        in_library), looking after each of REMOVAL_DELAYS. True once it does; False when it
        never did, or the engine could not say."""
        for delay in REMOVAL_DELAYS:
            await asyncio.sleep(delay)
            try:
                if not await self.engine.in_library(kind, library_id):
                    return True
            except EngineError as error:
                log.debug('library read after a removal: %s', error)
                return False
        log.info('Apple still lists the item removed: the library follows its listing')
        return False

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
        dialog.present(self.window)
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
