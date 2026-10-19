# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/lyrics.py's pronunciations: each line's under it while `lyrics-pronunciations` is
on, in the synced list and the unsynced text, and Show Pronunciations in the Now Playing
sheet's More Options for lyrics that have them. (The model is test_lyrics.py's.)"""

import json
import unittest

from tests import ROOT
from tests.gtk import SCHEMA_ID, requires_gtk, wait_for
from tests.test_player import TRACK, make_player

FIXTURES = ROOT / 'tests' / 'fixtures'


def fixture(name):
    with open(FIXTURES / name, encoding='utf-8') as file:
        return json.load(file)


@requires_gtk
class MarkupTest(unittest.TestCase):
    def test_the_text_with_and_without_pronunciations(self):
        from applemusic.lyrics import Lyrics
        from applemusic.widgets.lyrics import text_markup

        lyrics = Lyrics({'synced': False, 'lines': [
            {'text': '潮 & <風>', 'pronunciation': 'Shio & <kaze>', 'stanza': True},
            {'text': 'Oh oh'},
            {'text': '海', 'pronunciation': 'Umi', 'stanza': True}]})
        self.assertEqual(text_markup(lyrics, False), '潮 &amp; &lt;風&gt;\nOh oh\n\n海')
        self.assertEqual(text_markup(lyrics, True), '\n'.join([
            '潮 &amp; &lt;風&gt;',
            '<span size="smaller" alpha="70%">Shio &amp; &lt;kaze&gt;</span>',
            'Oh oh', '', '海', '<span size="smaller" alpha="70%">Umi</span>']))
        plain = Lyrics({'synced': False, 'lines': [{'text': 'A & B'}]})
        self.assertEqual(text_markup(plain, True), 'A &amp; B')
        self.assertEqual(text_markup(None, True), '')


@requires_gtk
class LyricsViewTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gio, Gtk

        from applemusic.widgets.lyrics import LyricsView

        self.player, _engine, self.app = make_player()
        self.app.settings = Gio.Settings.new(SCHEMA_ID)
        self.addCleanup(self.app.settings.reset, 'lyrics-pronunciations')
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
        """The rows bound, in order: (the line, its pronunciation when shown, else None)."""
        rows = self.view._rows
        return [(rows[position].label.get_label(),
                 rows[position].pronunciation.get_label()
                 if rows[position].pronunciation.get_visible() else None)
                for position in sorted(rows)]

    def test_the_synced_lines_show_their_pronunciations_while_the_setting_is_on(self):
        self.play(fixture('lyrics_pronunciations.json'))
        self.assertTrue(wait_for(lambda: len(self.shown()) > 2))
        first = ('霧の海に鐘が鳴る', 'Kiri no umi ni kane ga naru')
        self.assertEqual(self.shown()[0], (first[0], None))
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.assertTrue(wait_for(lambda: self.shown()[0] == first), self.shown())
        self.assertTrue(all(pronunciation for _line, pronunciation in self.shown()))
        self.app.settings.set_boolean('lyrics-pronunciations', False)
        self.assertTrue(wait_for(lambda: self.shown()[0] == (first[0], None)), self.shown())

    def test_lines_without_a_pronunciation_show_none(self):
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.play(fixture('lyrics.json'))
        self.assertTrue(wait_for(lambda: len(self.shown()) > 2))
        self.assertEqual({pronunciation for _line, pronunciation in self.shown()}, {None})

    def test_the_unsynced_text_follows_the_setting(self):
        self.play({'synced': False, 'lines': [
            {'text': '潮', 'pronunciation': 'Shio'}, {'text': '風'}]})
        self.assertEqual(self.view.get_visible_child_name(), 'text')
        self.assertEqual(self.view.text_label.get_text(), '潮\n風')
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.assertEqual(self.view.text_label.get_text(), '潮\nShio\n風')


@requires_gtk
class ShowPronunciationsMenuTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gtk

        from applemusic.widgets.now_playing import NowPlayingSheet

        self.player, _engine, _app = make_player()
        self.sheet = NowPlayingSheet()
        self.sheet._player = self.player  # set_player wants the window's bottom sheet
        self.button = Gtk.MenuButton()

    def items(self):
        """The (label, action) of every item in the menu More Options would show."""
        self.sheet._on_more_popup(self.button)
        menu = self.button.get_menu_model()
        found = []

        def walk(model):
            for index in range(model.get_n_items()):
                label = model.get_item_attribute_value(index, 'label', None)
                action = model.get_item_attribute_value(index, 'action', None)
                if label is not None:
                    found.append((label.unpack(), action.unpack() if action else None))
                for link in ('section', 'submenu'):
                    child = model.get_item_link(index, link)
                    if child is not None:
                        walk(child)
        if menu is not None:
            walk(menu)
        return found

    def test_offered_only_for_lyrics_with_pronunciations(self):
        show = ('_Show Pronunciations', 'app.lyrics-pronunciations')
        self.player.apply({'state': 'paused', 'track': TRACK,
                           'lyrics': fixture('lyrics_pronunciations.json')})
        self.assertIn(show, self.items())
        self.player.apply({'lyrics': fixture('lyrics.json')})
        self.assertNotIn(show, self.items())
        self.player.apply({'lyrics': None})
        self.assertNotIn(show, self.items())


if __name__ == '__main__':
    unittest.main()
