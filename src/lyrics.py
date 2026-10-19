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
    line.instrumental      # the instrumental break before the line (instrumental_breaks():
                           # a Break of its start_ms and end_ms), or None
    lyrics.moment_at(42.5) # what the synced view shows 42.5 s in, a Moment: the row current
                           # (`index`), whether it is in the break before its line
                           # (`instrumental`), and how far into its steps (`step`: the dots
                           # lit, 1 to DOTS, in a break; on a line the timed pieces begun,
                           # of all its parts, 0 for a line timed as a whole)
    lyrics.next_change(42.5)   # when moment_at() next changes (seconds), or None
    line.timed             # the parts with timed pieces: {field: Timing(words, spans)},
                           # the field the text's ('text', 'background', 'pronunciation',
                           # 'pronunciation_background'), the spans its pieces' bytes in
                           # that text (byte_spans())
    sung(words, 42500, sweep)  # how much of a part is sung 42.5 s in: a Sung

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

The current line (index_at) is the last one that has started: Apple's lines have end times
too, but the highlight stays on a line through the gap before the next one, as Apple's own
view does. moment_at() differs only in an instrumental break: synced lyrics whose first line
starts more than INSTRUMENTAL_GAP_MS (9 s) in have one before it, from 0, and a verse (a
line marked `stanza`) that starts more than that after the end of every line before it has
one from that end, each ending a millisecond before its line, as Apple's lyrics component
has them. A gap within a verse has none. A break belongs to the line after it
(`instrumental`): the view shows its dots in that line's row, so the rows stay one to one
with the lines (and the keyboard's stops with them), and moment_at() makes that row current
through the break, its DOTS dots lit one after another, the first as the break begins, the
next at each further DOTS-th of it. next_change() is the one clock of the view's stepping:
every moment a row begins, a break begins, a dot lights or a timed piece begins. A part
timed by the piece (Apple's word-timed lyrics: words, and syllables of them) is sung piece
by piece: sung() says how many pieces are sung and, while the view sweeps, how far into
the one being sung; byte_spans() places each piece in its text as Pango counts (UTF-8
bytes: the pieces joined are the text, so a piece's bytes follow from the ones before).
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


# Apple's rule: an instrumental break shows only where the music plays on without words for
# longer than this.
INSTRUMENTAL_GAP_MS = 9000
# A break's dots, lit one after another across it.
DOTS = 3

# An instrumental break: when it starts and ends (milliseconds, both within it).
Break = namedtuple('Break', 'start_ms end_ms')

# What the synced view shows at a moment (Lyrics.moment_at): the row current (-1: none),
# whether it is in the break before its line, and the step it is at (the dots lit, or on a
# line the pieces begun).
Moment = namedtuple('Moment', 'index instrumental step')
NO_MOMENT = Moment(-1, False, 0)


# The parts of a line that may be timed by the piece: the LyricLine field of each text and
# that of its words.
TIMED = (('text', 'words'), ('background', 'background_words'),
         ('pronunciation', 'pronunciation_words'),
         ('pronunciation_background', 'pronunciation_background_words'))

# Where a piece is in its text, in UTF-8 bytes (Pango's indices): its first byte, its last
# character's first byte, and the byte after it.
Span = namedtuple('Span', 'first last end')

# A timed part of a line (LyricLine.timed): its pieces (Word) and their spans.
Timing = namedtuple('Timing', 'words spans')

# How much of a timed part is sung (sung()): the pieces sung whole, and how far into the next
# one, from 0 to 1, while it is being sung and the view sweeps (None: no piece in progress,
# or whole pieces only).
Sung = namedtuple('Sung', 'whole fraction')


def byte_spans(words):
    """The Span of each of `words` (Word) in the text they make joined: UTF-8 byte offsets,
    which are what Pango indexes a label's text by (a Japanese character is three bytes,
    an accented letter two)."""
    spans = []
    offset = 0
    for word in words:
        size = len(word.text.encode('utf-8'))
        last = offset + size - len(word.text[-1].encode('utf-8')) if word.text else offset
        spans.append(Span(offset, last, offset + size))
        offset += size
    return tuple(spans)


def sung(words, ms, sweep):
    """How much of a part timed by `words` (Word, in order) is sung `ms` into the song, a
    Sung. In whole pieces (`sweep` False) a piece is sung from its start; sweeping, the
    piece begun last is sung from its start to its end, `fraction` saying how far (a piece
    without length is sung at its start), and the pieces before it are sung whole."""
    begun = bisect.bisect_right(words, ms, key=lambda word: word.start_ms)
    if sweep and begun:
        word = words[begun - 1]
        if ms < word.end_ms:
            return Sung(begun - 1, (ms - word.start_ms) / (word.end_ms - word.start_ms))
    return Sung(begun, None)


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
    lyrics timed by the line, and `timed` holds those that are not, by their text's field,
    each a Timing with the pieces' byte spans; `instrumental` is the Break before the line,
    or None. See the module for the fields."""

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
        self.instrumental = None
        if line is not None:
            for name, value in line._asdict().items():
                setattr(self, name, value)
        self.timed = {field: Timing(getattr(self, words), byte_spans(getattr(self, words)))
                      for field, words in TIMED if getattr(self, words)}


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


def instrumental_breaks(lines):
    """The instrumental breaks of synced lines (Line tuples or LyricLines in time order),
    one for each line, by Apple's rules: a Break or None. The first line has one when it
    starts more than INSTRUMENTAL_GAP_MS in, from 0 to a millisecond before it; a line that
    opens a verse (`stanza`) has one when it starts more than that after the latest end of
    the lines before it, from a millisecond after that end to a millisecond before it. A
    line without an end (no later than its start) leaves no break after it, its length
    unknown; a gap between two lines of one verse has none."""
    breaks = [None] * len(lines)
    if lines and lines[0].start_ms > INSTRUMENTAL_GAP_MS:
        breaks[0] = Break(0, lines[0].start_ms - 1)
    end = None      # the latest end so far, None after a line without one
    for index, line in enumerate(lines):
        if (index and line.stanza and end is not None
                and line.start_ms - end > INSTRUMENTAL_GAP_MS):
            breaks[index] = Break(end + 1, line.start_ms - 1)
        if line.end_ms > line.start_ms:
            end = line.end_ms if end is None else max(end, line.end_ms)
        else:
            end = None
    return breaks


def dots_lit(instrumental, ms):
    """How many of a break's DOTS are lit `ms` into the song (inside the break): the first
    from its start, one more at each further DOTS-th of it."""
    length = instrumental.end_ms - instrumental.start_ms + 1
    return 1 + min(DOTS - 1, max(0, ms - instrumental.start_ms) * DOTS // length)


def dot_times(instrumental):
    """When a break's dots light (milliseconds): its start, then each further DOTS-th."""
    length = instrumental.end_ms - instrumental.start_ms + 1
    return [instrumental.start_ms + -(-step * length // DOTS) for step in range(DOTS)]


def line_index_at(starts, seconds):
    """The index of the line current `seconds` in, given the lines' start times in
    milliseconds, ascending: the last line that has started, or -1 before the first."""
    if not starts:
        return -1
    return bisect.bisect_right(starts, _position_ms(seconds)) - 1


def _position_ms(seconds):
    return int(max(0.0, float(seconds)) * 1000)


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
        self._breaks = instrumental_breaks(parsed) if self.synced else [None] * len(parsed)
        for item, instrumental in zip(items, self._breaks, strict=True):
            item.instrumental = instrumental
        self.lines = Gio.ListStore(item_type=LyricLine)
        self.lines.splice(0, 0, items)
        self._starts = [line.start_ms for line in parsed] if self.synced else []
        # Each line's pieces' starts, of all its timed parts: the steps of a line's moment.
        self._pieces = [sorted(word.start_ms for timing in item.timed.values()
                               for word in timing.words) for item in items]
        changes = set(self._starts)
        for instrumental in self._breaks:
            if instrumental is not None:
                changes.update(dot_times(instrumental))
        for starts in self._pieces:
            changes.update(starts)
        self._changes = sorted(changes)
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

    def moment_at(self, seconds):
        """What the synced view shows `seconds` into the song (a Moment): in a break, the
        row of the line after it, its dots lit so far; else the line current (index_at),
        its step the timed pieces of its parts begun (0 for a line timed as a whole).
        NO_MOMENT before the first line (with no break before it) and always for unsynced
        lyrics."""
        ms = _position_ms(seconds)
        index = bisect.bisect_right(self._starts, ms) - 1
        following = index + 1
        if following < len(self._starts):
            instrumental = self._breaks[following]
            if instrumental is not None and instrumental.start_ms <= ms:
                return Moment(following, True, dots_lit(instrumental, ms))
        if index < 0:
            return NO_MOMENT
        return Moment(index, False, bisect.bisect_right(self._pieces[index], ms))

    def next_change(self, seconds):
        """When moment_at() next changes after `seconds` (seconds: a line's start, a
        break's, a dot lighting, a timed piece's start), or None after the last."""
        index = bisect.bisect_right(self._changes, _position_ms(seconds))
        return self._changes[index] / 1000 if index < len(self._changes) else None

    def start_of(self, index):
        """Where the line at `index` starts, in seconds (a click on it seeks there)."""
        line = self.lines.get_item(index) if 0 <= index < len(self) else None
        return line.start_ms / 1000 if line is not None else 0.0
