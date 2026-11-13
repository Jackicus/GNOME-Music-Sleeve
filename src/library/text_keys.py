# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Keys made from text: folded for matching as people type, collated for sorting as the
locale and Apple Music's sidebar do."""

import locale
import unicodedata


def fold(text):
    """text for matching as people type: case and accents ignored ("Beyoncé" is "beyonce")."""
    if not text.isascii():
        text = ''.join(char for char in unicodedata.normalize('NFKD', text)
                       if not unicodedata.combining(char))
    return text.casefold()


def search_key(*texts):
    """texts folded (fold()) on lines of their own: what a filter looks for a folded search
    in (Track.search_key, Item.search_key). A search cannot hold a line break, so no match
    spans two of them."""
    return fold('\n'.join(texts))


def filter_matches(search, key):
    """Whether an object whose search_key is `key` is shown for the filter's text `search`,
    folded (fold()): the whole of it anywhere in one of the key's texts, as the Songs filter,
    the grids', the Artists list's and a playlist's match (pages' Gtk.StringFilter over the
    key does the same in C); everything for no text."""
    return search in key


def collation_key(text):
    """A key that sorts text as the locale collates it, ignoring case, as a Gtk.StringSorter
    does. The app's locale is set by GTK; without it (tests) this is code point order."""
    try:
        return locale.strxfrm(text.casefold())
    except ValueError:  # an embedded NUL
        return text.casefold()


# ASCII punctuation and symbols in the order Unicode's default collation (CLDR's root, which a
# browser's localeCompare follows) gives them, all before the digits. glibc's collation ignores
# them at first, which would list "1.1 Lively 2" before "1. Lively"; Apple Music does not.
_SYMBOL_ORDER = {char: rank for rank, char in enumerate('_-,;:!?.\'"()[]{}@*/\\&#%`^+<=>|~$')}
_char_keys = {}  # a character (casefolded, unaccented) -> its part of title_key's first key


def _char_key(char):
    """A character's weight in title_key(): (class, rank within it)."""
    key = _char_keys.get(char)
    if key is None:
        if char.isspace():
            key = (0, '')
        elif char.isdecimal():
            key = (2, str(int(char)))
        elif char.isalpha():
            key = (3, collation_key(char))  # the locale's order of letters
        else:
            key = (1, chr(0x100 + _SYMBOL_ORDER.get(char, len(_SYMBOL_ORDER) + ord(char))))
        _char_keys[char] = key
    return key


def title_key(text):
    """A key that sorts titles as Apple Music's web player sorts its playlists (lower-cased,
    then compared by localeCompare), character by character: white space first, then
    punctuation and symbols, digits, letters in the locale's order; accents only part ties
    (case none). A digit is a character, not part of a number: "10" sorts before "2", as
    there."""
    folded = (text or '').casefold()
    bare = folded
    if not bare.isascii():
        bare = ''.join(char for char in unicodedata.normalize('NFD', bare)
                       if not unicodedata.combining(char))
    return [_char_keys.get(char) or _char_key(char) for char in bare], folded
