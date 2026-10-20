# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The transport pieces' decisions without a display: the seek slider's guard, the volume
button's coalescer, and the heart and the mode toggles over stand-in buttons and the
test_player fakes. No GTK widgets are built (importing the module needs the typelib only)."""

import asyncio
import unittest

from gi.repository import GObject

from tests import ROOT, SRC  # noqa: F401  ROOT registers src/ as applemusic
from tests.test_player import TRACK, make_player

from applemusic.backend.errors import EngineError
from applemusic.widgets.transport import (Coalescer, SeekGuard, VolumeControl, volume_step,
                                          volume_text)


class SeekGuardTest(unittest.TestCase):
    def test_nothing_incoming_counts_while_a_seek_waits_to_be_sent(self):
        """A click 1.5 s ahead of the play head: the tick that arrives during the settle
        must not release the target (it used to, and the seek was never sent)."""
        guard = SeekGuard(hold=1.5, tolerance=2.0)
        self.assertTrue(guard.accept(60.0, now=0.0))  # no seek about
        guard.moved(61.5)
        self.assertFalse(guard.accept(60.25, now=0.1))
        self.assertEqual(guard.target, 61.5)
        guard.moved(62.0)  # the drag goes on
        self.assertFalse(guard.accept(60.5, now=0.2))
        self.assertEqual(guard.target, 62.0)

    def test_a_position_near_the_target_releases_the_guard_once_sent(self):
        guard = SeekGuard(hold=1.5, tolerance=2.0)
        guard.moved(120.0)
        guard.sent(now=1.0)
        self.assertFalse(guard.accept(60.5, now=1.1))  # stale, from before the seek
        self.assertIsNotNone(guard.target)
        self.assertTrue(guard.accept(121.0, now=1.3))  # the seek has taken
        self.assertIsNone(guard.target)
        self.assertTrue(guard.accept(60.0, now=1.4))  # anything again

    def test_the_hold_running_out_releases_the_guard(self):
        guard = SeekGuard(hold=1.5, tolerance=2.0)
        guard.moved(120.0)
        guard.sent(now=1.0)
        self.assertFalse(guard.accept(60.0, now=2.4))
        self.assertTrue(guard.accept(60.0, now=2.5))
        self.assertIsNone(guard.target)

    def test_a_failure_releases_the_guard(self):
        guard = SeekGuard()
        guard.moved(120.0)
        guard.sent(now=1.0)
        guard.release()
        self.assertIsNone(guard.target)
        self.assertTrue(guard.accept(60.0, now=1.0))


class CoalescerTest(unittest.TestCase):
    def test_rapid_moves_send_at_most_two_commands(self):
        coalescer = Coalescer()
        sent = []
        for value in (0.1, 0.2, 0.3, 0.4):
            to_send = coalescer.moved(value)
            if to_send is not None:
                sent.append(to_send)
        self.assertEqual(sent, [0.1])
        self.assertEqual(coalescer.target, 0.4)
        self.assertEqual(coalescer.done(), 0.4)  # the first returned: the last value goes
        self.assertEqual(coalescer.target, 0.4)
        self.assertIsNone(coalescer.done())  # and then nothing waits
        self.assertIsNone(coalescer.target)
        self.assertEqual(coalescer.moved(0.5), 0.5)


class Button:
    """A Gtk.ToggleButton's surface the heart and the mode toggles use."""

    def __init__(self):
        self.active = False
        self.icon = None
        self.tooltip = None
        self.sensitive = True
        self.description = None  # the accessible description, None when reset
        self._handlers = []

    def update_property(self, properties, values):
        from gi.repository import Gtk

        for prop, value in zip(properties, values, strict=True):
            if prop == Gtk.AccessibleProperty.DESCRIPTION:
                self.description = value

    def reset_property(self, prop):
        from gi.repository import Gtk

        if prop == Gtk.AccessibleProperty.DESCRIPTION:
            self.description = None

    def connect(self, _signal, handler):
        self._handlers.append(handler)

    def set_active(self, active):
        if active != self.active:
            self.active = active
            for handler in self._handlers:
                handler(self)

    def get_active(self):
        return self.active

    def set_icon_name(self, name):
        self.icon = name

    def set_tooltip_text(self, text):
        self.tooltip = text

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive


class RatingEngine(GObject.Object):
    """An engine whose rating commands are recorded and gated: `rating` answers through
    `rated` what `ratings` holds (1 loved, -1 Suggest Less, 0 neither), `love`/`unlove`
    wait for `gate` and then raise when `fail` says so."""

    __gsignals__ = {
        'event': (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
    }

    state = GObject.Property(type=str, default='up')
    authorized = GObject.Property(type=bool, default=True)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.ratings = {}
        self.gate = asyncio.Event()
        self.read_gate = None  # an Event a rating() read waits for, when set
        self.fail = None

    async def rating(self, kind, item_id):
        self.calls.append(('rating', kind, item_id))
        if self.read_gate is not None:
            await self.read_gate.wait()
        value = self.ratings.get(item_id, 0)
        self.emit('rated', kind, item_id, value)
        return value

    async def love(self, kind, item_id):
        return await self._write('love', kind, item_id, 1)

    async def unlove(self, kind, item_id):
        return await self._write('unlove', kind, item_id, 0)

    async def _write(self, name, kind, item_id, value):
        self.calls.append((name, kind, item_id))
        await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        self.ratings[item_id] = value
        self.emit('rated', kind, item_id, value)


def make_heart():
    """A HeartControl over a stand-in button, a Player over the test_player fake engine
    (the events) and a RatingEngine (the ratings), the app reporting nothing."""
    from applemusic.widgets.transport import HeartControl

    player, events, app = make_player(state='up')
    engine = RatingEngine()
    app.engine = engine
    button = Button()
    heart = HeartControl(button)
    heart.attach(player, app)
    return heart, button, player, events, engine, app


class HeartTest(unittest.TestCase):
    def test_a_failed_write_reverts_only_the_item_it_was_for(self):
        """Unlove A, skip to B, then A's unlove fails: B's heart is left alone."""
        async def go():
            heart, button, player, events, engine, app = make_heart()
            await app.settle()
            engine.ratings['1000000001'] = 1
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertTrue(button.active)  # A is loved
            button.set_active(False)  # the user unloves A: the write waits at the gate
            await asyncio.sleep(0)
            self.assertEqual(engine.calls[-1], ('unlove', 'song', '1000000001'))
            other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=3)
            events.event('nowPlayingItemDidChange', {'track': other, 'index': 3})
            for _turn in range(5):  # B's rating read answers; A's write still waits
                await asyncio.sleep(0)
            self.assertFalse(button.active)  # B is not loved
            engine.fail = EngineError('timeout', 'slow')
            engine.gate.set()
            await app.settle()
            self.assertFalse(button.active)  # A's failure does not turn B's heart on
            self.assertEqual(len(app.toasts), 1)  # but is reported
        asyncio.run(go())

    def test_a_click_outranks_the_read_started_with_the_item(self):
        """The rating read when the item began answers after the click: the click's value
        stays."""
        async def go():
            heart, button, player, events, engine, app = make_heart()
            await app.settle()
            engine.read_gate = asyncio.Event()
            engine.gate.set()
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await asyncio.sleep(0)
            button.set_active(True)  # loved by the user before the read answered
            await app.settle()
            self.assertTrue(button.active)
            self.assertIn(('love', 'song', '1000000001'), engine.calls)
            engine.ratings['1000000001'] = 0  # what the read would have said
            engine.read_gate.set()
            await app.settle()
            self.assertTrue(button.active)  # the read was cancelled: nothing flipped
        asyncio.run(go())

    def test_suggest_less_empties_the_heart(self):
        """A menu's Suggest Less replaces the favourite (the rating -1): the heart shows
        the song not loved, and a read that answers -1 does too."""
        async def go():
            heart, button, player, events, engine, app = make_heart()
            await app.settle()
            engine.ratings['1000000001'] = 1
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertTrue(button.active)
            engine.emit('rated', 'song', '1000000001', -1)
            self.assertFalse(button.active)
            self.assertEqual(button.icon, 'heart-outline-symbolic')
            other = dict(TRACK, id='i.demo0002', catalogId='1000000002', index=3)
            engine.ratings['1000000002'] = -1
            events.event('nowPlayingItemDidChange', {'track': other, 'index': 3})
            await app.settle()
            self.assertFalse(button.active)
        asyncio.run(go())

    def test_the_same_song_again_is_not_read_again(self):
        async def go():
            heart, button, player, events, engine, app = make_heart()
            await app.settle()
            engine.ratings['1000000001'] = 1
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            reads = engine.calls.count(('rating', 'song', '1000000001'))
            self.assertEqual(reads, 1)
            # The same song re-created (its queue index changed): no reset, no read.
            events.event('nowPlayingItemDidChange', {'track': dict(TRACK, index=5), 'index': 5})
            await app.settle()
            self.assertTrue(button.active)
            self.assertEqual(engine.calls.count(('rating', 'song', '1000000001')), 1)
            # A fresh engine: read again.
            engine.state = 'down'
            engine.state = 'up'
            await app.settle()
            self.assertEqual(engine.calls.count(('rating', 'song', '1000000001')), 2)
        asyncio.run(go())

    def test_a_lazy_heart_reads_only_when_caught_up(self):
        """The full-screen player's heart reads nothing as the item changes; it shows the
        answers another heart's read brings, and reads on catch_up() only an item nothing
        has answered for."""
        async def go():
            from applemusic.widgets.transport import HeartControl

            _heart, _button, _player, events, engine, app = make_heart()  # the bar's
            lazy_button = Button()
            lazy = HeartControl(lazy_button, lazy=True)
            lazy.attach(_player, app)
            engine.ratings['1000000001'] = 1
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertEqual(engine.calls.count(('rating', 'song', '1000000001')), 1)
            self.assertTrue(lazy_button.active)   # the bar's answer
            lazy.catch_up()
            await app.settle()
            self.assertEqual(engine.calls.count(('rating', 'song', '1000000001')), 1)
            # Alone (no other heart reading): an item read only once it is caught up.
            player, events, app = make_player(state='up')
            app.engine = RatingEngine()
            app.engine.ratings['1000000001'] = 1
            alone_button = Button()
            alone = HeartControl(alone_button, lazy=True)
            alone.attach(player, app)
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertFalse(alone_button.active)
            self.assertEqual(app.engine.calls, [])
            alone.catch_up()
            await app.settle()
            self.assertEqual(app.engine.calls, [('rating', 'song', '1000000001')])
            self.assertTrue(alone_button.active)
        asyncio.run(go())

    def test_targets_by_kind(self):
        heart, button, player, events, engine, app = make_heart()
        self.assertIsNone(heart.target())
        events.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, type='library-songs'), 'index': 2})
        self.assertEqual(heart.target(), ('song', '1000000001'))
        events.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, id='i.v1', catalogId='555', type='music-videos',
                                    index=3), 'index': 3})
        self.assertEqual(heart.target(), ('video', '555'))
        self.assertTrue(button.sensitive)
        events.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, id='ra.1', catalogId=None, type='stations',
                                    index=0), 'index': 0})
        self.assertIsNone(heart.target())  # a station cannot be loved
        self.assertFalse(button.sensitive)
        events.event('nowPlayingItemDidChange',
                     {'track': dict(TRACK, id='i.x', catalogId=None, type='', index=1),
                      'index': 1})
        self.assertIsNone(heart.target())  # nor an item of no known kind


