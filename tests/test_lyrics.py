# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""src/lyrics.py: the engine's lyrics answer as a model, the current line by position, and
the instrumental breaks between verses with their dots."""

import json
import pathlib
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.lyrics import (DOTS, END, INSTRUMENTAL_GAP_MS, MIDDLE, NO_MOMENT, START,
                               Break, LyricLine, Lyrics, Moment, Word, dot_times, dots_lit,
                               instrumental_breaks, is_secondary, line_index_at, parse_lines,
                               side)

FIXTURES = pathlib.Path(__file__).parent / 'fixtures'


def fixture(name='lyrics.json'):
    with open(FIXTURES / name, encoding='utf-8') as file:
        return json.load(file)


def firsts(lines):
    """The lines' times, text, stanza, pronunciation and translation."""
    return [line[:6] for line in lines]


def pieces(*words):
    """Words as the answer has them, from (start, end, text)."""
    return [{'startMs': start, 'endMs': end, 'text': text} for start, end, text in words]


class ParseTest(unittest.TestCase):
    def test_lines_in_time_order_with_blanks_and_junk_dropped(self):
        answer = {'synced': True, 'lines': [
            {'startMs': 5000, 'endMs': 6000, 'text': 'Second'},
            {'startMs': 1000, 'endMs': 2000, 'text': '  First  '},
            {'startMs': 3000, 'endMs': 4000, 'text': '   '},
            'not a line',
            {'startMs': None, 'endMs': 'x', 'text': 'Untimed'},
            {'text': None},
        ]}
        self.assertEqual(firsts(parse_lines(answer)), [
            (0, 0, 'Untimed', False, '', ''), (1000, 2000, 'First', False, '', ''),
            (5000, 6000, 'Second', False, '', '')])

    def test_unsynced_lines_keep_their_order(self):
        answer = {'synced': False, 'lines': [{'text': 'B'}, {'text': 'A'}]}
        self.assertEqual([line[2] for line in parse_lines(answer)], ['B', 'A'])

    def test_entities_are_decoded_and_stanzas_kept(self):
        answer = {'synced': False, 'lines': [
            {'text': 'Rock &amp; Roll &#8217;til dawn', 'stanza': True},
            {'text': 'Fish &amp;amp; chips'},  # escaped twice: decoded once
            {'text': ' &#32; ', 'stanza': True},  # blank once decoded
            {'text': 'AT&T &lt;3', 'stanza': 'yes'}]}
        self.assertEqual(firsts(parse_lines(answer)), [
            (0, 0, 'Rock & Roll \u2019til dawn', True, '', ''),
            (0, 0, 'Fish &amp; chips', False, '', ''), (0, 0, 'AT&T <3', False, '', '')])

    def test_pronunciations_and_translations_are_read_as_the_text_is(self):
        answer = {'synced': True, 'lines': [
            {'startMs': 1000, 'text': '\u6f6e\u98a8', 'pronunciation': ' Shiokaze &amp; umi ',
             'translation': 'Sea &amp; wind'},
            {'startMs': 2000, 'text': 'Oh oh', 'pronunciation': 'Oh oh',  # the same: none
             'translation': 'Oh oh'},
            {'startMs': 3000, 'text': 'Tide', 'pronunciation': 7, 'translation': None},
            {'startMs': 4000, 'text': '  ', 'pronunciation': 'Nothing to say it of'}]}
        self.assertEqual([(line.pronunciation, line.translation) for line in parse_lines(answer)],
                         [('Shiokaze & umi', 'Sea & wind'), ('', ''), ('', '')])

    def test_nothing_from_nothing(self):
        for answer in (None, {}, {'lines': None}, {'lines': 'x'}, [], 'text'):
            self.assertEqual(parse_lines(answer), [], answer)


class IndexTest(unittest.TestCase):
    STARTS = [1000, 5000, 9000]

    def test_before_the_first_line(self):
        self.assertEqual(line_index_at(self.STARTS, 0), -1)
        self.assertEqual(line_index_at(self.STARTS, 0.999), -1)
        self.assertEqual(line_index_at(self.STARTS, -3), -1)

    def test_on_a_line_and_between_lines(self):
        self.assertEqual(line_index_at(self.STARTS, 1.0), 0)
        self.assertEqual(line_index_at(self.STARTS, 2.5), 0)
        self.assertEqual(line_index_at(self.STARTS, 4.999), 0)  # the gap keeps the line
        self.assertEqual(line_index_at(self.STARTS, 5.0), 1)
        self.assertEqual(line_index_at(self.STARTS, 8.9), 1)

    def test_after_the_last_line(self):
        self.assertEqual(line_index_at(self.STARTS, 9.0), 2)
        self.assertEqual(line_index_at(self.STARTS, 600), 2)

    def test_no_lines(self):
        self.assertEqual(line_index_at([], 4), -1)


