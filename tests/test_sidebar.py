# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Playlists section's entries (applemusic.sidebar), from invented playlist trees."""

import unittest

import gi

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import requires_gtk

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from applemusic import sections  # noqa: E402
from applemusic.library import Item, PlaylistTree  # noqa: E402
from applemusic.sections import ALL_PLAYLISTS, HOME, Destination  # noqa: E402
from applemusic.sidebar import (DEPTH_CLASSES, SidebarEntry, SidebarItem,  # noqa: E402
                                depth_class, is_shown, parse_key, plan_update,
                                playlist_entries, restore_target, reveal, stale_roots,
                                tooltip_markup)
from applemusic.widgets.util import descendants  # noqa: E402


def playlist(playlist_id, favourites=False, title=None):
    raw = {'id': playlist_id, 'kind': 'playlist', 'title': title or playlist_id.upper(),
           'groups': []}
    if favourites:
        raw['attributes'] = {'isFavourites': True}
    return Item(raw)


def tree(titles=None, folders=None):
    """root: folder a (folder b (p3), p1), p2, favourites; folder c (empty). `titles` renames
    playlists by id; `folders` replaces the folders' entries."""
    titles = titles or {}
    playlists = [playlist('p1', title=titles.get('p1')), playlist('p2', title=titles.get('p2')),
                 playlist('p3', title=titles.get('p3')), playlist('fav', True)]
    return PlaylistTree(folders or [
        {'id': 'root', 'title': '', 'parent': None, 'children': [
            {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
            {'kind': 'playlist', 'id': 'fav'}, {'kind': 'folder', 'id': 'c'}]},
        {'id': 'a', 'title': 'Folder A', 'parent': 'root', 'children': [
            {'kind': 'folder', 'id': 'b'}, {'kind': 'playlist', 'id': 'p1'}]},
        {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
            {'kind': 'playlist', 'id': 'p3'}]},
        {'id': 'c', 'title': 'Folder C', 'parent': 'root', 'children': []},
    ], playlists)


def by_key(entries):
    return {entry.key: entry for entry in entries}


class PlanUpdateTest(unittest.TestCase):
    """plan_update: the fewest changes that make the section list the new entries."""

    def test_identical_lists_need_nothing(self):
        retitles, splices = plan_update(playlist_entries(tree()), playlist_entries(tree()))
        self.assertEqual((retitles, splices), ([], []))

    def test_a_rename_is_one_retitle_and_no_splice(self):
        old = playlist_entries(tree())
        new = playlist_entries(tree(titles={'p1': 'Long Drive'}))
        retitles, splices = plan_update(old, new)
        self.assertEqual(splices, [])
        self.assertEqual([(index, entry.key, entry.title) for index, entry in retitles],
                         [(3, 'playlist:p1', 'Long Drive')])

    def test_an_insert_is_one_splice(self):
        old = playlist_entries(tree())
        folders = [
            {'id': 'root', 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
                {'kind': 'playlist', 'id': 'p4'}, {'kind': 'folder', 'id': 'c'}]},
            {'id': 'a', 'title': 'Folder A', 'parent': 'root', 'children': [
                {'kind': 'folder', 'id': 'b'}, {'kind': 'playlist', 'id': 'p1'}]},
            {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
                {'kind': 'playlist', 'id': 'p3'}]},
            {'id': 'c', 'title': 'Folder C', 'parent': 'root', 'children': []},
        ]
        new_tree = PlaylistTree(folders, [playlist('p1'), playlist('p2'), playlist('p3'),
                                          playlist('p4')])
        retitles, splices = plan_update(old, playlist_entries(new_tree))
        self.assertEqual(retitles, [])
        self.assertEqual([(index, count, [e.key for e in entries])
                          for index, count, entries in splices],
                         [(6, 0, ['playlist:p4'])])

    def test_a_rename_that_moves_an_entry_is_a_move(self):
        # Folder C renamed "Archive" goes before Folder A (folders sort by title): the
        # entry leaves its place and a new one comes in at the new place, under its new title.
        old = playlist_entries(tree())
        folders = [
            {'id': 'root', 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
                {'kind': 'playlist', 'id': 'fav'}, {'kind': 'folder', 'id': 'c'}]},
            {'id': 'a', 'title': 'Folder A', 'parent': 'root', 'children': [
                {'kind': 'folder', 'id': 'b'}, {'kind': 'playlist', 'id': 'p1'}]},
            {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
                {'kind': 'playlist', 'id': 'p3'}]},
            {'id': 'c', 'title': 'Archive', 'parent': 'root', 'children': []},
        ]
        new = playlist_entries(tree(folders=folders))
        self.assertEqual([e.key for e in new][:2], ['folder:c', 'folder:a'])
        retitles, splices = plan_update(old, new)
        self.assertEqual(retitles, [])
        entries = list(old)
        for index, count, inserted in splices:
            entries[index:index + count] = inserted
        self.assertEqual([e.shape() for e in entries], [e.shape() for e in new])
        self.assertEqual(sum(count for _index, count, _entries in splices), 1)  # only c went

    def test_a_move_between_folders_is_a_splice(self):
        old = playlist_entries(tree())
        folders = [  # p1 moves from folder a to folder c
            {'id': 'root', 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
                {'kind': 'folder', 'id': 'c'}]},
            {'id': 'a', 'title': 'Folder A', 'parent': 'root', 'children': [
                {'kind': 'folder', 'id': 'b'}]},
            {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
                {'kind': 'playlist', 'id': 'p3'}]},
            {'id': 'c', 'title': 'Folder C', 'parent': 'root', 'children': [
                {'kind': 'playlist', 'id': 'p1'}]},
        ]
        new = playlist_entries(tree(folders=folders))
        retitles, splices = plan_update(old, new)
        self.assertEqual(retitles, [])
        self.assertEqual([(index, count, [e.key for e in entries])
                          for index, count, entries in splices],
                         [(5, 0, ['playlist:p1']), (3, 1, [])])  # last first
        # Applied in that order, the old list becomes the new one.
        entries = list(old)
        for index, count, inserted in splices:
            entries[index:index + count] = inserted
        self.assertEqual([e.place() for e in entries], [e.place() for e in new])

    def test_everything_gone_is_one_splice(self):
        old = playlist_entries(tree())
        retitles, splices = plan_update(old, [])
        self.assertEqual(retitles, [])
        self.assertEqual([(index, count) for index, count, _entries in splices], [(0, 6)])