class QueueSliceTest(unittest.TestCase):
    def test_the_slice_starts_at_the_entry_playing(self):
        from applemusic.widgets.queue import slice_offset

        self.assertEqual(slice_offset(4), 4)
        self.assertEqual(slice_offset(0), 0)
        self.assertEqual(slice_offset(-1), 0)  # nothing playing: the whole queue
        # A row activated at slice position 2 while entry 4 plays is the queue's entry 6.
        self.assertEqual(2 + slice_offset(4), 6)


class ModeControlTest(unittest.TestCase):
    def test_the_repeat_cycle_is_put_back_on_a_failure(self):
        from applemusic.widgets.transport import ModeControl

        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            shuffle, repeat = Button(), Button()
            modes = ModeControl(shuffle, repeat)
            modes.attach(player, app)
            self.assertEqual(repeat.icon, 'media-playlist-repeat-symbolic')
            repeat.set_active(True)  # a click: none → one, shown at once
            self.assertEqual(repeat.icon, 'media-playlist-repeat-song-symbolic')
            await app.settle()
            self.assertEqual(engine.calls[-1], ('repeat', 'one'))
            engine.event('repeatModeDidChange', {'repeat': 'one'})
            engine.fail = EngineError('engine-down', 'gone')
            repeat.set_active(False)  # one → all asked for, shown, then refused
            self.assertEqual(repeat.icon, 'media-playlist-repeat-symbolic')
            self.assertTrue(repeat.active)
            await app.settle()
            self.assertEqual(repeat.icon, 'media-playlist-repeat-song-symbolic')  # back to one
            self.assertTrue(repeat.active)
            self.assertEqual(len(app.toasts), 1)
        asyncio.run(go())


