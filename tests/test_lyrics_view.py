# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/lyrics.py's rows and text: each line's pronunciation and translation under it
while `lyrics-pronunciations` and `lyrics-translations` are on, its background vocals on a
line of their own under those, with their own extras, in the synced list and the unsynced
text; a verse's gap outside the highlight of its line; and the Now Playing sheet's
Translation and Pronunciation menu, offered for lyrics that have either; a duet's rows on
their singers' sides, mirrored right to left, and a recycled row losing its old side; an
instrumental break's dots, opening over the line after it, lit step by step, and shut as
the line begins; a word-timed line's pieces lit as they are sung, on the current row only,
swept with animations on and whole with them off, the sweep's tick running only while a
piece is sung and shown, the lyrics held from going back but for a seek, and where each
piece is drawn (multi-byte text, wrapped lines, right to left) and its mask. (The model is
test_lyrics.py's.)"""

import json
import unittest
from unittest import mock

from tests import ROOT
from tests.gtk import SCHEMA_ID, requires_gtk, wait_for
from tests.test_player import TRACK, make_player

FIXTURES = ROOT / 'tests' / 'fixtures'
FIRST = ('霧の海に鐘が鳴る', 'Kiri no umi ni kane ga naru',
         'Fog on the water, a bell on the buoy')


def fixture(name):
    with open(FIXTURES / name, encoding='utf-8') as file:
        return json.load(file)


def visible_parts(box):
    """A row's parts, top to bottom (widgets.lyrics.PARTS), each label's text while it is
    shown, None while it is hidden."""
    from applemusic.widgets.lyrics import PARTS

    labels = [getattr(box, part.attribute) for part in PARTS]
    children, child = [], box.get_first_child()
    while child is not None:
        children.append(child)
        child = child.get_next_sibling()
    assert children == labels, children
    return tuple(label.get_label() if label.get_visible() else None for label in labels)


def make_list_item():
    """A stand-in Gtk.ListItem (the factory's handlers ask only this of it), at position 3."""
    from gi.repository import GObject

    class Item(GObject.Object):
        def __init__(self):
            super().__init__()
            self.child = self.line = self.spoken = None

        def set_child(self, child):
            self.child = child

        def get_child(self):
            return self.child

        def get_item(self):
            return self.line

        def get_position(self):
            return 3

        def set_accessible_label(self, label):
            self.spoken = label

    return Item()


def lit(box):
    """How many of a row's break dots are lit, and whether they are open (as asked: the
    revealer may still be sliding)."""
    from applemusic.widgets.lyrics import _children

    return (sum(dot.has_css_class('lit') for dot in _children(box.dots)),
            box.revealer.get_reveal_child())


def alignment(box):
    """A row's side as it is set: its labels' (xalign, justification), the same for all of
    them, then the box's start and end margins."""
    from applemusic.widgets.lyrics import PARTS

    aligned = {(getattr(box, part.attribute).get_xalign(),
                getattr(box, part.attribute).get_justify().value_nick) for part in PARTS}
    assert len(aligned) == 1, aligned
    return (*aligned.pop(), box.get_margin_start(), box.get_margin_end())


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
        # Background vocals on a line of their own, smaller, with their own extras under
        # them; a line of background vocals only is the background.
        sung = Lyrics({'synced': False, 'lines': [
            {'text': '潮', 'background': '(潮 & 風)', 'pronunciation': 'Shio',
             'pronunciationBackground': '(shio)', 'translation': 'Tide',
             'translationBackground': '(tide)'},
            {'text': '', 'background': '(Oh oh)', 'translation': 'Oh oh!', 'stanza': True}]})
        background = '<span size="90%" alpha="70%">{}</span>'.format
        smaller = '<span size="80%" alpha="60%">{}</span>'.format
        self.assertEqual(text_markup(sung, Shown(False, False)), '\n'.join([
            '潮', background('(潮 &amp; 風)'), '', background('(Oh oh)')]))
        self.assertEqual(text_markup(sung, Shown(True, True)), '\n'.join([
            '潮', small('Shio'), small('Tide'), background('(潮 &amp; 風)'),
            smaller('(shio)'), smaller('(tide)'), '', small('Oh oh!'),
            background('(Oh oh)')]))
        self.assertEqual(text_markup(sung, Shown(False, True)), '\n'.join([
            '潮', small('Tide'), background('(潮 &amp; 風)'), smaller('(tide)'), '',
            small('Oh oh!'), background('(Oh oh)')]))
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

    def shown(self, background=False):
        """The rows bound, in order: (the line, its pronunciation and its translation) as
        shown, None for a label hidden; with `background`, the background vocals' three
        after them."""
        rows = self.view._rows
        return [visible_parts(rows[position])[:None if background else 3]
                for position in sorted(rows)]

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
        self.assertEqual({row[1:] for row in self.shown(True)}, {(None,) * 5})

    def test_the_background_vocals_show_under_their_line(self):
        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(lambda: len(self.shown()) > 7), self.shown())
        self.assertEqual(self.shown(True)[0], ('Grey morning on the jetty', *[None] * 5))
        self.assertEqual(self.shown(True)[1], ('I keep the lantern burning', None, None,
                                               '(burning)', None, None))
        self.assertEqual(self.shown(True)[6], ('波の音を数えて', None, None, '(数えて)',
                                               None, None))
        self.app.settings.set_boolean('lyrics-pronunciations', True)
        self.app.settings.set_boolean('lyrics-translations', True)
        self.assertTrue(wait_for(lambda: self.shown(True)[6][1] is not None), self.shown(True))
        self.assertEqual(self.shown(True)[6], (
            '波の音を数えて', 'Nami no oto o kazoete', 'Counting the sound of the waves',
            '(数えて)', '(kazoete)', '(counting)'))
        self.app.settings.set_boolean('lyrics-pronunciations', False)
        self.assertTrue(wait_for(lambda: self.shown(True)[6][1] is None), self.shown(True))
        self.assertEqual(self.shown(True)[6], (
            '波の音を数えて', None, 'Counting the sound of the waves', '(数えて)', None,
            '(counting)'))
        # The background follows its line's state.
        box = self.view._rows[1]
        self.assertTrue(box.has_css_class('dimmed'))
        self.player.apply({'position': 17})
        self.assertTrue(wait_for(lambda: box.has_css_class('current')))
        self.assertIs(box.background.get_parent(), box)

    def test_a_row_rebound_shows_only_its_new_lines_parts(self):
        """A recycled row bound to a line with background vocals, then to lines without
        them or with nothing else: only the new line's parts show, and a screen reader
        hears the main vocals, then the background."""
        from applemusic.lyrics import LyricLine, Lyrics
        from applemusic.widgets.lyrics import Shown

        lines = Lyrics({'synced': True, 'lines': [
            {'startMs': 1000, 'text': 'Harbour lights', 'background': '(lights)',
             'pronunciation': 'Ha-bor', 'pronunciationBackground': '(laits)',
             'translation': 'Luces del puerto', 'translationBackground': '(luces)'},
            {'startMs': 2000, 'text': 'Low tide'},
            {'startMs': 3000, 'text': '', 'background': '(Oh oh)'}]}).lines
        self.view._shown = Shown(True, True)
        item = make_list_item()
        self.view._on_setup(None, item)
        bound = []
        for line in (*lines, LyricLine(), lines[0]):
            item.line = line
            self.view._on_bind(None, item)
            bound.append((visible_parts(item.child.line), item.spoken))
            self.view._on_unbind(None, item)
        self.assertEqual(bound, [
            (('Harbour lights', 'Ha-bor', 'Luces del puerto', '(lights)', '(laits)',
              '(luces)'), 'Harbour lights (lights)'),
            (('Low tide', *[None] * 5), 'Low tide'),
            ((None, None, None, '(Oh oh)', None, None), '(Oh oh)'),
            ((None,) * 6, ''),
            (('Harbour lights', 'Ha-bor', 'Luces del puerto', '(lights)', '(laits)',
              '(luces)'), 'Harbour lights (lights)')])

    def test_a_row_rebound_takes_its_new_lines_side(self):
        """A recycled row takes the side of each line bound to it, every label aligned to it
        and the margin on the other side, and loses it for a line on another side, or of a
        song that is not a duet; a screen reader hears the row as before, singers unnamed."""
        from applemusic.lyrics import Lyrics

        duet = Lyrics({'synced': True, 'lines': [
            {'startMs': 1000, 'text': 'Harbour lights', 'background': '(lights)',
             'translation': 'Luces', 'agent': 'v2'},
            {'startMs': 2000, 'text': 'Low tide', 'agent': 'v1'},
            {'startMs': 3000, 'text': 'All aboard', 'agent': 'v1000'}]}).lines
        solo = Lyrics({'synced': True, 'lines': [{'startMs': 1000, 'text': 'Sea wall'}]}).lines
        self.view._inset = 120
        item = make_list_item()
        self.view._on_setup(None, item)
        bound, dots = [], []
        for line in (duet[0], duet[1], duet[0], duet[2], solo[0], duet[2], duet[0]):
            item.line = line
            self.view._on_bind(None, item)
            box = item.child.line
            bound.append((alignment(box), item.spoken))
            dots.append((box.dots.get_halign().value_nick, box.dots.get_margin_start(),
                         box.dots.get_margin_end()))
            self.view._on_unbind(None, item)
        end = (1.0, 'right', 120, 0)
        start = (0.0, 'left', 0, 120)
        middle = (0.5, 'center', 60, 60)
        across = (0.0, 'left', 0, 0)
        self.assertEqual(bound, [
            (end, 'Harbour lights (lights)'), (start, 'Low tide'),
            (end, 'Harbour lights (lights)'), (middle, 'All aboard'), (across, 'Sea wall'),
            (middle, 'All aboard'), (end, 'Harbour lights (lights)')])
        # A break's dots go on its line's side.
        self.assertEqual(dots, [('end', 120, 0), ('start', 0, 120), ('end', 120, 0),
                                ('center', 60, 60), ('start', 0, 0), ('center', 60, 60),
                                ('end', 120, 0)])

    def test_a_row_rebound_switches_between_a_break_and_a_line(self):
        """A recycled row bound to a line with a break shows its dots, open and lit as the
        moment has them, at once; bound to a line without one, none; bound again to a
        break that is not current, shut."""
        from applemusic.lyrics import Break, LyricLine, Moment

        after_break = LyricLine()
        after_break.text, after_break.instrumental = 'Low tide', Break(0, 8999)
        plain = LyricLine()
        plain.text = 'Sea wall'
        item = make_list_item()
        self.view._on_setup(None, item)
        self.view._active = True    # the tab shown: the open dots breathe
        self.addCleanup(setattr, self.view, '_active', False)
        states = []
        for line, moment in ((after_break, Moment(3, True, 2)), (plain, Moment(3, False, 0)),
                             (after_break, Moment(2, False, 0)),
                             (after_break, Moment(3, True, 3))):
            self.view._moment = moment
            item.line = line
            self.view._on_bind(None, item)
            box = item.child.line
            states.append((box.revealer.get_visible(), *lit(box),
                           box.revealer.get_child_revealed(), box.has_css_class('current'),
                           box.dots.has_css_class('breathing')))
            self.view._on_unbind(None, item)
        self.assertEqual(states, [
            (True, 2, True, True, False, True),     # in the break: open, two lit, line dim
            (False, 2, False, False, True, False),  # a line without a break, current
            (True, 2, False, False, False, False),  # a break not current: shut
            (True, 3, True, True, False, True)])

    def test_a_breaks_dots_open_step_and_shut(self):
        """The invented duet's 12.4 s intro: the first row current with its dots open, a
        dot more lit at each third, then its line current, the dots shut; a break between
        verses opens over its line, the line before it dimmed."""
        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(lambda: 8 in self.view._rows), sorted(self.view._rows))
        rows = self.view._rows
        first = rows[0]
        self.assertEqual(self.view._current, 0)
        self.assertEqual(lit(first), (1, True))
        self.assertTrue(first.has_css_class('dimmed'))  # the line is still to come
        # The group breathes only while the tab is shown.
        self.assertFalse(first.dots.has_css_class('breathing'))
        self.view.set_active(True)
        self.addCleanup(self.view.set_active, False)
        self.assertTrue(first.dots.has_css_class('breathing'))
        self.assertTrue(first.revealer.get_visible())
        self.assertFalse(rows[1].revealer.get_visible())
        for position, expected in ((4.2, (2, True)), (8.3, (3, True)), (12.4, (3, False))):
            self.player.apply({'position': position})
            self.assertTrue(wait_for(lambda: lit(first) == expected), (position, lit(first)))  # noqa: B023
        self.assertTrue(first.has_css_class('current'))
        self.assertFalse(first.dots.has_css_class('breathing'))
        self.assertTrue(wait_for(lambda: not first.revealer.get_child_revealed()))
        # The break before the third verse.
        self.player.apply({'position': 43.4})
        self.assertTrue(wait_for(lambda: rows[7].has_css_class('current')))
        self.player.apply({'position': 47.5})
        self.assertTrue(wait_for(lambda: lit(rows[8]) == (2, True)), lit(rows[8]))
        self.assertEqual(self.view._current, 8)
        self.assertTrue(rows[7].has_css_class('dimmed') and rows[8].has_css_class('dimmed'))

    def test_the_timeout_waits_for_the_next_dot(self):
        """While playing, the one timeout is armed for the next change: a dot lighting in a
        break, the next line's start on a line."""
        from applemusic.widgets import lyrics as view_module

        self.view.set_active(True)
        self.addCleanup(self.view.set_active, False)
        self.play(fixture('lyrics_syllable.json'))
        delays = []

        def timeout_add(delay, callback):
            delays.append(delay)
            return 0

        for position in (4.0, 13.0, 16.0):
            self.player.apply({'state': 'playing', 'position': position})
            with mock.patch.object(view_module.GLib, 'timeout_add', timeout_add):
                self.view._arm_next_change()
        # 4.134 s: the second dot of the intro; 13.429 s: the next piece of the first line;
        # 16.3 s, after its last piece: the second line.
        self.assertEqual(len(delays), 3)
        self.assertAlmostEqual(delays[0], 134, delta=30)
        self.assertAlmostEqual(delays[1], 429, delta=30)
        self.assertAlmostEqual(delays[2], 300, delta=30)

    def animations(self, on):
        """Set gtk-enable-animations (put back after the test)."""
        from gi.repository import Gtk

        settings = Gtk.Settings.get_default()
        before = settings.get_property('gtk-enable-animations')
        self.addCleanup(settings.set_property, 'gtk-enable-animations', before)
        settings.set_property('gtk-enable-animations', on)

    def sung(self):
        """The timed labels' sung state, row by row: {position: (main, background)}."""
        return {position: (box.label.sung, box.background.sung)
                for position, box in sorted(self.view._rows.items())}

    def test_only_the_current_row_lights_its_pieces(self):
        """The current row's timed labels light the pieces sung (its background on its own
        timing); every other row's are drawn plainly; a seek moves the lighting with the
        line. Word-timed rows are `timed` (no fade into current)."""
        from applemusic.lyrics import Sung

        self.animations(False)
        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(lambda: 8 in self.view._rows))
        self.player.apply({'position': 17.5})
        self.assertTrue(wait_for(lambda: self.view._current == 1))
        sung = self.sung()
        # I, keep, the, lan: four pieces begun; the background's starts at 18.68 s.
        self.assertEqual(sung.pop(1), (Sung(4, None), Sung(0, None)))
        self.assertEqual(set(sung.values()), {(None, None)})
        self.assertTrue(self.view._rows[1].has_css_class('timed'))
        self.player.apply({'position': 19.0})
        self.assertEqual(self.sung()[1], (Sung(7, None), Sung(1, None)))
        self.player.apply({'position': 21.0})
        self.assertTrue(wait_for(lambda: self.view._current == 2))
        sung = self.sung()
        self.assertEqual(sung.pop(2), (Sung(3, None), None))   # no background vocals
        self.assertEqual(set(sung.values()), {(None, None)})
        # In a break nothing is lit: the row is current for its dots.
        self.player.apply({'position': 47.0})
        self.assertTrue(wait_for(lambda: self.view._current == 8))
        self.assertEqual(set(self.sung().values()), {(None, None)})

    def test_a_sweep_with_animations_and_whole_pieces_without(self):
        from applemusic.lyrics import Sung

        self.animations(True)
        self.play(fixture('lyrics_syllable.json'))
        self.player.apply({'position': 17.5})
        self.assertTrue(wait_for(lambda: self.view._current == 1))
        # "lan" from 17.38 s to 17.74 s: a third of it sung.
        self.assertEqual(self.sung()[1][0], Sung(3, (17500 - 17380) / 360))
        self.animations(False)
        self.assertEqual(self.sung()[1][0], Sung(4, None))

    def test_the_sweep_ticks_only_while_a_piece_is_sung(self):
        """The sweep's tick runs while the tab is shown, the music plays and a piece of the
        current line is being sung; not paused, hidden, in a gap between lines, after a song
        change, or with animations off."""
        self.animations(True)
        self.view.set_active(True)
        self.addCleanup(self.view.set_active, False)
        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(lambda: 1 in self.view._rows))

        def ticking():
            return self.view._sweep_tick is not None

        self.player.apply({'state': 'playing', 'position': 17.5})
        self.assertTrue(ticking())
        self.player.apply({'state': 'paused'})
        self.assertFalse(ticking())
        self.player.apply({'state': 'playing'})
        self.assertTrue(ticking())
        self.view.set_active(False)
        self.assertFalse(ticking())
        self.view.set_active(True)
        self.assertTrue(ticking())
        # Between the background's end (19.8 s) and the next line (20.1 s).
        self.player.apply({'position': 19.85})
        self.assertFalse(ticking())
        self.player.apply({'position': 17.5})
        self.assertTrue(ticking())
        self.animations(False)
        self.assertFalse(ticking())
        self.animations(True)
        self.assertTrue(ticking())
        self.play(fixture('lyrics.json'))
        self.player.apply({'state': 'playing', 'position': 20})
        self.assertFalse(ticking())     # line-timed: nothing to sweep

    def test_the_tick_follows_the_estimate(self):
        """Each frame the tick lights what the estimate has reached, and stops itself at
        the end of the line's pieces."""
        self.animations(True)
        self.view.set_active(True)
        self.addCleanup(self.view.set_active, False)
        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(lambda: 1 in self.view._rows))
        self.player.apply({'state': 'playing', 'position': 19.7})
        self.assertTrue(self.view._sweep_tick is not None)
        before = self.sung()[1][1]
        self.assertTrue(wait_for(lambda: self.sung()[1][1] != before), self.sung()[1])
        # The background ends at 19.8 s: the tick goes by itself.
        self.assertTrue(wait_for(lambda: self.view._sweep_tick is None, timeout=2))

    def test_the_lyrics_hold_until_a_seek(self):
        """The estimate falling back by less than HOLD_BACK (a pause reports the last whole
        second) leaves the lyrics where they were; further back is a seek, followed."""
        self.animations(False)
        self.play(fixture('lyrics_syllable.json'))
        self.player.apply({'position': 16.4})
        self.assertTrue(wait_for(lambda: self.view._current == 1))
        moment = self.view._moment
        self.player.apply({'position': 16.0})   # back before the line's start
        self.assertEqual((self.view._current, self.view._moment), (1, moment))
        self.player.apply({'position': 14.0})
        self.assertEqual(self.view._current, 0)

    def test_a_recycled_row_never_keeps_its_lights(self):
        """A row bound while its line is current lights its pieces; bound again where it is
        not, or to a line timed as a whole, it is drawn plainly at once."""
        from applemusic.lyrics import Lyrics, Moment, Sung

        lyrics = Lyrics({'synced': True, 'lines': [
            {'startMs': 0, 'text': 'One'}, {'startMs': 500, 'text': 'Two'},
            {'startMs': 800, 'text': 'Three'},
            {'startMs': 1000, 'endMs': 2000, 'text': 'Low tide',
             'words': [{'startMs': 1000, 'endMs': 1500, 'text': 'Low '},
                       {'startMs': 1500, 'endMs': 2000, 'text': 'tide'}]}]})
        self.view._lyrics = lyrics
        self.view._sweep = False
        self.view._position = 1.6
        self.addCleanup(setattr, self.view, '_lyrics', None)
        item = make_list_item()
        self.view._on_setup(None, item)
        states = []
        for moment, line in ((Moment(3, False, 2), lyrics.lines.get_item(3)),
                             (Moment(2, False, 0), lyrics.lines.get_item(3)),
                             (Moment(3, False, 2), lyrics.lines.get_item(3))):
            self.view._moment = moment
            item.line = line
            self.view._on_bind(None, item)
            states.append(item.child.line.label.sung)
            self.view._on_unbind(None, item)
        self.assertEqual(states, [Sung(2, None), None, Sung(2, None)])
        self.view._lyrics = Lyrics(fixture('lyrics.json'))  # line-timed, at the same row
        self.view._moment = Moment(3, False, 0)
        item.line = self.view._lyrics.lines.get_item(3)
        self.view._on_bind(None, item)
        self.assertIsNone(item.child.line.label.sung)

    def test_the_measure_of_a_duets_lines(self):
        from applemusic.widgets.lyrics import duet_measure

        self.assertEqual(duet_measure(1000), 600)   # Apple's share, in a wide list
        self.assertEqual(duet_measure(336), 280)    # the least, in a narrow one
        self.assertEqual(duet_measure(200), 200)    # never wider than the list
        self.assertEqual(duet_measure(0), 0)

    def test_a_duets_sides_mirrored_right_to_left(self):
        """In the list, the lead's boxes start at the row's start, the second singer's end
        at its end and a group's sit in the middle, their text aligned the same way; right
        to left, GTK mirrors the margins and the labels' alignment. A new width gives the
        rows bound a new margin; a song that is not a duet has its rows across the list."""
        from gi.repository import Gtk, Pango

        from applemusic.widgets.lyrics import duet_measure

        sung = (0, 4, 8)   # the fixture's first lines of v1, v2 and v3

        def places():
            """(the box's x in its row, its width, the row's width, the main label's Pango
            alignment) for the lead's, the second singer's and the group's rows."""
            result = []
            for position in sung:
                box = self.view._rows[position]
                ok, bounds = box.compute_bounds(box.get_parent())
                self.assertTrue(ok)
                result.append((round(bounds.get_x()), box.get_width(),
                               box.get_parent().get_width(),
                               box.label.get_layout().get_alignment()))
            return result

        def laid_out():
            rows = self.view._rows
            return (self.view._inset > 0 and all(position in rows for position in sung)
                    and all(rows[position].get_width() > 0 for position in sung))

        self.play(fixture('lyrics_syllable.json'))
        self.assertTrue(wait_for(laid_out))
        width = self.view._width
        inset = width - duet_measure(width)
        self.assertEqual(self.view._inset, inset)
        self.assertTrue(wait_for(lambda: places()[0][1] == places()[0][2] - inset), places())
        row = places()[0][2]
        self.assertEqual(places(), [(0, row - inset, row, Pango.Alignment.LEFT),
                                    (inset, row - inset, row, Pango.Alignment.RIGHT),
                                    (inset // 2, row - inset, row, Pango.Alignment.CENTER)])

        # A widget's own direction is not its children's: the default is (screenshot.py's
        # --rtl sets it too).
        default = Gtk.Widget.get_default_direction()
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
        self.addCleanup(Gtk.Widget.set_default_direction, default)
        self.assertTrue(wait_for(lambda: places()[0][0] == inset), places())
        self.assertEqual([(x, align) for x, _width, _row, align in places()],
                         [(inset, Pango.Alignment.RIGHT), (0, Pango.Alignment.LEFT),
                          (inset - inset // 2, Pango.Alignment.CENTER)])
        Gtk.Widget.set_default_direction(default)

        # A wider list: the rows bound take the new margin.
        self.view._width = width + 400
        self.view._update_inset()
        self.assertEqual(alignment(self.view._rows[4])[2:],
                         (width + 400 - duet_measure(width + 400), 0))

        # Not a duet: across the list.
        self.play(fixture('lyrics_localized.json'))
        self.assertTrue(wait_for(lambda: 0 in self.view._rows
                                 and self.view._rows[0].label.get_label() == FIRST[0]))
        self.assertEqual({alignment(box) for box in self.view._rows.values()},
                         {(0.0, 'left', 0, 0)})

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
                          if rows[position].get_parent().has_css_class('stanza')], [4])
        # The gap is the row's margin: the box (which draws the highlight) is no taller than
        # its neighbour without one, and starts lower in its row.
        self.assertTrue(wait_for(lambda: rows[4].get_height() > 0))
        self.assertEqual(rows[4].get_height(), rows[3].get_height())
        ok, bounds = rows[4].compute_bounds(rows[4].get_parent().get_parent())
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

    def test_the_unsynced_text_puts_the_background_under_its_line(self):
        answer = {'synced': False, 'lines': [
            {'text': '潮', 'background': '(潮)', 'translation': 'Tide',
             'translationBackground': '(tide)'},
            {'text': '', 'background': '(Oh oh)'}, {'text': '風'}]}
        self.play(answer)
        self.assertEqual(self.view.text_label.get_text(), '潮\n(潮)\n(Oh oh)\n風')
        self.assertEqual(self.view.text_label.get_text(), self.player.lyrics.text)
        self.app.settings.set_boolean('lyrics-translations', True)
        self.assertEqual(self.view.text_label.get_text(),
                         '潮\nTide\n(潮)\n(tide)\n(Oh oh)\n風')


@requires_gtk
class PieceGeometryTest(unittest.TestCase):
    """Where a LyricLabel's pieces are drawn (piece_segments): by Pango's byte indices, so
    multi-byte text maps right; one segment for each line a piece is on; right to left from
    the right; measured again whenever the layout changes; and the mask they make."""

    def label(self, words, width=-1):
        from gi.repository import Pango

        from applemusic.lyrics import byte_spans
        from applemusic.widgets.lyrics import LyricLabel

        label = LyricLabel(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                           label=''.join(word.text for word in words))
        layout = label.get_layout()
        layout.set_width(width if width < 0 else width * Pango.SCALE)
        return label, layout, byte_spans(words)

    def words(self, *texts):
        from applemusic.lyrics import Word

        return tuple(Word(index, index + 1, text) for index, text in enumerate(texts))

    def test_multi_byte_pieces_sit_where_pango_draws_them(self):
        from gi.repository import Pango

        from applemusic.widgets.lyrics import piece_segments

        _label, layout, spans = self.label(self.words('夜', '明', 'け ', 'café ', 'ok'))
        segments = piece_segments(layout, spans)
        self.assertEqual([len(piece) for piece in segments], [1] * 5)
        for span, (piece,) in zip(spans, segments, strict=True):
            start, end, y, height = piece
            self.assertAlmostEqual(start, layout.index_to_pos(span.first).x / Pango.SCALE)
            self.assertGreater(end, start)
            self.assertEqual(y, 0)
            self.assertGreater(height, 0)
        # Each piece ends where the next begins: no gap, no overlap.
        for (before,), (after,) in zip(segments, segments[1:], strict=False):
            self.assertAlmostEqual(before[1], after[0])

    def test_a_wrapped_line(self):
        from applemusic.widgets.lyrics import piece_segments

        words = self.words('Grey ', 'morn', 'ing ', 'on ', 'the ', 'jet', 'ty')
        _label, layout, spans = self.label(words, width=90)
        self.assertGreater(layout.get_line_count(), 1)
        segments = piece_segments(layout, spans)
        ys = [piece[0][2] for piece in segments]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(ys[0], 0)
        self.assertGreater(ys[-1], 0)
        # The first piece on the second line starts at its left again.
        second = ys.index(next(y for y in ys if y > 0))
        self.assertLess(segments[second][0][0], segments[second - 1][0][0])
        # A piece too long for a line is split across the lines it is on.
        _label, layout, spans = self.label(self.words('Ooooooooooooooooooooooh'), width=60)
        (piece,) = piece_segments(layout, spans)
        self.assertEqual(len(piece), layout.get_line_count())
        self.assertEqual(sorted(segment[2] for segment in piece), [s[2] for s in piece])

    def test_right_to_left_pieces_run_from_the_right(self):
        from applemusic.widgets.lyrics import piece_segments

        _label, layout, spans = self.label(self.words('שלום ', 'ים'))
        segments = piece_segments(layout, spans)
        (first,), (second,) = segments
        self.assertGreater(first[0], first[1])      # from its right edge to its left
        self.assertGreater(first[1] + 0.5, second[0])  # the second piece is to its left

    def test_spans_that_do_not_fit_have_no_segments(self):
        from applemusic.lyrics import Span
        from applemusic.widgets.lyrics import piece_segments

        _label, layout, _spans = self.label(self.words('Low'))
        self.assertEqual(piece_segments(layout, (Span(0, 5, 6),)), ())

    def test_the_segments_are_measured_again_when_the_layout_changes(self):
        from gi.repository import Gtk, Pango

        from applemusic.lyrics import Sung, byte_spans

        words = self.words('Grey ', 'morn', 'ing ', 'on ', 'the ', 'jet', 'ty')
        label, _layout, spans = self.label(words)
        label.sing(spans, Sung(2, 0.5))
        first = label.segments()
        self.assertIs(label.segments(), first)          # kept while nothing changes
        label.get_layout().set_width(90 * Pango.SCALE)  # wraps now: another serial
        wrapped = label.segments()
        self.assertIsNot(wrapped, first)
        self.assertNotEqual(wrapped, first)
        # Another font, once the label's style is worked out (in a window).
        window = Gtk.Window(child=label)
        window.present()
        self.addCleanup(window.destroy)
        self.assertTrue(wait_for(lambda: label.get_mapped()))
        before = label.segments()
        label.add_css_class('title-1')
        self.assertTrue(wait_for(lambda: label.segments() != before), before)
        other = self.words('夜', '明', 'け')
        label.set_label(''.join(word.text for word in other))
        label.sing(byte_spans(other), Sung(1, None))
        self.assertEqual(len(label.segments()), 3)
        left_to_right = label.segments()
        label.set_direction(Gtk.TextDirection.RTL)
        self.assertTrue(wait_for(lambda: label.segments() is not left_to_right))
        label.sing((), None)
        self.assertIsNone(label.sung)

    def test_the_mask(self):
        """Whole pieces at full opacity, merged along a line; the piece being sung up to a
        soft edge SWEEP_EDGE either side of where it has got, in its own direction and across
        its lines."""
        from applemusic.lyrics import Sung
        from applemusic.widgets.lyrics import mask_parts

        line = (((0, 10, 0, 20),), ((10, 30, 0, 20),), ((30, 50, 0, 20),))
        self.assertEqual(mask_parts(line, Sung(2, None)), ([(0, 0, 30, 20)], None))
        self.assertEqual(mask_parts(line, Sung(1, 0.5)), ([(0, 0, 12, 20)], (12, 28, 0, 20)))
        self.assertEqual(mask_parts(line, Sung(0, 0.1)), ([], (0, 9, 0, 20)))
        self.assertEqual(mask_parts(line, Sung(0, None)), ([], None))
        right_to_left = (((50, 30, 0, 20),),)
        self.assertEqual(mask_parts(right_to_left, Sung(0, 0.5)),
                         ([(48, 0, 2, 20)], (48, 32, 0, 20)))
        wrapped = (((40, 60, 0, 20), (0, 20, 20, 20)),)
        self.assertEqual(mask_parts(wrapped, Sung(0, 0.75)),
                         ([(40, 0, 20, 20), (0, 20, 2, 20)], (2, 18, 20, 20)))

    def test_drawn_with_and_without_lights(self):
        """A label sung in part draws through its mask; one plain, all sung or none sung
        without it."""
        from gi.repository import Gtk

        from applemusic.lyrics import Sung

        words = self.words('Low ', 'tide')
        label, _layout, spans = self.label(words)
        window = Gtk.Window(child=label)
        window.present()
        self.addCleanup(window.destroy)
        self.assertTrue(wait_for(lambda: label.get_width() > 0))

        def node_types(sung):
            label.sing(spans, sung)
            snapshot = Gtk.Snapshot()
            type(label).do_snapshot(label, snapshot)
            node = snapshot.to_node()
            return type(node).__name__ if node is not None else None

        self.assertEqual(node_types(None), node_types(Sung(2, None)))
        self.assertEqual(node_types(Sung(0, None)), 'OpacityNode')
        self.assertEqual(node_types(Sung(1, 0.5)), 'MaskNode')
        self.assertEqual(node_types(Sung(1, None)), 'MaskNode')


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
