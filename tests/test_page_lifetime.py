# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Widget lifetimes: a page pushed and popped, or kept as a root page and dropped (past
ROOT_LIMIT, at a sign-out), a Shelf removed and a dialog closed are freed, with the rows they
bound, the context menus and More Options opened on them, a drag begun on them; Up Next's
rows go as the queue shrinks; the handlers connected weakly still run; and connect_weak()
itself.

A widget that connects its children's signals to its own bound methods (or declares Blueprint
`=> $handler()` callbacks) is never freed: the cycle runs through C (widgets/util.py). Each
lifetime test builds the widget in a presented window (a stand-in for the app's: an
Adw.NavigationView under a root page), lets it bind its rows, drops it, lets the tasks it
spawned finish, collects, and asserts that the widget, and one of its rows, has been
finalized: a GObject weak reference (GObject.Object.weak_ref()) to each has died. Not a Python
weakref, which with PyGObject 3.56 dies with the Python wrapper, as soon as Python lets go of
it, whether or not the widget itself lives on (widgets/util.py).

The handler tests let go of the Python wrapper and collect before they emit, as the app does
(a pushed page is held by the navigation view alone), so a handler that held its widget
through the first wrapper would be found dead there. The pages and dialogs reach the app
through Gio.Application.get_default() and get_root(), so the window and the application here
are stand-ins that record what they are asked (open_item, play_request, an engine start),
which the handler tests read.
"""

import asyncio
import gc
import os
import tempfile
import time
import unittest
import weakref
from datetime import UTC, datetime
from unittest import mock

from tests.gtk import SCHEMA_ID, pump, requires_gtk
from tests.page_harness import Player, artist_answer

from gi.repository import Gio, GObject

from applemusic.backend.errors import EngineError
from applemusic.widgets.util import connect_weak, weak_method


class _Emitter(GObject.Object):
    __gsignals__ = {'ask': (GObject.SignalFlags.RUN_LAST, bool, (int,))}


class _Target:
    def __init__(self):
        self.calls = []

    def on_ask(self, emitter, value, *extra):
        self.calls.append((emitter, value, extra))
        return value > 0


class _GTarget(GObject.Object):
    """A GObject with Python state, as a widget is."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def on_ask(self, _emitter, value, *extra):
        self.calls.append((value, extra))
        return value > 0

    def double(self, value):
        return value * 2


class ConnectWeakTest(unittest.TestCase):
    def test_the_methods_result_is_the_handlers(self):
        emitter, target = _Emitter(), _Target()
        connect_weak(emitter, 'ask', target.on_ask, 'extra')
        self.assertTrue(emitter.emit('ask', 1))
        self.assertFalse(emitter.emit('ask', -1))
        self.assertEqual(target.calls, [(emitter, 1, ('extra',)), (emitter, -1, ('extra',))])

    def test_the_connection_does_not_keep_the_target(self):
        emitter, target = _Emitter(), _Target()
        handler = connect_weak(emitter, 'ask', target.on_ask)
        calls = target.calls
        ref = weakref.ref(target)
        del target
        gc.collect()
        self.assertIsNone(ref())
        self.assertTrue(emitter.handler_is_connected(handler))
        self.assertFalse(emitter.emit('ask', 1))  # nothing to call: the default answer
        self.assertFalse(emitter.handler_is_connected(handler))  # and gone after that
        self.assertEqual(calls, [])

    def test_a_gobject_target_outlives_its_python_wrapper(self):
        # Held by C alone (a list store, as a widget by its parent), the target's wrapper
        # goes and a new one is made on demand: the handler follows the GObject, not the
        # wrapper it was connected with.
        emitter, target = _Emitter(), _GTarget()
        handler = connect_weak(emitter, 'ask', target.on_ask, 'extra')
        call = weak_method(target.double)
        holder = Gio.ListStore(item_type=_GTarget)
        holder.append(target)
        finalized = []
        target.weak_ref(lambda: finalized.append(True))
        del target
        gc.collect()
        self.assertTrue(emitter.emit('ask', 1))
        self.assertEqual(call(4), 8)
        self.assertEqual(holder.get_item(0).calls, [(1, ('extra',))])

        holder.remove_all()
        gc.collect()
        self.assertEqual(finalized, [True])  # the connection kept nothing
        self.assertFalse(emitter.emit('ask', 1))
        self.assertFalse(emitter.handler_is_connected(handler))
        self.assertIsNone(call(4))


# -- the widget tests' stand-ins, made once GTK is known to work ---------------------------

_stand_ins = {}


