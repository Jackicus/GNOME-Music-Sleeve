# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the Charts page's genre menu (pages/charts.py) offers, and which genre a link to
the charts opens. No GTK here.

    link_genre(item)                     # the genre a charts Item names ('' for every genre)
    choices(genres, genre, label)        # [Choice(id, title)]: All Genres, then Apple's
    position(found, genre)               # where `genre` is among them

Engine.genres answers the catalog's genres ({genres: [{id, title}]}); Engine.charts(genre=…)
a genre's charts. The id '' (ALL) is every genre's, the charts the page opens on.
"""

from collections import namedtuple
from gettext import gettext as _

from .backend.api import is_genre_id

# The id of All Genres: the charts of every genre.
ALL = ''

Choice = namedtuple('Choice', ('id', 'title'))


def link_genre(item):
    """The genre a charts Item opens on: the id a `viewTop?genreId=` link named
    (explore.link_item keeps it as the Item's `genre`), else ALL (the Top Charts tile)."""
    genre = str(getattr(item, 'genre', None) or '')
    return genre if is_genre_id(genre) else ALL


def choices(genres, genre=ALL, label=''):
    """The menu's entries: All Genres first, then the engine's genres ({id, title}) each
    once, in its order. A `genre` they lack (a link's, while the genres are not read or
    Apple's list leaves it out) follows All Genres under `label`, the link's own words, so
    the menu says what the page shows."""
    # Translators: the Charts page's genre menu, the first entry: the charts of every genre.
    found = [Choice(ALL, _('All Genres'))]
    seen = {ALL}
    for entry in genres or []:
        if not isinstance(entry, dict):
            continue
        genre_id = str(entry.get('id') or '')
        title = ' '.join(str(entry.get('title') or '').split())
        if not is_genre_id(genre_id) or not title or genre_id in seen:
            continue
        seen.add(genre_id)
        found.append(Choice(genre_id, title))
    if genre and genre not in seen:
        title = ' '.join(str(label or '').split()) or genre
        found.insert(1, Choice(genre, title))
    return found


def position(found, genre):
    """Where `genre` is among the Choices `found` (0, All Genres, when it is not there)."""
    for index, choice in enumerate(found):
        if choice.id == genre:
            return index
    return 0