class DecisionsTest(unittest.TestCase):
    """restore_target, reveal and stale_roots over the invented tree."""

    def setUp(self):
        self.entries = by_key(playlist_entries(tree()))
        self.entries['home'] = Destination(HOME, 'Home', 'go-home-symbolic')
        self.entries[ALL_PLAYLISTS] = Destination(ALL_PLAYLISTS, 'All Playlists', 'x')

    def test_restore_a_key_the_sidebar_has(self):
        self.assertEqual(restore_target('home', self.entries, False), ('home', 'home'))
        self.assertEqual(restore_target('playlist:p1', self.entries, True),
                         ('playlist:p1', 'playlist:p1'))

    def test_restore_a_playlist_before_the_library_is_ready(self):
        self.assertEqual(restore_target('playlist:p9', {}, False), (ALL_PLAYLISTS, 'playlist:p9'))
        self.assertEqual(restore_target('folder:z', {}, False), (ALL_PLAYLISTS, 'folder:z'))

    def test_restore_what_is_gone_goes_home(self):
        self.assertEqual(restore_target('playlist:p9', self.entries, True), (HOME, HOME))
        self.assertEqual(restore_target('no-such-page', self.entries, False), (HOME, HOME))
        self.assertEqual(restore_target('', self.entries, True), (HOME, HOME))

    def test_reveal_the_folders_an_entry_is_in(self):
        self.assertEqual(reveal('playlist:p3', self.entries), ('a', 'b'))
        self.assertEqual(reveal('playlist:p1', self.entries), ('a',))
        self.assertEqual(reveal('playlist:p2', self.entries), ())
        self.assertEqual(reveal('home', self.entries), ())
        self.assertEqual(reveal('playlist:p9', self.entries), ())

    def test_stale_roots_are_the_playlists_and_folders_gone(self):
        roots = ['home', 'playlist:p1', 'playlist:p9', 'folder:c', 'folder:z']
        self.assertEqual(stale_roots(roots, self.entries, 'home'),
                         ['playlist:p9', 'folder:z'])
        # The page shown stays (it shows that its playlist is gone).
        self.assertEqual(stale_roots(roots, self.entries, 'playlist:p9'), ['folder:z'])


class TestEntries(unittest.TestCase):
    def test_depth_first_without_favourite_songs(self):
        # Folders first, then playlists, each by title, at every level (library.PlaylistTree).
        entries = playlist_entries(tree())
        self.assertEqual([(e.kind, e.key, e.title, e.depth, e.ancestors) for e in entries], [
            ('folder', 'folder:a', 'Folder A', 0, ()),
            ('folder', 'folder:b', 'Folder B', 1, ('a',)),
            ('playlist', 'playlist:p3', 'P3', 2, ('a', 'b')),
            ('playlist', 'playlist:p1', 'P1', 1, ('a',)),
            ('folder', 'folder:c', 'Folder C', 0, ()),
            ('playlist', 'playlist:p2', 'P2', 0, ()),
        ])
        self.assertEqual([e.icon_name for e in entries],
                         ['folder-symbolic'] * 2 + ['playlist-symbolic'] * 2
                         + ['folder-symbolic', 'playlist-symbolic'])
        self.assertEqual([e.folder_id for e in entries], ['a', 'b', None, None, 'c', None])
        self.assertEqual(entries[2].item.id, 'p3')

    def test_shown_when_every_folder_it_is_in_is_expanded(self):
        entries = playlist_entries(tree())

        def shown(expanded):
            return [e.key for e in entries if is_shown(e, set(expanded))]

        self.assertEqual(shown([]), ['folder:a', 'folder:c', 'playlist:p2'])
        self.assertEqual(shown(['a']), ['folder:a', 'folder:b', 'playlist:p1', 'folder:c',
                                        'playlist:p2'])
        self.assertEqual(shown(['a', 'b']), [e.key for e in entries])
        self.assertEqual(shown(['b']), shown([]))  # b is inside collapsed a

    def test_fixed_entry_and_shape(self):
        entry = SidebarEntry.fixed(Destination('all-playlists', 'All Playlists', 'view-app-grid'))
        self.assertEqual((entry.kind, entry.key, entry.title, entry.depth, entry.item),
                         ('fixed', 'all-playlists', 'All Playlists', 0, None))
        self.assertIsNone(entry.folder_id)
        # A reload of the same tree gives entries of the same shapes, with new Items.
        first, second = playlist_entries(tree()), playlist_entries(tree())
        self.assertEqual([e.shape() for e in first], [e.shape() for e in second])
        self.assertIsNot(first[0].item, second[0].item)

    def test_parse_key(self):
        self.assertEqual(parse_key('playlist:p.1:x'), ('playlist', 'p.1:x'))
        self.assertEqual(parse_key('folder:root'), ('folder', 'root'))
        for key in ('home', 'playlist:', 'album:l.1', '', None):
            with self.subTest(key=key):
                self.assertIsNone(parse_key(key))

    def test_depth_classes_are_capped_at_three_levels(self):
        self.assertEqual(DEPTH_CLASSES, ('depth-1', 'depth-2', 'depth-3'))
        self.assertEqual([depth_class(depth) for depth in range(6)],
                         [None, 'depth-1', 'depth-2', 'depth-3', 'depth-3', 'depth-3'])

    def test_tooltip_is_the_whole_name_escaped(self):
        self.assertEqual(tooltip_markup('A & B <C>'), 'A &amp; B &lt;C&gt;')
        self.assertEqual(tooltip_markup(None), '')
        # A nested playlist's item (no widget inside: a folder's arrow would need a display):
        # its row is indented, so it has no subtitle naming its folder.
        item = SidebarItem(SidebarEntry('playlist', 'playlist:p9', 'A & B <C>', 'x', 1,
                                        playlist('p9', title='A & B <C>'), ('a',)))
        self.assertEqual(item.get_tooltip(), 'A &amp; B &lt;C&gt;')
        self.assertFalse(item.get_subtitle())
        item.retitle('C <D>')
        self.assertEqual((item.get_title(), item.entry.title, item.get_tooltip()),
                         ('C <D>', 'C <D>', 'C &lt;D&gt;'))
        fixed = SidebarItem(SidebarEntry.fixed(Destination('all-playlists', 'All', 'x')))
        self.assertFalse(fixed.get_tooltip())
        self.assertFalse(fixed.get_subtitle())