def _classes():
    if _stand_ins:
        return _stand_ins
    from gi.repository import Adw, Gtk

    class Engine(GObject.Object):
        """What the pages and dialogs ask of app.engine: down, and it says so."""

        __gsignals__ = {
            'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
        }

        state = GObject.Property(type=str, default='down')
        authorized = GObject.Property(type=bool, default=False)
        headless = GObject.Property(type=bool, default=True)
        widevine = GObject.Property(type=bool, default=True)

        def __init__(self):
            super().__init__()
            self.calls = []
            self.artist_answer = None  # what artist_page() answers: engine-down while None
            self.album_answer = None  # what album_page() answers, the same way
            self.suggestions = None  # what playlist_suggestions() answers, the same way
            self.radio_answer = None  # what radio() answers, the same way
            self.charts_answer = None  # what charts() answers, the same way

        async def start(self, visible=None):
            self.calls.append('start')
            self.state = 'up'

        async def stop(self):
            self.calls.append('stop')

        async def restart(self, visible=None):
            self.calls.append('restart')
            await asyncio.get_running_loop().create_future()  # a sign-in that waits

        async def item(self, kind, item_id):
            self.calls.append('item')
            raise EngineError('engine-down')

        async def artist_page(self, artist_id, refresh=False):
            self.calls.append('artist_page')
            if self.artist_answer is None:
                raise EngineError('engine-down')
            return self.artist_answer

        async def album_page(self, album_id, song_id=None, refresh=False):
            self.calls.append('album_page')
            if self.album_answer is None:
                raise EngineError('engine-down')
            return self.album_answer

        async def playlist_suggestions(self, playlist_id, refresh=False, limit=16, offered=(),
                                       selected=(), more=False, basis=None):
            self.calls.append('more_suggestions' if more else 'playlist_suggestions')
            if self.suggestions is None:
                raise EngineError('engine-down')
            return self.suggestions

        async def radio(self, refresh=False):
            self.calls.append('radio')
            if self.radio_answer is None:
                raise EngineError('engine-down')
            return self.radio_answer

        async def charts(self, refresh=False):
            self.calls.append('charts')
            if self.charts_answer is None:
                raise EngineError('engine-down')
            return self.charts_answer

    class LibrarySync(GObject.Object):
        """The app's sync as the dialogs see it: never running."""

        running = GObject.Property(type=bool, default=False)

        async def cancel(self):
            pass

        def hold(self):
            pass

        def release(self):
            pass

    class App(Adw.Application):
        """Gio.Application.get_default() while the tests run: spawn(), the engine, the
        settings (memory backend), and a record of what the widgets asked."""

        signing_in = GObject.Property(type=bool, default=False)
        signing_out = GObject.Property(type=bool, default=False)

        def account_key(self, name):
            return name  # the release build's keys

        def __init__(self):
            super().__init__(application_id='io.github.jackicus.MusicSleeve.LifetimeTest',
                             flags=Gio.ApplicationFlags.NON_UNIQUE)
            self.set_default()  # the pages' app, whichever application another test made first
            self.engine = Engine()
            self.player = Player()  # the pages follow its item while shown
            self.library_sync = LibrarySync()
            self.settings = Gio.Settings.new(SCHEMA_ID)
            self.demo = False
            self.profile = 'default'
            self.tasks = []
            self.actions = []
            self.reported = []
            self.cleared = 0
            # app.sync, which Preferences' Refresh button runs by its action name.
            sync = Gio.SimpleAction.new('sync', None)
            sync.connect('activate', lambda *_args: self.actions.append('sync'))
            self.add_action(sync)

        def spawn(self, coro):
            task = asyncio.get_running_loop().create_task(coro)
            self.tasks.append(task)
            return task

        def report(self, error):
            self.reported.append(error.code)

        def refuse_in_demo(self):
            return self.demo

        def start_engine(self):
            return self.spawn(self.engine.start())

        def toast(self, _title):
            pass

        def activate_action(self, name, _parameter=None):
            self.actions.append(name)

        async def clear_cache(self):
            self.cleared += 1
            return True

        def start_sync(self):
            pass

    class ItemActions:
        """The window's item actions as a playlist's Suggested Songs use them: an add that
        takes (it holds nothing of what it was given): its task, done, says it succeeded;
        and as the context menus and More Options ask them: the menu every page shows
        (actions.build_menu), with nothing to move to."""

        def add_to_playlist(self, playlist_id, song_id, title='', kind='song'):
            task = asyncio.get_running_loop().create_future()
            task.set_result(True)
            return task

        def menu_for(self, obj, queued=False, queue_entry=None):
            from applemusic.actions import build_menu

            return build_menu(obj, queued=queued, queue_entry=queue_entry)

        def move_targets(self, _obj):
            return None

    class Window(Adw.Window):
        """The app's window as the pages see it (get_root()): a navigation view whose root
        page holds a box (for a Shelf on its own), and the seams they call, recorded."""

        def __init__(self):
            super().__init__(default_width=800, default_height=600)
            self.navigation_view = Adw.NavigationView()
            self.root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.root_page = Adw.NavigationPage(title='Root', child=self.root_box)
            self.navigation_view.add(self.root_page)
            self.navigation_view.replace([self.root_page])
            self.set_content(self.navigation_view)
            self.opened = []
            self.shelves_opened = []
            self.played = []
            self.item_actions = ItemActions()

        def open_item(self, item):
            self.opened.append(item)

        def open_shelf(self, shelf):
            self.shelves_opened.append(shelf)

        def play_request(self, play, start_with=None, shuffle=False, start_id=None):
            self.played.append((play, start_with, shuffle))

    _stand_ins.update(Engine=Engine, App=App, Window=Window)
    return _stand_ins


def _find(widget, cls):
    """The first widget of class cls in widget's tree (widget included), depth first."""
    if isinstance(widget, cls):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = _find(child, cls)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def _controllers(widget):
    model = widget.observe_controllers()
    return [model.get_item(position) for position in range(model.get_n_items())]


def _again(ref):
    """The widget a GObject weak reference names, as a new Python wrapper, once the old one
    has been collected: call it with no other reference to that wrapper left (`page =
    _again(page.weak_ref())` keeps one, in `page`, until the call returns; rebind first:
    `page = page.weak_ref()`, then `page = _again(page)`), so that what runs next finds the
    widget as the app's code would, through GTK (see the module)."""
    gc.collect()
    return ref()


def _track(album_id, number):
    return {'id': f'{album_id}.t{number}', 'catalogId': None, 'title': f'Song {number}',
            'artist': 'Invented Artist', 'album': album_id, 'trackNumber': number + 1,
            'discNumber': 1, 'durationMs': 180000, 'durationLabel': '3:00',
            'explicit': False, 'index': number, 'thumb': None}


def _album(number, tracks=3, year=None):
    album_id = f'l.album{number:03d}'
    play = {'kind': 'album', 'id': album_id}
    return {'id': album_id, 'kind': 'album', 'title': f'Album {number:03d}',
            'subtitle': 'Invented Artist', 'year': year or 2000 + number % 20, 'genre': 'Pop',
            'art': None, 'thumb': None, 'countLabel': f'{tracks} songs', 'play': play,
            'groups': [{'name': 'Disc 1', 'play': play,
                        'entries': [_track(album_id, i) for i in range(tracks)]}] if tracks
            else []}


def _artist(albums):
    groups = [{'name': album['title'], 'play': album['play'],
               'entries': album['groups'][0]['entries'] if album['groups'] else []}
              for album in albums]
    return {'id': 'l.artist001', 'kind': 'artist', 'title': 'Invented Artist', 'art': None,
            'thumb': None, 'groups': groups}


@requires_gtk
class WidgetTestCase(unittest.IsolatedAsyncioTestCase):
    """One presented window and one stand-in application for every class; animations off."""

    @classmethod
    def setUpClass(cls):
        from gi.repository import Gtk

        from applemusic.library import Library

        classes = _classes()
        cls.gtk_settings = Gtk.Settings.get_default()
        cls.animations = cls.gtk_settings.props.gtk_enable_animations
        cls.gtk_settings.props.gtk_enable_animations = False
        if 'app' not in classes:  # one per process: its ID is registered on the bus
            classes['app'] = classes['App']()
            classes['app'].register(None)  # Preferences inserts its actions: a registered app's
        cls.app = classes['app']
        cls.library = Library()
        cls.window = classes['Window']()
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
        del cls.window, cls.app, cls.library

    def setUp(self):
        self.window.opened.clear()
        self.window.shelves_opened.clear()
        self.window.played.clear()
        self.app.engine.calls.clear()
        self.app.engine.state = 'down'
        self.app.actions.clear()
        self.app.reported.clear()
        self.app.demo = False

    async def asyncTearDown(self):
        dialog = self.window.get_visible_dialog()
        while dialog is not None:
            dialog.force_close()
            pump(10)
            dialog = self.window.get_visible_dialog()
        self.window.navigation_view.replace([self.window.root_page])
        child = self.window.root_box.get_first_child()
        while child is not None:
            self.window.root_box.remove(child)
            child = self.window.root_box.get_first_child()
        await self.settle()

    async def until(self, predicate, timeout=1.0, interval=0.005):
        """Run GTK's main context and the asyncio loop until predicate() holds (True), or
        timeout seconds have gone (False), asking every interval seconds."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                return False
            pump(10)
            await asyncio.sleep(interval)
        return True

    async def turn(self):
        """Let what is pending run: GTK's main context, and the tasks up to their next
        wait."""
        for _round in range(5):
            pump(10)
            await asyncio.sleep(0)

    async def settle(self):
        """Let every task spawned so far finish (cancelling one still waiting after half a
        second), and drop them (a finished task's exception holds the frames it went
        through, and their widgets). GTK's main context runs while they do, as
        page_harness's settle() runs it: a task waiting for a frame (next_frame()) or a GLib
        timeout is only woken by it."""
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
            pending = None
            for task in tasks:
                if not task.done():
                    task.cancel()
            del tasks
        pump(10)

    async def push(self, page, *row_types):
        """Push page and wait for it to be shown (and to have bound a widget of each
        row_type)."""
        self.window.navigation_view.push(page)
        shown = await self.until(lambda: page.get_mapped() and all(
            _find(page, cls) is not None for cls in row_types))
        self.assertTrue(shown, f'{type(page).__name__} not shown')

    def answer(self, name, value):
        """The engine's `name` request answers value (for this test)."""
        async def method(*_args, **_kwargs):
            return value

        setattr(self.app.engine, name, method)
        self.addCleanup(lambda: self.app.engine.__dict__.pop(name, None))

    async def assert_freed(self, *refs):
        """Assert that the GObject weak references die once the tasks have finished and the
        collector has run. GTK may hold a widget it has just removed until its next frame,
        so this looks again for a while before failing."""
        await self.settle()

        def freed():
            gc.collect()
            return all(ref() is None for ref in refs)

        if not await self.until(freed, timeout=0.5, interval=0.02):
            for ref in refs:
                self.assertIsNone(ref(), f'still alive: {ref()!r}')


