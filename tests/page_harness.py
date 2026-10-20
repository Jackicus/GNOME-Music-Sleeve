# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the page tests share: stand-ins for the application, the engine and the window the
pages reach (pages.app() and get_root()), invented library data, and PageTestCase, a presented
window over an asyncio loop on GLib's (as the app runs).

The engine stand-in answers each request from `engine.answers[name]`: a value, an exception
to raise, or a function of the request's arguments (a coroutine function is awaited, so a
test can hold an answer back); a request without an answer raises engine-down, as the demo
engine does. `engine.calls` lists the requests in order. The application records what it is
asked (actions, reports, toasts, syncs) and runs spawn()ed coroutines as tasks that settle()
waits for.

The application here is not registered and has an ID of its own, so the lifetime tests'
(test_page_lifetime.py) can live beside it; stand_in_app() makes it the default application,
which is how a page finds it. Any widget test that builds a page calls that, PageTestCase and
test_tiles alike.
"""

import asyncio
import copy
import inspect
import time
import unittest

from tests.gtk import SCHEMA_ID, pump, requires_gtk

from gi.repository import Gio, GObject

from applemusic.backend.errors import EngineError
from applemusic.player import NowPlaying

_stand_ins = {}


class Player(GObject.Object):
    """What the pages follow of app.player: the item playing (a NowPlaying, or None), which a
    test sets (`playing(track)` makes one from a track's dict), and the song whose preview
    plays (`preview`); the preview commands are recorded in `previews` and set `preview` as
    the engine's events would."""

    track = GObject.Property(type=NowPlaying, default=None)
    preview = GObject.Property(type=str, default='')

    def __init__(self):
        super().__init__()
        self.previews = []  # ('start', song id, url) or ('stop',), per command

    async def start_preview(self, song_id, url):
        self.previews.append(('start', song_id, url))
        self.preview = song_id

    async def stop_preview(self):
        self.previews.append(('stop',))
        self.preview = ''


def playing(data):
    """A NowPlaying for a track dict (page_harness.track()), as the Player reports the
    item: the same keys as the bridge's Track shape (id, catalogId, title…)."""
    return NowPlaying(dict(data))


def classes():
    """The stand-in classes, made once GTK is known to work: Engine, App, Window."""
    if _stand_ins:
        return _stand_ins
    from gi.repository import Adw, Gtk

    from applemusic.recent_searches import RecentSearches

    class Engine(GObject.Object):
        __gsignals__ = {
            'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
        }

        state = GObject.Property(type=str, default='down')
        authorized = GObject.Property(type=bool, default=False)
        headless = GObject.Property(type=bool, default=True)

        def __init__(self):
            super().__init__()
            self.calls = []
            self.answers = {}
            self.suggestion_requests = []
            self.search_requests = []
            self.recent_requests = []  # each recently_played()'s refresh
            self.start_error = None  # an EngineError a start raises

        async def _answer(self, name, *args):
            self.calls.append(name)
            answer = self.answers.get(name, EngineError('engine-down'))
            if callable(answer) and not isinstance(answer, BaseException):
                answer = answer(*args)
                if inspect.isawaitable(answer):
                    answer = await answer
            if isinstance(answer, BaseException):
                raise answer
            return copy.deepcopy(answer)

        async def start(self, visible=None):
            self.calls.append('start')
            self.state = 'starting'
            await asyncio.sleep(0)
            if self.start_error is not None:
                self.state = 'down'
                raise self.start_error
            self.state = 'up'

        async def item(self, kind, item_id):
            return await self._answer('item', kind, item_id)

        async def suggest(self, text):
            return await self._answer('suggest', text)

        async def search(self, text, limit=None, kind=None, offset=0):
            # Each search's arguments, beside the answer's name in `calls`.
            self.search_requests.append({'text': text, 'limit': limit, 'kind': kind,
                                         'offset': offset})
            return await self._answer('search', text, kind, offset)

        async def landing(self, refresh=False):
            return await self._answer('landing')

        async def browse(self, refresh=False):
            return await self._answer('browse', refresh)

        async def made_for_you(self, refresh=False):
            return await self._answer('made_for_you', refresh)

        async def radio(self, refresh=False):
            return await self._answer('radio', refresh)

        async def charts(self, refresh=False):
            return await self._answer('charts', refresh)

        async def recently_played(self, refresh=False):
            # Each ask's refresh beside its name in `calls`.
            self.recent_requests.append(refresh)
            return await self._answer('recently_played', refresh)

        async def category(self, category_id, refresh=False):
            return await self._answer('category', category_id, refresh)

        async def artist_page(self, artist_id, refresh=False):
            return await self._answer('artist_page', artist_id)

        async def artist_view(self, artist_id, view):
            return await self._answer('artist_view', artist_id, view)

        async def album_page(self, album_id, song_id=None, refresh=False):
            return await self._answer('album_page', album_id, song_id)

        async def album_view(self, album_id, view):
            return await self._answer('album_view', album_id, view)

        async def catalog_artist(self, name, song_ids):
            return await self._answer('catalog_artist', name, song_ids)

        async def is_favourite_artist(self, artist_id):
            return await self._answer('is_favourite_artist', artist_id)

        async def playlist_suggestions(self, playlist_id, refresh=False, limit=16, offered=(),
                                       selected=(), more=False, basis=None, previewed=()):
            # Each request's arguments, beside the answer's name in `calls`.
            self.suggestion_requests.append({'refresh': refresh, 'limit': limit,
                                             'offered': list(offered),
                                             'selected': list(selected), 'more': more,
                                             'basis': basis, 'previewed': list(previewed)})
            if more:
                return await self._answer('more_suggestions', playlist_id)
            return await self._answer('playlist_suggestions', playlist_id, refresh)

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id='io.github.jackicus.MusicSleeve.PageTest',
                             flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.engine = Engine()
            self.player = Player()
            self.settings = Gio.Settings.new(SCHEMA_ID)
            self.demo = False
            self.tasks = []
            self.actions = []
            self.reported = []
            self.toasts = []
            self.syncs = []  # each start_sync()'s keyword arguments
            self.recent_searches = RecentSearches()  # in memory: never the real cache

        def reset(self):
            self.engine = Engine()
            self.recent_searches = RecentSearches()
            self.player.track = None
            self.player.preview = ''
            self.player.previews = []
            self.demo = False
            self.tasks = []
            self.actions = []
            self.reported = []
            self.toasts = []
            self.syncs = []
            self.settings.set_boolean('signed-in', True)

        def account_key(self, name):
            return name

        def spawn(self, coro):
            task = asyncio.get_running_loop().create_task(coro)
            self.tasks.append(task)
            return task

        def report(self, error):
            self.reported.append(error.code)

        def player_command(self, coro, on_error=None):
            async def command():
                try:
                    await coro
                except EngineError as error:
                    self.report(error)
            return self.spawn(command())

        def toast(self, title, *_args):
            self.toasts.append(title)

        def refuse_in_demo(self):
            return self.demo

        def start_sync(self, **kwargs):
            self.syncs.append(kwargs)
            return None

        def activate_action(self, name, _parameter=None):
            self.actions.append(name)

        def start_engine(self):
            if self.demo:
                return None

            async def start():
                try:
                    await self.engine.start()
                except EngineError as error:
                    self.report(error)

            return self.spawn(start())

    class ItemActions:
        def __init__(self):
            self.asked = []
            self.queue_entries = []  # each menu's queue entry (Up Next's rows)
            self.went = []  # (obj, kind) per go_to()
            self.added = []  # (playlist id, song id, title) per add_to_playlist()
            self.add_succeeds = True  # what the write's task answers
            self.library_adds = []  # (Item, its task) per add_to_library(): the test ends it
            self.moved = []  # (playlist id, from, to, at_once) per move_in_playlist()
            self.favourites = []  # (artist Item, favourite, its task) per favourite_artist()
            self.ratings = {}  # what known_rating() answers, by (kind, id)

        def add_to_playlist(self, playlist_id, song_id, title='', kind='song'):
            self.added.append((playlist_id, song_id, title))
            # The task the real one answers: whether the write succeeded.
            task = asyncio.get_running_loop().create_future()
            task.set_result(self.add_succeeds)
            return task

        def favourite_artist(self, obj, favourite, quiet=False, target=None):
            task = asyncio.get_running_loop().create_future()
            self.favourites.append((obj, favourite, task))
            return task

        def known_rating(self, rated):
            return self.ratings.get(tuple(rated))

        def add_to_library(self, obj):
            task = asyncio.get_running_loop().create_future()
            self.library_adds.append((obj, task))
            return task

        def move_in_playlist(self, playlist, from_index, to_index, at_once=False):
            # The real one's model change (PlaylistOrder.move()), nothing written.
            from applemusic.library import moved

            self.moved.append((playlist.id, from_index, to_index, at_once))
            return playlist.reorder(moved(len(playlist.track_ids()), from_index, to_index))

        def menu_for(self, obj, queued=False, queue_entry=None):
            self.asked.append(obj)
            self.queue_entries.append(queue_entry)
            menu = Gio.Menu()
            menu.append('Invented Action', 'win.invented')
            return menu

        def go_to(self, obj, kind):
            self.went.append((obj, kind))

        def show_artist(self, obj):
            self.went.append((obj, 'link to artist'))

    class Window(Adw.Window):
        def __init__(self):
            super().__init__(default_width=1000, default_height=700)
            self.navigation_view = Adw.NavigationView()
            self.root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.root_page = Adw.NavigationPage(title='Root', child=self.root_box)
            self.navigation_view.add(self.root_page)
            self.navigation_view.replace([self.root_page])
            self.set_content(self.navigation_view)
            self.item_actions = ItemActions()
            self.reset()

        def reset(self):
            self.item_actions.went = []
            self.item_actions.added = []
            self.item_actions.library_adds = []
            self.item_actions.moved = []
            self.item_actions.favourites = []
            self.item_actions.ratings = {}
            self.opened = []
            self.artist_pages = []  # open_artist_page()'s, Apple Music's pages of artists
            self.shelves_opened = []
            self.played = []
            self.started_with = []  # each play request's start_id
            self.songs_opened = []

        def content_width(self):
            return self.navigation_view.get_width()

        def open_item(self, item):
            self.opened.append(item)

        def open_artist_page(self, item):
            self.artist_pages.append(item)

        def open_shelf(self, shelf):
            self.shelves_opened.append(shelf)

        def open_songs(self, text=''):
            self.songs_opened.append(text)

        def play_request(self, play, start_with=None, shuffle=None, start_id=None):
            self.played.append((play, start_with, shuffle))
            self.started_with.append(start_id)

    _stand_ins.update(Engine=Engine, App=App, Window=Window)
    return _stand_ins


def stand_in_app():
    """The stand-in application, made once and made the default one, which is how a page
    reaches it (pages.app() is Gio.Application.get_default()). Any widget test that builds a
    page calls this: a module that leans on the default application another module left behind
    passes in the suite and fails on its own."""
    stand_ins = classes()
    if 'app' not in stand_ins:
        stand_ins['app'] = stand_ins['App']()
    stand_ins['app'].set_default()
    return stand_ins['app']


def find(widget, cls):
    """The first widget of class cls in widget's tree (widget included), depth first."""
    if isinstance(widget, cls):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = find(child, cls)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def find_all(widget, cls):
    """Every widget of class cls in widget's tree, depth first."""
    found = [widget] if isinstance(widget, cls) else []
    child = widget.get_first_child()
    while child is not None:
        found.extend(find_all(child, cls))
        child = child.get_next_sibling()
    return found


# -- invented data -----------------------------------------------------------------------

def track(album_id, number, disc=1, title=None):
    return {'id': f'{album_id}.t{disc}.{number}', 'catalogId': None,
            'title': title or f'Song {number}', 'artist': 'Invented Artist', 'album': album_id,
            'trackNumber': number + 1, 'discNumber': disc, 'durationMs': 180000,
            'durationLabel': '3:00', 'explicit': False, 'index': number, 'thumb': None}


def album(number, tracks=3, year=None, discs=1, kind='album'):
    album_id = f'l.{kind}{number:03d}'
    play = {'kind': kind, 'id': album_id}
    groups = [{'name': '', 'play': play,
               'entries': [track(album_id, i, disc) for i in range(tracks)]}
              for disc in range(1, discs + 1)] if tracks else []
    return {'id': album_id, 'kind': kind, 'title': f'Invented {kind.title()} {number:03d}',
            'subtitle': 'Invented Artist', 'year': year or 2000 + number % 20,
            'genre': 'Pop', 'art': None, 'thumb': None, 'play': play, 'groups': groups}


def artist(albums, artist_id='l.artist001'):
    groups = [{'name': entry['title'], 'play': entry['play'],
               'entries': entry['groups'][0]['entries'] if entry['groups'] else []}
              for entry in albums]
    return {'id': artist_id, 'kind': 'artist', 'title': 'Invented Artist', 'art': None,
            'thumb': None, 'groups': groups, 'play': {}}


def artist_answer(artist_id='42', songs=4, group=False, banner=None, favourite=False):
    """An invented catalog artist's page, as Engine.artist_page answers (normalize.artist_page):
    a latest release, `songs` top songs, Essential Albums, Albums (with more to fetch) and
    Similar Artists; `banner` its banner dict (normalize.artist_banner's), None by default;
    `favourite` whether the account has the artist as one (None: the answer does not say)."""
    def entry(kind, number, **extra):
        data = {'id': f'{kind}{number}', 'kind': kind, 'title': f'Invented {kind} {number}',
                'subtitle': '2026', 'year': 2026, 'art': None, 'thumb': None,
                'play': {'kind': kind, 'id': f'{kind}{number}'}, 'groups': []}
        data.update(extra)
        return data

    return {
        'id': artist_id,
        'artist': entry('artist', 0, id=artist_id, title='Invented Artist', subtitle='',
                        summary='An invented biography.', genre='Pop',
                        origin='Invented Town, Nowhere', bornOrFormed='1 May 2001',
                        isGroup=group, play={'kind': 'artist', 'id': artist_id}),
        'banner': banner,
        'favourite': favourite,
        'latest': {'key': 'latest-release', 'title': 'Latest Release',
                   'item': entry('album', 99, releaseDate='2026-09-24', trackCount=12)},
        'topSongs': {'key': 'top-songs', 'title': 'Top Songs', 'more': False,
                     'items': [entry('song', 900 + n, id=str(900 + n), album='Invented Album',
                                     play={'kind': 'song', 'id': str(900 + n)})
                               for n in range(songs)]},
        'shelves': [
            {'key': 'featured-albums', 'title': 'Essential Albums', 'more': False,
             'items': [entry('album', 1, subtitle='An invented line about it.')]},
            {'key': 'full-albums', 'title': 'Albums', 'more': True,
             'items': [entry('album', n) for n in range(1, 4)]},
            {'key': 'similar-artists', 'title': 'Similar Artists', 'more': False,
             'items': [entry('artist', 43, subtitle='')]},
        ],
    }


@requires_gtk
class PageTestCase(unittest.IsolatedAsyncioTestCase):
    """A presented stand-in window, the stand-in application as the default one, animations
    off; each test starts with a fresh engine, signed in, not in demo mode."""

    @classmethod
    def setUpClass(cls):
        from gi.repository import Gtk

        cls.app = stand_in_app()
        cls.gtk_settings = Gtk.Settings.get_default()
        cls.animations = cls.gtk_settings.props.gtk_enable_animations
        cls.gtk_settings.props.gtk_enable_animations = False
        cls.window = classes()['Window']()
        cls.window.present()
        deadline = time.monotonic() + 2
        while not cls.window.get_mapped() and time.monotonic() < deadline:
            pump(20)
            time.sleep(0.005)

    @classmethod
    def tearDownClass(cls):
        cls.window.destroy()
        pump()
        cls.gtk_settings.props.gtk_enable_animations = cls.animations
        del cls.window

    def setUp(self):
        from applemusic.library import Library

        self.app.set_default()  # the pages' app (pages.app()), whichever was made first
        self.app.reset()
        self.window.reset()
        self.library = Library()
        self._roots = []  # the pages show_root() added to the navigation view

    async def asyncTearDown(self):
        # A turn of the main loop before the teardown: the first entry to take the focus in a
        # process binds Wayland's text input, and when it is torn down before the loop has read
        # the compositor's answer, GTK's text input reaches it after it is gone and crashes
        # (docs/notes.md, #254). The turn is what matters; the focus moves off the page too.
        self.window.set_focus(None)
        await self.turn()
        self.window.navigation_view.replace([self.window.root_page])
        for page in self._roots:
            self.window.navigation_view.remove(page)
        child = self.window.root_box.get_first_child()
        while child is not None:
            self.window.root_box.remove(child)
            child = self.window.root_box.get_first_child()
        await self.settle()
        self.app.settings.reset('signed-in')

    async def until(self, predicate, timeout=1.0, interval=0.005):
        """Run GTK's main context and the asyncio loop until predicate() holds (True), or
        timeout seconds have gone (False)."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                return False
            pump(10)
            await asyncio.sleep(interval)
        return True

    async def until_focused(self, widget):
        """Wait for the window's focus to be in widget (an entry), then a tenth of a second
        more, for the compositor's answer to the text input the process's first focused
        entry binds: a page torn down before it is read crashes GTK (docs/notes.md). True
        when the focus came."""
        def inside():
            focus = self.window.get_focus()
            return focus is not None and (focus is widget or focus.is_ancestor(widget))

        focused = await self.until(inside)
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            pump(10)
            await asyncio.sleep(0.005)
        return focused

    def focused_in(self, view):
        """What the row or tile of view (a grid, a list, a table) with the window's focus
        shows, when that widget is on screen (mapped; a recycled one scrolled away is not):
        else None."""
        from applemusic.widgets import context_menu

        focus = self.window.get_focus()
        if focus is None or not focus.is_ancestor(view) or not focus.get_mapped():
            return None
        found = context_menu.find(view, focus)
        return found[1] if found is not None else None

    async def escape_from_filter(self, page, view, focused, text):
        """With the focus on `focused` (an item of view's model, far down it), Ctrl+F, the
        filter set to `text`, then Escape in its entry: True once the focus is on
        `focused` again, on screen (FilterBar.set_focus_return())."""
        from gi.repository import Gtk

        model = view.get_model()
        position = next(n for n in range(model.get_n_items()) if model.get_item(n) is focused)
        view.grab_focus()
        if isinstance(view, Gtk.ColumnView):
            view.scroll_to(position, None, Gtk.ListScrollFlags.FOCUS, None)
        else:
            view.scroll_to(position, Gtk.ListScrollFlags.FOCUS, None)
        self.assertTrue(await self.until(lambda: self.focused_in(view) is focused),
                        self.window.get_focus())
        self.assertTrue(page.focus_filter())  # Ctrl+F
        self.assertTrue(await self.until_focused(page.filter_bar.entry))
        page.filter_bar.set_text(text)
        await self.turn()
        page.filter_bar.entry.emit('stop-search')  # Escape
        return await self.until(lambda: self.focused_in(view) is focused)

    async def turn(self, rounds=5):
        """Let what is pending run: GTK's main context, and the tasks up to their next wait."""
        for _round in range(rounds):
            pump(10)
            await asyncio.sleep(0)

    async def settle(self):
        """Let every task spawned so far finish (cancelling one still waiting after half a
        second). GTK's main context runs while they do: a task waiting for a frame
        (next_frame()) or a GLib timeout is only woken by it, and asyncio's loop alone would
        leave it waiting out the half second and cancel it."""
        for _round in range(5):
            pump(10)
            tasks, self.app.tasks = self.app.tasks, []
            if not tasks:
                await asyncio.sleep(0)
                continue
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                _done, pending = await asyncio.wait(tasks, timeout=0.005)
                if not pending:
                    break
                pump(10)
            for task in tasks:
                if not task.done():
                    task.cancel()
        pump(10)

    async def push(self, page):
        """Push page and wait for it to be shown."""
        self.window.navigation_view.push(page)
        self.assertTrue(await self.until(page.get_mapped), f'{type(page).__name__} not shown')
        return page

    async def show_root(self, page):
        """Show page as the navigation view's root, as the window shows a destination's."""
        self.window.navigation_view.add(page)
        self._roots.append(page)
        self.window.navigation_view.replace([page])
        self.assertTrue(await self.until(page.get_mapped), f'{type(page).__name__} not shown')
        return page

    async def show_at(self, page, width, height=640):
        """Show page as the root of a stand-in window of its own, `width` by `height` (the
        shared one is 1000 by 700), for a page's breakpoints; the window goes when the test
        ends."""
        window = classes()['Window']()
        window.set_default_size(width, height)
        window.navigation_view.add(page)
        window.navigation_view.replace([page])
        window.present()
        self.addCleanup(window.destroy)
        self.assertTrue(await self.until(page.get_mapped, 2), f'{type(page).__name__} not shown')
        return page
