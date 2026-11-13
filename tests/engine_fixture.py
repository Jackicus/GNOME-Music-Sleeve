# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The engine's tests' fake Chrome: the Engine against it, for tests/test_engine*.py.

The tests run on gi.events' GLib-backed loop, as the app does, and the Engine spawns "Chrome"
through its own Gio.Subprocess code with the DevTools pipe on descriptors 3 and 4: only the
binary is fake. It is tests/fake_chrome_relay.py, which relays the pipe to the fake browser the
test runs on a Unix socket (UnixFakeChrome, test_client's FakeBrowser), so signals, exits and
the pipe closing are real. chrome.find_chrome is patched to name it, so nothing looks for, or
runs, a real Chrome. No display: the Engine is a GObject.
"""

import asyncio
import json
import os
import pathlib
import re
import shlex
import sys
import tempfile
import unittest
from unittest import mock

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)

from gi.events import GLibEventLoop

from applemusic.backend import chrome
from applemusic.engine import Engine
from tests.test_client import FakeBrowser, FakePage, thrown, until, value

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
RELAY = pathlib.Path(__file__).parent / 'fake_chrome_relay.py'
PLAYBACK_METHODS = ('signout', 'play', 'playNext', 'playLater', 'control', 'seek', 'volume',
                    'shuffle',
                    'repeat', 'nowPlaying', 'queue', 'queueJump', 'queueRemove', 'queueMove',
                    'queueClear', 'queueUndoClear', 'autoplay', 'lyrics',
                    'search', 'suggest', 'searchLanding', 'category', 'playlistSuggestions',
                    'rating', 'addToLibrary', 'removeFromLibrary', 'libraryHas',
                    'addToPlaylist', 'createPlaylist',
                    'updatePlaylist', 'deletePlaylist', 'removeFromPlaylist',
                    'replacePlaylistTracks', 'updateFolder', 'deleteFolder', 'createFolder',
                    'moveToFolder', 'preview',
                    'stopPreview', 'favourite', 'apiFresh')


class UnixFakeChrome(FakeBrowser):
    """FakeBrowser behind a Unix socket, where each fake Chrome the engine starts connects
    (its first line says its pid and argv, in `chromes`). The latest connection is the one
    answered; drop() hangs up on it, which ends that Chrome."""

    def __init__(self):
        super().__init__()
        self.chromes = []
        self.server = None
        self.writer = None

    async def start(self, path):
        self.server = await asyncio.start_unix_server(self._serve, path, limit=1 << 24)

    async def _serve(self, reader, writer):
        try:
            hello = json.loads(await reader.readline())
        except (ValueError, ConnectionError):
            writer.close()
            return
        self.chromes.append(hello)
        self.writer = writer
        buffer = b''
        try:
            while chunk := await reader.read(1 << 20):
                buffer += chunk
                *messages, buffer = buffer.split(b'\0')
                for message in messages:
                    await self.on_message(json.loads(message))
        except ConnectionError:
            pass
        finally:
            writer.close()

    async def write(self, payload):
        if self.writer is not None and not self.writer.is_closing():
            self.writer.write(payload + b'\0')
            await self.writer.drain()

    async def drop(self):
        """This Chrome goes: the relay sees the socket close and exits."""
        if self.writer is not None:
            self.writer.close()

    async def close(self):
        if self.writer is not None:
            self.writer.close()
        self.server.close()
        await self.server.wait_closed()

    @property
    def argv(self):
        """The latest Chrome's arguments (without the binary)."""
        return self.chromes[-1]['argv']


class EnginePage(FakePage):
    """The fake page: the bridge's status(), drm(), signin(), api() and apiAll(), and the
    account name lookup, on top of FakePage's probe/inject/subscribe."""

    def __init__(self):
        super().__init__()
        self.authorized = False
        self.storefront = 'us'
        self.api_answers = {}   # path, or (path, offset) for a page -> answer dict
        self.api_calls = []
        self.api_params = []    # the params of each api() call, in order
        self.signin_calls = 0
        self.account = None
        self.bridge_calls = []  # (method, args) of the playback commands
        self.bridge_answers = {}  # method -> what it answers (None: {ok: True})
        self.status_reads = 0   # the bridge's status() calls
        self.widevine = True    # drm()'s answer; None: it throws
        self.drm_reads = 0
        self.bitrate = 256      # mk.bitrate, as status() and bitrate() answer it
        self.bitrate_calls = []  # what each bitrate() call asked

    def __call__(self, message):
        expression = message['params']['expression']
        match = re.match(r'window\.__appleMusicLibrary\.(\w+)\((.*)\)$', expression, re.S)
        if expression == 'window.__appleMusicLibrary.drm()':
            self.drm_reads += 1
            if self.widevine is None:
                return thrown('TypeError: navigator is undefined')
            return value({'widevine': True} if self.widevine else {
                'widevine': False, 'error': 'Unsupported keySystem or supportedConfigurations.'})
        if match and match.group(1) in PLAYBACK_METHODS:
            args = json.loads('[' + match.group(2) + ']') if match.group(2) else []
            self.bridge_calls.append((match.group(1), *args))
            return value(self.bridge_answers.get(match.group(1), {'ok': True}))
        if match and match.group(1) == 'bitrate':
            asked = json.loads(match.group(2))
            self.bitrate_calls.append(asked)
            if asked is not None:
                self.bitrate = 64 if asked == 64 else 256  # bridge.js's PlaybackBitrate
            return value({'bitrate': self.bitrate})
        if expression == 'window.__appleMusicLibrary.status()':
            self.status_reads += 1
            return value(self.status())
        if expression == 'window.__appleMusicLibrary.signin()':
            self.signin_calls += 1
            return None  # hangs, as mk.authorize() does until the user acts
        if expression.startswith('window.__appleMusicLibrary.api('):
            path, params = json.loads(
                '[' + expression[len('window.__appleMusicLibrary.api('):-1] + ']')
            self.api_calls.append(path)
            self.api_params.append(params)
            answer = self.api_answers.get((path, params.get('offset')))
            if answer is None:
                answer = self.api_answers.get(path, {'errors': [{'status': '404', 'title': 'no'}]})
            return value(answer)
        if expression.startswith('window.__appleMusicLibrary.apiAll('):
            paths = json.loads(expression[len('window.__appleMusicLibrary.apiAll('):-1])
            self.api_calls.extend(paths)
            return value([self.api_answers.get(path) for path in paths])
        if expression == 'window.__appleMusicLibrary.accountName()':
            return value(self.account)
        return super().__call__(message)

    def status(self):
        return {'ready': self.ready, 'engine': True, 'authorized': self.authorized,
                'storefront': self.storefront, 'bitrate': self.bitrate}


class TestEngine(Engine):
    """An Engine that keeps every Chrome it spawned (the Gio.Subprocess and its argv)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.spawned = []   # [(process, argv)]

    def _spawn(self, argv, name=None, environment=None):
        process, transport = super()._spawn(argv, name, environment)
        self.spawned.append((process, argv))
        return process, transport


def exited(process):
    """Whether a Gio.Subprocess has ended (and been reaped)."""
    return process.get_identifier() is None


class EngineFixture(unittest.IsolatedAsyncioTestCase):
    """The fake Chrome, its page and a TestEngine on them. No tests of its own: the classes
    below subclass it, and a test here would run once for each of them."""

    loop_factory = GLibEventLoop

    # Seconds before the engine's first retry of a failed API read (doubling after): short,
    # so a read that fails every attempt takes milliseconds rather than 1.5 s.
    api_retry_delay = 0.01

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.profile = root / 'chrome-test'
        self.cache = root / 'cache'
        self.log_file = root / 'chrome.log'
        # The fake google-chrome-stable: the relay, on this Python.
        self.binary = root / 'google-chrome-stable'
        python, relay = shlex.quote(sys.executable), shlex.quote(str(RELAY))
        self.binary.write_text(f'#!/bin/sh\nexec {python} -S {relay} "$@"\n')
        self.binary.chmod(0o755)
        self.chrome = UnixFakeChrome()
        self.page = EnginePage()
        self.chrome.responders['Runtime.evaluate'] = self.page
        await self.chrome.start(str(root / 'chrome.sock'))
        environment = {'APPLE_MUSIC_CACHE': str(self.cache),
                       'FAKE_CHROME_SOCKET': str(root / 'chrome.sock'),
                       'FAKE_CHROME_LOG': str(self.log_file), 'FAKE_CHROME_MODE': ''}
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('APPLE_MUSIC_DEBUG_PORT', 'APPLE_MUSIC_PROFILE',
                     'APPLE_MUSIC_HOST_SESSION_BUS'):
            os.environ.pop(name, None)
        self.browser_commands = []
        patcher = mock.patch.object(chrome, 'find_chrome', self.find_chrome)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = TestEngine(profile_dir=self.profile)
        self.engine.stop_grace = 0.5
        self.engine.close_wait = 0.2
        self.engine.api_retry_delay = self.api_retry_delay
        self.states = []
        self.engine.connect('notify::state', lambda e, _p: self.states.append(e.state))

    async def asyncTearDown(self):
        await self.engine.stop()
        for process, _argv in self.engine.spawned:
            if not exited(process):
                process.force_exit()
        await self.chrome.close()

    def find_chrome(self, command=None):
        self.browser_commands.append(command)
        return str(self.binary)

    def chrome_mode(self, mode):
        """How the next fake Chrome behaves: '', 'stubborn' or 'exit:N' (the relay's)."""
        os.environ['FAKE_CHROME_MODE'] = mode

    def chrome_log(self):
        """What the fake Chromes did, as (event, pid) pairs."""
        try:
            lines = self.log_file.read_text().split()
        except OSError:
            return []
        return [(lines[i], int(lines[i + 1])) for i in range(0, len(lines), 2)]

    async def wait_exited(self, process, timeout=3.0):
        await until(lambda: exited(process), timeout=timeout)
