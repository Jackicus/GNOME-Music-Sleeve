# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Library: the stores the pages bind, filled by load(), kept by reload(), and what it
holds ahead of Apple's listings (folder changes, playlist orders, additions, removals).

The package's docstring (library/__init__.py) describes the file and the load as a whole.
"""

import asyncio
import concurrent.futures
import logging
import threading
import time

from gi.repository import Gio, GObject

from ..backend import config
from .diff import apply_diff
from .folders import (PENDING_HOLD, ROOT_FOLDER, PlaylistTree, _now, apply_changes,
                      change_settled, folder_entries)
from .objects import SORT_KEYS, Item, ShelfModel, Track, order_for, reorder_entries
from .pacing import FRAME_BUDGET, paused_gc, yield_to_frames
from .reading import _read_library, leave_out
from .records import _dicts, _entries, _entries_of, _entry_ids, _number, _text, favourite_set
from .songs import SongEntry, SongModel
from .text_keys import fold, title_key
from .words import albums_text, shelf_title

log = logging.getLogger(__name__)


# The sections of library.json and the stores they fill.
SECTIONS = ('albums', 'artists', 'playlists', 'radio', 'videos')

# How many Items a section is spliced into its store in one go. One splice for any section
# of the sizes seen so far: wrapping 3,000 albums takes 9 ms, and each splice into a sorted
# grid costs more than that (GTK re-sorts and rebinds the tiles it has made): one splice of
# 3,000 albums took 68 ms at startup, six of 500 took 157, and the first frames showed
# albums that the next batches then pushed away.
BATCH_SIZE = 5000


# The kinds of Item Library.holds() answers for: what has an Add button on its page.
HELD_KINDS = ('album', 'playlist')


class _OrderHold:
    """A playlist's track order shown ahead of Apple's listing (Library.reorder()): its
    tracks' ids in that order, until `expires` (_now() seconds)."""

    __slots__ = ('ids', 'expires')

    def __init__(self, ids, hold):
        self.ids = list(ids)
        self.expires = _now() + hold


def _index_folders(index, tree):
    """Add a PlaylistTree's folder Items, the top level's among them, to a by_id() index."""
    for node in tree.folders():
        index.setdefault(('folder', node.id), node.item)
    index.setdefault(('folder', ROOT_FOLDER), tree.root.item)


class _Superseded(Exception):
    """A newer load() started while this one waited."""