def deep_tree(folder_a='Folder A'):
    """root: folder a (folder b (folder d (folder e (p5)), p3), p1), p2; folder c (p4).
    `folder_a` renames folder a (after Folder C, "Zed" moves it and its contents)."""
    playlists = [playlist(f'p{n}') for n in range(1, 6)]
    return PlaylistTree([
        {'id': 'root', 'title': '', 'parent': None, 'children': [
            {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
            {'kind': 'folder', 'id': 'c'}]},
        {'id': 'a', 'title': folder_a, 'parent': 'root', 'children': [
            {'kind': 'folder', 'id': 'b'}, {'kind': 'playlist', 'id': 'p1'}]},
        {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
            {'kind': 'folder', 'id': 'd'}, {'kind': 'playlist', 'id': 'p3'}]},
        {'id': 'd', 'title': 'Folder D', 'parent': 'b', 'children': [
            {'kind': 'folder', 'id': 'e'}]},
        {'id': 'e', 'title': 'Folder E', 'parent': 'd', 'children': [
            {'kind': 'playlist', 'id': 'p5'}]},
        {'id': 'c', 'title': 'Folder C', 'parent': 'root', 'children': [
            {'kind': 'playlist', 'id': 'p4'}]},
    ], playlists)


class StubLibrary:
    state = 'ready'

    def __init__(self, playlist_tree):
        self.tree = playlist_tree

    def playlist_tree(self):
        return self.tree

    def favourite_songs(self):
        return None

    def by_id(self, _kind, _item_id):
        return None


class StubSplitView:
    def get_collapsed(self):
        return False

    def set_show_content(self, _show):
        pass


class StubWindow:
    def __init__(self):
        self.shown = None
        self.split_view = StubSplitView()

    def account_key(self, key):
        return key

    def show_root(self, key, pop=False):
        self.shown = key

    def get_focus(self):
        return None


@requires_gtk
class RowDepthTest(unittest.TestCase):
    """The controller gives a nested item's row the depth class style.css indents, capped
    at three levels, and keeps the classes right through the folders opening and closing, a
    reload's splices, a rename that moves a folder and the switch to the page mode and back
    (which builds new rows)."""

    def setUp(self):
        from gi.repository import Adw, Gio

        from applemusic.sidebar_view import SidebarController
        from tests.gtk import SCHEMA_ID

        self.Adw = Adw
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.set_strv('expanded-folders', [])
        self.library = StubLibrary(deep_tree())
        self.widget = Adw.Sidebar()
        self.controller = SidebarController(StubWindow(), self.widget, self.library,
                                            self.settings, item_actions=None)

    def tearDown(self):
        self.controller.write_expanded()  # no timeout left to write after the test
        self.settings.reset('expanded-folders')

    def depths(self):
        """key -> the depth classes on its row, for every item that has a key."""
        rows = self.controller.rows()
        self.assertEqual(len(rows), self.widget.get_items().get_n_items())
        found = {}
        for index, row in enumerate(rows):
            key = self.controller.key_of(self.widget.get_items().get_item(index))
            found[key] = [name for name in DEPTH_CLASSES if row.has_css_class(name)]
        return found

    def assertDepths(self):
        expected = {}
        for key, entry in self.controller.entries_by_key().items():
            depth = getattr(entry, 'depth', 0)  # a fixed section's Destination has none
            expected[key] = [depth_class(depth)] if depth else []
        self.assertEqual(self.depths(), expected)

    def test_classes_follow_depth_capped_at_three(self):
        depths = self.depths()
        self.assertEqual(depths['folder:a'], [])
        self.assertEqual(depths['playlist:p2'], [])
        self.assertEqual(depths[HOME], [])  # a fixed section's
        self.assertEqual(depths[ALL_PLAYLISTS], [])
        self.assertEqual(depths['folder:b'], ['depth-1'])
        self.assertEqual(depths['playlist:p1'], ['depth-1'])
        self.assertEqual(depths['playlist:p3'], ['depth-2'])
        self.assertEqual(depths['folder:d'], ['depth-2'])
        self.assertEqual(depths['folder:e'], ['depth-3'])
        self.assertEqual(depths['playlist:p5'], ['depth-3'])  # four deep: the last indent
        self.assertEqual(depths['playlist:p4'], ['depth-1'])
        self.assertDepths()

    def test_classes_survive_expanding_and_collapsing(self):
        for folder_id in ('a', 'b', 'd', 'e'):
            self.controller._set_expanded(folder_id, True)
            self.assertDepths()
        self.assertTrue(self.controller.item_for('playlist:p5').get_visible())
        self.controller._set_expanded('a', False)
        self.assertFalse(self.controller.item_for('playlist:p5').get_visible())
        self.assertDepths()

    def test_classes_follow_reloads_and_a_rename_that_moves(self):
        self.controller._set_expanded('a', True)
        # Folder A renamed Zed goes after Folder C: it and its contents are spliced out and in.
        self.library.tree = deep_tree(folder_a='Zed')
        self.controller.update_playlists()
        keys = [entry.key for entry in self.controller.entries_by_key().values()
                if getattr(entry, 'kind', None) in ('folder', 'playlist')]
        self.assertLess(keys.index('folder:c'), keys.index('folder:a'))
        self.assertDepths()
        # Back again, and a reload of the same tree (no splice).
        self.library.tree = deep_tree()
        self.controller.update_playlists()
        self.controller.update_playlists()
        self.assertDepths()

    def test_a_stale_class_is_taken_away(self):
        rows = self.controller.rows()
        index = self.controller.item_for('folder:a').get_index()
        nested = self.controller.item_for('playlist:p3').get_index()
        rows[index].add_css_class('depth-2')
        rows[nested].add_css_class('depth-1')
        self.controller.update_rows()
        self.assertDepths()

    def test_classes_follow_the_mode_switch(self):
        self.controller._set_expanded('a', True)
        old_rows = self.controller.rows()
        self.widget.set_mode(self.Adw.SidebarMode.PAGE)
        # New rows, given their classes at once (no frame drawn flat).
        self.assertFalse(set(self.controller.rows()) & set(old_rows))
        self.assertDepths()
        self.widget.set_mode(self.Adw.SidebarMode.SIDEBAR)
        self.assertDepths()

    def test_style_css_indents_the_rows_content(self):
        # With the app's stylesheet, a nested row's icon sits 28px further in per level (the
        # last indent beyond three), in both modes and both directions, whatever libadwaita
        # puts in a row: measured, not read from its widgets' names.
        from gi.repository import Gdk, Gtk

        from tests.gtk import wait_for

        provider = Gtk.CssProvider()
        provider.load_from_resource('/io/github/jackicus/MusicSleeve/style.css')
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, provider)
        for folder_id in ('a', 'b', 'd', 'e', 'c'):
            self.controller._set_expanded(folder_id, True)
        window = Gtk.Window(child=self.widget, default_width=300, default_height=1000)
        self.addCleanup(window.destroy)
        window.present()

        def icon_starts():
            """key -> how far the start of its row's icon is from the row's start."""
            starts = {}
            items = self.widget.get_items()
            for index, row in enumerate(self.controller.rows()):
                if not row.get_visible():
                    continue  # a destination its setting leaves out (Genres)
                icon = next(icon for icon in descendants_all(row, Gtk.Image)
                            if icon.has_css_class('icon') and icon.get_mapped())
                found, bounds = icon.compute_bounds(row)
                if not found or row.get_width() <= 0:
                    return None
                start = bounds.get_x()
                if row.get_direction() == Gtk.TextDirection.RTL:
                    start = row.get_width() - bounds.get_x() - bounds.get_width()
                starts[self.controller.key_of(items.get_item(index))] = start
            return starts

        expected = {'folder:a': 0, 'playlist:p2': 0, ALL_PLAYLISTS: 0, 'folder:b': 28,
                    'playlist:p1': 28, 'playlist:p4': 28, 'folder:d': 56, 'playlist:p3': 56,
                    'folder:e': 84, 'playlist:p5': 84}
        for mode in (self.Adw.SidebarMode.SIDEBAR, self.Adw.SidebarMode.PAGE):
            for direction in (Gtk.TextDirection.LTR, Gtk.TextDirection.RTL):
                with self.subTest(mode=mode, direction=direction):
                    self.widget.set_mode(mode)
                    self.widget.set_direction(direction)
                    starts = None

                    def measured():
                        nonlocal starts
                        starts = icon_starts()
                        return starts is not None and all(
                            round(starts[key] - starts[ALL_PLAYLISTS]) == indent
                            for key, indent in expected.items())

                    wait_for(measured)
                    self.assertIsNotNone(starts, 'the rows laid out')
                    self.assertEqual({key: round(starts[key] - starts[ALL_PLAYLISTS])
                                      for key in expected}, expected)