class LyricsObjectTest(unittest.TestCase):
    def test_the_fixture(self):
        lyrics = Lyrics(fixture(), '1000000001')
        self.assertTrue(lyrics.synced)
        self.assertEqual(lyrics.catalog_id, '1000000001')
        self.assertEqual(len(lyrics), 24)
        first = lyrics.lines.get_item(0)
        self.assertIsInstance(first, LyricLine)
        self.assertEqual((first.start_ms, first.end_ms), (1200, 4800))
        self.assertEqual(first.text, 'Fog on the water, a bell on the buoy')
        self.assertEqual(lyrics.index_at(0), -1)
        self.assertEqual(lyrics.index_at(1.2), 0)
        self.assertEqual(lyrics.index_at(24.0), 5)
        self.assertEqual(lyrics.index_at(46.5), 10)
        self.assertEqual(lyrics.index_at(500), 23)
        self.assertEqual(lyrics.start_of(5), 23.1)
        self.assertEqual(lyrics.start_of(99), 0.0)
        self.assertEqual([index for index in range(len(lyrics))
                          if lyrics.lines.get_item(index).stanza], [0, 4, 8, 12, 16, 20])
        # A blank line before each stanza but the first.
        self.assertEqual(lyrics.text.splitlines()[3:6],
                         ['And nobody answers the call', '', 'Low tide warning on the radio'])
        self.assertEqual(len(lyrics.text.splitlines()), 24 + 5)

    def test_unsynced_lyrics_have_text_and_no_current_line(self):
        lyrics = Lyrics({'synced': False, 'lines': [{'text': 'One'}, {'text': 'Two'}]})
        self.assertFalse(lyrics.synced)
        self.assertEqual(len(lyrics), 2)
        self.assertEqual(lyrics.text, 'One\nTwo')
        self.assertEqual(lyrics.index_at(30), -1)

    def test_stanzas_are_parted_by_a_blank_line(self):
        lyrics = Lyrics({'synced': True, 'lines': [
            {'startMs': 9000, 'text': 'Chorus', 'stanza': True},
            {'startMs': 1000, 'text': 'Verse one', 'stanza': True},
            {'startMs': 2000, 'text': 'Verse two'},
            {'startMs': 10000, 'text': 'Chorus again'}]})
        self.assertEqual(lyrics.text, 'Verse one\nVerse two\n\nChorus\nChorus again')
        self.assertEqual(len(lyrics), 4)
        self.assertEqual([line.stanza for line in lyrics.lines], [True, False, True, False])

    def test_pronunciations_and_translations(self):
        lyrics = Lyrics(fixture('lyrics_localized.json'), '1000000008')
        self.assertTrue(lyrics.has_pronunciations)
        self.assertTrue(lyrics.has_translations)
        self.assertEqual(lyrics.lines.get_item(0).translation,
                         'Fog on the water, a bell on the buoy')
        first = lyrics.lines.get_item(0)
        self.assertEqual((first.text, first.pronunciation),
                         ('\u9727\u306e\u6d77\u306b\u9418\u304c\u9cf4\u308b',
                          'Kiri no umi ni kane ga naru'))
        self.assertTrue(all(line.pronunciation for line in lyrics.lines))
        # The text is the lines' own; the view adds the pronunciations when shown.
        self.assertNotIn('Kiri', lyrics.text)
        plain = Lyrics(fixture(), '1000000001')
        self.assertFalse(plain.has_pronunciations or plain.has_translations)
        self.assertEqual(lyrics.lines.get_item(1).pronunciation, 'Minato no akari o kazoeteru')
        self.assertFalse(Lyrics({'synced': False, 'lines': [{'text': 'One'}]}).has_pronunciations)

    def test_synced_without_lines_is_not_synced(self):
        lyrics = Lyrics({'synced': True, 'lines': []})
        self.assertFalse(lyrics.synced)
        self.assertEqual(len(lyrics), 0)
        self.assertEqual(lyrics.text, '')


