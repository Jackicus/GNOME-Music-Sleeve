# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Lyrics as a model: the engine's answer ({synced, lines: [line]}, engine.lyrics_answer's
shape) as a Lyrics object holding LyricLine GObjects in a Gio.ListStore, and the lookup of
the line current at a playback position, which the Now Playing sheet highlights.

    lyrics = Lyrics(answer, catalog_id)
    lyrics.synced          # True when the lines carry times (Apple's TTML had begin="…")
    lyrics.lines           # Gio.ListStore of LyricLine, in time order
    lyrics.text            # the lines as plain text: each line's main vocals on a line, its
                           # background vocals on a line of their own under it, a blank line
                           # before each stanza (a verse, a chorus: a line the answer marks
                           # `stanza`); the unsynced view, without its extras
    lyrics.has_pronunciations   # some line has a pronunciation (Apple's transliteration:
                                # Japanese written in Latin letters, say)
    lyrics.has_translations     # some line has a translation (into the user's language)
    lyrics.duet            # some line is sung by a secondary singer (is_secondary)
    line.side              # where the synced view puts a line (side()): '' across the view,
                           # as every line of a song that is not a duet, else START, END
                           # or MIDDLE
    lyrics.index_at(42.5)  # the index of the line current 42.5 s in, -1 before the first
                           # (and always for unsynced lyrics)

A line of the answer (FORMAT 2), every field but the times and `text` left out when empty:

    {startMs, endMs,       # when it is sung (0 for unsynced lyrics)
     text,                 # the main vocals ('' for a line of background vocals only)
     stanza,               # true on the first line of a verse or a chorus
     words,                # the main vocals' timed pieces, [{startMs, endMs, text}] in
                           # order, for word-timed songs: each piece's text has the space
                           # that follows it, so the pieces joined are `text` (a piece with
                           # no trailing space is a syllable, joined to the next)
     background, backgroundWords,   # the background vocals, as Apple writes them
                           # (parentheses included), and their pieces, the same way
     agent,                # the singer (Apple's "v1", "v2", a group's id…), only in a duet
     pronunciation, pronunciationWords, pronunciationBackground,
     pronunciationBackgroundWords,  # the transliteration, split and timed as the line is
     translation, translationBackground}   # the translation, split the same way

