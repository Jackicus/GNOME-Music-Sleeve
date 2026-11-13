# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Which tracks of a list are selected, in a track list's selection mode (docs/decisions.md):
known by what `key` makes of them (the song's id), not as a Gtk.MultiSelection's positions.

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
page's hero and footer rows.

Nor are the Track objects the keys: a reload that changes an album or a playlist gives it
new Tracks and records (Item.merge(), `groups-changed`; the Songs store's entries follow),
and keep() would take every selected song of it for one no longer shown (#574). A song is
selected by its id (library.selection_key), which a reload keeps: the Songs table's list
holds the library's songs, each id once, as SongEntries and binds their Tracks to its rows,
and the key knows an entry and its Track as one song, so that Select All of 40,000 songs
makes no Track. A detail page's list may hold a song twice (a playlist): its key is
Places.key(), the song's id and which of its entries in the list it is (the first, the
second…), so each entry is selected by itself and keeps its selection when songs come or go
around it. What a reload took out of the list leaves the selection at the page's prune(),
as a filter's change does.

    places = Places(tracks)               # tracks(): every track of the list, unfiltered
    selection = Selection(places.key)
    places.forget()                       # the list's tracks changed: worked out again

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

from .library import selection_key, track_ref


class Selection(GObject.Object):
    """The selected tracks of one list: see the module. `changed` after every change.

    `key(obj)`, when given, is what a track is selected by (by default the object itself):
    library.selection_key (the Songs table: its list holds SongEntries and its rows their
    Tracks, both known by their song's id) or a Places' key (a detail page's); ordered()
    answers the elements of `shown`, whichever of them selected them."""

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
        """Whether track is selected (no key worked out while nothing is)."""
        return bool(self._selected) and self._key(track) in self._selected

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


class Places:
    """A detail page's selection key (see the module): `tracks()` answers every track of its
    list, unfiltered, in order, and a track is known by (its song's id, which of that song's
    entries it is: 0 for the first). Only songs the list holds more than once need the
    second part worked out, from `tracks()` at the first key asked for after forget()."""

    def __init__(self, tracks):
        self._tracks = tracks
        self._repeats = None  # id(record) -> its place among its song's entries, when not 0

    def forget(self):
        """The list's tracks changed: the places are worked out again when next asked."""
        self._repeats = None

    def key(self, track):
        repeats = self._repeats
        if repeats is None:
            repeats = self._repeats = self._find_repeats()
        return (selection_key(track), repeats.get(id(track.raw), 0) if repeats else 0)

    def _find_repeats(self):
        seen = {}
        repeats = {}
        for track in self._tracks() or ():
            song = selection_key(track)
            place = seen.get(song, 0)
            if place:
                repeats[id(track.raw)] = place
            seen[song] = place + 1
        return repeats


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
