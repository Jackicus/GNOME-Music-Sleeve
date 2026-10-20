# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/backdrop.py: the artwork's field as a background, the full-screen player's under
its scrim and the Now Playing sheet's as a tint, at the opacity its text reads at in the
colour scheme shown, none in high contrast; show_artwork(), the last call winning; and the
sheet following the item's artwork only while it is in sight."""

import asyncio
import tempfile
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import SCHEMA_ID, pump, requires_gtk, wait_for
from tests.test_player import TRACK, FakeApp
from tests.test_transport import RatingEngine


def cover(directory, name, colour):
    """An invented cover, one colour all over (0xRRGGBBAA), saved as a PNG: its path."""
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 64)
    pixbuf.fill(colour)
    path = f'{directory}/{name}.png'
    pixbuf.savev(path, 'png', [], [])
    return path


def load_stylesheet(test):
    """The app's stylesheet on the display for `test`: the tint's colour is style.css's."""
    from gi.repository import Gdk, Gtk

    provider = Gtk.CssProvider()
    provider.load_from_resource('/io/github/jackicus/MusicSleeve/style.css')
    display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(display, provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    test.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, provider)


@requires_gtk
class BackdropTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Adw

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        manager = Adw.StyleManager.get_default()
        scheme = manager.get_color_scheme()
        self.addCleanup(manager.set_color_scheme, scheme)
        load_stylesheet(self)

    def present(self, backdrop):
        from gi.repository import Gtk

        window = Gtk.Window(default_width=200, default_height=120, child=backdrop)
        self.addCleanup(window.destroy)
        window.present()
        self.assertTrue(wait_for(backdrop.get_mapped))
        return window

    def test_a_field_from_a_cover_and_its_drawing(self):
        from gi.repository import Gtk

        from applemusic.widgets import artwork
        from applemusic.widgets.backdrop import ArtworkBackdrop

        path = cover(self.directory.name, 'pale', 0xf0f0f0ff)  # the scrim deepens it
        field = artwork.load_field(path)
        self.assertIsNone(artwork.load_field(f'{self.directory.name}/missing.png'))
        self.assertEqual((field.texture.get_width(), field.texture.get_height()),
                         (artwork.FIELD_SIZE, artwork.FIELD_SIZE))
        self.assertGreater(field.scrim, 0.5)
        backdrop = ArtworkBackdrop()
        self.present(backdrop)
        backdrop.show_field(field)
        self.assertTrue(wait_for(lambda: backdrop._previous is None))
        snapshot = Gtk.Snapshot()
        backdrop.do_snapshot(snapshot)
        self.assertIsNotNone(snapshot.to_node())

    def test_the_tint_is_as_deep_as_the_text_allows_in_each_scheme(self):
        from gi.repository import Adw, Gtk

        from applemusic.widgets import artwork
        from applemusic.widgets.backdrop import ArtworkBackdrop

        manager = Adw.StyleManager.get_default()
        backdrop = ArtworkBackdrop(tint=True)
        self.assertTrue(backdrop.has_css_class('tint'))
        # The sheet's text colour comes from the backdrop's parent.
        self.present(Gtk.Overlay(child=backdrop))
        field = artwork.load_field(cover(self.directory.name, 'orange', 0xe68019ff))
        alphas = {}
        for scheme in (Adw.ColorScheme.FORCE_DARK, Adw.ColorScheme.FORCE_LIGHT):
            manager.set_color_scheme(scheme)
            pump(50)
            base, text = backdrop.colours()
            alpha = backdrop.tint_alpha(field)
            alphas[manager.get_dark()] = alpha
            self.assertGreater(alpha, 0)
            self.assertLessEqual(alpha, artwork.TINT_MAX)
            colour, opacity = text
            shown = tuple(b + alpha * (p - b) for p, b in zip(field.samples[0], base,
                                                              strict=True))
            for factor, ratio in artwork.TINT_TEXT:
                self.assertGreaterEqual(
                    artwork.contrast_ratio(colour, opacity * factor, shown), ratio)
        # The light scheme's dark text takes less of a mid-tone than the dark one's white.
        self.assertNotEqual(alphas[True], alphas[False])
        self.assertEqual(backdrop.tint_alpha(None), 0)
        backdrop.show_field(field)
        self.assertTrue(wait_for(lambda: backdrop._previous is None))
        snapshot = Gtk.Snapshot()
        backdrop.do_snapshot(snapshot)
        self.assertIsNotNone(snapshot.to_node())

    def test_no_tint_in_high_contrast(self):
        from gi.repository import Adw, Gtk

        from applemusic.widgets import artwork
        from applemusic.widgets.backdrop import ArtworkBackdrop

        backdrop = ArtworkBackdrop(tint=True)
        self.present(Gtk.Overlay(child=backdrop))
        field = artwork.load_field(cover(self.directory.name, 'blue', 0x3366ccff))
        self.assertGreater(backdrop.tint_alpha(field), 0)
        with mock.patch.object(Adw.StyleManager, 'get_high_contrast', lambda _manager: True):
            self.assertEqual(backdrop.tint_alpha(field), 0)

    def test_the_last_artwork_asked_for_wins(self):
        from gi.repository import Gtk

        from applemusic.widgets.backdrop import ArtworkBackdrop

        backdrop = ArtworkBackdrop(tint=True)
        self.present(Gtk.Overlay(child=backdrop))
        first = cover(self.directory.name, 'first', 0x204080ff)
        second = cover(self.directory.name, 'second', 0x802040ff)

        async def both():
            await asyncio.gather(backdrop.show_artwork(first), backdrop.show_artwork(second))

        asyncio.run(both())
        self.assertIsNotNone(backdrop.field)
        self.assertEqual(backdrop._wanted, second)
        asyncio.run(backdrop.show_artwork(None))
        pump(50)
        self.assertIsNone(backdrop.field)