class ModeSensitivityTest(unittest.TestCase):
    def test_the_mode_toggles_are_off_for_a_live_station(self):
        """#441: Shuffle and Repeat insensitive while a live station plays (MusicKit's
        modes would only change what plays after it), and with nothing playing; a song
        makes them sensitive again, as far as MusicKit allows each."""
        from applemusic.widgets.transport import ModeControl
        from tests.test_player import EVERYTHING, live_playing

        player, engine, app = make_player()
        shuffle, repeat = Button(), Button()
        ModeControl(shuffle, repeat).attach(player, app)
        self.assertEqual((shuffle.sensitive, repeat.sensitive), (False, False))  # no item
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertEqual((shuffle.sensitive, repeat.sensitive), (True, True))
        live_playing(engine)
        self.assertEqual((shuffle.sensitive, repeat.sensitive), (False, False))
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2,
                                                 'capabilities': dict(
                                                     EVERYTHING, canSetRepeatMode=False)})
        self.assertEqual((shuffle.sensitive, repeat.sensitive), (True, False))


class Adjustment:
    """A Gtk.Adjustment's surface the volume button uses (0 to 1)."""

    def __init__(self, value=1.0):
        self.value = value
        self._handlers = []

    def connect(self, _signal, handler):
        self._handlers.append(handler)

    def get_value(self):
        return self.value

    def set_value(self, value):
        value = min(1.0, max(0.0, value))
        if value != self.value:
            self.value = value
            for handler in self._handlers:
                handler(self)


class ScaleButton:
    """A Gtk.ScaleButton's surface over its Adjustment: value-changed as the level moves."""

    def __init__(self, adjustment):
        self.adjustment = adjustment
        self._handlers = []
        adjustment.connect('value-changed', self._changed)

    def connect(self, _signal, handler):
        self._handlers.append(handler)

    def _changed(self, adjustment):
        for handler in self._handlers:
            handler(self, adjustment.get_value())

    def set_value(self, value):
        self.adjustment.set_value(value)

    def update_property(self, _properties, _values):
        pass

    def get_popup(self):
        return None


class VolumeStepTest(unittest.TestCase):
    """Ctrl+Up and Ctrl+Down: the volume a step (VOLUME_STEP) up or down."""

    def test_the_steps(self):
        self.assertEqual(volume_step(0.7, 1), 0.8)
        self.assertEqual(volume_step(0.7, -1), 0.6)
        self.assertEqual(volume_step(0.73, 1), 0.8)  # to the next step that way
        self.assertEqual(volume_step(0.73, -1), 0.7)
        self.assertEqual(volume_step(0.7000001, 1), 0.8)  # a level that is a step, near enough
        self.assertEqual(volume_step(0.6999999, -1), 0.6)
        self.assertEqual(volume_step(0.3, 1), 0.4)  # 0.3 / 0.1 is 2.9999…
        self.assertEqual(volume_step(1.0, 1), 1.0)  # within 0 and 1
        self.assertEqual(volume_step(0.95, 1), 1.0)
        self.assertEqual(volume_step(0.0, -1), 0.0)
        self.assertEqual(volume_step(0.04, -1), 0.0)
        level = 0.0
        for _ in range(10):
            level = volume_step(level, 1)
        self.assertEqual(level, 1.0)

    def test_the_announcement(self):
        self.assertEqual(volume_text(0.8), 'Volume 80%')
        self.assertEqual(volume_text(0.0), 'Volume 0%')

    def test_a_run_of_presses_adds_up_and_is_sent(self):
        async def go():
            player, engine, app = make_player(state='up')
            await app.settle()
            adjustment = Adjustment(player.volume)
            control = VolumeControl(ScaleButton(adjustment), adjustment)
            control.attach(player, app)
            self.assertEqual(control.step(-1), 0.9)
            self.assertEqual(control.step(-1), 0.8)  # from the level shown, not MusicKit's yet
            self.assertEqual(adjustment.value, 0.8)
            await app.settle()
            self.assertEqual([call for call in engine.calls if call[0] == 'volume'],
                             [('volume', 0.9), ('volume', 0.8)])
            self.assertEqual(control.step(1), 0.9)
        asyncio.run(go())


class Widget:
    """The surface SeekControl uses of a label, a scale, an adjustment and a stack."""

    def __init__(self, parent=None):
        self.visible = True
        self.sensitive = True
        self.label = None
        self.shown = None  # a stack's visible child
        self.parent = parent

    def connect(self, *_args):
        pass

    def set_visible(self, visible):
        self.visible = visible

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive

    def set_label(self, label):
        self.label = label

    def set_upper(self, _value):
        pass

    def set_value(self, _value):
        pass

    def update_property(self, *_args):
        pass

    def get_parent(self):
        return self.parent

    def set_visible_child(self, child):
        self.shown = child


