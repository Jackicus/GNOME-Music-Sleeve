# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Lyrics as a model: the engine's answer ({synced, lines: [{startMs, endMs, text,
pronunciation?, translation?}]}) as a Lyrics object holding LyricLine GObjects in a
Gio.ListStore, and the lookup of the line current at a playback position, which the Now
Playing sheet highlights.

    lyrics = Lyrics(answer, catalog_id)
    lyrics.synced          # True when the lines carry times (Apple's TTML had begin="…")
    lyrics.lines           # Gio.ListStore of LyricLine (start_ms, end_ms, text, stanza,
                           # pronunciation, translation), in time order
    lyrics.text            # every line on its own line, a blank line before each stanza (a
                           # verse, a chorus: a line the answer marks `stanza`): the unsynced view
    lyrics.has_pronunciations   # some line has a pronunciation (Apple's transliteration:
                                # Japanese written in Latin letters, say)
    lyrics.has_translations     # some line has a translation (into the user's language)
    lyrics.index_at(42.5)  # the index of the line current 42.5 s in, -1 before the first
                           # (and always for unsynced lyrics)

The current line is the last one that has started: Apple's lines have end times too, but the
highlight stays on a line through the gap before the next one, as Apple's own view does.
parse_lines() is the one reading of an answer: the Engine keeps what it gives
(engine.lyrics_answer), so a lyrics file cached before a fix reads as the fix would have it.
GObject and Gio only, no GTK: tests feed it invented answers.
"""

import bisect
import html
from collections import namedtuple

from gi.repository import Gio, GObject


class LyricLine(GObject.Object):
    """One line of lyrics: its text, when synced when it starts and ends (milliseconds),
    whether it opens a stanza (a verse, a chorus: the synced view leaves a gap before it, as
    the text does), how it is pronounced and what it means ('' when Apple gave no
    pronunciation, no translation)."""

    __gtype_name__ = 'AppleMusicLyricLine'

    start_ms = GObject.Property(type=int, default=0)
    end_ms = GObject.Property(type=int, default=0)
    text = GObject.Property(type=str, default='')
    stanza = GObject.Property(type=bool, default=False)
    pronunciation = GObject.Property(type=str, default='')
    translation = GObject.Property(type=str, default='')


# One line as parse_lines() reads it.
Line = namedtuple('Line', 'start_ms end_ms text stanza pronunciation translation')


def _ms(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return 0
    return max(0, int(value))


def _text(value):
    return html.unescape(value).strip() if isinstance(value, str) else ''


def parse_lines(answer):
    """The answer's lines as Line tuples (start_ms, end_ms, text, stanza, pronunciation,
    translation): dicts with a text that is not blank, its character references decoded
    ("Rock &amp; Roll" was cached so once) and its ends stripped, `stanza` True on the first
    line of a verse or a chorus, `pronunciation` and `translation` the line's, read as the
    text is ('' for none, or one the same as the text); in time order when they carry times
    (a stable sort: two lines starting together keep their order)."""
    lines = []
    raw = answer.get('lines') if isinstance(answer, dict) else None
    for line in raw if isinstance(raw, list) else []:
        if not isinstance(line, dict):
            continue
        text = _text(line.get('text'))
        if not text:
            continue
        pronunciation, translation = (_text(line.get(key))
                                      for key in ('pronunciation', 'translation'))
        lines.append(Line(_ms(line.get('startMs')), _ms(line.get('endMs')), text,
                          line.get('stanza') is True,
                          '' if pronunciation == text else pronunciation,
                          '' if translation == text else translation))
    if isinstance(answer, dict) and answer.get('synced'):
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
        self.lines = Gio.ListStore(item_type=LyricLine)
        self.lines.splice(0, 0, [LyricLine(**line._asdict()) for line in parsed])
        self._starts = [line.start_ms for line in parsed] if self.synced else []
        self.has_pronunciations = any(line.pronunciation for line in parsed)
        self.has_translations = any(line.translation for line in parsed)
        texts = []
        for index, line in enumerate(parsed):
            if line.stanza and index:
                texts.append('')
            texts.append(line.text)
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
