# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""scripts/demo_stamp.py: a demo library is current only while it carries the stamp of the
sources and options that would make it now, so an out-of-date build/demo is written again."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT

SCRIPT = ROOT / 'scripts' / 'demo_stamp.py'


def load():
    spec = importlib.util.spec_from_file_location('demo_stamp', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DemoStampTest(unittest.TestCase):
    def setUp(self):
        self.stamp = load()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        self.sources = [os.path.join(self.dir, name) for name in ('script.py', 'normalize.py')]
        for path in self.sources:
            with open(path, 'w', encoding='utf-8') as file:
                file.write('# version one\n')
        self.out = os.path.join(self.dir, 'demo')
        os.mkdir(self.out)

    def library(self):
        with open(os.path.join(self.out, 'library.json'), 'w', encoding='utf-8') as file:
            file.write('{}')

    def test_a_stamped_library_is_current(self):
        self.library()
        self.stamp.write(self.out, sources=self.sources)
        self.assertTrue(self.stamp.current(self.out, sources=self.sources))

    def test_without_a_stamp_it_is_out_of_date(self):
        # A library from before the stamp, or a run that stopped before its end.
        self.library()
        self.assertFalse(self.stamp.current(self.out, sources=self.sources))

    def test_without_a_library_it_is_out_of_date(self):
        self.stamp.write(self.out, sources=self.sources)
        self.assertFalse(self.stamp.current(self.out, sources=self.sources))

    def test_a_changed_source_makes_it_out_of_date(self):
        self.library()
        self.stamp.write(self.out, sources=self.sources)
        with open(self.sources[1], 'a', encoding='utf-8') as file:
            file.write('# version two\n')
        self.assertFalse(self.stamp.current(self.out, sources=self.sources))

    def test_other_options_make_another_library(self):
        self.library()
        self.stamp.write(self.out, {'albums': 3000}, sources=self.sources)
        self.assertFalse(self.stamp.current(self.out, sources=self.sources))
        self.assertTrue(self.stamp.current(self.out, {'albums': 3000}, sources=self.sources))
        self.assertEqual(self.stamp.stamp({}, self.sources), self.stamp.stamp(None, self.sources))

    def test_the_sources_are_the_demos(self):
        self.assertIn(str(ROOT / 'scripts' / 'demo_library.py'), self.stamp.SOURCES)
        for path in self.stamp.SOURCES:
            self.assertTrue(os.path.exists(path), path)

    def test_the_command_answers_by_exit_status(self):
        run = subprocess.run([sys.executable, str(SCRIPT), self.out])
        self.assertEqual(run.returncode, 1)


if __name__ == '__main__':
    unittest.main()