def timed(*lines):
    """Synced lyrics from (start, end, stanza) for each line, its text invented."""
    return Lyrics({'synced': True, 'lines': [
        {'startMs': start, 'endMs': end, 'text': f'Line {index}', 'stanza': stanza}
        for index, (start, end, stanza) in enumerate(lines)]})


def breaks(*lines):
    return [line.instrumental for line in timed(*lines).lines]


class BreaksTest(unittest.TestCase):
    """Apple's instrumental breaks: before a first line more than 9 s in, and between two
    verses more than 9 s apart."""

    def test_the_rule_is_nine_seconds(self):
        self.assertEqual(INSTRUMENTAL_GAP_MS, 9000)
        self.assertEqual(DOTS, 3)

    def test_an_intro(self):
        self.assertEqual(breaks((9001, 12000, True)), [Break(0, 9000)])
        self.assertEqual(breaks((12400, 16000, True), (16300, 19800, False)),
                         [Break(0, 12399), None])
        # Exactly 9 s, or less: none.
        self.assertEqual(breaks((9000, 12000, True)), [None])
        self.assertEqual(breaks((1200, 4800, True)), [None])
        # Whether the first line opens a verse or not.
        self.assertEqual(breaks((20000, 24000, False)), [Break(0, 19999)])

    def test_between_verses(self):
        # The next verse 9.001 s after the previous line's end: from that end to the line.
        self.assertEqual(breaks((1000, 2000, True), (2500, 4000, False),
                                (13001, 15000, True)),
                         [None, None, Break(4001, 13000)])
        # Exactly 9 s, or less: none.
        self.assertEqual(breaks((1000, 2000, True), (2500, 4000, False),
                                (13000, 15000, True)), [None, None, None])
        self.assertEqual(breaks((1000, 2000, True), (5000, 6000, True)), [None, None])

    def test_none_within_a_verse(self):
        self.assertEqual(breaks((1000, 2000, True), (30000, 32000, False),
                                (60000, 62000, False)), [None, None, None])

    def test_from_the_latest_end(self):
        """Lines that overlap (a duet): the break starts after the last voice has ended."""
        self.assertEqual(breaks((1000, 9000, True), (2000, 4000, False),
                                (20000, 22000, True)), [None, None, Break(9001, 19999)])
        # ...which may leave no break at all.
        self.assertEqual(breaks((1000, 12000, True), (2000, 3000, False),
                                (14000, 16000, True)), [None, None, None])

    def test_none_after_a_line_without_an_end(self):
        self.assertEqual(breaks((1000, 0, True), (20000, 22000, True)), [None, None])
        self.assertEqual(breaks((1000, 2000, True), (3000, 3000, False),
                                (20000, 22000, True)), [None, None, None])
        # A line without an end at the start of a verse ends nothing: the break after the
        # next is from its end.
        self.assertEqual(breaks((1000, 2000, True), (3000, 0, True), (4000, 5000, False),
                                (20000, 22000, True)), [None, None, None, Break(5001, 19999)])

    def test_none_for_unsynced_or_empty_lyrics(self):
        unsynced = Lyrics({'synced': False, 'lines': [
            {'startMs': 20000, 'endMs': 22000, 'text': 'One', 'stanza': True},
            {'startMs': 40000, 'endMs': 42000, 'text': 'Two', 'stanza': True}]})
        self.assertEqual([line.instrumental for line in unsynced.lines], [None, None])
        self.assertEqual(unsynced.moment_at(30), NO_MOMENT)
        self.assertIsNone(unsynced.next_change(0))
        empty = Lyrics({'synced': True, 'lines': []})
        self.assertEqual((empty.moment_at(0), empty.next_change(0)), (NO_MOMENT, None))
        self.assertEqual(instrumental_breaks([]), [])
        self.assertIsNone(LyricLine().instrumental)

    def test_the_dots_light_across_a_break(self):
        """The first dot as the break begins, the next at each further third."""
        instrumental = Break(4001, 13000)
        self.assertEqual(dot_times(instrumental), [4001, 7001, 10001])
        self.assertEqual([dots_lit(instrumental, ms) for ms in
                          (4001, 7000, 7001, 10000, 10001, 13000)], [1, 1, 2, 2, 3, 3])
        # A length that does not divide: each step at the first millisecond past its third.
        odd = Break(0, 9999)
        self.assertEqual(dot_times(odd), [0, 3334, 6667])
        self.assertEqual([dots_lit(odd, ms) for ms in (3333, 3334, 6666, 6667)], [1, 2, 2, 3])
        # Every time dot_times() gives, dots_lit() steps there and not a millisecond before.
        for start, end in ((0, 12399), (43501, 53999), (85001, 96499)):
            for step, ms in enumerate(dot_times(Break(start, end)), 1):
                self.assertEqual(dots_lit(Break(start, end), ms), step)
                if ms > start:
                    self.assertEqual(dots_lit(Break(start, end), ms - 1), step - 1)

    def test_the_moments_through_a_song(self):
        """moment_at() through an intro, a verse, a break and the next verse; next_change()
        walks from one change to the next."""
        lyrics = timed((12000, 14000, True), (14500, 16000, False), (28000, 30000, True))
        self.assertEqual(lyrics.moment_at(0), Moment(0, True, 1))
        self.assertEqual(lyrics.moment_at(4.0), Moment(0, True, 2))
        self.assertEqual(lyrics.moment_at(11.999), Moment(0, True, 3))
        self.assertEqual(lyrics.moment_at(12), Moment(0, False, 0))
        self.assertEqual(lyrics.moment_at(16), Moment(1, False, 0))   # to its end...
        self.assertEqual(lyrics.moment_at(16.001), Moment(2, True, 1))  # ...then the break
        self.assertEqual(lyrics.moment_at(27.999), Moment(2, True, 3))
        self.assertEqual(lyrics.moment_at(28), Moment(2, False, 0))
        self.assertEqual(lyrics.moment_at(600), Moment(2, False, 0))
        moments, at = [], 0.0
        while at is not None:
            moments.append((at, lyrics.moment_at(at)))
            at = lyrics.next_change(at)
        self.assertEqual(moments, [
            (0.0, Moment(0, True, 1)), (4.0, Moment(0, True, 2)), (8.0, Moment(0, True, 3)),
            (12.0, Moment(0, False, 0)), (14.5, Moment(1, False, 0)),
            (16.001, Moment(2, True, 1)), (20.001, Moment(2, True, 2)),
            (24.001, Moment(2, True, 3)), (28.0, Moment(2, False, 0))])
        # Without breaks, the lines as index_at() has them, from before the first.
        plain = timed((1000, 2000, True), (3000, 4000, False))
        self.assertEqual(plain.moment_at(0.5), NO_MOMENT)
        self.assertEqual(plain.next_change(0.5), 1.0)
        self.assertEqual(plain.moment_at(3.5), Moment(1, False, 0))
        self.assertIsNone(plain.next_change(3.5))

    def test_the_lines_read_as_before(self):
        """The breaks are the lines' own: the store, the text, the line current, a line's
        start and what the lyrics have are as they were."""
        lyrics = timed((12000, 14000, True), (14500, 16000, False), (28000, 30000, True))
        self.assertEqual(len(lyrics), 3)
        self.assertEqual([line.text for line in lyrics.lines], ['Line 0', 'Line 1', 'Line 2'])
        self.assertEqual(lyrics.text, 'Line 0\nLine 1\n\nLine 2')
        self.assertEqual(lyrics.index_at(0), -1)
        self.assertEqual(lyrics.index_at(20), 1)    # the last line started, as before
        self.assertEqual((lyrics.start_of(0), lyrics.start_of(2)), (12.0, 28.0))
        self.assertFalse(lyrics.has_pronunciations or lyrics.has_translations or lyrics.duet)


