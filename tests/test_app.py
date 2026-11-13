# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Application (src/main.py) built without being run: its settings on the memory backend,
stand-ins for the engine, the player and the library, no window. What it decides on its own:
when a sync may start, how it quits (where errors go: tests/test_errors.py).
"""

import asyncio
import logging
import os
import tempfile
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from gi.repository import Gio, GLib, GObject

from applemusic import main
from applemusic.backend import config
from applemusic.backend.errors import EngineError
from applemusic.sync import LibrarySync

BASE_ID = 'io.github.jackicus.MusicSleeve'


class FakeEngine(GObject.Object):
    """The Engine as the app sees it: `state`, `authorized`, `headless`, `widevine`, the
    `lost` signal, and start/stop/kill that record themselves."""

    __gsignals__ = {
        'lost': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    state = GObject.Property(type=str, default='down')
    authorized = GObject.Property(type=bool, default=False)
    headless = GObject.Property(type=bool, default=True)
    widevine = GObject.Property(type=bool, default=True)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.pid = None
        self.demo = False
        self.start_blocks = False
        self.stop_blocks = False
        self._lock = asyncio.Lock()  # as the Engine's: a stop waits for a start under way

    async def start(self, visible=None):
        self.calls.append('start')
        async with self._lock:
            if self.start_blocks:
                await asyncio.get_running_loop().create_future()
            self.state = 'up'
            self.authorized = True

    async def stop(self, grace=None):
        self.calls.append(('stop', grace))
        async with self._lock:
            if self.stop_blocks:
                await asyncio.get_running_loop().create_future()
            self.state = 'down'
            self.authorized = False

    def kill(self):
        self.calls.append('kill')
        self.state = 'down'


class FakeLibrary(GObject.Object):
    syncing = GObject.Property(type=bool, default=False)
    file_state = GObject.Property(type=str, default='ok')
    version = GObject.Property(type=int, default=2)

    def song_count(self):
        return 0


def make_app(profile='default', demo=False):
    """An Application as do_startup would make it, with stand-ins, never run. The build
    profile config.set_build_profile() takes is put back after the test by the caller
    (tearDown). (The first application a process makes becomes its default:
    test_page_lifetime's stand-in makes itself the default again.)"""
    app = main.Application('0.9.0', f'{BASE_ID}.Test', BASE_ID, profile, None)
    app.demo = demo
    app.engine = FakeEngine()
    app.library = FakeLibrary()
    app.toasts = []
    app.toast = lambda title, button_label=None, action_name=None: app.toasts.append(
        (title, button_label, action_name))
    app.library_sync = LibrarySync(app)
    app._follow_account()
    return app


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.addCleanup(config.set_build_profile, 'default')
        self.app = make_app()
        for key in ('signed-in', 'account-name', 'last-sync', 'sync-interval'):
            self.addCleanup(self.app.settings.reset, key)


class StartSyncTest(AppTestCase):
    def test_demo_refuses(self):
        self.app.demo = True
        self.assertIsNone(self.app.start_sync())
        self.assertEqual(self.app.toasts, [('Not available with the demo library', None, None)])
        self.assertEqual(self.app.engine.calls, [])

    def test_signed_out_starts_nothing_and_offers_the_sign_in(self):
        asked = []
        self.app.activate_action = lambda name, parameter=None: asked.append(name)
        with self.assertLogs('applemusic.main', 'WARNING'):
            self.assertIsNone(self.app.start_sync())
        self.assertEqual(asked, ['sign-in'])
        self.assertEqual(self.app.engine.calls, [])
        self.assertFalse(self.app.library_sync.props.running)

    def test_the_action_follows_the_account_the_demo_and_the_sync(self):
        action = self.app.lookup_action('sync')
        self.assertFalse(action.get_enabled())  # signed out
        self.app.settings.set_boolean('signed-in', True)
        self.assertTrue(action.get_enabled())
        self.app.library_sync.props.running = True
        self.assertFalse(action.get_enabled())
        self.app.library_sync.props.running = False
        self.assertTrue(action.get_enabled())
        self.app.signing_out = True
        self.assertFalse(action.get_enabled())
        self.app.signing_out = False
        self.app.demo = True
        self.app._update_sync_action()
        self.assertFalse(action.get_enabled())


class QuitTest(AppTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(main.Gio.Application, 'quit',
                                    lambda app: self.app.engine.calls.append('quit'))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_a_start_under_way_is_cancelled_first(self):
        app = self.app
        app.engine.start_blocks = True
        app._autostart_task = asyncio.ensure_future(app.engine.start())
        await asyncio.sleep(0)
        started = asyncio.get_running_loop().time()
        await app._quit()
        self.assertLess(asyncio.get_running_loop().time() - started, 1.0)
        self.assertTrue(app._autostart_task.cancelled())
        self.assertEqual(app.engine.calls, ['start', ('stop', main.QUIT_GRACE), 'quit'])

    async def test_a_stop_that_hangs_is_killed_then_quits(self):
        app = self.app
        app.engine.stop_blocks = True
        app.engine.pid = 4242
        with mock.patch.object(main, 'QUIT_TIMEOUT', 0.05), \
                self.assertLogs('applemusic.main', 'WARNING'):
            await app._quit()
        self.assertEqual(app.engine.calls, [('stop', main.QUIT_GRACE), 'kill', 'quit'])

    async def test_the_sync_is_stopped_within_the_bound(self):
        app = self.app
        cancelled = []

        async def cancel():
            cancelled.append(True)

        app.library_sync.cancel = cancel
        await app._quit()
        self.assertEqual(cancelled, [True])

    async def test_a_sign_out_under_way_is_let_finish(self):
        app = self.app
        order = []
        revocation = app.revocation = asyncio.ensure_future(
            asyncio.get_running_loop().create_future())

        async def sign_out():
            await asyncio.wait([revocation])  # as account.sign_out() waits for it
            await asyncio.sleep(0.05)  # the wipe
            order.append('wiped')

        async def finish():
            await asyncio.get_running_loop().create_future()  # the name read, say

        app._sign_out_task = asyncio.ensure_future(sign_out())
        app.sign_in_finish = asyncio.ensure_future(finish())
        await asyncio.sleep(0)
        app.engine.calls = order
        await app._quit()
        self.assertTrue(revocation.cancelled())
        self.assertTrue(app.sign_in_finish.cancelled())
        self.assertEqual(order, [('stop', main.QUIT_GRACE), 'wiped', 'quit'])
        app.settings.set_boolean('signed-in', True)
        self.assertIsNone(app.library_sync.start())  # held: nothing starts while quitting

    async def test_the_last_session_is_taken_before_the_engine_stops(self):
        app = self.app
        order = app.engine.calls

        class Keeper:
            def save_now(self):
                order.append(('save', app.engine.state))  # the Player not emptied yet
                return asyncio.ensure_future(asyncio.sleep(0, 'written'))

        app.engine.state = 'up'
        app.session = Keeper()
        await app._quit()
        self.assertEqual(order, [('save', 'up'), ('stop', main.QUIT_GRACE), 'quit'])

    async def test_the_last_session_is_restored_once_the_library_has_loaded(self):
        app = self.app
        order = []

        async def load_library():
            order.append('library')

        class Keeper:
            async def load(self):
                order.append('session')

        app.load_library = load_library
        app.session = Keeper()
        await app._restore_session()
        self.assertEqual(order, ['library', 'session'])
        app._quitting = object()  # quitting meanwhile: nothing shown
        await app._restore_session()
        self.assertEqual(order, ['library', 'session', 'library'])

    def test_activating_while_quitting_shows_nothing(self):
        self.app._quitting = object()
        self.app.do_activate()  # no window made: the stand-ins have none to give
        self.assertIsNone(self.app.get_active_window())


class MiniPlayerTest(AppTestCase):
    """What the app does with its mini player (mini_player.py; its own tests are
    test_mini_player.py's): app.mini-player toggles it, never while quitting; quitting closes
    it; a search result's window is the main one, the mini player left for it."""

    class Host:
        def __init__(self):
            self.calls = []
            self.shown = False

        def toggle(self):
            self.calls.append('toggle')

        def leave(self):
            self.calls.append('leave')
            self.shown = False

        def quit(self):
            self.calls.append('quit')

    def setUp(self):
        super().setUp()
        self.host = self.app.mini_player = self.Host()

    def test_the_action_toggles_it(self):
        self.app.lookup_action('mini-player').activate(None)
        self.assertEqual(self.host.calls, ['toggle'])
        self.app._quitting = object()
        self.app.lookup_action('mini-player').activate(None)
        self.assertEqual(self.host.calls, ['toggle'])

    def test_its_accelerator(self):
        self.assertEqual(self.app.get_accels_for_action('app.mini-player'),
                         ['<Shift><Control>m'])

    async def test_quitting_closes_it(self):
        with mock.patch.object(main.Gio.Application, 'quit', lambda app: None):
            await self.app._quit()
        self.assertEqual(self.host.calls, ['quit'])

    def test_the_main_window_shown_leaves_it(self):
        main_window = object()
        activated = []
        self.app.activate = lambda: activated.append(True)
        self.app.main_window = lambda: main_window
        self.host.shown = True
        self.assertIs(self.app.show_main_window(), main_window)
        self.assertEqual((self.host.calls, activated), (['leave'], [True]))
        self.assertIs(self.app.show_main_window(), main_window)  # not shown: nothing to leave
        self.assertEqual(self.host.calls, ['leave'])

    def test_the_main_window_is_never_the_mini_player(self):
        self.assertIsNone(self.app.main_window())  # no window yet

    def test_an_announcement_goes_through_the_window_in_sight(self):
        # Up Next's edits run the main window's actions from the mini player's pane too,
        # and GTK drops what a hidden window announces.
        said = []
        main_window = mock.Mock(announce=lambda text, _priority: said.append(('main', text)))
        self.host.window = mock.Mock(
            announce=lambda text, _priority: said.append(('mini', text)))
        self.app.main_window = lambda: main_window
        self.app.announce('Removed from Up Next')
        self.host.shown = True
        self.app.announce('Removed from Up Next')
        self.assertEqual(said, [('main', 'Removed from Up Next'),
                                ('mini', 'Removed from Up Next')])
        self.host.shown = False
        self.app.main_window = lambda: None
        self.app.announce('Nobody to tell')  # no window yet: nothing


class BackgroundTest(AppTestCase):
    def test_a_closed_window_gets_a_notification_instead_of_a_toast(self):
        app = self.app
        del app.toast  # the Application's own, not the recording stand-in
        sent, withdrawn, released = [], [], []
        app.send_notification = lambda ident, notification: sent.append(ident)
        app.withdraw_notification = withdrawn.append
        app.release = lambda: released.append(True)
        app.background = mock.Mock(active=True)
        app.toast('Could not sync your library', 'Retry', 'app.sync')
        self.assertEqual(sent, [main.BACKGROUND_NOTIFICATION])
        app._release_background()  # the window is back
        self.assertEqual((withdrawn, released), ([main.BACKGROUND_NOTIFICATION], [True]))

    def notify(self, *args):
        """The buttons the notification for app.toast(*args) is given, with the window
        closed for background playback: [(method, label, action, target)]."""
        app = self.app
        del app.toast
        app.background = mock.Mock(active=True)
        app.send_notification = mock.Mock()
        with mock.patch.object(main.Gio, 'Notification') as notification:
            app.toast(*args)
        app.send_notification.assert_called_once()
        made = notification.new.return_value
        return ([('with-target', *call.args) for call in made.add_button_with_target.call_args_list]
                + [('plain', *call.args) for call in made.add_button.call_args_list])

    def test_a_window_actions_button_runs_through_an_app_action(self):
        # A notification's button can only run app.* actions: win.item-undo-reorder's Undo
        # did nothing (and GLib warned).
        buttons = self.notify('Moved', 'Undo', 'win.item-undo-reorder', GLib.Variant('s', 'p.1'))
        self.assertEqual(len(buttons), 1)
        method, label, action, target = buttons[0]
        self.assertEqual((method, label, action), ('with-target', 'Undo', 'app.window-action'))
        self.assertEqual(target.unpack(), ('item-undo-reorder', ['p.1']))
        self.assertIsNotNone(self.app.lookup_action('window-action'))

    def test_an_app_actions_button_is_kept(self):
        self.assertEqual(self.notify('Could not sync', 'Retry', 'app.sync'),
                         [('plain', 'Retry', 'app.sync')])

    def test_an_action_of_neither_gets_no_button(self):
        self.assertEqual(self.notify('Something', 'Do', 'page.do'), [])


class WindowActionTest(AppTestCase):
    def window_with(self, name, parameter_type):
        """A stand-in window with one action, recording its targets; the app's windows."""
        window = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new(name, parameter_type)
        ran = []
        action.connect('activate', lambda _action, target: ran.append(
            None if target is None else target.unpack()))
        window.add_action(action)
        self.app.get_windows = lambda: [object(), window]
        return ran

    def test_runs_the_windows_action_with_its_target(self):
        ran = self.window_with('item-move-to-folder', GLib.VariantType.new('(sss)'))
        name, target = main.app_action('win.item-move-to-folder',
                                       GLib.Variant('(sss)', ('p.fd1', 'playlist', 'p.pl1')))
        self.assertEqual(name, 'app.window-action')
        self.app.lookup_action('window-action').activate(target)
        self.assertEqual(ran, [('p.fd1', 'playlist', 'p.pl1')])

    def test_runs_an_action_without_a_target(self):
        ran = self.window_with('refresh', None)
        self.app.lookup_action('window-action').activate(main.app_action('win.refresh')[1])
        self.assertEqual(ran, [None])

    def test_no_window_with_it_is_only_logged(self):
        self.app.get_windows = lambda: []
        with self.assertLogs('applemusic.main', 'WARNING'):
            self.app.lookup_action('window-action').activate(main.app_action('win.refresh')[1])

    def test_every_app_actions_parameter_type_can_be_exported_on_the_bus(self):
        # The bus's DescribeAll writes each parameter type as a D-Bus signature, which has
        # no maybe type: one with an 'm' aborted the process once something described the
        # app's actions.
        added = []
        add_action = main.Application.add_action

        def record(app, action):
            added.append(action)
            add_action(app, action)

        with mock.patch.object(main.Application, 'add_action', record):
            make_app()
        self.assertIn('window-action', [action.get_name() for action in added])
        for action in added:
            parameter_type = action.get_parameter_type()
            if parameter_type is not None:
                self.assertTrue(GLib.Variant.is_signature(parameter_type.dup_string()),
                                f'app.{action.get_name()}: {parameter_type.dup_string()}')

    def test_app_actions_are_left_as_they_are(self):
        target = GLib.Variant('s', 'x')
        self.assertEqual(main.app_action('app.sync', target), ('app.sync', target))
        self.assertEqual(main.app_action(None), (None, None))

    def test_a_toast_in_preferences_runs_the_windows_action_through_the_app(self):
        # Preferences shown as a window of its own has only the app's actions.
        app = self.app
        del app.toast
        toasts = []
        app._preferences = mock.Mock(add_toast=toasts.append)
        app.toast('Moved', 'Undo', 'win.item-undo-reorder', GLib.Variant('s', 'p.1'))
        (toast,) = toasts
        self.assertEqual(toast.get_action_name(), 'app.window-action')
        self.assertEqual(toast.get_action_target_value().unpack(), ('item-undo-reorder', ['p.1']))

    def test_a_toast_in_the_mini_player_runs_the_windows_action_through_the_app(self):
        # A write begun in the main window that ends once the mini player shows: its toast
        # is the mini player's, which has none of the window's actions (its Undo was dead).
        app = self.app
        del app.toast
        toasts = []
        mini = mock.Mock(add_toast=toasts.append)
        app.mini_player = mock.Mock(shown=True, window=mini)
        app.get_active_window = lambda: mini
        app.toast('Removed 2 songs', 'Undo', 'win.item-undo-remove', GLib.Variant('s', 'p.1'))
        app.toast('Queue cleared', 'Undo', 'app.undo-clear-up-next')
        removed, cleared = toasts
        self.assertEqual(removed.get_action_name(), 'app.window-action')
        self.assertEqual(removed.get_action_target_value().unpack(),
                         ('item-undo-remove', ['p.1']))
        self.assertEqual(cleared.get_action_name(), 'app.undo-clear-up-next')  # as it is
        # The main window's own toasts keep the window's action.
        app.mini_player.shown = False
        app.toast('Removed 2 songs', 'Undo', 'win.item-undo-remove', GLib.Variant('s', 'p.1'))
        self.assertEqual(toasts[-1].get_action_name(), 'win.item-undo-remove')


class RatedTest(AppTestCase):
    def test_the_library_follows_the_engines_ratings(self):
        # A favourite made or taken back here, or a rating read (Engine's `rated`): the
        # library's hearts follow at once. Suggest Less (-1) is no favourite.
        calls = []
        self.app.library = mock.Mock(set_favourite=lambda *args: calls.append(args))
        for value in (1, 0, -1):
            self.app._on_rated(None, 'song', '9001', value)
        self.assertEqual(calls, [('9001', True), ('9001', False), ('9001', False)])
        # An artist's favourite (their star) is none of the library's.
        self.app._on_rated(None, 'artist', '9002', 1)
        self.assertEqual(len(calls), 3)


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(config.set_build_profile, 'default')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': ''})
        patcher.start()
        self.addCleanup(patcher.stop)

    def app(self, profile='development', demo_dir=None):
        return main.Application('0.9.0', f'{BASE_ID}.DemoTest', BASE_ID, profile, demo_dir)

    def test_the_demo_keeps_its_settings_apart(self):
        app = self.app(demo_dir=self.tmp.name)
        # The desktop's settings, as a backend of their own (the tests' default is memory).
        desktop = Gio.keyfile_settings_backend_new(
            os.path.join(self.tmp.name, 'desktop.ini'), '/', None)
        app.settings = Gio.Settings.new_full(app.settings.props.settings_schema, desktop, None)
        self.assertTrue(app._use_demo())
        self.assertTrue(app.demo)
        self.assertEqual(os.environ['APPLE_MUSIC_CACHE'], self.tmp.name)
        backend = app.settings.props.backend
        self.assertIsNot(backend, desktop)
        self.assertNotEqual(backend, Gio.SettingsBackend.get_default())
        app.settings.set_string('last-page', 'albums')
        Gio.Settings.sync()
        with open(os.path.join(self.tmp.name, 'settings.ini'), encoding='utf-8') as file:
            self.assertIn('albums', file.read())
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'desktop.ini')))

    def test_settings_on_the_memory_backend_are_kept(self):
        app = self.app(demo_dir=self.tmp.name)
        settings = app.settings
        self.assertTrue(app._use_demo())
        self.assertIs(app.settings, settings)

    def test_a_release_build_needs_a_library_named(self):
        app = self.app(profile='default')
        with self.assertLogs('applemusic.main', 'ERROR'):
            self.assertFalse(app._use_demo())
        self.assertFalse(app.demo)
        os.environ['APPLE_MUSIC_CACHE'] = self.tmp.name  # a generated library named
        self.assertTrue(app._use_demo())

    def test_a_demo_dir_that_is_not_there_is_no_library(self):
        # The Flatpak's DEMO_DIR is a path in its build sandbox, gone once installed; a
        # checkout's build/demo before scripts/demo.sh has written it. Neither is shown as an
        # empty library (nor gets a settings file made for it).
        missing = os.path.join(self.tmp.name, 'build', 'demo')
        app = self.app(demo_dir=missing)
        with self.assertLogs('applemusic.main', 'ERROR') as logs:
            self.assertFalse(app._use_demo())
        self.assertIn(missing, logs.output[0])
        self.assertFalse(app.demo)
        self.assertEqual(os.environ['APPLE_MUSIC_CACHE'], '')
        self.assertFalse(os.path.exists(missing))
        os.environ['APPLE_MUSIC_CACHE'] = self.tmp.name  # a library named instead
        self.assertTrue(app._use_demo())

    def test_the_demo_has_no_mpris(self):
        app = self.app(demo_dir=self.tmp.name)
        app._use_demo()
        app.library = FakeLibrary()
        with mock.patch.object(main, 'Mpris') as mpris:
            app._make_parts()
        mpris.assert_not_called()
        self.assertIsNone(app.mpris)
        self.assertIsNone(app.session)  # the demo keeps no session, reads none
        self.assertTrue(app.engine.demo)


class AccountKeyTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(config.set_build_profile, 'default')

    def test_the_development_build_has_keys_of_its_own(self):
        release = make_app(profile='default')
        devel = make_app(profile='development')
        schema = devel.settings.props.settings_schema
        for name in main.ACCOUNT_KEYS:
            self.assertEqual(release.account_key(name), name)
            self.assertEqual(devel.account_key(name), name + '-devel')
            self.assertTrue(schema.has_key(devel.account_key(name)), name)
        self.assertEqual(devel.account_key('sync-interval'), 'sync-interval')

    def test_the_development_app_reads_its_own(self):
        app = make_app(profile='development')
        for key in ('signed-in', 'signed-in-devel'):
            self.addCleanup(app.settings.reset, key)
        action = app.lookup_action('sync')
        app.settings.set_boolean('signed-in', True)  # the release build's sign-in
        self.assertFalse(action.get_enabled())
        self.assertFalse(app._autostart_wanted())
        app.settings.set_boolean('signed-in-devel', True)
        self.assertTrue(action.get_enabled())
        self.assertTrue(app._autostart_wanted())


class AutostartTest(AppTestCase):
    """Chrome at launch (_autostart_wanted(), _autostart()): only signed in, with
    engine-autostart on, never in the demo; a failed start reported, a sign-in gone said
    with Sign In, and the account's name read from the page when the sign-in missed it."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.app.settings.reset, 'engine-autostart')
        self.reported = []
        self.app.report = self.reported.append
        self.asked = []  # account_name()'s waits

        async def account_name(wait=None):
            self.asked.append(wait)
            return self.name

        self.name = 'Invented Listener'
        self.app.engine.account_name = account_name

    def test_wanted_signed_in_with_its_setting_and_not_in_the_demo(self):
        app = self.app
        self.assertFalse(app._autostart_wanted())  # signed out
        app.settings.set_boolean('signed-in', True)
        self.assertTrue(app._autostart_wanted())
        app.settings.set_boolean('engine-autostart', False)
        self.assertFalse(app._autostart_wanted())
        app.settings.set_boolean('engine-autostart', True)
        app.demo = True
        self.assertFalse(app._autostart_wanted())

    async def test_a_failed_start_is_reported_and_nothing_more(self):
        error = EngineError('no-browser')

        async def start(visible=None):
            raise error

        self.app.engine.start = start
        await self.app._autostart()
        self.assertEqual(self.reported, [error])
        self.assertEqual((self.app.toasts, self.asked), ([], []))

    async def test_a_sign_in_gone_offers_to_sign_in_again(self):
        async def start(visible=None):
            self.app.engine.state = 'up'  # up, but Apple Music is not signed in

        self.app.engine.start = start
        with self.assertLogs('applemusic.main', 'WARNING'):
            await self.app._autostart()
        self.assertEqual(self.app.toasts, [('Your Apple Music sign-in has expired', 'Sign In',
                                            'app.sign-in')])
        self.assertEqual((self.reported, self.asked), ([], []))

    async def test_a_name_the_sign_in_missed_is_read_from_the_page(self):
        await self.app._autostart()
        self.assertEqual(self.asked, [10])
        self.assertEqual(self.app.settings.get_string('account-name'), 'Invented Listener')
        self.assertEqual(self.app.toasts, [])

    async def test_a_name_known_is_not_asked_again(self):
        self.app.settings.set_string('account-name', 'Someone Invented')
        await self.app._autostart()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.app.settings.get_string('account-name'), 'Someone Invented')

    async def test_a_name_the_page_has_not_either_is_left_unset(self):
        self.name = ''
        await self.app._autostart()
        self.assertEqual(self.app.settings.get_string('account-name'), '')

        async def account_name(wait=None):
            raise EngineError('timeout')

        self.app.engine.account_name = account_name
        await self.app._autostart()  # only logged
        self.assertEqual(self.app.settings.get_string('account-name'), '')
        self.assertEqual((self.reported, self.app.toasts), ([], []))


class StartEngineTest(AppTestCase):
    """app.start-engine (start_engine()): one start at a time, its failure reported; none in
    the demo."""

    def setUp(self):
        super().setUp()
        self.reported = []
        self.app.report = self.reported.append

    def test_the_demo_has_no_engine_to_start(self):
        self.app.demo = True
        self.assertIsNone(self.app.start_engine())
        self.assertEqual(self.app.toasts, [('Not available with the demo library', None, None)])
        self.assertEqual(self.app.engine.calls, [])

    async def test_a_start_under_way_is_the_one_answered(self):
        engine = self.app.engine
        engine.start_blocks = True
        first = self.app.start_engine()
        await asyncio.sleep(0)
        self.assertIs(self.app.start_engine(), first)
        self.app.lookup_action('start-engine').activate(None)  # a toast's Restart: the same
        await asyncio.sleep(0)
        self.assertEqual(engine.calls, ['start'])
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        # Once it is over, the next asks for a start of its own.
        engine.start_blocks = False
        second = self.app.start_engine()
        self.assertIsNot(second, first)
        await second
        self.assertEqual((engine.calls, engine.state), (['start', 'start'], 'up'))
        self.assertEqual(self.reported, [])

    async def test_a_failed_start_is_reported(self):
        error = EngineError('no-browser')

        async def start(visible=None):
            raise error

        self.app.engine.start = start
        await self.app.start_engine()
        self.assertEqual(self.reported, [error])


class PlayerCommandTest(AppTestCase):
    """player_command(): the one runner of the Player's commands reports an EngineError and
    calls on_error() to put the widget back; a command that succeeds says nothing."""

    def setUp(self):
        super().setUp()
        self.reported = []
        self.app.report = self.reported.append

    async def test_a_failure_is_reported_and_the_widget_put_back(self):
        error = EngineError('timeout')
        put_back = []

        async def command():
            raise error

        await self.app.player_command(command(), on_error=lambda: put_back.append(True))
        self.assertEqual((self.reported, put_back), ([error], [True]))

    async def test_a_failure_without_on_error(self):
        async def command():
            raise EngineError('timeout')

        await self.app.player_command(command())
        self.assertEqual(len(self.reported), 1)

    async def test_success_says_nothing(self):
        put_back = []

        async def command():
            return 'done'

        await self.app.player_command(command(), on_error=lambda: put_back.append(True))
        self.assertEqual((self.reported, put_back), ([], []))


class PlaybackActionsTest(AppTestCase):
    """Play/Pause is enabled while there is an item, Next and Previous while MusicKit allows
    them too (_on_track_changed); all three start disabled."""

    def enabled(self):
        return [self.app.lookup_action(name).get_enabled()
                for name in ('play-pause', 'next', 'previous')]

    def changed(self, track, can_go_next=True, can_go_previous=True):
        player = mock.Mock(track=track, can_go_next=can_go_next,
                           can_go_previous=can_go_previous)
        self.app._on_track_changed(player, None)

    def test_the_actions_follow_the_item(self):
        self.assertEqual(self.enabled(), [False, False, False])
        self.changed(object())
        self.assertEqual(self.enabled(), [True, True, True])
        self.changed(object(), can_go_next=False)
        self.assertEqual(self.enabled(), [True, False, True])
        self.changed(object(), can_go_previous=False)
        self.assertEqual(self.enabled(), [True, True, False])
        # A live station: neither.
        self.changed(object(), can_go_next=False, can_go_previous=False)
        self.assertEqual(self.enabled(), [True, False, False])
        # Nothing playing: none, whatever MusicKit last said.
        self.changed(None)
        self.assertEqual(self.enabled(), [False, False, False])


class AccountActionsTest(AppTestCase):
    """Sign In and Sign Out are off while either runs (signing-in, signing-out)."""

    def test_off_while_the_account_changes(self):
        actions = [self.app.lookup_action(name) for name in ('sign-in', 'sign-out')]
        self.assertEqual([action.get_enabled() for action in actions], [True, True])
        for prop in ('signing-in', 'signing-out'):
            self.app.set_property(prop, True)
            self.assertEqual([action.get_enabled() for action in actions], [False, False])
            self.app.set_property(prop, False)
            self.assertEqual([action.get_enabled() for action in actions], [True, True])

    def test_the_sign_out_runs_only_when_confirmed(self):
        async def sign_out(app):
            pass

        spawned = []

        def spawn(coro):
            spawned.append(coro.cr_code.co_name)
            coro.close()

        self.app.spawn = spawn
        with mock.patch('applemusic.account.sign_out', sign_out):
            self.app._on_sign_out_response(None, 'cancel')
            self.assertEqual(spawned, [])
            self.app._on_sign_out_response(None, 'sign-out')
        self.assertEqual(spawned, ['sign_out'])


class CloseWindowTest(AppTestCase):
    """close_window(): with background playback on and something playing the window hides
    and the music plays on; otherwise, and while quitting, the app quits."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.app.settings.reset, 'background-playback')
        self.asked = []
        self.app.activate_action = lambda name, parameter=None: self.asked.append(name)
        self.app.player = mock.Mock(active=True)
        self.app.background = mock.Mock()
        self.window = mock.Mock()

    def test_background_playback_keeps_the_music_on(self):
        self.app.settings.set_boolean('background-playback', True)
        self.app.close_window(self.window)
        self.window.put_away.assert_called_once_with()
        self.app.background.enter.assert_called_once_with(self.window)
        self.assertEqual(self.asked, [])

    def test_otherwise_the_app_quits(self):
        self.app.close_window(self.window)  # the setting off (its default)
        self.app.settings.set_boolean('background-playback', True)
        self.app.player.active = False  # nothing playing
        self.app.close_window(self.window)
        self.app.player.active = True
        self.app._quitting = object()  # quitting already
        self.app.close_window(self.window)
        self.assertEqual(self.asked, ['quit', 'quit', 'quit'])
        self.window.put_away.assert_not_called()
        self.app.background.enter.assert_not_called()