@requires_gtk
class OfferedDestinationTest(unittest.TestCase):
    """A destination with a setting (Genres, show-genres) is listed while it is on: hidden
    by default, shown and hidden as it changes, Home in its place when it goes while
    selected, and never selected while hidden (a restored last-page shows Home)."""

    def setUp(self):
        from gi.repository import Adw, Gio

        from applemusic.sidebar_view import SidebarController
        from tests.gtk import SCHEMA_ID

        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.set_strv('expanded-folders', [])
        self.addCleanup(self.settings.reset, 'show-genres')
        self.window = StubWindow()
        self.widget = Adw.Sidebar()
        self.controller = SidebarController(self.window, self.widget, StubLibrary(deep_tree()),
                                            self.settings, item_actions=None)
        self.addCleanup(self.controller.write_expanded)

    def test_listed_while_its_setting_is_on(self):
        from applemusic.sections import HOME

        item = self.controller.item_for('genres')
        self.assertFalse(item.get_visible())
        self.assertEqual(self.controller.select('genres'), HOME)  # never a hidden item
        self.assertEqual(self.window.shown, HOME)
        self.settings.set_boolean('show-genres', True)
        self.assertTrue(item.get_visible())
        self.assertEqual(self.controller.select('genres'), 'genres')
        self.assertEqual(self.window.shown, 'genres')
        self.settings.set_boolean('show-genres', False)  # gone while selected: Home
        self.assertFalse(item.get_visible())
        self.assertEqual(self.controller.selected_key(), HOME)
        self.assertEqual(self.window.shown, HOME)
        self.assertTrue(self.controller.item_for('albums').get_visible())  # always listed


class SectionHeadersTest(unittest.TestCase):
    """style.css draws the divider above each titled section on the header libadwaita gives
    it, `sidebar .navigation-sidebar > .header:not(.first)`: each section but the first has
    one, which shows its title and not libadwaita's own separator, in the sidebar mode only."""

    @requires_gtk
    def test_titled_sections_headers_carry_what_the_css_selects(self):
        from gi.repository import Adw, Gtk

        sidebar = Adw.Sidebar()
        specs = sections.sidebar_sections()
        for spec in specs:
            section = Adw.SidebarSection(title=spec.title)
            for destination in spec.destinations:
                section.append(Adw.SidebarItem(title=destination.title))
            sidebar.append(section)
        self.assertEqual(sidebar.get_css_name(), 'sidebar')
        lists = [box for box in descendants(sidebar, Gtk.ListBox)
                 if box.has_css_class('navigation-sidebar')]
        self.assertEqual(len(lists), 1)
        headers = [child for child in children(lists[0]) if child.has_css_class('header')]
        self.assertEqual(len(headers), len(specs))
        self.assertEqual([header.has_css_class('first') for header in headers],
                         [True] + [False] * (len(specs) - 1))
        self.assertIsNone(specs[0].title)
        for spec, header in zip(specs[1:], headers[1:], strict=True):
            self.assertEqual([widget.get_label() for widget in shown(header)
                              if isinstance(widget, Gtk.Label)], [spec.title])
            self.assertFalse([widget for widget in shown(header)
                              if isinstance(widget, Gtk.Separator)])

        # The page mode's sections are boxed lists, which the selector does not reach.
        sidebar.set_mode(Adw.SidebarMode.PAGE)
        self.assertFalse([box for box in descendants(sidebar, Gtk.ListBox)
                          if box.has_css_class('navigation-sidebar')])


