# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""window.py's sign-out seam, Window.forget_account_pages(), over stand-ins for the window's
parts: the pages of the account's answers dropped, and what the pages kept and the item
actions know of the account forgotten. And the narrow layout's sidebar, over a real
Adw.OverlaySplitView: what covers the page, what closes it, where Back goes, and a root
page's Show Sidebar button."""

import types
import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.gtk import requires_gtk


class FakeStack:
    def __init__(self, pages):
        self.pages = pages

    def get_n_items(self):
        return len(self.pages)

    def __len__(self):
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


def bound(namespace, *names):
    """`namespace` with Window's methods `names` bound to it, as the window's own call them."""
    from applemusic.window import Window

    for name in names:
        setattr(namespace, name, types.MethodType(getattr(Window, name), namespace))
    return namespace


@requires_gtk
class SidebarOverlayTest(unittest.TestCase):
    """The split view is an Adw.OverlaySplitView (issue 593): collapsed, the sidebar slides
    over the page, which is never moved. sidebar_open() is the narrow layout's alone,
    hide_sidebar() never hides the sidebar shown beside the page, and Back closes the
    sidebar before it pops anything."""

    def setUp(self):
        from gi.repository import Adw, Gtk

        self.split_view = Adw.OverlaySplitView(sidebar=Gtk.Box(), content=Gtk.Box())
        self.window = bound(types.SimpleNamespace(split_view=self.split_view),
                            'sidebar_open', 'hide_sidebar')

    def test_beside_the_page_the_sidebar_is_not_open_and_never_hidden(self):
        self.assertFalse(self.window.sidebar_open())
        self.window.hide_sidebar()
        self.assertTrue(self.split_view.get_show_sidebar())

    def test_the_collapse_closes_it_and_widening_shows_it_again(self):
        self.split_view.set_collapsed(True)
        self.assertFalse(self.split_view.get_show_sidebar())
        self.assertFalse(self.window.sidebar_open())
        self.split_view.set_collapsed(False)
        self.assertTrue(self.split_view.get_show_sidebar())
        self.assertFalse(self.window.sidebar_open())

    def test_collapsed_it_opens_over_the_page_and_hide_sidebar_closes_it(self):
        from applemusic.window import Window

        self.split_view.set_collapsed(True)
        Window._on_toggle_sidebar(self.window)
        self.assertTrue(self.window.sidebar_open())
        self.window.hide_sidebar()
        self.assertFalse(self.window.sidebar_open())
        Window._on_toggle_sidebar(self.window)
        Window._on_toggle_sidebar(self.window)  # F9 again closes it
        self.assertFalse(self.window.sidebar_open())

    def test_back_closes_the_open_sidebar_before_it_pops(self):
        from applemusic.window import Window

        root, pushed = object(), object()
        view = FakeNavigationView([root, pushed])
        view.pop = lambda: view.pages.pop()
        view.get_visible_page = lambda: view.pages[-1]
        window = bound(self.window, '_can_go_back', '_page_can_go_back')
        window.navigation_view = view
        self.split_view.set_collapsed(True)
        self.split_view.set_show_sidebar(True)
        Window._on_back(window)
        self.assertFalse(window.sidebar_open())
        self.assertEqual(view.pages, [root, pushed])
        Window._on_back(window)
        self.assertEqual(view.pages, [root])
        # A destination's root has nowhere to go back to: not to the sidebar, as the
        # navigation split view's narrow layout had it.
        self.assertFalse(window._can_go_back())
        Window._on_back(window)
        self.assertEqual(view.pages, [root])
        self.assertFalse(window.sidebar_open())
        self.split_view.set_show_sidebar(True)
        self.assertTrue(window._can_go_back())

    def test_the_item_shown_is_none_while_the_sidebar_covers_the_page(self):
        from applemusic.library import Item
        from applemusic.window import Window

        item = Item({'id': 'a.invented', 'kind': 'album', 'title': 'Invented'})
        window = self.window
        window.bottom_sheet = types.SimpleNamespace(get_open=lambda: False)
        window.fullscreen_host = types.SimpleNamespace(shown=False)
        window.navigation_view = types.SimpleNamespace(
            get_visible_page=lambda: types.SimpleNamespace(item=item))
        self.assertIs(Window.shown_item(window), item)
        self.split_view.set_collapsed(True)
        self.assertIs(Window.shown_item(window), item)
        self.split_view.set_show_sidebar(True)
        self.assertIsNone(Window.shown_item(window))


@requires_gtk
class SidebarButtonTest(unittest.TestCase):
    """A root page's Show Sidebar button (Window._add_sidebar_button): in its header bar,
    named, shown only while the split view is collapsed, and holding the page to nothing."""

    def page(self):
        from gi.repository import Adw, Gtk

        toolbar = Adw.ToolbarView(content=Gtk.Box())
        toolbar.add_top_bar(Adw.HeaderBar())
        return Adw.NavigationPage(title='Invented', child=toolbar)

    def button(self, page):
        from gi.repository import Adw, Gtk

        from applemusic.widgets.util import descendants, first_descendant

        header = first_descendant(page, Adw.HeaderBar)
        return next(button for button in descendants(header, Gtk.Button)
                    if button.get_action_name() == 'win.toggle-sidebar')

    def test_shown_only_while_collapsed(self):
        from gi.repository import Adw, Gtk

        from applemusic.window import Window

        split_view = Adw.OverlaySplitView(sidebar=Gtk.Box(), content=Gtk.Box())
        window = types.SimpleNamespace(split_view=split_view)
        page = self.page()
        Window._add_sidebar_button(window, page)
        button = self.button(page)
        self.assertEqual(button.get_icon_name(), 'sidebar-show-symbolic')
        self.assertTrue(button.get_tooltip_text())  # its accessible name
        self.assertFalse(button.get_visible())
        split_view.set_collapsed(True)
        self.assertTrue(button.get_visible())
        split_view.set_collapsed(False)
        self.assertFalse(button.get_visible())

    def test_first_before_the_buttons_the_page_packed_at_the_start(self):
        # All Playlists and a folder's page pack New Playlist and New Folder at the start
        # (pages.add_folder_buttons): Show Sidebar still comes first.
        from gi.repository import Adw, Gtk

        from applemusic.widgets.util import first_descendant
        from applemusic.window import Window

        split_view = Adw.OverlaySplitView(sidebar=Gtk.Box(), content=Gtk.Box())
        window = types.SimpleNamespace(split_view=split_view)
        page = self.page()
        header = first_descendant(page, Adw.HeaderBar)
        new = Gtk.Button(icon_name='list-add-symbolic')
        header.pack_start(new)
        header.pack_start(Gtk.Button(icon_name='folder-new-symbolic'))
        Window._add_sidebar_button(window, page)
        button = self.button(page)
        self.assertIs(button.get_parent(), new.get_parent())
        self.assertIs(button.get_parent().get_first_child(), button)

    def test_the_page_is_freed_once_dropped(self):
        import gc

        from gi.repository import Adw, Gtk

        from applemusic.window import Window

        split_view = Adw.OverlaySplitView(sidebar=Gtk.Box(), content=Gtk.Box())
        window = types.SimpleNamespace(split_view=split_view)
        page = self.page()
        Window._add_sidebar_button(window, page)
        freed = []
        page.weak_ref(lambda: freed.append(True))
        del page
        gc.collect()
        self.assertEqual(freed, [True])
        split_view.set_collapsed(True)  # the binding went with the button


if __name__ == '__main__':
    unittest.main()