class MakeEngineTest(unittest.IsolatedAsyncioTestCase):
    """_make_engine(): the Engine made from the settings (the browser program, the preferred
    mode, the streaming quality), which then follows them; the quality goes to MusicKit at
    once (_set_bitrate), a failure there only logged. The demo's has no settings."""

    class Engine:
        def __init__(self, browser_command=None, demo=False):
            self.browser_command = browser_command
            self.demo = demo
            self.bitrates = []
            self.fail = None

        async def set_bitrate(self, bitrate):
            self.bitrates.append(bitrate)
            if self.fail is not None:
                raise self.fail

    def setUp(self):
        self.addCleanup(config.set_build_profile, 'default')
        self.app = main.Application('0.9.0', f'{BASE_ID}.Test', BASE_ID, 'default', None)
        self.settings = self.app.settings
        for key in ('browser-command', 'engine-headless', 'streaming-quality'):
            self.addCleanup(self.settings.reset, key)
        patcher = mock.patch.object(main, 'Engine', self.Engine)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_made_from_the_settings_and_following_them(self):
        settings = self.settings
        settings.set_string('browser-command', 'invented-browser')
        settings.set_boolean('engine-headless', False)
        settings.set_string('streaming-quality', 'standard')
        engine = self.app.engine = self.app._make_engine()
        self.assertEqual((engine.browser_command, engine.prefer_headless,
                          engine.preferred_bitrate), ('invented-browser', False, 64))
        settings.set_string('browser-command', '/opt/invented/browser')
        settings.set_boolean('engine-headless', True)
        self.assertEqual((engine.browser_command, engine.prefer_headless),
                         ('/opt/invented/browser', True))
        settings.set_string('streaming-quality', 'high')
        for _turn in range(3):
            await asyncio.sleep(0)
        self.assertEqual(engine.bitrates, [256])

    async def test_a_bitrate_the_engine_cannot_take_is_only_logged(self):
        engine = self.app.engine = self.app._make_engine()
        engine.fail = EngineError('engine-down')
        with self.assertLogs('applemusic.main', 'DEBUG'):
            await self.app._set_bitrate('standard')
        self.assertEqual(engine.bitrates, [64])

    def test_the_demos_engine(self):
        self.app.demo = True
        engine = self.app._make_engine()
        self.assertTrue(engine.demo)
        self.assertFalse(hasattr(engine, 'prefer_headless'))