class WordsTest(unittest.TestCase):
    """The timed pieces of a line's vocals: carried when they are good, else none."""

    WORDS = pieces((1000, 1400, 'Har'), (1400, 1800, 'bour '), (1800, 2500, 'lights'))

    def words(self, words, text='Harbour lights', synced=True, start=1000, end=3000):
        answer = {'synced': synced, 'lines': [
            {'startMs': start, 'endMs': end, 'text': text, 'words': words}]}
        return parse_lines(answer)[0].words

    def test_words_that_join_to_the_text(self):
        self.assertEqual(self.words(self.WORDS), (
            Word(1000, 1400, 'Har'), Word(1400, 1800, 'bour '), Word(1800, 2500, 'lights')))
        # Read as the text is: entities decoded, the ends stripped.
        self.assertEqual(self.words(pieces((1000, 1500, ' Rock &amp; '),
                                           (1500, 2000, 'Roll ')), 'Rock &amp; Roll'),
                         (Word(1000, 1500, 'Rock & '), Word(1500, 2000, 'Roll')))
        # Two pieces at once, a piece of no length, a line without an end: all fine.
        self.assertEqual(len(self.words(pieces((1000, 1000, 'Har'), (1000, 1800, 'bour '),
                                               (1800, 2500, 'lights')), end=0)), 3)

    def test_bad_words_are_none(self):
        bad = {
            'not joining': pieces((1000, 1400, 'Har'), (1400, 1800, 'bour'),
                                  (1800, 2500, 'lights')),
            'other words': pieces((1000, 2000, 'Harbour '), (2000, 2500, 'light')),
            'ending before they start': pieces((1000, 1400, 'Har'), (1800, 1400, 'bour '),
                                               (1800, 2500, 'lights')),
            'out of order': pieces((1000, 1400, 'Har'), (1900, 2000, 'bour '),
                                   (1800, 2500, 'lights')),
            'before the line': pieces((900, 1400, 'Har'), (1400, 1800, 'bour '),
                                      (1800, 2500, 'lights')),
            'after the line': pieces((1000, 1400, 'Har'), (1400, 1800, 'bour '),
                                     (1800, 3100, 'lights')),
            'a blank piece': pieces((1000, 1400, 'Har'), (1400, 1800, 'bour '),
                                    (1800, 1900, '  '), (1900, 2500, 'lights')),
            'a time not a number': [{'startMs': '1000', 'endMs': 1400, 'text': 'Harbour '},
                                    {'startMs': 1400, 'endMs': 2500, 'text': 'lights'}],
            'a time true': [{'startMs': True, 'endMs': 1400, 'text': 'Harbour '},
                            {'startMs': 1400, 'endMs': 2500, 'text': 'lights'}],
            'a time NaN': [{'startMs': 1000, 'endMs': float('nan'), 'text': 'Harbour '},
                           {'startMs': 1400, 'endMs': 2500, 'text': 'lights'}],
            'no text': [{'startMs': 1000, 'endMs': 2500}],
            'not a piece': ['Harbour lights'],
            'not a list': 'Harbour lights',
            'empty': [],
        }
        for name, words in bad.items():
            self.assertEqual(self.words(words), (), name)
        # Unsynced lyrics have no words, whatever the answer says.
        self.assertEqual(self.words(self.WORDS, synced=False), ())

    def test_every_part_has_its_words(self):
        line = parse_lines({'synced': True, 'lines': [{
            'startMs': 1000, 'endMs': 5000, 'text': '\u6f6e', 'background': '(\u6f6e)',
            'words': pieces((1000, 2000, '\u6f6e')),
            'backgroundWords': pieces((3000, 5000, '(\u6f6e)')),
            'pronunciation': 'Shio', 'pronunciationBackground': '(shio)',
            'pronunciationWords': pieces((1000, 2000, 'Shio')),
            'pronunciationBackgroundWords': pieces((3000, 4000, '(shi'), (4000, 5000, 'o)')),
            'translation': 'Tide', 'translationBackground': '(tide)',
            'translationWords': pieces((1000, 2000, 'Tide'))}]})[0]
        self.assertEqual(line.words, (Word(1000, 2000, '\u6f6e'),))
        self.assertEqual(line.background_words, (Word(3000, 5000, '(\u6f6e)'),))
        self.assertEqual(line.pronunciation_words, (Word(1000, 2000, 'Shio'),))
        self.assertEqual(line.pronunciation_background_words,
                         (Word(3000, 4000, '(shi'), Word(4000, 5000, 'o)')))
        self.assertEqual((line.translation, line.translation_background), ('Tide', '(tide)'))
        self.assertNotIn('translation_words', line._fields)


