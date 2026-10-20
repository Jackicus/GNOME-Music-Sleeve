# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The test process's own home (tests/__init__.py): the default cache, Chrome profile and
settings are the test run's, never the developer's, and every test module imports tests
before the app."""

import ast
import asyncio
import json
import os
import shutil
import subprocess
import sys
import unittest

import tests
from tests import ROOT, TEST_HOME

from applemusic.backend import config
from applemusic.library import Library


class TestHomeTest(unittest.TestCase):
    def test_the_xdg_directories_are_inside_the_test_home(self):
        for variable in tests.XDG_VARIABLES:
            with self.subTest(variable=variable):
                path = os.environ[variable]
                self.assertTrue(os.path.isabs(path))
                self.assertTrue(os.path.realpath(path).startswith(str(TEST_HOME) + os.sep))
        self.assertNotEqual(TEST_HOME, ROOT)
        self.assertFalse(ROOT.is_relative_to(TEST_HOME))

    def test_the_default_cache_and_profile_are_inside_the_test_home(self):
        self.assertNotIn('APPLE_MUSIC_CACHE', os.environ)
        self.assertNotIn('APPLE_MUSIC_PROFILE', os.environ)
        for profile in ('default', config.DEVELOPMENT):
            with self.subTest(profile=profile):
                saved = config.build_profile()
                config.set_build_profile(profile)
                try:
                    self.assertTrue(config.cache_dir().is_relative_to(TEST_HOME))
                    self.assertTrue(config.profile_dir().is_relative_to(TEST_HOME))
                finally:
                    config.set_build_profile(saved)

    def test_the_signed_in_session_is_out_of_reach(self):
        self.assertIsNone(config.debug_port())
        self.assertIsNone(config.host_session_bus())

    def test_settings_are_in_memory(self):
        self.assertEqual(os.environ.get('GSETTINGS_BACKEND'), 'memory')

    def test_a_library_with_no_cache_of_its_own_reads_the_test_home(self):
        cache = config.cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, cache, ignore_errors=True)
        play = {'kind': 'album', 'id': 'l.isolation'}
        album = {'id': 'l.isolation', 'kind': 'album', 'title': 'Isolation Album',
                 'subtitle': 'Test Artist', 'play': play, 'groups': []}
        data = {'version': 1, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': [album]}, 'shelves': []}
        (cache / 'library.json').write_text(json.dumps(data), encoding='utf-8')
        library = Library()
        asyncio.run(library.load())
        self.assertEqual([item.title for item in library.albums], ['Isolation Album'])

    def test_a_child_test_process_keeps_its_parents_directories(self):
        script = ('import json, os, tests; print(json.dumps([str(tests.TEST_HOME), '
                  'os.environ["XDG_CACHE_HOME"], os.environ.get("APPLE_MUSIC_CACHE")]))')
        cache = str(TEST_HOME / 'child-cache')
        done = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True,
                              text=True, env=dict(os.environ, APPLE_MUSIC_CACHE=cache),
                              check=True)
        self.assertEqual(json.loads(done.stdout),
                         [str(TEST_HOME), os.environ['XDG_CACHE_HOME'], cache])

    def test_a_process_whose_directories_are_elsewhere_gets_a_home_of_its_own(self):
        script = ('import json, os, tests; print(json.dumps([str(tests.TEST_HOME), '
                  'os.environ["XDG_CACHE_HOME"], os.environ.get("APPLE_MUSIC_CACHE")]))')
        env = dict(os.environ, XDG_CACHE_HOME=str(ROOT / 'not-the-test-home'),
                   APPLE_MUSIC_CACHE=str(ROOT / 'not-the-test-home'))
        done = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True,
                              text=True, env=env, check=True)
        home, cache_home, cache = json.loads(done.stdout)
        self.assertNotEqual(home, str(TEST_HOME))
        self.assertTrue(cache_home.startswith(home + os.sep))
        self.assertIsNone(cache)
        self.assertFalse(os.path.exists(home))  # removed as the child exited


class ImportOrderTest(unittest.TestCase):
    def test_every_test_module_imports_tests_before_the_app(self):
        for path in sorted((ROOT / 'tests').glob('*.py')):
            if path.name == '__init__.py':
                continue
            with self.subTest(module=path.name):
                imports = []
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        names = [node.module]
                    else:
                        continue
                    imports += [(node.lineno, name.split('.')[0]) for name in names
                                if name.split('.')[0] in ('tests', 'applemusic')]
                if imports:
                    self.assertEqual(min(imports)[1], 'tests',
                                     'imports applemusic before tests')


if __name__ == '__main__':
    unittest.main()
