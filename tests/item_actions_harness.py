# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the item actions' tests share (test_actions.py, test_item_menu.py,
test_playlist_actions.py and the others of applemusic.actions' modules): invented items in the
library's shapes, helpers that read a Gio.Menu, and stand-ins for the engine, the player, the
library, the application and the window ItemActions is given."""

import asyncio

from gi.repository import Gio, GObject

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.backend.errors import EngineError
from applemusic.library import Item, PlaylistTree, Track, apply_changes
from applemusic.player import NowPlaying


# Invented items, in the library's shapes.
LIBRARY_ALBUM = Item({'id': 'l.alb1', 'kind': 'album', 'title': 'Tidewater',
                      'subtitle': 'The Invented Band', 'play': {'kind': 'album', 'id': 'l.alb1'}})
MADE_UP_ALBUM = Item({'id': 'l.alb_0123456789ab', 'kind': 'album', 'title': 'Loose Ends',
                      'play': {'kind': 'album', 'id': 'l.alb_0123456789ab'}})
CATALOG_ALBUM = Item({'id': '1000000002', 'kind': 'album', 'title': 'Harbour Suite',
                      'url': 'https://music.apple.com/gb/album/harbour-suite/1000000002',
                      'play': {'kind': 'album', 'id': '1000000002'}})
LIBRARY_ARTIST = Item({'id': 'l.art_0123456789ab', 'kind': 'artist', 'title': 'The Band',
                       'play': {'kind': 'artist', 'id': 'l.art_0123456789ab'}})
CATALOG_ARTIST = Item({'id': '1000000005', 'kind': 'artist', 'title': 'Someone',
                       'play': {'kind': 'artist', 'id': '1000000005'}})
STATION = Item({'id': 'ra.1000000006', 'kind': 'station', 'title': 'Harbour Radio',
                'url': 'https://music.apple.com/gb/station/harbour-radio/ra.1000000006',
                'play': {'kind': 'station', 'id': 'ra.1000000006'}})
CATALOG_SONG = Item({'id': '1000000007', 'kind': 'song', 'title': 'Pilot Light',
                     'catalogId': '1000000007', 'play': {'kind': 'song', 'id': '1000000007'}})
CATALOG_VIDEO = Item({'id': '1000000012', 'kind': 'video', 'title': 'Pilot Light (Video)',
                      'play': {'kind': 'musicVideo', 'id': '1000000012'}})
FOLDER = Item({'id': 'l.fd1', 'kind': 'folder', 'title': 'Evenings'})
SHOW = Item({'id': '1000000009', 'kind': 'category', 'title': 'The Invented Hour',
             'subtitle': 'Rowan Vale',
             'url': 'https://music.apple.com/gb/curator/the-invented-hour/1000000009'})
PLAYLIST = Item({'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip',
                 'play': {'kind': 'playlist', 'id': 'p.pl1'}})
READ_ONLY = Item({'id': 'p.pl2', 'kind': 'playlist', 'title': 'Apple Picks',
                  'attributes': {'canEdit': False}, 'play': {'kind': 'playlist', 'id': 'p.pl2'}})
FAVOURITES = Item({'id': 'p.fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                   'attributes': {'isFavourites': True},
                   'play': {'kind': 'playlist', 'id': 'p.fav'}})
LIBRARY_TRACK = Track({'id': 'i.song1', 'catalogId': '1000000001', 'title': 'Harbour Lights',
                       'type': 'library-songs', 'index': 2},
                      play={'kind': 'album', 'id': 'l.alb1'})
CATALOG_TRACK = Track({'id': '1000000009', 'catalogId': '1000000009', 'title': 'Shoreline',
                       'index': 0}, play={'kind': 'album', 'id': '1000000002'})
UPLOAD_TRACK = Track({'id': 'i.song2', 'title': 'Demo Take', 'index': 0},
                     play={'kind': 'playlist', 'id': 'p.pl1'})
VIDEO_TRACK = Track({'id': 'i.vid1', 'catalogId': '1000000011', 'title': 'Harbour Lights (Live)',
                     'type': 'library-music-videos', 'index': 3},
                    play={'kind': 'playlist', 'id': 'p.pl1'})

# The library's artist of LIBRARY_ALBUM, as the library makes artists up from albums.
# A pre-release album and one of its songs not out yet (no playParams: `unreleased`).
UPCOMING_ALBUM = Item({'id': '1000000060', 'kind': 'album', 'title': 'Harbour Lights To Come',
                       'prerelease': True, 'releaseDate': '2099-12-04',
                       'play': {'kind': 'album', 'id': '1000000060'}})

BAND = Item({'id': 'l.art_00000000band', 'kind': 'artist', 'title': 'The Invented Band',
             'play': {}})

# A library artist of songs the library has no album for: their group holds the songs.
LOOSE_ARTIST = Item({'id': 'l.art_00000000lose', 'kind': 'artist', 'title': 'Loose Ends Trio',
                     'play': {'kind': 'artist', 'id': 'l.art_00000000lose'},
                     'groups': [{'name': 'Loose Ends',
                                 'play': {'kind': 'album', 'id': 'l.alb_0123456789ab'},
                                 'entries': [{'id': 'i.song7', 'catalogId': '1000000050',
                                              'title': 'Drift',
                                              'artist': 'Loose Ends Trio'}]}]})

# What the engine's item() answers for a playlist: the Item's shape with its groups.
PLAYLIST_ANSWER = {'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip', 'trackCount': 1,
                   'play': {'kind': 'playlist', 'id': 'p.pl1'},
                   'groups': [{'title': '', 'entries': [
                       {'id': 'i.song1', 'title': 'Harbour Lights', 'type': 'library-songs'}]}]}


def actions_of(menu):
    """[(action, target)] of a menu's items, sections and submenus flattened, in order."""
    found = []
    for position in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_ACTION)
        if action is not None:
            target = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_TARGET)
            found.append((action.get_string(), target.unpack() if target else None))
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(position, link)
            if linked is not None:
                found.extend(actions_of(linked))
    return found


