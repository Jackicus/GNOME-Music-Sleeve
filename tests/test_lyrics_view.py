# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/lyrics.py's pronunciations and translations: each line's under it while
`lyrics-pronunciations` and `lyrics-translations` are on, in the synced list and the
unsynced text; a verse's gap outside the highlight of its line; and the Now Playing
sheet's Translation and Pronunciation menu, offered for lyrics that have either. (The model
is test_lyrics.py's.)"""

import json
import unittest

from tests import ROOT
from tests.gtk import SCHEMA_ID, requires_gtk, wait_for
from tests.test_player import TRACK, make_player

FIXTURES = ROOT / 'tests' / 'fixtures'
FIRST = ('霧の海に鐘が鳴る', 'Kiri no umi ni kane ga naru',
         'Fog on the water, a bell on the buoy')


def fixture(name):
    with open(FIXTURES / name, encoding='utf-8') as file:
        return json.load(file)


@requires_gtk
class MarkupTest(unittest.TestCase):
    def test_the_text_with_and_without_its_extras(self):
        from applemusic.lyrics import Lyrics
        from applemusic.widgets.lyrics import Shown, text_markup

        lyrics = Lyrics({'synced': False, 'lines': [
            {'text': '潮 & <風>', 'pronunciation': 'Shio & <kaze>',
             'translation': 'Tide & wind', 'stanza': True},
            {'text': 'Oh oh'},
            {'text': '海', 'pronunciation': 'Umi', 'stanza': True}]})
        small = '<span size="smaller" alpha="70%">{}</span>'.format
        self.assertEqual(text_markup(lyrics, Shown(False, False)),
                         '潮 &amp; &lt;風&gt;\nOh oh\n\n海')
        self.assertEqual(text_markup(lyrics, Shown(True, False)), '\n'.join([
            '潮 &amp; &lt;風&gt;', small('Shio &amp; &lt;kaze&gt;'),
            'Oh oh', '', '海', small('Umi')]))
        self.assertEqual(text_markup(lyrics, Shown(True, True)), '\n'.join([
            '潮 &amp; &lt;風&gt;', small('Shio &amp; &lt;kaze&gt;'),
            small('Tide &amp; wind'), 'Oh oh', '', '海', small('Umi')]))
        self.assertEqual(text_markup(lyrics, Shown(False, True)), '\n'.join([
            '潮 &amp; &lt;風&gt;', small('Tide &amp; wind'), 'Oh oh', '', '海']))
        plain = Lyrics({'synced': False, 'lines': [{'text': 'A & B'}]})
        self.assertEqual(text_markup(plain, Shown(True, True)), 'A &amp; B')
        self.assertEqual(text_markup(None, Shown(True, True)), '')


