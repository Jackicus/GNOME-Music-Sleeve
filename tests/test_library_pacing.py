# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""paused_gc (library/pacing.py): the collector paused around a load and a Songs build, and
the heap frozen after."""

import asyncio
import gc
import os
import tempfile
import unittest
import weakref
from unittest import mock

from tests.test_library import album, write_library

from applemusic.library import Library
from applemusic.library.pacing import paused_gc


class TestPausedGc(unittest.TestCase):
    def setUp(self):
        self.addCleanup(gc.enable)
        self.addCleanup(gc.unfreeze)

    def test_paused_then_frozen_and_resumed(self):
        gc.enable()
        frozen = gc.get_freeze_count()
        with paused_gc():
            self.assertFalse(gc.isenabled())
            with paused_gc(freeze=False):
                self.assertFalse(gc.isenabled())
            self.assertFalse(gc.isenabled())  # the outer one still holds
            kept = [object() for _ in range(10)]  # noqa: F841
        self.assertTrue(gc.isenabled())
        self.assertGreater(gc.get_freeze_count(), frozen)

    def cycle(self):
        """A weak reference to a reference cycle that is garbage, not collected yet."""
        class Node:
            pass

        node = Node()
        node.self = node
        dead = weakref.ref(node)
        del node
        return dead

    def test_garbage_from_before_the_pause_is_not_frozen(self):
        gc.disable()
        dead = self.cycle()
        with paused_gc():
            pass
        gc.enable()
        gc.collect()
        self.assertIsNone(dead())

    def test_garbage_made_during_a_later_pause_is_not_frozen(self):
        gc.enable()
        gc.freeze()  # as after the first load
        with paused_gc():
            dead = self.cycle()
        gc.collect()
        self.assertIsNone(dead())

    def test_a_load_pauses_from_its_call_to_its_end(self):
        gc.enable()
        with tempfile.TemporaryDirectory() as cache:
            write_library(cache, [album('l.a1', 'A1', ['i.1'])])
            library = Library()
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                loading = library.load()
                self.assertFalse(gc.isenabled())  # the parse runs without collections
                asyncio.run(loading)
                self.assertTrue(gc.isenabled())
                # A load closed before it ever ran (an app never activated) lets go too.
                never = library.load()
                self.assertFalse(gc.isenabled())
                never.close()
                del never
                self.assertTrue(gc.isenabled())
                reloading = library.reload()
                self.assertFalse(gc.isenabled())
                asyncio.run(reloading)
                self.assertTrue(gc.isenabled())

    def test_no_freeze_when_not_asked_and_disabled_stays_disabled(self):
        gc.unfreeze()
        gc.disable()
        with paused_gc(freeze=False):
            self.assertFalse(gc.isenabled())
        self.assertFalse(gc.isenabled())
        self.assertEqual(gc.get_freeze_count(), 0)


if __name__ == '__main__':
    unittest.main()
