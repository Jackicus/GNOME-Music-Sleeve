# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The notification when the song changes (src/song_notification.py): the decision as pure
functions, and the SongNotifier over a stand-in Player and application, with a fake clock
and the real settings on the memory backend. No display, no bus."""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from gi.repository import Gio, GObject

from applemusic import main, song_notification
from applemusic.player import NowPlaying
from applemusic.song_notification import (
    NOTIFICATION_ID, PLAYED_MS, SongNotifier, in_sight, new_song, notification_text,
    should_notify)

BASE_ID = 'io.github.jackicus.MusicSleeve'


def track(ident='i.demo0001', index=0, title='Harbour Lights', artist='The Invented Band',
          live=False, art='https://example.invalid/image/1/256x256bb.jpg'):
    """An invented item, as the bridge's formatTrack shapes it."""
    return NowPlaying({'id': ident, 'index': index, 'title': title, 'artist': artist,
                       'album': 'Fictional Album', 'artUrl': art, 'isLive': live})


class FakePlayer(GObject.Object):
    """What the notifier reads of the Player: `track`, `state` (`resting`), `restored`."""

    track = GObject.Property(type=NowPlaying, default=None)
    state = GObject.Property(type=str, default='none')
    restored = GObject.Property(type=bool, default=False)

    @property
    def resting(self):
        return self.state


class Clock:
    """add_timeout/remove_timeout that run nothing until fire() is called."""

    def __init__(self):
        self.timers = {}
        self.next_id = 1

    def add(self, ms, callback):
        source = self.next_id
        self.next_id += 1
        self.timers[source] = (ms, callback)
        return source

    def remove(self, source):
        del self.timers[source]

    def fire(self):
        for source, (_ms, callback) in list(self.timers.items()):
            del self.timers[source]
            callback()


class FakeApp:
    """What the notifier asks of the Application."""

    def __init__(self, settings):
        self.settings = settings
        self.player = FakePlayer()
        self.in_sight = False
        self.sent = []  # [(id, notification)]
        self.withdrawn = []
        self.tasks = []

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    def send_notification(self, ident, notification):
        self.sent.append((ident, notification))

    def withdraw_notification(self, ident):
        self.withdrawn.append(ident)

    def window_in_sight(self):
        return self.in_sight


class Window:
    def __init__(self, visible, active):
        self.visible, self.active = visible, active

    def get_visible(self):
        return self.visible

    def is_active(self):
        return self.active


class DecisionTest(unittest.TestCase):
    def test_another_song_is_new(self):
        self.assertTrue(new_song(track('a'), track('b')))

    def test_the_first_item_is_no_change(self):
        self.assertFalse(new_song(None, track('a')))
        self.assertFalse(new_song(track('a'), None))

    def test_the_same_item_again_is_not_new(self):
        self.assertFalse(new_song(track('a', 3), track('a', 3)))  # repeat one, newer words

    def test_the_same_song_queued_twice_is_new(self):
        self.assertTrue(new_song(track('a', 3), track('a', 4)))

    def test_the_restored_item_played_is_not_new(self):
        self.assertFalse(new_song(track('a', 7), track('a', 0), previous_restored=True))
        self.assertTrue(new_song(track('a', 7), track('b', 1), previous_restored=True))

    def test_a_live_stations_programme_is_not_new(self):
        before = track('ra.live', 0, title='Morning Show', live=True)
        self.assertFalse(new_song(before, track('ra.live', 0, title='Evening Show', live=True)))
        self.assertFalse(new_song(before, track('ra.live', 1, title='Evening Show', live=True)))
        self.assertTrue(new_song(before, track('ra.other', 0, live=True)))

    def test_should_notify(self):
        self.assertTrue(should_notify(True, False, True, False))
        self.assertFalse(should_notify(False, False, True, False))  # the setting off
        self.assertFalse(should_notify(True, True, True, False))  # the user is looking
        self.assertFalse(should_notify(True, False, False, False))  # not playing
        self.assertFalse(should_notify(True, False, True, True))  # the session restored

    def test_in_sight(self):
        self.assertFalse(in_sight([]))
        self.assertFalse(in_sight([Window(visible=False, active=False)]))  # in the background
        self.assertFalse(in_sight([Window(visible=True, active=False)]))  # another app's turn
        self.assertTrue(in_sight([Window(visible=False, active=False),
                                  Window(visible=True, active=True)]))  # Preferences

    def test_the_text_is_the_title_and_the_artist(self):
        self.assertEqual(notification_text(track()), ('Harbour Lights', 'The Invented Band'))
        self.assertEqual(notification_text(track(artist='')), ('Harbour Lights', None))
        self.assertIsNone(notification_text(track(title='  ')))


class NotifierTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        settings = Gio.Settings.new(BASE_ID)
        settings.set_boolean(song_notification.SETTING, True)
        self.addCleanup(settings.reset, song_notification.SETTING)
        self.app = FakeApp(settings)
        self.player = self.app.player
        self.clock = Clock()
        self.icons = []  # the artwork URLs asked
        self.notifier = SongNotifier(self.app, add_timeout=self.clock.add,
                                     remove_timeout=self.clock.remove, icon_for=self.icon_for)
        self.notifier.start()
        self.addCleanup(self.notifier.stop)

    async def icon_for(self, url):
        self.icons.append(url)
        return Gio.ThemedIcon.new('audio-x-generic-symbolic')

    def play(self, item):
        """A new item, playing, as MusicKit reports it: the item, then its state."""
        self.player.track = item
        self.player.state = 'playing'

    async def settle(self):
        """The second up, and the notification made."""
        self.clock.fire()
        await asyncio.gather(*self.app.tasks)

    async def started_and_changed(self):
        """The first song (announced never), then a second one, its second waited."""
        self.play(track('a'))
        await self.settle()
        self.play(track('b', 1, title='Second Song'))
        self.assertEqual([ms for ms, _ in self.clock.timers.values()], [PLAYED_MS])

    async def test_a_change_out_of_sight_is_announced_once_its_second_is_up(self):
        await self.started_and_changed()
        self.assertEqual(self.app.sent, [])
        with mock.patch.object(song_notification.Gio, 'Notification') as notification:
            await self.settle()
        self.assertEqual([ident for ident, _ in self.app.sent], [NOTIFICATION_ID])
        notification.new.assert_called_once_with('Second Song')
        made = notification.new.return_value
        made.set_body.assert_called_once_with('The Invented Band')
        made.set_icon.assert_called_once()
        made.set_default_action.assert_called_once_with('app.show-window')
        self.assertEqual(self.icons, ['https://example.invalid/image/1/256x256bb.jpg'])

    async def test_the_real_notification_is_made(self):
        await self.started_and_changed()
        await self.settle()
        ((ident, notification),) = self.app.sent
        self.assertEqual(ident, NOTIFICATION_ID)
        self.assertIsInstance(notification, Gio.Notification)

    async def test_the_first_song_is_not_announced(self):
        self.play(track('a'))
        await self.settle()
        self.assertEqual(self.app.sent, [])

    async def test_quick_skips_announce_the_song_that_stays(self):
        self.play(track('a'))
        await self.settle()
        for index, ident in enumerate(('b', 'c', 'd'), 1):
            self.play(track(ident, index, title=ident.upper()))
            self.assertEqual(len(self.clock.timers), 1)  # one second, counted from the last
        with mock.patch.object(song_notification.Gio, 'Notification') as notification:
            await self.settle()
        notification.new.assert_called_once_with('D')

    async def test_a_song_that_has_not_played_yet_waits(self):
        self.play(track('a'))
        await self.settle()
        self.player.track = track('b', 1)
        self.player.state = 'loading'
        self.assertEqual(self.clock.timers, {})
        self.player.state = 'playing'
        await self.settle()
        self.assertEqual(len(self.app.sent), 1)

    async def test_a_pause_within_the_second_counts_again(self):
        await self.started_and_changed()
        self.player.state = 'paused'
        self.assertEqual(self.clock.timers, {})
        self.player.state = 'playing'
        self.assertEqual(len(self.clock.timers), 1)

    async def test_nothing_while_the_window_is_in_sight(self):
        await self.started_and_changed()
        self.app.in_sight = True
        await self.settle()
        self.assertEqual(self.app.sent, [])
        self.app.in_sight = False  # leaving the window later announces nothing of it
        self.player.state = 'paused'
        self.player.state = 'playing'
        await self.settle()
        self.assertEqual(self.app.sent, [])

    async def test_nothing_with_the_setting_off(self):
        self.app.settings.set_boolean(song_notification.SETTING, False)
        self.play(track('a'))
        self.play(track('b', 1))
        self.assertEqual(self.clock.timers, {})
        await self.settle()
        self.assertEqual(self.app.sent, [])

    async def test_the_restored_session_and_its_play_are_not_announced(self):
        self.player.restored = True
        self.player.track = track('a', 4)
        self.player.state = 'paused'
        self.player.restored = False  # Play: MusicKit holds the queue, numbered afresh
        self.play(track('a', 0))
        await self.settle()
        self.assertEqual(self.app.sent, [])
        self.play(track('b', 1))  # the next song is a change
        await self.settle()
        self.assertEqual(len(self.app.sent), 1)

    async def test_a_live_programme_change_is_not_announced(self):
        self.play(track('a'))
        await self.settle()
        self.play(track('ra.live', 1, title='Morning Show', live=True))
        await self.settle()
        self.assertEqual(len(self.app.sent), 1)  # tuning in is a change
        self.play(track('ra.live', 1, title='Evening Show', live=True))
        await self.settle()
        self.assertEqual(len(self.app.sent), 1)

    async def test_a_song_gone_while_its_cover_is_read_is_dropped(self):
        await self.started_and_changed()
        gate = asyncio.Event()

        async def slow_icon(url):
            await gate.wait()
            return None
        self.notifier._icon_for = slow_icon
        self.clock.fire()
        self.player.track = track('c', 2)
        gate.set()
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.app.sent, [])

    async def test_a_cover_that_fails_leaves_the_icon_out(self):
        await self.started_and_changed()

        async def broken_icon(url):
            raise OSError('gone')
        self.notifier._icon_for = broken_icon
        with mock.patch.object(song_notification.Gio, 'Notification') as notification, \
                self.assertLogs('applemusic.song_notification', 'ERROR'):
            await self.settle()
        notification.new.return_value.set_icon.assert_not_called()
        self.assertEqual(len(self.app.sent), 1)

    async def test_withdrawn_when_playback_ends_and_when_turned_off(self):
        await self.started_and_changed()
        await self.settle()
        self.player.track = None
        self.assertEqual(self.app.withdrawn, [NOTIFICATION_ID])
        self.play(track('a'))  # a start again: no change to announce
        await self.settle()
        self.play(track('b', 1))
        await self.settle()
        self.assertEqual(len(self.app.sent), 2)
        self.app.settings.set_boolean(song_notification.SETTING, False)
        self.assertEqual(self.app.withdrawn, [NOTIFICATION_ID] * 2)

    async def test_stop_withdraws_and_follows_nothing(self):
        await self.started_and_changed()
        await self.settle()
        self.notifier.stop()
        self.assertEqual(self.app.withdrawn, [NOTIFICATION_ID])
        self.play(track('c', 2))
        self.assertEqual(self.clock.timers, {})

    async def test_nothing_shown_is_not_withdrawn(self):
        self.play(track('a'))
        self.player.track = None
        self.notifier.stop()
        self.assertEqual(self.app.withdrawn, [])


class ArtworkIconTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_cached_cover_becomes_a_bytes_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'cover.jpg')
            with open(path, 'wb') as file:
                file.write(b'\xff\xd8 an invented cover')

            async def fetch(url):
                return path
            with mock.patch.object(song_notification.remote, 'fetch_remote', fetch):
                icon = await song_notification.artwork_icon('https://example.invalid/a.jpg')
        self.assertIsInstance(icon, Gio.BytesIcon)
        self.assertEqual(icon.get_bytes().get_data(), b'\xff\xd8 an invented cover')

    async def test_no_url_or_no_file_is_no_icon(self):
        self.assertIsNone(await song_notification.artwork_icon(None))

        async def fetch(url):
            return None
        with mock.patch.object(song_notification.remote, 'fetch_remote', fetch):
            self.assertIsNone(await song_notification.artwork_icon('https://example.invalid/'))


class ApplicationTest(unittest.TestCase):
    def test_the_ids_differ_from_the_background_toasts(self):
        self.assertNotEqual(NOTIFICATION_ID, main.BACKGROUND_NOTIFICATION)

    def test_the_default_action_is_the_applications(self):
        app = main.Application('0.9.0', f'{BASE_ID}.Test', BASE_ID, 'default', None)
        self.assertIsNotNone(app.lookup_action(
            song_notification.DEFAULT_ACTION.removeprefix('app.')))


if __name__ == '__main__':
    unittest.main()
