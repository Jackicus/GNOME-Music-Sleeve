#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Put the development build's suffix after the app's name, in every language, in a desktop
file or a metainfo whose translations are merged already (data/meson.build).

    name-suffix.py INPUT OUTPUT [SUFFIX]

With no suffix (a release build) OUTPUT is a copy of INPUT.

The suffix goes on after the merge, not into the source, so that the name's msgid in the
template is the name itself ("Music Sleeve"), which the merge then finds translated. In a
desktop file it goes after each Name= and Name[lang]= value; in a metainfo after each of the
component's own <name> elements (two spaces in, as the source has them), never the developer's.
"""

import re
import sys

DESKTOP_NAME = re.compile(r'^(Name(?:\[[^\]]+\])?=.*)$', re.MULTILINE)
METAINFO_NAME = re.compile(r'^(  <name(?: xml:lang="[^"]+")?>)([^<]*)(</name>)$', re.MULTILINE)


def add_suffix(text, suffix):
    """`text` (a desktop file's or a metainfo's) with `suffix` after each name of the app."""
    if text.lstrip().startswith('<'):
        return METAINFO_NAME.sub(lambda match: match[1] + match[2] + suffix + match[3], text)
    return DESKTOP_NAME.sub(lambda match: match[1] + suffix, text)


def main(argv):
    source, target = argv[1:3]
    suffix = argv[3] if len(argv) > 3 else ''  # none in a release build
    with open(source, encoding='utf-8') as file:
        text = file.read()
    with open(target, 'w', encoding='utf-8') as file:
        file.write(add_suffix(text, suffix))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
