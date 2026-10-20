# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicShelvesPage: a page of shelves the engine answers with: New (engine.browse()),
Made for You (engine.made_for_you()), Radio (engine.radio(), with a shelf of the library's
own: pages/radio.py), a search category (engine.category(id)), the Charts page and the
pages More to Explore's links open (engine.grouping(id), engine.multiroom(id):
pages/editorial.py).

Unlike Home, whose shelves are the library's, these pages own their Items: the engine's
shelf dicts are wrapped (remote.remote_shelves), their artwork pointed at <cache>/remote-art/
(remote.remote_item) and fetched in the background (remote.fetch_shelf_art), each tile
following its Item as its thumbnail arrives. The page shows a spinner while the answer is on
its way, a status page with the fitting button when the engine cannot answer
(widgets/engine_status.py), and the shelves otherwise, then the answer's rows of links
(`links`: More to Explore, widgets/explore.py); a refresh button in the header bar asks
Apple again past the day-long cache.
"""

import logging
from datetime import UTC, datetime
from gettext import gettext as _

from gi.repository import Adw, Gtk

from .. import explore
from ..backend.errors import EngineError
from ..backend.normalize import ANSWER_MAX_AGE, answer_expired
from ..remote import fetch_shelf_art, remote_shelves
from ..widgets.engine_status import EngineStatus
from ..widgets.explore import ExploreBox
from ..widgets.shelf import ShelfColumn
from ..widgets.util import HeaderTitle, MappedHandlers, connect_weak, next_frame
from . import app

log = logging.getLogger(__name__)


def expired(answer, now=None):
    """Whether an answer the page shows was fetched longer than a day ago (its `cached`
    stamp, normalize.ANSWER_MAX_AGE), or its `expires` has passed (Radio's live programmes:
    normalize.answer_expired): the page asks again as it is shown. An answer without a
    stamp never expires."""
    if answer_expired(answer, now):
        return True
    stamp = answer.get('cached') if isinstance(answer, dict) else None
    if not isinstance(stamp, str):
        return False
    try:
        when = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
    except ValueError:
        return False
    now = now or datetime.now(UTC)
    return (now - when).total_seconds() > ANSWER_MAX_AGE


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/shelves.ui')
class ShelvesPage(Adw.NavigationPage):
    """ShelvesPage(title, fetch, …): `fetch(refresh)` is a coroutine function answering
    {shelves: [{key, title, items}], cached} (an Engine method), called when the page is first
    shown, when it is shown again with an answer more than a day old (the app runs for days),
    and by the refresh button (with refresh=True). An answer Apple could not refresh
    (`stale`) is shown as it is. `root` false for a page pushed over another (a category),
    whose requests are cancelled when it is hidden. `hero` makes the first shelf large cards,
    as Home's. `icon_name` and the empty texts are the status page's. The header bar shows
    the title while the big one is out of view (widgets.util.HeaderTitle). The page watches
    the engine while mapped: an engine-down or signed-out state loads itself once the engine
    is up or signed in.

    Refresh is never made insensitive (the focus would be lost): it does nothing while a
    request is under way, and what the status page's button does while the engine is down or
    the account signed out. The demo has no engine: no Refresh.

    `arrange(shelves)`, when given, makes the shelves shown out of the engine's (ShelfModels;
    [] while it has not answered), for a page with shelves of its own beside Apple's (Radio's
    Recently Played). It is asked again as the page is shown, and by rearrange(), which
    `follow(obj, signal)` runs whenever obj emits signal while the page is shown. What it
    makes of [] is shown in place of the status page when the engine cannot answer (Refresh
    and the engine coming up still do what the status page's button would), and the spinner
    gives way to it while a request is under way.

    The answer's rows of links (`links`) follow the shelves (widgets.explore.ExploreBox), as
    `explore(links)` makes them Sections (explore.sections by default; New's has Top Charts
    among them).
    """

    __gtype_name__ = 'AppleMusicShelvesPage'

    header_bar = Gtk.Template.Child()
    refresh_button = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    status_button = Gtk.Template.Child()
    scrolled_window = Gtk.Template.Child()
    shelves_box = Gtk.Template.Child()
    title_label = Gtk.Template.Child()

    def __init__(self, title, fetch, root=True, icon_name=None, hero=True, empty_title=None,
                 empty_description=None, arrange=None, explore=explore.sections):
        super().__init__(title=title)
        self.item = None  # a category page's category, for the window's double-push guard
        self._fetch = fetch
        self._explore = explore
        self._root = root
        self._hero = hero
        self._icon_name = icon_name or 'view-grid-symbolic'
        self._empty = (empty_title or _('Nothing Here'), empty_description or '')
        self._arrange = arrange
        self._answer = None  # the answer shown
        self._task = None  # the fetch running
        self._art_task = None  # the thumbnails being fetched for the engine's shelves
        self._remote = []  # the engine's shelves, as ShelfModel objects
        self._shelves = []  # the shelves shown (the engine's, arranged)
        self._status = None  # the failure the status page shows (_show_status's arguments)
        self._handlers = MappedHandlers(self)
        # What the page says when the engine cannot answer, and what its button does.
        self._engine_status = EngineStatus(app(), self._show_status, self.load, {
            'engine-down': _('Start the engine to load this page'),
            'not-signed-in': _('This page appears once you sign in to Apple Music'),
            'failed': _('Could Not Load This Page'),
        })
        self._column = ShelfColumn(self.shelves_box, anchor=self.title_label)
        # After the shelves: the column places them right after the title.
        self.explore_box = ExploreBox()
        self.shelves_box.append(self.explore_box)
        self.title_label.set_label(title)
        self._header_title = HeaderTitle(self.header_bar, self.title_label, self.scrolled_window)
        self.refresh_button.set_visible(not app().demo)
        # Connected weakly (widgets/util.py): a bound method would keep a popped page alive.
        connect_weak(self.refresh_button, 'clicked', self._on_refresh_clicked)
        connect_weak(self.status_button, 'clicked', self._on_status_clicked)

    # The engine outlives the page: it is watched only while the page is shown.

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        self._engine_status.watch()  # may load again: the engine came up meanwhile
        if not self._loading() and (self._answer is None or expired(self._answer)):
            self.load()
        elif self._remote and self._art_task is None:
            self._art_task = app().spawn(fetch_shelf_art(self._remote))
        self.rearrange()

    def do_unmap(self):
        self._engine_status.unwatch()
        Adw.NavigationPage.do_unmap(self)

    def do_hidden(self):
        # A category page left (popped or covered; not just unmapped: a push maps, unmaps
        # and maps a page again): its requests stop, asked again if it is shown again.
        if not self._root:
            if self._loading():
                self._task.cancel()
                self._task = None
                self._engine_status.clear()
            if self._art_task is not None and not self._art_task.done():
                self._art_task.cancel()
                self._art_task = None
        Adw.NavigationPage.do_hidden(self)

    def _loading(self):
        return self._task is not None and not self._task.done()

    def follow(self, obj, signal):
        """Arrange the shelves again (rearrange()) whenever `obj` emits `signal` while the
        page is shown (weakly: obj may outlive the page)."""
        self._handlers.add(obj, signal, self.rearrange)

    def rearrange(self, *_args):
        """Show again what `arrange` makes of the engine's shelves, or of none while the
        status page would show (nothing without `arrange`)."""
        if self._arrange is None:
            return
        if self._answer is not None:
            self._present()
        elif self._status is not None:
            self._show_status(*self._status)

    def load(self, refresh=False):
        """Ask for the shelves (again, past the cache, with `refresh`)."""
        if self._loading():
            self._task.cancel()
        self._task = app().spawn(self._load(refresh))

    def start_over(self):
        """Ask for the shelves anew, those shown dropped (the spinner, then the answer or
        the status page): what the page asks for has changed (the Charts page's genre)."""
        if self._art_task is not None and not self._art_task.done():
            self._art_task.cancel()
        self._art_task = None
        self._answer = None
        self._remote = []
        self._shelves = []
        self._status = None
        self._column.show([])
        self.explore_box.show_sections([])
        self.scrolled_window.get_vadjustment().set_value(0)
        self.load()

    async def _load(self, refresh):
        if not self._shelves:
            self._engine_status.loading()
        try:
            answer = await self._fetch(refresh)
        except EngineError as error:
            log.info('%s: %s', self.get_title(), error)
            if self._remote:
                app().report(error)  # a refresh that failed keeps what is shown
            else:
                if refresh and self._shelves:
                    app().report(error)  # the shelves of the page's own stay
                self._engine_status.fail(error)
            return
        self._answer = answer if isinstance(answer, dict) else {}
        self._show(self._answer.get('shelves'))

    def _show(self, dicts):
        remote = remote_shelves(dicts)
        if self._art_task is not None and not self._art_task.done():
            self._art_task.cancel()
        self._remote = remote
        self._status = None
        self._engine_status.clear()
        self._present()
        if remote:
            self._art_task = app().spawn(fetch_shelf_art(remote))

    def _arranged(self, shelves):
        return list(shelves) if self._arrange is None else list(self._arrange(list(shelves)))

    def _present(self, shelves=None):
        """Show the engine's shelves as `arrange` places them (or `shelves`), then the
        answer's links, or the empty state when there are neither shelves nor links."""
        shelves = self._arranged(self._remote) if shelves is None else shelves
        self._column.show(shelves, hero_first=self._hero)
        self._shelves = shelves
        links = self._answer.get('links') if isinstance(self._answer, dict) else None
        self.explore_box.show_sections(self._explore(links))
        if shelves or (links and self.explore_box.sections):
            self.stack.set_visible_child_name('items')
            app().spawn(self._focus_shelves())
        else:
            title, description = self._empty
            self._show_status('empty', title, description, None)

    async def _focus_shelves(self):
        """A focus the shelves' showing left on the scrolled window itself, into the first
        shelf once it is laid out. The stack moves the focus it held (the spinner's, the
        status page's button's) into its new child at once, before the shelves' rows exist,
        and a shelf hidden for another (a new answer) loses it: either way the scrolled window
        takes it, where no key reaches a tile and Ctrl+2 finds it in the content already."""
        for _frame in range(3):
            await next_frame(self.shelves_box)
            root = self.get_root()
            widgets = self._column.widgets
            if root is None or root.get_focus() is not self.scrolled_window or not widgets:
                return
            if widgets[0].child_focus(Gtk.DirectionType.TAB_FORWARD):
                return

    def _show_status(self, status, title, description, button):
        """The spinner ('loading'), or the status page: EngineStatus's states, or 'empty'. A
        failure shows what `arrange` makes of no shelves instead, when it makes some, and
        the spinner leaves them be."""
        if status == 'loading':
            if not self._shelves:
                self.stack.set_visible_child_name('loading')
            return
        if status != 'empty':
            self._status = (status, title, description, button)
            own = self._arranged([]) if self._arrange is not None else []
            if own:
                self._present(own)
                return
            self._column.show([])
            self._shelves = []
        self.status_page.set_icon_name(self._icon_name)
        self.status_page.set_title(title)
        self.status_page.set_description(description)
        self.status_button.set_label(button or '')
        self.status_button.set_visible(bool(button))
        self.stack.set_visible_child_name('status')

    def refresh(self):
        """Refresh (the header bar's button, and F5 through win.refresh), while the page
        offers it (not in the demo)."""
        if self.refresh_button.get_visible():
            self._on_refresh_clicked(self.refresh_button)

    def _on_refresh_clicked(self, _button):
        if self._engine_status.status in ('engine-down', 'not-signed-in'):
            self._engine_status.activate()  # Start Engine, or Sign In
        elif not self._loading():
            self.load(refresh=True)

    def _on_status_clicked(self, _button):
        self._engine_status.activate()


def category_page(item):
    """A category's page (a tile of the search landing, a banner of New, a radio show's tile
    on Radio or an artist's page), pushed over the page it was opened from: the curator's
    grouping as shelves, then its playlists (a show's: its episodes, then its playlists)."""
    page = ShelvesPage(item.title,
                       lambda refresh: app().engine.category(item.id, refresh=refresh),
                       root=False, icon_name='view-grid-symbolic', hero=False,
                       empty_title=_('Nothing Here'),
                       empty_description=_('This category has nothing to show right now'))
    page.item = item
    return page
