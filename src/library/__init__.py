# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The library as GObject models the UI binds to, loaded from the cache's library.json.

library.json holds the Item and Track shapes src/backend/README.md describes. Library.load()
parses it in a thread and wraps it on the main thread in batches, so pages fill while frames
keep painting. Items become Item objects in one Gio.ListStore per section; an Item's `groups`
are wrapped only when first asked for, and the Songs store (`songs`, a SongModel) holds a
SongEntry per song, which makes its Track (its album's own) only when a view asks for it.
SongOrder sorts the Songs table.
GLib, GObject and Gio only, no GTK, so the model works in tests without a display.

Besides the README's shape, library.json may hold `folders`, the user's playlist folders (an
optional key, like `sections.videos`; the demo and the sync write it): a
list of {id, title, parent, children}, `parent` a folder id or null and `children` a list of
{kind: "folder" | "playlist", id} in Apple's order. The entry with id "root" lists what is in
no folder. PlaylistTree reads it, and lists each folder's contents as Apple Music's sidebar
does: Favourite Songs, the folders, the playlists, each group by title. `sections.songs`,
which only older syncs wrote, holds Track dicts: the library's loose songs, which the Songs
store takes after the albums' tracks, by id (the sync now leaves them under their stand-in
albums only). `sections.videos` holds Items of kind 'video'.

Since version 3 an Item may carry `added` (Apple's dateAdded: Item.added, in seconds) and the
file `favourites`, {section: ids} (favourite_set()): the account's favourites, a song by its
catalog id (else its library id), anything else by its library and catalog ids. Each Item's
`favourite` is set from them, and Library.is_favourite() answers for a Track (the rows ask
as they bind); Library.set_favourite() follows the app's own changes (the Engine's `rated`;
set_favourites() several at once, a selection's ahead of its writes) and
`favourites-changed` says the set changed. `recently_added` is the library's albums,
playlists and dated videos, newest added first (recently_added_order()), or, from a file
without dates, Apple's own recently-added shelf.

Since version 5 a Track carries its `genre` and `year` (TRACK_FIELDS), the song tables'
optional columns, which SongOrder sorts by too. `genres()` is the Genres page's store, an Item
of kind 'genre' for each genre the albums have (genre_items()), made at its first call and
kept up to date by every load after it.

load() makes new objects for everything; reload() (after a sync) reads the file again and brings
the models up to date in place: an Item or Track still in the library keeps its object, so open
pages and scroll positions survive. hide() makes every load leave out what was just removed
from the library (leave_out(), on the parsed file), at once and until Apple's listings, and so
the file, no longer hold it; unhide() brings it back.

Reading the file starts the moment load() is called, in a thread of its own, so the app calls
it before GTK has even started (Application.do_startup) and the parse runs while GTK starts and
the compositor maps the window, both C with the GIL let go. The parse decodes the file's big
lists an element at a time (parse()): json's C decoder holds the GIL for its whole call, and one
call for a 50 MB file would keep the main thread's Python (every signal handler and vfunc)
waiting 300 ms. The artists' groups repeat their albums' tracks; those lists are dropped at
parse time when the album is in the library (the artist page shows the album's own), and the
tracks' repeated names share one string each: together they cut what 40,000 tracks cost after
the parse by 40%. Each track is then kept as a tuple (TrackRecord), not a dict: 15 MB less
again. Garbage collection is paused from a load()'s call to its end (the parse and
the wrapping run without it) and during a Songs build, and the heap is frozen after both
(paused_gc), so the library is never scanned again: a full collection over it cost 50 ms, a
dropped frame each time one came round.

The package, one idea a module: records (library.json's raw values, TrackRecord), words (the
model's own words), text_keys (folded and collated keys), diff (apply_diff()), pacing
(FRAME_BUDGET, yield_to_frames(), paused_gc), objects (Item, Group, Track, ShelfModel),
songs (the Songs store's SongEntry and SongModel, SongOrder), refs (what a drag carries),
folders (PlaylistTree, TreeChange), reading (the parse, leave_out()) and model (the
Library). Every module is GLib, GObject and Gio only. The names the rest of the app uses
are imported from the package itself, here.
"""

from .diff import apply_diff
from .folders import ROOT_FOLDER, PlaylistTree, TreeChange, apply_changes
from .model import HELD_KINDS, Library, recently_added_order
from .objects import (EDITABLE, FAVOURITES, PUBLIC, REMOVABLE, TRACK_KINDS, Item, ShelfModel,
                      Track, drop_index, entries_without, moved, order_for)
from .pacing import FRAME_BUDGET, yield_to_frames
from .reading import parse
from .records import TrackRecord, added_seconds, favourite_set, release_passed
from .refs import TRACK_REF_KINDS, ItemRefs, Ref, track_ref
from .songs import (SongEntry, SongModel, SongOrder, make_song_tracks, narrows,
                    prepare_search_keys, selection_key, song_key, song_track, song_tracks,
                    songs_matching)
from .text_keys import filter_matches, fold, search_key
from .words import N_

__all__ = [
    'EDITABLE', 'FAVOURITES', 'FRAME_BUDGET', 'HELD_KINDS', 'N_', 'PUBLIC', 'REMOVABLE',
    'ROOT_FOLDER', 'TRACK_KINDS', 'TRACK_REF_KINDS', 'Item', 'ItemRefs', 'Library',
    'PlaylistTree', 'Ref', 'ShelfModel', 'SongEntry', 'SongModel', 'SongOrder', 'Track',
    'TrackRecord', 'TreeChange', 'added_seconds', 'apply_changes', 'apply_diff', 'drop_index',
    'entries_without', 'favourite_set', 'filter_matches', 'fold', 'make_song_tracks', 'moved',
    'narrows', 'order_for', 'parse', 'prepare_search_keys', 'recently_added_order',
    'release_passed', 'search_key', 'selection_key', 'song_key', 'song_track', 'song_tracks',
    'songs_matching', 'track_ref', 'yield_to_frames',
]
