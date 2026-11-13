# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The item actions (applemusic.actions): the win.* actions run against a stand-in window,
app and engine, so add to library, add to playlist, love and the drop onto a sidebar playlist
are checked without Apple. Gio and GObject only, no display; the actions' coroutines run
under asyncio."""

import asyncio
import sys
import types
import unittest
from unittest import mock

from gi.repository import GLib

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import action_messages
from applemusic import actions as actions_module
from applemusic import item_menu
from applemusic import item_targets
from applemusic import playlist_actions
from applemusic.actions import ItemActions, places_after
from applemusic.backend.errors import EngineError
from applemusic.item_menu import RATING_ACTIONS
from applemusic.library import Item, ItemRefs, Ref, Track
from tests.item_actions_harness import (BAND, CATALOG_ALBUM, CATALOG_ARTIST, CATALOG_SONG,
                                        CATALOG_TRACK, CATALOG_VIDEO, FOLDER, HELD_ALBUM, HOLDING,
                                        LIBRARY_ALBUM, LIBRARY_ARTIST, LIBRARY_TRACK, LONE_ALBUM,
                                        LOOSE_ARTIST, PLAYLIST, PLAYLIST_ANSWER, READ_ONLY, SHOW,
                                        STATION, UPCOMING_ALBUM, UPLOAD_TRACK, VIDEO_TRACK, FakeApp,
                                        FakeLibrary, FakeWindow, actions_of, track_of)


class ItemActionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FakeApp()
        self.window = FakeWindow()
        self.actions = ItemActions(self.window, self.app)
        self.launched = []
        self.actions.launch = self.launched.append

    async def run_action(self, name, *target):
        """Activate win.<name> with target, as a menu item does, and wait for its task."""
        signature = '(sss)' if len(target) == 3 else '(ss)'
        if name == 'item-remove-from-queue':
            signature = '(is)'
        elif name == 'item-move-in-queue':
            signature = '(iis)'
        self.window.actions[name].activate(GLib.Variant(signature, target))
        await asyncio.gather(*self.app.tasks)
        self.app.tasks.clear()

    def loved_shown(self):
        """(Favourite enabled, Remove from Favourites enabled): what a menu shows."""
        return (self.window.actions['item-love'].get_enabled(),
                self.window.actions['item-unlove'].get_enabled())

    def rating_shown(self):
        """The rating actions a menu shows (those enabled), in RATING_ACTIONS's order."""
        return [name for name in RATING_ACTIONS if self.window.actions[name].get_enabled()]

    async def test_every_action_is_added_with_its_target_type(self):
        self.assertEqual(sorted(self.window.actions), sorted([
            'item-play', 'item-play-next', 'item-play-later', 'item-love', 'item-unlove',
            'item-add-to-library', 'item-add-to-playlist', 'item-open-in-browser',
            'item-copy-link', 'item-go-to-album', 'item-go-to-artist', 'item-new-playlist',
            'item-rename', 'item-delete', 'item-remove-from-playlist', 'item-new-folder',
            'item-move-to-folder', 'item-remove-from-library', 'item-create-station',
            'item-suggest-less', 'item-undo-suggest-less', 'item-remove-from-queue',
            'item-move-in-queue', 'item-move-in-playlist', 'item-undo-reorder',
            'item-view-credits', 'item-undo-remove', 'item-duplicate', 'item-add-songs',
            'item-undo-unfavourite']))
        self.assertEqual(
            self.window.actions['item-move-in-queue'].get_parameter_type().dup_string(),
            '(iis)')
        self.assertEqual(
            self.window.actions['item-remove-from-queue'].get_parameter_type().dup_string(),
            '(is)')
        self.assertEqual(
            self.window.actions['item-remove-from-playlist'].get_parameter_type().dup_string(),
            '(ssi)')
        self.assertEqual(self.window.actions['item-love'].get_parameter_type().dup_string(),
                         '(ss)')
        self.assertEqual(
            self.window.actions['item-add-to-playlist'].get_parameter_type().dup_string(),
            '(sss)')

    async def test_view_credits_presents_the_dialog(self):
        presented = []

        class Dialog:
            def __init__(self, app, song_id, title):
                self.args = (app, song_id, title)

            def present(self, parent):
                presented.append((*self.args, parent))

        module = types.ModuleType('applemusic.dialogs.credits')
        module.CreditsDialog = Dialog
        with mock.patch.dict(sys.modules, {'applemusic.dialogs.credits': module}):
            self.actions.menu_for(LIBRARY_TRACK)  # the menu names the track
            await self.run_action('item-view-credits', 'song', 'i.song1')
            # A target no menu named: a catalog song by its id, without a title.
            await self.run_action('item-view-credits', 'song', '1000000020')
            # An upload has none.
            await self.run_action('item-view-credits', 'song', 'i.song2')
        self.assertEqual(presented, [(self.app, '1000000001', 'Harbour Lights', self.window),
                                     (self.app, '1000000020', '', self.window)])
        self.assertEqual(self.app.toasts, ['This song has no credits'])

    async def test_remove_from_up_next(self):
        await self.run_action('item-remove-from-queue', 4, 'i.song1')
        self.assertIn(('remove_from_queue', 4, 'i.song1'), self.app.engine.calls)
        self.assertEqual(self.window.announced, ['Removed from Up Next'])
        self.assertEqual(self.app.toasts, [])  # the row goes: no toast
        await self.run_action('item-remove-from-queue', 5, 'i.gone')
        self.assertEqual(self.window.announced, ['Removed from Up Next'])  # nothing taken

    async def test_move_in_up_next(self):
        await self.run_action('item-move-in-queue', 4, 2, 'i.q4')
        self.assertIn(('move_in_queue', 4, 2, 'i.q4'), self.app.engine.calls)
        # Its place among the four after the entry playing.
        self.assertEqual(self.window.announced,
                         ['“Entry 4” moved to position 1 of 4 in Up Next'])
        self.assertEqual(self.app.toasts, [])  # the row moves: no toast
        await self.run_action('item-move-in-queue', 3, 4, 'i.gone')
        self.assertEqual(len(self.window.announced), 1)  # nothing moved

    async def test_from_the_mini_player_up_next_is_announced_by_the_app(self):
        # The mini player's Up Next pane runs these actions with the window hidden: the
        # app tells assistive technology through the window in sight.
        said = []
        self.app.announce = said.append
        await self.run_action('item-remove-from-queue', 4, 'i.song1')
        await self.run_action('item-move-in-queue', 4, 2, 'i.q4')
        self.assertEqual(said[0], 'Removed from Up Next')
        self.assertIn('moved to position', said[1])
        self.assertEqual(self.window.announced, [])

    def test_what_shows_a_page_or_a_dialog_leaves_the_mini_player_first(self):
        shown = []

        class Host:
            shown = True

        self.app.mini_player = Host()
        self.app.show_main_window = lambda: shown.append(True)
        self.assertIs(self.actions.shown_window(), self.window)
        self.assertEqual(shown, [True])
        Host.shown = False
        self.assertIs(self.actions.shown_window(), self.window)
        self.assertEqual(shown, [True])  # the window is in sight: nothing to leave
        Host.shown = True
        album = Item({'kind': 'album', 'id': 'l.shown', 'title': 'Shown'})
        self.actions._show_page(album)
        self.assertEqual((shown, self.window.opened), ([True, True], [album]))

    async def test_love_a_track_by_its_catalog_id(self):
        self.actions.menu_for(LIBRARY_TRACK)  # the menu names the track; its action finds it
        await self.run_action('item-love', 'song', 'i.song1')
        self.assertIn(('love', 'song', '1000000001'), self.app.engine.calls)
        self.assertEqual(self.app.toasts, ['Added to Favourite Songs'])
        self.assertEqual(self.app.player.ensured, 1)
        self.assertEqual(self.loved_shown(), (False, True))  # the engine said so
        await self.run_action('item-unlove', 'song', 'i.song1')
        self.assertIn(('unlove', 'song', '1000000001'), self.app.engine.calls)
        self.assertEqual(self.app.toasts[-1], 'Removed from Favourite Songs')
        self.assertEqual(self.loved_shown(), (True, False))

    async def test_loving_a_song_refreshes_favourite_songs(self):
        answer = dict(PLAYLIST_ANSWER, id='p.fav', title='Favourite Songs',
                      attributes={'isFavourites': True})
        self.app.engine.items[('playlist', 'p.fav')] = answer
        changed = []
        self.app.favourites.connect('groups-changed', lambda *_: changed.append(True))
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-love', 'song', 'i.song1')
        self.assertIn(('item', 'playlist', 'p.fav'), self.app.engine.calls)
        self.assertEqual(changed, [True])
        self.assertEqual([track.id for group in self.app.favourites.groups
                          for track in group.entries], ['i.song1'])
        # An album loved touches no playlist.
        await self.run_action('item-love', 'album', 'l.alb1')
        self.assertEqual(self.app.engine.calls.count(('item', 'playlist', 'p.fav')), 1)

    async def test_suggest_less_and_undo_it(self):
        self.actions.menu_for(LIBRARY_TRACK)
        await asyncio.gather(*self.app.tasks)  # the menu's read: neither
        self.app.tasks.clear()
        self.assertEqual(self.rating_shown(), ['item-love', 'item-suggest-less'])
        await self.run_action('item-suggest-less', 'song', 'i.song1')
        self.assertIn(('suggest_less', 'song', '1000000001'), self.app.engine.calls)
        self.assertEqual(self.app.toasts, ['Apple Music will suggest less like this'])
        self.assertEqual(self.app.player.ensured, 1)
        # Known not loved: Favourite Songs is not fetched again.
        self.assertNotIn('item', [call[0] for call in self.app.engine.calls])
        self.assertEqual(self.rating_shown(), ['item-love', 'item-undo-suggest-less'])
        await self.run_action('item-undo-suggest-less', 'song', 'i.song1')
        self.assertEqual(self.app.engine.calls[-1], ('unlove', 'song', '1000000001'))
        self.assertEqual(self.app.toasts[-1], 'Suggest Less undone')
        self.assertEqual(self.rating_shown(), ['item-love', 'item-suggest-less'])
        # Favourite replaces a Suggest Less: the menu then offers only Remove from Favourites.
        await self.run_action('item-suggest-less', 'song', 'i.song1')
        await self.run_action('item-love', 'song', 'i.song1')
        self.assertEqual(self.rating_shown(), ['item-unlove'])

    async def test_suggest_less_on_albums_playlists_stations_and_videos(self):
        for kind, item_id, rated in (('album', 'l.alb1', ('album', 'l.alb1')),
                                     ('playlist', 'p.pl1', ('playlist', 'p.pl1')),
                                     ('station', 'ra.1000000006', ('station', 'ra.1000000006')),
                                     ('song', 'i.vid1', ('video', '1000000011'))):
            with self.subTest(kind=kind):
                self.actions.menu_for(VIDEO_TRACK)  # the track its target names
                await self.run_action('item-suggest-less', kind, item_id)
                self.assertEqual(self.app.engine.calls[-1], ('suggest_less', *rated))

    async def test_suggest_less_before_the_rating_is_known_refreshes_favourite_songs(self):
        # A song loved elsewhere loses its favourite to a Suggest Less chosen before the
        # menu's read answered: Favourite Songs is fetched again.
        answer = dict(PLAYLIST_ANSWER, id='p.fav', title='Favourite Songs',
                      attributes={'isFavourites': True})
        self.app.engine.items[('playlist', 'p.fav')] = answer
        self.app.engine.state = 'down'  # no read as the menu opens
        self.actions.menu_for(LIBRARY_TRACK)
        self.app.engine.state = 'up'
        await self.run_action('item-suggest-less', 'song', 'i.song1')
        self.assertIn(('item', 'playlist', 'p.fav'), self.app.engine.calls)

    async def test_the_menu_shows_a_suggest_less_it_reads(self):
        self.app.engine.ratings[('album', 'l.alb1')] = -1
        self.actions.menu_for(LIBRARY_ALBUM)
        self.assertEqual(self.rating_shown(), ['item-love', 'item-suggest-less'])
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.rating_shown(), ['item-love', 'item-undo-suggest-less'])

    async def test_unlove_an_album_from_the_library(self):
        await self.run_action('item-unlove', 'album', 'l.alb1')
        self.assertEqual(self.app.engine.calls, [('unlove', 'album', 'l.alb1')])
        self.assertEqual(self.app.toasts, ['Removed from Favourites'])

    async def test_add_to_library(self):
        await self.run_action('item-add-to-library', 'album', '1000000002')
        self.assertEqual(self.app.engine.calls, [('add_to_library', 'album', '1000000002')])
        self.assertEqual(self.app.toasts, ['Added “Harbour Suite” to your library'])
        # A library item is there already: nothing is sent.
        await self.run_action('item-add-to-library', 'album', 'l.alb1')
        self.assertEqual(len(self.app.engine.calls), 1)
        self.assertEqual(self.app.toasts[-1], 'This is in your library already')

    async def test_pre_add_says_so(self):
        task = self.actions.add_to_library(UPCOMING_ALBUM)
        self.assertTrue(await task)
        self.assertEqual(self.app.engine.calls, [('add_to_library', 'album', '1000000060')])
        self.assertEqual(self.app.toasts,
                         ['Pre-added “Harbour Lights To Come” to your library'])

    async def test_add_to_library_shows_what_it_added(self):
        # Apple answers the write with no body, so the item is read back: a quick sync, as
        # add_to_playlist fetches the playlist it wrote to. Without it the song is in the
        # account and nowhere in the app until the next full sync.
        await self.run_action('item-add-to-library', 'album', '1000000002')
        self.assertEqual(self.app.syncs, [True])
        # And the library notes the album, so its page says In Library ahead of the listing.
        self.assertEqual([item.id for item in self.app.library.noted], ['1000000002'])

    async def test_a_page_adds_its_item_and_learns_how_it_went(self):
        # The Add button's way in: the task says whether the write went through.
        task = self.actions.add_to_library(CATALOG_ALBUM)
        self.assertTrue(await task)
        self.assertEqual(self.app.engine.calls, [('add_to_library', 'album', '1000000002')])
        self.assertEqual(self.app.library.noted, [CATALOG_ALBUM])
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        self.assertFalse(await self.actions.add_to_library(CATALOG_ALBUM))
        self.assertEqual(self.app.library.noted, [CATALOG_ALBUM])  # not noted again
        self.assertIsNone(self.actions.add_to_library(LIBRARY_ALBUM))  # the library's own

    async def test_nothing_is_synced_when_the_add_fails(self):
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        await self.run_action('item-add-to-library', 'album', '1000000002')
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.app.syncs, [])
        self.assertEqual(self.app.library.noted, [])

    async def test_add_to_playlist_and_refresh_it(self):
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        changed = []
        self.app.playlist.connect('groups-changed', lambda *_: changed.append(True))
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-add-to-playlist', 'p.pl1', 'song', 'i.song1')
        self.assertIn(('add_to_playlist', 'p.pl1', 'i.song1', 'song'), self.app.engine.calls)
        self.assertEqual(self.app.toasts, ['Added “Harbour Lights” to “Road Trip”'])
        # The playlist is fetched again and the library's Item follows: its page re-shows.
        self.assertEqual(self.app.engine.calls[-1], ('item', 'playlist', 'p.pl1'))
        self.assertEqual(changed, [True])
        self.assertEqual(self.app.playlist.raw.get('trackCount'), 1)
        self.assertEqual(self.app.syncs, [('tracks', ('p.pl1',))])  # into library.json too

    async def test_a_refresh_that_fails_is_only_logged(self):
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-add-to-playlist', 'p.pl1', 'song', 'i.song1')
        self.assertEqual(self.app.engine.calls[-1], ('item', 'playlist', 'p.pl1'))  # no answer
        self.assertEqual(self.app.toasts, ['Added “Harbour Lights” to “Road Trip”'])
        self.assertEqual(self.app.reported, [])

    async def test_a_music_video_is_added_as_one(self):
        self.actions.menu_for(VIDEO_TRACK)
        await self.run_action('item-add-to-playlist', 'p.pl1', 'song', 'i.vid1')
        self.assertIn(('add_to_playlist', 'p.pl1', 'i.vid1', 'video'), self.app.engine.calls)
        await self.run_action('item-love', 'song', 'i.vid1')
        self.assertIn(('love', 'video', '1000000011'), self.app.engine.calls)

    async def test_the_submenu_lists_the_playlists_that_take_songs(self):
        menu = self.actions.menu_for(LIBRARY_TRACK)
        targets = [target for action, target in actions_of(menu)
                   if action == 'win.item-add-to-playlist']
        self.assertEqual(targets, [('p.pl1', 'song', 'i.song1')])  # not read-only, favourites

    async def test_the_submenu_lists_the_playlists_in_the_sidebars_order(self):
        # By title, whatever the library's order (library.PlaylistTree).
        titles = ['Zulu', '2. Two', 'alpha', '1. One']
        self.app.library = FakeLibrary(
            [Item({'id': f'p.o{n}', 'kind': 'playlist', 'title': title, 'groups': []})
             for n, title in enumerate(titles)] + [self.app.favourites])
        self.assertEqual([title for _id, title, _children in self.actions.playlists()],
                         ['1. One', '2. Two', 'alpha', 'Zulu'])

    async def test_drop_on_a_playlist(self):
        ref = ItemRefs([Ref('song', '1000000009', 'Shoreline')])
        self.assertTrue(self.actions.drop(self.app.playlist, ref))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.app.engine.calls[0],
                         ('add_to_playlist', 'p.pl1', '1000000009', 'song'))
        self.assertEqual(self.app.toasts, ['Added “Shoreline” to “Road Trip”'])
        video = ItemRefs([Ref('video', 'i.vid1', 'Live')])
        self.assertTrue(self.actions.drop(self.app.playlist, video))
        await asyncio.gather(*self.app.tasks)
        self.assertIn(('add_to_playlist', 'p.pl1', 'i.vid1', 'video'), self.app.engine.calls)
        for playlist in (READ_ONLY, self.app.favourites, FOLDER, LIBRARY_ALBUM, None):
            self.assertFalse(self.actions.drop(playlist, ref))
        self.assertFalse(self.actions.drop(self.app.playlist, ItemRefs()))
        self.assertFalse(self.actions.drop(self.app.playlist, 'not a ref'))
        # A playlist is not dropped on itself; nor is a folder or a station on a playlist.
        self.assertFalse(self.actions.drop(self.app.playlist, ItemRefs.for_objects([PLAYLIST])))
        for refused in (FOLDER, STATION):
            self.assertFalse(self.actions.drop(self.app.playlist,
                                               ItemRefs.for_objects([refused])))
        self.assertEqual(len([call for call in self.app.engine.calls
                              if call[0] == 'add_to_playlist']), 2)
        # Several songs: all of them, in order, in one add.
        self.app.toasts.clear()
        self.assertTrue(self.actions.drop(self.app.playlist, ItemRefs(
            [Ref('song', '1', 'One'), Ref('song', '2', 'Two')])))
        await asyncio.gather(*self.app.tasks)
        self.assertIn(('add_tracks_to_playlist', 'p.pl1', (('song', '1'), ('song', '2'))),
                      self.app.engine.calls)
        self.assertEqual(self.app.toasts, ['Added 2 songs to “Road Trip”'])

    def adds(self):
        return [call[1:] for call in self.app.engine.calls if call[0] == 'add_tracks_to_playlist']

    async def test_an_albums_songs_are_added_to_a_playlist(self):
        # A library album: its own tracks, in order, every disc, by their library ids (a
        # music video as one); one add, one toast, the playlist fetched again.
        album = Item({'id': 'l.alb9', 'kind': 'album', 'title': 'Tidewater', 'groups': [
            {'name': 'Disc 1', 'entries': [
                {'id': 'i.s1', 'title': 'One', 'type': 'library-songs'},
                {'id': '', 'title': 'Lost'},  # no id: left out
                {'id': 'i.v1', 'title': 'Two (Video)', 'type': 'library-music-videos'}]},
            {'name': 'Disc 2', 'entries': [
                {'id': 'i.s3', 'title': 'Three', 'type': 'library-songs'}]}]})
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        self.assertTrue(await self.actions.add_items_to_playlist('p.pl1', [album]))
        self.assertEqual(self.adds(), [
            ('p.pl1', (('song', 'i.s1'), ('video', 'i.v1'), ('song', 'i.s3')))])
        self.assertEqual(self.app.toasts, ['Added 3 songs to “Road Trip”'])
        self.assertIn(('item', 'playlist', 'p.pl1'), self.app.engine.calls)  # fetched again
        self.assertNotIn(('item', 'album', 'l.alb9'), self.app.engine.calls)  # had them

    async def test_a_catalog_albums_songs_are_read_first(self):
        # One that came without its tracks (a shelf's): the engine's item() read gives them
        # (all of them: it follows Apple's pages), by their catalog ids. Through the menu.
        self.app.engine.items[('album', '1000000002')] = {
            'id': '1000000002', 'kind': 'album', 'title': 'Harbour Suite', 'groups': [
                {'name': '', 'entries': [{'id': '1000000020', 'title': 'Overture'},
                                         {'id': '1000000021', 'title': 'Reprise'}]}]}
        self.actions.menu_for(CATALOG_ALBUM)
        await self.run_action('item-add-to-playlist', 'p.pl1', 'album', '1000000002')
        self.assertIn(('item', 'album', '1000000002'), self.app.engine.calls)
        self.assertEqual(self.adds(), [('p.pl1', (('song', '1000000020'),
                                                  ('song', '1000000021')))])
        self.assertEqual(self.app.toasts, ['Added 2 songs to “Road Trip”'])

    async def test_a_playlists_songs_are_added_from_a_drop(self):
        # A playlist's tile dropped on another playlist: its tracks, in its order.
        source = Item({'id': 'p.pl7', 'kind': 'playlist', 'title': 'Mixtape', 'groups': [
            {'name': '', 'entries': [{'id': 'i.s4', 'title': 'Four', 'type': 'library-songs'},
                                     {'id': 'i.s5', 'title': 'Five',
                                      'type': 'library-songs'}]}]})
        refs = ItemRefs.for_objects([source])
        self.assertTrue(self.actions.can_drop_refs(self.app.playlist, refs))
        self.assertTrue(self.actions.drop(self.app.playlist, refs))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.adds(), [('p.pl1', (('song', 'i.s4'), ('song', 'i.s5')))])
        # Its Refs alone (no objects): the library's playlist, or one read by its id.
        self.app.engine.items[('album', '1000000002')] = {
            'id': '1000000002', 'kind': 'album', 'groups': [
                {'entries': [{'id': '1000000020', 'title': 'Overture'}]}]}
        self.assertTrue(self.actions.drop(self.app.playlist, ItemRefs(
            [Ref('album', '1000000002', 'Harbour Suite'), Ref('song', 'i.s9', 'Nine')])))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.adds()[-1], ('p.pl1', (('song', '1000000020'), ('song', 'i.s9'))))

    async def test_the_same_add_is_not_made_twice_at_once(self):
        self.app.engine.adding = asyncio.Event()
        album = Item({'id': 'l.alb9', 'kind': 'album', 'title': 'Tidewater', 'groups': [
            {'entries': [{'id': 'i.s1', 'title': 'One'}]}]})
        first = self.actions.add_items_to_playlist('p.pl1', [album])
        self.assertIsNone(self.actions.add_items_to_playlist('p.pl1', [album]))  # a 2nd click
        other = self.actions.add_items_to_playlist('p.pl2', [album])  # another playlist: made
        self.app.engine.adding.set()
        self.assertTrue(await first)
        self.assertTrue(await other)
        self.assertEqual([playlist for playlist, _tracks in self.adds()], ['p.pl1', 'p.pl2'])
        # Once it is done, it can be made again.
        self.assertTrue(await self.actions.add_items_to_playlist('p.pl1', [album]))

    async def test_a_failed_add_is_reported_and_followed(self):
        album = Item({'id': 'l.alb9', 'kind': 'album', 'title': 'Tidewater', 'groups': [
            {'entries': [{'id': 'i.s1', 'title': 'One'}]}]})
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        self.assertIs(await self.actions.add_items_to_playlist('p.pl1', [album]), False)
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.app.toasts, [])
        # A catalog album whose read fails: reported, nothing sent.
        self.app.engine.fail = None
        self.app.engine.calls.clear()
        self.assertIs(await self.actions.add_items_to_playlist('p.pl1', [CATALOG_ALBUM]), False)
        self.assertEqual(self.app.reported, ['api', 'api'])
        self.assertEqual(self.adds(), [])
        # Nothing to add (an album without songs): said, nothing sent.
        empty = Item({'id': 'l.alb_00000000none', 'kind': 'album', 'title': 'Empty'})
        self.assertIs(await self.actions.add_items_to_playlist('p.pl1', [empty]), False)
        self.assertEqual(self.app.toasts, ['There are no songs to add'])
        self.assertEqual(self.adds(), [])
        self.app.demo = True
        self.assertIsNone(self.actions.add_items_to_playlist('p.pl1', [album]))

    async def test_a_new_playlist_of_an_albums_songs(self):
        # New Playlist… in an album's Add to Playlist: the name filled in with its title,
        # its songs read, the playlist made holding them, the toast counting them.
        asked = []
        self.actions.ask_playlist = lambda *args: asked.append(args)
        album = Item({'id': 'l.alb9', 'kind': 'album', 'title': 'Tidewater', 'groups': [
            {'entries': [{'id': 'i.s1', 'title': 'One'}, {'id': 'i.s2', 'title': 'Two'}]}]})
        self.actions.menu_for(album)
        self.actions.actions['item-new-playlist'].activate(GLib.Variant('(ss)',
                                                                        ('album', 'l.alb9')))
        _heading, _confirm, details, _folders, done = asked[0]
        self.assertEqual(details.name, 'Tidewater')
        await done(details)
        self.assertIn(('create_playlist', 'Tidewater', '', (('song', 'i.s1'), ('song', 'i.s2')),
                       'root'), self.app.engine.calls)
        self.assertEqual(self.app.toasts[0], 'Added 2 songs to the new playlist “Tidewater”')

    def test_container_tracks_and_the_messages(self):
        self.assertIsNone(item_targets.container_tracks(CATALOG_ALBUM))  # read them first
        self.assertEqual(item_targets.container_tracks(LOOSE_ARTIST),
                         [('song', 'i.song7')])
        self.assertEqual(action_messages.added_message(1, 'Road Trip'),
                         'Added 1 song to “Road Trip”')
        self.assertEqual(action_messages.added_message(12, ''), 'Added 12 songs to the playlist')
        self.assertTrue(item_targets.adds_songs(CATALOG_ALBUM))
        self.assertTrue(item_targets.adds_songs(PLAYLIST))
        self.assertFalse(item_targets.adds_songs(FOLDER))
        self.assertFalse(item_targets.adds_songs(CATALOG_SONG))
        self.assertTrue(item_targets.new_playlist_refs(ItemRefs.for_objects([LIBRARY_ALBUM])))
        self.assertFalse(item_targets.new_playlist_refs(ItemRefs.for_objects([PLAYLIST])))

    async def test_drops_on_the_player_bar_are_queued(self):
        def calls():
            return [call for call in self.app.engine.calls if call[0] in ('play_next',
                                                                          'play_later')]

        song = ItemRefs.for_objects([LIBRARY_TRACK])
        self.assertTrue(self.actions.queue_drop(song))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(calls(), [('play_later', 'song', '1000000001')])  # its catalog id
        self.assertEqual(self.app.toasts, ['“Harbour Lights” will play later'])
        self.app.engine.calls.clear()
        # Several, Shift held: each after the item playing, in the order dragged.
        several = ItemRefs.for_objects([LIBRARY_TRACK, PLAYLIST, CATALOG_ALBUM])
        self.assertTrue(self.actions.queue_drop(several, next_up=True))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(calls(), [('play_next', 'album', '1000000002'),
                                   ('play_next', 'playlist', 'p.pl1'),
                                   ('play_next', 'song', '1000000001')])
        self.assertEqual(self.app.toasts[-1], '3 items will play next')
        self.app.engine.calls.clear()
        # A folder cannot be queued: the drop is refused, nothing of it queued.
        for refused in (ItemRefs.for_objects([PLAYLIST, FOLDER]),
                        ItemRefs([Ref('song', 'i.song1', 'Harbour Lights')]), None):
            self.assertFalse(self.actions.queue_drop(refused))
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(calls(), [])
        self.assertEqual(self.app.player.ensured, 0)  # the Player's commands do that
        self.app.demo = True
        self.assertTrue(self.actions.queue_drop(song))
        self.assertEqual(self.app.toasts[-1], 'Not available with the demo library')

    async def test_a_failure_is_reported_not_confirmed(self):
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        await self.run_action('item-add-to-playlist', 'p.pl1', 'song', 'i.song1')
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.app.toasts, [])

    async def test_the_task_says_whether_the_add_succeeded(self):
        self.assertIs(await self.actions.add_to_playlist('p.pl1', 'i.song1'), True)
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        self.assertIs(await self.actions.add_to_playlist('p.pl1', 'i.song1'), False)
        self.assertEqual(self.app.reported, ['api'])  # reported, as before

    async def test_signed_out_is_reported_so_the_sign_in_opens(self):
        self.app.engine.fail = EngineError('not-signed-in', 'sign in first')
        await self.run_action('item-love', 'album', 'l.alb1')
        self.assertEqual(self.app.reported, ['not-signed-in'])
        self.assertEqual(self.app.toasts, [])

    async def test_demo_sends_nothing(self):
        self.app.demo = True
        await self.run_action('item-love', 'album', 'l.alb1')
        self.assertEqual(self.app.engine.calls, [])
        self.assertEqual(self.app.toasts, ['Not available with the demo library'])

    async def test_play_next_and_later(self):
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-play-next', 'song', 'i.song1')
        await self.run_action('item-play-later', 'album', 'l.alb1')
        queued = [call for call in self.app.engine.calls if call[0] != 'rating']  # the menu's
        self.assertEqual(queued, [('play_next', 'song', '1000000001'),
                                  ('play_later', 'album', 'l.alb1')])
        self.assertEqual(self.app.toasts, ['“Harbour Lights” will play next',
                                           '“Tidewater” will play later'])
        self.assertEqual(self.app.player.ensured, 0)  # the Player's commands do that

    async def test_a_music_video_plays_and_queues_as_one(self):
        self.actions.menu_for(CATALOG_VIDEO)
        self.actions.menu_for(VIDEO_TRACK)
        await self.run_action('item-play', 'video', '1000000012')
        await self.run_action('item-play-next', 'video', '1000000012')
        await self.run_action('item-play-later', 'song', 'i.vid1')
        self.assertEqual(self.window.played,
                         [({'kind': 'musicVideo', 'id': '1000000012'}, None)])
        queued = [call for call in self.app.engine.calls if call[0] != 'rating']
        self.assertEqual(queued, [('play_next', 'musicVideo', '1000000012'),
                                  ('play_later', 'musicVideo', '1000000011')])
        # A video track with no group to play from plays alone, as a video.
        alone = Track({'id': '1000000016', 'title': 'Lantern (Live)', 'type': 'music-videos'})
        self.actions.menu_for(alone)
        await self.run_action('item-play', 'song', '1000000016')
        self.assertEqual(self.window.played[-1],
                         ({'kind': 'musicVideo', 'id': '1000000016'}, None))

    async def test_play(self):
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-play', 'song', 'i.song1')
        await self.run_action('item-play', 'album', 'l.alb1')
        await self.run_action('item-play', 'station', 'ra.unknown')
        self.assertEqual(self.window.played, [
            ({'kind': 'album', 'id': 'l.alb1'}, 2), ({'kind': 'album', 'id': 'l.alb1'}, None),
            ({'kind': 'station', 'id': 'ra.unknown'}, None)])

    async def test_favourite_an_artist_from_their_menu(self):
        # Not a rating: the favourites' own write, and read as the menu opens.
        self.actions.menu_for(CATALOG_ARTIST)
        await asyncio.gather(*self.app.tasks)
        self.app.tasks.clear()
        self.assertEqual(self.app.engine.calls, [('is_favourite_artist', '1000000005')])
        self.assertEqual(self.loved_shown(), (True, False))
        await self.run_action('item-love', 'artist', '1000000005')
        self.assertEqual(self.app.engine.calls[-1], ('favourite_artist', '1000000005'))
        self.assertEqual(self.app.toasts, ['Added to Favourites'])
        self.assertEqual(self.app.player.ensured, 1)
        self.assertEqual(self.loved_shown(), (False, True))  # the engine said so
        self.assertEqual(self.actions.known_rating(('artist', '1000000005')), 1)
        await self.run_action('item-unlove', 'artist', '1000000005')
        self.assertEqual(self.app.engine.calls[-1], ('unfavourite_artist', '1000000005'))
        self.assertEqual(self.app.toasts[-1], 'Removed from Favourites')
        self.assertEqual(self.loved_shown(), (True, False))
        self.assertNotIn('love', [call[0] for call in self.app.engine.calls])

    async def test_an_artist_read_as_a_favourite_shows_in_the_menu(self):
        self.app.engine.favourite_artists.add('1000000060')
        carried = Item(dict(LIBRARY_ARTIST.raw, catalogId='1000000060'))
        self.actions.menu_for(carried)
        await asyncio.gather(*self.app.tasks)
        self.app.tasks.clear()
        self.assertEqual(self.loved_shown(), (False, True))
        # A library artist's menu names the library artist; the write takes the catalog's.
        await self.run_action('item-unlove', 'artist', 'l.art_0123456789ab')
        self.assertEqual(self.app.engine.calls[-1], ('unfavourite_artist', '1000000060'))

    async def test_an_artist_page_star_and_its_failure(self):
        # The page's star: quiet, and its task says whether the write was done.
        task = self.actions.favourite_artist(CATALOG_ARTIST, True, quiet=True)
        self.assertTrue(await task)
        self.assertEqual(self.app.toasts, [])
        self.app.engine.fail = EngineError('api', 'HTTP 403 Forbidden')
        task = self.actions.favourite_artist(CATALOG_ARTIST, False, quiet=True)
        self.assertFalse(await task)
        self.assertEqual(self.app.reported, ['api'])
        # Nothing the catalog knows: no write.
        self.assertIsNone(self.actions.favourite_artist(BAND, True))
        self.assertEqual(self.app.toasts, ['This cannot be a favourite'])
        self.assertEqual(len([call for call in self.app.engine.calls
                              if call[0].endswith('favourite_artist')]), 2)

    async def test_the_demo_favourites_an_artist_itself(self):
        # The demo engine remembers it: no "not available", no engine started.
        self.app.demo = True
        self.assertTrue(await self.actions.favourite_artist(CATALOG_ARTIST, True))
        self.assertEqual(self.app.engine.calls, [('favourite_artist', '1000000005')])
        self.assertEqual(self.app.toasts, ['Added to Favourites'])
        self.assertEqual(self.app.player.ensured, 0)
        # Anything else is still not available.
        await self.run_action('item-love', 'album', 'l.alb1')
        self.assertEqual(self.app.toasts[-1], 'Not available with the demo library')

    async def test_create_station_plays_it_at_once(self):
        # A library song by its catalog id; an artist by theirs; a target not known to the
        # actions by the catalog id it names.
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-create-station', 'song', 'i.song1')
        self.actions.menu_for(CATALOG_ARTIST)
        await self.run_action('item-create-station', 'artist', '1000000005')
        await self.run_action('item-create-station', 'song', '1000000020')
        self.assertEqual(self.window.played, [
            ({'kind': 'station', 'id': 'ra.1000000001'}, None),
            ({'kind': 'station', 'id': 'ra.1000000005'}, None),
            ({'kind': 'station', 'id': 'ra.1000000020'}, None)])
        # Nothing to seed it from: a toast, no play.
        self.actions.menu_for(UPLOAD_TRACK)
        await self.run_action('item-create-station', 'song', 'i.song2')
        await self.run_action('item-create-station', 'artist', 'l.art_00000000band')
        await self.run_action('item-create-station', 'album', '1000000002')
        self.assertEqual(len(self.window.played), 3)
        self.assertEqual(self.app.toasts, ['No station can be made from this'] * 3)

    async def test_links(self):
        # A library playlist's page opens, but is nobody else's to copy.
        await self.run_action('item-open-in-browser', 'playlist', 'p.pl1')
        self.assertEqual(self.launched, ['https://music.apple.com/library/playlist/p.pl1'])
        await self.run_action('item-copy-link', 'playlist', 'p.pl1')
        self.assertIsNone(self.window.clipboard.value)
        self.assertEqual(self.app.toasts, ['This has no link to copy'])
        # A library album: its catalog page when the engine knows it, else its library page
        # (opened, not copied).
        self.app.engine.catalog_urls['l.alb1'] = 'https://music.apple.com/gb/album/x/1000000010'
        await self.run_action('item-copy-link', 'album', 'l.alb1')
        self.assertEqual(self.window.clipboard.value,
                         'https://music.apple.com/gb/album/x/1000000010')
        self.assertEqual(self.app.toasts[-1], 'Link copied')
        await self.run_action('item-open-in-browser', 'album', 'l.alb1')
        self.app.engine.state = 'down'
        await self.run_action('item-open-in-browser', 'album', 'l.alb1')
        self.assertEqual(self.launched[1:], ['https://music.apple.com/gb/album/x/1000000010',
                                             'https://music.apple.com/library/albums/l.alb1'])
        self.actions.menu_for(UPLOAD_TRACK)
        await self.run_action('item-copy-link', 'song', 'i.song2')
        self.assertEqual(self.app.toasts[-1], 'This has no link to copy')

    async def test_a_curators_links_are_its_own_page(self):
        # A radio show's menu (#359): its page opens and copies; nothing plays or is loved.
        self.assertIsNotNone(self.actions.menu_for(SHOW))
        await self.run_action('item-open-in-browser', 'category', SHOW.id)
        await self.run_action('item-copy-link', 'category', SHOW.id)
        self.assertEqual(self.launched, [SHOW.url])
        self.assertEqual(self.window.clipboard.value, SHOW.url)
        self.assertEqual(self.app.engine.calls, [])

    async def test_a_library_artists_link_is_their_catalog_page(self):
        self.app.engine.state = 'down'  # started for the lookup
        self.app.engine.catalog_artists['Loose Ends Trio'] = '1000000051'
        self.actions.menu_for(LOOSE_ARTIST)
        await self.run_action('item-open-in-browser', 'artist', LOOSE_ARTIST.id)
        await self.run_action('item-copy-link', 'artist', LOOSE_ARTIST.id)
        self.assertEqual(self.launched, ['https://music.apple.com/gb/artist/1000000051'])
        self.assertEqual(self.window.clipboard.value,
                         'https://music.apple.com/gb/artist/1000000051')
        self.assertIn(('catalog_artist', 'Loose Ends Trio', ('1000000050',)),
                      self.app.engine.calls)
        self.assertEqual(self.app.player.ensured, 2)
        # Not found in the catalog: nothing to open; a failure is reported, not toasted twice.
        del self.app.engine.catalog_artists['Loose Ends Trio']
        await self.run_action('item-open-in-browser', 'artist', LOOSE_ARTIST.id)
        self.assertEqual(self.app.toasts[-1], 'This has no page to open')
        self.app.engine.fail = EngineError('not-signed-in', 'sign in first')
        toasts = len(self.app.toasts)
        await self.run_action('item-copy-link', 'artist', LOOSE_ARTIST.id)
        self.assertEqual(self.app.reported, ['not-signed-in'])
        self.assertEqual(len(self.app.toasts), toasts)
        self.assertEqual(len(self.launched), 1)

    async def test_a_library_artists_link_in_the_demo(self):
        self.app.demo = True
        self.actions.menu_for(LOOSE_ARTIST)
        await self.run_action('item-open-in-browser', 'artist', LOOSE_ARTIST.id)
        self.assertEqual(self.app.toasts, ['Not available with the demo library'])
        self.assertEqual(self.app.engine.calls, [])
        self.assertEqual(self.launched, [])

    async def test_a_foreign_catalog_answer_is_not_opened(self):
        self.app.engine.catalog_urls['l.alb1'] = 'http://evil.example/album'
        await self.run_action('item-open-in-browser', 'album', 'l.alb1')
        self.assertEqual(self.launched, ['https://music.apple.com/library/albums/l.alb1'])

    async def test_go_to_the_library_album_and_artist(self):
        # A track of the library's album: its group's album, then the album's artist by
        # name; neither needs the engine.
        song = Track({'id': 'i.song1', 'title': 'Harbour Lights', 'album': 'Tidewater',
                      'artist': 'The Invented Band feat. Someone', 'type': 'library-songs'},
                     play={'kind': 'playlist', 'id': 'p.pl1'})
        self.actions.menu_for(song)
        await self.run_action('item-go-to-album', 'song', 'i.song1')
        await self.run_action('item-go-to-artist', 'song', 'i.song1')
        self.assertEqual(self.window.opened, [LIBRARY_ALBUM, BAND])
        self.assertEqual([call for call in self.app.engine.calls if call[0] != 'rating'], [])
        # An album goes to its artist; the page shown is not opened again.
        await self.run_action('item-go-to-artist', 'album', 'l.alb1')
        self.window.shown = BAND
        await self.run_action('item-go-to-artist', 'album', 'l.alb1')
        self.assertEqual(self.window.opened, [LIBRARY_ALBUM, BAND, BAND])
        self.assertEqual(self.app.toasts, [])
        # The artist's is Apple Music's page of them, the library's artist's too.
        self.assertEqual(self.window.artist_pages, [BAND, BAND])

    async def test_a_link_to_an_artist_is_the_librarys_page_of_them(self):
        # A row's or an album page's link: the library's artist through open_item (the
        # library's page of them), the engine asked nothing; else as Go to Artist goes.
        song = Track({'id': 'i.song5', 'catalogId': '1000000030', 'title': 'Harbour Lights',
                      'artist': 'The Invented Band', 'type': 'library-songs'})
        self.assertIsNone(self.actions.show_artist(song))
        self.assertEqual(self.window.opened, [BAND])
        self.assertEqual(self.window.artist_pages, [])
        self.assertEqual([call for call in self.app.engine.calls if call[0] == 'related'], [])
        stranger = Track({'id': '1000000040', 'catalogId': '1000000040', 'title': 'Shoreline',
                          'artist': 'Nobody We Know'})
        self.app.engine.related_answers[('song', '1000000040')] = {
            'album': None,
            'artists': [{'id': '1000000041', 'kind': 'artist', 'title': 'Nobody We Know'}]}
        await self.actions.show_artist(stranger)
        self.assertEqual([(item.kind, item.id) for item in self.window.artist_pages],
                         [('artist', '1000000041')])

    async def test_go_to_the_catalog_album_and_artist(self):
        # The library has neither: the engine looks the catalog song up, once per kind of
        # answer, and the page opens on the answer's Item.
        song = Track({'id': '1000000009', 'catalogId': '1000000009', 'title': 'Shoreline',
                      'album': 'Coastal', 'artist': 'Mara Lind & Others'})
        self.app.engine.related_answers[('song', '1000000009')] = {
            'album': {'id': '1000000020', 'kind': 'album', 'title': 'Coastal',
                      'subtitle': 'Mara Lind', 'play': {'kind': 'album', 'id': '1000000020'}},
            'artists': [{'id': '1000000021', 'kind': 'artist', 'title': 'Someone Else'},
                        {'id': '1000000022', 'kind': 'artist', 'title': 'Mara Lind & Others'}]}
        self.actions.menu_for(song)
        await self.run_action('item-go-to-album', 'song', '1000000009')
        await self.run_action('item-go-to-artist', 'song', '1000000009')
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('album', '1000000020'), ('artist', '1000000022')])
        self.assertEqual([call for call in self.app.engine.calls if call[0] == 'related'],
                         [('related', 'song', '1000000009')] * 2)
        self.assertEqual(self.app.player.ensured, 2)
        # The catalog's album the library has is the library's.
        self.app.engine.related_answers[('song', '1000000009')]['album']['id'] = '1000000002'
        await self.run_action('item-go-to-album', 'song', '1000000009')
        self.assertIs(self.window.opened[-1], CATALOG_ALBUM)

    async def test_go_to_artist_is_apple_musics_page(self):
        # The library has the artist, but with the engine up the catalog names them exactly:
        # Apple Music's page opens (it shows the library's albums of theirs too).
        song = Track({'id': 'i.song4', 'catalogId': '1000000030', 'title': 'Harbour Lights',
                      'artist': 'The Invented Band', 'type': 'library-songs'})
        self.app.engine.related_answers[('song', '1000000030')] = {
            'album': None,
            'artists': [{'id': '1000000031', 'kind': 'artist', 'title': 'The Invented Band'}]}
        self.actions.menu_for(song)
        await self.run_action('item-go-to-artist', 'song', 'i.song4')
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('artist', '1000000031')])
        # The engine down: the library's artist, at once, nothing asked.
        self.app.engine.state = 'down'
        calls = len(self.app.engine.calls)
        await self.run_action('item-go-to-artist', 'song', 'i.song4')
        self.assertIs(self.window.opened[-1], BAND)
        self.assertEqual(len(self.app.engine.calls), calls)
        # The catalog failing, or naming no artist: the library's.
        self.app.engine.state = 'up'
        self.app.engine.related_answers[('song', '1000000030')] = {'album': None, 'artists': []}
        await self.run_action('item-go-to-artist', 'song', 'i.song4')
        self.app.engine.fail = EngineError('api', 'HTTP 500', status=500)
        await self.run_action('item-go-to-artist', 'song', 'i.song4')
        self.assertEqual(self.window.opened[-2:], [BAND, BAND])
        self.assertEqual(self.app.reported, [])
        self.assertEqual(self.app.toasts, [])

    async def test_go_to_finds_nothing(self):
        song = Track({'id': '1000000009', 'catalogId': '1000000009', 'title': 'Shoreline',
                      'album': 'Coastal'})
        self.actions.menu_for(song)
        await self.run_action('item-go-to-album', 'song', '1000000009')
        self.assertEqual(self.app.toasts, ['Could not find the album'])
        self.assertEqual(self.window.opened, [])
        # Signed out: reported, so the sign-in opens.
        self.app.engine.fail = EngineError('not-signed-in', 'sign in first')
        await self.run_action('item-go-to-artist', 'song', '1000000009')
        self.assertEqual(self.app.reported, ['not-signed-in'])
        # Gone from the storefront's catalog (Apple's 404): not found, not an error.
        self.app.engine.fail = EngineError('api', 'HTTP 404', status=404)
        await self.run_action('item-go-to-album', 'song', '1000000009')
        self.assertEqual(self.app.reported, ['not-signed-in'])
        self.assertEqual(self.app.toasts[-1], 'Could not find the album')
        # The demo asks no engine.
        self.app.engine.fail = None
        self.app.demo = True
        calls = len(self.app.engine.calls)
        await self.run_action('item-go-to-album', 'song', '1000000009')
        self.assertEqual(len(self.app.engine.calls), calls)
        self.assertEqual(self.app.toasts[-1], 'Not available with the demo library')
        # A target the actions know nothing of.
        await self.run_action('item-go-to-album', 'song', 'i.forgotten')
        self.assertEqual(self.app.toasts[-1], 'Could not find the album')

    async def test_the_menu_asks_whether_it_is_loved(self):
        self.app.engine.ratings[('song', '1000000001')] = 1
        self.actions.menu_for(LIBRARY_TRACK)
        self.assertEqual(self.loved_shown(), (True, False))  # not known loved yet
        await asyncio.gather(*self.app.tasks)
        self.assertEqual(self.loved_shown(), (False, True))  # once the engine answered
        # The next menu knows at once, and another item's shows its own state.
        self.app.engine.state = 'down'
        self.actions.menu_for(LIBRARY_TRACK)
        self.assertEqual(self.loved_shown(), (False, True))
        self.actions.menu_for(LIBRARY_ALBUM)
        self.assertEqual(self.loved_shown(), (True, False))

    async def test_a_sign_out_forgets_what_the_engine_said(self):
        # The ratings and artist favourites heard are the account's: after a sign-out
        # (the window's forget_account_pages()) a menu and the artist page's star take
        # theirs from the library and the engine only.
        self.actions.menu_for(LIBRARY_TRACK)
        await self.run_action('item-love', 'song', 'i.song1')
        self.actions.menu_for(CATALOG_ARTIST)
        await self.run_action('item-love', 'artist', '1000000005')
        self.assertEqual(self.actions.known_rating(('song', '1000000001')), 1)
        self.assertEqual(self.actions.known_rating(('artist', '1000000005')), 1)
        self.actions.forget_account()
        self.app.engine.state = 'down'
        self.app.engine.authorized = False
        self.assertIsNone(self.actions.known_rating(('song', '1000000001')))
        self.assertIsNone(self.actions.known_rating(('artist', '1000000005')))
        self.actions.menu_for(LIBRARY_TRACK)
        self.assertEqual(self.loved_shown(), (True, False))
        self.actions.menu_for(CATALOG_ARTIST)
        self.assertEqual(self.loved_shown(), (True, False))
        # Nor are the objects its menus were built for remembered.
        self.actions.forget_account()
        self.assertIsNone(self.actions._resolve('song', 'i.song1'))

    def test_the_menu_shows_the_librarys_favourite_at_once(self):
        # library.json's favourites (Library.is_favourite), before the engine has said.
        self.app.engine.state = 'down'
        self.app.library.is_favourite = lambda obj: obj is LIBRARY_ALBUM
        self.actions.menu_for(LIBRARY_ALBUM)
        self.assertEqual(self.loved_shown(), (False, True))
        self.actions.menu_for(LIBRARY_TRACK)
        self.assertEqual(self.loved_shown(), (True, False))