class Library(GObject.Object):
    """The whole library: one store per section, the shelves, and the Songs store.

    The stores are created once and filled in place, so a page can bind them before anything
    is loaded. `state` is 'empty' (nothing loaded, no library.json, or a load that failed or
    was cancelled), 'loading' or 'ready'; 'changed' is emitted when a load() finishes, whatever
    it found. `songs-ready` is true once the Songs store has been filled (build_songs()).
    `file-state` is what the last load found on disk: 'ok', 'missing' or 'unreadable' ('' until
    a load has read the file), and `version` that file's `version` (0 when it has none): a
    missing, unreadable or outdated library is due a sync. `syncing` is true while a sync
    runs (the sync sets it), so that a page can show an empty library as on its way.
    `playlists-changed` says the playlist tree was placed again between loads
    (place_playlists()), or made again with a change to the folders held ahead of Apple's
    listing (hold(), release(): a playlist moved or a folder made, shown at once and kept
    through reloads until library.json shows it or PENDING_HOLD has passed).
    `item-added` (kind, id) says an album or playlist of the catalog's was added to the
    library (note_added()), which holds() answers at once, ahead of Apple's listing.
    """

    __gtype_name__ = 'AppleMusicLibrary'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'playlists-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'item-added': (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        'favourites-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def _get_syncing(self):
        return self._syncing

    def _set_syncing(self, value):
        value = bool(value)
        if value != self._syncing:  # notified only when it changes (EXPLICIT_NOTIFY)
            self._syncing = value
            self.notify('syncing')

    state = GObject.Property(type=str, default='empty')
    syncing = GObject.Property(type=bool, default=False, getter=_get_syncing,
                               setter=_set_syncing,
                               flags=GObject.ParamFlags.READWRITE
                               | GObject.ParamFlags.EXPLICIT_NOTIFY)
    file_state = GObject.Property(type=str, default='')
    version = GObject.Property(type=int, default=0)
    generated = GObject.Property(type=str)
    storefront = GObject.Property(type=str)
    songs_ready = GObject.Property(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.albums = Gio.ListStore(item_type=Item)
        self.artists = Gio.ListStore(item_type=Item)
        self.playlists = Gio.ListStore(item_type=Item)
        self.radio = Gio.ListStore(item_type=Item)
        self.videos = Gio.ListStore(item_type=Item)
        self.recently_added = Gio.ListStore(item_type=Item)
        self._genres = Gio.ListStore(item_type=Item)
        self._genres_wanted = False  # genres() was called: every load brings it up to date
        self.shelves = []
        self.batch_size = BATCH_SIZE
        self._songs = SongModel()
        self._songs_wanted = False  # build_songs() was called: every load() refills the store
        self._song_count = 0
        self._index = {}  # (kind, id) -> Item
        self._favourites = None  # the Favourite Songs playlist, found by each load
        self._favourite_ids = frozenset()  # library.json's favourites, and the app's changes
        self._loose = []  # sections.songs: the loose songs' Track dicts
        self._loose_entries = {}  # id -> SongEntry, for the loose songs in the Songs store
        self._tree = PlaylistTree()
        self._folders = []  # library.json's `folders`, as the last load read them
        self._changes = []  # TreeChanges held ahead of Apple's listing (hold())
        self._held = None  # holds()'s dictionaries, made at its first question after a load
        self._added = {}  # (kind, id) -> the Item, for what note_added() noted
        self._orders = {}  # playlist id -> _OrderHold: orders shown ahead of Apple's (reorder())
        self._generation = 0
        self._paused = 0.0  # when a load or Songs build last paused for a frame (_pause())
        self._syncing = False
        self._reader = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix='library')  # its own: never behind a decode
        self._reading = threading.Event()  # clear: the parse waits (hold_reading())
        self._reading.set()
        self._hidden = frozenset()  # what every load leaves out (hide())
        self._song_ids = None  # {id or catalog id: library id} of the songs (library_id())

    @property
    def songs(self):
        """The Songs store: every album's tracks, then the loose songs (sections.songs),
        deduplicated by id, in album order, as a SongModel: SongEntries (`songs.entries`),
        each made a Track only when it is asked for, so the albums' groups are not wrapped
        for it and 40,000 songs cost 3 MB, not 23.

        It stays empty until build_songs() fills it (`songs-ready`); from then on every load()
        and reload() brings it up to date with the fewest changes (apply_diff), a song whose
        TrackRecord and group are the same keeping its entry (and so its Track), so the
        views over it keep the rows of the songs still there.
        """
        return self._songs

    def song_count(self):
        """How many tracks `songs` holds or will hold, without building it."""
        return self._songs.get_n_items() if self.songs_ready else self._song_count

    def genres(self):
        """The Genres store: an Item of kind 'genre' for each genre the library's albums
        have (genre_items()), by name.

        Filled at the first call, from the albums as they are (a few milliseconds for 3,000),
        and from then on brought up to date by every load and reload, a genre still there
        keeping its Item (merged) and its place (apply_diff). Nothing before the first call:
        the app starts without it."""
        if not self._genres_wanted:
            self._genres_wanted = True
            self._fill_genres(keep=True)
        return self._genres

    def _fill_genres(self, keep):
        kept = {item.id: item for item in self._genres} if keep else {}
        items = []
        for raw in genre_items(self.albums):
            item = kept.get(raw['id'])
            if item is None:
                item = Item(raw)
            else:
                item.merge(raw, replace=True)
            items.append(item)
        apply_diff(self._genres, items)

    async def build_songs(self):
        """Fill the Songs store, unless it is filled or being filled already.

        Wrapping 30,000 tracks takes about 300 ms, so it runs a few albums at a time with a
        pause for GTK to paint in between, and the store is spliced in one go at the end, so a
        view over it sorts once. When a load() is running, that load fills the store as it
        finishes; a load() that overtakes this build fills it instead.
        """
        if self._songs_wanted:
            return
        self._songs_wanted = True
        if self.state == 'loading':
            return
        with paused_gc():
            try:
                self._paused = time.monotonic()
                await self._fill_songs(self._generation)
            except _Superseded:
                pass  # the load that overtook it fills the store
            except BaseException:
                self._songs_wanted = self.songs_ready  # failed or cancelled: ask again
                raise

    def by_id(self, kind, item_id):
        """The Item of that kind and id, from a section, a shelf or the playlist folders
        (kind 'folder'), or None."""
        return self._index.get((kind, item_id))

    def shelf(self, key):
        """The shelf with that key ('recently-added', 'heavy-rotation'…), or None."""
        return next((shelf for shelf in self.shelves if shelf.key == key), None)

    def playlist_tree(self):
        """The playlists and folders as a PlaylistTree: `root` nested, `flat` depth first.

        A new tree for each load() and reload(): load() makes new folder Items and stores,
        reload() keeps those of the folders still there. Before the first load, an empty one.
        """
        return self._tree

    def folder_items(self, folder_id):
        """A Gio.ListStore of the Items (folders and playlists) in the folder with that id, in
        the sidebar's order (PlaylistTree), or None when there is no such folder. ROOT_FOLDER
        is the top level. reload() keeps a folder's store, brought up to date; load() makes new
        stores: follow the folder by its id."""
        node = self._tree.folder(folder_id)
        return node.store if node is not None else None

    def place_playlists(self):
        """Place the playlists and folders again by their titles, after one was retitled in
        place (a rename merged into its Item ahead of the next sync), and emit
        `playlists-changed`: the folders' stores move what moved with the fewest changes, and
        the window's sidebar follows the signal as it follows `changed` (retitled, moved,
        selection and folders kept). A load or reload places everything itself."""
        self._tree.sort()
        self.emit('playlists-changed')

    def hold(self, change):
        """Show a TreeChange to the playlist folders at once, ahead of Apple's listing: the
        tree is made again from the file's folders and the changes held (apply_changes()),
        keeping the folder Items and stores, and `playlists-changed` emitted (the sidebar
        moves what moved, its selection and open folders kept). Every reload() goes on
        showing it until library.json does (change_settled()) or it expires (PENDING_HOLD);
        a folder's move keeps the folder as shown now (TreeChange.entries), for a reload
        whose file lists it nowhere. load() forgets every change. False, and nothing held,
        for a move the tree refuses (PlaylistTree.can_move()) or a folder created twice."""
        if change.op == 'move' and not self._tree.can_move(change.kind, change.id,
                                                          change.folder_id):
            return False
        if change.op == 'create' and (self._tree.folder(change.id) is not None
                                      or self._tree.folder(change.folder_id) is None):
            return False
        if change.op == 'move':
            if change.kind == 'folder':
                # The folder as shown now, for a reload whose file lists it nowhere.
                change.entries = folder_entries(apply_changes(self._folders, self._changes),
                                                change.id)
            # A later move of the same item (Undo) replaces the one before: the two would
            # never both be listed.
            self._changes = [held for held in self._changes
                             if (held.op, held.kind, held.id) != ('move', change.kind, change.id)]
        self._changes.append(change)
        self._replant()
        return True

    def release(self, change):
        """Stop showing a TreeChange held (Apple refused it): the tree is made again without
        it, so what it moved is back where the file has it. Nothing for one not held."""
        if change in self._changes:
            self._changes.remove(change)
            self._replant()

    def pending_changes(self):
        """The TreeChanges held ahead of Apple's listing, oldest first."""
        return list(self._changes)

    def reorder(self, item, order, hold=PENDING_HOLD):
        """Put a playlist's tracks in a new order at once (Item.reorder(): `order`, positions
        in the list shown), and hold that order ahead of Apple's listing: every reload()
        whose file lists the same tracks in another order shows this one instead (the merge
        then finds nothing changed), until the file shows it, lists other tracks (changed
        elsewhere: the file wins) or `hold` seconds have passed; load() forgets it. False,
        and nothing changed, where Item.reorder() refuses."""
        if not isinstance(item, Item) or not item.reorder(order):
            return False
        self._orders[item.id] = _OrderHold(item.track_ids(), hold)
        return True

    def release_order(self, playlist_id):
        """Stop holding a playlist's order (its write failed, or was put back): the next
        reload shows the file's."""
        self._orders.pop(playlist_id, None)

    def held_order(self, playlist_id):
        """The track ids of a playlist's order held ahead of Apple's listing, or None."""
        held = self._orders.get(playlist_id)
        return list(held.ids) if held is not None and held.expires > _now() else None

    def with_held_order(self, raw):
        """A playlist's Item dict (a reload's, an engine.item() answer) with its tracks in the
        order held for it (reorder()), when it lists the same tracks in another order; the
        dict itself otherwise, the hold let go when the dict shows the order, lists other
        tracks, or the hold has expired."""
        playlist_id = _text(raw.get('id')) if raw.get('kind') == 'playlist' else None
        held = self._orders.get(playlist_id) if playlist_id else None
        if held is None:
            return raw
        groups = _dicts(raw.get('groups'))
        entries = _entries(groups[0].get('entries')) if len(groups) == 1 else None
        order = order_for(entries, held.ids) if entries is not None else None
        if held.expires <= _now() or order is None or order == list(range(len(order))):
            del self._orders[playlist_id]
            return raw
        return dict(raw, groups=[dict(groups[0], entries=reorder_entries(entries, order))])

    def _pending(self, folders):
        """The changes held that library.json's `folders` does not show yet and that have
        not expired."""
        now = _now()
        return [change for change in self._changes
                if change.expires > now and not change_settled(folders, change)]

    def _replant(self):
        """The playlist tree made again from the file's folders and the changes held, as a
        reload makes it (the folder Items and stores kept), and `playlists-changed`."""
        tree = PlaylistTree(apply_changes(self._folders, self._changes), list(self.playlists),
                            self._index, self._tree.stores())
        index = {key: item for key, item in self._index.items() if key[0] != 'folder'}
        _index_folders(index, tree)
        self._tree = tree
        self._index = index
        if tree.changed:
            self._notify_changed(dict.fromkeys(tree.changed))
        self.emit('playlists-changed')

    def holds(self, item):
        """Whether the library holds `item`, an album or playlist Item: one of its own, or one
        of the catalog's it has added, found by its catalog id (an Apple playlist added
        carries one) or, for an album, by its title and artist (a library album carries no
        catalog id: the sync's) and, when `item` has its songs, by one of them; or one that
        note_added() noted and the library does not list yet. Shelves are not the library:
        only the Albums and Playlists sections count. Dictionaries made at the first question
        after each load, so no request and no walk of the songs."""
        if item is None or item.kind not in HELD_KINDS or not item.id:
            return False
        return (item.kind, item.id) in self._added or self._find_held(item) is not None

    def held_item(self, item):
        """The library's own album or playlist Item that `item` is found as, as holds()
        finds it (itself, for one of the library's), or None: also for one note_added()
        noted that the library does not list yet. What Remove from Library takes out of a
        catalog album or playlist the library holds."""
        if item is None or item.kind not in HELD_KINDS or not item.id:
            return None
        return self._find_held(item)

    def note_added(self, item):
        """Note that `item`, an album or playlist of the catalog's, was just added to the
        library (Apple took the write): holds() says so at once, ahead of the listing (Apple
        lists an addition seconds to a minute later, src/backend/README.md), and emits
        `item-added`. A reload() that lists it drops the note; load() forgets them all."""
        if item is None or item.kind not in HELD_KINDS or not item.id:
            return
        self._added[(item.kind, item.id)] = item
        self.emit('item-added', item.kind, item.id)

    def _find_held(self, item):
        """The library's album or playlist Item that `item` is, or None (holds())."""
        if self._held is None:
            self._held = self._held_index()
        by_id, by_title = self._held
        for value in (item.id, item.catalog_id):
            found = by_id.get((item.kind, value)) if value else None
            if found is not None:
                return found
        if item.kind != 'album':
            return None
        candidates = by_title.get(_album_key(item.raw))
        if not candidates:
            return None
        ids = {value for group in item.groups for track in group.entries
               for value in (track.id, track.catalog_id) if value}
        if not ids:
            return candidates[0]
        return next((album for album in candidates
                     if any(track.catalog_id in ids or track.id in ids
                            for group in album.groups for track in group.entries)), None)

    def _held_index(self):
        """({(kind, id or catalog id): Item}, {album key: [Item]}) for the Albums and
        Playlists sections, from the Items' raw dicts (no property is read)."""
        by_id = {}
        by_title = {}
        for kind, store in (('album', self.albums), ('playlist', self.playlists)):
            for position in range(store.get_n_items()):
                item = store.get_item(position)
                raw = item.raw
                for value in (raw.get('id'), raw.get('catalogId')):
                    if value:
                        by_id.setdefault((kind, _text(value)), item)
                if kind == 'album':
                    by_title.setdefault(_album_key(raw), []).append(item)
        return by_id, by_title

    def favourite_songs(self):
        """The Favourite Songs playlist (Item.favourites), or None when the library has none."""
        return self._favourites

    def is_favourite(self, obj):
        """Whether a Track or an Item is one of the account's favourites: a track by its
        catalog id or its own, an Item by its id or its catalog id (two set lookups: rows
        ask it as they bind)."""
        ids = self._favourite_ids
        if not ids or obj is None:
            return False
        raw = obj.raw
        if raw.get('id') in ids:
            return True
        catalog_id = raw.get('catalogId')
        return catalog_id is not None and str(catalog_id) in ids

    def set_favourite(self, item_id, favourite):
        """The account made (or unmade) a favourite of the song, album, playlist or video
        with that id, as the app rated it (Engine's `rated`: a song by its catalog id, else
        its own; anything else by the id it was rated by). Taken away, every id the library
        knows the same Item by goes too, its library and its catalog id. The Items holding
        it notify `favourite`, and `favourites-changed` says rows should look again.
        Returns whether anything changed. Kept until the next load: library.json is the
        sync's to write."""
        return self.set_favourites((item_id,), favourite)

    def set_favourites(self, item_ids, favourite):
        """set_favourite() for several ids at once, with one `favourites-changed`: a
        selection's Remove from Favourites shown ahead of its writes, and put back for those
        that failed."""
        wanted = {str(item_id) for item_id in item_ids if item_id}
        if not wanted:
            return False
        ids = set(self._favourite_ids)
        if favourite:
            ids |= wanted
        else:
            ids -= wanted
            for item in self._index.values():
                raw = item.raw
                if raw.get('id') in wanted or raw.get('catalogId') in wanted:
                    ids.discard(raw.get('id'))
                    ids.discard(raw.get('catalogId'))
        if ids == self._favourite_ids:
            return False
        self._favourite_ids = frozenset(ids)
        self._mark_favourites(self._index.values())
        self.emit('favourites-changed')
        return True

    def _mark_favourites(self, items):
        """Set each Item's `favourite` from the ids (notified only where it changes)."""
        for item in items:
            favourite = self.is_favourite(item)
            if item._favourite != favourite:
                item.favourite = favourite

    def load(self):
        """Read library.json from the cache directory and fill the models from it: a
        coroutine to await, whose file is being read (in a thread) from the moment this is
        called.

        Wrapping happens on the caller's thread, a batch at a time, with a pause for GTK to
        paint between batches. The stores keep their identity and are refilled in place, with
        new Item objects. A missing or unreadable file leaves the library empty. A load that
        another load() overtakes gives up at its next pause. Garbage collection is paused from
        this call (the parse runs without it) to the load's end, and the heap frozen then
        (paused_gc); closing the coroutine unawaited resumes it too.
        """
        pause = _Pause(freeze=True)  # before the read starts: it collects first
        return self._load(keep=False, reading=self._read(), pause=pause, hidden=self._hidden)

    def reload(self):
        """Read library.json again (after a sync) and bring the models up to date in place.

        Everything is matched by kind and id: an Item still in the library keeps its object
        (its properties set where they changed, its groups and Tracks kept unless they
        changed), what is gone leaves the stores, what is new goes in at its place, and the
        shelves, the folder Items and the folders' stores keep theirs too. A page showing an
        Item, a grid's scroll position and the sidebar's selection all survive.

        What changed is told as it is: a kept Item notifies each property that changed and
        emits `groups-changed` when its groups did (Item.merge()); a kept ShelfModel notifies its
        title. Stores emit `items-changed` only where Items came, went or moved, and where a
        kept Item's title, subtitle or year changed (SORT_KEYS), so that the sort and filter
        models over them place it again (_notify_changed). A view's rows are not rebound by
        that on GTK 4.22: a widget bound to an Item follows its notify signals. As load()
        otherwise, but for the freeze: nothing is frozen after a reload.
        """
        pause = _Pause(freeze=False)
        return self._load(keep=True, reading=self._read(), pause=pause, hidden=self._hidden)

    def hide(self, refs):
        """Leave what `refs` names out of the models from now on, as removed from the library
        (leave_out(): (kind, id) pairs, 'album', 'playlist' and 'video' Items by id, 'song'
        entries by their id or catalog id): the coroutine of the reload that takes it out of
        the stores, the pages and the Songs store at once, ahead of Apple's listings.

        Every later load and reload leaves it out too, while the file it reads still holds
        it: a ref is let go by the first load that does not meet it (the sync that follows
        Apple's listing once it has dropped the item), or by unhide()."""
        self._hidden = self._hidden | frozenset(refs)
        return self.reload()

    def unhide(self, refs):
        """Show what hide(refs) left out again (a removal that failed): the coroutine of the
        reload that brings it back from the file."""
        self._hidden = self._hidden - frozenset(refs)
        return self.reload()

    @property
    def hidden(self):
        """The refs loads leave out now (hide())."""
        return self._hidden

    def library_id(self, kind, item_id, catalog_id=None):
        """The library's own id for the song, music video, album or playlist named by its id
        or its catalog id, or None when the library does not hold it: a song is one of the
        albums' tracks (or a loose song), by its id, else by its catalog id; a video one of
        the music videos; an album or a playlist an Item of the section."""
        if kind == 'song':
            if self._song_ids is None:
                self._song_ids = _song_index(
                    [entry for album in self.albums for entry in _entries_of(album.raw)]
                    + self._loose)
            return self._song_ids.get(item_id) or (
                self._song_ids.get(catalog_id) if catalog_id else None)
        if kind == 'video':
            for video in self.videos:
                if video.id == item_id or (catalog_id and video.catalog_id == catalog_id):
                    return video.id
            return None
        if kind in ('album', 'playlist'):
            item = self.by_id(kind, item_id)
            return item.id if item is not None else None
        return None

    def playlists_holding(self, ids):
        """The ids of the playlists with an entry whose id or catalog id is one of `ids`."""
        ids = set(ids)
        return [playlist.id for playlist in self.playlists
                if any(not ids.isdisjoint(_entry_ids(entry))
                       for entry in _entries_of(playlist.raw))]

    def _read(self):
        """Start reading library.json in the library's thread, now: the Future of
        _read_library's (data, song count, file state)."""
        return self._reader.submit(_read_library, config.cache_dir() / 'library.json',
                                   self._reading)

    def hold_reading(self):
        """Make a parse in progress wait at its next list element, until resume_reading()
        (or HOLD_LIMIT seconds in all): for main-thread Python that should not share the GIL
        with it.

        The parse holds the GIL but for the moments between elements, and a thread that
        wants it back waits up to the interpreter's switch interval (5 ms) each time, so
        Python on the main thread runs at half speed or worse beside it: the app's own start
        and building the window took 120 ms instead of 40 with the parse running, and the
        window was mapped that much later. Held meanwhile, the parse loses those 40 ms and
        catches up while GTK and the compositor map the window, which is C."""
        self._reading.clear()

    def resume_reading(self):
        """Let a parse held by hold_reading() go on."""
        self._reading.set()

    async def _load(self, keep, reading, pause, hidden=frozenset()):
        """load() and reload(): `reading` is the parse's Future, `pause` the _Pause of the
        collector that the call began, left here as the load ends, however it ends; `hidden`
        what to leave out (hide()), as it was at the call."""
        self._generation += 1
        generation = self._generation
        started = time.monotonic()
        self._set_state('loading')
        try:
            data, song_count, file_state = await asyncio.wrap_future(reading)
            reading = None  # the Future holds the parse too
            found = set()
            if hidden and data is not None:
                found, removed = await asyncio.to_thread(leave_out, data, hidden)
                song_count = max(0, song_count - len(removed))
            self._paused = time.monotonic()
            self._check(generation)
            log.debug('Library parsed in %.0f ms', (time.monotonic() - started) * 1000)
            if self.file_state != file_state:
                self.file_state = file_state
            version = _number(data.get('version')) if data is not None else 0
            if self.version != version:
                self.version = version
            loaded = data is not None
            await self._fill(data or {}, generation, keep)
            # What the models did not take goes now, while collections are paused: after the
            # pause, the first collection would have to scan it all.
            del data
        except _Superseded:
            return
        except BaseException:
            # Failed, or cancelled (a sync stopped during its reload): a page waiting on
            # 'loading' would wait forever, and a Songs build it was to do is asked again.
            if generation == self._generation:
                self._songs_wanted = self._songs_wanted and self.songs_ready
                self._set_state('empty')
                self.emit('changed')
            raise
        finally:
            pause.leave()
        self._song_count = song_count
        # What Apple's listing no longer holds needs leaving out no more.
        self._hidden = self._hidden - (hidden - found)
        self._set_state('ready' if loaded else 'empty')
        log.debug('Library %s in %.0f ms: %s, %d shelves, %d songs%s', self.state,
                  (time.monotonic() - started) * 1000,
                  ', '.join(f'{getattr(self, name).get_n_items()} {name}' for name in SECTIONS),
                  len(self.shelves), song_count, ' (in place)' if keep else '')
        self.emit('changed')

    async def _fill(self, data, generation, keep=False):
        self.generated = _text(data.get('generated'))
        self.storefront = _text(data.get('storefront'))
        sections = data.get('sections') if isinstance(data.get('sections'), dict) else {}
        existing = self._index if keep else {}
        index = {}
        changed = {}  # kept Items whose SORT_KEYS changed, in order (a dict as an ordered set)

        if not keep:
            self._orders = {}

        def wrap(raw):
            key = (_text(raw.get('kind')), _text(raw.get('id')))
            if key[0] == 'playlist' and self._orders:
                raw = self.with_held_order(raw)
            item = existing.get(key)
            if item is None:
                item = Item(raw)
            elif not SORT_KEYS.isdisjoint(item.merge(raw, replace=True)):
                changed[item] = None
            index.setdefault(key, item)
            return item

        for name in SECTIONS:
            raws = sections.get(name)
            await self._splice(getattr(self, name), raws if isinstance(raws, list) else [], wrap,
                               generation, keep)

        def shelf_item(raw):
            # The same album or playlist on a shelf and in a section is one object.
            return index.get((raw.get('kind'), raw.get('id'))) or wrap(raw)

        shelves = []
        kept = {shelf.key: shelf for shelf in self.shelves} if keep else {}
        for raw in _dicts(data.get('shelves')):
            key = _text(raw.get('key')) or ''
            title = shelf_title(key, _text(raw.get('title')))
            subtitle = _text(raw.get('subtitle')) or ''
            items = [shelf_item(item) for item in _dicts(raw.get('items'))]
            shelf = kept.pop(key, None)
            if shelf is None:
                shelf = ShelfModel(key, title, items, subtitle)
            else:
                shelf.update(title, items, subtitle)
            shelves.append(shelf)
        self._folders = _dicts(data.get('folders'))
        self._changes = self._pending(self._folders) if keep else []
        tree = PlaylistTree(apply_changes(self._folders, self._changes), list(self.playlists),
                            existing, self._tree.stores() if keep else None)
        _index_folders(index, tree)
        self._loose = _entries(sections.get('songs'))
        self._song_ids = None
        if not keep:
            self._loose_entries = {}
        self.shelves = shelves
        self._tree = tree
        self._index = index
        self._favourites = next((item for item in self.playlists if item.favourites), None)
        # holds() asks the stores as they are now; what it noted stays until they list it.
        self._held = None
        self._added = {key: item for key, item in self._added.items()
                       if self._find_held(item) is None} if keep else {}
        favourites = favourite_set(data.get('favourites'))
        favourites_changed = favourites != self._favourite_ids
        self._favourite_ids = favourites
        self._mark_favourites(index.values())
        recent = self.shelf('recently-added')
        # The albums and playlists (Favourite Songs aside: Apple's own, never added), and the
        # music videos Apple dates (its documentation gives them no dateAdded).
        candidates = [item for item in self.albums]
        candidates += [item for item in self.playlists if not item.favourites]
        candidates += [item for item in self.videos if item.added_seconds()]
        # About 8 ms on 3,300 items (4 for a reload, the dates read already): a frame of its
        # own when the load's budget is spent.
        if time.monotonic() - self._paused > FRAME_BUDGET:
            await self._pause(generation)
        apply_diff(self.recently_added, recently_added_order(
            candidates, list(recent.items) if recent is not None else []))
        if self._genres_wanted:
            self._fill_genres(keep)
        for item in tree.changed:
            changed[item] = None
        if changed:
            self._notify_changed(changed)
        if favourites_changed:
            self.emit('favourites-changed')
        if self._songs_wanted:
            await self._fill_songs(generation)

    def _notify_changed(self, items):
        """Make the sort and filter models over the stores place again the kept Items whose
        SORT_KEYS changed (`items`, a set or dict): in every store holding them (the sections,
        the shelves and the folders), each run of them is spliced over itself, one splice a
        run.

        That is all a same-object splice does on GTK 4.22: a view's bound rows are not rebound
        by it (the list item manager keeps the widget of an item removed and added back in one
        change), so widgets follow their Item's notify signals for what they show.
        """
        stores = [getattr(self, name) for name in SECTIONS]
        stores += [shelf.items for shelf in self.shelves]
        stores += self._tree.stores().values()
        for store in stores:
            positions = [position for position in range(store.get_n_items())
                         if store.get_item(position) in items]
            for start, end in reversed(_runs(positions)):
                store.splice(start, end - start,
                             [store.get_item(position) for position in range(start, end)])

    async def _splice(self, store, raws, wrap, generation, keep=False):
        """Replace the store's contents with the wrapped dicts of the list `raws`, a batch at
        a time.

        Each batch overwrites the old items at its position, so a reload never shows an empty
        store; whatever old items are left over go at the end. Keeping (reload), the wrapped
        items are diffed against the store instead, so unchanged runs are not touched, and
        wrapping (a merge for each kept Item) pauses for a frame every FRAME_BUDGET. `raws`
        lets each dict go as it is wrapped: a kept Item that has not changed keeps the dict it
        holds, and the new copy is freed then, a little at a time, rather than all at once
        with the parse.
        """
        if keep:
            items = []
            for position, raw in enumerate(raws):
                if isinstance(raw, dict):
                    items.append(wrap(raw))
                    raws[position] = None
                if time.monotonic() - self._paused > FRAME_BUDGET:
                    await self._pause(generation)
            apply_diff(store, items)
            return
        dicts = _dicts(raws)
        position = 0
        for start in range(0, len(dicts), self.batch_size):
            started = time.monotonic()
            batch = [wrap(raw) for raw in dicts[start:start + self.batch_size]]
            wrapped = time.monotonic()
            stale = min(len(batch), store.get_n_items() - position)
            store.splice(position, stale, batch)
            position += len(batch)
            log.debug("Library: %d items wrapped in %.0f ms, spliced in %.0f ms (the views' "
                      'work)', len(batch), (wrapped - started) * 1000,
                      (time.monotonic() - wrapped) * 1000)
            await self._pause(generation)
        store.splice(position, store.get_n_items() - position, [])

    async def _pause(self, generation):
        """Let GTK paint a frame (yield_to_frames), then carry on unless a newer load has
        started. The loops of a load and a Songs build call it when FRAME_BUDGET has passed
        since the last pause (`_paused`), one budget across all of them."""
        await yield_to_frames()
        self._check(generation)
        self._paused = time.monotonic()

    async def _fill_songs(self, generation):
        """Bring the Songs store to the albums' tracks and the loose songs: SongEntries made
        from the albums' raw groups (not their Groups, which stay unwrapped), a song whose
        TrackRecord and group's play target and thumbnail are the ones an entry of the store
        holds keeping that entry."""
        started = time.monotonic()
        old_entries = self._songs.entries
        kept = {}  # id(raw) -> the store's entry for it
        for start in range(0, len(old_entries), 5000):
            for entry in old_entries[start:start + 5000]:
                kept[id(entry.raw)] = entry
            if time.monotonic() - self._paused > FRAME_BUDGET:
                await self._pause(generation)
        seen = set()
        entries = []
        for item in list(self.albums):
            raw_item = item.raw
            # An album's tracks draw the album's cover, as its Groups' Tracks do.
            thumb = item.thumb if _text(raw_item.get('kind')) == 'album' else None
            for number, group in enumerate(_dicts(raw_item.get('groups'))):
                source = (item, number, group.get('play') or {}, thumb)
                for place, raw in enumerate(_entries(group.get('entries'))):
                    track_id = raw.get('id')
                    if track_id in seen:
                        continue
                    seen.add(track_id)
                    entry = kept.get(id(raw))
                    if (entry is None or entry.raw is not raw or isinstance(entry, Track)
                            or entry.place != place or entry.source != source):
                        entry = SongEntry(raw, source, place)
                    entries.append(entry)
            if time.monotonic() - self._paused > FRAME_BUDGET:
                await self._pause(generation)
        # The loose songs after the albums', by id; a loose song held before keeps its entry
        # while its dict is the same, and the dict it holds replaces the new, equal one.
        loose_entries = {}
        for position, raw in enumerate(self._loose):
            track_id = _text(raw.get('id'))
            if not track_id or track_id in seen:
                continue
            seen.add(track_id)
            entry = self._loose_entries.get(track_id)
            if entry is None or entry.raw != raw:
                entry = SongEntry(raw, (None, 0, {'kind': 'song', 'id': track_id}, None))
            else:
                self._loose[position] = entry.raw
            loose_entries[track_id] = entry
            entries.append(entry)
        self._loose_entries = loose_entries
        del kept, seen
        listed = time.monotonic()
        count = len(entries)
        # The store brought to `entries` with the fewest changes, so that the views over it
        # (Songs, Search) keep their rows: most syncs change a few songs, or none. The diff
        # (up to 13 ms over 40,000 songs, splices included) gets a frame of its own, and so
        # does letting go of what it replaced.
        if len(entries) != len(old_entries) or any(
                new is not old for new, old in zip(entries, old_entries, strict=True)):
            old = list(old_entries)
            await self._pause(generation)
            apply_diff(self._songs, entries, old)
            spliced = time.monotonic()
            await self._pause(generation)
            del old, entries
        else:
            spliced = time.monotonic()
        if not self.songs_ready:
            self.songs_ready = True
        log.debug('Songs built in %.0f ms: %d songs (listed in %.0f ms, spliced in %.0f ms: '
                  "the views' sort and rows)", (time.monotonic() - started) * 1000, count,
                  (listed - started) * 1000, (spliced - listed) * 1000)

    def _check(self, generation):
        if generation != self._generation:
            raise _Superseded

    def _set_state(self, state):
        if self.state != state:
            self.state = state


