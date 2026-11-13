#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Pseudo-translations of the app's strings, to see what a translation would break.

    scripts/pseudo_locale.py [--localedir build/locale]

Makes the template (meson's music-sleeve-pot target, in build/, which check.sh configures)
and two catalogues from it, compiled into LOCALEDIR/<lang>/LC_MESSAGES/music-sleeve.mo:

- en_XA, accented and lengthened: every letter accented ("Ŝéàŕçĥ"), each string about 40 %
  longer and in brackets ("⟦Ŝéàŕçĥ ~~⟧"), so text that is not translated stands out as plain
  English and text that is clipped loses a bracket;
- ar_XB, right to left: each run of words wrapped in a right-to-left override, after a
  right-to-left mark, so it reads mirrored and lays out as a right-to-left language's would.

Placeholders ({count}), date formats (%-d %B), mnemonics (_Play), markup and entities are
kept as they are. The .po files are build products, written beside the .mo files, never
committed. Run the demo with one through the harness, which reads MUSIC_SLEEVE_LOCALEDIR:

    MUSIC_SLEEVE_LOCALEDIR=build/locale LANGUAGE=en_XA scripts/headless.sh \\
        scripts/screenshot.py build/pseudo.png --demo --page albums
    MUSIC_SLEEVE_LOCALEDIR=build/locale LANGUAGE=ar_XB scripts/headless.sh \\
        scripts/screenshot.py build/rtl.png --demo --page albums --rtl

(--rtl mirrors the window: GTK takes its direction from its own catalogue, which ar_XB lacks.)
The session's locale must not be C or POSIX, or C's gettext (the Blueprint strings) ignores
LANGUAGE.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOMAIN = 'music-sleeve'
POT = os.path.join(ROOT, 'po', DOMAIN + '.pot')

ACCENTS = str.maketrans(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'àƀçđéƒĝĥîĵķļɱñöþǫŕšţûṽŵẋýžÀƁÇĐÉƑĜĤÎĴĶĻṀÑÖÞǪŔŠŢÛṼŴẊÝŽ')
# What a translation keeps as it is: placeholders, strftime directives, markup, entities,
# and a mnemonic's underscore (its letter is accented like the rest).
KEPT = re.compile(r'\{[^{}]*\}|%-?[A-Za-z%]|<[^<>]*>|&[#\w]+;|_')
RLM, RLO, PDF = '\u200f', '\u202e', '\u202c'
LANGUAGES = ('en_XA', 'ar_XB')
SKIPPED = {'translator-credits'}  # a list of names, not words


def pieces(text):
    """`text` as (kept, piece) pairs: kept pieces are left alone, the others are words."""
    place = 0
    for match in KEPT.finditer(text):
        if match.start() > place:
            yield False, text[place:match.start()]
        yield True, match.group()
        place = match.end()
    if place < len(text):
        yield False, text[place:]


def has_words(text):
    return any(not kept and any(ch.isalpha() for ch in piece) for kept, piece in pieces(text))


def accented(text):
    """en_XA's version of `text`: accented, about 40 % longer, in brackets; text without
    words (a separator, a date format) as it is."""
    if not has_words(text):
        return text
    body = ''.join(piece if kept else piece.translate(ACCENTS) for kept, piece in pieces(text))
    padding = max(0, round(len(text) * 0.4) - 2)
    return '⟦' + body + (' ' + '~' * padding if padding else '') + '⟧'


def mirrored(text):
    """ar_XB's version of `text`: each run of words in a right-to-left override, after a
    right-to-left mark; text without words as it is."""
    if not has_words(text):
        return text
    return RLM + ''.join(piece if kept or not piece.strip() else RLO + piece + PDF
                         for kept, piece in pieces(text))


TRANSFORMS = {'en_XA': accented, 'ar_XB': mirrored}


# -- the template ------------------------------------------------------------------------------

def unquote(line):
    """A PO string line's text ('"…"', C escapes) as it is meant."""
    body = line.strip()[1:-1]
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m[1], m[1]), body)


def quote(text):
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    escaped = escaped.replace('\t', '\\t')
    return '"' + escaped + '"'


def entries(pot_text):
    """The template's messages, each a dict of msgctxt, msgid and msgid_plural (the header,
    msgid "", left out)."""
    found = []
    current, key = {}, None
    for line in pot_text.splitlines() + ['']:
        line = line.strip()
        if not line:
            if current.get('msgid'):
                found.append(current)
            current, key = {}, None
            continue
        if line.startswith('#'):
            continue
        keyword, _space, rest = line.partition(' ')
        if keyword in ('msgctxt', 'msgid', 'msgid_plural'):
            key = keyword
            current[key] = unquote(rest)
        elif keyword.startswith('msgstr'):
            key = None
        elif line.startswith('"') and key is not None:
            current[key] += unquote(line)
    return found


def catalogue(messages, transform, language):
    """A .po file's text: every message translated by `transform`."""
    lines = ['msgid ""', 'msgstr ""',
             quote(f'Project-Id-Version: {DOMAIN}\n'),
             quote('PO-Revision-Date: 2026-01-01 00:00+0000\n'),
             quote('Last-Translator: scripts/pseudo_locale.py\n'),
             quote(f'Language-Team: {language} (pseudo)\n'),
             quote(f'Language: {language}\n'),
             quote('MIME-Version: 1.0\n'),
             quote('Content-Type: text/plain; charset=UTF-8\n'),
             quote('Content-Transfer-Encoding: 8bit\n'),
             quote('Plural-Forms: nplurals=2; plural=(n != 1);\n'), '']
    for message in messages:
        msgid = message['msgid']
        if msgid in SKIPPED:
            continue
        if 'msgctxt' in message:
            lines.append('msgctxt ' + quote(message['msgctxt']))
        lines.append('msgid ' + quote(msgid))
        if 'msgid_plural' in message:
            lines.append('msgid_plural ' + quote(message['msgid_plural']))
            lines.append('msgstr[0] ' + quote(transform(msgid)))
            lines.append('msgstr[1] ' + quote(transform(message['msgid_plural'])))
        else:
            lines.append('msgstr ' + quote(transform(msgid)))
        lines.append('')
    return '\n'.join(lines)


def make_template(localedir):
    """The template, made by meson's target and copied into `localedir`; po/'s copy is
    removed again unless it was there before."""
    existed = os.path.exists(POT)
    done = subprocess.run(['meson', 'compile', '-C', os.path.join(ROOT, 'build'),
                           DOMAIN + '-pot'], capture_output=True, text=True)
    if done.returncode:  # xgettext's warnings (it reads the .blp files as C) only on failure
        sys.exit(done.stdout + done.stderr)
    target = os.path.join(localedir, DOMAIN + '.pot')
    shutil.copyfile(POT, target)
    if not existed:
        os.remove(POT)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--localedir', default=os.path.join(ROOT, 'build', 'locale'))
    args = parser.parse_args(argv)
    os.makedirs(args.localedir, exist_ok=True)
    pot = make_template(args.localedir)
    with open(pot, encoding='utf-8') as file:
        messages = entries(file.read())
    for language in LANGUAGES:
        po = os.path.join(args.localedir, language + '.po')
        with open(po, 'w', encoding='utf-8') as file:
            file.write(catalogue(messages, TRANSFORMS[language], language))
        mo_dir = os.path.join(args.localedir, language, 'LC_MESSAGES')
        os.makedirs(mo_dir, exist_ok=True)
        subprocess.run(['msgfmt', '--check', '-o', os.path.join(mo_dir, DOMAIN + '.mo'), po],
                       check=True)
        print(f'{language}: {len(messages)} messages, {mo_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
