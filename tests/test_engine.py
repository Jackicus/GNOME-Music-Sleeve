# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Unit tests for src/engine/core.py: the Engine's lifecycle, its connection, the reads the
commands rest on (an API read, a full Item), and signing in, against a fake Chrome
(tests/engine_fixture.py)."""

import asyncio
import json
import os
import pathlib
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)

from gi.repository import Gio, GLib

from applemusic.backend import art_cache, cache_files, chrome
from applemusic.backend import client as client_module
from applemusic.backend.errors import EngineError
from applemusic.engine import Engine
from applemusic.engine import catalog as catalog_module
from applemusic.engine import core as core_module
from applemusic.engine import reads as reads_module
from tests.engine_fixture import FIXTURES, EngineFixture, exited
from tests.test_client import context_created, thrown, until, value


class LifecycleTest(EngineFixture):
    """Starting and stopping Chrome, the connection, and the reads the rest rests on (api,
    status, item, sign-in, the account name)."""

    # -- starting and stopping ------------------------------------------------------------

    async def test_start_spawns_chrome_on_the_pipe_and_brings_the_bridge_up(self):
        self.assertEqual(self.engine.state, 'down')
        await self.engine.start()
        self.assertEqual(self.states, ['starting', 'up'])
        self.assertEqual(len(self.engine.spawned), 1)
        argv = self.chrome.argv
        self.assertIn('--remote-debugging-pipe', argv)
        self.assertFalse([arg for arg in argv if arg.startswith('--remote-debugging-port')])
        self.assertFalse([arg for arg in argv if arg.startswith('--remote-debugging-address')])
        self.assertIn('--headless=new', argv)
        self.assertIn(f'--user-data-dir={self.profile}', argv)
        self.assertTrue(self.profile.is_dir())
        self.assertEqual(self.browser_commands, [None])
        self.assertEqual(self.chrome.methods(session=False)[:3], [
            'Target.setDiscoverTargets', 'Target.getTargets', 'Target.attachToTarget'])
        self.assertEqual((self.page.injections, self.page.subscriptions), (1, 1))
        self.assertTrue(self.engine.headless)
        self.assertFalse(self.engine.authorized)
        self.assertEqual(self.engine.pid, self.chrome.chromes[-1]['pid'])
        self.assertFalse((self.profile / 'engine.json').exists())

    @unittest.skipUnless(shutil.which('setpriv'), 'needs setpriv (util-linux)')
    async def test_chrome_is_spawned_through_setpriv(self):
        await self.engine.start()
        argv = self.engine.spawned[0][1]
        self.assertEqual(argv[1:4], ['--pdeathsig', 'TERM', '--'])
        self.assertTrue(argv[0].endswith('setpriv'))
        self.assertEqual(argv[4], str(self.binary))

    async def test_chrome_gets_the_host_session_bus_when_one_is_set(self):
        # A fresh profile (no Local State): no keyring check, so the bus need not exist.
        os.environ['APPLE_MUSIC_HOST_SESSION_BUS'] = 'unix:path=/nonexistent/host-bus'
        await self.engine.start()
        self.assertEqual(self.chrome.chromes[-1]['bus'], 'unix:path=/nonexistent/host-bus')

    async def test_chrome_inherits_the_session_bus_otherwise(self):
        await self.engine.start()
        self.assertEqual(self.chrome.chromes[-1]['bus'],
                         os.environ.get('DBUS_SESSION_BUS_ADDRESS'))

    async def test_the_exec_line_leaves_the_profile_s_path_out(self):
        with self.assertLogs('applemusic.engine', 'DEBUG') as logs:
            await self.engine.start()
        exec_lines = [line for line in logs.output if ':exec ' in line]
        self.assertEqual(len(exec_lines), 1)
        self.assertIn('--user-data-dir=<profile>', exec_lines[0])
        self.assertIn('--remote-debugging-pipe', exec_lines[0])
        self.assertNotIn(str(self.profile), '\n'.join(logs.output))

    async def test_the_debug_port_is_opt_in_and_warned_about(self):
        os.environ['APPLE_MUSIC_DEBUG_PORT'] = '9300'
        with self.assertLogs('applemusic.engine', 'WARNING') as logs:
            await self.engine.start()
        argv = self.chrome.argv
        self.assertIn('--remote-debugging-pipe', argv)
        self.assertIn('--remote-debugging-port=9300', argv)
        self.assertIn('--remote-debugging-address=127.0.0.1', argv)
        self.assertTrue(any('APPLE_MUSIC_DEBUG_PORT is set' in line and '127.0.0.1:9300' in line
                            and 'any local program' in line for line in logs.output))

    async def test_start_reads_authorized(self):
        self.page.authorized = True
        await self.engine.start()
        self.assertTrue(self.engine.authorized)

    async def test_start_again_in_the_same_mode_does_nothing(self):
        await self.engine.start()
        await self.engine.start()
        self.assertEqual(len(self.engine.spawned), 1)
        self.assertEqual(self.states, ['starting', 'up'])

    async def test_start_visible_restarts_a_headless_chrome(self):
        await self.engine.start()
        first, _ = self.engine.spawned[0]
        await self.engine.start(visible=True)
        self.assertEqual(len(self.engine.spawned), 2)
        self.assertTrue(exited(first))
        self.assertIn('--app=https://music.apple.com/', self.chrome.argv)
        self.assertNotIn('--headless=new', self.chrome.argv)
        self.assertFalse(self.engine.headless)
        self.assertEqual(self.engine.state, 'up')
        self.assertEqual(self.states, ['starting', 'up', 'down', 'starting', 'up'])

    async def test_stop_ends_chrome_and_forgets_it(self):
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        pid = self.engine.pid
        await self.engine.stop()
        self.assertEqual(self.engine.state, 'down')
        self.assertTrue(exited(process))
        self.assertIsNone(self.engine.pid)
        # Asked to close over the pipe, it did: no signal was needed.
        self.assertIn('Browser.close', self.chrome.methods(session=False))
        self.assertNotIn(('term', pid), self.chrome_log())
        with self.assertRaises(EngineError) as ctx:
            await self.engine.status()
        self.assertEqual(ctx.exception.code, 'engine-down')
        await self.engine.stop()  # twice is fine

    async def test_stop_kills_a_chrome_that_ignores_sigterm(self):
        self.chrome_mode('stubborn')
        self.engine.close_wait = 0.05
        self.engine.stop_grace = 0.2
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        pid = self.engine.pid
        started = time.monotonic()
        with self.assertLogs('applemusic.engine', 'WARNING'):  # ignored SIGTERM; killed
            await self.engine.stop()
        self.assertIn(('term', pid), self.chrome_log())
        self.assertTrue(exited(process))
        self.assertTrue(process.get_if_signaled())
        self.assertEqual(process.get_term_sig(), signal.SIGKILL)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertEqual(self.engine.state, 'down')

    async def test_a_stubborn_chrome_outlives_an_answer_into_a_closed_pipe(self):
        # Browser.close answered after the engine stopped waiting and closed its end of the
        # pipe (a loaded machine answers late on its own): the answer meets a broken pipe,
        # and a Chrome that ignores SIGTERM still lives until SIGKILL.
        self.chrome_mode('stubborn')
        self.engine.close_wait = 0.05
        self.engine.stop_grace = 0.3
        answered = asyncio.Event()

        async def close_late(message):
            await asyncio.sleep(0.15)
            await self.chrome.send({'id': message['id'], 'result': {}})
            answered.set()
        self.chrome.browser_responders['Browser.close'] = close_late
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        pid = self.engine.pid
        with self.assertLogs('applemusic.engine', 'WARNING'):  # ignored SIGTERM; killed
            await self.engine.stop()
        self.assertTrue(answered.is_set())
        self.assertIn(('term', pid), self.chrome_log())
        self.assertEqual(process.get_term_sig(), signal.SIGKILL)

    async def test_a_stop_with_a_shorter_grace(self):
        self.chrome_mode('stubborn')
        self.chrome.close_on_browser_close = False
        self.engine.close_wait = 0.05
        self.engine.stop_grace = 5
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        started = time.monotonic()
        with self.assertLogs('applemusic.engine', 'WARNING'):
            await self.engine.stop(grace=0.1)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(process.get_term_sig(), signal.SIGKILL)

    async def test_kill_after_a_cancelled_stop_still_kills_chrome(self):
        self.chrome_mode('stubborn')
        self.chrome.close_on_browser_close = False
        self.engine.close_wait = 0.05
        self.engine.stop_grace = 1
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        pid = self.engine.pid
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.engine.stop(), 0.25)  # cancelled inside SIGTERM's grace
        self.assertEqual(self.engine.pid, pid)  # not forgotten
        with self.assertLogs('applemusic.engine', 'WARNING'):
            self.engine.kill()
        await self.wait_exited(process, timeout=1)
        self.assertIn(('term', pid), self.chrome_log())
        self.assertEqual(process.get_term_sig(), signal.SIGKILL)
        self.assertEqual(self.engine.state, 'down')
        self.assertIsNone(self.engine.pid)

    def hold_the_start(self):
        """The fake Chrome's page attach waits for the Event returned: the start stays in
        progress until it is set."""
        gate = asyncio.Event()
        attach = self.chrome.browser_Target_attachToTarget

        async def held(message):
            await gate.wait()
            return attach(message)
        self.chrome.browser_responders['Target.attachToTarget'] = held
        return gate

    async def test_a_command_waits_for_a_start_in_progress(self):
        self.page.authorized = True
        gate = self.hold_the_start()
        starting = asyncio.create_task(self.engine.start())
        await until(lambda: self.engine.state == 'starting')
        play = asyncio.create_task(self.engine.play('album', 'l.1'))
        status = asyncio.create_task(self.engine.status())
        await asyncio.sleep(0.05)
        self.assertFalse(play.done())  # waiting, not failing with engine-down
        gate.set()
        await starting
        await play
        self.assertEqual((await status)['ready'], True)
        self.assertEqual(self.page.bridge_calls[-1][:3], ('play', 'album', 'l.1'))

    async def test_concurrent_starts_share_one_chrome(self):
        gate = self.hold_the_start()
        starts = [asyncio.create_task(self.engine.start()) for _ in range(3)]
        await until(lambda: self.engine.state == 'starting')
        gate.set()
        await asyncio.gather(*starts)
        self.assertEqual(len(self.engine.spawned), 1)
        self.assertEqual(self.states, ['starting', 'up'])

    async def test_a_failing_start_fails_every_waiter_with_its_code(self):
        self.page.ready = False
        with mock.patch.object(core_module, 'BRIDGE_WAIT', 0.15):
            results = await asyncio.gather(
                self.engine.start(), self.engine.start(), self.engine.control('pause'),
                return_exceptions=True)
        self.assertEqual([getattr(r, 'code', r) for r in results], ['timeout'] * 3)
        self.assertEqual(len(self.engine.spawned), 1)
        self.assertEqual(self.engine.state, 'down')

    async def test_a_cancelled_start_fails_its_waiters_and_a_cancelled_waiter_not_the_start(self):
        gate = self.hold_the_start()
        starting = asyncio.create_task(self.engine.start())
        await until(lambda: self.engine.state == 'starting')
        waiter = asyncio.create_task(self.engine.start())
        command = asyncio.create_task(self.engine.status())
        await asyncio.sleep(0.02)
        waiter.cancel()  # the start goes on
        await asyncio.sleep(0.02)
        self.assertEqual(self.engine.state, 'starting')
        starting.cancel()  # the start itself: stopped, and the command told so
        with self.assertRaises(asyncio.CancelledError):
            await starting
        with self.assertRaises(EngineError) as ctx:
            await command
        self.assertEqual(ctx.exception.code, 'engine-down')
        self.assertEqual(self.engine.state, 'down')
        gate.set()

    async def test_kill_ends_chrome_at_once_and_is_no_loss(self):
        lost = []
        self.engine.connect('lost', lambda e, reason: lost.append(reason))
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        with self.assertLogs('applemusic.engine', 'WARNING'):
            self.engine.kill()
        self.assertEqual((self.engine.state, self.engine.pid), ('down', None))
        await self.wait_exited(process)
        self.assertEqual(process.get_term_sig(), signal.SIGKILL)
        await asyncio.sleep(0.05)  # the pipe's end reaches the client
        self.assertEqual(lost, [])
        self.assertEqual(self.engine.state, 'down')

    async def test_restart(self):
        await self.engine.start()
        await self.engine.restart(visible=False)
        self.assertEqual(len(self.engine.spawned), 2)
        self.assertTrue(exited(self.engine.spawned[0][0]))
        self.assertEqual(self.engine.state, 'up')

    async def test_start_without_a_mode_keeps_a_running_engine(self):
        await self.engine.start(visible=True)
        await self.engine.start()  # a play request, a sync: whatever mode it runs in
        self.assertEqual(len(self.engine.spawned), 1)
        self.assertFalse(self.engine.headless)
        self.assertEqual(self.states, ['starting', 'up'])

    async def test_start_without_a_mode_follows_prefer_headless(self):
        self.engine.prefer_headless = False  # engine-headless off: a window, for debugging
        await self.engine.start()
        self.assertNotIn('--headless=new', self.chrome.argv)
        self.assertFalse(self.engine.headless)
        self.engine.prefer_headless = True
        await self.engine.restart()
        self.assertIn('--headless=new', self.chrome.argv)
        self.assertTrue(self.engine.headless)

    async def test_a_failed_start_cleans_up(self):
        self.page.ready = False
        with mock.patch.object(core_module, 'BRIDGE_WAIT', 0.15):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.start()
        self.assertEqual(ctx.exception.code, 'timeout')
        self.assertIn('MusicKit not loaded', ctx.exception.message)
        self.assertEqual(self.engine.state, 'down')
        await self.wait_exited(self.engine.spawned[0][0])

    async def test_no_chrome_is_no_browser(self):
        with mock.patch.object(chrome, 'find_chrome', lambda command: None):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.start()
        self.assertEqual(ctx.exception.code, 'no-browser')
        self.assertIn('not found', ctx.exception.message)
        self.assertEqual(self.engine.state, 'down')
        self.assertEqual(self.engine.spawned, [])

    async def test_a_browser_that_cannot_be_started_is_no_browser(self):
        missing = str(self.profile.parent / 'no-such-chrome')
        with mock.patch.object(chrome, 'find_chrome', lambda command: missing), \
                mock.patch.object(core_module, 'with_pdeathsig', list):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.start()
        self.assertEqual(ctx.exception.code, 'no-browser')
        self.assertIn('could not start', ctx.exception.message)
        self.assertEqual(self.engine.state, 'down')

    async def test_a_chrome_that_exits_at_once_is_reported_at_once(self):
        self.chrome_mode('exit:3')
        started = time.monotonic()
        with self.assertRaises(EngineError) as ctx:
            await self.engine.start()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(ctx.exception.code, 'engine-down')
        self.assertIn('Chrome exited at once (status 3)', ctx.exception.message)
        self.assertEqual(self.engine.state, 'down')

    async def test_a_profile_that_cannot_be_made_is_engine_down(self):
        blocker = self.profile.parent / 'a-file'
        blocker.write_text('not a directory')
        self.engine.profile_dir = blocker / 'chrome'
        with self.assertRaises(EngineError) as ctx:
            await self.engine.start()
        self.assertEqual(ctx.exception.code, 'engine-down')
        self.assertIn('could not prepare', ctx.exception.message)
        self.assertEqual(self.engine.state, 'down')
        self.assertEqual(self.engine.spawned, [])

    async def test_anything_unexpected_becomes_engine_down(self):
        def broken(*args, **kwargs):
            raise RuntimeError('a bug in the argv')
        with mock.patch.object(chrome, 'chrome_args', broken):
            with self.assertLogs('applemusic.engine', 'ERROR'):
                with self.assertRaises(EngineError) as ctx:
                    await self.engine.start()
        self.assertEqual((ctx.exception.code, ctx.exception.message),
                         ('engine-down', 'a bug in the argv'))
        self.assertEqual(self.engine.state, 'down')

    async def test_browser_command_is_tried_first(self):
        self.engine.browser_command = 'my-chrome'
        await self.engine.start()
        self.assertEqual(self.browser_commands, ['my-chrome'])

    # -- a Chrome already on the profile ----------------------------------------------------

    def leftover(self, lock=True):
        """A Chrome another process left on the profile (the debug CLI's, or one an app crash
        left): a live process with the profile on its command line, which the profile's
        SingletonLock names."""
        self.profile.mkdir(parents=True, exist_ok=True)
        flag = f'--user-data-dir={self.profile}'
        process = subprocess.Popen(
            [sys.executable, '-S', '-c', 'import time; time.sleep(30)', flag])
        self.addCleanup(lambda: (process.kill(), process.wait()))
        deadline = time.monotonic() + 2
        while not chrome.pid_alive(process.pid, self.profile) and time.monotonic() < deadline:
            time.sleep(0.005)  # its cmdline is the runner's for an instant while it execs
        if lock:
            os.symlink(f'{socket.gethostname()}-{process.pid}', self.profile / 'SingletonLock')
        return process

    async def test_a_chrome_holding_the_profile_is_stopped_first(self):
        leftover = self.leftover()
        await self.engine.start()
        self.assertIsNotNone(leftover.poll())
        self.assertEqual(leftover.returncode, -signal.SIGTERM)
        self.assertEqual(len(self.engine.spawned), 1)
        self.assertEqual(self.engine.state, 'up')

    async def test_stop_ends_the_chrome_on_the_profile_even_when_it_never_started(self):
        leftover = self.leftover()
        await self.engine.stop()
        self.assertIsNotNone(leftover.poll())
        self.assertEqual(self.engine.spawned, [])

    async def test_a_lock_naming_no_chrome_on_the_profile_is_left_alone(self):
        leftover = self.leftover(lock=False)
        os.symlink(f'{socket.gethostname()}-{os.getpid()}', self.profile / 'SingletonLock')
        await self.engine.start()
        await self.engine.stop()
        self.assertIsNone(leftover.poll())

    # -- the connection --------------------------------------------------------------------

    async def test_losing_the_connection_takes_the_engine_down(self):
        lost = []
        self.engine.connect('lost', lambda e, reason: lost.append((reason, e.state)))
        await self.engine.start()
        await self.engine.restart()
        await self.engine.stop()
        await self.engine.start()
        self.assertEqual(lost, [])  # asked for: not lost
        process, _ = self.engine.spawned[-1]
        with self.assertLogs('applemusic.engine', 'WARNING'):
            await self.chrome.drop()
            await until(lambda: self.engine.state == 'down', timeout=3)
        await self.wait_exited(process)
        self.assertFalse(self.engine.authorized)
        self.assertEqual(lost, [('closed by Chrome', 'up')])  # once, before the stop

    async def test_a_crashed_page_takes_the_engine_down(self):
        await self.engine.start()
        with self.assertLogs('applemusic.engine', 'WARNING'):
            await self.chrome.send_event('Inspector.targetCrashed', {})
            await until(lambda: self.engine.state == 'down', timeout=3)
        await self.wait_exited(self.engine.spawned[0][0])

    async def test_the_bridge_comes_back_after_a_slow_navigation(self):
        self.page.authorized = True
        await self.engine.start()
        self.assertTrue(self.engine.authorized)
        self.engine._client.reinject_timeout = 0.1
        seen = []
        self.engine.connect('event', lambda e, name, data: seen.append(name))
        subscriptions = self.page.subscriptions
        self.page.bridge = None        # a new document
        self.page.ready = False        # with MusicKit still loading
        self.page.authorized = False   # and the account signed out meanwhile
        with self.assertLogs(client_module.log, 'WARNING'):
            await self.chrome.send_event(*context_created(9))
            await asyncio.sleep(0.15)  # a try gives up
            self.page.ready = True     # MusicKit arrives
            await until(lambda: 'bridgeReset' in seen, timeout=3)
        self.assertEqual(self.page.subscriptions, subscriptions + 1)  # events flow again
        await until(lambda: not self.engine.authorized)  # the status read again
        self.assertEqual(self.engine.state, 'up')

    async def test_a_page_that_never_comes_back_takes_the_engine_down(self):
        await self.engine.start()
        self.engine._client.reinject_timeout = 0.05
        self.page.bridge = None
        self.page.ready = False
        with self.assertLogs(level='WARNING'):  # the client's tries, then the engine's end
            await self.chrome.send_event(*context_created(9))
            await until(lambda: self.engine.state == 'down', timeout=3)
        await self.wait_exited(self.engine.spawned[0][0])

    async def wedge(self, hangs):
        """The page stops answering the evaluates `hangs(expression)` picks."""
        page = self.page

        def evaluate(message):
            return None if hangs(message['params']['expression']) else page(message)
        self.chrome.responders['Runtime.evaluate'] = evaluate
        self.engine._client.timeout = 0.1
        self.engine.probe_timeout = 0.1

    async def test_a_wedged_page_takes_the_engine_down(self):
        lost = []
        self.engine.connect('lost', lambda e, reason: lost.append(reason))
        await self.engine.start()
        process, _ = self.engine.spawned[0]
        await self.wedge(lambda expression: True)
        with self.assertLogs('applemusic.engine', 'WARNING'):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.control('pause')
            self.assertEqual(ctx.exception.code, 'timeout')
            await until(lambda: self.engine.state == 'down', timeout=3)
        await self.wait_exited(process)
        self.assertEqual(lost, ['the page stopped answering'])

    async def test_a_slow_api_read_leaves_a_page_that_answers_up(self):
        await self.engine.start()
        await self.wedge(lambda js: js.startswith('window.__appleMusicLibrary.api('))
        with mock.patch.object(reads_module, 'API_RETRIES', 1):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.api('/v1/me/library/songs')
        self.assertEqual(ctx.exception.code, 'timeout')
        await until(lambda: self.engine._probe is not None and self.engine._probe.done())
        self.assertEqual(self.engine.state, 'up')
        self.assertEqual((await self.engine.status())['ready'], True)

    async def test_bridge_events_are_re_emitted(self):
        await self.engine.start()
        seen = []
        self.engine.connect('event', lambda e, name, data: seen.append((name, data)))
        await self.chrome.send_binding('playbackStateDidChange', {'state': 'playing'})
        await self.chrome.send_binding('authorizationStatusDidChange',
                                       {'authorized': True, 'status': 1})
        await until(lambda: len(seen) == 2)
        self.assertEqual(seen, [
            ('playbackStateDidChange', {'state': 'playing'}),
            ('authorizationStatusDidChange', {'authorized': True, 'status': 1})])
        self.assertTrue(self.engine.authorized)

    # -- commands --------------------------------------------------------------------------

    async def test_api_is_the_bridge_read(self):
        await self.engine.start()
        self.page.api_answers['/v1/me/library/albums'] = {'data': [{'id': 'l.1'}]}
        self.assertEqual(await self.engine.api('/v1/me/library/albums', {'limit': 5}),
                         {'data': [{'id': 'l.1'}]})
        self.assertEqual(self.page.api_params[-1], {'limit': 5})
        with self.assertRaises(EngineError) as ctx:
            await self.engine.api('/v1/nothing')
        self.assertEqual(ctx.exception.code, 'api')

    async def test_a_4xx_is_final_and_a_5xx_is_tried_again(self):
        await self.engine.start()
        self.page.api_answers['/v1/gone?include=tracks'] = {
            'errors': [{'status': '404', 'title': 'Not Found'}]}
        with self.assertRaises(EngineError) as ctx:
            await self.engine.api('/v1/gone?include=tracks')
        self.assertEqual((ctx.exception.code, ctx.exception.status), ('api', 404))
        self.assertEqual(ctx.exception.message, '/v1/gone: 404 Not Found:')  # no query
        self.assertEqual(self.page.api_calls, ['/v1/gone?include=tracks'])
        for status in ('503', '429', None):
            self.page.api_calls.clear()
            self.page.api_answers['/v1/busy'] = {'errors': [{'status': status, 'title': 'Busy'}]}
            with self.assertRaises(EngineError) as ctx:
                await self.engine.api('/v1/busy')
            self.assertEqual(self.page.api_calls, ['/v1/busy'] * reads_module.API_RETRIES)
        self.assertIsNone(ctx.exception.status)
        # A retried read that passes answers.
        self.page.api_calls.clear()
        answers = iter([{'errors': [{'status': '503'}]}, {'data': [{'id': 'x'}]}])

        def flaky(message):
            expression = message['params']['expression']
            if expression.startswith('window.__appleMusicLibrary.api("/v1/flaky"'):
                self.page.api_calls.append('/v1/flaky')
                return value(next(answers))
            return page(message)

        page = self.page
        self.chrome.responders['Runtime.evaluate'] = flaky
        self.assertEqual(await self.engine.api('/v1/flaky'), {'data': [{'id': 'x'}]})
        self.assertEqual(self.page.api_calls, ['/v1/flaky', '/v1/flaky'])

    async def test_a_read_that_times_out_is_not_tried_again(self):
        await self.engine.start()
        calls = []
        page = self.page

        def hang(message):
            if message['params']['expression'].startswith('window.__appleMusicLibrary.api('):
                calls.append(message)
                return None  # never answers
            return page(message)

        self.chrome.responders['Runtime.evaluate'] = hang
        with self.assertRaises(EngineError) as ctx:
            await self.engine.api('/v1/me/library/songs', timeout=0.2)
        self.assertEqual(ctx.exception.code, 'timeout')
        self.assertEqual(len(calls), 1)

    async def test_api_pages_with_a_total_fetches_the_rest_at_once(self):
        await self.engine.start()
        path = '/v1/me/library/songs'
        pages = {0: ['a', 'b'], 2: ['c', 'd'], 4: ['e', 'f'], 6: ['g']}
        for offset, ids in pages.items():
            self.page.api_answers[(path, offset)] = {
                'data': [{'id': i} for i in ids], 'meta': {'total': 7},
                'next': f'{path}?offset={offset + 2}' if offset < 6 else None}
        seen = []
        items = await self.engine.api_pages(path, {'include': 'albums'}, page=2,
                                            progress=lambda d, t: seen.append((d, t)))
        self.assertEqual([item['id'] for item in items], list('abcdefg'))
        self.assertEqual(self.page.api_calls.count(path), 4)
        self.assertEqual([p['offset'] for p in self.page.api_params if p.get('include')],
                         [0, 2, 4, 6])
        self.assertEqual(seen[0], (2, 7))
        self.assertEqual(seen[-1], (7, 7))

    async def test_api_pages_can_keep_each_item_once(self):
        await self.engine.start()
        path = '/v1/me/library/songs'
        # A song added while the listing is read shifts the offsets: 'b' comes back on the
        # second page.
        self.page.api_answers[(path, 0)] = {'data': [{'id': 'a'}, {'id': 'b'}],
                                            'meta': {'total': 5}, 'next': f'{path}?offset=2'}
        self.page.api_answers[(path, 2)] = {'data': [{'id': 'b'}, {'id': 'c'}],
                                            'meta': {'total': 5}, 'next': f'{path}?offset=4'}
        self.page.api_answers[(path, 4)] = {'data': [{'id': 'd'}], 'meta': {'total': 5}}
        items = await self.engine.api_pages(path, page=2)
        self.assertEqual([item['id'] for item in items], ['a', 'b', 'b', 'c', 'd'])
        with self.assertLogs('applemusic.engine', 'DEBUG') as logs:
            items = await self.engine.api_pages(path, page=2, unique=True)
        self.assertEqual([item['id'] for item in items], ['a', 'b', 'c', 'd'])
        self.assertIn('5 items, 4 of them once', logs.output[-1])

    async def test_api_pages_without_a_total_follows_next(self):
        await self.engine.start()
        path = '/v1/me/library/recently-added'
        self.page.api_answers[(path, 0)] = {'data': [{'id': 'x'}, {'id': 'y'}],
                                            'next': f'{path}?offset=2'}
        self.page.api_answers[(path, 2)] = {'data': [{'id': 'z'}]}
        seen = []
        items = await self.engine.api_pages(path, page=2,
                                            progress=lambda d, t: seen.append((d, t)))
        self.assertEqual([item['id'] for item in items], ['x', 'y', 'z'])
        self.assertEqual(seen, [(2, None), (3, None)])
        # A limit stops the paging and trims the answer.
        self.page.api_calls.clear()
        items = await self.engine.api_pages(path, page=2, limit=1)
        self.assertEqual([item['id'] for item in items], ['x'])
        self.assertEqual(self.page.api_calls, [path])

    async def test_api_all(self):
        await self.engine.start()
        self.page.api_answers['/v1/a'] = {'data': [1]}
        self.assertEqual(await self.engine.api_all(['/v1/a', '/v1/b']), [{'data': [1]}, None])

    async def test_status(self):
        with self.assertRaises(EngineError) as ctx:
            await self.engine.status()
        self.assertEqual(ctx.exception.code, 'engine-down')
        await self.engine.start()
        self.assertEqual(await self.engine.status(), self.page.status())
        self.page.authorized = True
        self.assertTrue((await self.engine.status())['authorized'])
        self.assertTrue(self.engine.authorized)  # status keeps the property current

    async def test_item_needs_sign_in(self):
        with self.assertRaises(EngineError) as ctx:
            await self.engine.item('album', '1724040700')
        self.assertEqual(ctx.exception.code, 'engine-down')
        await self.engine.start()
        with self.assertRaises(EngineError) as ctx:
            await self.engine.item('album', '1724040700')
        self.assertEqual(ctx.exception.code, 'not-signed-in')

    async def test_item_fetches_shapes_and_keeps_an_album(self):
        self.page.authorized = True
        with open(FIXTURES / 'catalog_album.json') as f:
            self.page.api_answers['/v1/catalog/us/albums/1724040700?include=tracks,artists'] = (
                json.load(f))
        await self.engine.start()
        fetched = []
        with mock.patch.object(art_cache, 'download_item_art',
                               lambda item, cache_dir, art_urls, generation:
                               fetched.append(cache_dir) or item):
            item = await self.engine.item('album', '1724040700')
        self.assertEqual(self.page.api_calls,
                         ['/v1/catalog/us/albums/1724040700?include=tracks,artists'])
        self.assertEqual((item['kind'], item['id'], item['title']),
                         ('album', '1724040700', 'Static Skyline (Deluxe Edition)'))
        self.assertEqual(len(item['groups']), 2)  # the fixture's two discs
        self.assertEqual([entry['title'] for entry in item['groups'][0]['entries']][:1],
                         ['Overpass'])
        self.assertEqual(fetched, [str(self.cache)])
        self.assertFalse((self.cache / 'items').exists())  # nothing reads an item back
        # Its artwork goes where the library's pruning cannot take it from an open page.
        self.assertEqual(os.path.dirname(item['art']), str(self.cache / 'remote-art'))
        self.assertEqual(os.path.dirname(item['thumb']), str(self.cache / 'remote-art'))

    async def test_item_library_ids_go_to_the_library_and_a_miss_is_api(self):
        self.page.authorized = True
        await self.engine.start()
        with mock.patch.object(reads_module, 'API_RETRIES', 1):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.item('playlist', 'p.abc')
        self.assertEqual(ctx.exception.code, 'api')
        self.assertEqual(self.page.api_calls, ['/v1/me/library/playlists/p.abc?include=tracks'])

    async def test_item_artist_fetches_its_albums_at_once(self):
        self.page.authorized = True
        with open(FIXTURES / 'catalog_album.json') as f:
            album = json.load(f)
        self.page.api_answers['/v1/catalog/us/artists/42?include=albums'] = {'data': [{
            'id': '42', 'type': 'artists', 'attributes': {'name': 'Paper Parachutes'},
            'relationships': {'albums': {'data': [
                {'id': '1724040700', 'type': 'albums'},
                {'id': 'l.missing', 'type': 'library-albums',
                 'attributes': {'name': 'Unreachable'}}]}}}]}
        self.page.api_answers['/v1/catalog/us/albums/1724040700?include=tracks'] = album
        await self.engine.start()
        with mock.patch.object(art_cache, 'download_item_art',
                               lambda item, cache_dir, art_urls, generation: item):
            item = await self.engine.item('artist', '42')
        self.assertEqual(self.page.api_calls, [
            '/v1/catalog/us/artists/42?include=albums',
            '/v1/catalog/us/albums/1724040700?include=tracks',
            '/v1/me/library/albums/l.missing?include=tracks'])
        self.assertEqual((item['kind'], item['title']), ('artist', 'Paper Parachutes'))
        names = [group['name'] for group in item['groups']]
        self.assertIn('Static Skyline (Deluxe Edition)', names)

    async def test_item_follows_an_artists_albums_past_the_first_page(self):
        self.page.authorized = True
        base = '/v1/catalog/us/artists/42'

        def stubs(*numbers):
            return [{'id': f'10000000{n}', 'type': 'albums',
                     'attributes': {'name': f'Album {n}', 'artistName': 'Paper Parachutes'}}
                    for n in numbers]

        self.page.api_answers[f'{base}?include=albums'] = {'data': [{
            'id': '42', 'type': 'artists', 'attributes': {'name': 'Paper Parachutes'},
            'relationships': {'albums': {'data': stubs(1, 2),
                                         'next': f'{base}/albums?offset=2'}}}]}
        self.page.api_answers[f'{base}/albums?offset=2'] = {
            'data': stubs(3, 4), 'next': f'{base}/albums?offset=4'}
        self.page.api_answers[f'{base}/albums?offset=4'] = {'data': stubs(5)}
        await self.engine.start()
        with mock.patch.object(catalog_module, 'ALBUM_BATCH', 2), \
                mock.patch.object(art_cache, 'download_item_art',
                                  lambda item, cache_dir, art_urls, generation: item):
            item = await self.engine.item('artist', '42')
        self.assertEqual([group['name'] for group in item['groups']],
                         ['Album 1', 'Album 2', 'Album 3', 'Album 4', 'Album 5'])
        # The pages followed one by one, then the albums two at a time (none answers here:
        # the stubs stand in).
        self.assertEqual(self.page.api_calls[:3], [
            f'{base}?include=albums', f'{base}/albums?offset=2', f'{base}/albums?offset=4'])
        self.assertEqual(len(self.page.api_calls), 3 + 5)

    async def test_item_has_all_of_a_long_playlist(self):
        self.page.authorized = True
        path = '/v1/catalog/us/playlists/pl.u-1'

        def tracks(first, last):
            return [{'id': f'20000{n:04}', 'type': 'songs',
                     'attributes': {'name': f'Song {n}', 'artistName': 'The Invented Band',
                                    'durationInMillis': 180000}}
                    for n in range(first, last)]

        self.page.api_answers[f'{path}?include=tracks'] = {'data': [{
            'id': 'pl.u-1', 'type': 'playlists', 'attributes': {'name': 'Long Drive'},
            'relationships': {'tracks': {'data': tracks(0, 100),
                                         'next': f'{path}/tracks?offset=100'}}}]}
        self.page.api_answers[f'{path}/tracks?offset=100'] = {'data': tracks(100, 150)}
        await self.engine.start()
        with mock.patch.object(art_cache, 'download_item_art',
                               lambda item, cache_dir, art_urls, generation: item):
            item = await self.engine.item('playlist', 'pl.u-1')
        entries = [entry for group in item['groups'] for entry in group['entries']]
        self.assertEqual(len(entries), 150)
        self.assertEqual(entries[-1]['title'], 'Song 149')
        self.assertEqual(item['trackCount'], 150)

    async def test_item_reads_the_storefront_once(self):
        self.page.authorized = True
        self.page.storefront = 'gb'
        path = '/v1/catalog/gb/stations/ra.1'
        self.page.api_answers[path] = {'data': [{
            'id': 'ra.1', 'type': 'stations', 'attributes': {'name': 'Harbour Radio'}}]}
        await self.engine.start()
        reads = self.page.status_reads
        with mock.patch.object(art_cache, 'download_item_art',
                               lambda item, cache_dir, art_urls, generation: item):
            await self.engine.item('station', 'ra.1')
            await self.engine.item('station', 'ra.1')
            self.assertEqual(self.page.status_reads, reads)  # the start's status sufficed
            self.assertEqual(self.page.api_calls, [path, path])
            # Signed in again (another account, maybe): the next item asks once.
            await self.chrome.send_binding('authorizationStatusDidChange',
                                           {'authorized': True, 'status': 3})
            await until(lambda: self.engine._storefront is None)
            await self.engine.item('station', 'ra.1')
            await self.engine.item('station', 'ra.1')
        self.assertEqual(self.page.status_reads, reads + 1)

    async def test_item_that_cannot_be_kept_is_api(self):
        self.page.authorized = True
        with open(FIXTURES / 'catalog_album.json') as f:
            self.page.api_answers['/v1/catalog/us/albums/1724040700?include=tracks,artists'] = (
                json.load(f))
        await self.engine.start()

        def full(*args):
            raise OSError(28, 'No space left on device')

        with mock.patch.object(catalog_module, '_shape_item', full):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.item('album', '1724040700')
        self.assertEqual(ctx.exception.code, 'api')
        self.assertIn('No space left on device', ctx.exception.message)

    async def test_signin_waits_for_the_event(self):
        await self.engine.start()
        task = asyncio.create_task(self.engine.signin(timeout=5))
        await until(lambda: self.engine.state == 'signing-in')
        await until(lambda: self.page.signin_calls == 1)  # mk.authorize() was asked
        self.page.authorized = True
        await self.chrome.send_binding('authorizationStatusDidChange',
                                       {'authorized': True, 'status': 1})
        self.assertTrue(await asyncio.wait_for(task, 3))
        self.assertTrue(self.engine.authorized)
        self.assertEqual(self.engine.state, 'up')

    async def test_signin_polls_the_status(self):
        await self.engine.start()
        with mock.patch.object(core_module, 'SIGNIN_POLL', 0.1):
            task = asyncio.create_task(self.engine.signin(timeout=5))
            await asyncio.sleep(0.25)
            self.assertFalse(task.done())
            self.page.authorized = True  # no event: the poll finds it
            self.assertTrue(await asyncio.wait_for(task, 3))
        self.assertTrue(self.engine.authorized)
        self.assertEqual(self.engine.state, 'up')

    async def test_signin_does_not_spin_on_a_status_that_fails(self):
        await self.engine.start()
        page = self.page
        reads = []

        def navigating(message):
            if message['params']['expression'] == 'window.__appleMusicLibrary.status()':
                reads.append(message)
                return thrown('Error: the page is navigating')
            return page(message)

        with mock.patch.object(core_module, 'SIGNIN_POLL', 0.1):
            task = asyncio.create_task(self.engine.signin(timeout=0.5))
            await until(lambda: self.engine.state == 'signing-in')
            self.chrome.responders['Runtime.evaluate'] = navigating
            # Signed in, and the page navigates: the event wakes the loop, the reads fail.
            await self.chrome.send_binding('authorizationStatusDidChange',
                                           {'authorized': True, 'status': 3})
            with self.assertRaises(EngineError) as ctx:
                await task
        self.assertEqual(ctx.exception.code, 'timeout')
        self.assertLess(len(reads), 10)  # one per poll, not thousands

    async def test_signin_times_out(self):
        await self.engine.start()
        with mock.patch.object(core_module, 'SIGNIN_POLL', 0.1):
            with self.assertRaises(EngineError) as ctx:
                await self.engine.signin(timeout=0.3)
        self.assertEqual(ctx.exception.code, 'timeout')
        self.assertEqual(self.engine.state, 'up')
        self.assertFalse(self.engine.authorized)

    async def test_signin_cancelled_leaves_the_engine_up(self):
        await self.engine.start()
        task = asyncio.create_task(self.engine.signin(timeout=5))
        await until(lambda: self.engine.state == 'signing-in')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.engine.state, 'up')

    async def test_signin_when_the_engine_stops(self):
        await self.engine.start()
        with mock.patch.object(core_module, 'SIGNIN_POLL', 0.1):
            task = asyncio.create_task(self.engine.signin(timeout=5))
            await until(lambda: self.engine.state == 'signing-in')
            await self.engine.stop()
            with self.assertRaises(EngineError) as ctx:
                await task
        self.assertEqual(ctx.exception.code, 'engine-down')
        self.assertEqual(self.engine.state, 'down')

    async def test_signin_already_authorized(self):
        self.page.authorized = True
        await self.engine.start()
        self.assertTrue(await self.engine.signin())
        self.assertEqual(self.page.signin_calls, 0)

    async def test_unauthorize_revokes_the_session_and_never_raises(self):
        with self.assertLogs('applemusic.engine', 'WARNING'):
            self.assertFalse(await self.engine.unauthorize())  # down: nothing to revoke with
        self.page.authorized = True
        await self.engine.start()
        self.assertTrue(await self.engine.unauthorize())
        self.assertEqual(self.page.bridge_calls, [('signout',)])
        self.assertFalse(self.engine.authorized)
        self.page.bridge_answers['signout'] = {'error': 'Unauthorized'}
        with self.assertLogs('applemusic.engine', 'WARNING') as logs:
            self.assertFalse(await self.engine.unauthorize())
        self.assertIn('Unauthorized', logs.output[0])
        # A page that does not answer in time: False, after `timeout`.
        page = self.page
        self.chrome.responders['Runtime.evaluate'] = lambda message: (
            None if 'signout' in message['params']['expression'] else page(message))
        with self.assertLogs('applemusic.engine', 'WARNING'):
            self.assertFalse(await self.engine.unauthorize(timeout=0.2))
        self.assertEqual(self.engine.state, 'up')

    async def test_account_name(self):
        await self.engine.start()
        self.assertEqual(await self.engine.account_name(), '')
        self.page.account = '  Jo  Bloggs '
        self.assertEqual(await self.engine.account_name(), 'Jo Bloggs')
        self.page.account = 'x' * 65  # not a name
        self.assertEqual(await self.engine.account_name(), '')
        self.page.account = 7
        self.assertEqual(await self.engine.account_name(), '')

    async def test_account_name_waits_for_the_account_menu(self):
        await self.engine.start()

        async def later():
            await asyncio.sleep(0.15)
            self.page.account = 'Jo Bloggs'

        with mock.patch.object(core_module, 'ACCOUNT_NAME_POLL', 0.05):
            appears = asyncio.create_task(later())
            self.assertEqual(await self.engine.account_name(wait=1), 'Jo Bloggs')
            await appears
            self.page.account = None
            self.assertEqual(await self.engine.account_name(wait=0.1), '')  # gives up


BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:path={socket}</listen>
  <servicedir>{services}</servicedir>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""

# A secret service the private bus can activate: it owns the name on the bus it is given and
# lives while that bus does (exit_on_close), so it goes with the test's dbus-daemon.
SECRETS_SERVICE = """\
import sys
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
         | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
