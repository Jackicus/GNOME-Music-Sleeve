# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Application (src/main.py) built without being run: its settings on the memory backend,
stand-ins for the engine, the player and the library, no window. What it decides on its own:
when a sync may start, how it quits (where errors go: tests/test_errors.py).
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from gi.repository import Gio, GLib, GObject

from applemusic import main
from applemusic.backend import config
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
        self.assertEqual(target.unpack(), ('item-undo-reorder', 'p.1'))
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
        self.assertEqual(toast.get_action_target_value().unpack(), ('item-undo-reorder', 'p.1'))


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