class LocalOptionsTest(unittest.TestCase):
    """--debug sets the log level; --demo with no demo library to show ends the run."""

    def setUp(self):
        self.addCleanup(config.set_build_profile, 'default')
        self.app = main.Application('0.9.0', f'{BASE_ID}.Test', BASE_ID, 'default', None)
        root = logging.getLogger()
        self.addCleanup(root.setLevel, root.level)
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': ''})
        patcher.start()
        self.addCleanup(patcher.stop)

    def options(self, *names):
        options = GLib.VariantDict.new(None)
        for name in names:
            options.insert_value(name, GLib.Variant('b', True))
        return options

    def test_none(self):
        self.assertEqual(self.app.do_handle_local_options(self.options()), -1)
        self.assertFalse(self.app.demo)

    def test_debug(self):
        logging.getLogger().setLevel(logging.INFO)
        self.assertEqual(self.app.do_handle_local_options(self.options('debug')), -1)
        self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_demo_without_a_library_ends_the_run(self):
        with self.assertLogs('applemusic.main', 'ERROR'):
            self.assertEqual(self.app.do_handle_local_options(self.options('demo')), 1)
        self.assertFalse(self.app.demo)

    def test_demo_with_a_library(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ['APPLE_MUSIC_CACHE'] = directory
            self.assertEqual(self.app.do_handle_local_options(self.options('demo')), -1)
        self.assertTrue(self.app.demo)


class ConstructionTest(unittest.TestCase):
    def test_the_profile_sets_the_paths(self):
        self.addCleanup(config.set_build_profile, 'default')
        with mock.patch.dict('os.environ', {'APPLE_MUSIC_CACHE': ''}):
            make_app(profile='development')
            self.assertTrue(str(config.cache_dir()).endswith('apple-music-devel'))
            make_app(profile='default')
            self.assertTrue(str(config.cache_dir()).endswith('apple-music'))


if __name__ == '__main__':
    unittest.main()
