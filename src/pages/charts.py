# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Charts page: Apple Music's charts of the account's storefront (engine.charts()) as
shelves, in music.apple.com's order: Top Songs as a numbered list of songs (a SongShelf,
which plays them as one queue from the song activated), Top Albums and Top Playlists as
numbered tiles, the Daily Top 100 and City Charts as playlist tiles that open their pages,
and Top Music Videos, numbered. A ShelvesPage pushed over the page it was opened from, not a
destination: as on music.apple.com, it is reached from New (More to Explore: Top Charts,
or Apple's own link to the charts, src/explore.py) and from Search's Browse Categories,
through the Top Charts tile (explore.charts_item(), which window.open_item opens). Kept a
day, as the other editorial pages are.

A genre menu in the header bar (GenreMenu: All Genres, then the catalog's genres,
engine.genres()) narrows the charts to a genre (engine.charts(genre=…), each genre's kept a
day). The page opens on every genre's charts, or on the genre a `viewTop?genreId=` link
names (src/charts.py); the choice is the page's, not remembered.
"""

import logging
from gettext import gettext as _

from gi.repository import Gtk

from .. import charts
from ..backend.errors import EngineError
from ..explore import CHARTS_KIND as KIND
from ..explore import charts_item
from ..widgets.labels import named_list_factory
from ..widgets.util import connect_weak
from . import app
from .shelves import ShelvesPage

__all__ = ('ICON_NAME', 'KIND', 'GenreMenu', 'charts_item', 'create')

log = logging.getLogger(__name__)

ICON_NAME = 'view-list-ordered-symbolic'


class GenreMenu:
    """The Charts page's genre menu: a Gtk.DropDown packed in the page's header bar, its
    entries src/charts.py's choices() (All Genres, then the engine's genres, read once the
    page first asks for its charts and again on a later ask while they are missing), shown
    once there is a genre to choose. `genre` is the genre the page asks for; choosing
    another starts the page over (ShelvesPage.start_over). Held by its page (`genre_menu`),
    which it holds weakly."""

    def __init__(self, genre=charts.ALL, label=''):
        self.genre = genre
        self._label = label  # what a link named its genre: the entry until the genres come
        self._page = None
        self._genres = None  # the engine's genres, once read
        self._task = None  # the genres being read
        self._choices = []
        self._setting = False  # the model or the selection being set, not chosen
        self.drop_down = Gtk.DropDown(valign=Gtk.Align.CENTER, visible=False,
                                      tooltip_text=_('Genre'))
        self.drop_down.update_property([Gtk.AccessibleProperty.LABEL], [_('Genre')])
        # The default factories leave the genres unnamed for assistive technology.
        self.drop_down.set_factory(named_list_factory(self.drop_down, popup=False,
                                                      drop_down=True))
        self.drop_down.set_list_factory(named_list_factory(self.drop_down, popup=True,
                                                           drop_down=True))
        connect_weak(self.drop_down, 'notify::selected', self._on_selected)

    def attach(self, page):
        """Pack the menu in `page`'s header bar, before its Refresh."""
        self._page = page.weak_ref()
        page.header_bar.pack_end(self.drop_down)
        self._show()

    async def fetch(self, refresh):
        """The page's fetch: the charts of the genre chosen (and the genres, while the menu
        has none)."""
        if self._genres is None and (self._task is None or self._task.done()):
            self._task = app().spawn(self._read_genres())
        return await app().engine.charts(genre=self.genre or None, refresh=refresh)

    async def _read_genres(self):
        try:
            answer = await app().engine.genres()
        except EngineError as error:
            log.info('charts: no genres to choose from: %s', error)
            return
        genres = answer.get('genres') if isinstance(answer, dict) else None
        self._genres = genres if isinstance(genres, list) else []
        self._show()

    def _show(self):
        found = charts.choices(self._genres, self.genre, self._label)
        if found != self._choices:
            self._choices = found
            self._setting = True
            try:
                self.drop_down.set_model(Gtk.StringList.new([c.title for c in found]))
                self.drop_down.set_selected(charts.position(found, self.genre))
            finally:
                self._setting = False
        self.drop_down.set_visible(len(found) > 1)

    def _on_selected(self, drop_down, _pspec):
        position = drop_down.get_selected()
        if self._setting or not 0 <= position < len(self._choices):
            return
        genre = self._choices[position].id
        page = self._page() if self._page is not None else None
        if genre == self.genre or page is None:
            return
        self.genre = genre
        page.start_over()


def create(item):
    """The Charts page, pushed for `item` (charts_item()'s, or a link's to the charts,
    titled as Apple labels it; one that names a genre opens on it, titled Top Charts, the
    genre's name in the menu)."""
    genre = charts.link_genre(item)
    menu = GenreMenu(genre, item.title if genre else '')
    page = ShelvesPage(charts_item().title if genre else item.title, menu.fetch,
                       root=False, icon_name=ICON_NAME, hero=False,
                       empty_title=_('No Charts'),
                       empty_description=_('Apple Music has no charts to show right now'))
    menu.attach(page)
    page.genre_menu = menu
    page.item = item
    return page
