# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A notification when the song changes, while the `notify-song-change` setting is on and
the window is out of sight.

    notifier = SongNotifier(app)   # in Application.do_startup, after app.player (not demo)
    notifier.start()               # follows the Player and the setting
    notifier.stop()                # at quit: nothing followed, the notification withdrawn

A song is announced once, after it has played for PLAYED_MS: a run of quick skips (each
item replacing the last before its second is up) announces only the one that stays, and a
song that never plays (loading, paused) is never announced. Only a change from one song to
another is: not the first item the Player holds (the session restored at launch, paused, or
what MusicKit was playing when the engine came up), not the restored item being played
(`new_song()`), not a live station's programme changing under the same station, and not a
song the window shows already (`should_notify()`: the window visible and focused, Preferences
included, `in_sight()`). The decision is taken when the second is up, so a song that began
while the user looked and played on after they left is not announced.

The notification (`NOTIFICATION_ID`, so each replaces the last, and never the toast that
background playback turns into a notification, main.BACKGROUND_NOTIFICATION) is the title,
the artist as its body, and the cover as its icon: the remote-art cache's file
(remote.fetch_remote, which the player bar has usually fetched already), read in a thread
into a Gio.BytesIcon, which the notification portal accepts where a file icon would need the
file shared. Clicking it runs `DEFAULT_ACTION`, which shows the window. It is withdrawn when
playback ends (no item), when the setting is turned off and at quit: it names a song no
longer playing.