def children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def descendants_all(widget, cls):
    """Every descendant of widget that is a cls, depth first, inside them too."""
    for child in children(widget):
        if isinstance(child, cls):
            yield child
        yield from descendants_all(child, cls)


def shown(widget):
    """The descendants of widget that its parents show (a stack's visible child, not the
    others)."""
    for child in children(widget):
        if child.get_child_visible() and child.get_visible():
            yield child
            yield from shown(child)


class StubActions:
    """The item actions the sidebar's drops ask: the real rules (ItemActions.can_move_refs,
    move_targets) over the stub library's tree; the drops recorded."""

    def __init__(self, library):
        from applemusic.actions import ItemActions

        self.library = library
        self.dropped = []
        self.refs = []  # the ItemRefs each drop() was given
        self.can_move_refs = ItemActions.can_move_refs.__get__(self)
        self.can_drop_refs = ItemActions.can_drop_refs.__get__(self)
        self.move_targets = ItemActions.move_targets.__get__(self)

    def can_drop(self, playlist):
        return not playlist.favourites  # these invented ids are no library's ("p.")

    def drop(self, playlist, refs):
        self.dropped.append(('playlist', playlist.id, [ref.id for ref in refs]))
        self.refs.append(refs)
        return True

    def drop_into_folder(self, folder_id, refs):
        self.dropped.append(('folder', folder_id, [ref.id for ref in refs]))
        return True

    def drop_new_playlist(self, refs):
        self.dropped.append(('new playlist', [ref.id for ref in refs]))
        return True


