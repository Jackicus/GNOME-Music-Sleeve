#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What a demo library was made from: `demo_stamp.py DIR` exits 0 when DIR holds a library
that demo_library.py, as it is now and with no options, wrote, and 1 otherwise.

demo_library.py writes DIR/.demo-stamp last, once everything else is written: a hash of the
sources that decide what it writes (SOURCES: the script, and the backend's normalize.py and
config.py, whose shapes and sizes it uses) and of the options it was given (only those that
differ from its defaults). A directory without the file (an interrupted run, or one from
before it existed), or with another hash (a source has changed since, or other options made
it), is out of date, and the harness and demo.sh write it again (it takes a second or two).
Standard library only: the harness imports it before anything else of the app's.
"""

import hashlib
import json
import os
import sys

STAMP = '.demo-stamp'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = tuple(os.path.join(ROOT, *path) for path in (
    ('scripts', 'demo_library.py'),
    ('src', 'backend', 'normalize.py'),
    ('src', 'backend', 'config.py'),
))


def stamp(options=None, sources=SOURCES):
    """The hash a library made from `sources` with `options` (a dict of the options that
    differ from the defaults; None or {} for none) is stamped with."""
    digest = hashlib.sha256()
    for path in sources:
        with open(path, 'rb') as file:
            digest.update(hashlib.sha256(file.read()).digest())
    digest.update(json.dumps(options or {}, sort_keys=True).encode())
    return digest.hexdigest()


def read(out_dir):
    """The stamp in out_dir, or None."""
    try:
        with open(os.path.join(out_dir, STAMP), encoding='utf-8') as file:
            return file.read().strip() or None
    except OSError:
        return None


def write(out_dir, options=None, sources=SOURCES):
    """Stamp out_dir as made from `sources` with `options`: the last thing a run writes."""
    with open(os.path.join(out_dir, STAMP), 'w', encoding='utf-8') as file:
        file.write(stamp(options, sources) + '\n')


def current(out_dir, options=None, sources=SOURCES):
    """Whether out_dir holds a library made from `sources`, as they are now, with `options`."""
    return (os.path.exists(os.path.join(out_dir, 'library.json'))
            and read(out_dir) == stamp(options, sources))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: demo_stamp.py DIR')
    sys.exit(0 if current(sys.argv[1]) else 1)
