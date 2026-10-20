# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""SearchPager: one kind of a catalog search's hits, fetched a page at a time as they are
wanted. No GTK here.

The Search page's filter by kind and a search shelf's See All show one kind (songs, albums,
radio shows…) as a list that grows as it is scrolled (widgets/search_list.py). The pager holds
what has been found so far in `items` (a Gio.ListStore of Items, appended to, never replaced),
where Apple's next page starts (`next`, an offset; None once Apple has no more) and its
`state`: 'idle' (more to fetch), 'loading', 'failed' (the last page could not be fetched:
`error` says why, and request() tries it again) or 'done'.

request() fetches the next page as a task (through `spawn`, app.spawn) unless one is under
way, the page done, or nothing more: more() asks `search(term, kind=, offset=, limit=)`
(Engine.search) for `limit` hits from `next`, keeps those it does not hold already (Apple's
offsets shift as its catalog changes) and starts fetching their thumbnails. A page that adds
nothing but names a next is followed at once, EMPTY_PAGES pages at most (a page of Apple's
curators may hold no radio show), and that many with nothing new end it. cancel() stops a
fetch under way, the state back to 'idle', so a page that is left stops asking.
"""

import asyncio
import logging

from gi.repository import Gio, GObject

from .backend import api
from .backend.errors import EngineError
from .library import Item
from .remote import fetch_items_art, remote_items

log = logging.getLogger(__name__)

# The pages one more() follows that bring nothing new, at most.
EMPTY_PAGES = 3

STATES = ('idle', 'loading', 'failed', 'done')


class SearchPager(GObject.Object):
    """The pages of kind `kind` (a shelf key, api.SEARCH_KIND_TYPES) of a search for `term`
    (see the module): `items` starts with the Items given (a shelf's, the first page's), and
    `next_offset` is where Apple's next page starts (None: Apple has no more)."""

    __gtype_name__ = 'AppleMusicSearchPager'

    state = GObject.Property(type=str, default='idle', nick='State',
                             blurb="'idle', 'loading', 'failed' or 'done'")

    def __init__(self, term, kind, items=(), next_offset=0, search=None, spawn=None,
                 limit=api.SEARCH_PAGE_LIMIT):
        super().__init__()
        self.term = term
        self.kind = kind
        self.limit = limit
        self.items = Gio.ListStore(item_type=Item)
        self.next = next_offset
        self.error = None  # the last page's failure, while `state` is 'failed'
        self._search = search
        self._spawn = spawn
        self._task = None
        self._seen = set()
        self._add(items)
        self.state = 'idle' if next_offset is not None else 'done'

    def _add(self, items):
        """Append the Items not held yet; answers them."""
        new = []
        for item in items:
            key = (item.kind, item.id)
            if key not in self._seen:
                self._seen.add(key)
                new.append(item)
        if new:
            self.items.splice(self.items.get_n_items(), 0, new)
        return new

    @property
    def busy(self):
        return self._task is not None and not self._task.done()

    def request(self):
        """Fetch the next page (more()) as a task, unless one is under way or there is none
        to fetch; answers the task, or None."""
        if self.busy or self.state not in ('idle', 'failed') or self.next is None:
            return None
        self._task = self._spawn(self.more())
        return self._task

    def cancel(self):
        """Stop the fetch under way, if any (its state goes back to 'idle')."""
        if self.busy:
            self._task.cancel()
        self._task = None

    async def more(self):
        """Fetch the next page now (see the module)."""
        if self.next is None or self.state == 'loading':
            return
        self.state = 'loading'
        self.error = None
        added = []
        try:
            for _ in range(EMPTY_PAGES):
                answer = await self._search(self.term, kind=self.kind, offset=self.next,
                                            limit=self.limit)
                shelf = next((found for found in (answer or {}).get('shelves') or []
                              if isinstance(found, dict) and found.get('key') == self.kind),
                             None) or {}
                following = shelf.get('next')
                added += self._add(remote_items(shelf.get('items')))
                # Apple's next page further on, or none: never the same page again.
                self.next = (following if isinstance(following, int) and following > self.next
                             else None)
                if added or self.next is None:
                    break
            else:
                self.next = None  # EMPTY_PAGES pages of nothing new: taken as the end
        except asyncio.CancelledError:
            self.state = 'idle'
            raise
        except EngineError as error:
            log.info('search: the next page of %s: %s', self.kind, error)
            self.error = error
            self.state = 'failed'
            return
        self.state = 'done' if self.next is None else 'idle'
        if added and self._spawn is not None:
            self._spawn(fetch_items_art(added))