@requires_gtk
class DragDropTest(unittest.TestCase):
    """The sidebar's drops: what each row takes from a drag in progress (dnd.current()), the
    row marked, the drop handed to the item actions; its rows as drag sources; the focus
    kept on a row a move splices anew."""

    def setUp(self):
        from gi.repository import Adw, Gdk, Gio, Gtk

        from applemusic.sidebar_view import SidebarController
        from applemusic.widgets import dnd
        from tests.gtk import SCHEMA_ID

        self.Gdk, self.Gtk, self.dnd = Gdk, Gtk, dnd
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.set_strv('expanded-folders', ['a', 'b', 'c'])
        self.library = StubLibrary(tree())
        self.actions = StubActions(self.library)
        self.widget = Adw.Sidebar()
        self.window = StubWindow()
        self.controller = SidebarController(self.window, self.widget, self.library,
                                            self.settings, self.actions)
        self.addCleanup(dnd._set_current, None)

    def tearDown(self):
        self.controller.write_expanded()
        self.settings.reset('expanded-folders')

    def index(self, key):
        return self.controller.item_for(key).get_index()

    def refs(self, *keys):
        from applemusic.library import ItemRefs

        return ItemRefs.for_objects([self.controller.entry(key).item for key in keys])

    def test_what_each_row_takes(self):
        from applemusic.library import Item, ItemRefs, Ref

        copy, move = self.Gdk.DragAction.COPY, self.Gdk.DragAction.MOVE
        action = self.controller.drop_action
        p1 = self.refs('playlist:p1')  # in folder a
        self.assertEqual(action(self.index('folder:c'), p1), move)
        self.assertEqual(action(self.index('folder:b'), p1), move)
        self.assertEqual(action(self.index('folder:a'), p1), 0)  # where it is
        self.assertEqual(action(self.index('playlist:p2'), p1), copy)  # p1's songs added
        self.assertEqual(action(self.index('playlist:p1'), p1), 0)  # not to itself
        self.assertEqual(action(self.index(ALL_PLAYLISTS), p1), move)  # to the top level
        self.assertEqual(action(self.index(HOME), p1), 0)
        song = ItemRefs([Ref('song', 'i.s1', 'Song')])
        self.assertEqual(action(self.index('playlist:p2'), song), copy)
        self.assertEqual(action(self.index('folder:c'), song), 0)
        # Songs and music videos on All Playlists: a new playlist of them; nowhere else.
        songs = ItemRefs([Ref('song', 'i.s1', 'Song'), Ref('video', 'i.v1', 'Clip')])
        self.assertEqual(action(self.index(ALL_PLAYLISTS), song), copy)
        self.assertEqual(action(self.index(ALL_PLAYLISTS), songs), copy)
        self.assertEqual(action(self.index('playlist:p2'), songs), copy)  # all of them
        # An album (a tile): its songs onto a playlist, a new playlist of them on All
        # Playlists; never into a folder.
        album = ItemRefs.for_objects([Item({'id': 'l.alb1', 'kind': 'album', 'title': 'A'})])
        self.assertEqual(action(self.index('playlist:p2'), album), copy)
        self.assertEqual(action(self.index(ALL_PLAYLISTS), album), copy)
        self.assertEqual(action(self.index('folder:c'), album), 0)
        # A sidebar row's drag offers MOVE alone: a playlist row onto another answers that.
        self.dnd._set_current(p1, move)
        self.assertEqual(action(self.index('playlist:p2'), p1), move)
        self.dnd._set_current(None)
        self.assertEqual(action(self.index(HOME), song), 0)
        mixed = ItemRefs([Ref('song', 'i.s1', 'Song'), Ref('playlist', 'p1', 'P')])
        self.assertEqual(action(self.index(ALL_PLAYLISTS), mixed), 0)
        self.assertEqual(action(self.index('folder:c'), None), 0)  # from elsewhere
        # A folder into another, never into itself or what is inside it.
        folder_a = self.refs('folder:a')
        self.assertEqual(action(self.index('folder:c'), folder_a), move)
        self.assertEqual(action(self.index('folder:b'), folder_a), 0)
        self.assertEqual(action(self.index('folder:a'), folder_a), 0)
        self.assertEqual(action(self.index(ALL_PLAYLISTS), folder_a), 0)  # where it is
        self.assertEqual(action(self.index(ALL_PLAYLISTS), self.refs('folder:b')), move)
        from unittest import mock

        from applemusic.backend import api

        # A move switched off in api is taken nowhere.
        with mock.patch.object(api, 'MOVE_FOLDERS', False), \
                mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', False):
            self.assertEqual(action(self.index('folder:c'), folder_a), 0)
            self.assertEqual(action(self.index(ALL_PLAYLISTS), p1), 0)

    def test_drop_enter_marks_the_row_and_drop_hands_it_over(self):
        self.dnd._set_current(self.refs('playlist:p2'))
        rows = self.controller.rows()
        target, refused = self.index('folder:c'), self.index(HOME)
        self.assertEqual(self.controller._on_drop_enter(self.widget, target),
                         self.Gdk.DragAction.MOVE)
        self.assertTrue(rows[target].has_css_class('drop-highlight'))
        self.assertEqual(self.controller._on_drop_enter(self.widget, refused), 0)
        self.assertFalse(any(row.has_css_class('drop-highlight') for row in rows))
        self.controller._on_drop_enter(self.widget, target)
        self.assertTrue(self.controller._on_drop(self.widget, target,
                                                 self.refs('playlist:p2'), 0))
        self.assertFalse(rows[target].has_css_class('drop-highlight'))  # cleared
        self.assertFalse(self.controller._on_drop(self.widget, refused,
                                                  self.refs('playlist:p2'), 0))
        self.assertEqual(self.actions.dropped, [('folder', 'c', ['p2'])])

    def test_a_playlist_dropped_on_a_playlist_adds_its_songs(self):
        # The drag's own ItemRefs (dnd.current(), with its objects) goes to the actions,
        # not the value GTK loaded.
        from applemusic.library import ItemRefs, Ref

        dragged = self.refs('playlist:p2')
        self.dnd._set_current(dragged)
        target = self.index('playlist:p1')
        self.assertEqual(self.controller._on_drop_enter(self.widget, target),
                         self.Gdk.DragAction.COPY)
        self.assertTrue(self.controller._on_drop(self.widget, target,
                                                 ItemRefs([Ref('playlist', 'p2', '')]), 0))
        self.assertEqual(self.actions.dropped, [('playlist', 'p1', ['p2'])])
        self.assertIs(self.actions.refs[-1], dragged)

    def test_songs_dropped_on_all_playlists_make_a_new_playlist(self):
        from applemusic.library import ItemRefs, Ref
        from tests.gtk import wait_for

        songs = ItemRefs([Ref('song', 'i.s1', 'Song'), Ref('song', 'i.s2', 'Other')])
        self.dnd._set_current(songs)
        target = self.index(ALL_PLAYLISTS)
        self.assertEqual(self.controller._on_drop_enter(self.widget, target),
                         self.Gdk.DragAction.COPY)
        row = self.controller.rows()[target]
        self.assertTrue(row.has_css_class('drop-highlight'))
        self.assertTrue(self.controller._on_drop(self.widget, target, songs, 0))
        self.assertFalse(row.has_css_class('drop-highlight'))
        # The dialog comes once the drop is over.
        self.assertTrue(wait_for(lambda: self.actions.dropped))
        self.assertEqual(self.actions.dropped, [('new playlist', ['i.s1', 'i.s2'])])

    def test_show_drop_target(self):
        rows = self.controller.rows()
        self.controller.show_drop_target('folder:b')
        self.assertTrue(rows[self.index('folder:b')].has_css_class('drop-highlight'))
        self.controller.show_drop_target(None)
        self.assertFalse(any(row.has_css_class('drop-highlight') for row in rows))

    def present(self):
        from tests.gtk import wait_for

        window = self.Gtk.Window(child=self.widget, default_width=300, default_height=900)
        self.addCleanup(window.destroy)
        window.present()
        self.assertTrue(wait_for(lambda: all(row.get_width() > 0 for row in self.controller.rows()
                                             if row.get_child_visible() and row.get_visible())))
        return window

    def middle_of(self, key):
        row = self.controller.row(self.index(key))
        found, bounds = row.compute_bounds(self.widget)
        self.assertTrue(found)
        return (bounds.get_x() + bounds.get_width() / 2,
                bounds.get_y() + bounds.get_height() / 2), row

    def test_rows_are_drag_sources(self):
        self.present()
        (x, y), row = self.middle_of('playlist:p1')
        refs, icon = self.controller._drag_source(x, y)
        self.assertEqual([ref.id for ref in refs], ['p1'])
        self.assertIs(icon, row)
        # A folder too; not a fixed item, nor Favourite Songs.
        (x, y), row = self.middle_of('folder:a')
        refs, icon = self.controller._drag_source(x, y)
        self.assertEqual([(ref.kind, ref.id) for ref in refs], [('folder', 'a')])
        self.assertIs(icon, row)
        for key in (ALL_PLAYLISTS, HOME):
            self.assertIsNone(self.controller._drag_source(*self.middle_of(key)[0]), key)
        self.assertIsNone(self.controller._drag_source(-50, -50))

    def test_the_focus_stays_on_a_moved_row(self):
        from tests.gtk import wait_for

        window = self.present()
        self.window.get_focus = window.get_focus
        self.controller.row(self.index('playlist:p1')).grab_focus()
        self.assertEqual(self.controller._focused_key(), 'playlist:p1')
        # p1 moves from folder a to folder c: its entry and row are new.
        old_row = self.controller.row(self.index('playlist:p1'))
        self.library.tree = tree(folders=[
            {'id': 'root', 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': 'a'}, {'kind': 'playlist', 'id': 'p2'},
                {'kind': 'playlist', 'id': 'fav'}, {'kind': 'folder', 'id': 'c'}]},
            {'id': 'a', 'title': 'Folder A', 'parent': 'root', 'children': [
                {'kind': 'folder', 'id': 'b'}]},
            {'id': 'b', 'title': 'Folder B', 'parent': 'a', 'children': [
                {'kind': 'playlist', 'id': 'p3'}]},
            {'id': 'c', 'title': 'Folder C', 'parent': 'root', 'children': [
                {'kind': 'playlist', 'id': 'p1'}]}])
        self.controller.update_playlists()
        new_row = self.controller.row(self.index('playlist:p1'))
        self.assertIsNot(new_row, old_row)
        self.assertTrue(wait_for(lambda: window.get_focus() is new_row))


