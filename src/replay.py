# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the Replay page's year menu (pages/replay.py) offers, and the page's title. No GTK
here.

    choices(years, latest)               # [Choice(id, title)]: the years, newest first
    position(found, year)                # where `year` is among them
    page_title(year)                     # 'Replay 2026', or 'Replay' without a year

Engine.replay answers {year, years, shelves}: the latest year's Replay, `years` every year
Apple lists one of; Engine.replay(year=…) a past year's. The id '' (LATEST) is the latest
year's: the summary the page opens on, asked without a year, so it is the one kept answer
whichever year it is of.
"""

from collections import namedtuple
from gettext import gettext as _

from .backend.api import is_replay_year

# The id of the latest year: the summary asked without a year.
LATEST = ''

Choice = namedtuple('Choice', ('id', 'title'))


def choices(years, latest=''):
    """The menu's entries, newest first, each year once: the years Apple lists (`years`)
    and `latest`, the year the latest summary is of, whose entry is LATEST's (choosing it
    asks for the latest summary again). Without `latest` (Apple's latest summary named no
    year, or none came yet) a Latest entry leads the years Apple lists. What is not a year
    (api.is_replay_year) is left out."""
    latest = str(latest or '')
    found = {str(year) for year in years or [] if is_replay_year(str(year))}
    if is_replay_year(latest):
        found.add(latest)
        head = []
    else:
        latest = ''
        # Translators: the Replay page's year menu, while Apple names no year for the latest
        # Replay: the latest one, whichever year it is of.
        head = [Choice(LATEST, _('Latest'))]
    return head + [Choice(LATEST if year == latest else year, year)
                   for year in sorted(found, reverse=True)]


def position(found, year):
    """Where `year` (an id: LATEST or a year) is among the Choices `found` (0 when it is not
    there)."""
    for index, choice in enumerate(found):
        if choice.id == year:
            return index
    return 0


def page_title(year):
    """The Replay page's title: of `year` when the answer names one."""
    year = str(year or '')
    if is_replay_year(year):
        # Translators: the Replay page's title: the account's year in music, of that year.
        return _('Replay {year}').format(year=year)
    # Translators: the Replay page's title while it names no year.
    return _('Replay')
