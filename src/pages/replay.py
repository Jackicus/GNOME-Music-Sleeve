# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Replay page: the account's year in music (engine.replay()) as shelves, as Apple
Music's Replay shows it: Top Songs as a numbered list of songs (a SongShelf, which plays
them as one queue from the song activated), Top Artists and Top Albums as numbered tiles,
then each year's Replay playlist, which opens its page. A ShelvesPage pushed over the page
it was opened from, not a destination: it is reached from the link More for You ends Made
for You and Home with (explore.replay_item(), which window.open_item opens). Kept a day, as
the other pages of Apple's answers are; titled with the year it shows (src/replay.py).

A year menu in the header bar (YearMenu: the years Apple lists a Replay of, newest first)
shows a past year's (engine.replay(year=…), each kept a day). The page opens on the latest
year's; the choice is the page's, not remembered. Replay needs the account's listening
history: an account without it, or a year Apple has nothing of, shows No Replay Yet.
"""

import logging
from gettext import gettext as _

from gi.repository import Gtk

from .. import replay
from ..explore import REPLAY_KIND as KIND
from ..explore import replay_item
from ..widgets.labels import named_list_factory
from ..widgets.util import connect_weak
from . import app
from .shelves import ShelvesPage

__all__ = ('ICON_NAME', 'KIND', 'YearMenu', 'create', 'replay_item')

log = logging.getLogger(__name__)

ICON_NAME = 'x-office-calendar-symbolic'


class YearMenu:
    """The Replay page's year menu: a Gtk.DropDown packed in the page's header bar, its
    entries src/replay.py's choices() (the years Apple's answers list, the latest year's
    first), shown once there is another year to choose. `year` is the year the page asks
    for (replay.LATEST, '', for the latest); choosing another starts the page over
    (ShelvesPage.start_over). Each answer titles the page with its year. Held by its page
    (`year_menu`), which it holds weakly."""

    def __init__(self):
        self.year = replay.LATEST
        self._latest = ''  # the year the latest summary is of, once answered
        self._years = set()  # the years Apple's answers listed
        self._page = None
        self._choices = []
        self._setting = False  # the model or the selection being set, not chosen
        # Translators: the Replay page's menu of the years to show the Replay of.
        self.drop_down = Gtk.DropDown(valign=Gtk.Align.CENTER, visible=False,
                                      tooltip_text=_('Year'))
        self.drop_down.update_property([Gtk.AccessibleProperty.LABEL], [_('Year')])
        # The default factories leave the years unnamed for assistive technology.
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
        """The page's fetch: the Replay of the year chosen; its answer's years join the
        menu's, and its year titles the page."""
        year = self.year
        answer = await app().engine.replay(year=year or None, refresh=refresh)
        if isinstance(answer, dict):
            shown = str(answer.get('year') or '')
            if year == replay.LATEST:
                self._latest = shown
            years = answer.get('years')
            if isinstance(years, list):
                self._years.update(entry for entry in years if isinstance(entry, str))
            self._show()
            self._title(shown or year)
        return answer

    def _title(self, year):
        """Title the page with `year` (Replay alone without one)."""
        page = self._page() if self._page is not None else None
        if page is not None:
            title = replay.page_title(year)
            page.set_title(title)
            page.title_label.set_label(title)

    def _show(self):
        found = replay.choices(self._years, self._latest)
        if found != self._choices:
            self._choices = found
            self._setting = True
            try:
                self.drop_down.set_model(Gtk.StringList.new([c.title for c in found]))
                self.drop_down.set_selected(replay.position(found, self.year))
            finally:
                self._setting = False
        self.drop_down.set_visible(len(found) > 1)

    def _on_selected(self, drop_down, _pspec):
        position = drop_down.get_selected()
        if self._setting or not 0 <= position < len(self._choices):
            return
        year = self._choices[position].id
        page = self._page() if self._page is not None else None
        if year == self.year or page is None:
            return
        self.year = year
        self._title(year or self._latest)  # the year asked for, whatever its answer
        page.start_over()


def create(item):
    """The Replay page, pushed for `item` (replay_item()'s): the latest year's, titled
    Replay until the answer names its year."""
    menu = YearMenu()
    page = ShelvesPage(replay.page_title(None), menu.fetch, root=False, icon_name=ICON_NAME,
                       hero=False, empty_title=_('No Replay Yet'),
                       empty_description=_('Replay appears once Apple Music has enough of '
                                           'your listening history for the year'))
    menu.attach(page)
    page.year_menu = menu
    page.item = item
    return page
