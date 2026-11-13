# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The songs Apple suggests adding to a playlist of the user's, shown under its tracks on
its page, and their previews.

Under a playlist the user can change (wants_suggestions()), the songs Apple suggests adding
to it (Engine.playlist_suggestions), as music.apple.com shows them: one more section after
the tracks, a store of one marker item whose row holds a SuggestedSongs of them
(widgets/suggested_songs.py: an Add button on each, and Refresh), six at a time, or twelve
with the `more-suggestions` setting, less the songs the playlist holds. What is shown, the
spares that fill an added song's place and what Apple has offered are a
suggestions.Suggestions, one a playlist. The section is left out while there are none to
show, the engine unable to answer among them: a failure is only logged.

A suggested song clicked plays in full, as a track row's song does, or, with the
`preview-suggestions` setting, Apple's 30-second preview of it (Player.start_preview(): the
queue pauses for it), clicked again to stop; a song without a preview plays in full. The
row of the song previewing is marked while the Player's `preview` names it, every song
previewed is told to Apple with the next request (Suggestions.preview()), and a preview
started here stops when the page is left.
"""

import asyncio
import logging

from ..backend.errors import EngineError
from ..library import Item, ShelfModel
from ..remote import fetch_shelf_art, remote_item
from ..suggestions import SPARES, Suggestions, preview_url
from ..suggestions import basis as suggestion_basis
from ..suggestions import count as suggestion_count
from ..widgets.suggested_songs import SuggestedSongs
from ..widgets.util import connect_weak, weak_method
from . import app

log = logging.getLogger(__name__)


def wants_suggestions(item):
    """Whether a page showing `item` offers the songs Apple suggests adding to it: a library
    playlist the user can change (Item.editable: not Favourite Songs, not one of Apple's), as
    music.apple.com offers them."""
    return item is not None and item.kind == 'playlist' and item.editable


def held_songs(item):
    """The ids of the songs a playlist holds: its tracks' catalog ids and their own."""
    held = set()
    for group in item.groups:
        for track in group.entries:
            held.update(song_id for song_id in (track.catalog_id, track.id) if song_id)
    return held


def suggestion_items(answer):
    """The song Items of an Engine.playlist_suggestions answer, in Apple's order."""
    return [Item(remote_item(entry)) for entry in (answer or {}).get('items') or []
            if isinstance(entry, dict) and entry.get('id') and entry.get('kind') == 'song']


class SuggestionsPart:
    """DetailPage's suggested songs (a mixin of pages/detail.py's DetailPage). It works on
    what DetailPage.__init__ makes: its state (_suggested_for, _suggestions,
    _suggestions_task, _more_task, _suggestion_art_task, suggested_songs, _previewing), the
    list's sections (_sections, _rows, _suggestions_section, _suggestions_start), _groups,
    _settings, the Player through _playing, and item."""

    # The songs Apple suggests adding to a playlist.

    def _suggestions_widget(self):
        """The section of suggestions, made the first time there are some."""
        if self.suggested_songs is None:
            # In a track list's row, which keeps the page's margins.
            section = SuggestedSongs(margin_top=18, margin_bottom=12)
            connect_weak(section, 'play-song', self._on_play_suggestion)
            connect_weak(section, 'add-song', self._on_add_suggestion)
            connect_weak(section, 'refresh', self._on_refresh_suggestions)
            player = self._playing.player
            section.set_previewing(player.preview if player is not None else '')
            self.suggested_songs = section
        return self.suggested_songs

    def _count(self):
        """How many suggestions to show: the `more-suggestions` setting's (suggestions.py)."""
        more = self._settings is not None and self._settings.get_boolean('more-suggestions')
        return suggestion_count(more)

    def _suggest(self):
        """Ask for the suggestions of the playlist shown, once (wants_suggestions), while
        the page is mapped."""
        item = self.item
        if not wants_suggestions(item) or self._suggested_for is item or not self.get_mapped():
            return
        self._suggested_for = item
        self._suggestions = Suggestions(self._count())
        self._fetch_suggestions(item)

    def _fetch_suggestions(self, item, refresh=False):
        for task in (self._suggestions_task, self._more_task):
            if task is not None and not task.done():
                task.cancel()
        self._suggestions_task = app().spawn(
            self._load_suggestions(item, self._suggestions, refresh))

    async def _load_suggestions(self, item, suggestions, refresh):
        """The first answer (kept for a day), or a Refresh's: new songs, none of those
        offered so far, as many as are shown and SPARES more. A Refresh Apple cannot answer
        shows the next spares instead, when there are some. The answer kept is for what the
        playlist holds now (suggestion_basis): once it holds other songs, it is asked again."""
        basis = suggestion_basis(held_songs(item))
        try:
            if refresh:
                answer = await app().engine.playlist_suggestions(
                    item.id, refresh=True, limit=suggestions.count + SPARES,
                    offered=list(suggestions.offered), selected=list(suggestions.selected),
                    previewed=list(suggestions.previewed), basis=basis)
            else:
                answer = await app().engine.playlist_suggestions(item.id, basis=basis)
        except EngineError as error:
            log.info('suggestions for playlist %s: %s', item.id, error)
            if (refresh and self.item is item and self._suggestions is suggestions
                    and suggestions.rotate(held_songs(item))):
                self._update_suggestions()
            return
        if self.item is not item or self._suggestions is not suggestions:
            return
        suggestions.take(suggestion_items(answer), held_songs(item))
        self._update_suggestions()
        self._want_more()

    def _want_more(self):
        """Ask for a few more songs when the spares have run out (and Apple had more the
        last time it was asked), to fill the places of the next songs added."""
        suggestions = self._suggestions
        loading = self._suggestions_task  # an answer on its way, unless this is it
        if (suggestions is None or not suggestions.wants_more() or suggestions.exhausted
                or self.item is None or not self.get_mapped()
                or (self._more_task is not None and not self._more_task.done())
                or (loading is not None and not loading.done()
                    and loading is not asyncio.current_task())):
            return
        self._more_task = app().spawn(self._load_more(self.item, suggestions))

    async def _load_more(self, item, suggestions):
        limit = max(suggestions.count - len(suggestions.shown), 0) + SPARES
        try:
            answer = await app().engine.playlist_suggestions(
                item.id, limit=limit, offered=list(suggestions.offered),
                selected=list(suggestions.selected), previewed=list(suggestions.previewed),
                more=True)
        except EngineError as error:
            log.info('more suggestions for playlist %s: %s', item.id, error)
            suggestions.exhausted = True
            return
        if self.item is not item or self._suggestions is not suggestions:
            return
        if not suggestions.extend(suggestion_items(answer), held_songs(item)):
            suggestions.exhausted = True
        self._update_suggestions()

    def _update_suggestions(self):
        """Show the suggestions as they are now: the section's songs, its place in the list
        while it has some, and their thumbnails."""
        item = self.item
        shown = []
        if (item is not None and self._groups and wants_suggestions(item)
                and self._suggestions is not None and self._suggested_for is item):
            shown = list(self._suggestions.shown)
        if shown or self.suggested_songs is not None:
            self._suggestions_widget().set_items(shown)
        count = self._sections.get_n_items()
        present = count > 0 and self._sections.get_item(count - 1) is self._suggestions_section
        if shown and not present:
            self._suggestions_start = self._rows.get_n_items()
            self._sections.append(self._suggestions_section)
        elif present and not shown:
            self._suggestions_start = None
            self._sections.remove(count - 1)
        if shown:
            if self._suggestion_art_task is not None and not self._suggestion_art_task.done():
                self._suggestion_art_task.cancel()
            self._suggestion_art_task = app().spawn(
                fetch_shelf_art([ShelfModel('suggested', '', shown)]))

    def _on_count_changed(self, *_args):
        """The `more-suggestions` setting: as many shown as it says, from the spares, and a
        few more asked for when they run out."""
        if self._suggestions is None or self.item is None:
            return
        self._suggestions.set_count(self._count(), held_songs(self.item))
        self._update_suggestions()
        self._want_more()

    def _on_refresh_suggestions(self, _section):
        if wants_suggestions(self.item) and self._suggestions is not None:
            self._fetch_suggestions(self.item, refresh=True)

    def _on_play_suggestion(self, _section, song):
        """A suggested song clicked: in full, or its preview with the `preview-suggestions`
        setting (stopped instead when it is the one previewing). A song without a preview
        plays in full."""
        url = preview_url(song)
        wanted = self._settings is not None and self._settings.get_boolean('preview-suggestions')
        player = self._playing.player
        if not (url and wanted and player is not None):
            self.get_root().play_request(song.play)
            return
        application = app()
        if application.refuse_in_demo():
            return
        if player.preview == song.id:
            self._previewing = ''
            application.player_command(player.stop_preview())
            return
        self._previewing = song.id
        application.player_command(player.start_preview(song.id, url))

    def _on_preview_changed(self, *_args):
        """The Player's preview: its row marked, and the song told to Apple next time as one
        previewed."""
        player = self._playing.player
        song_id = player.preview if player is not None else ''
        if self.suggested_songs is not None:
            self.suggested_songs.set_previewing(song_id)
        if song_id and self._suggestions is not None:
            song = next((item for item in self._suggestions.shown if item.id == song_id), None)
            if song is not None:
                self._suggestions.preview(song)
        if not song_id:
            self._previewing = ''

    def _stop_preview(self):
        """Stop the preview this page started, if it still plays: the page is left, and its
        row with it."""
        player = self._playing.player
        song_id, self._previewing = self._previewing, ''
        if song_id and player is not None and player.preview == song_id:
            app().player_command(player.stop_preview())

    def _on_add_suggestion(self, _section, song):
        """Add a suggested song to the playlist (the item actions' Add to Playlist, which
        fetches the playlist again), and give its place to the next suggestion at once; an
        add that fails gives it back (_on_suggestion_written)."""
        actions = getattr(self.get_root(), 'item_actions', None)
        if actions is None or self.item is None or self._suggestions is None:
            return
        task = actions.add_to_playlist(self.item.id, song.id, song.title)
        if task is None:
            return
        suggestions = self._suggestions
        suggestions.fill(song, held_songs(self.item))
        self._update_suggestions()
        self._want_more()
        # The task outlives a page that may be popped meanwhile: it holds the page weakly.
        written = weak_method(self._on_suggestion_written)
        task.add_done_callback(lambda done: written(done, song, suggestions))

    def _on_suggestion_written(self, task, song, suggestions):
        """An add from the suggestions ended: when it failed (reported already, by the item
        actions), the song is not selected and goes back to its place, while this page still
        shows the suggestions it was added from."""
        if task.cancelled() or task.exception() is not None or task.result() is not False:
            return
        if suggestions is not self._suggestions or self.item is None:
            suggestions.restore(song)  # not reported to Apple as chosen, wherever it is
            return
        if suggestions.restore(song, held_songs(self.item)):
            self._update_suggestions()