def names(menu):
    return [action for action, _target in actions_of(menu)] if menu is not None else None


def labels_of(menu):
    """The labels of a menu's items, sections and submenus flattened, in order."""
    found = []
    for position in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        if label is not None:
            found.append(label.unpack())
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(position, link)
            if linked is not None:
                found.extend(labels_of(linked))
    return found


def levels_of(menu):
    """The labels of each level of a menu, as a Gtk.PopoverMenu shows them one at a time:
    [the menu's items and sections, then each submenu's level, depth first]."""
    level, below = [], []

    def walk(model):
        for position in range(model.get_n_items()):
            label = model.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
            if label is not None:
                level.append(label.unpack())
            section = model.get_item_link(position, Gio.MENU_LINK_SECTION)
            if section is not None:
                walk(section)
            submenu = model.get_item_link(position, Gio.MENU_LINK_SUBMENU)
            if submenu is not None:
                below.extend(levels_of(submenu))

    walk(menu)
    return [level, *below]


def mnemonic_clashes(menu, names=()):
    """The levels of a menu (levels_of()) where two labels share a mnemonic; the labels in
    `names` (a playlist's, a folder's: underscores no mnemonics) left out."""
    clashes = []
    for level in levels_of(menu):
        letters = [label[label.index('_') + 1].lower() for label in level
                   if '_' in label and '__' not in label and label not in names]
        if len(letters) != len(set(letters)):
            clashes.append(level)
    return clashes


def submenu_of(menu, label):
    """The submenu labelled `label` among a menu's items and sections, or None."""
    for position in range(menu.get_n_items()):
        found = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        submenu = menu.get_item_link(position, Gio.MENU_LINK_SUBMENU)
        if submenu is not None and found is not None and found.unpack() == label:
            return submenu
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        inside = submenu_of(section, label) if section is not None else None
        if inside is not None:
            return inside
    return None


