# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicSearchAllPage: a search shelf's See All, the whole of its kind as Apple pages it.

The Search page gives each of a search's shelves of one kind (its Songs, Albums, Radio
Shows…) a `make_page` (see_all_page()), which window.open_shelf() calls for See All: the page
starts from the hits the shelf holds and a search_pager.SearchPager fetches Apple's next pages
as the list (widgets/search_list.py) is scrolled, from where the shelf's answer said the next
one starts, down to the end. Leaving the page (popped or covered) stops a page on its way; it
is asked for again when the list shows once more. What is opened from it goes to Recently
Searched, as from the Search page.
"""

from gettext import gettext as _

from gi.repository import Adw, Gtk

from ..search_pager import SearchPager
from ..widgets.search_list import SearchList  # noqa: F401  $AppleMusicSearchList
from ..widgets.util import connect_weak
from . import app


def see_all_page(term, shelf):
    """The See All page of `shelf`, a ShelfModel of a search for `term` whose key is a kind
    (api.SEARCH_KIND_TYPES) and whose `next` says where Apple's next page starts."""
    application = app()
    pager = SearchPager(term, shelf.key, list(shelf.items), getattr(shelf, 'next', None),
                        search=application.engine.search, spawn=application.spawn)
    return SearchAllPage(pager, shelf.title)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/search_all.ui')
class SearchAllPage(Adw.NavigationPage):
    """A pager's hits under `title` (see the module)."""

    __gtype_name__ = 'AppleMusicSearchAllPage'

    window_title = Gtk.Template.Child()
    results_list = Gtk.Template.Child()

    def __init__(self, pager, title):
        super().__init__(title=title)
        self.pager = pager
        self.window_title.set_title(title)
        # Translators: the subtitle of a search's See All page: what was searched for.
        self.window_title.set_subtitle(_('“{term}”').format(term=pager.term))
        self.results_list.set_pager(pager)
        connect_weak(self.results_list, 'item-activated', self._on_item_activated)

    def do_hidden(self):
        # Left (popped or covered), not just unmapped (a push maps, unmaps and maps a page
        # again): the page on its way stops, asked for again when the list shows.
        self.pager.cancel()

    def _on_item_activated(self, _list, item):
        self.get_root().open_item(item)
        recent = getattr(app(), 'recent_searches', None)
        if recent is not None:
            recent.add(item)
