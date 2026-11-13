# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the catalog shows under an album's or a catalog playlist's tracks on its page: the
album's footer, the catalog's shelves (Engine.album_page, Engine.playlist_page) and their
See All.

An album's tracks end as Apple Music's clients end an album: a section of one marker item
whose row holds the footer (release.py: the release date in full, the songs and their time,
the ℗ line), then, once the catalog has answered (Engine.album_page, asked after the
tracks' first paint, kept for a day), one more whose row holds the catalog's shelves (Other
Versions, Music Videos, More By, Featured On, You Might Also Like) in a ShelfColumn, as an
artist page's are. An album the catalog cannot answer for shows the footer's counts alone:
the failure is only logged.

A catalog playlist (release.playlist_target(): one of Apple's or a curator's, in the library or
not) ends the same way, without the footer: once the catalog has answered
(Engine.playlist_page, asked after the tracks' first paint, kept for a day), a section whose row
holds its shelves (Featured Artists, More By <curator>, You Might Also Like), and the curator's
name under the title becomes a link to their page (release.curator_item(): an Apple curator's
category page, a third party's page on music.apple.com in the browser).
"""

import logging

from gi.repository import Gtk

from ..backend.errors import EngineError
from ..library import Item
from ..release import (album_artist, album_shelves, album_target, curator, curator_item,
                       footer_lines, playlist_shelves, playlist_target)
from ..remote import fetch_shelf_art, remote_item
from ..widgets.util import next_frame
from . import app

log = logging.getLogger(__name__)

# The kinds whose tracks the engine's item() fetches when an Item came without them.
FETCHED_KINDS = ('album', 'playlist')


def album_completer(answer, shelf):
    """See All's coroutine function for a shelf under an album Apple has more of: the whole
    view (Engine.album_view; for More By the artist's albums, Engine.artist_view, less the
    album), the Items shown kept. None for a shelf Apple sent whole."""
    if not getattr(shelf, 'more', False) or not isinstance(answer, dict):
        return None
    album_id = str(answer.get('id') or '')
    artist_id = str(answer.get('artistId') or '')
    if shelf.key == 'more-by-artist':
        if not artist_id:
            return None
        return _completer(shelf, artist_id, album_id,
                          lambda engine: engine.artist_view(artist_id, 'full-albums'))
    if album_id:
        return _completer(shelf, album_id, album_id,
                          lambda engine: engine.album_view(album_id, shelf.key))
    return None


def playlist_completer(answer, shelf):
    """See All's coroutine function for a shelf under a catalog playlist Apple has more of:
    the whole view (Engine.playlist_view; for More By the curator's playlists,
    Engine.curator_playlists), less the playlist, the Items shown kept. None for a shelf
    Apple sent whole."""
    if not getattr(shelf, 'more', False) or not isinstance(answer, dict):
        return None
    playlist_id = str(answer.get('id') or '')
    if not playlist_id:
        return None
    if shelf.key == 'more-by-curator':
        curator = answer.get('curator')
        curator_id = str(curator.get('id') or '') if isinstance(curator, dict) else ''
        if not curator_id or curator.get('kind') != 'category':
            return None
        return _completer(shelf, playlist_id, playlist_id,
                          lambda engine: engine.curator_playlists(curator_id))
    return _completer(shelf, playlist_id, playlist_id,
                      lambda engine: engine.playlist_view(playlist_id, shelf.key))


def _completer(shelf, key, own_id, fetch):
    """See All's coroutine function: `fetch(engine)`'s Items for the shelf, the one with
    `own_id` (the page's own album or playlist) left out, the Items shown kept; a failure
    is only logged (by `key` and the shelf's)."""
    async def complete():
        try:
            dicts = await fetch(app().engine)
        except EngineError as error:
            log.info('%s, %s: %s', key, shelf.key, error)
            return
        shown = {item.id: item for item in shelf.items}
        items = [shown.get(data.get('id')) or Item(remote_item(data)) for data in dicts
                 if isinstance(data, dict) and data.get('id') and data.get('kind')
                 and own_id not in (data.get('id'), data.get('catalogId'))]
        if items:
            shelf.more = False
            shelf.update(shelf.title, items)
            await fetch_shelf_art([shelf])
    return complete


class CatalogPart:
    """DetailPage's footer and catalog shelves (a mixin of pages/detail.py's DetailPage). It
    works on what DetailPage.__init__ makes: its state (_catalog_asked_for, _catalog_task,
    _catalog_art_task, _catalog_answer, _catalog_shelves, _curator, _shelf_column), the
    template's footer_label and shelves_box, and the list's sections (_sections, _rows,
    _shelves_section, _shelves_start); _take_playlist() shows the curator through
    DetailPage._show_curator()."""

    # What the catalog shows under an album's tracks: the footer and the shelves.

    def _update_footer(self, item, groups):
        """The footer's lines: the release date, the songs shown and their time, the
        copyright (release.footer_lines), from the catalog's answer once it has come."""
        count = sum(group.entries.get_n_items() for group in groups)
        duration = sum(track.duration_ms for group in groups for track in group.entries)
        answer = self._catalog_answer if self._catalog_asked_for is item else None
        lines = footer_lines(item, answer, count, duration)
        self.footer_label.set_label('\n'.join(lines))
        self.footer_label.set_visible(bool(lines))

    def _forget_catalog(self):
        """The catalog's answer for another Item than the one shown let go of."""
        self._catalog_answer = None
        self._catalog_shelves = []
        self._curator = None

    def _ask_catalog(self):
        """Ask the catalog for the rest of the album or catalog playlist shown
        (release.album_target, release.playlist_target), once, while the page is mapped and
        its tracks are shown: the page's first build never waits for it."""
        item = self.item
        if (item is None or item.kind not in FETCHED_KINDS or self._catalog_asked_for is item
                or not self.get_mapped() or not self._groups):
            return
        self._catalog_asked_for = item
        if item.kind == 'album':
            target = album_target(item)
            load = self._load_album(item, *target) if target is not None else None
        else:
            target = playlist_target(item)
            load = self._load_playlist(item, target) if target is not None else None
        if load is None:
            return
        if self._catalog_task is not None and not self._catalog_task.done():
            self._catalog_task.cancel()
        self._catalog_task = app().spawn(load)

    async def _load_album(self, item, album_id, song_id):
        """Engine.album_page()'s answer, after the tracks' first paint. An album it cannot
        answer for (offline, the engine down, one the catalog lacks) shows what it has: the
        failure is only logged."""
        await next_frame(self.list_view)
        try:
            answer = await app().engine.album_page(album_id, song_id=song_id)
        except EngineError as error:
            log.info('the rest of album %s: %s', item.id, error)
            return
        if self.item is item and self._catalog_asked_for is item:
            self._take_album(item, answer)

    def _take_album(self, item, answer):
        """Show Engine.album_page()'s answer: the footer's release lines, the shelves after
        it (appended, the tracks' rows left as they are), and their thumbnails."""
        self._catalog_answer = answer
        self._catalog_shelves = album_shelves(answer, album_artist(item))
        for shelf in self._catalog_shelves:
            shelf.complete = album_completer(answer, shelf)
        groups = [group for group in item.groups if group.entries.get_n_items()]
        if not groups:
            return
        self._update_footer(item, groups)
        self._show_catalog_shelves()

    async def _load_playlist(self, item, playlist_id):
        """Engine.playlist_page()'s answer, after the tracks' first paint. A playlist it
        cannot answer for (offline, the engine down, one the catalog lacks) keeps its plain
        curator and no shelves: the failure is only logged."""
        await next_frame(self.list_view)
        try:
            answer = await app().engine.playlist_page(playlist_id)
        except EngineError as error:
            log.info('the rest of playlist %s: %s', item.id, error)
            return
        if self.item is item and self._catalog_asked_for is item:
            self._take_playlist(item, answer)

    def _take_playlist(self, item, answer):
        """Show Engine.playlist_page()'s answer: the curator's name a link to their page,
        the shelves after the tracks (appended, the tracks' rows left as they are), and
        their thumbnails."""
        self._catalog_answer = answer
        self._curator = curator_item(answer)
        self._catalog_shelves = playlist_shelves(answer, curator(item))
        for shelf in self._catalog_shelves:
            shelf.complete = playlist_completer(answer, shelf)
        self._show_curator(item)
        if any(group.entries.get_n_items() for group in item.groups):
            self._show_catalog_shelves()

    def _show_catalog_shelves(self):
        """The catalog's shelves (_catalog_shelves) in the last section, appended or taken
        away as there are some or none, and their thumbnails fetched."""
        if self._shelf_column is None and self._catalog_shelves:
            from ..widgets.shelf import ShelfColumn

            self._shelf_column = ShelfColumn(self.shelves_box)
        if self._shelf_column is not None:
            self._shelf_column.show(self._catalog_shelves)
        count = self._sections.get_n_items()
        present = count > 0 and self._sections.get_item(count - 1) is self._shelves_section
        if self._catalog_shelves and not present:
            self._shelves_start = self._rows.get_n_items()
            self._sections.append(self._shelves_section)
        elif present and not self._catalog_shelves:
            self._shelves_start = None
            self._sections.remove(count - 1)
        if self._catalog_shelves:
            if self._catalog_art_task is not None and not self._catalog_art_task.done():
                self._catalog_art_task.cancel()
            self._catalog_art_task = app().spawn(fetch_shelf_art(list(self._catalog_shelves)))

    async def _focus_shelves(self):
        """The first shelf's first focusable widget, once the list has laid out the row
        scroll_to() brought into view (a frame or two)."""
        for _attempt in range(3):
            await next_frame(self.list_view)
            if (self.shelves_box.get_mapped()
                    and self.shelves_box.child_focus(Gtk.DirectionType.TAB_FORWARD)):
                return