class VocalsTest(unittest.TestCase):
    """The background vocals, the singers, and what the views show."""

    def test_background_vocals_are_their_own(self):
        lines = parse_lines({'synced': True, 'lines': [
            {'startMs': 1000, 'text': 'Harbour lights', 'background': ' (lights) '},
            {'startMs': 2000, 'text': '', 'background': '(Oh oh)'},   # background alone
            {'startMs': 3000, 'text': ' ', 'background': ' '},          # nothing: dropped
            {'startMs': 4000, 'background': 'No text at all'}]})
        self.assertEqual([(line.text, line.background) for line in lines],
                         [('Harbour lights', '(lights)'), ('', '(Oh oh)'),
                          ('', 'No text at all')])

    def test_a_pronunciation_or_translation_the_same_as_the_line_is_none(self):
        line = {'text': 'Oh oh', 'background': '(oh)'}
        same = parse_lines({'lines': [dict(line, pronunciation='Oh oh',
                                           pronunciationBackground='(oh)',
                                           translation='Oh oh', translationBackground='(oh)')]})
        self.assertEqual((same[0].pronunciation, same[0].pronunciation_background,
                          same[0].translation, same[0].translation_background),
                         ('', '', '', ''))
        other = parse_lines({'lines': [dict(line, pronunciation='Oh oh',
                                            pronunciationBackground='(ooh)')]})[0]
        self.assertEqual((other.pronunciation, other.pronunciation_background),
                         ('Oh oh', '(ooh)'))

    def test_singers(self):
        self.assertFalse(is_secondary(''))
        self.assertFalse(is_secondary('v1'))
        for agent in ('v2', 'v3', 'v1000', 'v2000'):
            self.assertTrue(is_secondary(agent), agent)
        lines = [{'startMs': 1000, 'text': 'One', 'agent': 'v1'},
                 {'startMs': 2000, 'text': 'Two', 'agent': ' v2 '},
                 {'startMs': 3000, 'text': 'Three', 'agent': 7}]
        lyrics = Lyrics({'synced': True, 'lines': lines})
        self.assertTrue(lyrics.duet)
        self.assertEqual([line.agent for line in lyrics.lines], ['v1', 'v2', ''])
        self.assertFalse(Lyrics({'synced': True, 'lines': lines[:1]}).duet)
        self.assertFalse(Lyrics({'synced': True, 'lines': [{'text': 'One'}]}).duet)

    def test_sides(self):
        # A song that is not a duet has no sides, whoever is named.
        for agent in ('', 'v1', 'v2', 'v3'):
            self.assertEqual(side(agent, False), '', agent)
        # In a duet: the lead (and a line naming no one) at the start, the second singer at
        # the end, a group, everyone or a third singer in the middle.
        self.assertEqual(side('v1', True), START)
        self.assertEqual(side('', True), START)
        self.assertEqual(side('v2', True), END)
        for agent in ('v3', 'v4', 'v1000', 'v2000'):
            self.assertEqual(side(agent, True), MIDDLE, agent)

    def test_the_lines_carry_their_side(self):
        lines = [{'startMs': 1000, 'text': 'One', 'agent': 'v1'},
                 {'startMs': 2000, 'text': 'Two', 'agent': 'v2'},
                 {'startMs': 3000, 'text': 'All', 'agent': 'v1000'},
                 {'startMs': 4000, 'text': 'Nobody'}]
        self.assertEqual([line.side for line in Lyrics({'synced': True, 'lines': lines}).lines],
                         ['start', 'end', 'middle', 'start'])
        # Only v1 sings: not a duet, no sides.
        solo = Lyrics({'synced': True, 'lines': [lines[0], lines[3]]})
        self.assertFalse(solo.duet)
        self.assertEqual([line.side for line in solo.lines], ['', ''])
        self.assertEqual(LyricLine().side, '')

    def test_the_text_puts_the_background_on_a_line_of_its_own(self):
        lyrics = Lyrics({'synced': True, 'lines': [
            {'startMs': 1000, 'text': '\u6f6e', 'background': '(\u6f6e)', 'stanza': True,
             'pronunciation': 'Shio', 'pronunciationBackground': '(shio)',
             'translation': 'Tide', 'translationBackground': '(tide)'},
            {'startMs': 2000, 'text': '', 'background': '(Oh oh)', 'stanza': True},
            {'startMs': 3000, 'text': 'Harbour lights'}]})
        first = lyrics.lines.get_item(0)
        self.assertEqual((first.text, first.background, first.pronunciation_background,
                          first.translation_background),
                         ('\u6f6e', '(\u6f6e)', '(shio)', '(tide)'))
        # Each part on its own line; a line of background vocals only is the background.
        self.assertEqual(lyrics.text, '\u6f6e\n(\u6f6e)\n\n(Oh oh)\nHarbour lights')
        self.assertTrue(lyrics.has_pronunciations and lyrics.has_translations)
        background_only = Lyrics({'lines': [{'text': 'Sea', 'pronunciationBackground': '(umi)',
                                             'translationBackground': '(sea!)'}]})
        self.assertTrue(background_only.has_pronunciations)
        self.assertTrue(background_only.has_translations)

    def test_an_answer_without_the_new_fields_reads_as_before(self):
        line = Lyrics(fixture('lyrics_localized.json')).lines.get_item(0)
        self.assertEqual((line.background, line.agent, line.words, line.pronunciation_words),
                         ('', '', (), ()))
        self.assertEqual(LyricLine().words, ())