class FakeEngine(GObject.Object):
    """The Engine's surface the actions use: state, authorized, the `rated` signal, and the
    writes, recorded (nothing is sent anywhere)."""

    __gsignals__ = {
        'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
    }

    state = GObject.Property(type=str, default='up')
    authorized = GObject.Property(type=bool, default=True)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail = None
        self.ratings = {}
        self.favourite_artists = set()  # the catalog artists is_favourite_artist() says are
        self.catalog_urls = {}
        self.catalog_artists = {}  # a library artist's name -> catalog_artist()'s answer
        self.items = {}  # (kind, id) -> the Item dict item() answers
        self.related_answers = {}  # (kind, id) -> related()'s answer
        self.listings = []  # folder_children()'s answers, one per call; then none
        self.moving = None  # an asyncio.Event move_to_folder() waits for, when set
        self.adding = None  # an asyncio.Event add_tracks_to_playlist() waits for, when set
        self.still_listed = []  # in_library()'s answers, one per call; then False

    async def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail is not None:
            raise self.fail

    async def love(self, kind, item_id):
        await self._record('love', kind, item_id)
        self.emit('rated', kind, item_id, 1)

    async def unlove(self, kind, item_id):
        await self._record('unlove', kind, item_id)
        self.emit('rated', kind, item_id, 0)

    async def suggest_less(self, kind, item_id):
        await self._record('suggest_less', kind, item_id)
        self.emit('rated', kind, item_id, -1)

    async def favourite_artist(self, artist_id):
        await self._record('favourite_artist', artist_id)
        self.emit('rated', 'artist', artist_id, 1)

    async def unfavourite_artist(self, artist_id):
        await self._record('unfavourite_artist', artist_id)
        self.emit('rated', 'artist', artist_id, 0)

    async def is_favourite_artist(self, artist_id):
        await self._record('is_favourite_artist', artist_id)
        favourite = artist_id in self.favourite_artists
        self.emit('rated', 'artist', artist_id, 1 if favourite else 0)
        return favourite

    async def rating(self, kind, item_id):
        await self._record('rating', kind, item_id)
        value = self.ratings.get((kind, item_id), 0)
        self.emit('rated', kind, item_id, value)
        return value

    async def add_to_library(self, kind, item_id):
        await self._record('add_to_library', kind, item_id)

    async def add_to_playlist(self, playlist_id, song_id, kind='song'):
        await self._record('add_to_playlist', playlist_id, song_id, kind)

    async def add_tracks_to_playlist(self, playlist_id, tracks):
        if self.adding is not None:
            await self.adding.wait()
        await self._record('add_tracks_to_playlist', playlist_id, tuple(tracks))
        return len(tracks)

    async def catalog_artist(self, name, song_ids):
        await self._record('catalog_artist', name, tuple(song_ids))
        return self.catalog_artists.get(name)

    async def catalog_url(self, kind, item_id):
        await self._record('catalog_url', kind, item_id)
        return self.catalog_urls.get(item_id)

    async def create_folder(self, name, folder_id=None):
        await self._record('create_folder', name, folder_id)
        return 'p.fdnew'

    async def move_to_folder(self, kind, item_id, folder_id=None):
        if self.moving is not None:
            await self.moving.wait()
        await self._record('move_to_folder', kind, item_id, folder_id)

    async def related(self, kind, item_id):
        await self._record('related', kind, item_id)
        return self.related_answers.get((kind, item_id), {'album': None, 'artists': []})

    async def create_playlist(self, name, description='', tracks=(), folder_id=None,
                              public=False):
        # A public one's call says so; the others' as they were.
        await self._record('create_playlist', name, description, tuple(tracks), folder_id,
                           *(('public',) if public else ()))
        return 'p.new'

    async def edit_playlist(self, playlist_id, name=None, description=None, public=None):
        await self._record('edit_playlist', playlist_id, name, description,
                           *(() if public is None else (public,)))

    async def delete_playlist(self, playlist_id):
        await self._record('delete_playlist', playlist_id)

    async def remove_from_library(self, kind, item_id):
        await self._record('remove_from_library', kind, item_id)
        return item_id

    async def in_library(self, kind, library_id):
        self.calls.append(('in_library', kind, library_id))
        return bool(self.still_listed and self.still_listed.pop(0))

    async def remove_from_playlist(self, playlist_id, track_id, index=None):
        await self._record('remove_from_playlist', playlist_id, track_id, index)
        return True

    async def reorder_playlist(self, playlist_id, shown, order):
        await self._record('reorder_playlist', playlist_id, tuple(shown), tuple(order))

    async def remove_playlist_entries(self, playlist_id, shown, positions):
        await self._record('remove_playlist_entries', playlist_id, tuple(shown),
                           tuple(positions))
        return [{'id': track_id, 'type': 'library-songs'} for track_id in shown]

    async def put_back_playlist_entries(self, playlist_id, kept, entries):
        await self._record('put_back_playlist_entries', playlist_id, tuple(kept),
                           tuple(entry['id'] for entry in entries))

    async def playlist_track_ids(self, playlist_id):
        self.calls.append(('playlist_track_ids', playlist_id))
        return []

    async def rename_folder(self, folder_id, name):
        await self._record('rename_folder', folder_id, name)

    async def delete_folder(self, folder_id):
        await self._record('delete_folder', folder_id)

    async def folder_children(self, folder_id=None):
        self.calls.append(('folder_children', folder_id))
        if self.listings:
            listing = self.listings.pop(0)
            if isinstance(listing, Exception):
                raise listing
            return listing
        return []

    async def item(self, kind, item_id):
        await self._record('item', kind, item_id)
        answer = self.items.get((kind, item_id))
        if answer is None:
            raise EngineError('api', f'item not found: {kind} {item_id}')
        return answer


