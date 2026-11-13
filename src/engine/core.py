# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Engine itself: Chrome as a Gio.Subprocess, the one CDPClient over its pipe, the page's
state (authorized, storefront, bitrate, Widevine), its events, and signing in and out. The
commands are mixins of the one Engine, each in a module of its own (reads, playback, edits,
catalog, browse); the package's docstring lists them.

The browser command (`browser_command`) and the preferred mode (`prefer_headless`) are read
when Chrome is spawned, so a change applies at the next start and a running Chrome is left
alone. The streaming bitrate (`preferred_bitrate`, the streaming-quality setting's:
quality_bitrate()) is set on MusicKit beside every start and after every bridgeReset (the page
starts with MusicKit's own), when MusicKit has another; set_bitrate() changes it at once.
APPLE_MUSIC_DEBUG_PORT, when set, also opens DevTools on that port of 127.0.0.1 for a
developer's debug CLI to attach to, with a warning at every start. What the cache holds and
how it is cleared is src/cache.py's.

Chrome's session bus is the app's, or APPLE_MUSIC_HOST_SESSION_BUS when that is set
(scripts/headless.sh sets it to the desktop's while the app runs on a private one): the
keyring holding the key that encrypts the profile's cookies answers there. A start on a
profile whose Local State records that key (chrome.profile_used_keyring) first checks that
org.freedesktop.secrets is up on that bus, or comes up when asked, and is
EngineError('no-keyring') otherwise, Chrome never spawned: without its key Chrome deletes the
cookies it cannot decrypt, the sign-in among them. In a Flatpak sandbox the bus is given to
the host's Chrome through flatpak-spawn, and the host is asked (chrome.host_secret_service()).
"""

import asyncio
import logging
import os
import shutil
import signal
import time
from pathlib import Path

from gi.repository import Gio, GLib, GObject

from ..backend import api, chrome, config
from ..backend.client import EVENT_PREFIX, CDPClient, PipeTransport
from ..backend.errors import EngineError
from .browse import BrowseCommands
from .catalog import CatalogCommands
from .edits import AccountEdits
from .playback import QUALITIES, PlaybackCommands
from .reads import API_RETRY_DELAY, ApiReads

log = logging.getLogger(__name__)

PAGE_WAIT = 20.0          # a new Chrome showing music.apple.com
BRIDGE_WAIT = 15.0        # a fresh page loading MusicKit
EXIT_GRACE = 1.0          # Chrome's pipe closing to its exit being seen, when it fails
CDP_TIMEOUT = 30.0        # a CDP call without a timeout of its own
PROBE_TIMEOUT = 5.0       # after a call timed out: a page silent this long is wedged
CLOSE_WAIT = 2.0          # Chrome closing on Browser.close, before SIGTERM
STOP_GRACE = 5.0          # after SIGTERM, before SIGKILL
KEYRING_WAIT = 5.0        # the keyring answering on Chrome's bus, or starting when asked
DRM_TIMEOUT = 5.0         # the page saying whether the browser can decrypt Widevine
SIGNIN_TIMEOUT = 600.0    # ten minutes to sign in
SIGNIN_POLL = 2.0         # isAuthorized is polled this often while signing in
ACCOUNT_NAME_POLL = 0.5   # the account name is looked for this often while waiting for it
UNAUTHORIZE_TIMEOUT = 5.0  # MusicKit revoking the session, at sign-out


def _kbps(value):
    """A bitrate as the page gives it (a positive number), else 0: none known."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return 0
    return int(value)


def _exit_status(process):
    """How an exited Gio.Subprocess ended, for a message: 'status 3', 'signal 9'."""
    if process.get_if_signaled():
        return f'signal {process.get_term_sig()}'
    if process.get_if_exited():
        return f'status {process.get_exit_status()}'
    return 'status unknown'


async def _process_exit(process):
    """Until the Gio.Subprocess has exited (a task can wait on it and be cancelled cleanly:
    a cancelled wait_async() raises GLib.Error, not CancelledError)."""
    try:
        await process.wait_async()
    except GLib.Error:
        pass


def _connection_closed(connection, result):
    """A D-Bus connection's close done (Gio.DBusConnection.close's callback): a failure to
    close one the engine is finished with is nothing to report."""
    try:
        connection.close_finish(result)
    except GLib.Error:
        pass


_setpriv_missing_told = False


def with_pdeathsig(argv):
    """argv run through `setpriv --pdeathsig TERM --`, so the kernel sends Chrome SIGTERM when
    the app ends however it ends (a crash, SIGKILL, a lost display): its pid and command line
    are Chrome's through setpriv's exec. Not in a Flatpak sandbox, whose flatpak-spawn
    --watch-bus ends Chrome already; argv as it is (and a warning, once) without util-linux's
    setpriv, when only a clean quit stops Chrome and the next start ends one left behind."""
    global _setpriv_missing_told
    if chrome.in_flatpak():
        return list(argv)
    setpriv = shutil.which('setpriv')
    if setpriv is None:
        if not _setpriv_missing_told:
            _setpriv_missing_told = True
            log.warning('setpriv (util-linux) was not found: Chrome may outlive the app if it '
                        'crashes')
        return list(argv)
    return [setpriv, '--pdeathsig', 'TERM', '--', *argv]


class Engine(ApiReads, PlaybackCommands, AccountEdits, CatalogCommands, BrowseCommands,
             GObject.Object):
    """Chrome and the bridge, as one object the UI talks to. See the module."""

    __gtype_name__ = 'AppleMusicEngine'

    __gsignals__ = {
        'event': (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
        'lost': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    state = GObject.Property(type=str, default='down')
    authorized = GObject.Property(type=bool, default=False)
    headless = GObject.Property(type=bool, default=True)
    # False once the page has said the browser cannot decrypt Widevine: songs cannot play.
    widevine = GObject.Property(type=bool, default=True)
    # The kbps MusicKit streams at (256, 64), as the page last said; 0 while down or unknown.
    bitrate = GObject.Property(type=int, default=0)

    def __init__(self, profile_dir=None, browser_command=None, demo=False):
        super().__init__()
        self.demo = demo
        self.profile_dir = Path(profile_dir) if profile_dir else config.profile_dir()
        self.browser_command = browser_command
        # Whether start() without a mode runs Chrome headless (the engine-headless setting);
        # sign-in asks for a window whatever this says.
        self.prefer_headless = True
        # The kbps set on MusicKit beside every start and page load (streaming-quality).
        self.preferred_bitrate = QUALITIES[0][1]
        self.stop_grace = STOP_GRACE
        self.close_wait = CLOSE_WAIT
        self.probe_timeout = PROBE_TIMEOUT
        self.api_retry_delay = API_RETRY_DELAY
        self._catalog_artists = {}  # a library artist's name, folded -> its catalog id, or None
        self._related = {}  # (kind, catalog id) -> related()'s answer
        # catalog artist id -> whether they are a favourite, as this session wrote or read it
        # (an artist's page kept for a day says what it was when fetched)
        self._favourite_artists = {}
        # While set (a reason), start() refuses with 'engine-down': sign-out sets it while it
        # stops Chrome and deletes the profile, which a Chrome started meanwhile would rewrite.
        self.refuse_starts = None
        self._client = None
        self._process = None   # the Gio.Subprocess running Chrome
        self._pid = None       # its pid
        self._watch = None     # the task waiting for the connection to drop
        self._relay = None     # the task relaying Chrome's stderr to the log (DEBUG only)
        self._lock = asyncio.Lock()
        self._starting = None  # (Future, headless) of the start under way
        self._tasks = set()    # small tasks of the engine's own, held until they end
        self._probe = None     # the task asking a page that timed out whether it answers
        self._storefront = None  # the account's, as the last status read had it
        self._drm = None       # the task asking the page about Widevine, once per start
        # The language lyrics are translated into and the script of their pronunciations:
        # the user's (GLib's first language name: LANGUAGE, LC_ALL, LC_MESSAGES, LANG).
        self.lyrics_languages = api.lyrics_languages(GLib.get_language_names()[0])

    @property
    def pid(self):
        return self._pid

    @property
    def client(self):
        """The CDPClient while the engine is up (the debug CLI drives the page through it),
        else None."""
        return self._client if self.state in ('up', 'signing-in') else None

    @property
    def cache_dir(self):
        return config.cache_dir()

    # -- lifecycle ---------------------------------------------------------------------------

    async def start(self, visible=None):
        """Chrome up with the bridge in it: headless unless `visible`. Without a mode, a
        running engine is kept whatever its mode, and a stopped one starts headless unless
        `prefer_headless` is off. Asked for a mode, a running Chrome in the other mode is
        stopped first; one in the same mode is kept. EngineError when Chrome or the page will
        not come up, and only EngineError: anything unexpected is logged and becomes
        'engine-down'.

        A start already under way is joined rather than queued behind it, when it suits
        (any start without a mode, the same mode asked): its outcome, success or error, is
        this call's too. Cancelling the call that started it cancels the start (its waiters
        get 'engine-down'); cancelling a joined call leaves the start running."""
        if self.demo:
            return
        if self._starting is not None:
            future, headless = self._starting
            if visible is None or headless == (not visible):
                await self._join_start(future)
                return
        future = asyncio.get_running_loop().create_future()
        starting = self._starting = (
            future, self.prefer_headless if visible is None else not visible)
        try:
            await self._start_locked(visible)
        except BaseException as e:
            if not future.done():
                future.set_exception(e if isinstance(e, EngineError) else EngineError(
                    'engine-down', 'the engine was stopped while it started'))
            raise
        else:
            if not future.done():
                future.set_result(None)
        finally:
            if self._starting is starting:
                self._starting = None
            if not future.cancelled() and future.done():
                future.exception()  # retrieved, whether anyone joined or not

    @staticmethod
    async def _join_start(future):
        """Wait for a start under way, its failure raised here as an EngineError of the same
        code. The start goes on when the waiter is cancelled."""
        await asyncio.wait({future})
        error = future.exception()
        if error is not None:
            raise EngineError(error.code, error.message) from error

    async def _start_locked(self, visible):
        async with self._lock:
            if visible is None:
                if self.state != 'down':
                    return
                headless = self.prefer_headless
            else:
                headless = not visible
            if self.state != 'down' and self.headless == headless:
                return
            if self.refuse_starts:  # checked here: a start may have waited for a stop's lock
                raise EngineError('engine-down',
                                  f'the engine cannot start now: {self.refuse_starts}')
            if self.state != 'down':
                log.info('the engine is %s; restarting it %s',
                         'headless' if self.headless else 'visible',
                         'headless' if headless else 'visible')
                await self._stop()
            self.state = 'starting'
            self.headless = headless
            try:
                await self._start(headless)
            except BaseException as e:
                await self._stop()
                if isinstance(e, Exception) and not isinstance(e, EngineError):
                    log.error('the engine could not start', exc_info=e)
                    raise EngineError('engine-down', str(e) or type(e).__name__) from e
                raise

    async def _start(self, headless):
        # In a thread: in a Flatpak sandbox it asks the host through flatpak-spawn.
        binary = await asyncio.to_thread(chrome.find_chrome, self.browser_command)
        if binary is None:
            raise EngineError(
                'no-browser', 'a Chromium-based browser was not found (Google Chrome, '
                'Edge, Brave, Vivaldi or Chromium; the browser-command setting names another)')
        try:
            await asyncio.to_thread(self.profile_dir.mkdir, parents=True, exist_ok=True)
        except OSError as e:
            raise EngineError('engine-down',
                              f'could not prepare {self.profile_dir}: {e.strerror or e}') from e
        host_bus = config.host_session_bus()
        await self._check_keyring(host_bus)
        # A Chrome already on the profile (the debug CLI's, or one an app crash left behind)
        # would take the new one's arguments and let it exit at once.
        await self._end_owner()
        debug_port = config.debug_port()
        if debug_port is not None:
            log.warning("APPLE_MUSIC_DEBUG_PORT is set: Chrome's DevTools listen on "
                        '127.0.0.1:%d and any local program can control the signed-in '
                        'session', debug_port)
        argv = with_pdeathsig(
            chrome.chrome_args(binary, self.profile_dir, headless, debug_port=debug_port,
                               host_bus=host_bus))
        log.debug('exec %s', chrome.describe_argv(argv))  # the profile's path left out
        environment = chrome.chrome_environment(host_bus)
        if environment:
            log.debug("Chrome's session bus is APPLE_MUSIC_HOST_SESSION_BUS's")
        self._process, transport = self._spawn(argv, binary, environment)
        self._pid = int(self._process.get_identifier())
        log.info('Chrome %d started %s', self._pid, 'headless' if headless else 'visible')
        client = self._client = CDPClient(timeout=CDP_TIMEOUT)
        client.on(EVENT_PREFIX + '*', self._on_bridge_event)
        client.on_timeout = lambda _method: self._on_timeout(client)
        await self._open(client, transport, self._process)
        await client.ensure_bridge(timeout=BRIDGE_WAIT)
        await client.subscribe()  # finds the bridge in place; events from now on
        status = await client.bridge('status')
        self.authorized = bool(isinstance(status, dict) and status.get('authorized'))
        self._storefront = status.get('storefront') if isinstance(status, dict) else None
        self._set_bitrate(status.get('bitrate') if isinstance(status, dict) else None)
        if not self.widevine:
            self.widevine = True  # another browser, perhaps: its page says
        self._drm = self._in_background(self._check_widevine(client))
        self._in_background(self._apply_bitrate(client))
        self.state = 'up'
        self._watch = asyncio.create_task(self._watch_connection(client), name='engine-watch')
        log.info('engine up: %s', 'authorized' if self.authorized else 'not signed in')

    async def _check_widevine(self, client):
        """Whether the browser just started can decrypt Widevine, as its page says (the
        bridge's drm()), once per start, beside it rather than in its way: `widevine` goes
        False, with a warning, when the page says no. A page that cannot say (an error, no
        answer in DRM_TIMEOUT) leaves it True: a play would find out."""
        try:
            answer = await client.bridge('drm', timeout=DRM_TIMEOUT)
        except EngineError as e:
            log.debug('the Widevine check: %s', e)
            return
        if client is not self._client or not isinstance(answer, dict):
            return
        if answer.get('widevine') is False:
            log.warning('the browser cannot decrypt Widevine (%s): songs will not play in it; '
                        'Google Chrome can play them', answer.get('error') or 'refused')
            self.widevine = False
        else:
            log.debug('the browser can decrypt Widevine')

    async def _require_widevine(self):
        """Before a play: EngineError('no-widevine') when the page said the browser cannot
        decrypt Widevine; a check still under way is waited for (DRM_TIMEOUT at most)."""
        probe = self._drm
        if probe is not None and not probe.done():
            await asyncio.wait({probe})
        if not self.widevine:
            raise EngineError('no-widevine', 'the browser cannot decrypt Widevine, which the '
                              'songs are protected with')

    async def _check_keyring(self, host_bus):
        """Before Chrome is spawned: nothing for a profile whose Local State does not record
        the OS keyring's key (a fresh one, or one that never reached the keyring), else
        EngineError('no-keyring') unless org.freedesktop.secrets is up on the session bus
        Chrome will use (`host_bus`, or this process's own), or comes up when asked as Chrome
        would ask, within KEYRING_WAIT seconds. Started on such a profile without its key,
        Chrome encrypts with a fallback one and deletes the cookies it cannot decrypt: the
        sign-in. In a Flatpak sandbox Chrome is the host's, on the bus flatpak-spawn gives it
        (`host_bus`, else the host's session), which the sandbox cannot reach: the host is
        asked (chrome.host_secret_service())."""
        if not await asyncio.to_thread(chrome.profile_used_keyring, self.profile_dir):
            return
        if chrome.in_flatpak():
            reason = await asyncio.to_thread(chrome.host_secret_service, host_bus, KEYRING_WAIT)
        else:
            cancellable = Gio.Cancellable()
            try:
                reason = await asyncio.wait_for(self._secret_service(host_bus, cancellable),
                                                KEYRING_WAIT)
            except TimeoutError:
                cancellable.cancel()
                reason = f'{chrome.SECRETS_NAME} did not answer within {KEYRING_WAIT:g} s'
        if reason is None:
            return
        where = ('APPLE_MUSIC_HOST_SESSION_BUS' if host_bus
                 else "the host's session bus" if chrome.in_flatpak()
                 else "the app's session bus")
        log.warning('not starting Chrome: %s on %s, and the profile is encrypted with the '
                    "keyring's key, so Chrome would drop its sign-in", reason, where)
        raise EngineError('no-keyring',
                          f"{reason} on {where}: Chrome would drop the profile's sign-in")

    @staticmethod
    async def _secret_service(address, cancellable):
        """None when org.freedesktop.secrets has an owner on the session bus at `address`
        (None: this process's own), or is activatable there and comes up when asked; else
        why not, in a few words. A connection of its own to an address, closed after."""
        flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                 | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        try:
            if address:
                connection = await Gio.DBusConnection.new_for_address(address, flags, None,
                                                                      cancellable)
            else:
                connection = await Gio.bus_get(Gio.BusType.SESSION, cancellable)
        except GLib.Error as e:
            return f'no session bus for Chrome ({e.message})'

        async def bus_call(method, parameters, reply_type):
            answer = await connection.call(
                'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                method, parameters, GLib.VariantType(reply_type), Gio.DBusCallFlags.NONE,
                int(KEYRING_WAIT * 1000), cancellable)
            return answer.unpack()[0]

        name = chrome.SECRETS_NAME
        try:
            if await bus_call('NameHasOwner', GLib.Variant('(s)', (name,)), '(b)'):
                return None
            if name not in await bus_call('ListActivatableNames', None, '(as)'):
                return f'no {name} (no keyring service)'
            try:
                await bus_call('StartServiceByName', GLib.Variant('(su)', (name, 0)), '(u)')
            except GLib.Error as e:
                return f'{name} did not start: {e.message}'
            return None
        except GLib.Error as e:
            return f'the session bus did not answer: {e.message}'
        finally:
            if address:
                connection.close(None, _connection_closed)

    def _spawn(self, argv, name=None, environment=None):
        """Chrome as a Gio.Subprocess, the DevTools pipe on its descriptors 3 (it reads) and 4
        (it writes); its output silenced, or its stderr relayed to the log when that is at
        DEBUG; `environment`'s variables set over this process's (chrome.chrome_environment).
        Answers the process and the PipeTransport over this end of the pipe."""
        debug = log.isEnabledFor(logging.DEBUG)
        flags = Gio.SubprocessFlags.STDOUT_SILENCE | (
            Gio.SubprocessFlags.STDERR_PIPE if debug else Gio.SubprocessFlags.STDERR_SILENCE)
        commands, chrome_in = os.pipe()     # Chrome reads commands on its 3
        chrome_out, answers = os.pipe()     # and writes answers and events on its 4
        launcher = Gio.SubprocessLauncher.new(flags)
        for variable, value in (environment or {}).items():
            launcher.setenv(variable, value, True)
        launcher.take_fd(commands, 3)
        launcher.take_fd(answers, 4)
        try:
            process = launcher.spawnv(argv)
        except GLib.Error as e:
            os.close(chrome_in)
            os.close(chrome_out)
            raise EngineError('no-browser',
                              f'could not start {name or argv[0]}: {e.message}') from e
        finally:
            launcher.close()  # Chrome's ends are Chrome's alone now
        if debug:
            self._relay = asyncio.create_task(self._relay_stderr(process), name='chrome-stderr')
        return process, PipeTransport(chrome_out, chrome_in)

    async def _relay_stderr(self, process):
        """Chrome's stderr, a line at a time, to the log at DEBUG. Read to the end whatever
        happens: an undrained pipe would stall Chrome."""
        stream = process.get_stderr_pipe()
        pending = b''
        try:
            while True:
                data = await stream.read_bytes_async(4096, GLib.PRIORITY_LOW)
                chunk = data.get_data() if data is not None else b''
                if not chunk:
                    break
                pending += chunk
                *lines, pending = pending.split(b'\n')
                for line in lines:
                    log.debug('chrome: %s', line.decode('utf-8', 'replace').rstrip())
            if pending:
                log.debug('chrome: %s', pending.decode('utf-8', 'replace').rstrip())
        except GLib.Error as e:  # the pipe's own failure: Chrome has gone
            log.debug('chrome stderr relay ended: %s', e)
        except Exception:
            log.warning('chrome stderr relay failed', exc_info=True)
        finally:
            try:
                stream.close(None)
            except GLib.Error:
                pass

    async def _open(self, client, transport, process):
        """_connect(), raced against Chrome's exit: a Chrome that exits first (a wrong browser
        command, a crash, a profile another Chrome holds) is EngineError('engine-down') at
        once with its exit status, not a timeout after the page wait."""
        opening = asyncio.ensure_future(self._connect(client, transport))
        exited = asyncio.ensure_future(_process_exit(process))
        try:
            done, _ = await asyncio.wait({opening, exited}, return_when=asyncio.FIRST_COMPLETED)
            if opening in done and opening.exception() is None:
                return
            if exited not in done:
                # The connection failed first; a Chrome that is going closes its pipe a
                # moment before it is reaped.
                await asyncio.wait({exited}, timeout=EXIT_GRACE)
            if exited.done():
                raise EngineError('engine-down', f'Chrome exited at once ({_exit_status(process)})')
            raise opening.exception()
        finally:
            for task in (opening, exited):
                if not task.done():
                    task.cancel()
                elif not task.cancelled():
                    task.exception()  # retrieved: its error, if any, is ours or superseded

    async def _connect(self, client, transport):
        """The client on Chrome's pipe, attached to the music.apple.com page."""
        await client.connect(transport)
        await client.attach_page(PAGE_WAIT)

    def _on_timeout(self, client):
        """A call ran out of time: is the page there at all? One probe at a time, and only
        while the engine is up (a start has waits of its own)."""
        if self._client is not client or self.state not in ('up', 'signing-in'):
            return
        if self._probe is None or self._probe.done():
            self._probe = self._in_background(self._probe_page(client))

    async def _probe_page(self, client):
        """`0` in the page. A page that answers is alive, and the slow part was MusicKit or
        Apple; one silent for probe_timeout is wedged (a hung or crashed renderer), so its
        connection is closed: the engine goes down (_watch_connection) and the next command
        starts a fresh Chrome, rather than every command timing out while the Player shows
        what played last."""
        try:
            await client.evaluate('0', await_promise=False, timeout=self.probe_timeout)
        except EngineError as e:
            if e.code == 'timeout' and self._client is client:
                log.warning('the page does not answer; the engine goes down')
                await client.close('the page stopped answering')

    async def _watch_connection(self, client):
        """The engine down when its connection goes on its own (Chrome crashed or was killed,
        the page crashed, closed or stopped answering): `lost(reason)` first, which a stop,
        a restart, sign-in's restarts and quitting never emit."""
        await client.wait_closed()
        async with self._lock:
            if self._client is not client:
                return  # stop() closed it
            reason = client.lost_reason or 'the connection to Chrome was closed'
            log.warning('the engine is down: %s', reason)
            self.emit('lost', reason)
            await self._stop()

    async def stop(self, grace=None):
        """End Chrome: Browser.close over the pipe and up to close_wait seconds for it to go,
        then SIGTERM, up to `grace` seconds (stop_grace), SIGKILL. Nothing to do when it is
        down. Chrome's process is kept until it has gone, so a stop cancelled on its way (a
        bounded quit) still leaves kill() something to kill."""
        if self.demo:
            return
        async with self._lock:
            await self._stop(grace)

    async def _stop(self, grace=None):
        client, self._client = self._client, None
        watch, self._watch = self._watch, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()
        process = self._process
        if client is not None:
            client.off(EVENT_PREFIX + '*', self._on_bridge_event)
            if process is not None and client.connected:
                await self._close_browser(client, process)
            await client.close()
        if process is not None:
            await self._terminate(self._pid, process, grace)
            if self._process is process:
                self._pid = self._process = None
        else:
            await self._end_owner()  # stopping an engine that was never started here
        relay, self._relay = self._relay, None
        if relay is not None and not relay.done():
            try:
                await asyncio.wait_for(relay, 1.0)  # Chrome's pipe closes as it exits
            except TimeoutError:
                pass  # wait_for has cancelled it
            except Exception:  # the stop goes on to 'down' whatever the relay did
                log.warning('chrome stderr relay failed', exc_info=True)
        self.authorized = False
        self._storefront = None
        self._related = {}  # the next account's storefront may differ
        self._favourite_artists = {}  # and its favourites
        self._set_bitrate(None)
        self.state = 'down'

    async def _close_browser(self, client, process):
        """Browser.close over the pipe, and close_wait seconds in all for Chrome to exit."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.close_wait
        try:
            await client.call('Browser.close', browser=True, timeout=self.close_wait)
        except EngineError as e:  # the answer may not make it out before Chrome is gone
            log.debug('Browser.close: %s', e)
        await self._wait_exit(process, max(0.0, deadline - loop.time()))

    async def _terminate(self, pid, process, grace=None):
        """SIGTERM this process's Chrome, up to `grace` seconds (stop_grace), SIGKILL, and as
        long again for it to be gone."""
        if process.get_identifier() is None:
            return  # gone already, and reaped
        grace = self.stop_grace if grace is None else grace
        log.info('stopping Chrome %d', pid)
        self._signal(process, signal.SIGTERM)
        if not await self._wait_exit(process, grace):
            log.warning('Chrome %d ignored SIGTERM for %g s; killing it', pid, grace)
            self._signal(process, signal.SIGKILL)
            if not await self._wait_exit(process, max(grace, 1.0)):
                log.warning('Chrome %d is still there after SIGKILL', pid)

    async def _end_owner(self):
        """End a Chrome this process did not start that holds the profile (its SingletonLock
        names it): SIGTERM, stop_grace seconds, SIGKILL."""
        pid = await asyncio.to_thread(chrome.profile_owner, self.profile_dir)
        if pid is None:
            return
        log.info('Chrome %d holds the engine profile; stopping it', pid)
        for signum in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                return
            except OSError as e:
                log.warning('could not signal Chrome %d: %s', pid, e)
                return
            if await self._pid_gone(pid, self.stop_grace):
                return
            if signum == signal.SIGTERM:
                log.warning('Chrome %d ignored SIGTERM for %g s; killing it', pid,
                            self.stop_grace)
        log.warning('Chrome %d is still running after SIGKILL', pid)

    async def _pid_gone(self, pid, timeout):
        """True once `pid` is no Chrome on the profile, False after `timeout` seconds."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while await asyncio.to_thread(chrome.pid_alive, pid, self.profile_dir):
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.05)
        return True

    @staticmethod
    def _signal(process, signum):
        try:
            if signum == signal.SIGKILL:
                process.force_exit()
            else:
                process.send_signal(signum)
        except GLib.Error:
            pass

    @staticmethod
    async def _wait_exit(process, timeout):
        """True once the process is gone, False after `timeout` seconds with it still there."""
        try:
            await asyncio.wait_for(_process_exit(process), timeout)
            return True
        except TimeoutError:
            return False

    def kill(self):
        """SIGKILL Chrome now, without waiting: the last resort when stop() ran out of time.
        The connection is let go of as a stop would (it ends as Chrome does), so no `lost`
        follows."""
        client, self._client = self._client, None
        watch, self._watch = self._watch, None
        if watch is not None and watch is not asyncio.current_task():
            watch.cancel()
        if client is not None:
            client.off(EVENT_PREFIX + '*', self._on_bridge_event)
        pid, self._pid = self._pid, None
        process, self._process = self._process, None
        if process is not None and process.get_identifier() is not None:
            log.warning('killing Chrome %d', pid)
            self._signal(process, signal.SIGKILL)
        self.state = 'down'
        self.authorized = False
        self._set_bitrate(None)

    async def restart(self, visible=None):
        """stop(), then start(visible): without a mode, the preferred one (prefer_headless),
        with the browser the settings now name."""
        await self.stop()
        await self.start(visible=visible)

    async def browser_version(self):
        """Chrome's product and version ('Chrome/154.0.…', 'HeadlessChrome/…') while the
        engine is up, else None: for the About dialog's debug information."""
        client = self.client
        if client is None:
            return None
        try:
            answer = await client.call('Browser.getVersion', browser=True, timeout=5)
        except EngineError as e:
            log.debug('Browser.getVersion: %s', e)
            return None
        product = answer.get('product') if isinstance(answer, dict) else None
        return product if isinstance(product, str) and product else None

    @staticmethod
    async def browser_path(command):
        """Where the program `command` (a name on PATH, or a path) is, or None: on the host
        in a Flatpak sandbox, where Chrome runs. For Preferences to check a browser program
        before it is kept; unlike a start, it tries no other name."""
        if chrome.in_flatpak():
            return await asyncio.to_thread(chrome.find_host_chrome, [command])
        return await asyncio.to_thread(shutil.which, command)

    # -- events --------------------------------------------------------------------------

    def _on_bridge_event(self, name, data):
        name = name[len(EVENT_PREFIX):]
        if name == 'authorizationStatusDidChange' and isinstance(data, dict):
            authorized = bool(data.get('authorized'))
            if authorized != self.authorized:
                self.authorized = authorized
            self._storefront = None  # the account's may differ: the next status says
            self._related = {}
            self._favourite_artists = {}
        elif name == 'bridgeReset':
            # The page loaded a new document, and the bridge is back in it: what MusicKit
            # held (the sign-in, the queue, the bitrate) may have changed with it. The Player
            # hears it too.
            self._in_background(self._reread_status())
        elif name == 'playbackBitrateDidChange' and isinstance(data, dict):
            self._set_bitrate(data.get('bitrate'))  # MusicKit's own choice, or ours
        self.emit('event', name, data)

    async def _reread_status(self):
        try:
            await self.status()  # keeps `authorized` and `bitrate` current
        except EngineError as e:
            log.debug('status after the bridge came back: %s', e)
            return
        client = self._client
        if client is not None:
            await self._apply_bitrate(client)  # the new page has MusicKit's own

    def _in_background(self, coro):
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # -- commands ----------------------------------------------------------------------------

    async def _ready(self):
        """The client, for a command: a start in progress is waited for (its failure is the
        command's); 'engine-down' when the engine is down, since commands never start Chrome
        themselves."""
        if self.demo:
            raise EngineError('engine-down', 'the engine is not running')
        if self._starting is not None:
            await self._join_start(self._starting[0])
        if self._client is None or self.state not in ('up', 'signing-in'):
            raise EngineError('engine-down', 'the engine is not running')
        return self._client

    async def status(self):
        """The bridge's status: {ready, engine, authorized, storefront, bitrate}. It keeps
        `authorized` and the storefront the commands use current."""
        client = await self._ready()
        status = await client.bridge('status')
        if not isinstance(status, dict):
            raise EngineError('api', 'the page gave no status')
        self._take_status(status)
        return status

    def _take_status(self, status):
        authorized = bool(status.get('authorized'))
        if authorized != self.authorized:
            self.authorized = authorized
        self._storefront = str(status.get('storefront') or '') or None
        self._set_bitrate(status.get('bitrate'))

    def _set_bitrate(self, value):
        kbps = _kbps(value)
        if kbps != self.bitrate:
            self.bitrate = kbps

    async def _apply_bitrate(self, client):
        """`preferred_bitrate` set on the page's MusicKit, when it has another (a start, a
        page loaded again); a failure is logged, never raised."""
        if self.bitrate == self.preferred_bitrate:
            return
        try:
            await self._send_bitrate(client)
        except EngineError as e:
            log.debug('bitrate: %s', e)

    async def _send_bitrate(self, client):
        answer = await client.bridge('bitrate', self.preferred_bitrate)
        if client is self._client:
            self._set_bitrate(answer.get('bitrate') if isinstance(answer, dict) else None)
        if self.bitrate and self.bitrate != self.preferred_bitrate:
            log.info('bitrate: MusicKit kept %d kbps', self.bitrate)
        return self.bitrate

    async def _current_storefront(self):
        """The account's storefront ('gb'): as the last status read had it (the start's, or
        sign-in's), read again only when none has since the authorization changed."""
        if not self._storefront:
            await self.status()
        return self._storefront or 'us'

    async def signin(self, timeout=SIGNIN_TIMEOUT):
        """Until MusicKit is authorized: the bridge asks the page to authorize (Apple's sign-in
        in the visible Chrome window), then the authorizationStatusDidChange event or a poll
        of the status every SIGNIN_POLL seconds says so. The one place the app polls.
        True when signed in; EngineError('timeout') after `timeout` seconds."""
        client = await self._ready()
        if self.authorized:
            return True
        self.state = 'signing-in'
        authorized = asyncio.Event()

        def on_change(_name, data):
            if isinstance(data, dict) and data.get('authorized'):
                authorized.set()

        client.on(EVENT_PREFIX + 'authorizationStatusDidChange', on_change)
        prompt = asyncio.create_task(self._authorize(client, timeout), name='engine-authorize')
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                try:
                    await asyncio.wait_for(authorized.wait(), SIGNIN_POLL)
                except TimeoutError:
                    pass
                if self._client is not client:
                    raise EngineError('engine-down', 'the engine stopped while signing in')
                try:
                    status = await client.bridge('status', timeout=5)
                except EngineError as e:
                    if e.code == 'engine-down':
                        raise
                    log.debug('sign-in poll: %s', e)  # the page is navigating, mostly
                    status = None
                    # The event that woke the loop is spent: the next read waits for another
                    # event or the poll, not a loop as fast as the page can fail.
                    authorized.clear()
                if isinstance(status, dict) and status.get('authorized'):
                    self._take_status(status)
                    log.info('signed in')
                    return True
                if loop.time() >= deadline:
                    raise EngineError('timeout', f'not signed in within {timeout:g} s')
        finally:
            client.off(EVENT_PREFIX + 'authorizationStatusDidChange', on_change)
            if not prompt.done():
                prompt.cancel()
            if self.state == 'signing-in':
                self.state = 'up' if self._client is client else 'down'

    async def _authorize(self, client, timeout):
        """The bridge's signin(): mk.authorize(), whose promise settles when the user has
        signed in or given up. Its outcome is only logged: the poll decides."""
        try:
            result = await client.bridge('signin', timeout=timeout)
            log.debug('authorize answered %r', result)
        except EngineError as e:
            log.debug('authorize: %s', e)

    async def unauthorize(self, timeout=UNAUTHORIZE_TIMEOUT):
        """Sign out of Apple Music in the page: the bridge's signout(), MusicKit's
        unauthorize(), which revokes the session at Apple's end, so a copy of it stops
        working too. Sign-out calls it before the app forgets the account. Best effort: True
        when MusicKit said it was done; False when it could not be (the engine down, the page
        failing or slow, MusicKit refusing), logged at WARNING. It never raises an
        EngineError."""
        try:
            client = await self._ready()
            answer = await client.bridge('signout', timeout=timeout)
        except EngineError as e:
            log.warning('could not sign out of Apple Music: %s', e)
            return False
        if isinstance(answer, dict) and answer.get('ok'):
            log.info('signed out of Apple Music')
            self.authorized = False
            return True
        error = answer.get('error') if isinstance(answer, dict) else None
        log.warning('could not sign out of Apple Music: %s', error or 'no answer')
        return False

    async def account_name(self, wait=0):
        """The account's display name as the signed-in page shows it (the bridge's
        accountName(): only elements that name the user, none while a sign-in control is on
        the page), or '' when none does. Never a guess. Apple's page renders the account menu
        a moment after authorization, so `wait` seconds of polling (every
        ACCOUNT_NAME_POLL) cover the gap right after sign-in."""
        deadline = time.monotonic() + wait
        while True:
            client = await self._ready()
            try:
                name = await client.bridge('accountName', timeout=5)
            except EngineError as e:
                if e.code == 'engine-down':
                    raise
                log.debug('account name: %s', e)
                name = None
            if isinstance(name, str):
                name = ' '.join(name.split())
                if 0 < len(name) <= 64:
                    return name
            if time.monotonic() >= deadline:
                return ''
            await asyncio.sleep(ACCOUNT_NAME_POLL)

    async def _require_signed_in(self, what):
        """The client, for a command of the account's: 'not-signed-in' ("sign in to Apple
        Music to <what>") when MusicKit is not authorized."""
        client = await self._ready()
        if not self.authorized:
            raise EngineError('not-signed-in', f'sign in to Apple Music to {what}')
        return client
