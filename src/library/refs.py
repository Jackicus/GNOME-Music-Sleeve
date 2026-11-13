# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What a drag inside the app carries: Refs to library objects, and ItemRefs."""

import collections

from gi.repository import GObject

from .objects import Item, Track


# One library object a drag carries (ItemRefs): its `kind` ('song', 'video', 'album',
# 'playlist', 'folder', 'station'…), the `id` the writes take (a track's own id, a library
# "i." one else a catalog one; an Item's id), its `title`, and for a track its `index`, its
# place in the list it was dragged from (Track.index), else -1.
Ref = collections.namedtuple('Ref', 'kind id title index', defaults=(-1,))

# The kinds of Ref a playlist takes, and those a folder takes.
TRACK_REF_KINDS = ('song', 'video')
CONTAINER_REF_KINDS = ('playlist', 'folder')
# The Items a drag may carry besides songs and videos.
DRAGGABLE_KINDS = ('album', 'playlist', 'folder', 'station')


def track_ref(obj):
    """The Ref of a Track (a video by Track.kind), or of a song or music video Item, by its
    own id (a library "i." id, else its catalog id); None for anything else, or for one
    without an id. What Add to Playlist and a drop add."""
    if isinstance(obj, Track):
        kind = obj.kind or 'song'
    elif isinstance(obj, Item) and obj.kind in TRACK_REF_KINDS:
        kind = obj.kind
    else:
        return None
    song_id = obj.id or obj.catalog_id
    if not song_id:
        return None
    return Ref(kind, song_id, obj.title or '', obj.index if isinstance(obj, Track) else -1)


def item_ref(obj):
    """The Ref of anything a drag may carry: a track or a song or video (track_ref()), an
    album, playlist, folder or station Item by its kind and id; None for anything else."""
    ref = track_ref(obj)
    if ref is None and isinstance(obj, Item) and obj.kind in DRAGGABLE_KINDS and obj.id:
        ref = Ref(obj.kind, obj.id, obj.title or '')
    return ref


class ItemRefs(GObject.Object):
    """What a drag inside the app carries: one or more library objects, in order, as Refs.
    The app's one drag type: a track row's drag is an ItemRefs of one 'song' (or 'video')
    Ref, a playlist's or folder's (a sidebar row, a tile) one of that kind.

        refs = ItemRefs.for_objects([track], origin=('playlist', 'p.1'))   # or None
        provider = widgets.dnd.provider(refs)   # the ItemRefs, and its links outward
        refs.refs          # (Ref, …), never empty
        refs.origin        # (kind, id) of the list dragged from, or None
        refs.objects       # the Tracks and Items the refs were made of, in their order
        refs.tracks()      # the songs and videos: what a playlist takes
        refs.containers()  # the playlists and folders: what a folder takes
        refs.only('song', 'video')   # every Ref is of these kinds
        len(refs); list(refs)

    `origin` tells a drop where the drag came from: a playlist's tracks dropped back on the
    same playlist are a reorder, not an add. Only drags that start in the app carry one
    (widgets.dnd.current() is the drag in progress); a drop target takes no other.
    `objects` are what the refs name, for a drop that needs more than a Ref says (the player
    bar queues each by its play target: item_targets.queue_targets()); empty for ItemRefs made
    of Refs alone.
    """

    __gtype_name__ = 'AppleMusicItemRefs'

    def __init__(self, refs=(), origin=None, objects=()):
        super().__init__()
        self.refs = tuple(refs)
        self.origin = tuple(origin) if origin is not None else None
        self.objects = tuple(objects)

    @classmethod
    def for_objects(cls, objects, origin=None):
        """The ItemRefs of `objects` (Tracks, and Items: item_ref()), in order, those that
        cannot be dragged left out; None when none can."""
        pairs = [(ref, obj) for ref, obj in ((item_ref(obj), obj) for obj in objects)
                 if ref is not None]
        if not pairs:
            return None
        return cls([ref for ref, _obj in pairs], origin, [obj for _ref, obj in pairs])

    def tracks(self):
        """The songs and videos, in order: what a playlist takes."""
        return tuple(ref for ref in self.refs if ref.kind in TRACK_REF_KINDS)

    def containers(self):
        """The playlists and folders, in order: what a folder takes."""
        return tuple(ref for ref in self.refs if ref.kind in CONTAINER_REF_KINDS)

    def only(self, *kinds):
        """Whether every Ref is of one of `kinds` (and there is one)."""
        return bool(self.refs) and all(ref.kind in kinds for ref in self.refs)

    def __len__(self):
        return len(self.refs)

    def __iter__(self):
        return iter(self.refs)

    def __bool__(self):
        return bool(self.refs)

    def __repr__(self):
        return f'ItemRefs({list(self.refs)!r}, origin={self.origin!r})'