class PageLifetimeTest(WidgetTestCase):
    """The widget is made in the call, so that the test holds no reference to it."""

    async def pushed_and_popped(self, page, *row_types, during=None):
        """Push page, wait for a widget of each row_type in it, await during(page) when
        given (what is done on the page while it shows), pop it: GObject weak references to
        the page and to those rows, and to whatever during() answers (a list of them)."""
        await self.push(page, *row_types)
        refs = [page.weak_ref()] + [_find(page, cls).weak_ref() for cls in row_types]
        if during is not None:
            refs += await during(page) or []
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: page.get_parent() is None))
        return refs

    async def rooted_and_dropped(self, page, *row_types, during=None):
        """As the window keeps a root page (a sidebar destination's, a playlist's or a
        folder's) and drops it (_trim_roots past ROOT_LIMIT, forget_account_pages at a
        sign-out): added to the navigation view, made its root, shown, the root replaced,
        the page removed. GObject weak references, as pushed_and_popped()'s."""
        nav = self.window.navigation_view
        nav.add(page)
        nav.replace([page])
        shown = await self.until(lambda: page.get_mapped() and all(
            _find(page, cls) is not None for cls in row_types))
        self.assertTrue(shown, f'{type(page).__name__} not shown')
        refs = [page.weak_ref()] + [_find(page, cls).weak_ref() for cls in row_types]
        if during is not None:
            refs += await during(page) or []
        nav.replace([self.window.root_page])
        nav.remove(page)
        self.assertTrue(await self.until(lambda: page.get_parent() is None))
        return refs

    async def added_and_removed(self, widget, row_type):
        """Add widget to the root page, wait for a row_type in it, remove it: GObject weak
        references to the widget and to that row."""
        self.window.root_box.append(widget)
        self.assertTrue(await self.until(lambda: _find(widget, row_type) is not None))
        refs = widget.weak_ref(), _find(widget, row_type).weak_ref()
        self.window.root_box.remove(widget)
        return refs

    async def test_grid_page(self):
        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets.tile import Tile

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(_album(number)) for number in range(24)])
        refs = await self.pushed_and_popped(
            GridPage(self.library, 'Invented Shelf', store, sorts=('title', 'year'),
                     root=False), Tile)
        await self.assert_freed(*refs)

    async def test_draggable_grid_page(self):
        # A folder's page: its tiles are drag sources (widgets/dnd.py), whose finder holds
        # the grid only weakly.
        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets.tile import Tile

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(_album(number)) for number in range(8)])
        refs = await self.pushed_and_popped(
            GridPage(self.library, 'Invented Folder', store, root=False), Tile)
        await self.assert_freed(*refs)

    async def test_search_see_all_page(self):
        # A search shelf's See All, paging on while shown (a page fetched, its footer bound).
        from applemusic.library import Item
        from applemusic.pages.search_all import SearchAllPage
        from applemusic.search_pager import SearchPager
        from applemusic.widgets.search_list import FooterRow, ResultRow

        def song(number):
            return {'id': f'17240{number:05d}', 'kind': 'song', 'title': f'Song {number}',
                    'subtitle': 'Invented Artist', 'art': None, 'thumb': None}

        async def search(term, kind=None, offset=0, limit=25):
            return {'shelves': [{'key': kind, 'items': [song(n) for n in range(offset, 30)],
                                 'next': None}]}

        pager = SearchPager('invented', 'songs', [Item(song(n)) for n in range(3)], 3,
                            search=search, spawn=self.app.spawn)
        refs = await self.pushed_and_popped(SearchAllPage(pager, 'Songs'), ResultRow,
                                            FooterRow)
        del pager
        await self.assert_freed(*refs)

    async def test_detail_page(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.track_row import TrackRow

        refs = await self.pushed_and_popped(
            DetailPage(self.library, Item(_album(1, tracks=12))), TrackRow)
        await self.assert_freed(*refs)

    async def test_album_page_with_the_catalogs_shelves(self):
        # The footer and the shelves under an album's tracks, bound a frame apart.
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.tile import Tile

        def entry(number):
            return {'id': str(1724049100 + number), 'kind': 'album', 'title': f'Other {number}',
                    'subtitle': '2026', 'art': None, 'thumb': None, 'groups': [],
                    'play': {'kind': 'album', 'id': str(1724049100 + number)}}

        self.app.engine.album_answer = {
            'id': '1724049100', 'artistId': '42', 'artistName': 'Invented Artist',
            'release': {'releaseDate': '2026-03-14', 'copyright': '℗ 2026 Invented'},
            'shelves': [{'key': key, 'title': '', 'more': key == 'you-might-also-like',
                         'items': [entry(number) for number in range(1, 5)]}
                        for key in ('other-versions', 'more-by-artist', 'appears-on',
                                    'you-might-also-like')]}
        self.addCleanup(setattr, self.app.engine, 'album_answer', None)
        item = Item(dict(_album(1, tracks=3), catalogId='1724049100'))
        refs = await self.pushed_and_popped(DetailPage(self.library, item), Shelf, Tile)
        await self.assert_freed(*refs)

    async def test_playlist_table_page(self):
        # A playlist's page in a window wide enough for its table: links and a header.
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.track_links import TrackLink
        from applemusic.widgets.track_row import TrackRow, TrackTableHeader

        item = Item(dict(_album(1, tracks=12), kind='playlist'))
        refs = await self.pushed_and_popped(DetailPage(self.library, item), TrackRow,
                                            TrackLink, TrackTableHeader)
        await self.assert_freed(*refs)

    async def test_playlist_page_filtered(self):
        # A playlist's page with its filter bar shown, typed into, Escape pressed on the page.
        from gi.repository import Gdk, Gtk

        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.filter_bar import FilterBar
        from applemusic.widgets.track_row import TrackRow

        item = Item(dict(_album(1, tracks=12), kind='playlist'))
        page = DetailPage(self.library, item)
        refs = [page.weak_ref()]
        self.window.navigation_view.push(page)
        self.assertTrue(await self.until(lambda: _find(page, TrackRow) is not None))
        refs += [_find(page, FilterBar).weak_ref(), _find(page, TrackRow).weak_ref()]
        self.assertTrue(page.focus_filter())
        entry = page.filter_bar.entry
        self.assertTrue(await self.until(lambda: self.window.get_focus() is not None
                                         and self.window.get_focus().is_ancestor(entry)))
        # The compositor's answer to the first focused entry's text input, before the page
        # goes (docs/notes.md).
        await self.until(lambda: False, timeout=0.1)
        page.filter_bar.set_text('song 1')
        await self.turn()
        escape = next(controller for controller in page.observe_controllers()
                      if isinstance(controller, Gtk.EventControllerKey))
        escape.emit('key-pressed', Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
        await self.turn()
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: page.get_parent() is None))
        page = escape = entry = None
        await self.assert_freed(*refs)

    async def test_playlist_page_with_suggestions(self):
        # A playlist's Suggested Songs: the section, its grid, its rows with their buttons,
        # one of them added (its place filled by a spare, its row bound again).
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.song_shelf import SongRow
        from applemusic.widgets.suggested_songs import SuggestedSongs, SuggestionRow

        self.app.engine.suggestions = {'items': [
            {'id': str(3000 + number), 'kind': 'song', 'title': f'Suggested {number}',
             'subtitle': 'Other Artist', 'art': None, 'thumb': None,
             'play': {'kind': 'song', 'id': str(3000 + number)}, 'groups': []}
            for number in range(8)]}
        self.addCleanup(setattr, self.app.engine, 'suggestions', None)
        item = Item(dict(_album(1, tracks=3), kind='playlist'))
        page = DetailPage(self.library, item)
        refs = [page.weak_ref()]
        self.window.navigation_view.push(page)
        self.assertTrue(await self.until(lambda: _find(page, SuggestionRow) is not None))
        section = _find(page, SuggestedSongs)
        refs += [section.weak_ref(), section.grid.weak_ref(), _find(page, SongRow).weak_ref()]
        row = section.grid.rows[0]
        refs.append(row.weak_ref())
        row.add_button.emit('clicked')  # Add to Playlist, then its place filled
        await self.settle()
        self.assertEqual(section.items[0].id, '3006')
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: page.get_parent() is None))
        page = section = row = None
        await self.assert_freed(*refs)

    async def test_artist_page(self):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage
        from applemusic.widgets.tile import Tile

        refs = await self.pushed_and_popped(
            ArtistPage(self.library, Item(_artist([_album(n) for n in range(4)]))), Tile)
        await self.assert_freed(*refs)

    async def test_library_artist_page(self):
        # Its albums are made up from the artist's groups (the library here has none of them).
        from applemusic.library import Item
        from applemusic.pages.library_artist import LibraryArtistPage
        from applemusic.widgets.tile import Tile

        refs = await self.pushed_and_popped(
            LibraryArtistPage(self.library, Item(_artist([_album(n) for n in range(4)]))),
            Tile)
        await self.assert_freed(*refs)

    async def test_artist_page_with_the_catalog(self):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage
        from applemusic.widgets.hero_tile import HeroTile
        from applemusic.widgets.song_shelf import SongRow, SongShelf
        from applemusic.widgets.tile import Tile

        from applemusic.widgets.banner import ArtistBanner

        # With a banner on disk (an invented image): the page's banner decodes it and fades
        # it in, and goes with the page.
        from gi.repository import Gdk, GLib

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, 'banner.png')
        Gdk.MemoryTexture.new(6, 2, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(bytes(48)),
                              24).save_to_png(path)
        banner = {'url': None, 'art': path, 'crop': 'vf', 'width': 6, 'height': 2,
                  'color': '#102030'}
        self.app.engine.artist_answer = artist_answer(banner=banner)
        self.addCleanup(setattr, self.app.engine, 'artist_answer', None)
        page = ArtistPage(self.library, Item(dict(_artist([_album(1)]), catalogId='42')))
        await self.push(page, SongShelf, SongRow, HeroTile, Tile)
        self.assertTrue(await self.until(lambda: page.banner.picture.get_opacity() == 1))
        refs = [page.weak_ref(), page.banner.weak_ref()] + [
            _find(page, cls).weak_ref() for cls in (SongShelf, SongRow, HeroTile, Tile)]
        self.assertIsInstance(page.banner, ArtistBanner)
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: page.get_parent() is None))
        page = None
        await self.assert_freed(*refs)

    async def test_shelves_page(self):
        from applemusic.pages.shelves import ShelvesPage
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.tile import Tile

        async def fetch(refresh):
            return {'shelves': [
                {'key': key, 'title': key.title(),
                 'items': [dict(_album(n, tracks=0), id=f'{key}{n}') for n in range(6)]}
                for key in ('first', 'second')]}

        refs = await self.pushed_and_popped(ShelvesPage('Invented Page', fetch, root=False),
                                            Shelf, Tile)
        await self.assert_freed(*refs)

    async def test_radio_page(self):
        # A shelves page with an arrange of its own and the library followed.
        from applemusic.pages import radio
        from applemusic.sections import Destination
        from applemusic.widgets.hero_tile import HeroTile
        from applemusic.widgets.tile import Tile

        self.app.engine.radio_answer = {'shelves': [
            {'key': key, 'title': key.title(),
             'items': [dict(_album(n, tracks=0), id=f'{key}{n}') for n in range(6)]}
            for key in ('live', 'shows')]}
        self.addCleanup(setattr, self.app.engine, 'radio_answer', None)
        refs = await self.pushed_and_popped(
            radio.create(Destination('radio', 'Radio', 'broadcast-symbolic'), self.library),
            HeroTile, Tile)
        await self.assert_freed(*refs)

    async def test_charts_page(self):
        # A shelves page of a chart's forms: numbered songs in a grid, numbered tiles.
        from applemusic.pages import charts
        from applemusic.widgets.shelf import RankedTile
        from applemusic.widgets.song_shelf import SongRow, SongShelf

        songs = [{'id': f'19{n}', 'kind': 'song', 'title': f'Song {n}', 'subtitle': 'Artist',
                  'play': {'kind': 'song', 'id': f'19{n}'}} for n in range(6)]
        self.app.engine.charts_answer = {'shelves': [
            {'key': 'charts-songs', 'title': 'Top Songs', 'ranked': True, 'form': 'songs',
             'items': songs},
            {'key': 'charts-albums', 'title': 'Top Albums', 'ranked': True,
             'items': [dict(_album(n, tracks=0), id=f'c{n}') for n in range(6)]}]}
        self.addCleanup(setattr, self.app.engine, 'charts_answer', None)
        refs = await self.pushed_and_popped(charts.create(charts.charts_item()), SongShelf,
                                            SongRow, RankedTile)
        await self.assert_freed(*refs)

    async def test_shelf_widget(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.tile import Tile

        model = ShelfModel('invented', 'Invented', [Item(_album(n)) for n in range(6)])

        def shelf():
            widget = Shelf(see_all=True)
            widget.bind_shelf(model)
            return widget

        refs = await self.added_and_removed(shelf(), Tile)
        await self.assert_freed(*refs)

    async def test_category_page(self):
        # A search category's, a curator's or a radio show's page, pushed, with its shelves.
        from applemusic.library import Item
        from applemusic.pages.shelves import category_page
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.tile import Tile

        self.answer('category', _shelves('playlists', 'shows', kind='playlist'))
        item = Item({'id': 'c1', 'kind': 'category', 'title': 'Invented Category', 'art': None,
                     'thumb': None})
        refs = await self.pushed_and_popped(category_page(item), Shelf, Tile)
        del item
        await self.assert_freed(*refs)

    async def test_new_page(self):
        # New, with More to Explore's tiles after its shelves; dropped at a sign-out.
        from applemusic.pages import new
        from applemusic.sections import Destination
        from applemusic.widgets.category_tile import CategoryTile
        from applemusic.widgets.hero_tile import HeroTile
        from applemusic.widgets.tile import Tile

        self.answer('browse', _shelves('featured', 'albums'))
        refs = await self.rooted_and_dropped(
            new.create(Destination('new', 'New', 'starred-symbolic')),
            HeroTile, Tile, CategoryTile)
        await self.assert_freed(*refs)

    async def test_made_for_you_page(self):
        # Dropped at a sign-out.
        from applemusic.pages import made_for_you
        from applemusic.sections import Destination
        from applemusic.widgets.hero_tile import HeroTile

        self.answer('made_for_you', _shelves('mixes', 'stations', kind='playlist'))
        refs = await self.rooted_and_dropped(
            made_for_you.create(Destination('made-for-you', 'Made for You',
                                            'starred-symbolic')), HeroTile)
        await self.assert_freed(*refs)

    async def test_search_page(self):
        # The landing (categories, Recently Searched: a store of the app's, which outlives
        # the page), suggestions, the results' shelves, a kind's paged list, Your Library;
        # dropped at a sign-out.
        from applemusic.library import Item
        from applemusic.pages.search import SearchPage
        from applemusic.recent_searches import RecentSearches
        from applemusic.widgets.category_tile import CategoryTile
        from applemusic.widgets.search_list import ResultRow
        from applemusic.widgets.shelf import Shelf

        recent = RecentSearches(None, self.app.spawn)
        recent.items.append(Item(dict(_album(9, tracks=0), id='r9')))
        self.app.recent_searches = recent
        self.addCleanup(delattr, self.app, 'recent_searches')
        self.answer('landing', {'categories': [
            {'id': f'cat{n}', 'kind': 'category', 'title': f'Category {n}', 'art': None}
            for n in range(4)]})
        self.answer('suggest', {'terms': [{'term': 'inv', 'display': 'inv'}], 'items': []})

        async def search(text, limit=None, kind=None, offset=0):
            if kind:
                return {'shelves': [{'key': kind, 'items': [
                    {'id': f'9{n}', 'kind': 'song', 'title': f'Song {n}',
                     'subtitle': 'Invented Artist', 'art': None} for n in range(5)],
                    'next': None}]}
            return _shelves('top', 'albums', 'songs')

        self.app.engine.search = search
        self.addCleanup(lambda: self.app.engine.__dict__.pop('search', None))

        async def during(page):
            page.search_entry.set_text('invented')
            page._search('invented')
            self.assertTrue(await self.until(
                lambda: _find(page.results_box, Shelf) is not None))
            page.set_kind('songs')
            self.assertTrue(await self.until(
                lambda: _find(page.kind_list, ResultRow) is not None))
            refs = [_find(page.results_box, Shelf).weak_ref(),
                    _find(page.kind_list, ResultRow).weak_ref()]
            page.set_mode('library')
            await self.turn()
            return refs

        refs = await self.rooted_and_dropped(SearchPage(self.library, 'Search'), CategoryTile,
                                             during=during)
        await self.assert_freed(*refs)

    async def test_playlist_root_page(self):
        # A sidebar playlist's page (pages.playlist), dropped past ROOT_LIMIT.
        from applemusic import pages

        refs = await self.rooted_and_dropped(pages.playlist(self.library, 'p.none', 'Invented'))
        await self.assert_freed(*refs)

    async def test_folder_pages_and_their_more_options(self):
        # A folder's page as a sidebar root and pushed from a tile, with New Playlist, New
        # Folder and More Options (its menu made as it opens: the folder's).
        from applemusic import pages
        from applemusic.library import Item

        folder = Item({'id': 'f.invented', 'kind': 'folder', 'title': 'Invented Folder'})
        self.library._index[('folder', folder.id)] = folder
        self.addCleanup(self.library._index.pop, ('folder', folder.id))

        async def more_options(page):
            from gi.repository import Gtk

            button = _find_where(page.header_bar, lambda widget: isinstance(
                widget, Gtk.MenuButton) and widget.get_icon_name() == 'view-more-symbolic')
            return await self.opened_and_closed(button)

        refs = await self.rooted_and_dropped(
            pages.folder(self.library, folder.id, 'Invented Folder'), during=more_options)
        refs += await self.pushed_and_popped(
            pages.folder(self.library, folder.id, 'Invented Folder', root=False),
            during=more_options)
        await self.assert_freed(*refs)

    async def opened_and_closed(self, button):
        """A menu button's popover opened (its menu made as it opens) and closed: a GObject
        weak reference to it, in a list."""
        button.popup()
        popover = button.get_popover()
        self.assertIsNotNone(popover)
        self.assertIsNotNone(button.get_menu_model())
        self.assertTrue(await self.until(popover.get_mapped))
        button.popdown()
        self.assertTrue(await self.until(lambda: not popover.get_mapped()))
        # The focus, back on the button, leaves the page: this stand-in window keeps a page
        # popped with the focus in it alive (the app's window does not: the demo app frees
        # an album's page popped with the focus on its More Options).
        self.window.set_focus(None)
        return [popover.weak_ref()]

    async def menu_opened_and_closed(self, view):
        """The context menu of the first row or tile of view opened (context_menu.popup())
        and closed, and unparented: GObject weak references to the row and the popover."""
        from applemusic.widgets import context_menu

        widget, obj = context_menu._descendant(view)
        popover = context_menu.popup(widget, obj)
        self.assertIsNotNone(popover)
        self.assertTrue(await self.until(popover.get_mapped))
        popover.popdown()
        self.assertTrue(await self.until(lambda: popover.get_parent() is None))
        self.window.set_focus(None)  # see opened_and_closed()
        return [widget.weak_ref(), popover.weak_ref()]

    async def test_context_menus_and_more_options(self):
        # A tile's menu on a grid, a track row's and More Options on an album's page: each
        # opened and closed, then the page popped.
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.pages.grid import GridPage
        from applemusic.widgets.tile import Tile
        from applemusic.widgets.track_row import TrackRow

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(_album(number)) for number in range(8)])

        async def tile_menu(page):
            return await self.menu_opened_and_closed(page.grid_view)

        refs = await self.pushed_and_popped(
            GridPage(self.library, 'Invented Shelf', store, root=False), Tile, during=tile_menu)
        del store

        async def row_menu_and_more_options(page):
            return (await self.menu_opened_and_closed(page.list_view)
                    + await self.opened_and_closed(page.more_button))

        refs += await self.pushed_and_popped(
            DetailPage(self.library, Item(_album(1, tracks=4))), TrackRow,
            during=row_menu_and_more_options)
        await self.assert_freed(*refs)

    async def test_sidebar_row_menus(self):
        # A sidebar row's menu (a playlist's, a folder's, All Playlists'), opened and closed:
        # the popovers, parented to the rows of a sidebar that lives as long as the window,
        # are unparented and freed.
        from gi.repository import Adw

        from applemusic.sections import ALL_PLAYLISTS
        from applemusic.sidebar_view import SidebarController
        from tests.test_sidebar import MenuLibrary, StubWindow, tree

        self.app.settings.set_strv('expanded-folders', ['a'])
        self.addCleanup(self.app.settings.reset, 'expanded-folders')
        sidebar = Adw.Sidebar(vexpand=True)
        self.window.root_box.append(sidebar)
        controller = SidebarController(StubWindow(), sidebar, MenuLibrary(tree()),
                                       self.app.settings, self.window.item_actions)
        keys = ('playlist:p1', 'folder:a', ALL_PLAYLISTS)
        self.assertTrue(await self.until(lambda: all(
            controller.row(controller.item_for(key).get_index()).get_mapped()
            for key in keys)))
        refs = []
        for key in keys:
            popover = controller.popup_menu(key)
            self.assertIsNotNone(popover, key)
            self.assertTrue(await self.until(popover.get_mapped))
            popover.popdown()
            self.assertTrue(await self.until(lambda popover=popover: popover.get_parent()
                                             is None))
            refs.append(popover.weak_ref())
            popover = None
        await self.assert_freed(*refs)

    async def test_a_tile_dragged(self):
        # A tile's drag prepared on a pushed grid (the drag source's icon is a paintable of
        # the tile), then the page popped.
        from gi.repository import Gtk

        from applemusic.library import Item
        from applemusic.pages.grid import GridPage
        from applemusic.widgets import dnd
        from applemusic.widgets.tile import Tile

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(_album(number)) for number in range(8)])

        async def drag(page):
            source = next(controller for controller in _controllers(page.grid_view)
                          if isinstance(controller, Gtk.DragSource))
            tile = _find(page.grid_view, Tile)
            self.assertTrue(await self.until(lambda: tile.get_mapped() and tile.get_width()))
            ok, point = tile.compute_point(page.grid_view, _point(tile.get_width() / 2, 20))
            self.assertTrue(ok)
            self.assertIsNotNone(source.emit('prepare', point.x, point.y))
            dnd._set_current(None)

        refs = await self.pushed_and_popped(
            GridPage(self.library, 'Invented Folder', store, root=False), Tile, during=drag)
        del store
        await self.assert_freed(*refs)

    async def test_a_playlist_page_mid_reorder(self):
        # A playlist of the user's with one of its songs dragged over it (the insertion line
        # on a row, auto-scroll's tick on the scrolled window), popped without a leave.
        from gi.repository import Gdk, Gtk

        from applemusic.library import Item, ItemRefs
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets import dnd
        from applemusic.widgets.track_row import TrackRow

        async def reorder(page):
            self.assertTrue(page.can_reorder())
            track = page.item.groups[0].entries.get_item(1)
            dnd._set_current(ItemRefs.for_objects([track], ('playlist', page.item.id)),
                             Gdk.DragAction.MOVE)
            self.addCleanup(dnd._set_current, None)
            target = next(controller for controller in _controllers(page.list_view)
                          if isinstance(controller, Gtk.DropTarget))
            row = _find(page.list_view, TrackRow)
            ok, point = row.compute_point(page.list_view, _point(20, 5))
            self.assertTrue(ok)
            target.emit('motion', point.x, point.y)
            page._drop_feedback.motion(page.scrolled_window.get_height() - 2)  # the tick
            self.assertIsNotNone(page._drop_feedback.marked())
            await self.turn()
            dnd._set_current(None)

        item = Item(dict(_album(1, tracks=12), kind='playlist', id='l.playlist1'))
        refs = await self.pushed_and_popped(DetailPage(self.library, item), TrackRow,
                                            during=reorder)
        del item
        await self.assert_freed(*refs)

    async def test_up_next_and_history_rows(self):
        # Not a page: the Now Playing sheet's queue lives as long as the window, but its
        # lists destroy rows as the queue shrinks. Every QueueRow made, Up Next's and
        # History's, is either bound still or freed.
        from gi.repository import GLib

        from applemusic.widgets.queue import QueueRow, QueueView
        from tests.test_player import make_player
        from tests.test_queue import entries

        made = []
        init = QueueRow.__init__

        def record(row, *args, **kwargs):
            init(row, *args, **kwargs)
            made.append(row.weak_ref())

        patch = mock.patch.object(QueueRow, '__init__', record)
        patch.start()
        self.addCleanup(patch.stop)
        player, _engine, app = make_player()
        player.apply_queue({'index': 6, 'items': entries(30)})
        view = QueueView()
        view.set_player(player, app)
        view.art._fetch = None
        view.art._find = lambda urls: {}
        view.set_vexpand(True)
        self.window.root_box.append(view)
        self.assertTrue(await self.until(lambda: len(view._rows) > 5))
        view.history_button.set_active(True)  # History: the six played
        self.assertTrue(await self.until(lambda: sum(row.history for row in view._rows) == 6))
        view.history_button.set_active(False)
        player.apply_queue({'index': 0, 'items': entries(2)})  # a short queue, none played
        self.assertTrue(await self.until(lambda: len(view._rows) == 2))
        view.history_button.set_active(True)
        await self.turn()
        view.history_button.set_active(False)
        self.assertGreater(len(made), 8)

        def freed():
            gc.collect()
            return all(ref() is None or ref() in view._rows for ref in made)

        await self.settle()
        self.assertTrue(await self.until(freed), 'a QueueRow unbound but alive')
        self.window.root_box.remove(view)
        if view.art._source:  # no look after the test
            GLib.source_remove(view.art._source)


