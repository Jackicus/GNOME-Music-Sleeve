# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Which tracks of a list are selected, in a track list's selection mode (docs/decisions.md):
the Track objects themselves (or what `key` knows them by), not a Gtk.MultiSelection's
positions.

    selection = Selection(key=None)
    selection.start()                     # the mode on (`active`), nothing selected
    selection.toggle(track)               # selected or not; the anchor of a range
    selection.extend(shown, track)        # from the anchor to track, in `shown`'s order
    selection.select_all(shown)           # every track shown; select_none()
    selection.keep(shown)                 # what a filter hides leaves the selection
    selection.has(track)                  # in a bind: one set lookup
    selection.ordered(shown)              # the selected, in the order shown
    selection.stop()                      # the mode off, the selection cleared

`shown` is any iterable of the Tracks a list shows, in its order. Why not a selection model:
GTK selects the hovered row of a single-click list (the lists play on a single click and
select nothing, `Gtk.NoSelection`); a Gtk.MultiSelection keeps positions, which the Songs
table's and a playlist's filters replace at every key (inserted, then the old removed: the
rows recycled), so the selection would go with each; and its Select All would take a detail
page's hero and footer rows. A Library reload keeps its Track objects, so they are stable
keys, and a song a playlist holds twice is two Tracks, each selected by itself. The Songs
table's list holds the library's songs as SongEntries and binds their Tracks to its rows:
its Selection's `key` is library.song_key, which knows an entry and its Track as one song,
so that Select All of 40,000 songs makes no Track.

`changed` is emitted after every change of the selected set or of `active`.

Picks is the songs Add Songs… (dialogs/add_songs.py) has picked for a playlist from lists
that come and go (the library's songs, each search's): kept by what a playlist add takes
(library.track_ref(): the song's kind and id), so a song is picked once wherever it shows, in
the order picked, which is the order they are added in.

    picks = Picks()
    picks.toggle(obj)                     # picked, or not any more; False for no song
    picks.has(obj); picks.count; picks.objects()

GObject only, no GTK: tests/test_selection.py.
"""

from gi.repository import GObject

from .library import track_ref


class Selection(GObject.Object):
    """The selected tracks of one list: see the module. `changed` after every change.

    `key(obj)`, when given, is what a track is selected by (by default the object itself):
    the Songs table's list holds SongEntries and its rows their Tracks, both known by
    library.song_key(); ordered() answers the elements of `shown`, whichever of the two
    selected them."""

    __gtype_name__ = 'AppleMusicSelection'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, key=None):
        super().__init__()
        self._key = key if key is not None else _itself
        self._active = False
        self._selected = {}  # key -> the track selected
        self._anchor = None  # the key of the track a Shift range starts from: the last toggled

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
    def active(self):
        """Whether the list is in its selection mode."""
        return self._active

    @property
    def count(self):
        """How many tracks are selected."""
        return len(self._selected)

    def has(self, track):
        """Whether track is selected."""
        return self._key(track) in self._selected

    def start(self):
        """Turn the mode on, nothing selected (nothing when it is on already)."""
        if self._active:
            return
        self._active = True
        self._selected.clear()
        self._anchor = None
        self.notify('active')
        self.emit('changed')

    def stop(self):
        """Turn the mode off, the selection cleared (nothing when it is off)."""
        if not self._active:
            return
        self._active = False
        self._selected.clear()
        self._anchor = None
        self.notify('active')
        self.emit('changed')

    def toggle(self, track):
        """Select track, or unselect it when it is selected; it is the anchor of the next
        range either way. The mode is turned on first when it is off."""
        self.start()
        key = self._key(track)
        if key in self._selected:
            del self._selected[key]
        else:
            self._selected[key] = track
        self._anchor = key
        self.emit('changed')

    def extend(self, shown, track):
        """Select the tracks from the anchor to track (both included) in `shown`'s order,
        keeping what is selected besides; with no anchor shown, track alone (and it is the
        anchor). The anchor stays where it was, so a second Shift+click reaches from it
        again. Nothing for a track not shown."""
        self.start()
        tracks = list(shown)
        keys = [self._key(element) for element in tracks]
        key = self._key(track)
        if key not in keys:
            return
        if self._anchor is None or self._anchor not in keys:
            self._anchor = key
        start, end = keys.index(self._anchor), keys.index(key)
        low, high = min(start, end), max(start, end)
        self._selected.update(zip(keys[low:high + 1], tracks[low:high + 1], strict=True))
        self.emit('changed')

    def select_all(self, shown):
        """Select every track shown (the mode turned on first)."""
        self.start()
        key = self._key
        self._selected = {key(element): element for element in shown}
        self.emit('changed')

    def select_none(self):
        """Unselect everything, the mode staying on."""
        if not self._selected:
            return
        self._selected.clear()
        self._anchor = None
        self.emit('changed')

    def keep(self, shown):
        """Keep only the selected tracks still shown (a filter's change, a sync that took
        some away): an action never reaches a song the list does not show. True when that
        changed the selection."""
        if not self._selected:
            return False
        key = self._key
        kept = {key(element) for element in shown}.intersection(self._selected)
        if len(kept) == len(self._selected):
            return False
        self._selected = {name: track for name, track in self._selected.items()
                          if name in kept}
        if self._anchor is not None and self._anchor not in kept:
            self._anchor = None
        self.emit('changed')
        return True

    def ordered(self, shown):
        """The selected tracks in `shown`'s order: the elements of `shown` selected."""
        selected = self._selected
        if not selected:
            return []
        key = self._key
        return [element for element in shown if key(element) in selected]


def _itself(obj):
    return obj


class Picks(GObject.Object):
    """The songs picked to add to a playlist: see the module. `changed` after every change."""

    __gtype_name__ = 'AppleMusicPicks'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self._picked = {}  # (kind, id) -> the object picked, in the order picked

    @staticmethod
    def key(obj):
        """What a song is picked by: (kind, id) as a playlist add takes it, or None for
        anything that is no song or music video."""
        ref = track_ref(obj)
        return (ref.kind, ref.id) if ref is not None else None

    @property
    def count(self):
        return len(self._picked)

    def has(self, obj):
        key = self.key(obj)
        return key is not None and key in self._picked

    def toggle(self, obj):
        """Pick obj, or unpick it (the one picked by its key, from whichever list); False,
        and nothing changes, for what is no song."""
        key = self.key(obj)
        if key is None:
            return False
        if key in self._picked:
            del self._picked[key]
        else:
            self._picked[key] = obj
        self.emit('changed')
        return True

    def objects(self):
        """What was picked, in the order picked."""
        return list(self._picked.values())
