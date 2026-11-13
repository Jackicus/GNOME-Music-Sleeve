# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What each item action takes of an object, and whether it applies: an Item's or a
Track's (kind, id) target for playing, queueing, rating, adding and removing, and the tests a
menu makes before it offers an action. Pure functions over the library's Items and Tracks:
actions.py runs the actions, item_menu.py offers them.
"""

from . import related
from .backend import api
from .backend.api import is_library_id
from .library import (REMOVABLE, ROOT_FOLDER, TRACK_KINDS, TRACK_REF_KINDS, Item, ItemRefs,
                      Track, track_ref)

# The songs one queue command (Play Next, Play Later of several) sends at most.
QUEUE_BATCH = 100

# Ids the library makes up for what Apple gave none (backend.normalize groups songs into albums
# and artists): nothing of Apple's answers to them.
SYNTHETIC_PREFIXES = ('l.alb_', 'l.art_')
QUEUE_KINDS = ('album', 'playlist')
# The Items whose songs Add to Playlist and a drop on a sidebar playlist add, all of them.
SOURCE_KINDS = ('album', 'playlist')
RATED_KINDS = ('album', 'playlist', 'station', 'video')
LIBRARY_KINDS = ('song', 'album', 'playlist', 'video')


def pre_adds(obj):
    """Whether Add to Library pre-adds obj: an album not out yet (Item.prerelease, Apple's
    isPrerelease), whose songs come into the library as they come out."""
    return isinstance(obj, Item) and obj.kind == 'album' and obj.prerelease


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


def is_curator(obj):
    """Whether obj is an Apple curator's tile (kind 'category': a genre's page, a radio
    show), which opens its page: Apple gives a curator no playParams, so nothing plays it,
    queues it or favourites it."""
    return isinstance(obj, Item) and obj.kind == 'category' and bool(obj.id)


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
