# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""window.py's sign-out seam, Window.forget_account_pages(), over stand-ins for the window's
parts: the pages of the account's answers dropped, and what the pages kept and the item
actions know of the account forgotten."""

import types
import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.gtk import requires_gtk


class FakeStack:
    def __init__(self, pages):
        self.pages = pages

    def get_n_items(self):
        return len(self.pages)

    def get_item(self, position):
        return self.pages[position]


class FakeNavigationView:
    def __init__(self, pages):
        self.pages = list(pages)

    def get_navigation_stack(self):
        return FakeStack(self.pages)

    def pop_to_page(self, page):
        del self.pages[self.pages.index(page) + 1:]


class FakeSidebar:
    def __init__(self):
        self.selected = []
        self.forgot = 0

    def select(self, key):
        self.selected.append(key)

    def forget_expanded(self):
        self.forgot += 1


class FakeHome:
    def __init__(self):
        self.forgot = 0

    def forget_account(self):
        self.forgot += 1


class FakeItemActions:
    def __init__(self):
        self.forgot = 0

    def forget_account(self):
        self.forgot += 1


@requires_gtk
class ForgetAccountPagesTest(unittest.TestCase):
    def window(self, roots, shown):
        window = types.SimpleNamespace(
            _roots=dict(roots), shown=shown, _sidebar=FakeSidebar(),
            navigation_view=FakeNavigationView([roots[shown], object()]),
            item_actions=FakeItemActions(), dropped=[])

        def drop(key):
            window.dropped.append(key)
            del window._roots[key]

        window._drop_root = drop
        return window

    def test_the_accounts_pages_go_and_the_kept_ones_forget_it(self):
        from applemusic.window import Window

        home = FakeHome()
        albums = object()  # a library page: it follows the library's load
        roots = {'home': home, 'albums': albums, 'new': object(), 'search': object(),
                 'playlist:p.invented': object()}
        window = self.window(roots, 'search')
        Window.forget_account_pages(window)
        self.assertEqual(window.dropped, ['new', 'search', 'playlist:p.invented'])
        self.assertEqual(window._roots, {'home': home, 'albums': albums})
        self.assertEqual(window._sidebar.selected, ['home'])
        self.assertEqual(len(window.navigation_view.pages), 1)  # the pushed page popped
        self.assertEqual(home.forgot, 1)  # Recently Played
        self.assertEqual(window.item_actions.forgot, 1)  # the ratings heard
        self.assertEqual(window._sidebar.forgot, 1)


if __name__ == '__main__':
    unittest.main()
