# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The model's own words, in the app's language: counts, Home's fixed shelf titles and the
names of what has none.

Made and translated here, never taken from the English the backend writes (it writes none).
"""

from gettext import gettext as _
from gettext import ngettext


def N_(text):
    """Mark a string for translation where it is defined; _() translates it where it is used."""
    return text


# Home's shelves of the library's own are titled by key, in the app's language: the sync
# writes no title for them (older versions wrote English ones, which nothing shows now).
FIXED_SHELF_TITLES = {
    # Translators: a shelf on the Home page, as Apple Music names it: the albums,
    # playlists and stations played most lately.
    'heavy-rotation': N_('Heavy Rotation'),
    # Translators: a shelf on the Home page: what was added to the library last.
    'recently-added': N_('Recently Added'),
}

# What an Item of that kind is called when it has no title (unknown_title()).
UNKNOWN_TITLES = {
    # Translators: in place of the name of an album that has none.
    'album': N_('Unknown Album'),
    # Translators: in place of the name of an artist that has none.
    'artist': N_('Unknown Artist'),
}
_unknown_titles = {}  # kind -> its UNKNOWN_TITLES entry translated, looked up once


def unknown_title(kind):
    """What an Item of `kind` is called when it has no title (UNKNOWN_TITLES, translated once
    per process), or '' for a kind without such a name."""
    text = _unknown_titles.get(kind)
    if text is None:
        source = UNKNOWN_TITLES.get(kind)
        if source is None:
            return ''
        text = _unknown_titles[kind] = _(source)
    return text


def songs_text(count, duration_ms=None):
    """An album's or playlist's caption: '12 songs, 43 min', or '12 songs' without a total
    time."""
    # Translators: how many songs an album or a playlist has.
    songs = ngettext('{count} song', '{count} songs', count).format(count=f'{count:n}')
    if duration_ms is None:
        return songs
    # Translators: an album's or a playlist's songs, then their total time: "12 songs, 43 min".
    return _('{songs}, {duration}').format(songs=songs, duration=duration_text(duration_ms))


def duration_text(duration_ms):
    """A total time in hours and minutes, as a caption gives it: '43 min', '1 hr 5 min',
    '2 hr' (at least a minute when there is any time at all)."""
    minutes = max(1, round(duration_ms / 60000)) if duration_ms > 0 else 0
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        # Translators: a total time in hours and minutes, abbreviated: "1 hr 5 min".
        return _('{hours} hr {minutes} min').format(hours=f'{hours:n}', minutes=f'{minutes:n}')
    if hours:
        # Translators: a total time in whole hours, abbreviated: "2 hr".
        return ngettext('{hours} hr', '{hours} hr', hours).format(hours=f'{hours:n}')
    # Translators: a total time in minutes, abbreviated: "43 min".
    return ngettext('{minutes} min', '{minutes} min', minutes).format(minutes=f'{minutes:n}')


def albums_text(count):
    """An artist's caption, or a genre's: '3 albums'."""
    # Translators: how many albums of an artist, or of a genre, the library has.
    return ngettext('{count} album', '{count} albums', count).format(count=f'{count:n}')


def shelf_title(key, title):
    """A library.json shelf's title as Home shows it: the app's own words for its fixed
    shelves (FIXED_SHELF_TITLES), Apple's title for a recommendation, which comes in the
    account's language, and 'For You' for a recommendation without one."""
    if key in FIXED_SHELF_TITLES:
        return _(FIXED_SHELF_TITLES[key])
    # Translators: the title of a shelf of Apple Music's recommendations that has none.
    return title or _('For You')