class FakePlayer:
    def __init__(self, engine):
        self.engine = engine
        self.ensured = 0
        # An invented queue of six, the second playing: Up Next's moves name its entries.
        self.queue = Gio.ListStore(item_type=NowPlaying)
        for number in range(6):
            self.queue.append(NowPlaying({'id': f'i.q{number}', 'title': f'Entry {number}',
                                          'type': 'song', 'index': number}))
        self.queue_index = 1

    async def ensure_engine(self):
        self.ensured += 1

    async def play_next(self, kind, item_id):
        await self.engine._record('play_next', kind, item_id)

    async def play_later(self, kind, item_id):
        await self.engine._record('play_later', kind, item_id)

    async def remove_from_queue(self, index, entry_id):
        await self.engine._record('remove_from_queue', index, entry_id)
        return entry_id != 'i.gone'

    async def move_in_queue(self, index, to_index, entry_id):
        await self.engine._record('move_in_queue', index, to_index, entry_id)
        if entry_id == 'i.gone':
            return False
        entries = list(self.queue)
        entries.insert(to_index, entries.pop(index))
        self.queue.splice(0, len(entries), entries)
        for position, entry in enumerate(entries):
            entry.index = position
        return True


class FakeLibrary:
    storefront = 'gb'

    def __init__(self, items, folders=()):
        self.items = {(item.kind, item.id): item for item in items}
        self.playlists = [item for item in items if item.kind == 'playlist']
        self.albums = [item for item in items if item.kind == 'album']
        self.artists = [item for item in items if item.kind == 'artist']
        self.folders = list(folders)
        self.changes = []  # hold()'s TreeChanges, as Library keeps them
        self.tree = PlaylistTree(folders, self.playlists)
        for node in self.tree.folders():
            self.items[('folder', node.id)] = node.item
        self.placed = 0
        self.released = []
        self.hidden = []  # ('hide' or 'unhide', the refs), in order
        self.held = {}  # playlist id -> its order held (reorder())
        self.tracks_kept = []  # ('hold' or 'release', playlist id), in order
        self.noted = []  # note_added()'s Items
        self.twins = {}  # (kind, catalog id): the library's album or playlist found for it
        self.favourite_ids = set()  # what set_favourites() made favourites
        self.favourites_set = []  # (favourite, the ids) per set_favourites()

    def set_favourites(self, item_ids, favourite):
        ids = set(item_ids)
        self.favourites_set.append((favourite, ids))
        if favourite:
            self.favourite_ids |= ids
        else:
            self.favourite_ids -= ids
        return bool(ids)

    def note_added(self, item):
        self.noted.append(item)

    def hold_tracks(self, playlist_id):
        self.tracks_kept.append(('hold', playlist_id))

    def release_tracks(self, playlist_id):
        self.tracks_kept.append(('release', playlist_id))

    def held_item(self, item):
        """As Library.held_item: the library's own album or playlist that item is found as
        (itself, or its twin), None for one only noted."""
        if item.kind not in ('album', 'playlist'):
            return None
        return self.items.get((item.kind, item.id)) or self.twins.get((item.kind, item.id))

    def holds(self, item):
        """As Library.holds: found, or noted as just added."""
        return self.held_item(item) is not None or any(
            (noted.kind, noted.id) == (item.kind, item.id) for noted in self.noted)

    def hold(self, change):
        self.changes.append(change)
        self._replant()
        return True

    def release(self, change):
        self.released.append(change)
        if change in self.changes:
            self.changes.remove(change)
            self._replant()

    def _replant(self):
        existing = {key: item for key, item in self.items.items() if key[0] == 'folder'}
        self.tree = PlaylistTree(apply_changes(self.folders, self.changes), self.playlists,
                                 existing)
        for node in self.tree.folders():
            self.items[('folder', node.id)] = node.item

    def by_id(self, kind, item_id):
        return self.items.get((kind, item_id))

    def library_id(self, kind, item_id, catalog_id=None):
        """As Library.library_id: a song by the albums' tracks' ids and catalog ids."""
        if kind == 'song':
            for album in self.albums:
                for group in album.raw.get('groups') or []:
                    for entry in group.get('entries') or []:
                        if item_id in (entry.get('id'), entry.get('catalogId')) or (
                                catalog_id and catalog_id == entry.get('catalogId')):
                            return entry.get('id')
            return None
        item = self.items.get((kind, item_id))
        return item.id if item is not None else None

    def playlists_holding(self, ids):
        return [playlist.id for playlist in self.playlists
                if any(entry.get('id') in ids or entry.get('catalogId') in ids
                       for group in playlist.raw.get('groups') or []
                       for entry in group.get('entries') or [])]

    def hide(self, refs):
        self.hidden.append(('hide', set(refs)))
        return asyncio.sleep(0)  # Library.hide's reload

    def unhide(self, refs):
        self.hidden.append(('unhide', set(refs)))
        return asyncio.sleep(0)

    def playlist_tree(self):
        return self.tree

    def place_playlists(self):
        self.placed += 1

    def favourite_songs(self):
        return next((item for item in self.playlists if item.favourites), None)

    def reorder(self, item, order):
        # Library.reorder()'s, the order held as it holds it.
        if not item.reorder(order):
            return False
        self.held[item.id] = item.track_ids()
        return True

    def release_order(self, playlist_id):
        self.held.pop(playlist_id, None)

    def with_held_order(self, raw):
        return raw


