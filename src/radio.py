# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the Radio page (pages/radio.py) shows beside Apple's shelves as they come: the
programme each live station has on air, and the library's own stations as Recently Played.
No GTK here.

Engine.radio's answer gives a live station its programmes (`events`, [{title, start, end}],
UTC stamps: normalize.radio_shelves); the answer is kept, so which is on air is worked out as
the page is shown (show_on_air(), at each arrange()), and the Item's subtitle follows it.
"""

from datetime import UTC, datetime
from gettext import gettext as _

from .backend.normalize import STAMP_FORMAT

# The key of the Recently Played shelf: none of Apple's (theirs are `radio-<element id>`).
RECENT_KEY = 'recently-played-stations'


class RecentlyPlayed:
    """The Recently Played shelf: the library's own stations (library.radio, the store itself,
    so a sync's changes reach its tiles), as a Shelf binds a ShelfModel (`key`, `title`,
    `items`). Hashable by identity, as ShelfColumn keys its shelves."""

    def __init__(self, items):
        self.key = RECENT_KEY
        self.title = _('Recently Played')
        self.items = items


def arrange(shelves, recent, now=None):
    """The Radio page's shelves: Apple's (ShelfModels, the live stations first), each live
    station subtitled with its programme on air at `now` (show_on_air()), and `recent` (a
    RecentlyPlayed) after the first of them, or alone; left out while it is empty."""
    show_on_air(shelves, now)
    if not recent.items.get_n_items():
        return list(shelves)
    return [*shelves[:1], recent, *shelves[1:]]


def on_air(events, now=None):
    """The programme on air at `now` (by default the present) among a station's `events`
    ([{title, start, end}]), or None."""
    if not isinstance(events, list):
        return None
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime(STAMP_FORMAT)
    return next((event for event in events if isinstance(event, dict)
                 and str(event.get('start') or '~') <= stamp < str(event.get('end') or '')),
                None)


def show_on_air(shelves, now=None):
    """Subtitle each station of the shelves that has programmes with the one on air at `now`,
    or, between them, with its own subtitle (kept in its raw dict as `stationSubtitle` the
    first time): the tiles showing it follow the Item's notify::subtitle."""
    for shelf in shelves:
        for item in shelf.items:
            raw = item.raw if isinstance(item.raw, dict) else {}
            events = raw.get('events')
            if not events:
                continue
            own = raw.setdefault('stationSubtitle', item.subtitle or '')
            current = on_air(events, now)
            subtitle = str(current.get('title') or own) if current else own
            if item.subtitle != subtitle:
                item.subtitle = subtitle