def _shelves(*keys, n=6, kind='album'):
    """An answer of shelves, one per key, of n invented items of `kind` each."""
    return {'shelves': [
        {'key': key, 'title': key.title(),
         'items': [dict(_album(number, tracks=0), id=f'{key}{number}', kind=kind)
                   for number in range(n)]}
        for key in keys]}


def _point(x, y):
    from gi.repository import Graphene

    point = Graphene.Point()
    point.x, point.y = x, y
    return point


def _find_where(widget, predicate):
    """The first widget in widget's tree (widget included) for which predicate() holds."""
    if predicate(widget):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = _find_where(child, predicate)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


class DialogLifetimeTest(WidgetTestCase):
    async def presented_and_closed(self, dialog):
        """Present dialog over the window and close it as Escape would: a GObject weak
        reference to it."""
        closed = []
        dialog.connect('closed', lambda _dialog: closed.append(True))
        dialog.present(self.window)
        self.assertTrue(await self.until(dialog.get_mapped))
        await self.turn()
        dialog.force_close()
        self.assertTrue(await self.until(lambda: closed))
        return dialog.weak_ref()

    async def test_preferences_dialog(self):
        from applemusic.dialogs.preferences import PreferencesDialog

        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
            ref = await self.presented_and_closed(PreferencesDialog(self.app))
            await self.assert_freed(ref)

    async def test_sign_in_dialog(self):
        from applemusic.dialogs.signin import SignInDialog

        # Closed as the sign-in waits for the engine: the task is cancelled, the engine
        # stopped.
        ref = await self.presented_and_closed(SignInDialog(self.app))
        await self.assert_freed(ref)
        self.assertEqual(self.app.engine.calls, ['restart', 'stop'])

    async def test_name_dialog(self):
        from applemusic.dialogs.playlist import NameDialog

        answers = []
        dialog = NameDialog('Rename Playlist', '_Rename', 'Road Trip', 'Long drives',
                            lambda *answer: answers.append(answer))
        dialog.name_row.set_text('Night Drive')  # its handler, connected weakly, still runs
        self.assertTrue(dialog.get_response_enabled('confirm'))
        dialog.name_row.set_text('  ')
        self.assertFalse(dialog.get_response_enabled('confirm'))  # no blank name
        dialog.name_row.set_text(' Night Drive ')
        dialog.emit('response', 'confirm')
        self.assertEqual(answers, [('Night Drive', None)])  # the description unchanged
        ref = await self.presented_and_closed(dialog)
        del dialog  # the test's own reference
        await self.assert_freed(ref)

    async def closed(self, dialog):
        """A dialog presented already (by the code under test), closed as Escape would: a
        GObject weak reference to it."""
        closed = []
        dialog.connect('closed', lambda _dialog: closed.append(True))
        self.assertTrue(await self.until(dialog.get_mapped))
        await self.turn()
        dialog.force_close()
        self.assertTrue(await self.until(lambda: closed))
        return dialog.weak_ref()

    async def test_confirm_shortcuts_and_about_dialogs(self):
        # Delete Playlist or Folder and Remove from Library ask with confirm(); Keyboard
        # Shortcuts and About.
        from applemusic.dialogs import about, shortcuts
        from applemusic.dialogs.playlist import confirm

        done = []
        refs = [await self.closed(confirm(self.window, 'Delete Invented Playlist?',
                                          'It goes.', '_Delete', lambda: done.append(True))),
                await self.closed(shortcuts.present(self.window))]
        self.app.version = '1.0.0'
        self.addCleanup(delattr, self.app, 'version')
        refs.append(await self.closed(about.present(self.app, self.window)))
        await self.assert_freed(*refs)
        self.assertEqual(done, [])  # closed, not confirmed

    async def test_preferences_shown_as_a_window_of_its_own(self):
        # Over a window that is not resizable (nor maximized, nor tiled) a dialog is a window
        # of its own. Preferences lets go of its handlers (strong ones, on the settings, the
        # engine, the app and the sync) and its timer only in `closed`, which force_close()
        # does not emit for such a dialog (libadwaita 1.9): the window closes it as it closes
        # every dialog shown so (Window._close_dialogs, by its window's close()), which does.
        from gi.repository import Adw, Gtk

        from applemusic.dialogs.preferences import PreferencesDialog
        from applemusic.window import Window

        parent = Adw.Window(default_width=600, default_height=500, resizable=False)
        parent.present()
        self.addCleanup(parent.destroy)
        self.assertTrue(await self.until(parent.get_mapped))
        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
            dialog = PreferencesDialog(self.app)
            closed = []
            dialog.connect('closed', lambda _dialog: closed.append(True))
            dialog.present(parent)
            self.assertTrue(await self.until(dialog.get_mapped))
            self.assertIsInstance(dialog.get_root(), Gtk.Window)
            self.assertIsNot(dialog.get_root(), parent)  # a window of its own
            await self.turn()
            Window._close_dialogs(parent)  # what the window does when it hides or quits
            self.assertTrue(await self.until(lambda: closed))
            ref = dialog.weak_ref()
            del dialog
            await self.assert_freed(ref)


