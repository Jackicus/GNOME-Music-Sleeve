# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/banner.py: an artist's banner, its height for a width, the size it is decoded and
fetched at, and the image fading in over its colour. The loader is test_artwork's FakeLoader
and the fetch a stand-in (nothing is downloaded or decoded)."""

import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import pump, wait_for
from tests.test_tiles import WidgetTestCase, texture

from applemusic import remote

WIDE = {'url': 'https://x.invalid/b/{w}x{h}vf.jpg', 'crop': 'vf', 'width': 3000,
        'height': 3000, 'color': '#102030'}


class SizeTest(unittest.TestCase):
    def test_the_height_for_a_width(self):
        from applemusic.widgets.banner import MAX_HEIGHT, MIN_HEIGHT, banner_height

        self.assertEqual(banner_height(0), MIN_HEIGHT)
        self.assertEqual(banner_height(360), MIN_HEIGHT)  # a phone: the middle of it
        self.assertEqual(banner_height(1110), 370)  # 3:1
        self.assertEqual(banner_height(4000), MAX_HEIGHT)

    def test_the_edge_decoded_covers_the_box(self):
        from applemusic.widgets.banner import drawn_edge

        self.assertEqual(drawn_edge(1110, 370, 3), 370)
        self.assertEqual(drawn_edge(360, 240, 3), 240)  # cut at the sides
        self.assertEqual(drawn_edge(1500, 440, 3), 500)  # cut at the top and foot
        self.assertEqual(drawn_edge(1000, 400, 2), 500)  # an editorial background, 2:1
        self.assertEqual(drawn_edge(0, 240, 3), 0)


class BannerTest(WidgetTestCase):
    """The banner in a presented window 600 px wide: 240 px tall."""

    def setUp(self):
        super().setUp()
        from applemusic.widgets import banner

        self.fetched = []  # (banner, pixels)
        self.spawned = []

        async def fetch_banner(data, pixels):
            self.fetched.append((data, pixels))
            return f'/remote-art/banner-{pixels}.jpg'

        app = mock.Mock(spawn=self.spawned.append)
        self.addCleanup(self.close_spawned)
        for target, name, value in ((banner.remote, 'fetch_banner', fetch_banner),
                                    (banner.Gio.Application, 'get_default', lambda: app)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def close_spawned(self):
        for coroutine in self.spawned:
            coroutine.close()

    def run_spawned(self):
        async def run_all():
            for coroutine in self.spawned:
                await coroutine

        asyncio.run(run_all())
        self.spawned.clear()
        pump()

    def banner(self, data=WIDE):
        from applemusic.widgets.banner import ArtistBanner

        widget = self.show(ArtistBanner())
        widget.set_banner(data)
        self.assertTrue(wait_for(lambda: widget._allocated[0] > 0))
        pump()
        return widget

    def test_as_tall_as_its_width_asks(self):
        from gi.repository import Gtk

        from applemusic.widgets.banner import banner_height

        widget = self.banner()
        self.assertEqual(widget.measure(Gtk.Orientation.VERTICAL, 900)[:2], (300, 300))
        self.assertEqual(widget.get_height(), banner_height(widget.get_width()))

    def test_fetched_for_its_width_then_decoded_and_faded_in(self):
        from applemusic.widgets.banner import drawn_edge

        widget = self.banner()
        scale = self.scale(widget)
        width, height = widget.get_width(), widget.get_height()
        self.assertEqual(self.fetched, [])
        self.assertEqual(len(self.spawned), 1)
        self.run_spawned()
        self.assertEqual(self.fetched, [(WIDE, width * scale)])
        self.assertTrue(wait_for(lambda: self.loader.requests))
        path = f'/remote-art/banner-{width * scale}.jpg'
        self.assertEqual(self.loader.requests, [(path, drawn_edge(width, height, 3) * scale)])
        self.assertEqual(widget.picture.get_opacity(), 0)  # the colour meanwhile
        shown = texture()
        self.loader.answer(path, shown)
        self.assertIs(widget.picture.get_paintable(), shown)
        self.assertTrue(wait_for(lambda: widget.picture.get_opacity() == 1))

    def test_a_wider_window_asks_again_and_a_narrower_one_does_not(self):
        widget = self.banner()
        self.run_spawned()
        width = widget.get_width()
        widget.allocate(width + 1000, 500, -1, None)  # as a wider window would
        self.assertTrue(wait_for(lambda: self.spawned))
        self.run_spawned()
        self.assertEqual(self.fetched[-1][1], (width + 1000) * self.scale(widget))
        widget.queue_resize()  # back to the window's width
        self.assertTrue(wait_for(lambda: widget.get_width() == width))
        pump()
        self.assertEqual(self.spawned, [])
        self.assertEqual(len(self.fetched), 2)

    def test_a_banner_on_disk_is_shown_without_a_fetch(self):
        self.banner(dict(WIDE, url=None, art='/demo/art/banner.jpg'))
        self.assertTrue(wait_for(lambda: self.loader.requests))
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.loader.requests[0][0], '/demo/art/banner.jpg')

    def test_none_lets_go(self):
        widget = self.banner()
        self.run_spawned()
        self.assertTrue(wait_for(lambda: self.loader.requests))
        self.loader.answer(self.loader.requests[0][0], texture())
        widget.set_banner(None)
        pump()
        self.assertEqual(widget.picture.get_opacity(), 0)
        self.assertEqual(widget._slot.paths, ())

    def test_freed(self):
        widget = self.banner()
        self.run_spawned()
        self.assertTrue(wait_for(lambda: self.loader.requests))
        self.loader.answer(self.loader.requests[0][0], texture())
        self.assertTrue(wait_for(lambda shown=widget: shown.picture.get_opacity() == 1))
        ref = self.drop(widget)
        del widget
        self.assert_freed(ref)

    def test_the_size_asked_follows_remote(self):
        self.assertEqual(remote.banner_size(WIDE, 600)[0], 2 * remote.BANNER_STEP)


if __name__ == '__main__':
    unittest.main()