class FakeApp:
    def account_key(self, name):
        return name  # the release build's keys

    def __init__(self):
        self.engine = FakeEngine()
        self.player = FakePlayer(self.engine)
        # The playlists are this test's own: an add merges the engine's answer into them.
        self.playlist = Item(dict(PLAYLIST.raw))
        self.favourites = Item(dict(FAVOURITES.raw))
        self.library = FakeLibrary([LIBRARY_ALBUM, CATALOG_ALBUM, self.playlist, READ_ONLY,
                                    self.favourites, BAND])
        self.demo = False
        self.tasks = []
        self.reported = []
        self.toasts = []
        self.buttons = []  # (label, action, target) of the toasts' buttons
        self.syncs = []  # (quick,) per start_sync, ('tracks', ids) for a tracks pass
        self.library_sync = None

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    def report(self, error):
        self.reported.append(error.code)

    def toast(self, title, button_label=None, action_name=None, action_target=None):
        self.toasts.append(title)
        if button_label:
            self.buttons.append((button_label, action_name,
                                 action_target.unpack() if action_target else None))

    def start_sync(self, quick=False, playlists=False, videos=False, tracks_of=()):
        if playlists and tracks_of:
            self.syncs.append(('tracks', tuple(tracks_of)))
        elif videos or tracks_of:
            self.syncs.append(('quick', videos, tuple(tracks_of)))
        else:
            self.syncs.append('playlists' if playlists else quick)
        return None

    def refuse_in_demo(self):
        if self.demo:
            self.toast('Not available with the demo library')
        return self.demo


