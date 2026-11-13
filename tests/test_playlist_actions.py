# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The playlists' and folders' actions and Remove from Library (applemusic.playlist_actions,
a part of ItemActions): run against the stand-in window, app and engine of
item_actions_harness, the engine's writes recorded, Apple's listing followed."""

import asyncio
import sys
import types
import unittest
from unittest import mock

from gi.repository import GLib

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import item_targets
from applemusic import playlist_actions
from applemusic.actions import ItemActions
from applemusic.backend import api
from applemusic.backend.errors import EngineError
from applemusic.library import Item, ItemRefs, PlaylistTree, Track
from applemusic.playlist_actions import Details, folder_choices, playlist_changes
from tests.item_actions_harness import (CATALOG_ALBUM, CATALOG_PLAYLIST, CATALOG_TRACK, HELD_ALBUM,
                                        HOLDING, LIBRARY_ALBUM, LIBRARY_TRACK, LIBRARY_VIDEO,
                                        LONE_ALBUM, PLAYLIST, PLAYLIST_ANSWER, READ_ONLY,
                                        UPLOAD_TRACK, VIDEO_TRACK, FakeApp, FakeLibrary, FakeWindow,
                                        actions_of, labels_of, mnemonic_clashes, names, submenu_of,
                                        track_of)


class PlaylistDetailsTest(unittest.TestCase):
    """The playlist dialog's Folder row (folder_choices) and what an edit changed
    (playlist_changes)."""

    def setUp(self):
        self.playlist = Item({'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip'})
        self.favourites = Item({'id': 'p.fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                                'attributes': {'isFavourites': True}})
        self.tree = PlaylistTree([
            {'id': 'root', 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': 'p.fd1'}, {'kind': 'folder', 'id': 'p.fd3'},
                {'kind': 'playlist', 'id': 'p.fav'}]},
            {'id': 'p.fd1', 'title': 'Evenings', 'parent': 'root', 'children': [
                {'kind': 'folder', 'id': 'p.fd2'}, {'kind': 'playlist', 'id': 'p.pl1'}]},
            {'id': 'p.fd2', 'title': 'Late', 'parent': 'p.fd1', 'children': []},
            {'id': 'p.fd3', 'title': '', 'parent': 'root', 'children': []},
        ], [self.playlist, self.favourites])

    def test_a_new_playlist_can_go_anywhere(self):
        # In the sidebar's order (the untitled folder first, as its title sorts).
        self.assertEqual(folder_choices(self.tree), [
            ('root', 'Top Level'), ('p.fd3', 'Untitled Folder'), ('p.fd1', 'Evenings'),
            ('p.fd2', 'Evenings › Late')])
        self.assertEqual(folder_choices(None), [('root', 'Top Level')])

    def test_a_playlist_where_it_is_and_where_it_can_go(self):
        self.assertEqual(folder_choices(self.tree, self.playlist), [
            ('root', 'Top Level'), ('p.fd3', 'Untitled Folder'), ('p.fd1', 'Evenings'),
            ('p.fd2', 'Evenings › Late')])
        # Favourite Songs stays where it is: no row.
        self.assertIsNone(folder_choices(self.tree, self.favourites))
        # Apple not known to take a move out to the top level: not offered, but where it is.
        with mock.patch.object(api, 'can_move_to_folder',
                               lambda kind, folder_id: folder_id != 'root'):
            self.assertEqual([choice for choice, _label in
                              folder_choices(self.tree, self.playlist)],
                             ['p.fd3', 'p.fd1', 'p.fd2'])

    def test_what_an_edit_changed(self):
        before = Details('Road Trip', 'Long drives', 'p.fd1', False)
        self.assertEqual(playlist_changes(before, before), {})
        self.assertEqual(playlist_changes(before, before._replace(name=' Road Trip ')), {})
        self.assertEqual(playlist_changes(before, before._replace(name='  ')), {})  # no name
        self.assertEqual(playlist_changes(before, Details(' Night Drive ', '', 'root', True)),
                         {'name': 'Night Drive', 'description': '', 'public': True,
                          'folder': 'root'})



class PlaylistActionsTest(unittest.IsolatedAsyncioTestCase):
    """New Playlist, Rename, Delete and Remove from Playlist: the dialogs stood in for (what
    they would answer is called directly), the engine's writes recorded."""

    async def asyncSetUp(self):
        self.app = FakeApp()
        # The playlist in a folder of the user's, which holds it alone.
        folders = [{'id': 'root', 'title': '', 'parent': None,
                    'children': [{'kind': 'folder', 'id': 'p.fd1'},
                                 {'kind': 'folder', 'id': 'p.fd2'},
                                 {'kind': 'playlist', 'id': 'p.pl2'}]},
                   {'id': 'p.fd1', 'title': 'Evenings', 'parent': 'root',
                    'children': [{'kind': 'playlist', 'id': 'p.pl1'}]},
                   {'id': 'p.fd2', 'title': 'Mornings', 'parent': 'root', 'children': []}]
        self.app.library = FakeLibrary([self.app.playlist, READ_ONLY, self.app.favourites],
                                       folders)
        self.folder = self.app.library.by_id('folder', 'p.fd1')
        self.window = FakeWindow()
        self.actions = ItemActions(self.window, self.app)
        self.asked = []  # (heading, confirm, name, description, done) per name dialog
        self.confirms = []  # (heading, body, confirm, done) per confirmation
        self.details = []  # (heading, confirm, details, folders, done) per playlist dialog
        self.actions.ask_name = lambda *args: self.asked.append(args)
        self.actions.ask_playlist = lambda *args: self.details.append(args)
        self.actions.ask_confirm = lambda *args: self.confirms.append(args)
        for name in ('SETTLE_DELAYS', 'FOLDER_SETTLE_DELAYS'):
            self.addCleanup(setattr, playlist_actions, name, getattr(playlist_actions, name))
            setattr(playlist_actions, name, (0, 0, 0))
        self.actions.playlist_order.settle = (0,)


    async def test_add_to_playlist_nests_the_folders(self):
        # The folder holds the playlist; READ_ONLY and Favourite Songs are left out.
        self.assertEqual(self.actions.playlists(),
                         [('p.fd1', 'Evenings', [('p.pl1', 'Road Trip', None)])])
        menu = self.actions.menu_for(LIBRARY_TRACK)
        evenings = submenu_of(submenu_of(menu, 'Add to Pla_ylist'), 'Evenings')
        self.assertEqual(actions_of(evenings),
                         [('win.item-add-to-playlist', ('p.pl1', 'song', 'i.song1'))])

    async def test_a_folder_with_nothing_to_add_to_is_left_out(self):
        folders = [{'id': 'root', 'title': '', 'parent': None,
                    'children': [{'kind': 'folder', 'id': 'p.fd1'},
                                 {'kind': 'playlist', 'id': 'p.pl1'}]},
                   {'id': 'p.fd1', 'title': 'Evenings', 'parent': 'root',
                    'children': [{'kind': 'folder', 'id': 'p.fd2'},
                                 {'kind': 'playlist', 'id': 'p.pl2'}]},
                   {'id': 'p.fd2', 'title': 'Empty', 'parent': 'p.fd1', 'children': []}]
        self.app.library = FakeLibrary([self.app.playlist, READ_ONLY, self.app.favourites],
                                       folders)
        self.assertEqual(self.actions.playlists(), [('p.pl1', 'Road Trip', None)])
    async def run_action(self, name, *target):
        signature = {3: '(sss)'}.get(len(target), '(ss)')
        if name == 'item-remove-from-playlist':
            signature = '(ssi)'
        elif name == 'item-move-in-playlist':
            signature = '(ssii)'
        elif name == 'item-undo-reorder':
            signature = 's'
            target = target[0]
        self.window.actions[name].activate(GLib.Variant(signature, target))
        await self.settle()

    async def settle(self):
        while self.app.tasks:
            tasks = list(self.app.tasks)
            self.app.tasks.clear()
            await asyncio.gather(*tasks)

    def writes(self):
        return [call for call in self.app.engine.calls
                if call[0] not in ('folder_children', 'rating', 'playlist_track_ids')]  # reads

    async def test_remove_a_track_from_the_playlist_it_is_shown_in(self):
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        track = Track({'id': 'i.song1', 'title': 'Harbour Lights', 'type': 'library-songs',
                       'index': 2}, play={'kind': 'playlist', 'id': 'p.pl1'})
        menu = self.actions.menu_for(track)
        self.assertIn(('win.item-remove-from-playlist', ('p.pl1', 'i.song1', 2)),
                      actions_of(menu))
        await self.run_action('item-remove-from-playlist', 'p.pl1', 'i.song1', 2)
        self.assertEqual(self.writes()[0], ('remove_from_playlist', 'p.pl1', 'i.song1', 2))
        self.assertEqual(self.app.toasts, ['Removed “Harbour Lights” from “Road Trip”'])
        self.assertEqual(self.writes()[-1], ('item', 'playlist', 'p.pl1'))  # its page follows
        self.assertEqual(self.app.syncs, [('tracks', ('p.pl1',))])  # and library.json
        # Shown in Apple's own playlist, or in Favourite Songs: no such item.
        for playlist_id in ('p.pl2', 'p.fav'):
            elsewhere = Track({'id': 'i.song1', 'title': 'Harbour Lights'},
                              play={'kind': 'playlist', 'id': playlist_id})
            self.assertNotIn('win.item-remove-from-playlist',
                             names(self.actions.menu_for(elsewhere)))

    def songs(self, *track_ids):
        """The playlist holding these songs, in this order, as the library has it."""
        play = {'kind': 'playlist', 'id': 'p.pl1'}
        self.app.playlist.merge({'groups': [{'name': 'Tracks', 'play': play, 'entries': [
            {'id': track_id, 'title': f'Song {track_id[2:].upper()}', 'type': 'library-songs',
             'index': index} for index, track_id in enumerate(track_ids)]}]})
        return [self.app.playlist.groups[0].entries.get_item(n) for n in range(len(track_ids))]

    async def test_move_up_and_move_down_in_the_menu(self):
        first, second, third, last = self.songs('i.a', 'i.b', 'i.c', 'i.d')
        moves = [entry for entry in actions_of(self.actions.menu_for(second))
                 if entry[0] == 'win.item-move-in-playlist']
        # Move to Top, Move Up, Move Down, Move to Bottom: the index each moves it to.
        self.assertEqual(moves, [('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, 0)),
                                 ('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, 0)),
                                 ('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, 2)),
                                 ('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, 3))])
        menu = self.actions.menu_for(second)
        labels = labels_of(menu)
        self.assertEqual([label for label in labels
                          if label.replace('_', '').startswith('Move')],
                         ['Move to T_op', '_Move Up', 'Move _Down', 'Mov_e to Bottom'])
        self.assertLess(labels.index('Mov_e to Bottom'), labels.index('Remo_ve from Playlist'))
        self.assertEqual(mnemonic_clashes(menu), [])
        # Not up from the first, nor down from the last.
        self.assertEqual([entry[1][3] for entry in actions_of(self.actions.menu_for(first))
                          if entry[0] == 'win.item-move-in-playlist'], [1, 3])
        self.assertEqual([entry[1][3] for entry in actions_of(self.actions.menu_for(last))
                          if entry[0] == 'win.item-move-in-playlist'], [0, 2])
        self.assertEqual(len([entry for entry in actions_of(self.actions.menu_for(third))
                              if entry[0] == 'win.item-move-in-playlist']), 4)
        # Nowhere else: Apple's playlist, Favourite Songs, an album, a list of one.
        for playlist_id in ('p.pl2', 'p.fav'):
            elsewhere = Track({'id': 'i.b', 'title': 'B', 'index': 0},
                              play={'kind': 'playlist', 'id': playlist_id})
            self.assertNotIn('win.item-move-in-playlist',
                             names(self.actions.menu_for(elsewhere)))
        self.assertNotIn('win.item-move-in-playlist', names(self.actions.menu_for(LIBRARY_TRACK)))
        only, = self.songs('i.a')
        self.assertNotIn('win.item-move-in-playlist', names(self.actions.menu_for(only)))

    async def test_no_move_up_or_down_while_the_playlists_page_filters_it(self):
        _first, second, _last = self.songs('i.a', 'i.b', 'i.c')
        playlist = self.app.playlist

        class Page:
            item = playlist
            reorder = True

            def can_reorder(self):
                return self.reorder

        page = Page()

        class View:
            def get_visible_page(self):
                return page

        self.window.navigation_view = View()
        self.assertIn('win.item-move-in-playlist', names(self.actions.menu_for(second)))
        page.reorder = False  # its filter shows some of its songs
        menu = self.actions.menu_for(second)
        self.assertNotIn('win.item-move-in-playlist', names(menu))
        self.assertIn('win.item-remove-from-playlist', names(menu))  # the rest stays
        page.item = None  # another page shown: its filter is not this playlist's
        self.assertIn('win.item-move-in-playlist', names(self.actions.menu_for(second)))

    async def test_a_move_is_shown_announced_and_written(self):
        self.songs('i.a', 'i.b', 'i.c')
        self.actions.playlist_order.delay = 0
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.b', 1, 2)
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.c', 'i.b'])
        self.assertEqual(self.window.announced, ['“Song B” moved to position 3 of 3'])
        self.assertIn(('reorder_playlist', 'p.pl1', ('i.a', 'i.b', 'i.c'), (0, 2, 1)),
                      self.writes())
        self.assertEqual(self.app.toasts, ['Moved “Song B”'])
        # A menu made before the list changed names a song no longer there: nothing.
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.b', 1, 0)
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.c', 'i.b'])
        # Undo: the order before, written back.
        await self.run_action('item-undo-reorder', 'p.pl1')
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.b', 'i.c'])
        self.assertEqual(self.writes()[-1],
                         ('reorder_playlist', 'p.pl1', ('i.a', 'i.c', 'i.b'), (0, 2, 1)))

    async def test_the_order_pending_goes_before_a_removal(self):
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        self.songs('i.a', 'i.b', 'i.c')
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.c', 2, 1)  # pending
        self.assertNotIn('reorder_playlist', [call[0] for call in self.writes()])
        await self.run_action('item-remove-from-playlist', 'p.pl1', 'i.c', 1)
        self.assertEqual([call[0] for call in self.writes()][:2],
                         ['reorder_playlist', 'remove_from_playlist'])

    async def test_edit_details_of_a_playlist(self):
        self.app.engine.listings = [[], [{'kind': 'playlist', 'id': 'p.pl1',
                                          'name': 'Night Drive'}]]
        await self.run_action('item-rename', 'playlist', 'p.pl1')
        heading, confirm, details, folders, done = self.details[0]
        self.assertEqual((heading, confirm), ('Edit Details', '_Save'))
        self.assertEqual(details, Details('Road Trip', '', 'p.fd1', False))
        # In its folder now, or at the top level, or in the other folder.
        self.assertEqual(folders, [('root', 'Top Level'), ('p.fd1', 'Evenings'),
                                   ('p.fd2', 'Mornings')])
        self.assertEqual(self.asked, [])  # not the name dialog
        done(details._replace(name='Night Drive', description='Late, with the windows down'))
        await self.settle()
        self.assertEqual(self.writes(), [
            ('edit_playlist', 'p.pl1', 'Night Drive', 'Late, with the windows down')])
        # The Item and the sidebar follow at once, the library once Apple lists the name:
        # in the folder that holds it, asked until it is listed.
        self.assertEqual(self.app.playlist.title, 'Night Drive')
        self.assertEqual(self.app.playlist.summary, 'Late, with the windows down')
        self.assertEqual(self.app.library.placed, 1)
        self.assertEqual([call for call in self.app.engine.calls
                          if call[0] == 'folder_children'],
                         [('folder_children', 'p.fd1')] * 2)
        self.assertEqual(self.app.syncs, ['playlists'])

    async def test_edit_details_writes_only_what_changed(self):
        await self.run_action('item-rename', 'playlist', 'p.pl1')
        before, done = self.details[0][2], self.details[0][4]
        # Nothing changed: nothing written.
        self.assertIsNone(self.actions.edit_details(self.app.playlist, before, before))
        # Made public: that alone, and the Item says so at once.
        done(before._replace(public=True))
        await self.settle()
        self.assertEqual(self.writes(), [('edit_playlist', 'p.pl1', None, None, True)])
        self.assertTrue(self.app.playlist.public)
        # Another folder: moved there as Move to Folder moves it, nothing else written.
        await self.run_action('item-rename', 'playlist', 'p.pl1')
        before, done = self.details[1][2], self.details[1][4]
        self.assertTrue(before.public)
        done(before._replace(folder='p.fd2'))
        await self.settle()
        self.assertEqual(self.writes()[1:], [('move_to_folder', 'playlist', 'p.pl1', 'p.fd2')])
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fd2')
        self.assertEqual(self.app.toasts, ['Moved “Road Trip” to “Mornings”'])
        # A refusal is reported, and nothing moves.
        self.app.engine.fail = EngineError('api', 'HTTP 500')
        await self.run_action('item-rename', 'playlist', 'p.pl1')
        before, done = self.details[2][2], self.details[2][4]
        done(before._replace(name='Elsewhere', folder='root'))
        await self.settle()
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fd2')
        self.assertEqual(self.app.playlist.title, 'Road Trip')

    async def test_rename_a_folder(self):
        await self.run_action('item-rename', 'folder', 'p.fd1')
        heading, _confirm, name, description, done = self.asked[0]
        self.assertEqual((heading, name, description), ('Rename Folder', 'Evenings', None))
        done('Late Evenings', None)
        await self.settle()
        self.assertEqual(self.writes(), [('rename_folder', 'p.fd1', 'Late Evenings')])
        self.assertEqual(self.folder.title, 'Late Evenings')
        self.assertIn(('folder_children', 'root'), self.app.engine.calls)

    async def test_what_is_not_the_users_is_not_renamed_or_deleted(self):
        for action in ('item-rename', 'item-delete'):
            for target in (('playlist', 'p.pl2'), ('playlist', 'p.fav'), ('folder', 'root')):
                await self.run_action(action, *target)
        self.assertEqual((self.asked, self.details, self.confirms, self.writes()),
                         ([], [], [], []))
        self.assertEqual(self.app.toasts, ['This cannot be renamed'] * 3
                         + ['This cannot be deleted'] * 3)

    async def test_delete_a_playlist_once_confirmed(self):
        await self.run_action('item-delete', 'playlist', 'p.pl1')
        heading, body, confirm, done = self.confirms[0]
        self.assertEqual((heading, confirm), ('Delete Playlist?', '_Delete'))
        self.assertIn('“Road Trip”', body)
        self.assertIn('all your devices', body)
        self.assertEqual(self.writes(), [])  # nothing before the confirmation
        done()
        await self.settle()
        self.assertEqual(self.writes(), [('delete_playlist', 'p.pl1')])
        self.assertEqual(self.app.toasts, ['Deleted “Road Trip”'])
        # Its pages are left, for the folder that held it; the library follows.
        self.assertEqual(self.window.left, [({('playlist', 'p.pl1')}, 'p.fd1')])
        self.assertEqual(self.app.syncs, ['playlists'])

    async def test_delete_a_folder_with_what_is_in_it(self):
        await self.run_action('item-delete', 'folder', 'p.fd1')
        heading, body, _confirm, done = self.confirms[0]
        self.assertEqual(heading, 'Delete Folder?')
        self.assertIn('“Evenings” and the playlist in it', body)
        done()
        await self.settle()
        self.assertEqual(self.writes(), [('delete_folder', 'p.fd1')])
        self.assertEqual(self.window.left,
                         [({('folder', 'p.fd1'), ('playlist', 'p.pl1')}, 'root')])

    async def test_a_failed_delete_is_reported_and_leaves_nothing(self):
        self.app.engine.fail = EngineError('api', 'HTTP 500')
        await self.run_action('item-delete', 'playlist', 'p.pl1')
        self.confirms[0][3]()
        await self.settle()
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual((self.window.left, self.app.syncs, self.app.toasts), ([], [], []))

    async def test_new_playlist_holding_a_song(self):
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-new-playlist', 'song', 'i.song1')
        heading, confirm, details, folders, done = self.details[0]
        self.assertEqual((heading, confirm, details),
                         ('New Playlist', '_Create', Details('', '', 'root', False)))
        # Any folder can take it.
        self.assertEqual(folders, [('root', 'Top Level'), ('p.fd1', 'Evenings'),
                                   ('p.fd2', 'Mornings')])
        done(Details('Harbour Songs', '', 'root', False))
        await self.settle()
        self.assertEqual(self.writes(), [
            ('create_playlist', 'Harbour Songs', '', (('song', 'i.song1'),), 'root')])
        self.assertEqual(self.app.toasts,
                         ['Added “Harbour Lights” to the new playlist “Harbour Songs”'])
        self.assertIn(('folder_children', 'root'), self.app.engine.calls)
        self.assertEqual(self.window.selected, [])  # the song's page stays

    async def test_songs_dropped_on_all_playlists_make_a_playlist_of_them(self):
        new = Item({'id': 'p.new', 'kind': 'playlist', 'title': 'Harbour Lights'})

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            self.app.library.items[('playlist', 'p.new')] = new  # the pass brought it

        self.app.start_sync = start_sync
        refs = ItemRefs.for_objects([LIBRARY_TRACK, VIDEO_TRACK])
        self.assertTrue(self.actions.drop_new_playlist(refs))
        heading, confirm, details, _folders, done = self.details[0]
        # Named after the first song, which the user may change.
        self.assertEqual((heading, confirm, details),
                         ('New Playlist', '_Create', Details('Harbour Lights', '', 'root')))
        done(details)
        await self.settle()
        self.assertEqual(self.writes(), [
            ('create_playlist', 'Harbour Lights', '',
             (('song', 'i.song1'), ('video', 'i.vid1')), 'root')])
        self.assertEqual(self.app.toasts, ['Created “Harbour Lights”'])
        self.assertEqual(self.window.selected, ['playlist:p.new'])  # then shown
        # One song: the toast names it.
        self.assertTrue(self.actions.drop_new_playlist(ItemRefs.for_objects([UPLOAD_TRACK])))
        self.details[1][4](Details('Takes'))
        await self.settle()
        self.assertEqual(self.app.toasts[-1], 'Added “Demo Take” to the new playlist “Takes”')
        # Playlists dropped there are moved, not made into a playlist: refused here.
        for refused in (ItemRefs.for_objects([PLAYLIST]),
                        ItemRefs.for_objects([LIBRARY_TRACK, PLAYLIST]), None):
            self.assertFalse(self.actions.drop_new_playlist(refused))
        self.assertEqual(len(self.details), 2)

    async def test_new_playlist_in_a_folder_is_shown(self):
        new = Item({'id': 'p.new', 'kind': 'playlist', 'title': 'Fresh'})

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            self.app.library.items[('playlist', 'p.new')] = new  # the pass brought it

        self.app.start_sync = start_sync
        await self.run_action('item-new-playlist', 'folder', 'p.fd1')
        heading, _confirm, details, _folders, done = self.details[0]
        self.assertEqual(details, Details('', '', 'p.fd1', False))  # the folder chosen
        done(Details('Fresh', 'Brand new', 'p.fd1', True))
        await self.settle()
        self.assertEqual(self.writes(), [('create_playlist', 'Fresh', 'Brand new', (), 'p.fd1',
                                          'public')])
        self.assertEqual(self.app.toasts, ['Created “Fresh”'])
        self.assertEqual(self.window.selected, ['playlist:p.new'])

    async def test_duplicate_copies_the_songs_beside_it_and_shows_the_copy(self):
        new = Item({'id': 'p.new', 'kind': 'playlist', 'title': 'Road Trip Copy'})

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            self.app.library.items[('playlist', 'p.new')] = new  # the pass brought it

        self.app.start_sync = start_sync
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER  # its songs, read
        await self.run_action('item-duplicate', 'playlist', 'p.pl1')
        # In its folder, its songs in its own order, its page shown once Apple lists it.
        self.assertEqual(self.writes(), [
            ('item', 'playlist', 'p.pl1'),
            ('create_playlist', 'Road Trip Copy', '', (('song', 'i.song1'),), 'p.fd1')])
        self.assertEqual(self.app.toasts, ['Added 1 song to the new playlist “Road Trip Copy”'])
        self.assertEqual(self.window.selected, ['playlist:p.new'])

    async def test_an_empty_playlist_is_duplicated_empty(self):
        empty = Item({'id': 'p.pl3', 'kind': 'playlist', 'title': 'Quiet', 'description': '',
                      'groups': [{'name': 'Tracks', 'entries': []}]})
        self.actions.duplicate(empty)
        await self.settle()
        self.assertEqual(self.writes(), [('create_playlist', 'Quiet Copy', '', (), 'root')])
        self.assertEqual(self.app.toasts, ['Created “Quiet Copy”'])
        # Not a catalog playlist, and nothing in the demo.
        self.assertIsNone(self.actions.duplicate(
            Item({'id': 'pl.1000000003', 'kind': 'playlist', 'title': 'Harbour Mix'})))
        self.assertEqual(self.app.toasts[-1], 'This cannot be duplicated')
        self.app.demo = True
        self.assertIsNone(self.actions.duplicate(empty))
        self.assertEqual(len(self.writes()), 1)

    async def test_an_empty_playlist_listed_without_its_tracks_is_duplicated_empty(self):
        # A playlist the library lists without its tracks (made empty and never opened: a
        # playlists pass reads no tracks) is read first; Apple answers that it has none, and
        # its copy is made empty all the same, not refused as an add of no songs is.
        unread = Item({'id': 'p.pl3', 'kind': 'playlist', 'title': 'Quiet', 'groups': []})
        self.app.engine.items[('playlist', 'p.pl3')] = {
            'id': 'p.pl3', 'kind': 'playlist', 'title': 'Quiet',
            'groups': [{'name': 'Tracks', 'entries': []}]}
        self.actions.duplicate(unread)
        await self.settle()
        self.assertEqual(self.writes(), [('item', 'playlist', 'p.pl3'),
                                         ('create_playlist', 'Quiet Copy', '', (), 'root')])
        self.assertEqual(self.app.toasts, ['Created “Quiet Copy”'])

    async def test_add_songs_opens_its_dialog_for_a_playlist_of_the_users(self):
        made = []

        class Dialog:
            def __init__(self, app, library, title, done):
                made.append((title, done))

            def present(self, parent):
                made.append(parent)

        module = types.ModuleType('applemusic.dialogs.add_songs')
        module.AddSongsDialog = Dialog
        with mock.patch.dict(sys.modules, {'applemusic.dialogs.add_songs': module}):
            await self.run_action('item-add-songs', 'playlist', 'p.pl1')
            self.assertIsNone(self.actions.ask_add_songs(READ_ONLY))
        self.assertEqual(self.app.toasts, ['Songs cannot be added to this playlist'])
        (title, done), parent = made
        self.assertEqual((title, parent), ('Road Trip', self.window))
        # What it picks goes in at the end of the playlist, in one write.
        done([LIBRARY_TRACK, CATALOG_TRACK])
        await self.settle()
        self.assertIn(('add_tracks_to_playlist', 'p.pl1',
                       (('song', 'i.song1'), ('song', '1000000009'))), self.writes())

    async def test_the_demo_shows_the_dialog_and_writes_nothing(self):
        self.app.demo = True
        await self.run_action('item-new-playlist', 'folder', 'root')
        self.details[0][4](Details('Fresh'))
        await self.run_action('item-delete', 'playlist', 'p.pl1')
        self.confirms[0][3]()
        await self.settle()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.app.toasts, ['Not available with the demo library'] * 2)

    def parent_of(self, kind, item_id):
        return self.app.library.playlist_tree().node(kind, item_id).parent.id

    async def test_move_to_folder_shows_at_once_then_follows_apple(self):
        self.app.engine.moving = asyncio.Event()
        self.window.actions['item-move-to-folder'].activate(
            GLib.Variant('(sss)', ('p.fd2', 'playlist', 'p.pl1')))
        for _turn in range(3):
            await asyncio.sleep(0)
        # Shown in its new folder before Apple has answered.
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fd2')
        self.assertEqual(self.writes(), [])
        self.app.engine.listings = [[{'kind': 'playlist', 'id': 'p.pl1', 'name': 'Road Trip'}]]
        self.app.engine.moving.set()
        await self.settle()
        self.assertEqual(self.writes(), [('move_to_folder', 'playlist', 'p.pl1', 'p.fd2')])
        self.assertEqual(self.app.toasts, ['Moved “Road Trip” to “Mornings”'])
        # Undo moves it back where it was; the library follows Apple's listing.
        self.assertEqual(self.app.buttons, [('Undo', 'win.item-move-to-folder',
                                             ('p.fd1', 'playlist', 'p.pl1'))])
        self.assertIn(('folder_children', 'p.fd2'), self.app.engine.calls)
        self.assertEqual(self.app.syncs, ['playlists'])
        self.assertEqual(self.app.library.released, [])

    async def test_a_move_apple_refuses_is_put_back(self):
        self.app.engine.fail = EngineError('api', 'HTTP 403')
        await self.run_action('item-move-to-folder', 'p.fd2', 'playlist', 'p.pl1')
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fd1')
        self.assertEqual(len(self.app.library.released), 1)
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual((self.app.toasts, self.app.syncs), ([], []))

    async def test_moves_that_are_not_offered_are_refused(self):
        await self.run_action('item-move-to-folder', 'p.fd1', 'playlist', 'p.pl1')  # there
        await self.run_action('item-move-to-folder', 'p.fd1', 'playlist', 'p.fav')
        await self.run_action('item-move-to-folder', 'p.fd1', 'folder', 'p.fd1')  # itself
        await self.run_action('item-move-to-folder', 'root', 'folder', 'p.fd1')  # there
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.app.toasts, ['This cannot be moved there'] * 4)
        # A move switched off in api is refused too.
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', False), \
                mock.patch.object(api, 'MOVE_FOLDERS', False):
            await self.run_action('item-move-to-folder', 'root', 'playlist', 'p.pl1')
            await self.run_action('item-move-to-folder', 'p.fd2', 'folder', 'p.fd1')
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.app.toasts, ['This cannot be moved there'] * 6)

    async def test_a_playlist_to_the_top_level(self):
        await self.run_action('item-move-to-folder', 'root', 'playlist', 'p.pl1')
        self.assertEqual(self.writes(), [('move_to_folder', 'playlist', 'p.pl1', 'root')])
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'root')
        self.assertEqual(self.app.toasts, ['Moved “Road Trip” to the top level'])
        self.assertEqual(self.app.buttons, [('Undo', 'win.item-move-to-folder',
                                             ('p.fd1', 'playlist', 'p.pl1'))])
        # Looked for at the top level as long as a playlist is, then the sync.
        self.assertEqual(self.app.engine.calls.count(('folder_children', 'root')), 3)
        self.assertEqual(self.app.syncs, ['playlists'])

    async def test_a_folder_into_a_folder_and_out(self):
        playlist_actions.FOLDER_SETTLE_DELAYS = (0,) * 5
        await self.run_action('item-move-to-folder', 'p.fd1', 'folder', 'p.fd2')
        self.assertEqual(self.writes(), [('move_to_folder', 'folder', 'p.fd2', 'p.fd1')])
        self.assertEqual(self.parent_of('folder', 'p.fd2'), 'p.fd1')
        self.assertEqual(self.app.toasts, ['Moved “Mornings” to “Evenings”'])
        self.assertEqual(self.app.buttons[-1], ('Undo', 'win.item-move-to-folder',
                                                ('root', 'folder', 'p.fd2')))
        # Apple lists a folder in a folder only about a minute later: looked for longer.
        self.assertEqual(self.app.engine.calls.count(('folder_children', 'p.fd1')), 5)
        # Undo: back out to the top level, looked for there as a playlist is.
        await self.run_action('item-move-to-folder', 'root', 'folder', 'p.fd2')
        self.assertEqual(self.writes()[-1], ('move_to_folder', 'folder', 'p.fd2', 'root'))
        self.assertEqual(self.parent_of('folder', 'p.fd2'), 'root')
        self.assertEqual(self.app.engine.calls.count(('folder_children', 'root')), 3)
        self.assertEqual(self.app.syncs, ['playlists', 'playlists'])

    async def test_dropping_playlists_on_a_folder(self):
        refs = ItemRefs.for_objects([self.app.playlist])
        self.assertTrue(self.actions.can_move_refs(refs, 'p.fd2'))
        self.assertFalse(self.actions.can_move_refs(refs, 'p.fd1'))  # where it is
        self.assertTrue(self.actions.can_move_refs(refs, 'root'))  # out to the top level
        folder = ItemRefs.for_objects([self.folder])
        self.assertTrue(self.actions.can_move_refs(folder, 'p.fd2'))  # a folder into one
        self.assertFalse(self.actions.can_move_refs(folder, 'root'))  # where it is
        self.assertFalse(self.actions.can_move_refs(folder, self.folder.id))  # itself
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', False), \
                mock.patch.object(api, 'MOVE_FOLDERS', False):
            self.assertFalse(self.actions.can_move_refs(refs, 'root'))
            self.assertFalse(self.actions.can_move_refs(folder, 'p.fd2'))
        self.assertFalse(self.actions.can_move_refs(ItemRefs.for_objects([LIBRARY_TRACK]),
                                                    'p.fd2'))
        self.assertFalse(self.actions.can_move_refs(ItemRefs.for_objects([self.app.favourites]),
                                                    'p.fd2'))
        self.assertFalse(self.actions.can_move_refs('not refs', 'p.fd2'))
        self.assertFalse(self.actions.drop_into_folder('p.fd1', refs))
        self.assertTrue(self.actions.drop_into_folder('p.fd2', refs))
        await self.settle()
        self.assertEqual(self.writes(), [('move_to_folder', 'playlist', 'p.pl1', 'p.fd2')])

    async def test_new_folder(self):
        playlist_actions.FOLDER_SETTLE_DELAYS = (0,) * 5
        await self.run_action('item-new-folder', 'folder', 'p.fd1')
        heading, confirm, name, description, done = self.asked[0]
        self.assertEqual((heading, confirm, name, description),
                         ('New Folder', '_Create', '', None))
        done('Box', None)
        await self.settle()
        self.assertEqual(self.writes(), [('create_folder', 'Box', 'p.fd1')])
        # Shown and selected as soon as Apple answers with its id.
        self.assertEqual(self.parent_of('folder', 'p.fdnew'), 'p.fd1')
        self.assertEqual(self.app.library.by_id('folder', 'p.fdnew').title, 'Box')
        self.assertEqual(self.window.selected, ['folder:p.fdnew'])
        self.assertEqual(self.app.toasts, ['Created “Box”'])
        # Apple lists a folder made in a folder only about a minute later: looked for longer.
        self.assertEqual(self.app.engine.calls.count(('folder_children', 'p.fd1')), 5)
        # At the top level, from the main menu or All Playlists.
        await self.run_action('item-new-folder', 'folder', 'root')
        self.asked[1][4]('Top', None)
        await self.settle()
        self.assertEqual(self.writes()[-1], ('create_folder', 'Top', 'root'))

    async def test_new_folder_holding_a_playlist(self):
        await self.run_action('item-move-to-folder', '', 'playlist', 'p.pl1')
        self.assertEqual(self.asked[0][:2], ('New Folder', '_Create'))
        self.asked[0][4]('Box', None)
        await self.settle()
        # Made beside it, then the playlist moved in.
        self.assertEqual(self.writes(), [('create_folder', 'Box', 'p.fd1'),
                                         ('move_to_folder', 'playlist', 'p.pl1', 'p.fdnew')])
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fdnew')
        self.assertEqual(self.app.toasts, ['Created “Box”', 'Moved “Road Trip” to “Box”'])

    async def test_a_failed_new_folder_is_reported(self):
        self.app.engine.fail = EngineError('api', 'HTTP 500')
        await self.run_action('item-new-folder', 'folder', 'root')
        self.asked[0][4]('Box', None)
        await self.settle()
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual((self.window.selected, self.app.library.changes), ([], []))

    async def test_the_demo_moves_and_makes_nothing(self):
        self.app.demo = True
        await self.run_action('item-move-to-folder', 'p.fd2', 'playlist', 'p.pl1')
        await self.run_action('item-new-folder', 'folder', 'root')
        self.asked[0][4]('Box', None)
        await self.settle()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.parent_of('playlist', 'p.pl1'), 'p.fd1')
        self.assertEqual(self.app.toasts, ['Not available with the demo library'] * 2)

    async def test_waiting_for_the_listing(self):
        listed = [{'kind': 'playlist', 'id': 'p.pl1', 'name': 'Road Trip'}]
        engine = self.app.engine
        engine.listings = [[], listed]
        self.assertTrue(await self.actions.wait_listed('root', 'p.pl1', 'Road Trip'))
        engine.listings = [listed, []]
        self.assertTrue(await self.actions.wait_listed('p.fd1', 'p.pl1', None))
        # Gone from a folder that holds more: not while Apple answers it with nothing.
        other = [{'kind': 'playlist', 'id': 'p.pl2', 'name': 'Commute'}]
        folder = [{'kind': 'folder', 'id': 'p.fd1', 'name': 'Evenings'}, *other]
        engine.listings = [folder, [], other]
        self.assertTrue(await self.actions.wait_listed('root', 'p.fd1', None))
        self.assertEqual(engine.listings, [])
        engine.listings = [[], [], []]
        self.assertFalse(await self.actions.wait_listed('root', 'p.fd1', None))
        engine.listings = [listed] * 3
        self.assertFalse(await self.actions.wait_listed('root', 'p.pl1', 'Night Drive'))
        engine.listings = [EngineError('engine-down')]
        self.assertFalse(await self.actions.wait_listed('root', 'p.pl1', None))



class RemoveFromLibraryTest(unittest.IsolatedAsyncioTestCase):
    """Remove from Library: the confirmation stood in for, the library's hide and unhide
    and the engine's writes recorded, the waits for Apple's listing made short."""

    async def asyncSetUp(self):
        self.app = FakeApp()
        folders = [{'id': 'root', 'title': '', 'parent': None,
                    'children': [{'kind': 'folder', 'id': 'p.fd1'}]},
                   {'id': 'p.fd1', 'title': 'Apple', 'parent': 'root',
                    'children': [{'kind': 'playlist', 'id': 'p.pl2'}]}]
        self.app.library = FakeLibrary([LIBRARY_ALBUM, HELD_ALBUM, LONE_ALBUM, READ_ONLY,
                                        HOLDING, LIBRARY_VIDEO, self.app.playlist], folders)
        self.window = FakeWindow()
        self.actions = ItemActions(self.window, self.app)
        self.confirms = []  # (heading, body, confirm, done) per confirmation
        self.actions.ask_confirm = lambda *args: self.confirms.append(args)
        for name, value in (('SETTLE_DELAYS', (0, 0, 0)), ('FOLDER_SETTLE_DELAYS', (0, 0, 0)),
                            ('REMOVAL_DELAYS', (0, 0, 0)), ('LISTING_LAG', 0)):
            self.addCleanup(setattr, playlist_actions, name, getattr(playlist_actions, name))
            setattr(playlist_actions, name, value)

    async def settle(self):
        while self.app.tasks:
            tasks = list(self.app.tasks)
            self.app.tasks.clear()
            await asyncio.gather(*tasks)

    async def remove(self, obj, confirm=True):
        """Remove from Library on obj as its menu runs it, the dialog answered."""
        self.actions.menu_for(obj)
        self.window.actions['item-remove-from-library'].activate(
            GLib.Variant('(ss)', item_targets.describe(obj)))
        await self.settle()
        if confirm and self.confirms:
            self.confirms[-1][3]()
            await self.settle()

    def writes(self):
        return [call for call in self.app.engine.calls
                if call[0] not in ('folder_children', 'rating', 'in_library')]

    async def test_a_song_goes_at_once_then_the_library_follows_apple(self):
        self.app.engine.still_listed = [True, False]  # Apple's read: there, then gone
        await self.remove(track_of(HELD_ALBUM, 0), confirm=False)
        heading, body, confirm, done = self.confirms[0]
        self.assertEqual((heading, confirm), ('Remove from Library?', '_Remove'))
        self.assertIn('“Undertow”', body)
        self.assertEqual(self.writes(), [])  # nothing before the confirmation
        done()
        await self.settle()
        # Left out by its library id and its catalog id (a playlist holds it by that).
        self.assertEqual(self.app.library.hidden,
                         [('hide', {('song', 'i.song3'), ('song', '1000000021')})])
        self.assertEqual(self.writes(), [('remove_from_library', 'song', 'i.song3')])
        self.assertEqual(self.app.toasts, ['Removed “Undertow” from your library'])
        self.assertEqual(self.app.engine.calls.count(('in_library', 'song', 'i.song3')), 2)
        # The quick pass reads again the playlist that held it.
        self.assertEqual(self.app.syncs, [('quick', False, ('p.pl4',))])
        self.assertEqual(self.window.left, [])  # no page shows the song alone

    async def test_an_albums_last_song_takes_its_page(self):
        await self.remove(track_of(LONE_ALBUM, 0))
        self.assertEqual(self.writes(), [('remove_from_library', 'song', 'i.song5')])
        self.assertEqual(self.window.left, [({('album', 'l.alb3')}, None)])

    async def test_an_album_goes_with_its_songs(self):
        await self.remove(HELD_ALBUM)
        self.assertIn('“Low Tide” and its songs', self.confirms[0][1])
        self.assertEqual(self.app.library.hidden, [('hide', {('album', 'l.alb2')})])
        self.assertEqual(self.writes(), [('remove_from_library', 'album', 'l.alb2')])
        self.assertEqual(self.window.left, [({('album', 'l.alb2')}, None)])
        self.assertEqual(self.app.syncs, [('quick', False, ('p.pl4',))])

    async def test_a_music_video(self):
        await self.remove(LIBRARY_VIDEO)
        self.assertEqual(self.app.library.hidden,
                         [('hide', {('video', 'i.vid2'), ('video', '1000000024')})])
        self.assertEqual(self.writes(), [('remove_from_library', 'video', 'i.vid2')])
        self.assertEqual(self.app.syncs, [('quick', True, ('p.pl4',))])

    async def test_a_playlist_of_apples_as_a_deleted_one(self):
        await self.remove(READ_ONLY)
        self.assertNotIn('playlists', self.confirms[0][1])
        self.assertEqual(self.writes(), [('remove_from_library', 'playlist', 'p.pl2')])
        self.assertEqual(self.window.left, [({('playlist', 'p.pl2')}, 'p.fd1')])
        self.assertIn(('folder_children', 'p.fd1'), self.app.engine.calls)
        self.assertEqual(self.app.syncs, ['playlists'])

    async def test_a_held_catalog_albums_menu_agrees_with_its_page(self):
        """A catalog album or playlist the library holds (Library.holds(), the page's In
        Library) has no Add to Library, wherever its menu shows, and Remove from Library
        takes out the library's own."""
        library = self.app.library
        self.assertIn('win.item-add-to-library', names(self.actions.menu_for(CATALOG_ALBUM)))
        library.twins = {('album', CATALOG_ALBUM.id): HELD_ALBUM,
                         ('playlist', CATALOG_PLAYLIST.id): READ_ONLY}
        for obj in (CATALOG_ALBUM, CATALOG_PLAYLIST):
            menu = self.actions.menu_for(obj)
            self.assertNotIn('win.item-add-to-library', names(menu), obj.kind)
            self.assertEqual(actions_of(menu)[-1],
                             ('win.item-remove-from-library', (obj.kind, obj.id)))
        await self.remove(CATALOG_ALBUM)
        self.assertIn('“Harbour Suite” and its songs', self.confirms[-1][1])
        self.assertEqual(library.hidden, [('hide', {('album', 'l.alb2')})])
        await self.remove(CATALOG_PLAYLIST)
        self.assertEqual(self.writes(), [('remove_from_library', 'album', 'l.alb2'),
                                         ('remove_from_library', 'playlist', 'p.pl2')])
        self.assertEqual(self.window.left[-1], ({('playlist', 'p.pl2')}, 'p.fd1'))
        # Only noted as just added: held, so no Add, and nothing to remove yet.
        library.twins = {}
        library.noted.append(CATALOG_ALBUM)
        menu = names(self.actions.menu_for(CATALOG_ALBUM))
        self.assertNotIn('win.item-add-to-library', menu)
        self.assertNotIn('win.item-remove-from-library', menu)

    async def test_a_failure_brings_it_back(self):
        self.app.engine.fail = EngineError('api', 'HTTP 500')
        await self.remove(HELD_ALBUM)
        self.assertEqual(self.app.library.hidden, [('hide', {('album', 'l.alb2')}),
                                                   ('unhide', {('album', 'l.alb2')})])
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual((self.window.left, self.app.syncs, self.app.toasts), ([], [], []))

    async def test_the_wait_for_apple_has_an_end(self):
        self.app.engine.still_listed = [True] * 10
        self.assertFalse(await self.actions.wait_removed('song', 'i.song3'))
        self.assertEqual(self.app.engine.calls.count(('in_library', 'song', 'i.song3')), 3)

    async def test_what_the_library_does_not_hold_is_not_sent(self):
        self.actions.menu_for(CATALOG_ALBUM)
        self.window.actions['item-remove-from-library'].activate(
            GLib.Variant('(ss)', ('album', CATALOG_ALBUM.id)))
        await self.settle()
        self.assertEqual((self.confirms, self.writes()), ([], []))
        self.assertEqual(self.app.toasts, ['This is not in your library'])

    async def test_not_in_the_demo(self):
        self.app.demo = True
        await self.remove(HELD_ALBUM)
        self.assertEqual((self.writes(), self.app.library.hidden), ([], []))
        self.assertEqual(self.app.toasts, ['Not available with the demo library'])



class SettleDelaysTest(unittest.TestCase):
    """How long a change is looked for in Apple's listing (settle_delays)."""

    def test_how_long_a_change_is_looked_for(self):
        # A folder into a folder: past the minute Apple took to list one there.
        delays = playlist_actions.settle_delays('folder', 'p.fd1')
        self.assertIs(delays, playlist_actions.FOLDER_SETTLE_DELAYS)
        self.assertGreater(sum(delays), 75)
        for kind, folder_id in (('folder', 'root'), ('playlist', 'p.fd1'), ('playlist', 'root')):
            self.assertIs(playlist_actions.settle_delays(kind, folder_id),
                          playlist_actions.SETTLE_DELAYS)


if __name__ == '__main__':
    unittest.main()
