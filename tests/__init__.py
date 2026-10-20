# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Test package. Importing it keeps the test process off the developer's own files and
settings, then registers src/ as the ``applemusic`` package.

The source tree is laid out for installation (src/ becomes applemusic/), so
tests import it under that name without a build. `python3 -m unittest
discover -s tests` imports test modules as top-level modules and never runs
this file itself, so every test module starts with ``from tests import …``
(run from the repository root, as scripts/check.sh does), before it imports
``applemusic`` (tests/test_isolation.py checks).

First, before anything of the app is imported: XDG_CACHE_HOME, XDG_DATA_HOME,
XDG_CONFIG_HOME and XDG_STATE_HOME point into TEST_HOME, a fresh temporary directory
(removed at exit), and APPLE_MUSIC_CACHE and APPLE_MUSIC_PROFILE are unset, so the default
cache and Chrome profile are empty directories in there: a test that forgets its own set-up
reads nothing of the developer's. APPLE_MUSIC_DEBUG_PORT and APPLE_MUSIC_HOST_SESSION_BUS,
which lead to the signed-in session, are unset too. A test that wants a cache of its own
still points APPLE_MUSIC_CACHE at it. A child process a test starts with this environment
that imports tests again keeps its parent's directories and whatever the test set
(TEST_HOME_VARIABLE names the parent's TEST_HOME), and an import that finds the default
cache or profile outside TEST_HOME raises.

Then GSettings goes to the memory backend, with this tree's schema visible (tests/gtk.py's
use_test_settings(), called here, before any test module can start GTK or GSettings).
Widget tests use tests/gtk.py's requires_gtk.
"""

import atexit
import importlib.util
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'src'

TEST_HOME_VARIABLE = 'MUSIC_SLEEVE_TEST_HOME'
XDG_VARIABLES = {'XDG_CACHE_HOME': 'cache', 'XDG_DATA_HOME': 'data',
                 'XDG_CONFIG_HOME': 'config', 'XDG_STATE_HOME': 'state'}
UNSET_VARIABLES = ('APPLE_MUSIC_CACHE', 'APPLE_MUSIC_PROFILE', 'APPLE_MUSIC_DEBUG_PORT',
                   'APPLE_MUSIC_HOST_SESSION_BUS')


def _inherited_home():
    """The TEST_HOME of the test process that started this one, when this is such a child
    (the variable names a directory and every XDG directory is inside it), else None."""
    value = os.environ.get(TEST_HOME_VARIABLE, '')
    if not value or not os.path.isdir(value):
        return None
    home = pathlib.Path(value).resolve()
    for variable in XDG_VARIABLES:
        path = os.environ.get(variable, '')
        if not os.path.isabs(path) or not pathlib.Path(path).resolve().is_relative_to(home):
            return None
    return home


def _isolate():
    """TEST_HOME: the parent's, or a fresh temporary directory the XDG base directories now
    point into, with the app's path and session variables unset."""
    inherited = _inherited_home()
    if inherited is not None:
        return inherited
    home = pathlib.Path(tempfile.mkdtemp(prefix='music-sleeve-test-home-')).resolve()
    atexit.register(shutil.rmtree, home, ignore_errors=True)
    os.environ[TEST_HOME_VARIABLE] = str(home)
    for variable, name in XDG_VARIABLES.items():
        (home / name).mkdir()
        os.environ[variable] = str(home / name)
    for variable in UNSET_VARIABLES:
        os.environ.pop(variable, None)
    return home


TEST_HOME = _isolate()

if 'applemusic' not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        'applemusic', SRC / '__init__.py', submodule_search_locations=[str(SRC)])
    _module = importlib.util.module_from_spec(_spec)
    sys.modules['applemusic'] = _module
    _spec.loader.exec_module(_module)

from applemusic.backend import config as _config  # noqa: E402  (after _isolate(), above)

if os.environ.get('APPLE_MUSIC_CACHE') is None:  # a child's test may have set its own
    for _path in (_config.cache_dir(), _config.default_profile_dir()):
        if not _path.is_relative_to(TEST_HOME):
            raise RuntimeError(f'tests: {_path} is outside the test directory {TEST_HOME}')

from tests.gtk import use_test_settings  # noqa: E402  (needs ROOT, above)

use_test_settings()
