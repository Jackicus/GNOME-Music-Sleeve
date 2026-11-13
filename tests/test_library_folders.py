# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The playlist tree and the folder changes held ahead of Apple (library/folders.py), through
the Library that makes and keeps them."""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from tests.test_library import load, playlist, shape, write_library

from applemusic.library import (ROOT_FOLDER, Item, Library, PlaylistTree, TreeChange,
                                apply_changes)
from applemusic.library import folders as folders_module
from applemusic.library import model as model_module
from applemusic.library import text_keys as text_keys_module
from applemusic.library.folders import PENDING_HOLD, change_settled, folder_entries, folder_of


def folder(folder_id, children, parent=ROOT_FOLDER, title=None):
    """A folders entry; children are 'f:<id>' for a folder and a plain id for a playlist."""
    return {'id': folder_id, 'title': title or folder_id, 'parent': parent,
            'children': [{'kind': 'folder', 'id': child[2:]} if child.startswith('f:')
                         else {'kind': 'playlist', 'id': child} for child in children]}


class TestPlaylistTree(unittest.TestCase):
    """PlaylistTree over invented folders: the children lists decide, the rest is tidied up."""

    def test_nesting(self):
        playlists = [playlist(f'p{n}') for n in range(1, 6)]
        tree = PlaylistTree([
            folder('root', ['f:a', 'p5', 'f:c']),
            folder('a', ['f:b', 'p2', 'p1']),
            folder('b', ['p3'], parent='a'),
            folder('c', ['p4']),
        ], playlists)
        self.assertEqual(shape(tree), [
            ('folder', 'a', 0, []),
            ('folder', 'b', 1, ['a']),
            ('playlist', 'p3', 2, ['a', 'b']),
            ('playlist', 'p1', 1, ['a']),
            ('playlist', 'p2', 1, ['a']),
            ('folder', 'c', 0, []),
            ('playlist', 'p4', 1, ['c']),
            ('playlist', 'p5', 0, []),
        ])
        self.assertEqual([child.id for child in tree.root.children], ['a', 'c', 'p5'])
        self.assertEqual([child.id for child in tree.folder('a').children], ['b', 'p1', 'p2'])
        self.assertIs(tree.folder('b').parent, tree.folder('a'))
        self.assertIs(tree.flat[2].item, playlists[2])
        self.assertEqual(tree.folder('a').item.title, 'a')
        self.assertEqual([item.id for item in tree.folder('a').store], ['b', 'p1', 'p2'])

    def test_order_as_apple_music_lists_it(self):
        # At every level: Favourite Songs, the folders, the playlists, each group by title
        # whatever the order of the children lists.
        titles = {'p1': '2. Rocks', 'p2': '1.1 Lively 2', 'p3': '10. Ten', 'p4': '1. Lively',
                  'p5': 'zebra', 'p6': 'Émile', 'p7': 'apple', 'p8': 'Egg', 'p9': 'emu'}
        playlists = [playlist(pid, title) for pid, title in titles.items()]
        favourites = Item({'id': 'fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                           'attributes': {'isFavourites': True}, 'groups': []})
        playlists.append(favourites)
        tree = PlaylistTree([
            folder('root', ['p1', 'f:z', 'p2', 'fav', 'p3', 'f:Old', 'p4', 'f:a']),
            folder('z', ['p5', 'f:inner', 'p6', 'p7'], title='zz'),
            folder('inner', ['p9', 'p8'], parent='z', title='Inner'),
            folder('Old', [], title='OLD'),
            folder('a', [], title='4.XX'),
        ], playlists)

        def titles_of(folder_id):
            return [child.item.title for child in tree.folder(folder_id).children]

        self.assertEqual(titles_of(ROOT_FOLDER), [
            'Favourite Songs', '4.XX', 'OLD', 'zz',
            '1. Lively', '1.1 Lively 2', '10. Ten', '2. Rocks'])
        self.assertEqual(titles_of('z'), ['Inner', 'apple', 'Émile', 'zebra'])
        self.assertEqual(titles_of('inner'), ['Egg', 'emu'])
        # The stores and the depth-first list follow the same order.
        self.assertEqual([item.title for item in tree.root.store], titles_of(ROOT_FOLDER))
        self.assertEqual([node.item.title for node in tree.flat if node.depth == 1],
                         ['Inner', 'apple', 'Émile', 'zebra'])

    def test_title_key(self):
        key = text_keys_module.title_key
        # Case is no matter and accents only part ties; white space, then punctuation,
        # before digits, digits before letters, a digit at a time (no number order).
        ordered = ['', ' a', '-a', '1. Lively', '1.1 Lively 2', '10', '2', 'a', 'cafe',
                   'café', 'É', 'eb', 'Z']
        self.assertEqual(sorted(reversed(ordered), key=key), ordered)
        self.assertEqual(key('CAFE')[0], key('cafe')[0])
        self.assertEqual(key('Cafe'), key('cafe'))  # a tie: the lists' order decides
        self.assertEqual(key(None), key(''))
        self.assertLess(key('Straße'), key('strasse z'))  # casefolded: ß is ss
        self.assertLess(key('٣'), key('4'))  # any script's digits are digits

    def test_ties_keep_the_lists_order(self):
        playlists = [playlist('p1', 'Same'), playlist('p2', 'same'), playlist('p3', 'SAME')]
        tree = PlaylistTree([folder('root', ['p2', 'p3', 'p1'])], playlists)
        self.assertEqual([node.id for node in tree.flat], ['p2', 'p3', 'p1'])
        tree = PlaylistTree([], playlists)  # no folders: the section's order
        self.assertEqual([node.id for node in tree.flat], ['p1', 'p2', 'p3'])

    def test_sort_places_a_retitled_item_again(self):
        playlists = [playlist(f'p{n}', title) for n, title in enumerate('bcd', 1)]
        tree = PlaylistTree([folder('root', ['f:a', 'p1', 'p2', 'p3']),
                             folder('a', [], title='A')], playlists)
        store = tree.root.store
        events = []
        store.connect('items-changed', lambda _store, *change: events.append(change))
        self.assertFalse(tree.sort())  # nothing changed: nothing moves
        self.assertEqual(events, [])
        playlists[2].title = 'a'  # d becomes a: before b, after the folder
        self.assertTrue(tree.sort())
        self.assertEqual([item.id for item in store], ['a', 'p3', 'p1', 'p2'])
        self.assertEqual([node.id for node in tree.flat], ['a', 'p3', 'p1', 'p2'])
        self.assertIs(tree.root.store, store)
        self.assertEqual(len(events), 2)  # moved: out and in, one splice each

    def test_without_folders_every_playlist_is_at_the_top(self):
        playlists = [playlist('p2'), playlist('p1')]
        tree = PlaylistTree([], playlists)
        self.assertEqual(shape(tree), [('playlist', 'p1', 0, []), ('playlist', 'p2', 0, [])])
        self.assertEqual(list(tree.root.store), [playlists[1], playlists[0]])
        self.assertEqual(shape(PlaylistTree()), [])

    def test_what_nothing_lists_goes_at_the_top(self):
        playlists = [playlist(f'p{n}') for n in range(1, 5)]
        root = folder('root', ['p2', 'f:gone', 'p.gone', 'f:p1'])  # p1 is not a folder
        root['children'] += [{'kind': 'station', 'id': 'p4'}, 'p4', {'id': 'p4'}]
        tree = PlaylistTree([root, folder('orphan', ['p3'], parent='nowhere')], playlists)
        self.assertEqual(shape(tree), [
            ('folder', 'orphan', 0, []),
            ('playlist', 'p3', 1, ['orphan']),
            ('playlist', 'p1', 0, []),
            ('playlist', 'p2', 0, []),
            ('playlist', 'p4', 0, []),
        ])

    def test_nothing_twice_and_no_cycles(self):
        playlists = [playlist('p1'), playlist('p2')]
        tree = PlaylistTree([
            folder('root', ['f:a', 'p1', 'f:a']),
            folder('a', ['p1', 'f:b', 'f:a', 'f:root', 'p2']),
            folder('b', ['f:a', 'p2'], parent='a'),
        ], playlists)
        self.assertEqual(shape(tree), [
            ('folder', 'a', 0, []),
            ('folder', 'b', 1, ['a']),
            ('playlist', 'p2', 2, ['a', 'b']),
            ('playlist', 'p1', 1, ['a']),
        ])

    def test_without_a_root_entry_the_top_is_the_parentless_folders(self):
        playlists = [playlist('p1'), playlist('p2')]
        tree = PlaylistTree([
            folder('a', ['p1'], parent=None),
            folder('b', ['p2'], parent='a'),  # listed by nothing: at the top, after a
        ], playlists)
        self.assertEqual(shape(tree), [
            ('folder', 'a', 0, []),
            ('playlist', 'p1', 1, ['a']),
            ('folder', 'b', 0, []),
            ('playlist', 'p2', 1, ['b']),
        ])

    def test_loaded_with_the_library(self):
        with tempfile.TemporaryDirectory() as cache:
            raw = [{'id': f'p{n}', 'kind': 'playlist', 'title': f'P{n}',
                    'play': {'kind': 'playlist', 'id': f'p{n}'}, 'groups': []} for n in (1, 2)]
            write_library(cache, [], playlists=raw,
                          folders=[folder('root', ['f:a']), folder('a', ['p2', 'p1'])])
            library = load(cache)
            first = library.playlist_tree()
            self.assertEqual(shape(first), [('folder', 'a', 0, []), ('playlist', 'p1', 1, ['a']),
                                            ('playlist', 'p2', 1, ['a'])])
            self.assertIs(library.by_id('folder', 'a'), first.folder('a').item)
            self.assertEqual([item.id for item in library.folder_items('a')], ['p1', 'p2'])
            self.assertIs(library.folder_items('a').get_item(0), library.by_id('playlist', 'p1'))
            # Another load makes a new tree, with new folder Items and stores; a library
            # without folders puts everything at the top.
            write_library(cache, [], playlists=raw)
            load(cache, library)
            self.assertIsNot(library.playlist_tree(), first)
            self.assertEqual(shape(library.playlist_tree()),
                             [('playlist', 'p1', 0, []), ('playlist', 'p2', 0, [])])
            self.assertIsNone(library.by_id('folder', 'a'))
            self.assertIsNone(library.folder_items('a'))
        self.assertEqual(shape(Library().playlist_tree()), [])  # before any load

    def test_a_reload_keeps_the_folder_stores(self):
        raw = [{'id': f'p{n}', 'kind': 'playlist', 'title': f'P{n}',
                'play': {'kind': 'playlist', 'id': f'p{n}'}, 'groups': []} for n in (1, 2, 3)]
        library = Library()

        def reload(cache, folders):
            write_library(cache, [], playlists=raw, folders=folders)
            with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                asyncio.run(library.reload())

        with tempfile.TemporaryDirectory() as cache:
            folders = [folder('root', ['f:a', 'p3']), folder('a', ['p2', 'p1'])]
            write_library(cache, [], playlists=raw, folders=folders)
            load(cache, library)
            top, inner = library.folder_items(ROOT_FOLDER), library.folder_items('a')
            folder_a = library.by_id('folder', 'a')
            events = []
            for store in (top, inner):
                store.connect('items-changed',
                              lambda store, *change: events.append((store, change)))
            reload(cache, folders)  # the same file: nothing to tell
            self.assertIs(library.folder_items(ROOT_FOLDER), top)
            self.assertIs(library.folder_items('a'), inner)
            self.assertIs(library.by_id('folder', 'a'), folder_a)
            self.assertEqual(events, [])
            self.assertEqual([item.id for item in inner], ['p1', 'p2'])  # by title
            # p1 moves out of a, to the top level, by title: the same stores, in the new order.
            folders = [folder('root', ['f:a', 'p3', 'p1']), folder('a', ['p2'])]
            reload(cache, folders)
            self.assertIs(library.folder_items(ROOT_FOLDER), top)
            self.assertIs(library.folder_items('a'), inner)
            self.assertEqual([item.id for item in top], ['a', 'p1', 'p3'])
            self.assertEqual([item.id for item in inner], ['p2'])
            self.assertEqual(sorted((store is top, change) for store, change in events),
                             [(False, (0, 1, 0)), (True, (1, 0, 1))])
            # A renamed folder keeps its Item, spliced over itself where it is listed.
            events.clear()
            reload(cache, [folder('root', ['f:a', 'p3', 'p1']), folder('a', ['p2'], title='A!')])
            self.assertIs(library.by_id('folder', 'a'), folder_a)
            self.assertEqual(folder_a.title, 'A!')
            self.assertEqual(events, [(top, (0, 1, 1))])
            # A renamed playlist keeps its Item and moves to its new place in the same store.
            p3 = library.by_id('playlist', 'p3')
            raw[2]['title'] = 'Before P1'
            events.clear()
            reload(cache, [folder('root', ['f:a', 'p3', 'p1']), folder('a', ['p2'], title='A!')])
            self.assertIs(library.by_id('playlist', 'p3'), p3)
            self.assertIs(library.folder_items(ROOT_FOLDER), top)
            self.assertEqual([item.id for item in top], ['a', 'p3', 'p1'])
            self.assertTrue(events)
            self.assertTrue(all(store is top for store, _change in events))

    def test_place_playlists_after_a_rename_in_place(self):
        with tempfile.TemporaryDirectory() as cache:
            raw = [{'id': f'p{n}', 'kind': 'playlist', 'title': f'P{n}',
                    'play': {'kind': 'playlist', 'id': f'p{n}'}, 'groups': []} for n in (1, 2)]
            write_library(cache, [], playlists=raw, folders=[folder('root', ['p1', 'p2'])])
            library = load(cache)
            top = library.folder_items(ROOT_FOLDER)
            tree = library.playlist_tree()
            told = []
            library.connect('playlists-changed', lambda _library: told.append(True))
            library.by_id('playlist', 'p2').title = 'A Rename'
            library.place_playlists()
            self.assertEqual(told, [True])
            self.assertIs(library.playlist_tree(), tree)  # the same tree, placed again
            self.assertIs(library.folder_items(ROOT_FOLDER), top)
            self.assertEqual([item.id for item in top], ['p2', 'p1'])
            self.assertEqual([node.id for node in tree.flat], ['p2', 'p1'])


class TestTreeChanges(unittest.TestCase):
    """Moves and new folders shown ahead of Apple's listing: apply_changes() over library.json's
    folders, the tree's refusals, and Library.hold()/release() through reloads."""

    FOLDERS = [folder('root', ['f:a', 'p3']), folder('a', ['f:b', 'p1']),
               folder('b', ['p2'], parent='a')]

    def tree(self, folders=None, changes=()):
        playlists = [playlist(f'p{n}') for n in (1, 2, 3)]
        return PlaylistTree(apply_changes(folders or self.FOLDERS, list(changes)), playlists)

    def test_a_playlist_into_a_folder_and_out_to_the_top(self):
        into = TreeChange.move('playlist', 'p3', 'b')
        self.assertEqual(shape(self.tree(changes=[into])), [
            ('folder', 'a', 0, []), ('folder', 'b', 1, ['a']),
            ('playlist', 'p2', 2, ['a', 'b']), ('playlist', 'p3', 2, ['a', 'b']),
            ('playlist', 'p1', 1, ['a'])])
        out = TreeChange.move('playlist', 'p2', ROOT_FOLDER)
        self.assertEqual(shape(self.tree(changes=[out]))[-2:],
                         [('playlist', 'p2', 0, []), ('playlist', 'p3', 0, [])])
        # The list given is left alone.
        self.assertEqual(self.FOLDERS[2]['children'], [{'kind': 'playlist', 'id': 'p2'}])

    def test_a_folder_moves_with_what_is_in_it(self):
        moved = self.tree(changes=[TreeChange.move('folder', 'b', ROOT_FOLDER)])
        self.assertEqual(shape(moved), [
            ('folder', 'a', 0, []), ('playlist', 'p1', 1, ['a']),
            ('folder', 'b', 0, []), ('playlist', 'p2', 1, ['b']),
            ('playlist', 'p3', 0, [])])

    def test_a_folder_created(self):
        created = self.tree(changes=[TreeChange.create('c', 'New One', 'a')])
        self.assertIn(('folder', 'c', 1, ['a']), shape(created))
        self.assertEqual(created.folder('c').item.title, 'New One')
        # Twice, or in a folder that is not there: nothing more.
        self.assertEqual(shape(self.tree(changes=[TreeChange.create('c', 'X', 'a')] * 2)),
                         shape(created))
        self.assertEqual(shape(self.tree(changes=[TreeChange.create('c', 'X', 'gone')])),
                         shape(self.tree()))

    def test_a_moved_folder_the_file_lists_nowhere(self):
        # Apple stops listing a folder where it was before it lists it in its new folder:
        # the change's entries put it back, with what is in it.
        self.assertEqual([raw['id'] for raw in folder_entries(self.FOLDERS, 'a')], ['a', 'b'])
        self.assertEqual(folder_entries(self.FOLDERS, 'gone'), ())
        folders = [folder('root', ['f:a', 'f:c', 'p3']), folder('a', ['p1']), folder('c', [])]
        move = TreeChange.move('folder', 'b', 'c')
        self.assertEqual(shape(self.tree(folders, [move])), [  # no entries: skipped
            ('folder', 'a', 0, []), ('playlist', 'p1', 1, ['a']), ('folder', 'c', 0, []),
            ('playlist', 'p2', 0, []), ('playlist', 'p3', 0, [])])
        move.entries = folder_entries(self.FOLDERS, 'b')
        self.assertEqual(shape(self.tree(folders, [move])), [
            ('folder', 'a', 0, []), ('playlist', 'p1', 1, ['a']), ('folder', 'c', 0, []),
            ('folder', 'b', 1, ['c']), ('playlist', 'p2', 2, ['c', 'b']),
            ('playlist', 'p3', 0, [])])
        # The file's own entry wins whenever it has the folder.
        listed = [folder('root', ['f:a', 'f:b', 'f:c', 'p2', 'p3']), folder('a', ['p1']),
                  folder('b', []), folder('c', [])]
        self.assertIn(('folder', 'b', 1, ['c']), shape(self.tree(listed, [move])))
        self.assertIn(('playlist', 'p2', 0, []), shape(self.tree(listed, [move])))

    def test_without_a_root_entry(self):
        folders = [folder('a', ['p1'], parent=None)]
        moved = self.tree(folders, [TreeChange.move('playlist', 'p1', ROOT_FOLDER)])
        self.assertEqual(shape(moved)[:1], [('folder', 'a', 0, [])])
        self.assertIn(('playlist', 'p1', 0, []), shape(moved))

    def test_what_the_tree_refuses(self):
        tree = self.tree()
        self.assertTrue(tree.can_move('playlist', 'p3', 'a'))
        self.assertTrue(tree.can_move('folder', 'b', ROOT_FOLDER))
        self.assertFalse(tree.can_move('playlist', 'p3', ROOT_FOLDER))  # where it is
        self.assertFalse(tree.can_move('folder', 'a', 'a'))  # into itself
        self.assertFalse(tree.can_move('folder', 'a', 'b'))  # into a folder inside it
        self.assertFalse(tree.can_move('folder', ROOT_FOLDER, 'a'))  # the top level
        self.assertFalse(tree.can_move('playlist', 'p9', 'a'))  # not in the tree
        self.assertFalse(tree.can_move('playlist', 'p3', 'gone'))
        favourites = Item({'id': 'fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                           'attributes': {'isFavourites': True}, 'groups': []})
        tree = PlaylistTree(self.FOLDERS, [playlist('p1'), favourites])
        self.assertFalse(tree.can_move('playlist', 'fav', 'a'))
        self.assertIs(tree.node('folder', 'a'), tree.folder('a'))
        self.assertEqual(tree.node('playlist', 'p1').parent.id, 'a')

    def test_settled_when_the_file_shows_it(self):
        folders = [folder('root', ['f:a', 'p3']), folder('a', ['p1'])]
        self.assertTrue(change_settled(folders, TreeChange.move('playlist', 'p1', 'a')))
        self.assertTrue(change_settled(folders, TreeChange.move('playlist', 'p3', ROOT_FOLDER)))
        self.assertTrue(change_settled(folders, TreeChange.move('playlist', 'p9', ROOT_FOLDER)))
        self.assertFalse(change_settled(folders, TreeChange.move('playlist', 'p3', 'a')))
        self.assertTrue(change_settled(folders, TreeChange.create('a', 'A', ROOT_FOLDER)))
        self.assertFalse(change_settled(folders, TreeChange.create('c', 'C', ROOT_FOLDER)))
        self.assertEqual(folder_of(folders, 'folder', 'gone'), None)

    def test_hold_and_release_through_reloads(self):
        raw = [{'id': f'p{n}', 'kind': 'playlist', 'title': f'P{n}',
                'play': {'kind': 'playlist', 'id': f'p{n}'}, 'groups': []} for n in (1, 2, 3)]
        library = Library()
        with tempfile.TemporaryDirectory() as cache:
            def reload(folders):
                write_library(cache, [], playlists=raw, folders=folders)
                with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                    asyncio.run(library.reload())

            write_library(cache, [], playlists=raw, folders=self.FOLDERS)
            load(cache, library)
            top, inner = library.folder_items(ROOT_FOLDER), library.folder_items('a')
            folder_a = library.by_id('folder', 'a')
            told = []
            library.connect('playlists-changed', lambda _library: told.append(True))

            # A move shows at once, in the same stores and folder Items.
            move = TreeChange.move('playlist', 'p3', 'a')
            self.assertTrue(library.hold(move))
            self.assertEqual(told, [True])
            self.assertEqual([item.id for item in top], ['a'])
            self.assertIs(library.folder_items('a'), inner)
            self.assertEqual([item.id for item in inner], ['b', 'p1', 'p3'])
            self.assertIs(library.by_id('folder', 'a'), folder_a)
            # The tree refuses: nothing held, nothing told.
            self.assertFalse(library.hold(TreeChange.move('folder', 'a', 'b')))
            self.assertEqual(len(told), 1)

            # A sync before Apple lists it keeps it shown; one that lists it settles it.
            reload(self.FOLDERS)
            self.assertEqual([item.id for item in inner], ['b', 'p1', 'p3'])
            self.assertEqual(library.pending_changes(), [move])
            reload([folder('root', ['f:a']), folder('a', ['f:b', 'p1', 'p3']),
                    folder('b', ['p2'], parent='a')])
            self.assertEqual(library.pending_changes(), [])
            self.assertEqual([item.id for item in inner], ['b', 'p1', 'p3'])

            # A move and its Undo before any sync: the later replaces the earlier.
            there = TreeChange.move('playlist', 'p2', 'a')
            library.hold(there)
            undone = TreeChange.move('playlist', 'p2', 'b')
            library.hold(undone)
            self.assertEqual(library.pending_changes(), [undone])
            reload(self.FOLDERS)  # the file has it in b: settled, nothing held
            self.assertEqual(library.pending_changes(), [])
            self.assertEqual([item.id for item in library.folder_items('b')], ['p2'])
            reload([folder('root', ['f:a']), folder('a', ['f:b', 'p1', 'p3']),
                    folder('b', ['p2'], parent='a')])

            # Released (Apple refused it): back where the file has it.
            back = TreeChange.move('playlist', 'p3', ROOT_FOLDER)
            library.hold(back)
            self.assertEqual([item.id for item in top], ['a', 'p3'])
            library.release(back)
            self.assertEqual([item.id for item in top], ['a'])
            self.assertEqual(library.pending_changes(), [])

            # A new folder is in the tree and by_id() at once, and goes when released.
            created = TreeChange.create('c', 'Fresh', ROOT_FOLDER)
            self.assertTrue(library.hold(created))
            self.assertEqual(library.by_id('folder', 'c').title, 'Fresh')
            self.assertEqual([item.id for item in top], ['a', 'c'])
            self.assertFalse(library.hold(TreeChange.create('c', 'Again', ROOT_FOLDER)))
            library.release(created)
            self.assertIsNone(library.by_id('folder', 'c'))

    def test_a_folder_moved_into_a_folder_survives_a_sync_that_lists_it_nowhere(self):
        raw = [{'id': f'p{n}', 'kind': 'playlist', 'title': f'P{n}',
                'play': {'kind': 'playlist', 'id': f'p{n}'}, 'groups': []} for n in (1, 2, 3)]
        start = [folder('root', ['f:a', 'f:c', 'p3']), folder('a', ['f:b', 'p1']),
                 folder('b', ['p2'], parent='a'), folder('c', [])]
        library = Library()
        with tempfile.TemporaryDirectory() as cache:
            def reload(folders):
                write_library(cache, [], playlists=raw, folders=folders)
                with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                    asyncio.run(library.reload())

            write_library(cache, [], playlists=raw, folders=start)
            load(cache, library)
            folder_b = library.by_id('folder', 'b')
            move = TreeChange.move('folder', 'b', 'c')
            self.assertTrue(library.hold(move))
            self.assertEqual([item.id for item in library.folder_items('c')], ['b'])
            # Gone from a, not yet listed in c: still shown in c, holding p2.
            reload([folder('root', ['f:a', 'f:c', 'p3']), folder('a', ['p1']), folder('c', [])])
            self.assertEqual(library.pending_changes(), [move])
            self.assertEqual([item.id for item in library.folder_items('c')], ['b'])
            self.assertEqual([item.id for item in library.folder_items('b')], ['p2'])
            self.assertIs(library.by_id('folder', 'b'), folder_b)
            self.assertEqual([item.id for item in library.folder_items(ROOT_FOLDER)],
                             ['a', 'c', 'p3'])
            # Listed there: settled.
            reload([folder('root', ['f:a', 'f:c', 'p3']), folder('a', ['p1']),
                    folder('c', ['f:b']), folder('b', ['p2'], parent='c')])
            self.assertEqual(library.pending_changes(), [])
            self.assertEqual([item.id for item in library.folder_items('c')], ['b'])

    def test_an_expired_change_gives_way_and_a_load_forgets_them(self):
        raw = [{'id': 'p1', 'kind': 'playlist', 'title': 'P1',
                'play': {'kind': 'playlist', 'id': 'p1'}, 'groups': []}]
        folders = [folder('root', ['f:a', 'p1']), folder('a', [])]
        library = Library()
        with tempfile.TemporaryDirectory() as cache:
            write_library(cache, [], playlists=raw, folders=folders)
            load(cache, library)
            with mock.patch.object(folders_module, '_now', return_value=1000.0):
                library.hold(TreeChange.move('playlist', 'p1', 'a'))
            with mock.patch.object(model_module, '_now', return_value=1000.0 + PENDING_HOLD):
                with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': cache}):
                    asyncio.run(library.reload())
            self.assertEqual(library.pending_changes(), [])
            self.assertEqual([item.id for item in library.folder_items('a')], [])
            library.hold(TreeChange.move('playlist', 'p1', 'a'))
            load(cache, library)
            self.assertEqual(library.pending_changes(), [])
            self.assertEqual([item.id for item in library.folder_items('a')], [])


if __name__ == '__main__':
    unittest.main()
