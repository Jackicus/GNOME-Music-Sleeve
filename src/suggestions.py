# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What a playlist's page shows of the songs Apple suggests adding to it (pages/detail.py).

music.apple.com shows six at a time out of an answer of twenty, fills an added song's place
from the rest, and on Refresh asks again, telling Apple which songs it has offered and which
were added, so that none of them comes back. The page does the same with Suggestions: six,
or twelve with the `more-suggestions` setting (count()), each answer's first `count` shown
and the rest held as spares (take()); an added song's place filled in place by the next
spare (fill()); a few more asked for (wants_more(), extend()) when the spares run out; and
every song shown remembered as offered, every one added as selected and every one whose
preview was played as previewed (preview()), for the next request.

The answer is kept for a day (Engine.playlist_suggestions) with basis(), a fingerprint of
the songs the playlist held when it was asked: once the playlist holds others (a song added
here or elsewhere, one removed), the next page shown asks Apple again. A page already open
keeps what it shows: an added song's place is filled from the spares, not asked again.

columns_for() is the number of columns the grid of them has at a width: one that divides
the count, so the rows are full (6 as 3 by 2, 2 by 3 or 6 by 1; 12 as 4, 3, 2 or 1 a row).
"""

import hashlib

COUNT = 6  # shown at a time
MORE_COUNT = 12  # with the `more-suggestions` setting
SPARES = 4  # asked for beyond the count, to fill the places of songs added
MAX_COLUMNS = 4


def count(more):
    """How many suggestions a page shows: MORE_COUNT with the setting on, else COUNT."""
    return MORE_COUNT if more else COUNT


def basis(held):
    """A fingerprint of what a playlist holds (`held`, its songs' ids, in any order): the
    same for the same songs, another once one is added or removed."""
    joined = '\n'.join(sorted({str(song_id) for song_id in held if song_id}))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def preview_url(item):
    """The https address of Apple's preview of a suggested song Item (its `previewUrl`,
    normalize.playlist_suggestions()), or None: a song without one plays in full."""
    raw = item.raw if item is not None and isinstance(item.raw, dict) else {}
    url = raw.get('previewUrl')
    return url if isinstance(url, str) and url.startswith('https://') else None


def columns_for(width, total, column_width, spacing=0):
    """The columns of a grid of `total` songs `width` wide, each at least `column_width`
    with `spacing` between them: as many as fit (at most MAX_COLUMNS), less until they
    divide the total; at least one."""
    fit = max(1, (int(width) + spacing) // (column_width + spacing))
    columns = max(1, min(fit, MAX_COLUMNS, total))
    while columns > 1 and total % columns:
        columns -= 1
    return columns


class Suggestions:
    """The suggestions of one playlist, as one page shows them: `shown` (at most `count`
    song Items, in their places), the spares, and the catalog ids `offered` (every song
    shown), `selected` (every song added) and `previewed` (every song whose preview was
    played), in the order they came.

    Every method that takes `held` (the ids of the songs the playlist holds) leaves those
    out of what it shows."""

    def __init__(self, count=COUNT):
        self.count = count
        self.shown = []
        self.spares = []
        self.offered = []
        self.selected = []
        self.previewed = []
        self.exhausted = False  # the last request for more brought none: ask no more
        self._filled = {}  # an added song's id -> (its place, the spare that took it, or None)

    def take(self, items, held=()):
        """A new answer (the first, or a Refresh's): its first `count` songs shown, the
        rest spare, leaving out those already offered (Apple should have), held or added."""
        self.shown = []
        self.spares = self._new(items, held)
        self.exhausted = False
        self._filled = {}
        self._top_up(held)

    def extend(self, items, held=()):
        """A few more (wants_more()'s answer): spares behind those there are, then any empty
        places filled. Whether anything new came."""
        new = self._new(items, held)
        self.spares.extend(new)
        self._top_up(held)
        return bool(new)

    def fill(self, song, held=()):
        """`song` was added to the playlist: selected, and its place taken by the next spare
        (or, with none left, given up: the rest keep their places). Whether it was shown."""
        if song.id not in self.selected:
            self.selected.append(song.id)
        index = next((i for i, item in enumerate(self.shown) if item.id == song.id), None)
        if index is None:
            return False
        spare = self._next_spare(held)
        self._filled[song.id] = (index, spare)
        if spare is None:
            del self.shown[index]
        else:
            self.shown[index] = spare
            self._offer(spare)
        return True

    def restore(self, song, held=()):
        """Adding `song` failed: no longer selected, and back in the place it gave up while
        that place is still there (the spare that took it, still shown, goes back to the front
        of the spares; an empty place, still empty). Not after an answer that replaced what
        was shown, nor once the playlist holds it. Whether it is shown again."""
        if song.id in self.selected:
            self.selected.remove(song.id)
        index, spare = self._filled.pop(song.id, (None, None))
        if index is None or song.id in held or any(item.id == song.id for item in self.shown):
            return False
        if spare is not None:
            place = next((i for i, item in enumerate(self.shown) if item is spare), None)
            if place is None:
                return False
            self.shown[place] = song
            self.spares.insert(0, spare)
            return True
        if len(self.shown) >= self.count:
            return False
        self.shown.insert(min(index, len(self.shown)), song)
        return True

    def preview(self, song):
        """`song`'s preview was played: told to Apple with the next request."""
        if song.id and song.id not in self.previewed:
            self.previewed.append(song.id)

    def drop_held(self, held):
        """Songs that are now in the playlist (added elsewhere, or by a sync) give their
        places to spares, as an added one does."""
        self.spares = [item for item in self.spares if item.id not in held]
        index = 0
        while index < len(self.shown):
            if self.shown[index].id not in held:
                index += 1
                continue
            spare = self._next_spare(held)
            if spare is None:
                del self.shown[index]
            else:
                self.shown[index] = spare
                self._offer(spare)
                index += 1

    def set_count(self, count, held=()):
        """Show `count` from now on: fewer shown give the rest back to the front of the
        spares (in their order); more take spares."""
        self.count = count
        if len(self.shown) > count:
            self.spares[:0] = self.shown[count:]
            del self.shown[count:]
        self._top_up(held)

    def rotate(self, held=()):
        """A Refresh Apple could not answer: the next `count` spares in place of those shown,
        when there are any. Whether anything changed."""
        spares = [item for item in self.spares if item.id not in held]
        if not spares:
            return False
        self.shown = []
        self.spares = spares
        self._filled = {}
        self._top_up(held)
        return True

    def wants_more(self):
        """Whether to ask for a few more: no spares are left (a place may be empty)."""
        return not self.spares

    def _new(self, items, held):
        known = set(self.offered) | set(self.selected) | set(held)
        known.update(item.id for item in self.spares)
        new = []
        for item in items:
            if item.id and item.id not in known:
                known.add(item.id)
                new.append(item)
        return new

    def _next_spare(self, held):
        while self.spares:
            spare = self.spares.pop(0)
            if spare.id not in held and spare.id not in self.selected:
                return spare
        return None

    def _top_up(self, held):
        while len(self.shown) < self.count:
            spare = self._next_spare(held)
            if spare is None:
                return
            self.shown.append(spare)
            self._offer(spare)

    def _offer(self, item):
        if item.id not in self.offered:
            self.offered.append(item.id)