class MenuLibrary(StubLibrary):
    """The stub library with the top level's folder Item (All Playlists' menu)."""

    ROOT = Item({'id': 'root', 'kind': 'folder', 'title': ''})

    def by_id(self, kind, item_id):
        return self.ROOT if (kind, item_id) == ('folder', 'root') else None


class MenuActions:
    """The item actions' menu_for: the menu every page and tile shows (actions.build_menu),
    each one asked for recorded."""

    def __init__(self):
        self.asked = []
        self.menus = []

    def menu_for(self, obj, queued=False, queue_entry=None, queue_moves=()):
        from applemusic.actions import build_menu

        self.asked.append(obj)
        self.menus.append(build_menu(obj))
        return self.menus[-1]

    def move_targets(self, _obj):
        return None


class StubGesture:
    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)


@requires_gtk
class ContextMenuTest(unittest.TestCase):
    """A Playlists row's context menu is the item actions' menu for its Item (the page's),
    opened from the row by a right click (at the pointer) or by Menu on the focused row
    (under it); the other sections' rows have none."""

    def setUp(self):
        from gi.repository import Adw, Gio, Gtk

        from applemusic.sidebar_view import SidebarController
        from tests.gtk import SCHEMA_ID

        self.Gtk = Gtk
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.set_strv('expanded-folders', ['a', 'b', 'c'])
        self.library = MenuLibrary(tree())
        self.actions = MenuActions()
        self.widget = Adw.Sidebar()
        self.stub_window = StubWindow()
        self.controller = SidebarController(self.stub_window, self.widget, self.library,
                                            self.settings, self.actions)

    def tearDown(self):
        self.controller.write_expanded()
        self.settings.reset('expanded-folders')

    def present(self):
        from tests.gtk import wait_for

        actions = self.actions

        class Window(self.Gtk.Window):
            item_actions = actions  # what context_menu.popup() asks the row's root for

        window = Window(child=self.widget, default_width=300, default_height=900)
        self.addCleanup(window.destroy)
        window.present()
        self.assertTrue(wait_for(lambda: all(row.get_width() > 0 for row in self.controller.rows()
                                             if row.get_child_visible() and row.get_visible())))
        self.stub_window.get_focus = window.get_focus
        return window

    def row(self, key):
        return self.controller.row(self.controller.item_for(key).get_index())

    def test_the_menu_is_the_items_own(self):
        from tests.gtk import wait_for

        self.present()
        for key, obj in (('playlist:p1', self.controller.entry('playlist:p1').item),
                         ('folder:a', self.controller.entry('folder:a').item),
                         (ALL_PLAYLISTS, MenuLibrary.ROOT)):
            popover = self.controller.popup_menu(key)
            self.assertIsNotNone(popover, key)
            self.assertIs(self.actions.asked[-1], obj)
            self.assertIs(popover.get_menu_model(), self.actions.menus[-1])
            row = self.row(key)
            self.assertIs(popover.get_parent(), row)  # it points at the row
            self.assertTrue(row.has_css_class('has-open-popup'))
            popover.popdown()
            self.assertFalse(row.has_css_class('has-open-popup'))
            self.assertTrue(wait_for(lambda popover=popover: popover.get_parent() is None))
        # The fixed sections have no menu (nor Favourite Songs without its Item here).
        self.assertIsNone(self.controller.popup_menu(HOME))

    def test_a_right_click_opens_it_at_the_pointer(self):
        self.present()
        row = self.row('playlist:p2')
        found, bounds = row.compute_bounds(self.widget)
        self.assertTrue(found)
        x, y = bounds.get_x() + 20, bounds.get_y() + bounds.get_height() / 2
        gesture = StubGesture()
        self.controller._on_menu_press(gesture, x, y)
        self.assertEqual(gesture.states, [self.Gtk.EventSequenceState.CLAIMED])
        popover = next(child for child in children(row)
                       if isinstance(child, self.Gtk.PopoverMenu))
        self.addCleanup(popover.popdown)
        ok, rectangle = popover.get_pointing_to()
        self.assertTrue(ok)
        self.assertEqual((rectangle.x, rectangle.y), (20, int(bounds.get_height() / 2)))
        self.assertIs(self.actions.asked[-1], self.controller.entry('playlist:p2').item)
        # On a row without a menu, the press is left to the row.
        found, bounds = self.row(HOME).compute_bounds(self.widget)
        gesture = StubGesture()
        self.controller._on_menu_press(gesture, bounds.get_x() + 20, bounds.get_y() + 5)
        self.assertEqual(gesture.states, [])

    def test_menu_and_shift_f10_open_the_focused_rows(self):
        from applemusic.widgets import context_menu

        self.present()
        row = self.row('playlist:p1')
        self.assertTrue(row.grab_focus())
        # The keys are a shortcut on the sidebar: Menu and Shift+F10, as on tiles.
        trigger = self.Gtk.ShortcutTrigger.parse_string(context_menu.MENU_KEYS)
        shortcuts = [controller.get_item(index)
                     for controller in self.widget.observe_controllers()
                     if isinstance(controller, self.Gtk.ShortcutController)
                     for index in range(controller.get_n_items())]
        shortcut = next(found for found in shortcuts if found.get_trigger().equal(trigger))
        self.assertTrue(shortcut.get_action().activate(
            self.Gtk.ShortcutActionFlags.EXCLUSIVE, self.widget, None))
        popover = next(child for child in children(row)
                       if isinstance(child, self.Gtk.PopoverMenu))
        self.addCleanup(popover.popdown)
        self.assertFalse(popover.get_pointing_to()[0])  # the whole row: the menu under it
        self.assertIs(self.actions.asked[-1], self.controller.entry('playlist:p1').item)
        # The focus on a fixed row: nothing opens, the key goes on.
        self.assertTrue(self.row(HOME).grab_focus())
        self.assertFalse(self.controller._on_menu_key())