class HandlerTest(WidgetTestCase):
    """The handlers now connected weakly (they were template callbacks or bound-method
    connects) still do their work, with the widget's first Python wrapper gone."""

    async def shown(self, page, *row_types):
        """Push page, wait for it to show its rows, and answer it again (_again)."""
        await self.push(page, *row_types)
        page = page.weak_ref()
        return _again(page)

    async def presented(self, dialog):
        """Present dialog over the window, and answer it again (_again)."""
        dialog.present(self.window)
        self.assertTrue(await self.until(dialog.get_mapped))
        await self.turn()
        dialog = dialog.weak_ref()
        return _again(dialog)

    async def test_grid_sort_activation_and_title(self):
        from applemusic.library import Item
        from applemusic.pages.grid import GridPage, columns_for
        from applemusic.widgets.tile import Tile

        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, [Item(_album(number, year=1990 + number)) for number in range(60)])
        page = await self.shown(GridPage(self.library, 'Invented Grid', store,
                                         sorts=('title', 'year'), root=False), Tile)
        view_model = page.grid_view.get_model()
        self.assertEqual(view_model.get_item(0).title, 'Album 000')
        from gi.repository import GLib

        page.activate_action('page.sort', GLib.Variant('s', 'year'))  # newest first
        self.assertEqual(view_model.get_item(0).title, 'Album 059')
        page.activate_action('page.sort', GLib.Variant('s', 'title'))
        self.assertEqual(view_model.get_item(0).title, 'Album 000')

        page.grid_view.emit('activate', 2)
        self.assertEqual(self.window.opened, [view_model.get_item(2)])

        # get-child-position: the grid fits its columns to the width it was laid out at,
        # and the title moves up as the grid scrolls (value-changed).
        page = page.weak_ref()
        page = _again(page)
        self.assertTrue(await self.until(
            lambda: page.grid_view.get_max_columns() == columns_for(page.overlay.get_width())))

        def title_y():
            return page.title_label.compute_bounds(page.overlay)[1].get_y()

        before = title_y()
        page.scrolled_window.get_vadjustment().set_value(30)
        self.assertTrue(await self.until(lambda: title_y() < before))

    async def test_detail_page_buttons_rows_and_tab(self):
        from gi.repository import Gdk, Gtk

        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.widgets.track_row import TrackRow

        item = Item(_album(2, tracks=4))
        page = await self.shown(DetailPage(self.library, item), TrackRow)
        page.play_button.emit('clicked')
        page.shuffle_button.emit('clicked')
        page.list_view.emit('activate', 2)  # the hero is row 0: the second track
        track = item.groups[0].entries.get_item(1)
        self.assertEqual(self.window.played, [(item.play, None, False), (item.play, None, True),
                                              (track.play, track.index, False)])

        # Tab from the hero's last button (More Options) goes on into the tracks (the list's
        # capture key controller).
        page.more_button.grab_focus()
        keys = next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))
        page = page.weak_ref()
        page = _again(page)
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Tab, 0, Gdk.ModifierType(0)))

    async def test_detail_page_follows_the_player(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage
        from applemusic.player import NowPlaying
        from applemusic.widgets.track_row import TrackRow

        item = Item(_album(4, tracks=3))
        page = await self.shown(DetailPage(self.library, item), TrackRow)
        self.assertTrue(await self.until(lambda: len(page._bound) == 3))
        self.addCleanup(setattr, self.app.player, 'track', None)
        self.app.player.track = NowPlaying(_track('l.album004', 1))
        self.assertEqual([list_item.get_item().id for list_item in page._bound
                          if list_item.get_child().track_row.playing], ['l.album004.t1'])

    def signed_in(self):
        """The account signed in (the engine-down pages offer Start Engine, not Sign In)."""
        self.app.settings.set_boolean('signed-in', True)
        self.addCleanup(self.app.settings.reset, 'signed-in')

    async def test_detail_page_status_button(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        self.signed_in()

        # Fetched, with the engine down: Start Engine, then fetch again.
        page = await self.shown(DetailPage(self.library, Item(_album(3, tracks=0))))
        self.assertTrue(await self.until(lambda: page.status_button.get_visible()))
        page.status_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls, ['item', 'start', 'item'])

    async def test_artist_page_album_and_status(self):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage
        from applemusic.widgets.shelf import Shelf
        from applemusic.widgets.tile import Tile

        self.signed_in()

        # The engine down: the library's albums, newest first, and Start Engine under them.
        page = await self.shown(ArtistPage(self.library, Item(dict(
            _artist([_album(n) for n in range(3)]), catalogId='42'))), Tile)
        _find(page, Shelf).list_view.emit('activate', 1)
        self.assertEqual([album.title for album in self.window.opened], ['Album 001'])
        self.assertTrue(await self.until(lambda: page.status_button.get_visible()))
        page.status_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls, ['artist_page', 'start', 'artist_page'])
        self.window.navigation_view.pop()

    async def test_artist_page_top_songs(self):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage
        from applemusic.widgets.song_shelf import SongRow, SongShelf

        self.app.engine.artist_answer = artist_answer()
        self.addCleanup(setattr, self.app.engine, 'artist_answer', None)
        page = await self.shown(ArtistPage(self.library, Item(dict(_artist([]), catalogId='42'))),
                                SongRow)
        _find(page, SongShelf).grid_view.emit('activate', 1)
        self.assertEqual(self.window.played,
                         [({'kind': 'songs', 'id': '900,901,902,903'}, 1, False)])
        page.release_button.emit('clicked')
        self.assertEqual([item.title for item in self.window.opened], ['Invented album 99'])

    async def test_shelf_activation_and_see_all(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.widgets.hero_tile import HeroTile
        from applemusic.widgets.shelf import Shelf

        model = ShelfModel('invented', 'Invented', [Item(_album(n)) for n in range(4)])
        shelf = Shelf(hero=True, see_all=True)
        shelf.bind_shelf(model)
        self.window.root_box.append(shelf)
        self.assertTrue(await self.until(lambda: _find(shelf, HeroTile) is not None))
        shelf = shelf.weak_ref()
        shelf = _again(shelf)
        shelf.list_view.emit('activate', 1)
        shelf.see_all_button.emit('clicked')
        self.assertEqual(self.window.opened, [model.items.get_item(1)])
        self.assertEqual(self.window.shelves_opened, [model])

    async def test_shelves_page_refresh_and_status(self):
        from applemusic.pages.shelves import ShelvesPage

        self.signed_in()

        asked = []

        async def fetch(refresh):
            asked.append(refresh)
            if len(asked) == 1:
                raise EngineError('engine-down')
            return {'shelves': []}

        page = await self.shown(ShelvesPage('Invented Page', fetch, root=False))
        self.assertTrue(await self.until(lambda: page.status_button.get_visible()))
        page.status_button.emit('clicked')  # Start Engine, then load
        await self.settle()
        page.refresh_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls, ['start'])
        self.assertEqual(asked, [False, False, True])

    async def test_preferences_rows(self):
        from applemusic.dialogs.preferences import PreferencesDialog
        from applemusic.sync import INTERVALS

        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
            dialog = await self.presented(PreferencesDialog(self.app))
            try:
                dialog.interval_row.set_selected(0)
                self.assertEqual(self.app.settings.get_int('sync-interval'), INTERVALS[0])
                # Show More Suggestions is the more-suggestions setting.
                self.addCleanup(self.app.settings.reset, 'more-suggestions')
                dialog.more_suggestions_row.set_active(True)
                self.assertTrue(self.app.settings.get_boolean('more-suggestions'))
                self.app.settings.set_boolean('more-suggestions', False)
                self.assertFalse(dialog.more_suggestions_row.get_active())
                # Last Refreshed follows the last-sync setting and the sync's running.
                self.assertEqual(dialog.last_refreshed_row.get_subtitle(), 'Never')
                self.app.settings.set_string('last-sync', datetime.now(UTC).isoformat())
                self.assertTrue(await self.until(
                    lambda: dialog.last_refreshed_row.get_subtitle() == 'Just now'))
                self.app.library_sync.props.running = True
                self.assertEqual(dialog.last_refreshed_row.get_subtitle(), 'Refreshing…')
                self.app.library_sync.props.running = False
                self.assertEqual(dialog.last_refreshed_row.get_subtitle(), 'Just now')
                # The engine row says when the browser cannot play songs.
                engine = self.app.engine
                engine.props.state = 'up'
                engine.props.authorized = True
                self.assertEqual(dialog.engine_row.get_subtitle(), 'Running hidden')
                engine.props.widevine = False
                self.assertEqual(dialog.engine_row.get_subtitle(),
                                 'Running, but this browser cannot play songs')
                engine.props.widevine = True
                engine.props.state = 'down'
                dialog.refresh_button.emit('clicked')  # app.sync
                dialog.engine_button.emit('clicked')
                dialog.sign_out_row.emit('activated')
                dialog.clear_button.emit('clicked')  # asks first
                self.assertTrue(await self.until(
                    lambda: self.window.get_visible_dialog() is not dialog))
                alert = _again(self.window.get_visible_dialog().weak_ref())
                alert.emit('response', 'clear')
                del alert
                await self.settle()
                self.assertEqual(self.app.engine.calls, ['start'])
                self.assertEqual(self.app.actions, ['sync', 'sign-out'])
                self.assertEqual(self.app.cleared, 1)
            finally:
                self.app.settings.reset('sync-interval')
                self.app.settings.reset('last-sync')
                await self.asyncTearDown()  # the dialogs closed with the cache still patched

    async def test_preferences_account_always_has_a_row(self):
        """Signed out, signed in, or the demo (Sign In insensitive, as the Engine row's Start
        is): the Account group shows a row, never an empty list under its description."""
        from applemusic.dialogs.preferences import PreferencesDialog

        def shown(dialog):
            return [(row.get_title(), row.get_sensitive())
                    for row in (dialog.sign_in_row, dialog.sign_out_row) if row.get_visible()]

        self.addCleanup(self.app.settings.reset, 'signed-in')
        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
            try:
                for demo, signed_in, rows in ((False, False, [('Sign _In…', True)]),
                                              (False, True, [('Sign _Out…', True)]),
                                              (True, False, [('Sign _In…', False)]),
                                              (True, True, [('Sign _In…', False)])):
                    self.app.demo = demo
                    self.app.settings.set_boolean('signed-in', signed_in)
                    dialog = await self.presented(PreferencesDialog(self.app))
                    self.assertEqual(shown(dialog), rows, (demo, signed_in))
                    dialog.force_close()
                    del dialog
                    await self.settle()
            finally:
                await self.asyncTearDown()  # the dialogs closed with the cache still patched

    async def test_sign_in_cancel(self):
        from applemusic.dialogs.signin import SignInDialog

        dialog = await self.presented(SignInDialog(self.app))  # the sign-in waits
        closed = []
        dialog.connect('closed', lambda _dialog: closed.append(True))
        dialog.cancel_button.emit('clicked')
        await self.settle()
        self.assertTrue(await self.until(lambda: closed))
        self.assertEqual(self.app.engine.calls, ['restart', 'stop'])


if __name__ == '__main__':
    unittest.main()
