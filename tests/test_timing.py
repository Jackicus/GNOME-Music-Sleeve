# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The startup marks (src/timing.py) that scripts/bench.py reads, with a stand-in window and
frame clock: each mark is kept the first time only, a painted mark waits for the end of the
next frame, and the process's start is read from /proc or falls back to now.
"""

import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from applemusic import timing


class Clock:
    """A frame clock: `after-paint` handlers, connected and disconnected, run by paint()."""

    def __init__(self):
        self.handlers = {}
        self._next = 0

    def connect(self, signal, callback):
        assert signal == 'after-paint', signal
        self._next += 1
        self.handlers[self._next] = callback
        return self._next

    def disconnect(self, handler):
        del self.handlers[handler]

    def paint(self):
        for callback in list(self.handlers.values()):
            callback(self)


class Window:
    def __init__(self, clock):
        self.clock = clock

    def get_frame_clock(self):
        return self.clock


class Now:
    """GLib.get_monotonic_time(), stepped by the test."""

    def __init__(self, value=1_000_000):
        self.value = value

    def __call__(self):
        return self.value


class StartupMarksTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.window = Window(self.clock)
        self.now = Now()
        patcher = mock.patch.object(timing.GLib, 'get_monotonic_time', self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.marks = timing.StartupMarks(lambda: self.window)

    def test_a_mark_is_kept_the_first_time_only(self):
        self.marks.mark('startup')
        self.now.value += 500
        self.marks.mark('startup')
        self.marks.mark('activate')
        self.assertEqual(self.marks.marks, {'startup': 1_000_000, 'activate': 1_000_500})

    def test_a_painted_mark_waits_for_the_end_of_the_next_frame(self):
        self.marks.mark('albums-bound', painted='albums-painted')
        self.assertEqual(list(self.marks.marks), ['albums-bound'])
        self.now.value += 16_000
        self.clock.paint()
        self.assertEqual(self.marks.marks['albums-painted'], 1_016_000)
        self.assertEqual(self.clock.handlers, {})  # one frame only
        self.now.value += 16_000
        self.clock.paint()
        self.assertEqual(self.marks.marks['albums-painted'], 1_016_000)

    def test_a_painted_mark_again_is_not_waited_for(self):
        self.marks.mark('albums-bound', painted='albums-painted')
        self.marks.mark('albums-bound', painted='albums-painted')
        self.assertEqual(len(self.clock.handlers), 1)

    def test_no_window_or_no_clock_marks_nothing_painted(self):
        self.window = None
        self.marks.mark('albums-bound', painted='albums-painted')
        self.window = Window(None)  # not realized: no frame clock
        self.marks.mark_after_paint('first-frame')
        self.assertEqual(list(self.marks.marks), ['albums-bound'])

    def test_the_windows_map_marks_it_and_its_first_frame(self):
        self.marks.on_window_mapped(self.window)
        self.assertIn('window-mapped', self.marks.marks)
        self.now.value += 20_000
        self.clock.paint()
        self.assertEqual(self.marks.marks['first-frame'], 1_020_000)
        # Mapped again (the window shown after background playback): nothing new waited for.
        self.marks.on_window_mapped(self.window)
        self.assertEqual(self.clock.handlers, {})

    def test_the_debug_log_says_how_long_after_the_start(self):
        with mock.patch.object(timing, 'PROCESS_START', 400_000), \
                self.assertLogs('applemusic.timing', 'DEBUG') as logs:
            self.marks.mark('startup')
        self.assertEqual(logs.output, ['DEBUG:applemusic.timing:startup: startup at +600 ms'])


class ProcessStartTest(unittest.TestCase):
    def test_before_now_on_linux(self):
        start = timing.process_start()
        self.assertLessEqual(start, timing.GLib.get_monotonic_time())
        self.assertLessEqual(timing.PROCESS_START, timing.GLib.get_monotonic_time())

    def test_read_from_the_stat_files_start_time(self):
        # The 22nd field, after the command's name (which may hold spaces and parentheses),
        # in clock ticks since boot: started 2.5 s after boot, 10 s since boot now, so 7.5 s
        # ago.
        fields = ['S'] + ['0'] * 18 + ['250'] + ['0'] * 5
        stat = '1234 (invented (x) cmd) ' + ' '.join(fields)
        with mock.patch('builtins.open', mock.mock_open(read_data=stat)), \
                mock.patch.object(timing.os, 'sysconf', return_value=100), \
                mock.patch.object(timing.time, 'clock_gettime', return_value=10.0), \
                mock.patch.object(timing.GLib, 'get_monotonic_time', return_value=50_000_000):
            self.assertEqual(timing.process_start(), 50_000_000 - 7_500_000)

    def test_now_when_it_cannot_be_read(self):
        with mock.patch.object(timing.GLib, 'get_monotonic_time', return_value=123), \
                mock.patch('builtins.open', side_effect=OSError('no /proc')):
            self.assertEqual(timing.process_start(), 123)
        with mock.patch.object(timing.GLib, 'get_monotonic_time', return_value=123), \
                mock.patch('builtins.open', mock.mock_open(read_data='1 (short) S 0')):
            self.assertEqual(timing.process_start(), 123)


if __name__ == '__main__':
    unittest.main()