class HeaderStepTest(unittest.TestCase):
    """Up and Down around the Playlists heading's New button, in the sidebar mode."""

    def test_the_steps(self):
        from applemusic.sidebar_view import header_step

        before, first, button, other = object(), object(), object(), object()
        self.assertIs(header_step(before, before, first, button, down=True), button)
        self.assertIs(header_step(button, before, first, button, down=True), first)
        self.assertIs(header_step(first, before, first, button, down=False), button)
        self.assertIs(header_step(button, before, first, button, down=False), before)
        # Anywhere else the list moves as it does.
        self.assertIsNone(header_step(other, before, first, button, down=True))
        self.assertIsNone(header_step(first, before, first, button, down=True))
        self.assertIsNone(header_step(None, before, first, button, down=True))
        self.assertIsNone(header_step(None, None, first, button, down=False))


@requires_gtk
class NewButtonTest(unittest.TestCase):
    """The Playlists heading ends with the New button (New Playlist…, New Folder…, at the
    top level), in both modes and through the changes that make the headings again; Up and
    Down reach it in the sidebar mode."""

    def setUp(self):
        from gi.repository import Adw, Gio, Gtk

        from applemusic.sidebar_view import SidebarController
        from tests.gtk import SCHEMA_ID

        self.Adw, self.Gtk = Adw, Gtk
        self.settings = Gio.Settings.new(SCHEMA_ID)
        self.settings.set_strv('expanded-folders', [])
        self.library = StubLibrary(deep_tree())
        self.widget = Adw.Sidebar()
        self.stub_window = StubWindow()
        self.controller = SidebarController(self.stub_window, self.widget, self.library,
                                            self.settings, item_actions=None)

    def tearDown(self):
        self.controller.write_expanded()
        self.settings.reset('expanded-folders')

    def present(self):
        from tests.gtk import wait_for

        window = self.Gtk.Window(child=self.widget, default_width=300, default_height=900)
        self.addCleanup(window.destroy)
        window.present()
        self.assertTrue(wait_for(lambda: all(row.get_width() > 0 for row in self.controller.rows()
                                             if row.get_child_visible() and row.get_visible())))
        self.stub_window.get_focus = window.get_focus
        return window

    def heading(self):
        """The Playlists heading's Stack (sidebar mode)."""
        row = self.controller.row(self.controller.item_for(ALL_PLAYLISTS).get_index())
        return row.get_header()

    def test_the_button_and_its_menu(self):
        from tests.test_actions import actions_of

        button = self.controller.new_button()
        self.assertEqual(button.get_tooltip_text(), 'New Playlist or Folder')
        self.assertEqual(button.get_icon_name(), 'list-add-symbolic')
        self.assertEqual(actions_of(button.get_menu_model()),
                         [('win.item-new-playlist', ('folder', 'root')),
                          ('win.item-new-folder', ('folder', 'root'))])

    def test_at_the_end_of_the_heading_in_both_modes(self):
        from tests.gtk import pump, wait_for

        self.present()
        button = self.controller.new_button()
        heading = self.heading()
        self.assertTrue(button.is_ancestor(heading))
        shown = heading.get_visible_child()
        labels = [child.get_label() for child in children(shown)
                  if isinstance(child, self.Gtk.Label)]
        self.assertEqual(labels, ['Playlists'])  # the title, then the button
        self.assertIs(shown.get_last_child(), button)
        # A reload's splices and a folder opened make the headings again: still there.
        self.library.tree = deep_tree('Zed')
        self.controller.update_playlists()
        self.controller._set_expanded('a', True)
        pump()
        self.assertTrue(wait_for(lambda: button.is_ancestor(self.heading())))
        # The page mode: the section's group's header suffix; back, the heading's again.
        self.widget.set_mode(self.Adw.SidebarMode.PAGE)

        def last_group():
            groups = list(descendants(self.widget, self.Adw.PreferencesGroup))
            return groups[-1] if groups else None

        self.assertTrue(wait_for(lambda: last_group() is not None
                                 and last_group().get_header_suffix() is button),
                        last_group() and last_group().get_header_suffix())
        self.assertEqual(last_group().get_title(), 'Playlists')
        self.widget.set_mode(self.Adw.SidebarMode.SIDEBAR)
        self.assertTrue(wait_for(lambda: self.heading() is not None
                                 and button.is_ancestor(self.heading())))

    def test_up_and_down_reach_it(self):
        from gi.repository import Gdk

        self.present()
        button = self.controller.new_button()
        first = self.controller.row(self.controller.item_for(ALL_PLAYLISTS).get_index())
        rows = self.controller.rows()
        before = [row for row in rows[:rows.index(first)] if row.get_visible()][-1]

        def key(keyval):
            return self.controller._on_heading_key(None, keyval, 0, 0)

        before.grab_focus()
        self.assertTrue(key(Gdk.KEY_Down))
        self.assertTrue(self.stub_window.get_focus().is_ancestor(button))
        self.assertTrue(key(Gdk.KEY_Down))
        self.assertIs(self.stub_window.get_focus(), first)
        self.assertTrue(key(Gdk.KEY_Up))
        self.assertTrue(self.stub_window.get_focus().is_ancestor(button))
        self.assertTrue(key(Gdk.KEY_Up))
        self.assertIs(self.stub_window.get_focus(), before)
        self.assertFalse(key(Gdk.KEY_Up))  # elsewhere: the list's own move
        # Not in the page mode, where Tab reaches it.
        self.widget.set_mode(self.Adw.SidebarMode.PAGE)
        self.assertFalse(key(Gdk.KEY_Down))


if __name__ == '__main__':
    unittest.main()
