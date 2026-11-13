# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Preferences dialog (src/dialogs/preferences.py) over a stand-in application and
engine, never presented: what its rows say for each state of the engine, the account and the
sync, what Start and Stop, the choice rows, the browser program and Clear do, and that it lets
go of everything when it closes. (That a closed dialog is freed: test_page_lifetime.py.)
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.gtk import SCHEMA_ID, requires_gtk

from gi.repository import Gio, GObject

from applemusic.backend.errors import EngineError

KEYS = ('sync-interval', 'streaming-quality', 'browser-command', 'last-sync', 'signed-in',
        'account-name', 'background-playback')


class Engine(GObject.Object):
    """What Preferences reads of the Engine, and its start, stop, status and browser check,
    recorded; `stop_error` is raised by stop(), `found` is the path browser_path() answers."""

    state = GObject.Property(type=str, default='down')
    authorized = GObject.Property(type=bool, default=False)
    headless = GObject.Property(type=bool, default=True)
    widevine = GObject.Property(type=bool, default=True)
    bitrate = GObject.Property(type=int, default=0)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.stop_error = None
        self.found = '/usr/bin/invented-browser'
        self.hold = None  # a future stop() waits for, when set

    async def stop(self):
        self.calls.append('stop')
        if self.hold is not None:
            await self.hold
        if self.stop_error is not None:
            raise self.stop_error
        self.state = 'down'

    async def status(self):
        self.calls.append('status')
        self.bitrate = 256

    async def browser_path(self, text):
        self.calls.append(('browser_path', text))
        return self.found


class LibrarySync(GObject.Object):
    running = GObject.Property(type=bool, default=False)


