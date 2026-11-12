# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""scripts/resize_test.py's arithmetic, without a window: the width the sweep asks for at a
moment (wide to narrow and back, so many times, then done), the figures of its frames, what
changed in a frame, and the Python time read from a profile."""

import importlib.util
import sys
import unittest

from tests import ROOT


def load():
    """scripts/resize_test.py, imported by path: scripts/ is not a package. Its window and
    the harness are only reached from main()."""
    if 'resize_test' not in sys.modules:
        path = ROOT / 'scripts' / 'resize_test.py'
        spec = importlib.util.spec_from_file_location('resize_test', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules['resize_test'] = module
        spec.loader.exec_module(module)
    return sys.modules['resize_test']


class SweepWidthTest(unittest.TestCase):

    def test_goes_down_then_back_then_ends(self):
        sweep = load().sweep_width
        # 1400 to 400 at 1000 px/s: a second down, a second back, twice.
        self.assertEqual(sweep(0, 1400, 400, 1000, 2), 1400)
        self.assertEqual(sweep(0.25, 1400, 400, 1000, 2), 1150)
        self.assertEqual(sweep(1.0, 1400, 400, 1000, 2), 400)
        self.assertEqual(sweep(1.5, 1400, 400, 1000, 2), 900)
        self.assertEqual(sweep(2.25, 1400, 400, 1000, 2), 1150)  # the second round
        self.assertIsNone(sweep(4.0, 1400, 400, 1000, 2))
        self.assertIsNone(sweep(9.0, 1400, 400, 1000, 2))

    def test_nothing_to_sweep(self):
        sweep = load().sweep_width
        self.assertIsNone(sweep(0, 400, 400, 1000, 1))
        self.assertIsNone(sweep(0, 1400, 400, 0, 1))


class FiguresTest(unittest.TestCase):

    def test_summarize(self):
        module = load()
        # (work, layout, width, changes): two of five over a 16.7 ms budget.
        frames = [(0.004, 0.002, 900, []), (0.006, 0.003, 880, []), (0.020, 0.015, 640, ['x']),
                  (0.005, 0.002, 620, []), (0.120, 0.100, 600, ['y'])]
        figures = module.summarize(frames, 1 / 60)
        self.assertEqual(figures['frames'], 5)
        self.assertEqual(figures['over'], 2)
        self.assertAlmostEqual(figures['over_share'], 40)
        self.assertAlmostEqual(figures['mean'], 31)
        self.assertAlmostEqual(figures['longest'], 120)
        self.assertAlmostEqual(figures['p90'], 120)
        self.assertAlmostEqual(figures['layout'], 24.4)
        self.assertEqual(module.longest_frames(frames, 2),
                         [(120.0, 600, 100.0), (20.0, 640, 15.0)])

    def test_summarize_nothing(self):
        figures = load().summarize([], 1 / 60)
        self.assertEqual((figures['frames'], figures['mean'], figures['longest'],
                          figures['over_share']), (0, 0, 0, 0))

    def test_percentile_nearest_rank(self):
        percentile = load().percentile
        self.assertEqual(percentile([], 0.9), 0)
        self.assertEqual(percentile(list(range(10)), 0.9), 9)
        self.assertEqual(percentile(list(range(10)), 0.5), 5)
        self.assertEqual(percentile([3], 0.99), 3)


class ChangesTest(unittest.TestCase):

    def test_breakpoints_and_columns(self):
        changes = load().changes
        before = {'window': 'max-width: 900sp', 'AppleMusicGridPage': 4,
                  'AppleMusicSongsPage': ''}
        after = {'window': 'max-width: 640sp', 'AppleMusicGridPage': 3,
                 'AppleMusicSongsPage': ''}
        self.assertEqual(changes(before, after),
                         ['AppleMusicGridPage columns 4>3', 'window: max-width: 640sp'])
        self.assertEqual(changes(after, after), [])
        self.assertEqual(changes({'window': 'max-width: 640sp'}, {'window': ''}),
                         ['window: -max-width: 640sp'])


class PythonTimeTest(unittest.TestCase):

    def test_own_time_ranked_without_the_script(self):
        module = load()

        class Stats:  # pstats.Stats' table: (file, line, name): (cc, nc, tt, ct, callers)
            stats = {
                ('/x/applemusic/widgets/tile.py', 99, '__init__'): (10, 10, 0.003, 0.009, {}),
                ('~', 0, "<method 'connect' of 'gi._gi.GObject' objects>"):
                    (40, 40, 0.001, 0.001, {}),
                ('/x/gi/_gtktemplate.py', 161, 'init_template'): (10, 10, 0.006, 0.006, {}),
                (module.__file__, 300, 'tick'): (99, 99, 0.5, 0.5, {}),
            }

        seconds, ranked = module.python_time(Stats())
        self.assertAlmostEqual(seconds, 0.010)
        self.assertEqual([where for _own, _calls, where in ranked],
                         ['_gtktemplate.py:161(init_template)', 'tile.py:99(__init__)',
                          "<method 'connect' of 'gi._gi.GObject' objects>"])


if __name__ == '__main__':
    unittest.main()