@requires_gtk
class LyricsViewTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gio, Gtk

        from applemusic.widgets.lyrics import SETTINGS, LyricsView

        self.player, _engine, self.app = make_player()
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        for key in SETTINGS:
            self.addCleanup(self.app.settings.reset, key)
        self.view = LyricsView()
        self.view.set_player(self.player, self.app)
        window = Gtk.Window(default_width=400, default_height=600, child=self.view)
        window.present()
        self.addCleanup(window.destroy)
        self.assertTrue(wait_for(window.get_mapped))

    def play(self, lyrics):
        self.player.apply({'state': 'paused', 'track': TRACK, 'position': 0, 'duration': 120,
                           'lyrics': lyrics})

    def shown(self):
        """The rows bound, in order: (the line, then its pronunciation and its translation
        when shown, else None)."""
        rows = self.view._rows

        def visible(label):
            return label.get_label() if label.get_visible() else None
        return [(rows[position].label.get_label(), visible(rows[position].pronunciation),
                 visible(rows[position].translation)) for position in sorted(rows)]

    def test_the_synced_lines_show_their_extras_while_the_settings_are_on(self):
        self.play(fixture('lyrics_localized.json'))
        self.assertTrue(wait_for(lambda: len(self.shown()) > 2))
        self.assertEqual(self.shown()[0], (FIRST[0], None, None))
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.assertTrue(wait_for(lambda: self.shown()[0] == (*FIRST[:2], None)), self.shown())
        self.assertTrue(all(row[1] for row in self.shown()))
        self.app.settings.set_boolean('lyrics-translations', True)
        self.assertTrue(wait_for(lambda: self.shown()[0] == FIRST), self.shown())
        self.app.settings.set_boolean('lyrics-pronunciations', False)
        self.assertTrue(wait_for(lambda: self.shown()[0] == (FIRST[0], None, FIRST[2])),
                        self.shown())

    def test_lines_without_extras_show_none(self):
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.app.settings.set_boolean('lyrics-translations', True)
        self.play(fixture('lyrics.json'))
        self.assertTrue(wait_for(lambda: len(self.shown()) > 2))
        self.assertEqual({row[1:] for row in self.shown()}, {(None, None)})

    def test_a_verse_gap_is_outside_the_highlight(self):
        from gi.repository import Gdk, Gtk

        css = Gtk.CssProvider()
        css.load_from_resource('/io/github/jackicus/MusicSleeve/style.css')
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, css)
        self.play(fixture('lyrics_localized.json'))
        self.assertTrue(wait_for(lambda: len(self.view._rows) > 5))
        rows = self.view._rows
        # The fixture's second verse starts at its fifth line; the first line has no gap.
        self.assertEqual([position for position in range(6)
                          if rows[position].has_css_class('stanza')], [4])
        # The gap is the box's margin: the box (which draws the highlight) is no taller than
        # its neighbour without one, and starts lower in its row.
        self.assertTrue(wait_for(lambda: rows[4].get_height() > 0))
        self.assertEqual(rows[4].get_height(), rows[3].get_height())
        ok, bounds = rows[4].compute_bounds(rows[4].get_parent())
        self.assertTrue(ok)
        self.assertGreaterEqual(bounds.get_y(), 18)

    def test_the_unsynced_text_follows_the_settings(self):
        self.play({'synced': False, 'lines': [
            {'text': '潮', 'pronunciation': 'Shio', 'translation': 'Tide'},
            {'text': '風'}]})
        self.assertEqual(self.view.get_visible_child_name(), 'text')
        self.assertEqual(self.view.text_label.get_text(), '潮\n風')
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.assertEqual(self.view.text_label.get_text(), '潮\nShio\n風')
        self.app.settings.set_boolean('lyrics-translations', True)
        self.assertEqual(self.view.text_label.get_text(), '潮\nShio\nTide\n風')


@requires_gtk
class LyricsMenuTest(unittest.TestCase):
    def items(self, answer):
        from applemusic.lyrics import Lyrics
        from applemusic.widgets.now_playing import lyrics_menu

        menu = lyrics_menu(Lyrics(answer) if answer is not None else None)
        if menu is None:
            return None
        return [(menu.get_item_attribute_value(index, 'label', None).unpack(),
                 menu.get_item_attribute_value(index, 'action', None).unpack())
                for index in range(menu.get_n_items())]

    def test_the_items_the_lyrics_have(self):
        translations = ('Show _Translations', 'app.lyrics-translations')
        pronunciations = ('Show _Pronunciations', 'app.lyrics-pronunciations')
        self.assertEqual(self.items(fixture('lyrics_localized.json')),
                         [translations, pronunciations])
        self.assertEqual(self.items({'synced': False, 'lines': [
            {'text': 'Uno', 'translation': 'One'}]}), [translations])
        self.assertEqual(self.items({'synced': False, 'lines': [
            {'text': '潮', 'pronunciation': 'Shio'}]}), [pronunciations])
        self.assertIsNone(self.items(fixture('lyrics.json')))
        self.assertIsNone(self.items(None))

    def test_the_button_shows_while_the_lyrics_have_extras(self):
        from applemusic.widgets.now_playing import NowPlayingSheet

        player, _engine, _app = make_player()
        sheet = NowPlayingSheet()
        sheet._player = player  # set_player wants the window's bottom sheet
        player.connect('notify::lyrics', lambda *_: sheet._update_lyrics_button())
        self.assertFalse(sheet.lyrics_button.get_visible())
        player.apply({'state': 'paused', 'track': TRACK,
                      'lyrics': fixture('lyrics_localized.json')})
        self.assertTrue(sheet.lyrics_button.get_visible())
        self.assertEqual(sheet.lyrics_button.get_menu_model().get_n_items(), 2)
        player.apply({'lyrics': fixture('lyrics.json')})
        self.assertFalse(sheet.lyrics_button.get_visible())


if __name__ == '__main__':
    unittest.main()