class App(Gio.SimpleActionGroup):
    """The Application as Preferences sees it: an action group (inserted as `app`), the
    settings on the memory backend, the engine and the sync, and a record of what it was
    asked."""

    signing_out = GObject.Property(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.engine = Engine()
        self.library_sync = LibrarySync()
        self.demo = False
        self.tasks = []
        self.actions = []
        self.toasts = []
        self.reported = []
        self.starts = 0
        self.cleared = []  # what clear_cache() answers, in turn
        self.add_action(Gio.SimpleAction.new('sync', None))

    def account_key(self, name):
        return name

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    async def settle(self):
        while not all(task.done() for task in self.tasks):
            await asyncio.gather(*self.tasks, return_exceptions=True)

    def refuse_in_demo(self):
        return self.demo

    def start_engine(self):
        if self.demo:
            return None
        self.starts += 1

        async def start():
            self.engine.state = 'starting'
            await asyncio.sleep(0)
            self.engine.state = 'up'

        return self.spawn(start())

    def report(self, error):
        self.reported.append(error.code)

    def toast(self, title):
        self.toasts.append(title)

    def activate_action(self, name, _parameter=None):
        self.actions.append(name)

    async def clear_cache(self):
        await asyncio.sleep(0)
        answer = self.cleared.pop(0) if self.cleared else True
        if isinstance(answer, BaseException):
            raise answer
        return answer


@requires_gtk
class PreferencesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from applemusic.dialogs.preferences import PreferencesDialog

        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = cache.name
        self.app = App()
        for key in KEYS:
            self.addCleanup(self.app.settings.reset, key)
        self.engine = self.app.engine
        self.dialog = PreferencesDialog(self.app)
        await self.app.settle()  # the cache measured
        self.addAsyncCleanup(self.close)

    async def close(self):
        if not self.dialog._closed:
            self.closed()
        await self.app.settle()

    def closed(self):
        """The dialog closed, as its `closed` says (it is never presented here, and
        force_close() closes only a presented one)."""
        self.dialog.emit('closed')

    def engine_says(self):
        return self.dialog.engine_row.get_subtitle()

    # -- the engine ------------------------------------------------------------------------

    def test_the_engine_rows_subtitle_follows_its_state(self):
        engine = self.engine
        self.assertEqual(self.engine_says(), 'Not running')
        self.assertEqual(self.dialog.engine_button.get_label(), '_Start')
        engine.state = 'starting'
        self.assertEqual(self.engine_says(), 'Starting…')
        engine.state = 'signing-in'
        self.assertEqual(self.engine_says(), 'Signing in…')
        engine.state = 'up'
        self.assertEqual(self.engine_says(), 'Running, not signed in')
        self.assertEqual(self.dialog.engine_button.get_label(), '_Stop')
        engine.authorized = True
        self.assertEqual(self.engine_says(), 'Running hidden')
        engine.headless = False
        self.assertEqual(self.engine_says(), 'Running in a window')
        engine.widevine = False  # says so before anything else, once up
        self.assertEqual(self.engine_says(), 'Running, but this browser cannot play songs')
        engine.state = 'down'
        self.assertEqual(self.engine_says(), 'Not running')
        self.assertTrue(self.dialog.engine_button.get_sensitive())

    async def test_start_while_down_stop_while_up(self):
        button = self.dialog.engine_button
        button.emit('clicked')
        self.assertTrue(self.dialog._engine_busy)
        button.emit('clicked')  # busy: nothing more
        await self.app.settle()
        self.assertEqual((self.app.starts, self.engine.state), (1, 'up'))
        self.assertFalse(self.dialog._engine_busy)
        button.emit('clicked')
        await self.app.settle()
        self.assertEqual((self.engine.calls[-1], self.engine.state), ('stop', 'down'))

    async def test_nothing_while_it_changes(self):
        for state in ('starting', 'signing-in'):
            self.engine.state = state
            self.dialog.engine_button.emit('clicked')
            self.assertFalse(self.dialog._engine_busy)
        await self.app.settle()
        self.assertEqual((self.app.starts, self.engine.calls), (0, []))

    async def test_a_failed_stop_is_reported_and_the_button_free_again(self):
        self.engine.state = 'up'
        self.engine.stop_error = EngineError('timeout')
        self.dialog.engine_button.emit('clicked')
        await self.app.settle()
        self.assertEqual(self.app.reported, ['timeout'])
        self.assertFalse(self.dialog._engine_busy)

    async def test_a_command_that_ends_after_the_close_touches_nothing(self):
        self.engine.state = 'up'
        self.engine.hold = asyncio.get_running_loop().create_future()
        self.dialog.engine_button.emit('clicked')
        await asyncio.sleep(0)
        self.closed()
        updates = []
        self.dialog._update_engine = lambda *args: updates.append(args)
        self.engine.hold.set_result(None)
        await self.app.settle()
        self.assertEqual(updates, [])  # nor does the closed dialog follow the engine
        self.assertEqual(self.engine.state, 'down')

    async def test_the_demo_has_no_engine(self):
        self.closed()
        self.app.demo = True
        from applemusic.dialogs.preferences import PreferencesDialog

        self.dialog = PreferencesDialog(self.app)
        self.assertEqual(self.engine_says(), 'Not used with the demo library')
        self.assertFalse(self.dialog.engine_button.get_sensitive())
        self.assertEqual(self.dialog.account_group.get_description(),
                         'Not used with the demo library')
        self.assertTrue(self.dialog.sign_in_row.get_visible())
        self.assertFalse(self.dialog.sign_in_row.get_sensitive())
        self.assertFalse(self.dialog.sign_out_row.get_visible())
        self.dialog.clear_button.emit('clicked')  # refused: no dialog asks
        self.assertFalse(self.dialog._clearing)

    # -- the streaming quality -------------------------------------------------------------

    async def test_the_quality_row_and_its_setting_follow_each_other(self):
        row, settings = self.dialog.quality_row, self.app.settings
        self.assertEqual(row.get_selected(), 0)  # high
        row.set_selected(1)
        self.assertEqual(settings.get_string('streaming-quality'), 'standard')
        settings.set_string('streaming-quality', 'high')
        self.assertEqual(row.get_selected(), 0)

    async def test_the_bitrate_is_said_while_the_engine_runs(self):
        row = self.dialog.quality_row
        self.assertEqual(row.get_subtitle(), 'High Efficiency uses less data')
        self.engine.bitrate = 64
        self.assertEqual(row.get_subtitle(), 'High Efficiency uses less data')  # down
        self.engine.state = 'up'
        self.assertEqual(row.get_subtitle(), 'Streaming at 64 kbps now')
        self.engine.state = 'down'
        self.assertEqual(row.get_subtitle(), 'High Efficiency uses less data')

    async def test_the_bitrate_is_read_again_as_it_opens_with_the_engine_up(self):
        from applemusic.dialogs.preferences import PreferencesDialog

        self.closed()
        self.engine.state = 'up'
        self.dialog = PreferencesDialog(self.app)
        await self.app.settle()
        self.assertEqual(self.engine.calls, ['status'])
        self.assertEqual(self.dialog.quality_row.get_subtitle(), 'Streaming at 256 kbps now')

    # -- the library -----------------------------------------------------------------------

    async def test_the_interval_row_and_its_setting_follow_each_other(self):
        from applemusic.sync import INTERVALS

        row, settings = self.dialog.interval_row, self.app.settings
        self.assertEqual(INTERVALS[row.get_selected()], settings.get_int('sync-interval'))
        row.set_selected(INTERVALS.index(0))
        self.assertEqual(settings.get_int('sync-interval'), 0)  # manual
        settings.set_int('sync-interval', 24)
        self.assertEqual(row.get_selected(), INTERVALS.index(24))
        settings.set_int('sync-interval', 30)  # not a choice: shown as the nearest, kept
        self.assertEqual(row.get_selected(), INTERVALS.index(24))
        self.assertEqual(settings.get_int('sync-interval'), 30)

    async def test_last_refreshed_and_refreshing(self):
        row, sync = self.dialog.last_refreshed_row, self.app.library_sync
        self.assertEqual(row.get_subtitle(), 'Never')
        sync.running = True
        self.assertEqual(row.get_subtitle(), 'Refreshing…')
        self.app.settings.set_string('last-sync', '2020-01-01T00:00:00+00:00')
        self.assertEqual(row.get_subtitle(), 'Refreshing…')
        with open(os.path.join(self.cache, 'library.json'), 'w', encoding='utf-8') as file:
            file.write('{}')  # what the sync wrote
        sync.running = False
        self.assertRegex(row.get_subtitle(), r'^\d[\d,]* days ago$')  # the locale's grouping
        await self.app.settle()  # measured again once a sync has ended
        self.assertEqual(self.dialog.cache_row.get_subtitle(), '2 bytes')

    async def test_the_cache_is_measured(self):
        self.assertEqual(self.dialog.cache_row.get_subtitle(), 'Empty')

    async def test_clear_asks_and_measures_again(self):
        dialog = self.dialog
        dialog._on_clear_response(None, 'cancel')
        await self.app.settle()
        self.assertEqual(self.app.toasts, [])
        dialog._on_clear_response(None, 'clear')
        await asyncio.sleep(0)
        self.assertTrue(dialog._clearing)
        self.assertEqual(dialog.cache_row.get_subtitle(), 'Clearing…')
        dialog.clear_button.emit('clicked')  # under way: no second question
        await self.app.settle()
        self.assertFalse(dialog._clearing)
        self.assertEqual(self.app.toasts, ['Cache cleared'])
        self.assertEqual(dialog.cache_row.get_subtitle(), 'Empty')

    async def test_a_clear_that_fails_says_nothing_cleared(self):
        self.app.cleared = [False, OSError('invented')]
        await self.dialog.clear()
        with self.assertLogs('applemusic.dialogs.preferences', 'WARNING'):
            await self.dialog.clear()
        self.assertEqual(self.app.toasts, [])
        self.assertFalse(self.dialog._clearing)

    # -- the browser program ---------------------------------------------------------------

    async def test_a_program_found_is_kept_stripped(self):
        row, settings = self.dialog.browser_row, self.app.settings
        row.add_css_class('error')
        await self.dialog._apply_browser('invented-browser')
        self.assertEqual(self.engine.calls, [('browser_path', 'invented-browser')])
        self.assertEqual(settings.get_string('browser-command'), 'invented-browser')
        self.assertEqual(row.get_text(), 'invented-browser')
        self.assertFalse(row.has_css_class('error'))

    async def test_a_program_not_found_is_not_kept(self):
        row, settings = self.dialog.browser_row, self.app.settings
        self.engine.found = None
        await self.dialog._apply_browser('missing-browser')
        self.assertEqual(settings.get_string('browser-command'), 'google-chrome-stable')
        self.assertTrue(row.has_css_class('error'))
        self.assertEqual(self.app.toasts, ['No program called “missing-browser” was found'])
        row.emit('changed')  # typing again takes the mark away
        self.assertFalse(row.has_css_class('error'))

    async def test_empty_is_the_default_again(self):
        settings = self.app.settings
        settings.set_string('browser-command', 'invented-browser')
        await self.dialog._apply_browser('')
        self.assertEqual(settings.get_string('browser-command'), 'google-chrome-stable')
        self.assertEqual(self.engine.calls, [])

    # -- the account -----------------------------------------------------------------------

    def test_the_account_rows(self):
        dialog, settings = self.dialog, self.app.settings

        def shown():
            return (dialog.account_group.get_description(), dialog.sign_in_row.get_visible(),
                    dialog.sign_out_row.get_visible())

        self.assertEqual(shown(), ('Not signed in', True, False))
        settings.set_boolean('signed-in', True)
        self.assertEqual(shown(), ('Signed in', False, True))
        settings.set_string('account-name', 'Invented Listener')
        self.assertEqual(shown(), ('Signed in as Invented Listener', False, True))
        self.assertTrue(dialog.sign_out_row.get_sensitive())
        self.app.signing_out = True
        self.assertFalse(dialog.sign_out_row.get_sensitive())

    def test_sign_in_closes_the_dialog_sign_out_asks_over_it(self):
        closes = []
        self.dialog.close = lambda: closes.append(True)  # never presented here
        self.dialog.sign_out_row.emit('activated')
        self.assertEqual((self.app.actions, closes), (['sign-out'], []))
        self.dialog.sign_in_row.emit('activated')
        self.assertEqual((self.app.actions, closes), (['sign-out', 'sign-in'], [True]))

    # -- closing ---------------------------------------------------------------------------

    def test_closed_it_follows_nothing(self):
        dialog = self.dialog
        self.closed()
        self.assertTrue(dialog._closed)
        subtitle = dialog.engine_row.get_subtitle()
        self.engine.state = 'up'
        self.app.settings.set_boolean('signed-in', True)
        self.app.settings.set_boolean('background-playback', True)
        self.assertEqual(dialog.engine_row.get_subtitle(), subtitle)
        self.assertEqual(dialog.engine_button.get_label(), '_Start')
        self.assertTrue(dialog.sign_in_row.get_visible())
        self.assertFalse(dialog.background_row.get_active())


if __name__ == '__main__':
    unittest.main()