The current line is the last one that has started: Apple's lines have end times too, but the
highlight stays on a line through the gap before the next one, as Apple's own view does.
parse_lines() is the one reading of an answer, and its one validation: the Engine keeps what
it gives (engine.lyrics_answer), so a lyrics file cached before a fix reads as the fix would
have it. GObject and Gio only, no GTK: tests feed it invented answers.
"""

import bisect
import html
from collections import namedtuple

from gi.repository import Gio, GObject

# The answer's shape, kept with it (engine.lyrics_answer): a file kept in an older one lacks
# what parse_lines reads now, and is fetched again. 2: the words, the background vocals and
# the singers.
FORMAT = 2

# One timed piece of a line's vocals: when it is sung (milliseconds) and its text, with the
# space after it.
Word = namedtuple('Word', 'start_ms end_ms text')

# One line as parse_lines() reads it: LyricLine's fields, the words as tuples of Word.
Line = namedtuple('Line', 'start_ms end_ms text stanza pronunciation translation background '
                          'pronunciation_background translation_background agent words '
                          'background_words pronunciation_words pronunciation_background_words')

# Line's texts beyond `text`, and the answer's keys for them.
_TEXTS = (('pronunciation', 'pronunciation'), ('translation', 'translation'),
          ('background', 'background'), ('pronunciation_background', 'pronunciationBackground'),
          ('translation_background', 'translationBackground'))
# Line's words, the answer's keys for them, and the texts they make.
_WORDS = (('words', 'words', 'text'), ('background_words', 'backgroundWords', 'background'),
          ('pronunciation_words', 'pronunciationWords', 'pronunciation'),
          ('pronunciation_background_words', 'pronunciationBackgroundWords',
           'pronunciation_background'))


def is_secondary(agent):
    """Whether a line sung by `agent` is the secondary singer's, by Apple's rule: any singer
    but v1 (another person, a group, everyone). A song is a duet when some line is."""
    return bool(agent) and agent != 'v1'


# The sides of a duet's lines (LyricLine.side): the lead singer's at the start of the view
# (the left, mirrored in a right-to-left language), the second singer's at the end, and the
# lines of a group, everyone or anyone else in the middle. A song that is not a duet has no
# sides: its lines are ''.
START, END, MIDDLE = 'start', 'end', 'middle'


def side(agent, duet):
    """The side of a line sung by `agent` in a song that is (`duet`) or is not a duet: ''
    for every line of a song that is not; in a duet START for v1 (and a line that names no
    singer: not the secondary's, by Apple's rule), END for v2, MIDDLE for the rest (v3, v4,
    v1000…: Apple's ids for a group, everyone, or a third singer)."""
    if not duet:
        return ''
    if not is_secondary(agent):
        return START
    return END if agent == 'v2' else MIDDLE


class LyricLine(GObject.Object):
    """One line of lyrics: its text (the main vocals) and its background vocals, when synced
    when it starts and ends (milliseconds), whether it opens a stanza (a verse, a chorus: the
    synced view leaves a gap before it, as the text does), how it is pronounced and what it
    means, each split the same way ('' when Apple gave none), who sings it (`agent`, ''
    unless the song is a duet) and so the side of the view it goes on (`side`, which its
    Lyrics sets: side()). The timed pieces (`words`, `background_words`,
    `pronunciation_words`, `pronunciation_background_words`) are tuples of Word, empty for
    lyrics timed by the line. See the module for the fields."""

    __gtype_name__ = 'AppleMusicLyricLine'

    start_ms = GObject.Property(type=int, default=0)
    end_ms = GObject.Property(type=int, default=0)
    text = GObject.Property(type=str, default='')
    stanza = GObject.Property(type=bool, default=False)
    pronunciation = GObject.Property(type=str, default='')
    translation = GObject.Property(type=str, default='')
    background = GObject.Property(type=str, default='')
    pronunciation_background = GObject.Property(type=str, default='')
    translation_background = GObject.Property(type=str, default='')
    agent = GObject.Property(type=str, default='')

    def __init__(self, line=None):
        super().__init__()
        self.side = ''
        self.words = self.background_words = ()
        self.pronunciation_words = self.pronunciation_background_words = ()
        if line is not None:
            for name, value in line._asdict().items():
                setattr(self, name, value)


def _ms(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return 0
    return max(0, int(value))


def _text(value):
    return html.unescape(value).strip() if isinstance(value, str) else ''


def _time(value):
    """A piece's time in whole milliseconds, or None when it is not one."""
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or value != value
            or not 0 <= value < 2 ** 31):
        return None
    return int(value)


def _words(value, text, start_ms, end_ms):
    """The pieces of `value` as a tuple of Word, when they are good: each a dict with times
    (its start before its end, the starts in order, all within the line's start_ms and
    end_ms) and a text that is not blank, read as the text is, the pieces joined being
    `text`. Anything else is no words at all (the line is then highlighted whole), never an
    error."""
    if not text or not isinstance(value, list) or not value:
        return ()
    words = []
    last = len(value) - 1
    previous = start_ms
    for index, piece in enumerate(value):
        if not isinstance(piece, dict) or not isinstance(piece.get('text'), str):
            return ()
        start, end = _time(piece.get('startMs')), _time(piece.get('endMs'))
        if start is None or end is None or not previous <= start <= end:
            return ()
        if end_ms and end > end_ms:
            return ()
        piece_text = html.unescape(piece['text'])
        if index == 0:
            piece_text = piece_text.lstrip()
        if index == last:
            piece_text = piece_text.rstrip()
        if not piece_text.strip():
            return ()
        words.append(Word(start, end, piece_text))
        previous = start
    if ''.join(word.text for word in words) != text:
        return ()
    return tuple(words)


def parse_lines(answer):
    """The answer's lines as Line tuples: dicts with a text or a background that is not
    blank, every text's character references decoded ("Rock &amp; Roll" was cached so once)
    and its ends stripped, `stanza` True on the first line of a verse or a chorus, the
    pronunciation and the translation the line's ('' for none, or for one the same as the
    line, text and background alike), `agent` the singer's id, the words as _words() reads
    them (none for unsynced lyrics); in time order when they carry times (a stable sort: two
    lines starting together keep their order)."""
    lines = []
    raw = answer.get('lines') if isinstance(answer, dict) else None
    synced = bool(isinstance(answer, dict) and answer.get('synced'))
    for line in raw if isinstance(raw, list) else []:
        if not isinstance(line, dict):
            continue
        fields = {'text': _text(line.get('text'))}
        fields.update((name, _text(line.get(key))) for name, key in _TEXTS)
        if not (fields['text'] or fields['background']):
            continue
        sung = (fields['text'], fields['background'])
        for part in ('pronunciation', 'translation'):
            if (fields[part], fields[f'{part}_background']) == sung:
                fields[part] = fields[f'{part}_background'] = ''
        start_ms, end_ms = _ms(line.get('startMs')), _ms(line.get('endMs'))
        for name, key, text in _WORDS:
            fields[name] = (_words(line.get(key), fields[text], start_ms, end_ms) if synced
                            else ())
        agent = line.get('agent')
        lines.append(Line(start_ms=start_ms, end_ms=end_ms, stanza=line.get('stanza') is True,
                          agent=agent.strip() if isinstance(agent, str) else '', **fields))
    if synced:
        lines.sort(key=lambda line: line.start_ms)
    return lines


def line_index_at(starts, seconds):
    """The index of the line current `seconds` in, given the lines' start times in
    milliseconds, ascending: the last line that has started, or -1 before the first."""
    if not starts:
        return -1
    ms = int(max(0.0, float(seconds)) * 1000)
    return bisect.bisect_right(starts, ms) - 1


class Lyrics(GObject.Object):
    """A song's lyrics, parsed from the engine's answer. See the module."""

    __gtype_name__ = 'AppleMusicLyrics'

    def __init__(self, answer, catalog_id=''):
        super().__init__()
        self.catalog_id = catalog_id
        parsed = parse_lines(answer)
        self.synced = bool(isinstance(answer, dict) and answer.get('synced')) and bool(parsed)
        self.has_pronunciations = any(line.pronunciation or line.pronunciation_background
                                      for line in parsed)
        self.has_translations = any(line.translation or line.translation_background
                                    for line in parsed)
        self.duet = any(is_secondary(line.agent) for line in parsed)
        items = [LyricLine(line) for line in parsed]
        for item in items:
            item.side = side(item.agent, self.duet)
        self.lines = Gio.ListStore(item_type=LyricLine)
        self.lines.splice(0, 0, items)
        self._starts = [line.start_ms for line in parsed] if self.synced else []
        texts = []
        for index, line in enumerate(parsed):
            if line.stanza and index:
                texts.append('')
            texts.extend(text for text in (line.text, line.background) if text)
        self.text = '\n'.join(texts)

    def __len__(self):
        return self.lines.get_n_items()

    def index_at(self, seconds):
        """The index of the line current `seconds` into the song, or -1 (before the first
        line, or unsynced lyrics)."""
        return line_index_at(self._starts, seconds)

    def start_of(self, index):
        """Where the line at `index` starts, in seconds (a click on it seeks there)."""
        line = self.lines.get_item(index) if 0 <= index < len(self) else None
        return line.start_ms / 1000 if line is not None else 0.0
