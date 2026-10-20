# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The words an album's or playlist's page shows besides its tracks (pages/detail.py), as
Apple Music's clients show them: the hero's curator and caption, and under an album's tracks
the release footer, then the catalog's shelves.

    album_artist(item)            an album's artist: its artistName, else its subtitle
    curator(item, 'Alex')         an album's artist, a playlist's curator (the user's own: theirs)
    hero_caption(item)            'Pop · 2001 · 12 songs, 43 min'; 'Updated 3 March · 22 songs…'
    updated_text('2026-03-03T09:00:00Z')             'Updated 3 March' (or today, yesterday…)
    album_target(item)            (album id, song id) Engine.album_page() is asked by, or None
    footer_lines(item, answer, count, duration_ms)   the footer's lines, in the reader's words
    release_date_text('2026-09-24')                  '24 September 2026'
    length_text(12, 2580000)                         '12 songs, 43 minutes'
    album_shelves(answer, artist_name)               the answer's shelves as ShelfModels

A playlist's hero names its curator (Apple's playlists, a curator's) or, for one of the
user's, the account's name, then says when it was updated (its `modified`, Apple's
lastModifiedDate: today, yesterday, a weekday within the week, else the date) and its songs
and their time; an album's says its genre, year, songs and time.

The footer is the release date in full, the songs and their total time, and the ℗ or © line
(else the label): the catalog album's (Engine.album_page()'s `release`) when the page has
its answer, a library album's included; else the date an Item carries (an artist page's
latest release) and the counts alone. The shelves are Other Versions, Music Videos, More By
<artist>, Featured On and You Might Also Like, in that order (the engine's), titled as Apple
titles them, or here when Apple gives no title (More By always: it is no view of Apple's).

GLib, GObject and Gio only, no GTK: the unit tests run it without a display.
"""

from gettext import gettext as _
from gettext import ngettext
from gettext import pgettext as C_

from gi.repository import GLib

from .backend.api import is_library_id
from .library import Item, ShelfModel
from .related import artist_name
from .remote import remote_item


def album_target(item):
    """What Engine.album_page() is asked for an album Item: (its catalog id, None), or for a
    library album without one (a library album carries none: the sync's), (its own id, the
    catalog id of its first song that has one), through which the engine finds its catalog
    album. None for anything else, a stand-in for loose songs among them (`l.alb_`, no
    catalog album), or an album with no song to find it by."""
    if item is None or item.kind != 'album' or not item.id:
        return None
    for candidate in (item.catalog_id, item.id):
        if candidate and not is_library_id(candidate):
            return str(candidate), None
    if str(item.id).startswith('l.alb_'):
        return None
    for group in item.groups:
        for track in group.entries:
            if track.catalog_id and not is_library_id(track.catalog_id):
                return str(item.id), str(track.catalog_id)
    return None


def album_artist(item):
    """The artist an album is by, wherever its page means them (the line under its title, its
    link, its rows, More By): its `artistName` when it carries one (a shelf's album, an
    artist page's, subtitled with its year), else its subtitle; '' for anything else."""
    if item is None or item.kind != 'album':
        return ''
    return artist_name(item)


def curator(item, account_name=''):
    """The line under a playlist's or album's title: an album's artist (album_artist()), a
    playlist's curator (its subtitle), else for a playlist of the user's (Item.editable, or
    Favourite Songs) `account_name`, the account's (the user's own carry no curator); else
    ''."""
    if item is None:
        return ''
    if item.kind == 'album':
        return album_artist(item)
    if item.subtitle:
        return item.subtitle
    if item.kind == 'playlist' and (item.editable or item.favourites):
        return account_name or ''
    return ''


def _datetime(make):
    """make()'s GLib.DateTime, or None for a date GLib refuses (PyGObject raises TypeError
    for the NULL GLib answers)."""
    try:
        return make()
    except (TypeError, ValueError):
        return None


def _day(date):
    """The local midnight starting the day of a GLib.DateTime."""
    return GLib.DateTime.new_local(date.get_year(), date.get_month(), date.get_day_of_month(),
                                   0, 0, 0)


def updated_text(modified, now=None):
    """When a playlist was last changed (Apple's lastModifiedDate, '2026-03-03T09:00:00Z'), in
    the reader's words and time zone: "Updated today", "Updated yesterday", the weekday within
    the week ("Updated Monday"), the day and month this year ("Updated 3 March"), else with the
    year ("Updated 3 March 2025"). '' for anything that is not such a date. `now` is a
    GLib.DateTime (the local time when None)."""
    if not isinstance(modified, str) or not modified.strip():
        return ''
    text = modified.strip()
    date = _datetime(lambda: GLib.DateTime.new_from_iso8601(text, GLib.TimeZone.new_utc()))
    if date is None and len(text) == 10:  # a day alone ('2026-03-03'): that local day
        parts = text.split('-')
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            year, month, day = (int(part) for part in parts)
            date = _datetime(lambda: GLib.DateTime.new_local(year, month, day, 12, 0, 0))
    if date is None:
        return ''
    date = date.to_local()
    now = (now or GLib.DateTime.new_now_local()).to_local()
    days = round(_day(now).difference(_day(date)) / GLib.TIME_SPAN_DAY)
    if days <= 0:
        # Translators: when a playlist was last changed, under its title.
        return _('Updated today')
    if days == 1:
        # Translators: when a playlist was last changed, under its title.
        return _('Updated yesterday')
    if days < 7:
        # Translators: when a playlist was last changed, under its title, within the past
        # week: {weekday} is the day's name ("Updated Monday").
        return _('Updated {weekday}').format(weekday=date.format('%A') or '')
    if date.get_year() == now.get_year():
        # Translators: a playlist's last change this year, as GLib.DateTime.format() takes
        # it: "%-d %B" is "3 March".
        day = date.format(C_('playlist updated date', '%-d %B')) or ''
    else:
        # Translators: a playlist's last change in another year, as GLib.DateTime.format()
        # takes it: "%-d %B %Y" is "3 March 2025".
        day = date.format(C_('playlist updated date', '%-d %B %Y')) or ''
    # Translators: when a playlist was last changed, under its title: {date} is a date
    # ("Updated 3 March").
    return _('Updated {date}').format(date=day) if day else ''


def hero_caption(item, now=None):
    """The caption under an album's or playlist's title: an album's genre, year, and songs
    and time (its count-label); a playlist's last change (updated_text()) and count-label,
    joined by middle dots. '' when there is none of them."""
    if item is None:
        return ''
    if item.kind == 'playlist':
        modified = item.raw.get('modified') if isinstance(item.raw, dict) else None
        details = [updated_text(modified, now), item.count_label]
    else:
        details = [item.genre, str(item.year) if item.year else None, item.count_label]
    return ' · '.join(detail for detail in details if detail)


def release_date_text(text):
    """Apple's release date ('2026-09-24') in the reader's words, in full ("24 September
    2026"); a year alone as it is; '' for anything else."""
    text = str(text or '').strip()
    if len(text) == 4 and text.isdigit():
        return text
    try:
        year, month, day = (int(part) for part in text.split('-'))
        date = GLib.DateTime.new_local(year, month, day, 0, 0, 0)
    except (TypeError, ValueError):
        return ''
    if date is None:
        return ''
    # Translators: an album's release date under its songs, in full, as
    # GLib.DateTime.format() takes it: "%-d %B %Y" is "24 September 2026".
    return date.format(C_('album release date', '%-d %B %Y')) or ''


def length_text(count, duration_ms=None):
    """An album's songs and their total time in words, as its footer says them: "12 songs,
    43 minutes", "18 songs, 1 hour, 5 minutes", "1 song" without a time."""
    # Translators: how many songs an album or a playlist has.
    songs = ngettext('{count} song', '{count} songs', count).format(count=f'{count:n}')
    if not duration_ms or duration_ms <= 0:
        return songs
    minutes = max(1, round(duration_ms / 60000))
    hours, minutes = divmod(minutes, 60)
    parts = [songs]
    if hours:
        # Translators: part of an album's total time under its songs: "1 hour".
        parts.append(ngettext('{hours} hour', '{hours} hours', hours).format(
            hours=f'{hours:n}'))
    if minutes:
        # Translators: part of an album's total time under its songs: "43 minutes".
        parts.append(ngettext('{minutes} minute', '{minutes} minutes', minutes).format(
            minutes=f'{minutes:n}'))
    # Translators: what joins the parts of an album's length under its songs: "12 songs,
    # 1 hour, 5 minutes".
    return C_('album length', ', ').join(parts)


def footer_lines(item, answer, count, duration_ms):
    """The lines of an album's footer: its release date in full, its `count` songs and their
    `duration_ms`, and its copyright (else its label), each only when known: from the
    answer's `release` (Engine.album_page()), else what the Item carries."""
    release = answer.get('release') if isinstance(answer, dict) else None
    release = release if isinstance(release, dict) else {}
    raw = item.raw if item is not None and isinstance(item.raw, dict) else {}
    date = release_date_text(release.get('releaseDate') or raw.get('releaseDate'))
    lines = [date] if date else []
    if count:
        lines.append(length_text(count, duration_ms))
    rights = release.get('copyright') or release.get('recordLabel')
    if isinstance(rights, str) and rights.strip():
        lines.append(rights.strip())
    return lines


def shelf_title(key, title, artist_name):
    """A shelf's title: Apple's, else the app's for its key ("More By <artist>" always)."""
    if key == 'more-by-artist':
        if not artist_name:
            # Translators: the shelf of an album's artist's other albums, its artist unknown.
            return _('More By the Artist')
        # Translators: the shelf of an album's artist's other albums: "More By Taylor Swift".
        return _('More By {artist}').format(artist=artist_name)
    if title:
        return title
    return {
        # Translators: the shelf of an album's other editions (deluxe, remastered).
        'other-versions': _('Other Versions'),
        # Translators: the shelf of the music videos of an album's songs.
        'related-videos': _('Music Videos'),
        # Translators: the shelf of the playlists an album's songs are on.
        'appears-on': _('Featured On'),
        # Translators: the shelf of albums like the one shown.
        'related-albums': _('You Might Also Like'),
    }.get(key, '')


def album_shelves(answer, artist_name=''):
    """ShelfModels of an Engine.album_page() answer's shelves, in its order, titled
    (shelf_title(): More By names `artist_name`, else the answer's artist), their items with
    their artwork where the app fetches it (remote_item), `more` where Apple has more."""
    answer = answer if isinstance(answer, dict) else {}
    artist_name = artist_name or str(answer.get('artistName') or '')
    shelves = []
    for data in answer.get('shelves') or []:
        if not isinstance(data, dict):
            continue
        items = [Item(remote_item(entry)) for entry in data.get('items') or []
                 if isinstance(entry, dict) and entry.get('id') and entry.get('kind')]
        if not items:
            continue
        key = str(data.get('key') or '')
        title = data.get('title') if isinstance(data.get('title'), str) else ''
        shelf = ShelfModel(key, shelf_title(key, title, artist_name), items)
        shelf.more = bool(data.get('more'))
        shelves.append(shelf)
    return shelves