def _album_key(raw):
    """An album's title and artist as holds() matches a catalog album to the library's: case
    and accents ignored; the artist its artistName when it has one (a shelf's album is
    subtitled with its year), else its subtitle."""
    artist = _text(raw.get('artistName')) or _text(raw.get('subtitle')) or ''
    return fold(_text(raw.get('title')) or ''), fold(artist)


def recently_added_order(items, recent):
    """Recently Added: the library's albums, playlists and videos (`items`), newest `added`
    first, ties in the order of Apple's own recently-added list (`recent`, its first hundred,
    the Home shelf's), then by title; those without a date (a loose song's stand-in album)
    last, by title. With no dates at all (a library.json from before them) Apple's list as
    it is."""
    dated, undated = [], []
    for item in items:
        (dated if item.added_seconds() else undated).append(item)
    if not dated:
        return list(recent)
    rank = {id(item): position for position, item in enumerate(recent)}
    last = len(rank)
    # Titles only part ties: a title_key() for every item was most of the sort's time.
    keyed = sorted(((-item.added_seconds(), rank.get(id(item), last), item) for item in dated),
                   key=_without_item)
    dated = []
    start = 0
    while start < len(keyed):
        end = start + 1
        while end < len(keyed) and keyed[end][:2] == keyed[start][:2]:
            end += 1
        if end - start == 1:
            dated.append(keyed[start][2])
        else:
            dated += sorted((entry[2] for entry in keyed[start:end]),
                            key=lambda item: title_key(item.title))
        start = end
    undated.sort(key=lambda item: title_key(item.title))
    return dated + undated


