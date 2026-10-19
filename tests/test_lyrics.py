# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""src/lyrics.py: the engine's lyrics answer as a model, and the current line by position."""

import json
import pathlib
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.lyrics import (LyricLine, Lyrics, Word, folded, is_secondary,
                               line_index_at, parse_lines)

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

    def test_the_views_show_the_background_folded_into_its_line(self):
        self.assertEqual(folded('Harbour lights', '(lights)'), 'Harbour lights (lights)')
        self.assertEqual(folded('', '(Oh oh)'), '(Oh oh)')
        self.assertEqual(folded('Tide', ''), 'Tide')
        lyrics = Lyrics({'synced': True, 'lines': [
            {'startMs': 1000, 'text': '\u6f6e', 'background': '(\u6f6e)', 'stanza': True,
             'pronunciation': 'Shio', 'pronunciationBackground': '(shio)',
             'translation': 'Tide', 'translationBackground': '(tide)'},
            {'startMs': 2000, 'text': '', 'background': '(Oh oh)', 'stanza': True},
            {'startMs': 3000, 'text': 'Harbour lights'}]})
        first = lyrics.lines.get_item(0)
        self.assertEqual((first.shown_text, first.shown_pronunciation, first.shown_translation),
                         ('\u6f6e (\u6f6e)', 'Shio (shio)', 'Tide (tide)'))
        self.assertEqual(lyrics.lines.get_item(2).shown_pronunciation, '')
        self.assertEqual(lyrics.text, '\u6f6e (\u6f6e)\n\n(Oh oh)\nHarbour lights')
        self.assertTrue(lyrics.has_pronunciations and lyrics.has_translations)
        background_only = Lyrics({'lines': [{'text': 'Sea', 'pronunciationBackground': '(umi)',
                                             'translationBackground': '(sea!)'}]})
        self.assertTrue(background_only.has_pronunciations)
        self.assertTrue(background_only.has_translations)

    def test_an_answer_without_the_new_fields_reads_as_before(self):
        line = Lyrics(fixture('lyrics_localized.json')).lines.get_item(0)
        self.assertEqual((line.background, line.agent, line.words, line.pronunciation_words),
                         ('', '', (), ()))
        self.assertEqual(line.shown_text, line.text)
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

    def test_instrumental_breaks(self):
        """Apple shows a break before the first verse when it starts after 9 s, and between
        two verses more than 9 s apart."""
        self.assertGreater(self.lines[0].start_ms, 9000)
        gaps = [line.start_ms - previous.end_ms
                for previous, line in zip(self.lines, self.lines[1:], strict=False)
                if line.stanza]
        self.assertGreaterEqual(sum(gap > 9000 for gap in gaps), 2)
        self.assertEqual(sum(line.stanza for line in self.lines), 5)


if __name__ == '__main__':
    unittest.main()
