# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Radio destination: Apple Music's own Radio page (engine.radio(): the live stations with
what is on air, then the shows, episodes and genre stations in Apple's order) as shelves, the
live stations as large cards, and the stations the user played recently (the library's own,
library.radio) as one shelf after them, Recently Played.

A ShelvesPage (pages/shelves.py) with an `arrange` of its own (src/radio.py): the page
arranges its shelves again as it is shown (a live station's subtitle is the programme on air
then) and when the library changes (Recently Played comes and goes with the stations). While
Apple cannot be asked and nothing is kept, Recently Played shows alone, as the large cards,
when there are stations; else the page's status. An answer is asked for again once its
programmes run out (`expires`). A show's tile opens its page (a category's,
window.open_item), as on music.apple.com.
"""

from gettext import gettext as _

from .. import radio
from . import app
from .shelves import ShelvesPage


def create(destination, library):
    recent = radio.RecentlyPlayed(library.radio)
    # Neither closure holds the page: it holds them.
    page = ShelvesPage(destination.title, lambda refresh: app().engine.radio(refresh=refresh),
                       icon_name=destination.icon_name, hero=True,
                       empty_title=_('No Stations'),
                       empty_description=_('Apple Music has no radio to show right now'),
                       arrange=lambda shelves: radio.arrange(shelves, recent))
    page.follow(library, 'changed')
    return page