# A playlist of the user's holding a song twice (its tracks in hand: Track.index is the
# place), as a selection's Remove from Playlist sees it.
MIX = Item({'id': 'p.pl5', 'kind': 'playlist', 'title': 'Mix',
            'play': {'kind': 'playlist', 'id': 'p.pl5'},
            'groups': [{'name': 'Tracks', 'play': {'kind': 'playlist', 'id': 'p.pl5'},
                        'entries': [{'id': track_id, 'title': title, 'index': index,
                                     'type': 'library-songs'}
                                    for index, (track_id, title) in enumerate((
                                        ('i.m1', 'First'), ('i.m2', 'Second'),
                                        ('i.m1', 'First'), ('i.m3', 'Third')))]}]})


class SelectionActionsTest(unittest.IsolatedAsyncioTestCase):
    """A selection's batch actions (widgets/selection_mode.py's bar): Play Next and Play
    Later of runs of songs, Remove from Playlist in one write with Undo, Remove from Library
    with one confirmation. The engine's writes recorded."""

    async def asyncSetUp(self):
        self.app = FakeApp()
        self.mix = Item(dict(MIX.raw))
        self.app.library = FakeLibrary([HELD_ALBUM, LONE_ALBUM, HOLDING, self.mix,
                                        self.app.playlist])
        self.window = FakeWindow()
        self.actions = ItemActions(self.window, self.app)
        self.confirms = []
        self.asked = []
        self.actions.ask_confirm = lambda *args: self.confirms.append(args)
        self.actions.ask_name = lambda *args: self.asked.append(args)
        self.actions.ask_playlist = lambda *args: self.asked.append(args)
        for name, value in (('SETTLE_DELAYS', (0, 0, 0)), ('FOLDER_SETTLE_DELAYS', (0, 0, 0)),
                            ('REMOVAL_DELAYS', (0, 0, 0)), ('LISTING_LAG', 0)):
            self.addCleanup(setattr, playlist_actions, name, getattr(playlist_actions, name))
            setattr(playlist_actions, name, value)

    async def settle(self):
        while self.app.tasks:
            tasks = list(self.app.tasks)
            self.app.tasks.clear()
            await asyncio.gather(*tasks)

    def calls(self, *names):
        return [call for call in self.app.engine.calls if call[0] in names]

    def mix_tracks(self):
        entries = self.mix.groups[0].entries
        return [entries.get_item(position) for position in range(entries.get_n_items())]

    async def test_the_first_of_a_bigger_selection_are_queued(self):
        # A selection's Play Next takes its first PLAY_LIMIT: the toast says of how many
        # (a total under 1,000: the count's digits are grouped by the locale's rules).
        self.actions.queue_objects([LIBRARY_TRACK, CATALOG_TRACK], total=500)
        await self.settle()
        self.assertEqual(self.app.toasts[-1], 'The first 2 of 500 items will play next')
        self.actions.queue_objects([LIBRARY_TRACK, CATALOG_TRACK], later=True, total=300)
        await self.settle()
        self.assertEqual(self.app.toasts[-1], 'The first 2 of 300 items will play later')
        self.actions.queue_objects([LIBRARY_TRACK, CATALOG_TRACK], total=2)  # all of them
        await self.settle()
        self.assertEqual(self.app.toasts[-1], '2 items will play next')

    async def test_a_song_not_out_yet_left_out_is_not_a_limit(self):
        # Three selected, all taken, one a pre-release album's song not out yet, which
        # cannot be queued: two go, and the toast says so, not "the first 2 of 3".
        coming = Track({'id': '1000000012', 'catalogId': '1000000012', 'title': 'Soon',
                        'unreleased': True, 'index': 1},
                       play={'kind': 'album', 'id': '1000000002'})
        coming._release = '2099-12-04'
        self.actions.queue_objects([LIBRARY_TRACK, coming, CATALOG_TRACK], total=3)
        await self.settle()
        self.assertEqual(self.calls('play_next'),
                         [('play_next', 'songs', '1000000001,1000000009')])
        self.assertEqual(self.app.toasts[-1], '2 items will play next')
        # Over the limit, the toast still says of how many.
        self.actions.queue_objects([LIBRARY_TRACK, coming, CATALOG_TRACK], total=900)
        await self.settle()
        self.assertEqual(self.app.toasts[-1], 'The first 2 of 900 items will play next')

    async def test_tracks_of_many_songs_lets_frames_in(self):
        yielded = []

        async def yield_to_frames():
            yielded.append(True)

        tracks = [Track({'id': f'i.s{n}', 'title': f'Song {n}', 'type': 'library-songs'})
                  for n in range(50)]
        with mock.patch.object(actions_module, 'FRAME_BUDGET', -1), \
                mock.patch.object(actions_module, 'yield_to_frames', yield_to_frames):
            found = await self.actions.tracks_of(tracks)
        self.assertEqual(len(found), 50)
        self.assertEqual(len(yielded), 50)

    async def test_play_next_and_later_of_a_selection(self):
        chosen = [LIBRARY_TRACK, CATALOG_TRACK, VIDEO_TRACK, UPLOAD_TRACK]
        self.actions.queue_objects(chosen)
        await self.settle()
        # After the item playing in the order shown: the last command first.
        self.assertEqual(self.calls('play_next'), [
            ('play_next', 'song', 'i.song2'), ('play_next', 'musicVideo', '1000000011'),
            ('play_next', 'songs', '1000000001,1000000009')])
        self.assertEqual(self.app.toasts, ['4 items will play next'])
        self.actions.queue_objects(chosen[:2], later=True)
        await self.settle()
        self.assertEqual(self.calls('play_later'),
                         [('play_later', 'songs', '1000000001,1000000009')])
        self.assertEqual(self.app.toasts[-1], '2 items will play later')
        self.actions.queue_objects([CATALOG_TRACK], later=True)
        await self.settle()
        self.assertEqual(self.app.toasts[-1], '“Shoreline” will play later')

    async def test_a_list_musickit_refuses_goes_one_song_at_a_time(self):
        player = self.app.player
        queued = []

        async def play_next(kind, item_id):
            if kind == 'songs':
                raise EngineError('api', 'MusicKit: unsupported queue')
            queued.append((kind, item_id))

        player.play_next = play_next
        self.actions.queue_objects([LIBRARY_TRACK, CATALOG_TRACK, VIDEO_TRACK])
        await self.settle()
        # Still in the order shown, the video first only because Play Next goes backwards.
        self.assertEqual(queued, [('musicVideo', '1000000011'), ('song', '1000000009'),
                                  ('song', '1000000001')])
        self.assertEqual((self.app.reported, self.app.toasts), ([], ['3 items will play next']))

        async def refused(kind, item_id):
            raise EngineError('engine-down', 'Chrome is not running')

        player.play_next = refused
        self.actions.queue_objects([LIBRARY_TRACK, CATALOG_TRACK])
        await self.settle()
        self.assertEqual(self.app.reported, ['engine-down'])  # not tried song by song

    async def test_a_drop_on_the_player_bar_queues_runs_too(self):
        refs = ItemRefs.for_objects([LIBRARY_TRACK, CATALOG_TRACK])
        self.assertTrue(self.actions.queue_drop(refs))
        await self.settle()
        self.assertEqual(self.calls('play_later'),
                         [('play_later', 'songs', '1000000001,1000000009')])

    async def test_remove_from_playlist_is_one_write_with_undo(self):
        tracks = self.mix_tracks()
        self.actions.remove_entries(self.mix, [tracks[2], tracks[1]])
        await self.settle()
        shown = ('i.m1', 'i.m2', 'i.m1', 'i.m3')
        self.assertEqual(self.calls('remove_playlist_entries'),
                         [('remove_playlist_entries', 'p.pl5', shown, (1, 2))])
        self.assertEqual(self.app.toasts, ['Removed 2 songs from “Mix”'])
        self.assertEqual(self.app.buttons, [('Undo', 'win.item-undo-remove', 'p.pl5')])
        self.window.actions['item-undo-remove'].activate(GLib.Variant('s', 'p.pl5'))
        await self.settle()
        self.assertEqual(self.calls('put_back_playlist_entries'),
                         [('put_back_playlist_entries', 'p.pl5', ('i.m1', 'i.m3'), shown)])
        self.assertEqual(self.app.toasts[-1], 'Put back 2 songs in “Mix”')
        # Once: a second Undo has nothing to put back.
        self.window.actions['item-undo-remove'].activate(GLib.Variant('s', 'p.pl5'))
        await self.settle()
        self.assertEqual(len(self.calls('put_back_playlist_entries')), 1)

    async def test_one_song_removed_is_named(self):
        # Delete on a song (DetailPage.remove_focused()): the same write and Undo.
        self.actions.remove_entries(self.mix, self.mix_tracks()[3:])
        await self.settle()
        self.assertEqual(self.calls('remove_playlist_entries'), [
            ('remove_playlist_entries', 'p.pl5', ('i.m1', 'i.m2', 'i.m1', 'i.m3'), (3,))])
        self.assertEqual(self.app.toasts, ['Removed “Third” from “Mix”'])
        self.assertEqual(self.app.buttons, [('Undo', 'win.item-undo-remove', 'p.pl5')])

    def apple_takes_removals(self):
        """The engine's stand-in keeps the playlist as Apple would: a removal takes the
        entries out of what item() answers next, so the refresh after it shows them gone."""
        engine = self.app.engine
        engine.items[('playlist', 'p.pl5')] = dict(self.mix.raw)

        async def remove_playlist_entries(playlist_id, shown, positions):
            engine.calls.append(('remove_playlist_entries', playlist_id, tuple(shown),
                                 tuple(positions)))
            if engine.fail is not None:
                raise engine.fail
            answer = engine.items[('playlist', playlist_id)]
            group = answer['groups'][0]
            entries = [dict(entry, index=index) for index, entry in enumerate(
                entry for place, entry in enumerate(group['entries'])
                if place not in positions)]
            engine.items[('playlist', playlist_id)] = dict(
                answer, groups=[dict(group, entries=entries)])
            return [{'id': track_id, 'type': 'library-songs'} for track_id in shown]

        engine.remove_playlist_entries = remove_playlist_entries

    async def test_two_removals_in_quick_succession_both_go_in_order(self):
        # Delete, Down, Delete before the first has ended (#573): the second waits for the
        # playlist to show without the first, and takes its song from where it is then.
        self.apple_takes_removals()
        tracks = self.mix_tracks()
        first = self.actions.remove_entries(self.mix, [tracks[1]])
        second = self.actions.remove_entries(self.mix, [tracks[3]])
        await self.settle()
        self.assertEqual(self.calls('remove_playlist_entries'), [
            ('remove_playlist_entries', 'p.pl5', ('i.m1', 'i.m2', 'i.m1', 'i.m3'), (1,)),
            ('remove_playlist_entries', 'p.pl5', ('i.m1', 'i.m1', 'i.m3'), (2,))])
        self.assertEqual((first.result(), second.result()), (True, True))
        self.assertEqual(self.mix.track_ids(), ['i.m1', 'i.m1'])
        self.assertEqual(self.app.toasts, ['Removed “Second” from “Mix”',
                                           'Removed “Third” from “Mix”'])
        self.assertEqual(self.app.reported, [])
        self.assertEqual(self.actions._removals, {})

    async def test_a_removal_of_what_the_last_one_took_asks_nothing(self):
        self.apple_takes_removals()
        tracks = self.mix_tracks()
        self.actions.remove_entries(self.mix, [tracks[1], tracks[2]])
        again = self.actions.remove_entries(self.mix, [tracks[2]])
        after = self.actions.remove_entries(self.mix, [tracks[3]])
        await self.settle()
        self.assertEqual([call[2:] for call in self.calls('remove_playlist_entries')], [
            (('i.m1', 'i.m2', 'i.m1', 'i.m3'), (1, 2)), (('i.m1', 'i.m3'), (1,))])
        self.assertEqual((again.result(), after.result()), (False, True))

    async def test_a_removal_ends_once_the_playlist_shows_and_the_pass_follows(self):
        # The task ends when the playlist was read again, not a playlists pass later: the
        # next removal is made while that pass runs, and one more pass follows it.
        self.apple_takes_removals()
        passes = []

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            passes.append(asyncio.get_running_loop().create_future())
            return passes[-1]

        self.app.start_sync = start_sync
        task = self.actions.remove_entries(self.mix, self.mix_tracks()[:1])
        self.assertTrue(await task)
        await asyncio.sleep(0)
        self.assertEqual(len(passes), 1)
        self.assertFalse(passes[0].done())
        library = self.app.library
        self.assertEqual(library.tracks_kept, [('hold', 'p.pl5'), ('release', 'p.pl5')])
        self.assertTrue(await self.actions.remove_entries(self.mix, self.mix_tracks()[:1]))
        self.assertEqual(len(self.calls('remove_playlist_entries')), 2)
        # What that removal read is kept through the first pass's reload.
        self.assertEqual(library.tracks_kept[-1], ('hold', 'p.pl5'))
        self.assertEqual(len(passes), 1)
        passes[0].set_result(None)
        for _turn in range(3):
            await asyncio.sleep(0)
        self.assertEqual(len(passes), 2)
        self.assertEqual(library.tracks_kept[-1], ('release', 'p.pl5'))
        passes[1].set_result(None)
        await self.settle()
        self.assertEqual(len(passes), 2)

    def test_places_after(self):
        entries = [('a', 0), ('c', 2), ('e', 4)]
        self.assertEqual(places_after(entries, []), entries)
        self.assertEqual(places_after(entries, [[1]]), [('a', 0), ('c', 1), ('e', 3)])
        # Each removal's places are in the list as the one before left it.
        self.assertEqual(places_after(entries, [[1], [1]]), [('a', 0), ('e', 2)])
        self.assertEqual(places_after(entries, [[0, 3], [0]]), [('c', 0), ('e', 1)])

    async def test_remove_from_playlist_only_from_the_users_and_not_in_the_demo(self):
        self.assertIsNone(self.actions.remove_entries(READ_ONLY, self.mix_tracks()))
        self.app.demo = True
        self.assertIsNone(self.actions.remove_entries(self.mix, self.mix_tracks()))
        self.assertEqual(self.calls('remove_playlist_entries'), [])
        self.app.demo = False
        # A refusal (the playlist changed elsewhere) is reported, with no Undo.
        self.app.engine.fail = EngineError('conflict', 'changed')
        self.actions.remove_entries(self.mix, self.mix_tracks()[:1])
        await self.settle()
        self.assertEqual((self.app.reported, self.app.buttons), (['conflict'], []))

    async def test_remove_from_library_asks_once_for_them_all(self):
        chosen = [track_of(HELD_ALBUM, 0), track_of(HELD_ALBUM, 1), CATALOG_TRACK]
        self.actions.ask_remove_from_library(chosen)
        heading, body, confirm, done = self.confirms[0]
        self.assertEqual((heading, confirm), ('Remove 2 Songs from Library?', '_Remove'))
        self.assertIn('from your playlists', body)
        self.assertEqual(self.calls('remove_from_library'), [])
        done()
        await self.settle()
        # Left out at once, all of them; one write each; one toast; one sync.
        self.assertEqual(self.app.library.hidden, [('hide', {
            ('song', 'i.song3'), ('song', '1000000021'), ('song', 'i.song4'),
            ('song', '1000000022')})])
        self.assertEqual(self.calls('remove_from_library'),
                         [('remove_from_library', 'song', 'i.song3'),
                          ('remove_from_library', 'song', 'i.song4')])
        self.assertEqual(self.app.toasts, ['Removed 2 songs from your library'])
        self.assertEqual(self.app.syncs, [('quick', False, ('p.pl4',))])

    async def test_remove_from_library_looks_through_the_playlists_once(self):
        # One look for the whole selection, and before the library leaves the songs out of
        # its playlists: a look a song went through every playlist's entries each time and
        # held the main loop for seconds.
        library = self.app.library
        looks = []
        playlists_holding = library.playlists_holding

        def counted(ids):
            looks.append((set(ids), list(library.hidden)))
            return playlists_holding(ids)

        library.playlists_holding = counted
        self.actions.ask_remove_from_library([track_of(HELD_ALBUM, 0), track_of(HELD_ALBUM, 1),
                                              track_of(LONE_ALBUM, 0)])
        self.confirms[0][3]()
        await self.settle()
        self.assertEqual(looks, [({'i.song3', '1000000021', 'i.song4', '1000000022',
                                   'i.song5', '1000000023'}, [])])
        self.assertEqual(len(self.calls('remove_from_library')), 3)
        self.assertEqual(self.app.syncs, [('quick', False, ('p.pl4',))])

    async def test_remove_from_library_of_one_is_the_menus(self):
        self.actions.ask_remove_from_library([track_of(HELD_ALBUM, 0), CATALOG_TRACK])
        self.assertEqual(self.confirms[0][0], 'Remove from Library?')
        self.assertIn('“Undertow”', self.confirms[0][1])
        self.actions.ask_remove_from_library([CATALOG_TRACK])
        self.assertEqual(len(self.confirms), 1)
        self.assertEqual(self.app.toasts, ['These are not in your library'])

    async def test_a_failure_partway_brings_back_the_rest(self):
        engine = self.app.engine
        removed = []

        async def remove_from_library(kind, item_id):
            if removed:
                raise EngineError('api', 'HTTP 500')
            removed.append(item_id)
            return item_id

        engine.remove_from_library = remove_from_library
        self.actions.ask_remove_from_library([track_of(HELD_ALBUM, 0), track_of(HELD_ALBUM, 1),
                                              track_of(LONE_ALBUM, 0)])
        self.confirms[0][3]()
        await self.settle()
        self.assertEqual(removed, ['i.song3'])
        self.assertEqual(self.app.library.hidden[1], ('unhide', {
            ('song', 'i.song4'), ('song', '1000000022'), ('song', 'i.song5'),
            ('song', '1000000023')}))
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.app.toasts, ['Removed 1 song from your library'])

    async def test_new_playlist_of_a_selection(self):
        tracks = self.mix_tracks()[:2]
        self.actions.new_playlist_of(tracks)
        heading, confirm, details, folders, done = self.asked[0]
        self.assertEqual((heading, details.name), ('New Playlist', ''))
        done(details._replace(name='Picked'))
        await self.settle()
        self.assertEqual(self.calls('create_playlist'), [
            ('create_playlist', 'Picked', '', (('song', 'i.m1'), ('song', 'i.m2')), 'root')])

    def test_add_to_playlist_menu_for_a_selection(self):
        entries = [('p.pl1', 'Road Trip', None), ('p.pl5', 'Mix', None),
                   ('p.fd1', 'Evenings', [('p.pl6', 'Late', None)])]
        menu = item_menu.playlist_submenu(entries, ('playlist', 'p.pl5'),
                                               action='selection.add-to-playlist')
        self.assertEqual(actions_of(menu), [('selection.add-to-playlist', 'p.pl1'),
                                            ('selection.add-to-playlist', 'p.pl6')])
        menu = item_menu.playlist_submenu(entries, None, action='selection.add-to-playlist')
        self.assertEqual(len(actions_of(menu)), 3)