No GTK: the window's state is the app's `window_in_sight()`, the timers GLib's unless a
test passes its own.
"""

import asyncio
import logging

from gi.repository import Gio, GLib

from . import remote

log = logging.getLogger(__name__)

SETTING = 'notify-song-change'

# The notification's id: one at a time, each replacing the last.
NOTIFICATION_ID = 'song-changed'

# The app action a click on the notification runs: the window shown and raised.
DEFAULT_ACTION = 'app.show-window'

# How long a new song plays before it is announced: a skip within it announces nothing.
PLAYED_MS = 1000


def new_song(previous, track, previous_restored=False):
    """Whether `track` (a NowPlaying) is another song than `previous`, the item the Player
    held before it. Nothing before it (the first item since launch or since playback ended)
    is no change. Another id is; the same id at another queue index is too (the song queued
    twice in a row), but not after a session restored (MusicKit numbers the queue it is given
    afresh: the restored item, played), nor for a live station (one station, whatever its
    programme)."""
    if track is None or previous is None:
        return False
    if track.id != previous.id:
        return True
    if previous_restored or track.live:
        return False
    return track.index != previous.index


def should_notify(enabled, in_sight, playing, restored):
    """Whether a song that has just played its first second is announced: the setting on,
    the window out of sight, the music playing, and not a session restored."""
    return enabled and not in_sight and playing and not restored


def in_sight(windows):
    """Whether the user can see the app: one of its windows (`get_visible()`, `is_active()`)
    shown and focused."""
    return any(window.get_visible() and window.is_active() for window in windows)


def notification_text(track):
    """The notification's title and body for a NowPlaying: its title and its artist (None
    without one); None for an item with no title, which is not announced."""
    title = (track.title or '').strip()
    if not title:
        return None
    return title, (track.artist or '').strip() or None


async def artwork_icon(url):
    """The cover at `url` as a Gio.BytesIcon, or None: the remote-art cache's file, fetched
    when it is not there yet, read in a thread."""
    if not url:
        return None
    path = await remote.fetch_remote(url)
    if not path:
        return None
    data = await asyncio.to_thread(_read, path)
    return Gio.BytesIcon.new(GLib.Bytes.new(data)) if data else None


def _read(path):
    try:
        with open(path, 'rb') as file:
            return file.read()
    except OSError as error:
        log.debug('song notification: artwork not read: %s', error)
        return None


class SongNotifier:
    """See the module. `app` gives `settings`, `player`, `spawn(coro)`,
    `send_notification(id, notification)`, `withdraw_notification(id)` and
    `window_in_sight()`; `add_timeout(ms, callback)` answers a source id that
    `remove_timeout(id)` removes (GLib's by default); `icon_for(url)` is a coroutine
    answering the cover's Gio.Icon or None (artwork_icon())."""

    def __init__(self, app, add_timeout=None, remove_timeout=None, icon_for=None):
        self._app = app
        self._player = app.player
        self._settings = app.settings
        self._add_timeout = add_timeout or GLib.timeout_add
        self._remove_timeout = remove_timeout or GLib.source_remove
        self._icon_for = icon_for or artwork_icon
        self._handlers = []  # [(source, handler id)] while started
        self._previous = None  # the item the Player held last
        self._previous_restored = False  # whether it was a session restored
        self._candidate = None  # the new song to announce once it has played PLAYED_MS
        self._timer = None  # that wait, while the song plays
        self._shown = False  # a notification is out (not withdrawn since)
        self._task = None  # the notification being made (its cover read)

    @property
    def enabled(self):
        return self._settings.get_boolean(SETTING)

    def start(self):
        player = self._player
        self._handlers = [
            (player, player.connect('notify::track', self._on_track)),
            (player, player.connect('notify::state', self._update)),
            (player, player.connect('notify::restored', self._update)),
            (self._settings, self._settings.connect('changed::' + SETTING,
                                                    self._on_setting)),
        ]
        self._previous = player.track
        self._previous_restored = player.restored

    def stop(self):
        for source, handler in self._handlers:
            source.disconnect(handler)
        self._handlers = []
        self._candidate = None
        self._disarm()
        self.withdraw()

    def withdraw(self):
        """The notification out, if any, taken back; one being made is dropped."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._shown:
            self._shown = False
            self._app.withdraw_notification(NOTIFICATION_ID)

    def _on_setting(self, *_args):
        if not self.enabled:
            self._candidate = None
            self.withdraw()
        self._update()

    def _on_track(self, player, _pspec):
        track = player.track
        if track is None:
            # Playback ended: what follows is a start, not a change; the song named is over.
            self._candidate = None
            self._previous = None
            self.withdraw()
        else:
            restored = player.restored
            if restored:
                self._candidate = None
            elif new_song(self._previous, track, self._previous_restored):
                self._candidate = track
                self._disarm()  # its own second, from now
            elif self._candidate is not None and self._candidate.same_as(track):
                self._candidate = track  # the same item again, newer words
            self._previous = track
            self._previous_restored = restored
        self._update()

    def _waiting(self):
        """Whether the candidate is the item playing, its second to count."""
        player = self._player
        candidate = self._candidate
        return (candidate is not None and self.enabled and not player.restored
                and player.track is not None and candidate.same_as(player.track)
                and player.resting == 'playing')

    def _update(self, *_args):
        """The candidate's second counts while it plays, and starts again if it stops."""
        if self._waiting():
            if self._timer is None:
                self._timer = self._add_timeout(PLAYED_MS, self._on_played)
        else:
            self._disarm()

    def _disarm(self):
        if self._timer is not None:
            self._remove_timeout(self._timer)
            self._timer = None

    def _on_played(self):
        self._timer = None
        if not self._waiting():
            return GLib.SOURCE_REMOVE
        track, self._candidate = self._candidate, None
        player = self._player
        if should_notify(self.enabled, self._app.window_in_sight(),
                         player.resting == 'playing', player.restored):
            if self._task is not None and not self._task.done():
                self._task.cancel()
            self._task = self._app.spawn(self._send(track))
        return GLib.SOURCE_REMOVE

    async def _send(self, track):
        text = notification_text(track)
        if text is None:
            return
        try:
            icon = await self._icon_for(track.artwork_url)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('song notification: the cover could not be read')
            icon = None
        # The cover took a moment: the song may have gone, or the user come back.
        current = self._player.track
        if (current is None or not current.same_as(track) or not self.enabled
                or self._app.window_in_sight()):
            return
        title, body = text
        notification = Gio.Notification.new(title)
        if body:
            notification.set_body(body)
        if icon is not None:
            notification.set_icon(icon)
        notification.set_default_action(DEFAULT_ACTION)
        self._app.send_notification(NOTIFICATION_ID, notification)
        self._shown = True
