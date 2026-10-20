# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the Home page (pages/home.py) shows beside the library's shelves: Recently Played,
asked of Apple as the page is shown, and where it goes. No GTK here.

    recent = RecentlyPlayed()                 # the shelf, one for the page's life
    recent.show(answer, library)              # Engine.recently_played()'s answer, in place
    shelves = arrange(library.shelves, recent.shelf)
    throttle = Throttle(); throttle.due(answer)   # whether to ask Apple again now

The library's shelves come from the sync (every few hours); Recently Played is
Engine.recently_played(), whose answer is kept for a day: the page shows the kept one at once
and asks Apple again (refresh) once it is RECENT_MAX_AGE old, not more often (Throttle), and
not again for RETRY_DELAY after Apple failed. The shelf is one ShelfModel for the page's life,
its store brought to each answer with the fewest splices (library.apply_diff), each item the
library's own Item when the library has it (by kind and id) and otherwise the same Item as the
last answer's, so the shelf's widget, its tiles and its scroll position stay through an
update. hold_back() says when an update would move what is under the user's eyes or take the
focus: the page keeps it for the next time it is shown.
"""

import time
from datetime import UTC, datetime
from gettext import gettext as _

from .backend import errors
from .backend.normalize import STAMP_FORMAT
from .library import Item, ShelfModel, apply_diff
from .remote import remote_item

# The key of the Recently Played shelf: none of the sync's (theirs are `rec-<id>` and the
# fixed shelves' keys).
RECENT_KEY = 'recently-played'
# Seconds: an answer older than this is asked for again as Home is shown, or on Refresh.
RECENT_MAX_AGE = 60
# Seconds after Apple failed to answer (not the engine down or the account signed out, which
# the page waits out by watching the engine) before it is asked again.
RETRY_DELAY = 60
# The fewest items of one of Apple's recommendations that are all in Recently Played for it
# to count as a repeat of it (arrange()).
REPEAT_MIN = 2


def answer_age(answer, now=None):
    """Seconds since the answer's `cached` stamp (normalize.write_answer's), or None without
    one (or one that is not a stamp)."""
    stamp = answer.get('cached') if isinstance(answer, dict) else None
    if not isinstance(stamp, str):
        return None
    try:
        when = datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return ((now or datetime.now(UTC)) - when).total_seconds()


class Throttle:
    """When Home asks Apple for Recently Played again. `clock` (seconds, monotonic) is for
    tests."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._failed_at = None

    def due(self, answer, now=None):
        """Whether to ask Apple now: no answer in hand, or one without a stamp, stale or
        RECENT_MAX_AGE old (`now` the time in UTC, for tests); never within RETRY_DELAY of
        a failure."""
        if self._failed_at is not None and self._clock() - self._failed_at < RETRY_DELAY:
            return False
        age = answer_age(answer, now)
        return (age is None or age >= RECENT_MAX_AGE
                or (isinstance(answer, dict) and answer.get('stale') is True))

    def answered(self):
        """Apple answered: the next ask waits only for the answer's age."""
        self._failed_at = None

    def reset(self):
        """The account signed out: its failures hold the next account's asks back no more."""
        self._failed_at = None

    def failed(self, error):
        """Apple could not answer (an EngineError): no ask for RETRY_DELAY, unless the engine
        was down or the account signed out (the page asks again once the engine is up or
        authorized)."""
        if getattr(error, 'code', None) not in (errors.ENGINE_DOWN, errors.NOT_SIGNED_IN):
            self._failed_at = self._clock()


class RecentlyPlayed:
    """The Recently Played shelf (`shelf`, a ShelfModel keyed RECENT_KEY) and the Items of the
    answers shown in it, kept by kind and id, so an item still played keeps its object."""

    def __init__(self):
        self.shelf = ShelfModel(RECENT_KEY, _('Recently Played'), [])
        self._remote = {}  # (kind, id) -> the Item made for an answer's dict

    def items_for(self, answer, library=None):
        """The Items `answer` (Engine.recently_played's: {items: [Item dict]}) shows, in its
        order: the library's own Item for one it has (library.by_id), else the one made for
        the last answer, its fields brought up to date (its groups left alone: a page
        showing it may have fetched them), else a new one, its artwork where remote.py
        fetches it (remote_item()). An item without a kind and an id is left out, and so is
        one met twice."""
        dicts = answer.get('items') if isinstance(answer, dict) else None
        items = []
        seen = set()
        remote = {}
        for data in dicts if isinstance(dicts, list) else []:
            if not isinstance(data, dict) or not data.get('id') or not data.get('kind'):
                continue
            key = (str(data['kind']), str(data['id']))
            if key in seen:
                continue
            seen.add(key)
            item = library.by_id(*key) if library is not None else None
            if item is None:
                data = remote_item(data)
                item = self._remote.get(key)
                if item is None:
                    item = Item(dict(data))
                else:
                    item.merge({name: value for name, value in data.items()
                                if name != 'groups'})
                remote[key] = item
            items.append(item)
        return items, remote

    def show(self, answer, library=None):
        """Bring the shelf to `answer` with the fewest changes; True when it changed."""
        items, remote = self.items_for(answer, library)
        before = [self.shelf.items.get_item(i) for i in range(self.shelf.items.get_n_items())]
        self._remote = remote
        if items == before:
            return False
        apply_diff(self.shelf.items, items, before)
        return True

    def clear(self):
        """Show nothing (the account signed out: its plays are not the next one's)."""
        self._remote = {}
        self.shelf.items.remove_all()


def _keys(item):
    """The (kind, id) pairs an Item goes by: its own, and its catalog id's."""
    keys = {(item.kind, item.id)}
    catalog_id = item.raw.get('catalogId') if isinstance(item.raw, dict) else None
    if catalog_id:
        keys.add((item.kind, str(catalog_id)))
    return keys


def repeats(shelf, played):
    """Whether a shelf of the library's is one of Apple's recommendations (`rec-…`) whose
    items, at least REPEAT_MIN of them, are all among `played` ((kind, id) pairs): Apple's own
    Recently Played among its recommendations, which the shelf of that name shows already."""
    if not str(shelf.key).startswith('rec-'):
        return False
    count = shelf.items.get_n_items()
    return count >= REPEAT_MIN and all(
        _keys(shelf.items.get_item(i)) & played for i in range(count))


def arrange(shelves, recent):
    """Home's shelves: the library's (ShelfModels) that have items, in their order, with
    `recent` (the Recently Played ShelfModel) after the first of them, as Apple Music places
    it under its Top Picks, or alone; left out while it is empty. A recommendation that only
    repeats it (repeats()) is left out while it shows."""
    shelves = [shelf for shelf in shelves if shelf.items.get_n_items()]
    if not recent.items.get_n_items():
        return shelves
    played = set()
    for item in recent.items:
        played |= _keys(item)
    shelves = [shelf for shelf in shelves if not repeats(shelf, played)]
    return [*shelves[:1], recent, *shelves[1:]]


def hold_back(shown, will_show, scrolled, focused):
    """Whether an update of Recently Played waits for the next time the page is shown: while
    the focus is in the shelf (`focused`: its tiles may go under it), or when the shelf would
    come or go (`shown`, `will_show`) above what the user scrolled to (`scrolled`: the page
    is not at its top), which would move everything under it."""
    return focused or (shown != will_show and scrolled)