def favourite_songs(count=4):
    """An invented Favourite Songs of `count` library songs, each with a catalog id, its
    tracks in hand."""
    play = {'kind': 'playlist', 'id': 'p.fav'}
    return Item({'id': 'p.fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                 'attributes': {'isFavourites': True}, 'play': play,
                 'trackCount': count, 'durationMs': 1000 * count,
                 'groups': [{'name': 'Tracks', 'play': play,
                             'entries': [{'id': f'i.f{n}', 'catalogId': f'{1000000100 + n}',
                                          'title': f'Favourite {n}', 'index': n,
                                          'durationMs': 1000, 'type': 'library-songs'}
                                         for n in range(count)]}]})


class RemoveFromFavouritesTest(unittest.IsolatedAsyncioTestCase):
    """Favourite Songs' Remove from Favourites (a selection's): one unlove a song, the hearts
    and the rows changed at once and put back where a write fails, one toast with Undo,
    which loves them again."""

    async def asyncSetUp(self):
        self.app = FakeApp()
        self.favourites = favourite_songs()
        self.app.library = FakeLibrary([self.favourites, HELD_ALBUM])
        self.window = FakeWindow()
        self.actions = ItemActions(self.window, self.app)

    async def settle(self):
        while self.app.tasks:
            tasks = list(self.app.tasks)
            self.app.tasks.clear()
            await asyncio.gather(*tasks)

    def tracks(self):
        entries = self.favourites.groups[0].entries
        return [entries.get_item(position) for position in range(entries.get_n_items())]

    def calls(self, *names):
        return [call for call in self.app.engine.calls if call[0] in names]

    def answer_without(self, *places):
        """Apple's read of Favourite Songs once the songs at `places` have gone."""
        raw = self.favourites.raw
        entries = [dict(entry) for entry in raw['groups'][0]['entries']
                   if entry['index'] not in places]
        for position, entry in enumerate(entries):
            entry['index'] = position
        self.app.engine.items[('playlist', 'p.fav')] = dict(
            raw, groups=[dict(raw['groups'][0], entries=entries)])

    def test_what_is_written_and_where_it_shows(self):
        tracks = self.tracks()
        ids = self.favourites.track_ids()
        targets, places = item_targets.favourite_places(
            [tracks[2], tracks[0], tracks[2], CATALOG_TRACK], self.favourites, ids)
        # Each song once, by its catalog id; its place only where Favourite Songs shows it.
        self.assertEqual(targets, [('song', '1000000102'), ('song', '1000000100'),
                                   ('song', '1000000009')])
        self.assertEqual(places, {('song', '1000000102'): [2, 2], ('song', '1000000100'): [0],
                                  ('song', '1000000009'): []})
        self.assertEqual(item_targets.favourite_places(tracks[:1], None, []),
                         ([('song', '1000000100')], {('song', '1000000100'): []}))

    async def test_each_song_is_unloved_with_one_toast_and_undo(self):
        tracks = self.tracks()
        self.answer_without(1, 3)
        task = self.actions.remove_favourites([tracks[1], tracks[3]])
        # At once, before any write: the hearts go, and the rows, counts counted down.
        self.assertEqual(self.app.library.favourites_set,
                         [(False, {'1000000101', '1000000103'})])
        self.assertEqual(self.favourites.track_ids(), ['i.f0', 'i.f2'])
        self.assertEqual(self.favourites.raw['trackCount'], 2)
        self.assertEqual([track.index for track in self.tracks()], [0, 1])
        await self.settle()
        self.assertTrue(task.result())
        self.assertEqual(self.calls('unlove'), [('unlove', 'song', '1000000101'),
                                                ('unlove', 'song', '1000000103')])
        self.assertEqual(self.app.toasts, ['Removed 2 songs from Favourite Songs'])
        self.assertEqual(self.app.buttons, [('Undo', 'win.item-undo-unfavourite', '1')])
        self.assertEqual(self.calls('item'), [('item', 'playlist', 'p.fav')])  # read again
        self.assertEqual(self.favourites.track_ids(), ['i.f0', 'i.f2'])

        # Undo: the songs loved again, their hearts and rows back at once.
        del self.app.engine.items[('playlist', 'p.fav')]
        self.window.actions['item-undo-unfavourite'].activate(GLib.Variant('s', '1'))
        self.assertEqual(self.app.library.favourites_set[-1],
                         (True, {'1000000101', '1000000103'}))
        self.assertEqual(self.favourites.track_ids(), ['i.f0', 'i.f1', 'i.f2', 'i.f3'])
        self.assertEqual(self.favourites.raw['trackCount'], 4)
        await self.settle()
        self.assertEqual(self.calls('love'), [('love', 'song', '1000000101'),
                                              ('love', 'song', '1000000103')])
        self.assertEqual(self.app.toasts[-1], 'Put back 2 songs in Favourite Songs')
        # Once: a second Undo has nothing to put back.
        self.window.actions['item-undo-unfavourite'].activate(GLib.Variant('s', '1'))
        await self.settle()
        self.assertEqual(len(self.calls('love')), 2)

    async def test_a_failure_puts_back_the_songs_not_written(self):
        engine = self.app.engine
        unloved = []

        async def unlove(kind, item_id):
            if unloved:
                raise EngineError('api', 'HTTP 500')
            unloved.append(item_id)

        engine.unlove = unlove
        self.addCleanup(setattr, actions_module, 'RATING_WRITES', actions_module.RATING_WRITES)
        actions_module.RATING_WRITES = 1  # one after the other: the third is never tried
        tracks = self.tracks()
        task = self.actions.remove_favourites(tracks[:3])
        self.assertEqual(self.favourites.track_ids(), ['i.f3'])
        await self.settle()
        self.assertFalse(task.result())
        self.assertEqual(unloved, ['1000000100'])
        self.assertEqual(self.app.library.favourites_set[-1],
                         (True, {'1000000101', '1000000102'}))
        self.assertEqual(self.app.library.favourite_ids, {'1000000101', '1000000102'})
        self.assertEqual(self.favourites.track_ids(), ['i.f1', 'i.f2', 'i.f3'])
        self.assertEqual(self.app.reported, ['api'])
        self.assertEqual(self.app.toasts, ['Removed 1 song from Favourite Songs'])

    async def test_nothing_goes_when_the_engine_cannot_start(self):
        async def ensure_engine():
            raise EngineError('not-signed-in', 'not signed in')

        self.app.player.ensure_engine = ensure_engine
        task = self.actions.remove_favourites(self.tracks()[:2])
        await self.settle()
        self.assertFalse(task.result())
        self.assertEqual(self.favourites.track_ids(), ['i.f0', 'i.f1', 'i.f2', 'i.f3'])
        self.assertEqual(self.favourites.raw['trackCount'], 4)
        self.assertEqual(self.app.library.favourites_set[-1],
                         (True, {'1000000100', '1000000101'}))
        self.assertEqual((self.app.reported, self.app.toasts, self.calls('unlove')),
                         (['not-signed-in'], [], []))

    async def test_a_few_writes_at_once(self):
        running, most = [0], [0]

        async def unlove(kind, item_id):
            running[0] += 1
            most[0] = max(most[0], running[0])
            await asyncio.sleep(0)
            running[0] -= 1

        self.app.engine.unlove = unlove
        self.favourites.merge(dict(favourite_songs(10).raw))
        self.actions.remove_favourites(self.tracks())
        await self.settle()
        self.assertEqual(most[0], actions_module.RATING_WRITES)
        self.assertEqual(self.app.toasts, ['Removed 10 songs from Favourite Songs'])

    async def test_not_in_the_demo(self):
        self.app.demo = True
        self.assertIsNone(self.actions.remove_favourites(self.tracks()))
        self.assertEqual(self.favourites.track_ids(), ['i.f0', 'i.f1', 'i.f2', 'i.f3'])
        self.assertEqual(self.app.library.favourites_set, [])
        self.assertEqual(self.app.toasts, ['Not available with the demo library'])

    async def test_a_change_made_meanwhile_is_not_undone(self):
        self.app.engine.fail = EngineError('api', 'HTTP 500')
        self.actions.remove_favourites(self.tracks()[:1])
        # A sync brings another song in before the write fails: left as it is.
        self.favourites.merge(dict(favourite_songs(5).raw))
        await self.settle()
        self.assertEqual(len(self.favourites.track_ids()), 5)
        self.assertEqual(self.app.reported, ['api'])


if __name__ == '__main__':
    unittest.main()