class SyllableFixtureTest(unittest.TestCase):
    """tests/fixtures/lyrics_syllable.json, an invented word-timed duet: what the display of
    words, background vocals, singers and instrumental breaks needs is all in it."""

    def setUp(self):
        self.lyrics = Lyrics(fixture('lyrics_syllable.json'), '1000000009')
        self.lines = list(self.lyrics.lines)

    def test_every_line_is_timed_by_the_word(self):
        self.assertTrue(self.lyrics.synced)
        self.assertEqual(len(self.lines), 18)
        self.assertEqual(len(self.lyrics), 18)
        for line in self.lines:
            self.assertEqual(''.join(word.text for word in line.words), line.text)
        # Syllables: a piece with no space after it, joined to the next, in English and in
        # Japanese, whose words are not parted by spaces.
        self.assertEqual([word.text for word in self.lines[0].words],
                         ['Grey ', 'morn', 'ing ', 'on ', 'the ', 'jet', 'ty'])
        self.assertNotIn(' ', self.lines[4].text)

    def test_background_vocals_and_the_extras(self):
        backgrounds = [line for line in self.lines if line.background]
        self.assertGreaterEqual(len(backgrounds), 6)
        for line in backgrounds:
            self.assertEqual(''.join(word.text for word in line.background_words),
                             line.background)
            self.assertTrue(line.background.startswith('(') and line.background.endswith(')'))
        both = [line for line in backgrounds if line.pronunciation_background]
        self.assertEqual(len(both), 2)
        for line in both:
            self.assertTrue(line.pronunciation_words and line.pronunciation_background_words)
            self.assertTrue(line.translation_background)
        self.assertTrue(self.lyrics.has_pronunciations and self.lyrics.has_translations)
        # The English lines have no pronunciation: Apple's is the line itself.
        self.assertFalse(self.lines[0].pronunciation or self.lines[0].translation)

    def test_two_singers_and_everyone(self):
        self.assertTrue(self.lyrics.duet)
        agents = [line.agent for line in self.lines]
        self.assertEqual(set(agents), {'v1', 'v2', 'v3'})
        # Somewhere the singers take a line each in turn.
        self.assertIn(['v2', 'v1', 'v2', 'v1'], [agents[i:i + 4] for i in range(len(agents))])
        self.assertEqual({(line.agent, line.side) for line in self.lines},
                         {('v1', 'start'), ('v2', 'end'), ('v3', 'middle')})

    def test_instrumental_breaks(self):
        """Apple shows a break before the first verse when it starts after 9 s, and between
        two verses more than 9 s apart."""
        self.assertGreater(self.lines[0].start_ms, 9000)
        gaps = [line.start_ms - previous.end_ms
                for previous, line in zip(self.lines, self.lines[1:], strict=False)
                if line.stanza]
        self.assertGreaterEqual(sum(gap > 9000 for gap in gaps), 2)
        self.assertEqual(sum(line.stanza for line in self.lines), 5)
        # The intro (12.4 s), the 10.5 s gap before the third verse and the 11.5 s gap
        # before the last; the 1 s gap before the fourth has none.
        self.assertEqual([(index, line.instrumental) for index, line in enumerate(self.lines)
                          if line.instrumental], [
            (0, Break(0, 12399)), (8, Break(43501, 53999)), (16, Break(85001, 96499))])
        self.assertEqual(self.lyrics.moment_at(47), Moment(8, True, 1))
        self.assertEqual(self.lyrics.moment_at(52), Moment(8, True, 3))


if __name__ == '__main__':
    unittest.main()