# The id of a genre's Item (genre_items()): the prefix, then the genre's name.
GENRE_PREFIX = 'genre:'


def genre_items(albums):
    """The Genres page's Item dicts, one for each genre the albums (Items) have, by name
    (title_key()): {id, kind 'genre', title (the name), subtitle ("3 albums"), albumCount,
    thumb and art (its first album's that has a cover)}. An album's genre is its `genre`,
    the first of Apple's genreNames; an album without one is in no genre. Albums are read in
    their order, by their raw dicts (no property calls)."""
    found = {}  # name -> [count, the first album dict with a cover, or None]
    for album in albums:
        raw = album.raw
        name = _text(raw.get('genre'))
        name = name.strip() if name else ''
        if not name:
            continue
        entry = found.get(name)
        if entry is None:
            entry = found[name] = [0, None]
        entry[0] += 1
        if entry[1] is None and (raw.get('thumb') or raw.get('art')):
            entry[1] = raw
    items = []
    for name in sorted(found, key=title_key):
        count, cover = found[name]
        cover = cover or {}
        items.append({'id': GENRE_PREFIX + name, 'kind': 'genre', 'title': name,
                      'subtitle': albums_text(count), 'albumCount': count,
                      'thumb': _text(cover.get('thumb')), 'art': _text(cover.get('art'))})
    return items


def _without_item(entry):
    return entry[:2]


def _runs(positions):
    """Ascending positions as runs of consecutive ones: [(start, end)], end excluded."""
    runs = []
    for position in positions:
        if runs and runs[-1][1] == position:
            runs[-1][1] = position + 1
        else:
            runs.append([position, position + 1])
    return [(start, end) for start, end in runs]


def _song_index(entries):
    """{id or catalog id: the library id} of the track entries, the first of each kept."""
    ids = {}
    keep = ids.setdefault
    for entry in entries:
        library_id = entry.get('id')
        if library_id:
            keep(library_id, library_id)
            catalog_id = entry.get('catalogId')
            if catalog_id:
                keep(catalog_id, library_id)
    return ids


class _Pause:
    """A paused_gc entered when made and left once: by leave() as its load ends, or, should
    its load's coroutine be closed before it ever ran (the first load of an app that was
    never activated), as the coroutine lets it go, so the collector is not left paused."""

    def __init__(self, freeze):
        self._left = True  # until entered
        self._context = paused_gc(freeze)
        self._context.__enter__()
        self._left = False

    def leave(self):
        if not self._left:
            self._left = True
            self._context.__exit__(None, None, None)

    def __del__(self):
        self.leave()