@requires_gtk
class SheetTintTest(unittest.TestCase):
    """The Now Playing sheet makes its tint only while it is in sight."""

    def test_the_sheet_follows_the_artwork_only_while_open(self):
        from gi.repository import Adw, Gio, Gtk

        from applemusic.player import Player
        from applemusic.player_bar import PlayerBar
        from applemusic.widgets.now_playing import NowPlayingSheet

        app = FakeApp(RatingEngine())
        app.settings = Gio.Settings.new(SCHEMA_ID)
        player = Player(app)
        player.track_grace_ms = 0
        sheet = NowPlayingSheet()
        bottom_sheet = Adw.BottomSheet(bottom_bar=PlayerBar(), sheet=sheet,
                                       content=Gtk.Label())
        window = Gtk.Window(default_width=800, default_height=600, child=bottom_sheet)
        self.addCleanup(window.destroy)
        sheet.set_player(player, app, bottom_sheet)
        window.present()
        self.assertTrue(wait_for(window.get_mapped))

        def fetches():
            return app.spawned.count('NowPlayingSheet._fetch_backdrop')

        player.apply({'state': 'playing', 'track': TRACK, 'position': 1, 'duration': 200})
        self.assertEqual(fetches(), 0)            # closed: nothing made
        bottom_sheet.set_open(True)
        pump(50)
        self.assertEqual(fetches(), 1)            # open: the item's
        player.apply({'state': 'playing', 'track': dict(TRACK, id='i.other', index=3,
                                                         artUrl=None)})
        pump(50)
        self.assertEqual(fetches(), 1)            # no artwork: the plain background
        self.assertIsNone(sheet.backdrop.field)
        bottom_sheet.set_open(False)
        pump(50)
        player.apply({'state': 'playing', 'track': TRACK})
        pump(50)
        self.assertEqual(fetches(), 1)            # closed again: nothing
        bottom_sheet.set_open(True)
        pump(50)
        self.assertEqual(fetches(), 2)            # caught up with as it opens


if __name__ == '__main__':
    unittest.main()
