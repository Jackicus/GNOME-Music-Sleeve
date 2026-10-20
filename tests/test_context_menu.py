# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The item menus as a Gtk.PopoverMenu shows them (applemusic.widgets.context_menu.popup over
actions.build_menu): every submenu a page of its own, which its item opens. A PopoverMenu
names each submenu's page by its label, so two submenus of one label share a page (issue
423): the menus have none but Add to Playlist and Move to Folder."""

import re
import unittest

import gi

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import requires_gtk

gi.require_version('Gtk', '4.0')

from gi.repository import Gio, GObject  # noqa: E402

from applemusic.actions import build_menu  # noqa: E402
from applemusic.library import Item  # noqa: E402

# Invented: a playlist at the top level, and folders that hold playlists and a folder, which
# both Add to Playlist and Move to Folder list.
PLAYLIST = Item({'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip',
                 'play': {'kind': 'playlist', 'id': 'p.pl1'}})
PLAYLISTS = [('p.fd1', 'Evenings', [('p.pl2', 'Dusk', None),
                                    ('p.fd2', 'Late', [('p.pl3', 'Owl', None)])]),
             ('p.fd3', 'Untitled', [('p.pl4', 'Dawn', None)]),
             ('p.fd4', 'Untitled', [('p.pl5', 'Noon', None)]),
             ('p.pl6', 'Main', None)]
MOVES = (False, [('p.fd1', 'Evenings', True, [('p.fd2', 'Late', True, [])]),
                 ('p.fd3', 'Untitled', True, []), ('p.fd4', 'Untitled', True, [])])
TITLE_ROLE = 3  # GtkButtonRole's TITLE: a submenu's header, which goes back


def submenus(model, path=()):
    """[(path, submenu)] of a menu model, depth first: `path` the shown positions (sections
    flattened) of the items that lead to it."""
    found = []
    for position, (_label, submenu) in enumerate(entries(model)):
        if submenu is not None:
            found.append(((*path, position), submenu))
            found.extend(submenus(submenu, (*path, position)))
    return found


def entries(model):
    """[(label, submenu or None)] of a menu model's items, its sections flattened, as one
    page of a PopoverMenu shows them here: the label as it reads (its mnemonic taken out),
    the items hidden while their action is disabled left out (the test's window has no
    win.* actions)."""
    found = []
    for position in range(model.get_n_items()):
        section = model.get_item_link(position, Gio.MENU_LINK_SECTION)
        if section is not None:
            found.extend(entries(section))
            continue
        if model.get_item_attribute_value(position, 'hidden-when', None) is not None:
            continue
        label = model.get_item_attribute_value(position, 'label', None).unpack()
        found.append((re.sub('_(.)', r'\1', label),
                      model.get_item_link(position, Gio.MENU_LINK_SUBMENU)))
    return found


def descendants(widget):
    """widget and everything under it, depth first."""
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


def buttons(page):
    """The items a page of a PopoverMenu shows, in order (not its header)."""
    return [widget for widget in descendants(page)
            if GObject.type_name(widget) == 'GtkModelButton'
            and widget.get_property('role') != TITLE_ROLE]


@requires_gtk
class PopoverTest(unittest.TestCase):
    def popup(self, menu):
        from gi.repository import Gtk

        from applemusic.widgets import context_menu
        from tests.gtk import wait_for

        class Actions:
            def menu_for(self, obj, **_kwargs):
                return menu

        class Window(Gtk.Window):
            item_actions = Actions()

        anchor = Gtk.Box(width_request=100, height_request=40)
        window = Window(child=anchor)
        self.addCleanup(window.destroy)
        window.present()
        popover = context_menu.popup(anchor, PLAYLIST)
        self.addCleanup(popover.popdown)
        self.assertTrue(wait_for(popover.get_mapped))
        return next(widget for widget in descendants(popover) if isinstance(widget, Gtk.Stack))

    def test_each_submenu_opens_its_own_items(self):
        from tests.gtk import pump

        menu = build_menu(PLAYLIST, playlists=PLAYLISTS, moves=MOVES)
        stack = self.popup(menu)
        found = submenus(menu)
        self.assertTrue(found)
        # A page for the menu and one for each submenu, each named once.
        names = [page.get_name() for page in stack.get_pages()]
        self.assertEqual(len(names), len(found) + 1, names)
        self.assertEqual(len(set(names)), len(names), names)
        for path, submenu in found:
            with self.subTest(path=path):
                stack.set_visible_child_name('main')
                pump()
                for position in path:  # as clicks on the items leading to it open it
                    buttons(stack.get_visible_child())[position].emit('clicked')
                    pump()
                shown = [button.get_property('text')
                         for button in buttons(stack.get_visible_child())]
                self.assertEqual(shown, [label for label, _submenu in entries(submenu)])

    def test_a_widgets_own_section_ends_its_menu(self):
        # The player bar's Mini Player (its `context_extra`), after the item's own menu.
        from gi.repository import Gtk

        from applemusic.widgets import context_menu
        from tests.gtk import wait_for

        menu = build_menu(PLAYLIST)

        class Actions:
            def menu_for(self, obj, **_kwargs):
                return menu

        class Window(Gtk.Window):
            item_actions = Actions()

        extra = Gio.Menu()
        extra.append('_Mini Player', 'app.mini-player')
        anchor = Gtk.Box(width_request=100, height_request=40)
        anchor.context_extra = extra
        window = Window(child=anchor)
        self.addCleanup(window.destroy)
        window.present()
        popover = context_menu.popup(anchor, PLAYLIST)
        self.addCleanup(popover.popdown)
        self.assertTrue(wait_for(popover.get_mapped))
        shown = popover.get_menu_model()
        last = shown.get_item_link(shown.get_n_items() - 1, Gio.MENU_LINK_SECTION)
        self.assertEqual(last.get_item_attribute_value(0, 'action', None).unpack(),
                         'app.mini-player')
        self.assertEqual(entries(shown)[0], ('Play', None))  # the item's own menu first


if __name__ == '__main__':
    unittest.main()