connection = Gio.DBusConnection.new_for_address_sync(sys.argv[1], flags, None, None)
connection.set_exit_on_close(True)
Gio.bus_own_name_on_connection(connection, sys.argv[2], Gio.BusNameOwnerFlags.NONE, None, None)
GLib.timeout_add_seconds(60, sys.exit, 0)
GLib.MainLoop().run()
"""

BUS_FLAGS = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
             | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)


@unittest.skipUnless(shutil.which('dbus-daemon'), 'no dbus-daemon for a private bus')
class KeyringTest(EngineFixture):
    """A start on a profile whose Local State records the keyring's key checks for
    org.freedesktop.secrets on the session bus Chrome will use, here a private dbus-daemon
    with a service directory of its own, so what it owns and can activate is the test's.
    Refused, nothing is spawned: Chrome without its key would delete the sign-in."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        root = pathlib.Path(self.tmp.name)
        self.services = root / 'services'
        self.services.mkdir()
        config = root / 'bus.conf'
        config.write_text(BUS_CONFIG.format(socket=root / 'bus', services=self.services))
        daemon = subprocess.Popen(
            ['dbus-daemon', '--config-file', str(config), '--nofork', '--nopidfile',
             '--print-address=1'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(daemon.wait)
        self.addCleanup(daemon.terminate)
        self.address = daemon.stdout.readline().strip()
        daemon.stdout.close()
        if not self.address:
            raise unittest.SkipTest('dbus-daemon gave no address')
        os.environ['APPLE_MUSIC_HOST_SESSION_BUS'] = self.address
        self.record_keyring_use(True)

    def record_keyring_use(self, used):
        """A Local State as Chrome 154 writes it after a start with (or without) the keyring."""
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.profile / chrome.LOCAL_STATE).write_text(json.dumps({
            'os_crypt': {'portal': {'prev_init_success': used, 'prev_desktop': 'GNOME'}}}))

    def bus_call(self, method, parameters=None, reply_type=None):
        """One call to the private bus's driver, on a connection of the test's own."""
        connection = Gio.DBusConnection.new_for_address_sync(self.address, BUS_FLAGS, None,
                                                             None)
        try:
            answer = connection.call_sync(
                'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                method, parameters, GLib.VariantType(reply_type) if reply_type else None,
                Gio.DBusCallFlags.NONE, 3000, None)
        finally:
            connection.close_sync(None)
        return answer.unpack()[0] if reply_type else None

    def own_the_name(self):
        """The test's own connection owning org.freedesktop.secrets until the test ends."""
        connection = Gio.DBusConnection.new_for_address_sync(self.address, BUS_FLAGS, None,
                                                             None)
        self.addCleanup(connection.close_sync, None)
        reply = connection.call_sync(
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'RequestName', GLib.Variant('(su)', (chrome.SECRETS_NAME, 0)),
            GLib.VariantType('(u)'), Gio.DBusCallFlags.NONE, 3000, None)
        self.assertEqual(reply.unpack()[0], 1)  # the primary owner

    def name_has_owner(self):
        return self.bus_call('NameHasOwner', GLib.Variant('(s)', (chrome.SECRETS_NAME,)), '(b)')

    def make_activatable(self, exec_line):
        """A service file for org.freedesktop.secrets the daemon can activate."""
        (self.services / f'{chrome.SECRETS_NAME}.service').write_text(
            f'[D-BUS Service]\nName={chrome.SECRETS_NAME}\nExec={exec_line}\n')
        self.bus_call('ReloadConfig')

    async def refused(self):
        """The EngineError a refused start raises, nothing spawned and the engine down."""
        with self.assertRaises(EngineError) as raised:
            await self.engine.start()
        self.assertEqual(raised.exception.code, 'no-keyring')
        self.assertEqual((self.engine.spawned, self.chrome.chromes), ([], []))
        self.assertEqual((self.engine.state, self.states), ('down', ['starting', 'down']))
        return raised.exception

    async def test_no_secret_service_on_the_bus_refuses_the_start(self):
        with self.assertLogs('applemusic.engine', 'WARNING') as logs:
            error = await self.refused()
        self.assertIn('no org.freedesktop.secrets', error.message)
        self.assertIn('APPLE_MUSIC_HOST_SESSION_BUS', error.message)
        self.assertTrue(any('not starting Chrome' in line and 'drop its sign-in' in line
                            for line in logs.output), logs.output)

    async def test_an_owner_lets_chrome_start_on_that_bus(self):
        self.own_the_name()
        await self.engine.start()
        self.assertEqual(self.chrome.chromes[-1]['bus'], self.address)

    async def test_an_activatable_service_that_comes_up_lets_chrome_start(self):
        script = pathlib.Path(self.tmp.name) / 'secrets_service.py'
        script.write_text(SECRETS_SERVICE)
        self.make_activatable(f'{sys.executable} {script} {self.address} {chrome.SECRETS_NAME}')
        self.assertFalse(self.name_has_owner())
        await self.engine.start()
        self.assertTrue(self.name_has_owner())  # started by the check, as Chrome would
        self.assertEqual(self.chrome.chromes[-1]['bus'], self.address)

    async def test_an_activatable_service_that_fails_refuses_the_start(self):
        # Activatable was what the private session of the incident had: the name in a
        # system service file, and an activation that never came up.
        self.make_activatable('/bin/false')
        with self.assertLogs('applemusic.engine', 'WARNING'):
            error = await self.refused()
        self.assertIn('org.freedesktop.secrets did not start', error.message)

    async def test_a_bus_that_never_answers_refuses_the_start_in_time(self):
        async def never(address, cancellable):
            await asyncio.sleep(3600)

        with mock.patch.object(core_module, 'KEYRING_WAIT', 0.2), \
                mock.patch.object(Engine, '_secret_service', staticmethod(never)), \
                self.assertLogs('applemusic.engine', 'WARNING'):
            error = await self.refused()
        self.assertIn('did not answer within 0.2 s', error.message)

    async def test_a_bus_that_cannot_be_reached_refuses_the_start(self):
        os.environ['APPLE_MUSIC_HOST_SESSION_BUS'] = 'unix:path=/nonexistent/host-bus'
        with self.assertLogs('applemusic.engine', 'WARNING'):
            error = await self.refused()
        self.assertIn('no session bus for Chrome', error.message)

    async def test_a_profile_that_never_reached_the_keyring_starts_as_before(self):
        self.record_keyring_use(False)
        await self.engine.start()  # the bus has no secret service
        self.assertEqual(self.chrome.chromes[-1]['bus'], self.address)

    async def test_without_a_host_bus_the_app_s_own_is_checked(self):
        del os.environ['APPLE_MUSIC_HOST_SESSION_BUS']

        async def private_bus(bus_type, cancellable):
            self.assertEqual(bus_type, Gio.BusType.SESSION)
            return await Gio.DBusConnection.new_for_address(self.address, BUS_FLAGS, None,
                                                            cancellable)

        with mock.patch.object(Gio, 'bus_get', private_bus):
            with self.assertLogs('applemusic.engine', 'WARNING'):
                error = await self.refused()
            self.assertIn("on the app's session bus", error.message)
            self.own_the_name()
            await self.engine.start()
        self.assertEqual(self.chrome.chromes[-1]['bus'],
                         os.environ.get('DBUS_SESSION_BUS_ADDRESS'))

    async def test_nothing_is_checked_in_a_flatpak_sandbox(self):
        # Chrome is the host's there, on the host's session, which this cannot see; the spawn
        # itself would go through flatpak-spawn, so the check alone is called.
        with mock.patch.object(chrome, 'in_flatpak', lambda: True):
            self.assertIsNone(await self.engine._check_keyring(self.address))
            self.assertIsNone(await self.engine._check_keyring(None))


class PdeathsigTest(unittest.TestCase):
    """Chrome tied to the app's life through setpriv --pdeathsig TERM."""

    def which(self, found):
        return mock.patch.object(core_module.shutil, 'which',
                                 lambda name: found if name == 'setpriv' else None)

    def test_argv_goes_through_setpriv(self):
        with self.which('/usr/bin/setpriv'), \
                mock.patch.object(chrome, 'in_flatpak', lambda: False):
            self.assertEqual(core_module.with_pdeathsig(['chrome', '--x']),
                             ['/usr/bin/setpriv', '--pdeathsig', 'TERM', '--', 'chrome', '--x'])

    def test_not_in_a_flatpak(self):
        with self.which('/usr/bin/setpriv'), \
                mock.patch.object(chrome, 'in_flatpak', lambda: True):
            self.assertEqual(core_module.with_pdeathsig(['flatpak-spawn', '--host']),
                             ['flatpak-spawn', '--host'])

    def test_without_setpriv_a_warning_once(self):
        patcher = mock.patch.object(core_module, '_setpriv_missing_told', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.which(None), mock.patch.object(chrome, 'in_flatpak', lambda: False):
            with self.assertLogs('applemusic.engine', 'WARNING'):
                self.assertEqual(core_module.with_pdeathsig(['chrome']), ['chrome'])
            with self.assertNoLogs('applemusic.engine', 'WARNING'):
                self.assertEqual(core_module.with_pdeathsig(['chrome']), ['chrome'])

    @unittest.skipUnless(shutil.which('setpriv') and os.path.isdir('/proc'),
                         'needs setpriv (util-linux) and /proc')
    def test_the_child_goes_when_its_parent_is_killed(self):
        # The "app" spawns the "Chrome" through setpriv and is SIGKILLed once the "Chrome" runs.
        # setpriv asks for the signal (prctl) just before it execs the program, and killing the
        # parent before then sends nothing. So the program says its pid itself, once it is
        # running: /proc's command line cannot tell, since it reads as the app's, or empty,
        # while the child is still exec'ing setpriv.
        read, write = os.pipe()
        grandchild = (f'import os, time; os.write({write}, str(os.getpid()).encode());'
                      ' time.sleep(30)')
        app = subprocess.Popen([sys.executable, '-S', '-c', (
            'import subprocess, sys, time\n'
            'subprocess.Popen(["setpriv", "--pdeathsig", "TERM", "--", sys.executable,'
            f' "-S", "-c", {grandchild!r}], pass_fds=({write},))\n'
            'time.sleep(30)\n')], pass_fds=(write,))
        os.close(write)
        self.addCleanup(app.wait)
        self.addCleanup(app.kill)
        try:
            ready, _, _ = select.select([read], [], [], SLOW_MACHINE)
            self.assertTrue(ready, 'setpriv never ran the program')
            child = int(os.read(read, 32))
        finally:
            os.close(read)
        self.assertFalse(gone_within(child, 0))
        app.kill()
        app.wait()
        self.assertTrue(gone_within(child, SLOW_MACHINE), 'the grandchild outlived its parent')


# A deadline for what a loaded machine may take seconds to do; the waits end as soon as it is done.
SLOW_MACHINE = 10.0


def gone_within(pid, timeout):
    """Whether `pid` has exited (gone, or a zombie nobody reaps) within `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            state = pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1][0]
        except (OSError, IndexError):
            return True
        if state in 'ZX':
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


class DemoEngineTest(unittest.IsolatedAsyncioTestCase):
    async def test_demo_does_nothing_and_every_command_is_engine_down(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        # A kept answer is not served either: a demo has none of Apple's.
        cache_files.write_answer(cache_files.landing_cache_path(tmp.name), {'categories': []},
                                 tmp.name)
        engine = Engine(profile_dir='/nowhere/chrome', demo=True)
        await engine.start()
        await engine.start(visible=True)
        self.assertEqual(engine.state, 'down')
        for command in (engine.status(), engine.item('album', '1'), engine.signin(),
                        engine.account_name(), engine.search('x'), engine.suggest('x'),
                        engine.landing(), engine.category('1'), engine.browse(),
                        engine.made_for_you()):
            with self.assertRaises(EngineError) as ctx:
                await command
            self.assertEqual(ctx.exception.code, 'engine-down')
        await engine.stop()
        self.assertFalse(pathlib.Path('/nowhere/chrome').exists())


class RefuseStartsTest(unittest.IsolatedAsyncioTestCase):
    """Engine.refuse_starts: sign-out's guard while it deletes the profile."""

    async def test_a_refused_start_spawns_nothing(self):
        engine = Engine(profile_dir=tempfile.mkdtemp(prefix='refused-'))
        self.addCleanup(shutil.rmtree, engine.profile_dir, ignore_errors=True)
        engine.refuse_starts = 'signing out'
        with mock.patch.object(chrome, 'find_chrome',
                               side_effect=AssertionError('looked for Chrome')):
            with self.assertRaises(EngineError) as raised:
                await engine.start()
            self.assertEqual(raised.exception.code, 'engine-down')
            self.assertEqual(engine.state, 'down')
            # A running engine in the mode asked for is kept, refused or not.
            engine.state = 'up'
            await engine.start()
            await engine.start(visible=False)
        engine.refuse_starts = None


class BrowserVersionTest(unittest.IsolatedAsyncioTestCase):
    """Engine.browser_version(): the About dialog's line on Chrome, from a stand-in client."""

    async def test_the_product_while_up_none_otherwise(self):
        answers = []

        class Client:
            async def call(self, method, params=None, timeout=None, browser=False):
                answers.append((method, browser))
                answer = answers_to_give.pop(0)
                if isinstance(answer, Exception):
                    raise answer
                return answer

        answers_to_give = [{'product': 'Chrome/154.0.0.0'}, EngineError('timeout', 'slow'), {}]
        engine = Engine()
        self.assertIsNone(await engine.browser_version())  # down: nothing asked
        engine._client = Client()
        engine.state = 'up'
        self.assertEqual(await engine.browser_version(), 'Chrome/154.0.0.0')
        self.assertIsNone(await engine.browser_version())
        self.assertIsNone(await engine.browser_version())
        self.assertEqual(answers, [('Browser.getVersion', True)] * 3)


class BrowserPathTest(unittest.IsolatedAsyncioTestCase):
    """Engine.browser_path(): Preferences' check of a browser program, no Chrome needed."""

    async def test_a_program_is_looked_up_as_it_is(self):
        with tempfile.TemporaryDirectory() as bin_dir:
            program = os.path.join(bin_dir, 'invented-browser')
            with open(program, 'w', encoding='utf-8') as file:
                file.write('#!/bin/sh\n')
            os.chmod(program, 0o755)
            with mock.patch.object(chrome, 'in_flatpak', lambda: False), \
                    mock.patch.dict(os.environ, {'PATH': bin_dir}):
                self.assertEqual(await Engine.browser_path('invented-browser'), program)
                self.assertEqual(await Engine.browser_path(program), program)
                # No other name is tried in its place, as a start would.
                self.assertIsNone(await Engine.browser_path('google-chrome-stable'))

    async def test_in_a_sandbox_the_host_is_asked(self):
        with mock.patch.object(chrome, 'in_flatpak', lambda: True), \
                mock.patch.object(chrome, 'find_host_chrome', lambda names: f'/host/{names[0]}'):
            self.assertEqual(await Engine.browser_path('chrome'), '/host/chrome')


if __name__ == '__main__':
    unittest.main()
