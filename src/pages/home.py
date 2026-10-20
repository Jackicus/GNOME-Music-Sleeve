# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicHomePage: the library's shelves, one under another, as on music.apple.com's Home,
with Recently Played asked of Apple each time the page is shown, and Refresh."""

import logging

from gi.repository import Adw, Gtk

from .. import home
from ..backend.errors import EngineError
from ..remote import fetch_shelf_art
from ..widgets.shelf import ShelfColumn
from ..widgets.util import HeaderTitle, MappedHandlers, connect_weak
from . import SignInOffer, app, signed_out

log = logging.getLogger(__name__)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/home.ui')
class HomePage(Adw.NavigationPage):
    """Every shelf of the library with items in it, in library.json's order (Apple's
    recommendations, then Heavy Rotation, Recently Added…), the first as large cards, each
    offering See All, and Recently Played after the first (src/home.py: arrange()).

    The shelves are a ShelfColumn under the title: a reload keeps each shelf's widget (moved
    into place, its tiles rebound rather than rebuilt), and new ones are bound a frame apart
    after the first few. The loading and empty states follow the library's state, as the grid
    pages' do (the first sync filling an empty library is loading). The header bar shows the
    title while the big one is out of view.

    Recently Played is Engine.recently_played(): the answer kept from last time shows as the
    page is first shown, and Apple is asked again whenever the page is shown with an answer a
    minute old (home.Throttle), never holding up the library's shelves. The answer comes into
    the one shelf in place (home.RecentlyPlayed), so nothing is built again; an answer that
    would move the page under the user (the shelf coming or going above where they scrolled
    to) or take the focus (it is in the shelf) waits for the next time the page is shown
    (home.hold_back()). While the engine is down or starting the kept answer shows, and the
    page asks once the engine is up and signed in; signed out there is no Recently Played,
    and nothing is asked. No failure is toasted: the shelf stays as it was.

    Refresh (the header bar's button, and F5: refresh()) asks Apple for Recently Played past
    the throttle and has the sync read the library's shelves again (Application.start_sync's
    shelves pass, which starts the engine when it is down and says why when it fails). Signed
    out it offers the sign-in, as a status page's button would; in the demo it reads the
    invented answer again. It is never made insensitive (the focus would be lost).
    """

    __gtype_name__ = 'AppleMusicHomePage'

    header_bar = Gtk.Template.Child()
    refresh_button = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    empty_page = Gtk.Template.Child()
    scrolled_window = Gtk.Template.Child()
    shelves_box = Gtk.Template.Child()
    title_label = Gtk.Template.Child()

    def __init__(self, library, title, icon_name=None):
        super().__init__(title=title)
        self._library = library
        self._column = ShelfColumn(self.shelves_box, anchor=self.title_label)
        self._recent = home.RecentlyPlayed()
        self._throttle = home.Throttle()
        self._answer = None  # the Recently Played answer in hand
        self._pending = None  # one held back until the page is shown again (hold_back)
        self._task = None  # the ask under way
        self._art_task = None  # the shelf's thumbnails being fetched
        self._wanted = False  # Refresh asked while the engine could not answer
        self.title_label.set_label(title)
        self.empty_page.set_icon_name(icon_name)
        self._sign_in = SignInOffer(self.empty_page)  # Sign In… while signed out
        self._header_title = HeaderTitle(self.header_bar, self.title_label, self.scrolled_window)
        # The library and the engine outlive the window: the page follows them only while it
        # is shown, and catches up as it is shown again (do_map).
        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._update)
        self._handlers.add(library, 'notify::syncing', self._update)
        self._handlers.add(library, 'changed', self._on_library_changed)
        application = app()
        if application is not None and not application.demo:
            self._handlers.add(application.settings,
                               'changed::' + application.account_key('signed-in'),
                               self._on_account_changed)
            self._handlers.add(application.engine, 'notify::state', self._on_engine_changed)
            self._handlers.add(application.engine, 'notify::authorized',
                               self._on_engine_changed)
        connect_weak(self.refresh_button, 'clicked', self._on_refresh_clicked)
        self._update()

    def do_map(self):
        Adw.NavigationPage.do_map(self)
        if signed_out():
            self._forget()
        elif self._pending is not None:
            self._show_recent(self._pending, hold=False)  # shown afresh: nothing moves
        elif self._art_task is None and self._recent.shelf.items.get_n_items():
            self._fetch_art()  # what was left to fetch when the page was hidden
        self._update()
        self.ask()

    def do_unmap(self):
        if self._art_task is not None and not self._art_task.done():
            self._art_task.cancel()
        self._art_task = None
        Adw.NavigationPage.do_unmap(self)

    # Recently Played.

    def _loading(self):
        return self._task is not None and not self._task.done()

    def ask(self, force=False):
        """Ask for Recently Played: the kept answer when there is none in hand, then Apple
        when it is due (home.Throttle), or past the throttle with `force` (Refresh, or one
        still wanted: _wanted). Nothing while an ask is under way (a forced one is made once
        it ends), signed out, or without an application."""
        application = app()
        if application is None or getattr(application, 'engine', None) is None:
            return
        force = force or self._wanted
        if self._loading():
            self._wanted = force
            return
        if signed_out():
            self._forget()
            return
        if not force and ((self._answer is not None and application.demo)
                          or not self._throttle.due(self._answer)):
            return
        self._wanted = False
        self._task = application.spawn(self._load(self._answer is not None, force))

    async def _load(self, refresh, force=False):
        """One ask (Apple's answer with `refresh`, else the kept one), shown; after the kept
        one, Apple's when it is due or forced. A forced ask the engine could not answer
        (down, starting, signed out) is made once it can (_on_engine_changed)."""
        application = app()
        try:
            answer = await application.engine.recently_played(refresh=refresh)
        except EngineError as error:
            log.info('Recently Played: %s', error)
            self._throttle.failed(error)
            if force and error.code in ('engine-down', 'not-signed-in'):
                self._wanted = True
            return
        if refresh:
            self._throttle.answered()
        self._show_recent(answer)
        if not refresh:
            if answer.get('stale'):
                # Apple was asked just now, in vain: asked again once the engine is up, or
                # the next time the page is shown.
                self._wanted = self._wanted or force
                return
            if force or (not application.demo and self._throttle.due(answer)):
                await self._load(True, force)
                return
        if self._wanted:
            application.spawn(self._ask_later())

    async def _ask_later(self):
        # A Refresh that came while an ask was under way: made once that one has ended.
        self.ask()

    def _show_recent(self, answer, hold=True):
        """Show an answer in the shelf, in place; with `hold`, keep it for the next map when
        showing it now would move the page or take the focus (home.hold_back())."""
        self._answer = answer
        if hold:
            will_show = bool(self._recent.items_for(answer, self._library)[0])
            shown = self._recent.shelf in self._column.shelves
            adjustment = self.scrolled_window.get_vadjustment()
            if home.hold_back(shown, will_show, adjustment.get_value() > 0,
                              self._focus_in_recent()):
                self._pending = answer
                return
        self._pending = None
        self._recent.show(answer, self._library)
        self._update()
        self._fetch_art()

    def _fetch_art(self):
        if self._art_task is not None and not self._art_task.done():
            self._art_task.cancel()
        self._art_task = app().spawn(fetch_shelf_art([self._recent.shelf]))

    def _focus_in_recent(self):
        widget = self._column.widget_for(self._recent.shelf)
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        return widget is not None and focus is not None and (
            focus is widget or focus.is_ancestor(widget))

    def _forget(self):
        """The account signed out: no Recently Played, nothing held, nothing under way."""
        if self._loading():
            self._task.cancel()
        self._task = None
        self._answer = self._pending = None
        self._wanted = False
        if self._recent.shelf.items.get_n_items():
            self._recent.clear()
            self._update()

    def _on_account_changed(self, *_args):
        if signed_out():
            self._forget()
        else:
            self.ask()

    def _on_engine_changed(self, engine, _pspec):
        # The engine came up (or was authorized): what could not be asked is asked now.
        if engine.state == 'up' and engine.authorized:
            self.ask()

    def _on_library_changed(self, *_args):
        # A load or a reload: the shelf's items that the library has are the library's Items.
        if self._answer is not None and self._pending is None:
            self._recent.show(self._answer, self._library)
        self._update()

    # Refresh.

    def refresh(self):
        """Refresh (see the class): Recently Played and the library's shelves asked again."""
        application = app()
        if application is None:
            return
        if application.demo:
            self.ask(force=True)
        elif signed_out():
            application.activate_action('sign-in', None)
        else:
            application.start_sync(shelves=True)
            self.ask(force=True)

    def _on_refresh_clicked(self, _button):
        self.refresh()

    # The shelves.

    def _update(self, *_args):
        library = self._library
        shelves = home.arrange(library.shelves, self._recent.shelf)
        if shelves != self._column.shelves:
            self._column.show(shelves, hero_first=True)
        if shelves:
            name = 'items'
        elif library.state == 'loading' or (library.state == 'empty' and library.syncing):
            name = 'loading'  # the first sync is on its way
        else:
            name = 'empty'
        self.stack.set_visible_child_name(name)