class SeekLiveTest(unittest.TestCase):
    """A live station (#343): the LIVE badge in the slider's place, no times; a song
    shows the slider again, insensitive while MusicKit allows no seek."""

    def test_the_badge_takes_the_sliders_place(self):
        from applemusic.widgets.transport import SeekControl
        from tests.test_player import LIVE, NOTHING

        stack = Widget()
        scale, live, elapsed, remaining = Widget(stack), Widget(stack), Widget(), Widget()
        seek = SeekControl(scale, Widget(), elapsed, remaining, live)
        player, engine, app = make_player()
        seek.attach(player, app)
        self.assertIs(stack.shown, scale)
        engine.event('nowPlayingItemDidChange', {'track': LIVE, 'index': 0,
                                                 'capabilities': NOTHING})
        self.assertIs(stack.shown, live)
        self.assertEqual((elapsed.visible, remaining.visible, scale.sensitive),
                         (False, False, False))
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertIs(stack.shown, scale)
        self.assertEqual((elapsed.visible, remaining.visible, scale.sensitive),
                         (True, True, True))
        engine.event('capabilitiesChanged', {'capabilities': {'canSeek': False}})
        self.assertFalse(scale.sensitive)
        # The bar's compact layout hides the times for good, live or not.
        seek.set_times_shown(False)
        self.assertEqual((elapsed.visible, remaining.visible), (False, False))
        engine.event('nowPlayingItemDidChange', {'track': LIVE, 'index': 0})
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertEqual((elapsed.visible, remaining.visible), (False, False))
        seek.set_times_shown(True)
        self.assertEqual((elapsed.visible, remaining.visible), (True, True))


class PlayButtonTest(unittest.TestCase):
    def test_the_icons_are_the_bundled_ones(self):
        """Play and Pause draw the app's own icons: an icon theme's 24 px
        media-playback-start (Papirus's) came out small and off-centre in the sheet."""
        from applemusic.widgets.transport import PlayButton

        class Player:
            active = False
            pending = False
            live = False

            def connect(self, *_args):
                pass

        bundled = {path.stem for path in (SRC / 'icons').glob('*.svg')}
        button = Button()
        player = Player()
        play = PlayButton(button)
        play.attach(player)
        for active, live, tooltip in ((False, False, 'Play'), (True, False, 'Pause'),
                                      (True, True, 'Stop'), (False, True, 'Play')):
            with self.subTest(active=active, live=live):
                player.active, player.live = active, live
                play.update()
                self.assertIn(button.icon, bundled)
                self.assertEqual(button.tooltip, tooltip)

    def test_a_live_station_is_described_on_the_button(self):
        """#455: the LIVE badge is a label no focus reaches; the play button, which the
        focus does reach, is described as "Live Radio" while the item is live, playing or
        stopped, and not otherwise."""
        from applemusic.widgets.transport import PlayButton
        from tests.test_player import live_playing

        player, engine, app = make_player()
        button = Button()
        PlayButton(button).attach(player)
        self.assertIsNone(button.description)
        live_playing(engine)
        self.assertEqual((button.tooltip, button.description), ('Stop', 'Live Radio'))
        engine.event('playbackStateDidChange', {'state': 'paused'})
        self.assertEqual((button.tooltip, button.description), ('Play', 'Live Radio'))
        engine.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
        self.assertIsNone(button.description)


class DetachTest(unittest.TestCase):
    def test_a_detached_piece_follows_nothing(self):
        """The mini player's pieces go before the Player: detach() disconnects every
        handler attach() made, on the Player and on the engine."""
        from applemusic.widgets.transport import ModeControl, PlayButton

        async def go():
            heart, button, player, events, engine, app = make_heart()
            play, shuffle, repeat = Button(), Button(), Button()
            pieces = [PlayButton(play), ModeControl(shuffle, repeat), heart]
            pieces[0].attach(player)
            pieces[1].attach(player, app)
            events.event('playbackStateDidChange', {'state': 'playing'})
            events.event('nowPlayingItemDidChange', {'track': TRACK, 'index': 2})
            await app.settle()
            self.assertEqual(play.tooltip, 'Pause')
            for piece in pieces:
                piece.detach()
            events.event('playbackStateDidChange', {'state': 'paused'})
            events.event('shuffleModeDidChange', {'shuffle': True})
            engine.emit('rated', 'song', TRACK['catalogId'], 1)
            await app.settle()
            self.assertEqual(play.tooltip, 'Pause')  # not followed any more
            self.assertFalse(shuffle.active)
            self.assertFalse(button.active)
            pieces[0].detach()  # twice is nothing
        asyncio.run(go())

if __name__ == '__main__':
    unittest.main()
