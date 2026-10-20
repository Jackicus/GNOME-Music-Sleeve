# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""RecentSearches: what was opened from the Search page, newest first (app.recent_searches),
which the page shows as Recently Searched before anything is typed.

music.apple.com keeps its Recently Searched in the browser's own storage, not in the account,
so the app keeps its own: <cache>/recent-searches.json, a list of Item dicts (only the keys a
tile and window.open_item() read: KEYS), at most LIMIT of them. Clear Cache and sign-out
clear it with the rest of the cache; load() notices the cache's generation move (store.py)
and reads the file again, so nothing of the old cache shows, and a write begun for the old
cache is dropped.

    recent = RecentSearches(config.cache_dir() / FILE_NAME, app.spawn)
    await recent.load()      # the file, once, and again after the cache was cleared
    recent.add(item)         # to the front, once; written in a thread
    recent.clear()
    recent.items             # a Gio.ListStore of Items

No GTK. A RecentSearches without a path is kept in memory only (the tests' stand-in app).
"""

import asyncio
import json
import logging
import os

from gi.repository import Gio

from .backend import store
from .library import Item

log = logging.getLogger(__name__)

FILE_NAME = 'recent-searches.json'
LIMIT = 10
# The kinds a search opens or plays: a category is browsed, not searched for.
KINDS = ('album', 'artist', 'playlist', 'song', 'station', 'video')
# What a tile shows and open_item() needs; an album's tracks are fetched again when opened.
KEYS = ('id', 'kind', 'title', 'subtitle', 'art', 'thumb', 'artUrl', 'thumbUrl', 'artColor',
        'catalogId', 'url', 'explicit', 'play')


def entry(data):
    """The part of an Item dict that is kept, or None for one that cannot be (no id, or a
    kind a search does not open)."""
    if not isinstance(data, dict) or data.get('kind') not in KINDS:
        return None
    if not isinstance(data.get('id'), str) or not data['id']:
        return None
    return {key: data[key] for key in KEYS if data.get(key) is not None}


def read(path):
    """The entries kept at `path`, newest first; [] when there is no file or it cannot be
    read. Blocks: call it in a thread."""
    try:
        with open(path, encoding='utf-8') as file:
            data = json.load(file)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        log.warning('could not read %s: %s', path, error)
        return []
    entries = data.get('items') if isinstance(data, dict) else None
    kept = [entry(item) for item in entries or []]
    return [item for item in kept if item is not None][:LIMIT]


def write(path, entries, generation):
    """Keep `entries` at `path`, atomically; not once the cache's generation has moved from
    `generation`. Best effort. Blocks: call it in a thread."""
    try:
        store.atomic_write(path, lambda file: json.dump({'items': entries}, file),
                           root=os.path.dirname(path), text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not keep %s: %s', path, error)


class RecentSearches:
    """See the module. Every change is written by one writer task at a time, which writes
    again while the list changed under it, so the file ends as the list is."""

    def __init__(self, path=None, spawn=None):
        self.path = str(path) if path is not None else None
        self.items = Gio.ListStore(item_type=Item)
        self._spawn = spawn
        self._generation = None  # the cache's generation the list was read from
        self._edits = 0  # changes made, to know whether a read or a write is behind
        self._writer = None

    async def load(self):
        """Read the file, unless it was read for this cache already (cheap then)."""
        generation = store.cache_generation()
        if generation == self._generation or self.path is None:
            return
        self._generation = generation
        edits = self._edits
        entries = await asyncio.to_thread(read, self.path)
        if edits == self._edits and generation == store.cache_generation():
            self.items.splice(0, self.items.get_n_items(), [Item(data) for data in entries])

    def add(self, item):
        """Put an Item at the front (moving it there when it is in the list already), and
        keep LIMIT; an Item a search does not open is left out."""
        data = entry(item.raw)
        if data is None:
            return
        for position in range(self.items.get_n_items()):
            kept = self.items.get_item(position)
            if kept.kind == item.kind and kept.id == item.id:
                self.items.remove(position)
                break
        self.items.insert(0, Item(data))
        excess = self.items.get_n_items() - LIMIT
        if excess > 0:
            self.items.splice(LIMIT, excess, [])
        self._changed()

    def clear(self):
        if self.items.get_n_items():
            self.items.remove_all()
            self._changed()

    def _changed(self):
        self._edits += 1
        if self.path is None or self._spawn is None:
            return
        if self._writer is None or self._writer.done():
            self._writer = self._spawn(self._write())

    async def _write(self):
        written = None
        while written != self._edits:
            written = self._edits
            entries = [dict(item.raw) for item in self.items]
            await asyncio.to_thread(write, self.path, entries, self._generation)