class FakeClipboard:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class FakeWindow:
    def __init__(self):
        self.actions = {}
        self.played = []
        self.opened = []
        self.artist_pages = []  # the artists in `opened` that open_artist_page() opened
        self.shown = None  # the Item of the page shown
        self.clipboard = FakeClipboard()
        self.left = []  # leave()'s (gone, parent)
        self.selected = []  # select_page()'s keys
        self.announced = []  # what assistive technology was told

    def leave(self, gone, parent=None):
        self.left.append((gone, parent))

    def announce(self, message, _priority):
        self.announced.append(message)

    def select_page(self, key):
        self.selected.append(key)

    def open_item(self, item):
        self.opened.append(item)

    def open_artist_page(self, item):
        # Apple Music's page of an artist: in `opened` too, in the order pages opened.
        self.opened.append(item)
        self.artist_pages.append(item)

    def shown_item(self):
        return self.shown

    def add_action(self, action):
        self.actions[action.get_name()] = action

    def play_request(self, play, start_with=None, shuffle=None, start_id=None):
        self.played.append((play, start_with))

    def get_clipboard(self):
        return self.clipboard


# A library album with its tracks, a music video and a playlist of Apple's that may not be
# removed, for Remove from Library.
HELD_ALBUM = Item({'id': 'l.alb2', 'kind': 'album', 'title': 'Low Tide',
                   'play': {'kind': 'album', 'id': 'l.alb2'},
                   'groups': [{'name': 'Disc 1', 'play': {'kind': 'album', 'id': 'l.alb2'},
                               'entries': [
                                   {'id': 'i.song3', 'catalogId': '1000000021',
                                    'title': 'Undertow', 'type': 'library-songs'},
                                   {'id': 'i.song4', 'catalogId': '1000000022',
                                    'title': 'Slack Water', 'type': 'library-songs'}]}]})
LONE_ALBUM = Item({'id': 'l.alb3', 'kind': 'album', 'title': 'Single File',
                   'play': {'kind': 'album', 'id': 'l.alb3'},
                   'groups': [{'name': 'Disc 1', 'play': {'kind': 'album', 'id': 'l.alb3'},
                               'entries': [{'id': 'i.song5', 'catalogId': '1000000023',
                                            'title': 'Alone', 'type': 'library-songs'}]}]})
LIBRARY_VIDEO = Item({'id': 'i.vid2', 'kind': 'video', 'title': 'Undertow (Video)',
                      'catalogId': '1000000024',
                      'play': {'kind': 'musicVideo', 'id': '1000000024'}})
# A playlist of the user's holding the album's first song (by its catalog id) and the video.
HOLDING = Item({'id': 'p.pl4', 'kind': 'playlist', 'title': 'Undertows',
                'play': {'kind': 'playlist', 'id': 'p.pl4'},
                'groups': [{'name': 'Tracks', 'play': {'kind': 'playlist', 'id': 'p.pl4'},
                            'entries': [{'id': 'i.plt1', 'catalogId': '1000000021',
                                         'title': 'Undertow', 'type': 'library-songs'},
                                        {'id': 'i.vid2', 'catalogId': '1000000024',
                                         'title': 'Undertow (Video)',
                                         'type': 'library-music-videos'}]}]})


# A playlist of Apple's catalog: READ_ONLY is the library's copy of it once added.
CATALOG_PLAYLIST = Item({'id': 'pl.0123456789abcdef', 'kind': 'playlist',
                         'title': 'Apple Picks',
                         'play': {'kind': 'playlist', 'id': 'pl.0123456789abcdef'}})


def track_of(item, position):
    """The Track at `position` of an Item's first group, as its page shows it."""
    group = item.raw['groups'][0]
    return Track(group['entries'][position], play=group['play'])
