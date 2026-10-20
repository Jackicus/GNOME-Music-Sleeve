# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The item actions (applemusic.actions): the menus built per kind, and the win.* actions run
against a stand-in window, app and engine, so add to library, add to playlist, love and the
drop onto a sidebar playlist are checked without Apple. Gio and GObject only, no display;
the actions' coroutines run under asyncio."""

import asyncio
import unittest
from unittest import mock

from gi.repository import Gio, GLib, GObject

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.actions import (ItemActions, build_menu, can_play, describe,
                                favourite_target, is_apple_music_url,
                                is_removable_playlist, is_shareable,
                                library_target, main_menu_section, mnemonic_escaped,
                                move_targets, new_playlist_tracks, now_playing_track,
                                playlist_song, playlist_track, queue_message, queue_target,
                                queue_targets, rating_actions, rating_target, removal_target,
                                removal_words, RATING_ACTIONS,
                                share_url, station_target, web_url)
from applemusic.backend import api
from applemusic import actions as actions_module
from applemusic.backend.errors import EngineError
from applemusic.library import (Item, ItemRefs, PlaylistTree, Ref, Track, apply_changes,
                                track_ref)
from applemusic.player import NowPlaying

# Invented items, in the library's shapes.
LIBRARY_ALBUM = Item({'id': 'l.alb1', 'kind': 'album', 'title': 'Tidewater',
                      'subtitle': 'The Invented Band', 'play': {'kind': 'album', 'id': 'l.alb1'}})
MADE_UP_ALBUM = Item({'id': 'l.alb_0123456789ab', 'kind': 'album', 'title': 'Loose Ends',
                      'play': {'kind': 'album', 'id': 'l.alb_0123456789ab'}})
CATALOG_ALBUM = Item({'id': '1000000002', 'kind': 'album', 'title': 'Harbour Suite',
                      'url': 'https://music.apple.com/gb/album/harbour-suite/1000000002',
                      'play': {'kind': 'album', 'id': '1000000002'}})
LIBRARY_ARTIST = Item({'id': 'l.art_0123456789ab', 'kind': 'artist', 'title': 'The Band',
                       'play': {'kind': 'artist', 'id': 'l.art_0123456789ab'}})
CATALOG_ARTIST = Item({'id': '1000000005', 'kind': 'artist', 'title': 'Someone',
                       'play': {'kind': 'artist', 'id': '1000000005'}})
STATION = Item({'id': 'ra.1000000006', 'kind': 'station', 'title': 'Harbour Radio',
                'url': 'https://music.apple.com/gb/station/harbour-radio/ra.1000000006',
                'play': {'kind': 'station', 'id': 'ra.1000000006'}})
CATALOG_SONG = Item({'id': '1000000007', 'kind': 'song', 'title': 'Pilot Light',
                     'catalogId': '1000000007', 'play': {'kind': 'song', 'id': '1000000007'}})
CATALOG_VIDEO = Item({'id': '1000000012', 'kind': 'video', 'title': 'Pilot Light (Video)',
                      'play': {'kind': 'musicVideo', 'id': '1000000012'}})
FOLDER = Item({'id': 'l.fd1', 'kind': 'folder', 'title': 'Evenings'})
TOP_LEVEL = Item({'id': 'root', 'kind': 'folder', 'title': ''})  # the top level: All Playlists
CATEGORY = Item({'id': '1000000008', 'kind': 'category', 'title': 'Jazz'})
SHOW = Item({'id': '1000000009', 'kind': 'category', 'title': 'The Invented Hour',
             'subtitle': 'Rowan Vale',
             'url': 'https://music.apple.com/gb/curator/the-invented-hour/1000000009'})
PLAYLIST = Item({'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip',
                 'play': {'kind': 'playlist', 'id': 'p.pl1'}})
READ_ONLY = Item({'id': 'p.pl2', 'kind': 'playlist', 'title': 'Apple Picks',
                  'attributes': {'canEdit': False}, 'play': {'kind': 'playlist', 'id': 'p.pl2'}})
FAVOURITES = Item({'id': 'p.fav', 'kind': 'playlist', 'title': 'Favourite Songs',
                   'attributes': {'isFavourites': True},
                   'play': {'kind': 'playlist', 'id': 'p.fav'}})
LIBRARY_TRACK = Track({'id': 'i.song1', 'catalogId': '1000000001', 'title': 'Harbour Lights',
                       'type': 'library-songs', 'index': 2},
                      play={'kind': 'album', 'id': 'l.alb1'})
CATALOG_TRACK = Track({'id': '1000000009', 'catalogId': '1000000009', 'title': 'Shoreline',
                       'index': 0}, play={'kind': 'album', 'id': '1000000002'})
UPLOAD_TRACK = Track({'id': 'i.song2', 'title': 'Demo Take', 'index': 0},
                     play={'kind': 'playlist', 'id': 'p.pl1'})
VIDEO_TRACK = Track({'id': 'i.vid1', 'catalogId': '1000000011', 'title': 'Harbour Lights (Live)',
                     'type': 'library-music-videos', 'index': 3},
                    play={'kind': 'playlist', 'id': 'p.pl1'})

# The library's artist of LIBRARY_ALBUM, as the library makes artists up from albums.
BAND = Item({'id': 'l.art_00000000band', 'kind': 'artist', 'title': 'The Invented Band',
             'play': {}})

# A library artist of songs the library has no album for: their group holds the songs.
LOOSE_ARTIST = Item({'id': 'l.art_00000000lose', 'kind': 'artist', 'title': 'Loose Ends Trio',
                     'play': {'kind': 'artist', 'id': 'l.art_00000000lose'},
                     'groups': [{'name': 'Loose Ends',
                                 'play': {'kind': 'album', 'id': 'l.alb_0123456789ab'},
                                 'entries': [{'id': 'i.song7', 'catalogId': '1000000050',
                                              'title': 'Drift',
                                              'artist': 'Loose Ends Trio'}]}]})

# What the engine's item() answers for a playlist: the Item's shape with its groups.
PLAYLIST_ANSWER = {'id': 'p.pl1', 'kind': 'playlist', 'title': 'Road Trip', 'trackCount': 1,
                   'play': {'kind': 'playlist', 'id': 'p.pl1'},
                   'groups': [{'title': '', 'entries': [
                       {'id': 'i.song1', 'title': 'Harbour Lights', 'type': 'library-songs'}]}]}


def actions_of(menu):
    """[(action, target)] of a menu's items, sections and submenus flattened, in order."""
    found = []
    for position in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_ACTION)
        if action is not None:
            target = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_TARGET)
            found.append((action.get_string(), target.unpack() if target else None))
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(position, link)
            if linked is not None:
                found.extend(actions_of(linked))
    return found


def names(menu):
    return [action for action, _target in actions_of(menu)] if menu is not None else None


def attributes_of(menu, name):
    """{action: attribute value} for the items of a menu (sections and submenus flattened)
    that carry the attribute `name`."""
    found = {}
    for position in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_ACTION)
        value = menu.get_item_attribute_value(position, name)
        if action is not None and value is not None:
            found[action.get_string()] = value.unpack()
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(position, link)
            if linked is not None:
                found.update(attributes_of(linked, name))
    return found


def labels_of(menu):
    """The labels of a menu's items, sections and submenus flattened, in order."""
    found = []
    for position in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        if label is not None:
            found.append(label.unpack())
        for link in (Gio.MENU_LINK_SECTION, Gio.MENU_LINK_SUBMENU):
            linked = menu.get_item_link(position, link)
            if linked is not None:
                found.extend(labels_of(linked))
    return found


def submenu_of(menu, label):
    """The submenu labelled `label` among a menu's items and sections, or None."""
    for position in range(menu.get_n_items()):
        found = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        submenu = menu.get_item_link(position, Gio.MENU_LINK_SUBMENU)
        if submenu is not None and found is not None and found.unpack() == label:
            return submenu
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        inside = submenu_of(section, label) if section is not None else None
        if inside is not None:
            return inside
    return None


class MenuTest(unittest.TestCase):
    def test_library_album(self):
        self.assertEqual(names(build_menu(LIBRARY_ALBUM)), [
            'win.item-play', 'win.item-play-next', 'win.item-play-later',
            'win.item-go-to-artist', 'win.item-love', 'win.item-unlove',
            'win.item-suggest-less', 'win.item-undo-suggest-less',
            'win.item-new-playlist', 'win.item-open-in-browser', 'win.item-copy-link'])
        self.assertTrue(all(target == ('album', 'l.alb1')
                            for _action, target in actions_of(build_menu(LIBRARY_ALBUM))))

    def test_albums_and_playlists_add_their_songs_to_playlists(self):
        # Add to Playlist, as for a song: the playlists, then New Playlist…, the target the
        # album's or the playlist's own; a playlist is not offered to itself, nor a folder
        # holding only it.
        playlists = [('p.fd1', 'Evenings', [('p.pl1', 'Road Trip', None)]),
                     ('p.pl3', 'Dusk', None)]
        for obj in (LIBRARY_ALBUM, CATALOG_ALBUM, PLAYLIST, FAVOURITES):
            with self.subTest(title=obj.title):
                menu = build_menu(obj, playlists=playlists)
                added = [target for action, target in actions_of(menu)
                         if action == 'win.item-add-to-playlist']
                if obj is PLAYLIST:
                    self.assertEqual(added, [('p.pl3', 'playlist', 'p.pl1')])
                    self.assertIsNone(submenu_of(menu, 'Evenings'))
                else:
                    self.assertEqual(added, [('p.pl1', *describe(obj)), ('p.pl3', *describe(obj))])
                self.assertIn(('win.item-new-playlist', describe(obj)), actions_of(menu))
        # Nothing else takes it: a folder, a station, an artist.
        for obj in (FOLDER, STATION, CATALOG_ARTIST):
            with self.subTest(title=obj.title):
                self.assertNotIn('win.item-add-to-playlist',
                                 names(build_menu(obj, playlists=playlists)) or [])

    def test_catalog_album_can_be_added(self):
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_ALBUM)))

    def test_the_rating_items_hide_with_their_action(self):
        menu = build_menu(LIBRARY_ALBUM)
        self.assertEqual(attributes_of(menu, 'hidden-when'),
                         {'win.item-love': 'action-disabled',
                          'win.item-unlove': 'action-disabled',
                          'win.item-suggest-less': 'action-disabled',
                          'win.item-undo-suggest-less': 'action-disabled'})

    def test_the_rating_shows_favourite_or_suggest_less(self):
        def shown(value):
            return sorted(action for action, enabled in rating_actions(value).items()
                          if enabled)
        self.assertEqual(shown(0), ['item-love', 'item-suggest-less'])
        # A favourite offers no Suggest Less, as Apple's players have it.
        self.assertEqual(shown(1), ['item-unlove'])
        # Suggest Less: Favourite (which replaces it) and Undo Suggest Less.
        self.assertEqual(shown(-1), ['item-love', 'item-undo-suggest-less'])
        self.assertEqual(set(rating_actions(0)), set(RATING_ACTIONS))

    def test_labels_have_distinct_mnemonics(self):
        labels = labels_of(build_menu(LIBRARY_TRACK, playlists=[('p.pl1', 'Road Trip', None)]))
        letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label
                   and label != 'Road Trip']
        self.assertEqual(len(letters), len(set(letters)), labels)
        self.assertIn('_Play', labels)
        self.assertIn('Add to Pla_ylist', labels)

    def test_track_with_playlists(self):
        menu = build_menu(LIBRARY_TRACK, playlists=[
            ('p.fd1', 'Evenings', [('p.fd2', '', [('p.pl5', 'Late', None)]),
                                   ('p.pl2', 'Dusk', None)]),
            ('p.pl1', 'Road Trip', None), ('p.pl3', '', None), ('p.pl4', 'work_focus', None)])
        self.assertEqual(actions_of(menu), [
            ('win.item-play', ('song', 'i.song1')),
            ('win.item-play-next', ('song', 'i.song1')),
            ('win.item-play-later', ('song', 'i.song1')),
            ('win.item-create-station', ('song', 'i.song1')),
            ('win.item-go-to-album', ('song', 'i.song1')),
            ('win.item-go-to-artist', ('song', 'i.song1')),
            ('win.item-love', ('song', 'i.song1')),
            ('win.item-unlove', ('song', 'i.song1')),
            ('win.item-suggest-less', ('song', 'i.song1')),
            ('win.item-undo-suggest-less', ('song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl5', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl2', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl1', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl3', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl4', 'song', 'i.song1')),
            ('win.item-new-playlist', ('song', 'i.song1')),
            ('win.item-open-in-browser', ('song', 'i.song1')),
            ('win.item-copy-link', ('song', 'i.song1'))])
        # A playlist's name is shown as it is: its underscores are not mnemonics.
        self.assertIn('work__focus', labels_of(menu))
        # A folder is a submenu of what it holds, named by the folder, nested as it is.
        listed = submenu_of(submenu_of(menu, 'Add to Pla_ylist'), 'Evenings')
        self.assertEqual(labels_of(listed), ['Untitled Folder', 'Late', 'Dusk'])
        self.assertEqual(names(submenu_of(listed, 'Untitled Folder')),
                         ['win.item-add-to-playlist'])
        self.assertEqual(mnemonic_escaped('a_b__c'), 'a__b____c')
        # No playlists: the submenu has New Playlist… alone. A catalog track can be added to
        # the library.
        self.assertNotIn('win.item-add-to-playlist', names(build_menu(LIBRARY_TRACK)))
        self.assertIn('win.item-new-playlist', names(build_menu(LIBRARY_TRACK)))
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_TRACK)))

    def test_go_to_album_and_artist(self):
        song = Track({'id': 'i.song3', 'title': 'Undertow', 'artist': 'The Invented Band',
                      'album': 'Tidewater', 'type': 'library-songs'},
                     play={'kind': 'playlist', 'id': 'p.pl1'})
        self.assertEqual(names(build_menu(song))[3:5],
                         ['win.item-go-to-album', 'win.item-go-to-artist'])
        # A music video has an artist, but no album to go to.
        self.assertNotIn('win.item-go-to-album', names(build_menu(VIDEO_TRACK)))
        self.assertIn('win.item-go-to-artist', names(build_menu(VIDEO_TRACK)))
        # An album goes to its artist; a playlist, a station, an artist nowhere.
        self.assertNotIn('win.item-go-to-album', names(build_menu(CATALOG_ALBUM)))
        for item in (PLAYLIST, STATION, CATALOG_ARTIST):
            self.assertFalse({'win.item-go-to-album', 'win.item-go-to-artist'}
                             & set(names(build_menu(item))), item.kind)
        # A song with nothing to look up by (an upload without names) goes nowhere.
        self.assertFalse({'win.item-go-to-album', 'win.item-go-to-artist'}
                         & set(names(build_menu(UPLOAD_TRACK))))

    def test_go_to_is_left_out_where_it_is_already(self):
        # An album's own tracks on its page; an artist's songs on theirs.
        self.assertNotIn('win.item-go-to-album', names(build_menu(LIBRARY_TRACK,
                                                                  here=LIBRARY_ALBUM)))
        self.assertIn('win.item-go-to-album', names(build_menu(LIBRARY_TRACK,
                                                               here=CATALOG_ALBUM)))
        song = Track({'id': '1000000013', 'title': 'Undertow', 'artist': 'the band'})
        self.assertNotIn('win.item-go-to-artist', names(build_menu(song, here=LIBRARY_ARTIST)))
        self.assertIn('win.item-go-to-artist', names(build_menu(song, here=CATALOG_ARTIST)))

    def test_a_queued_item_has_no_play(self):
        # The item playing's menu, Up Next's: Play would replace the queue.
        menu = names(build_menu(LIBRARY_TRACK, queued=True))
        self.assertNotIn('win.item-play', menu)
        self.assertIn('win.item-play-next', menu)
        self.assertIn('win.item-go-to-album', menu)

    def test_an_up_next_entry_may_be_removed_when_its_menu_says(self):
        # Only with its queue entry (Up Next's rows after the one playing, while the queue
        # may be edited): never the item playing's menu, nor anywhere else.
        menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=(4, 'i.song1'))
        self.assertIn(('win.item-remove-from-queue', (4, 'i.song1')), actions_of(menu))
        self.assertIn('Remove from Up Ne_xt', labels_of(menu))
        letters = [label[label.index('_') + 1].lower() for label in labels_of(menu)
                   if '_' in label]
        self.assertEqual(len(letters), len(set(letters)), labels_of(menu))
        self.assertNotIn('win.item-remove-from-queue',
                         names(build_menu(LIBRARY_TRACK, queued=True)))
        self.assertNotIn('win.item-remove-from-queue', names(build_menu(LIBRARY_TRACK)))

    def test_the_item_playing_as_a_track(self):
        playing = NowPlaying({'id': 'i.song1', 'catalogId': '1000000001', 'type': 'song',
                              'title': 'Harbour Lights', 'artist': 'The Invented Band',
                              'album': 'Tidewater', 'index': 4})
        track = now_playing_track(playing)
        self.assertEqual((track.id, track.catalog_id, track.kind, track.artist, track.album),
                         ('i.song1', '1000000001', 'song', 'The Invented Band', 'Tidewater'))
        self.assertEqual(track.play, {})
        self.assertEqual(rating_target(track), ('song', '1000000001'))
        video = now_playing_track(NowPlaying({'id': '1000000012', 'type': 'musicVideo',
                                              'title': 'Pilot Light (Video)'}))
        self.assertEqual(video.kind, 'video')
        self.assertEqual(playlist_track(video), ('video', '1000000012'))
        # A station's segment, an ad, nothing: no menu.
        self.assertIsNone(now_playing_track(NowPlaying({'id': 'x', 'type': 'stations'})))
        self.assertIsNone(now_playing_track(None))

    def test_what_has_no_menu(self):
        self.assertIsNone(build_menu(CATEGORY))  # a curator without a page of Apple's
        self.assertIsNone(build_menu(object()))

    def test_a_curator_offers_its_page_alone(self):
        # A radio show (an Apple curator, #359): no Play, Play Next or Favourite, which Apple
        # gives a curator nothing for; its page to open and to copy.
        menu = build_menu(SHOW, playlists=[('p.pl1', 'Road Trip', None)], storefront='gb')
        self.assertEqual(actions_of(menu), [
            ('win.item-open-in-browser', ('category', SHOW.id)),
            ('win.item-copy-link', ('category', SHOW.id))])
        self.assertFalse(can_play(SHOW))
        self.assertIsNone(actions_module.rating_target(SHOW))
        self.assertIsNone(actions_module.queue_target(SHOW))
        # Only Apple's own pages: an address elsewhere has nothing to open.
        self.assertIsNone(build_menu(Item(dict(SHOW.raw, url='https://example.invalid/x'))))

    def test_an_artist_is_favourited_by_their_catalog_id(self):
        self.assertEqual(favourite_target(CATALOG_ARTIST), ('artist', '1000000005'))
        carried = Item(dict(LIBRARY_ARTIST.raw, catalogId='1000000060'))
        self.assertEqual(favourite_target(carried), ('artist', '1000000060'))
        # One the library made up from its songs' names, and what is not an artist: none.
        for obj in (LIBRARY_ARTIST, BAND, CATALOG_ALBUM, CATALOG_SONG, LIBRARY_TRACK):
            self.assertIsNone(favourite_target(obj))
        self.assertIsNone(rating_target(CATALOG_ARTIST))  # not a rating
        self.assertNotIn('win.item-love', names(build_menu(LIBRARY_ARTIST)))
        self.assertEqual([name for name in names(build_menu(carried)) if 'love' in name],
                         ['win.item-love', 'win.item-unlove'])

    def test_other_kinds(self):
        # An artist's favourite (their star), no Suggest Less: not a rating.
        self.assertEqual(names(build_menu(CATALOG_ARTIST)), [
            'win.item-play', 'win.item-create-station', 'win.item-love', 'win.item-unlove',
            'win.item-open-in-browser', 'win.item-copy-link'])
        self.assertEqual(names(build_menu(STATION)), [
            'win.item-play', 'win.item-love', 'win.item-unlove', 'win.item-suggest-less',
            'win.item-undo-suggest-less', 'win.item-open-in-browser', 'win.item-copy-link'])
        self.assertEqual(names(build_menu(FAVOURITES)), [
            'win.item-play', 'win.item-play-next', 'win.item-play-later',
            'win.item-new-playlist',
            'win.item-open-in-browser'])  # its library route is the owner's: no Copy Link
        self.assertEqual(names(build_menu(MADE_UP_ALBUM)), ['win.item-play',
                                                            'win.item-new-playlist'])
        self.assertNotIn('win.item-open-in-browser', names(build_menu(UPLOAD_TRACK)))

    def test_create_station_from_a_song_or_an_artist(self):
        # The station Apple seeds from a song or an artist is ra.<its catalog id>.
        library_artist = Item({'id': 'r.art1', 'kind': 'artist', 'title': 'Someone',
                               'catalogId': '1000000017', 'play': {}})
        library_song = Item({'id': 'i.song9', 'kind': 'song', 'title': 'Lantern',
                             'catalogId': '1000000018'})
        catalog_only = Track({'id': '1000000019', 'title': 'Undertow'})
        for obj, station in ((LIBRARY_TRACK, 'ra.1000000001'), (CATALOG_TRACK, 'ra.1000000009'),
                             (CATALOG_SONG, 'ra.1000000007'), (library_song, 'ra.1000000018'),
                             (catalog_only, 'ra.1000000019'),
                             (CATALOG_ARTIST, 'ra.1000000005'),
                             (library_artist, 'ra.1000000017')):
            with self.subTest(title=obj.title):
                self.assertEqual(station_target(obj), station)
                self.assertIn(('win.item-create-station', describe(obj)),
                              actions_of(build_menu(obj)))
        # None without a catalog id (an upload, an artist the library made up), nor for a
        # music video, an album, a playlist or a station.
        for obj in (UPLOAD_TRACK, LIBRARY_ARTIST, BAND, LOOSE_ARTIST, VIDEO_TRACK, CATALOG_VIDEO,
                    LIBRARY_ALBUM, CATALOG_ALBUM, PLAYLIST, STATION, FOLDER):
            with self.subTest(title=obj.title):
                self.assertIsNone(station_target(obj))
                self.assertNotIn('win.item-create-station', names(build_menu(obj)) or [])
        # It follows Play Later in the first section, and stays in the queue's menus (the
        # item playing's, Up Next's), which have no Play.
        self.assertEqual(names(build_menu(CATALOG_TRACK))[:4], [
            'win.item-play', 'win.item-play-next', 'win.item-play-later',
            'win.item-create-station'])
        self.assertEqual(names(build_menu(LIBRARY_TRACK, queued=True))[:3], [
            'win.item-play-next', 'win.item-play-later', 'win.item-create-station'])
        self.assertIn('Create Stat_ion', labels_of(build_menu(CATALOG_ARTIST)))

    def test_a_playlist_of_the_users_is_renamed_and_deleted(self):
        self.assertEqual(names(build_menu(PLAYLIST))[-2:], ['win.item-rename', 'win.item-delete'])
        self.assertIn('_Delete Playlist…', labels_of(build_menu(PLAYLIST)))
        # Apple's own (canEdit false) and Favourite Songs: never.
        for playlist in (READ_ONLY, FAVOURITES):
            self.assertFalse({'win.item-rename', 'win.item-delete'}
                             & set(names(build_menu(playlist))), playlist.title)
        # A folder of the user's: New Playlist… and New Folder… in it, then those two,
        # Delete Folder… by name.
        self.assertEqual(actions_of(build_menu(FOLDER)), [
            ('win.item-new-playlist', ('folder', 'l.fd1')),
            ('win.item-new-folder', ('folder', 'l.fd1')),
            ('win.item-rename', ('folder', 'l.fd1')), ('win.item-delete', ('folder', 'l.fd1'))])
        self.assertIn('_Delete Folder…', labels_of(build_menu(FOLDER)))

    def test_remove_from_playlist_where_the_track_is_shown(self):
        track = Track({'id': 'i.song1', 'title': 'Harbour Lights', 'type': 'library-songs',
                       'index': 4}, play={'kind': 'playlist', 'id': 'p.pl1'})
        menu = build_menu(track, container=PLAYLIST)
        # Its own entry, by index: the same song twice is two entries.
        self.assertIn(('win.item-remove-from-playlist', ('p.pl1', 'i.song1', 4)),
                      actions_of(menu))
        # Not in a playlist that is not the user's, nor anywhere else.
        for container in (READ_ONLY, FAVOURITES, LIBRARY_ALBUM, None):
            self.assertNotIn('win.item-remove-from-playlist',
                             names(build_menu(track, container=container)))
        # Every label of the fullest menus has a mnemonic of its own.
        for labels in (labels_of(menu), labels_of(build_menu(PLAYLIST)),
                       labels_of(build_menu(FOLDER))):
            letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label]
            self.assertEqual(len(letters), len(set(letters)), labels)

    def test_copy_link_only_for_a_shareable_page(self):
        # A library playlist's page opens for its owner only: Open in Browser, no Copy Link.
        self.assertIn('win.item-open-in-browser', names(build_menu(PLAYLIST)))
        self.assertNotIn('win.item-copy-link', names(build_menu(PLAYLIST)))
        # A catalog album has both; a library album too (its catalog page, from the engine).
        self.assertIn('win.item-copy-link', names(build_menu(CATALOG_ALBUM)))
        self.assertIn('win.item-copy-link', names(build_menu(LIBRARY_ALBUM)))

    def test_a_library_artist_offers_their_apple_music_page(self):
        # Nothing to play (the library made them up), but Apple Music's page of them, which
        # the engine finds when it is asked for.
        self.assertEqual(actions_of(build_menu(LIBRARY_ARTIST)), [
            ('win.item-open-in-browser', ('artist', 'l.art_0123456789ab')),
            ('win.item-copy-link', ('artist', 'l.art_0123456789ab'))])

    def test_folders_and_all_playlists(self):
        # A sidebar row's menu is its Item's, as its page's More Options shows it (a
        # playlist's: the menu this class checks throughout).
        self.assertEqual(actions_of(build_menu(FOLDER)), [
            ('win.item-new-playlist', ('folder', 'l.fd1')),
            ('win.item-new-folder', ('folder', 'l.fd1')),
            ('win.item-rename', ('folder', 'l.fd1')),
            ('win.item-delete', ('folder', 'l.fd1'))])
        self.assertIn('_Delete Folder…', labels_of(build_menu(FOLDER)))
        self.assertIn('New _Folder…', labels_of(build_menu(FOLDER)))
        # All Playlists (the top level's folder Item): new ones there, nothing to rename.
        self.assertEqual(actions_of(build_menu(TOP_LEVEL)), [
            ('win.item-new-playlist', ('folder', 'root')),
            ('win.item-new-folder', ('folder', 'root'))])
        # With where it can be moved: Move to Folder, before Rename… and Delete Folder….
        moves = (True, [('l.fd2', 'Mornings', True, [])])
        self.assertEqual(names(build_menu(FOLDER, moves=moves))[2:],
                         ['win.item-move-to-folder', 'win.item-move-to-folder',
                          'win.item-move-to-folder', 'win.item-rename', 'win.item-delete'])

    def test_a_playlists_menu_has_the_pages_items(self):
        # The sidebar's too: Play Later, Favourite (the rating items, each shown by its
        # state), Add to Playlist, Move to Folder and the rest, in the page's order.
        menu = build_menu(PLAYLIST, playlists=[('p.pl9', 'Evening Mix', None)],
                          moves=(False, [('l.fd1', 'Evenings', True, [])]))
        self.assertEqual(names(menu), [
            'win.item-play', 'win.item-play-next', 'win.item-play-later',
            *(f'win.{name}' for name in RATING_ACTIONS), 'win.item-add-to-playlist',
            'win.item-new-playlist',
            'win.item-move-to-folder', 'win.item-move-to-folder',
            'win.item-open-in-browser', 'win.item-rename', 'win.item-delete'])
        self.assertIsNotNone(submenu_of(menu, 'Add to Pla_ylist'))
        self.assertIsNotNone(submenu_of(menu, 'Mov_e to Folder'))
        # Apple's own and Favourite Songs: played, never renamed or deleted.
        for playlist in (READ_ONLY, FAVOURITES):
            self.assertFalse({'win.item-rename', 'win.item-delete'}
                             & set(names(build_menu(playlist))))

    def test_move_targets_and_their_submenu(self):
        playlists = [Item(dict(item.raw)) for item in (PLAYLIST, READ_ONLY, FAVOURITES)]
        tree = PlaylistTree([
            {'id': 'root', 'title': '', 'parent': None,
             'children': [{'kind': 'folder', 'id': 'p.fd1'}, {'kind': 'folder', 'id': 'p.fd2'},
                          {'kind': 'playlist', 'id': 'p.pl2'},
                          {'kind': 'playlist', 'id': 'p.fav'}]},
            {'id': 'p.fd1', 'title': 'Evenings', 'parent': 'root',
             'children': [{'kind': 'playlist', 'id': 'p.pl1'}, {'kind': 'folder', 'id': 'p.fd3'}]},
            {'id': 'p.fd3', 'title': 'Late_Night', 'parent': 'p.fd1', 'children': []},
            {'id': 'p.fd2', 'title': 'Mornings', 'parent': 'root', 'children': []}], playlists)
        playlist, evenings = playlists[0], tree.folder('p.fd1').item
        # Its own folder is no target, but holds one; the top level is not offered while
        # Apple is not known to take it (api.MOVE_TO_TOP_LEVEL).
        moves = move_targets(tree, playlist)
        self.assertEqual(moves, (False, [('p.fd1', 'Evenings', False,
                                          [('p.fd3', 'Late_Night', True, [])]),
                                         ('p.fd2', 'Mornings', True, [])]))
        menu = build_menu(playlist, moves=moves)
        submenu = submenu_of(menu, 'Mov_e to Folder')
        self.assertEqual(actions_of(submenu), [
            ('win.item-move-to-folder', ('p.fd3', 'playlist', 'p.pl1')),
            ('win.item-move-to-folder', ('p.fd2', 'playlist', 'p.pl1')),
            ('win.item-move-to-folder', ('', 'playlist', 'p.pl1'))])  # New Folder…
        self.assertEqual(labels_of(submenu), ['Evenings', 'Late__Night', 'Mornings',
                                              'New _Folder…'])
        # Every level has mnemonics of its own (a popover shows one level at a time).
        for level in (set(labels_of(menu)) - set(labels_of(submenu)), labels_of(submenu)):
            letters = [label[label.index('_') + 1].lower() for label in level
                       if '_' in label and label != 'Late__Night']
            self.assertEqual(len(letters), len(set(letters)), level)
        # Apple's own playlist at the top level: every folder; Favourite Songs: never.
        self.assertEqual(move_targets(tree, playlists[1])[1][1][:3], ('p.fd2', 'Mornings', True))
        self.assertIsNone(move_targets(tree, playlists[2]))
        self.assertIsNone(move_targets(tree, LIBRARY_ALBUM))
        self.assertIsNone(move_targets(tree, tree.root.item))
        self.assertIsNone(move_targets(tree, evenings))  # folders wait for api.MOVE_FOLDERS
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', True), \
                mock.patch.object(api, 'MOVE_FOLDERS', True):
            top, entries = move_targets(tree, playlist)
            self.assertTrue(top)
            moved = submenu_of(build_menu(playlist, moves=(top, entries)), 'Mov_e to Folder')
            self.assertEqual(actions_of(moved)[0],
                             ('win.item-move-to-folder', ('root', 'playlist', 'p.pl1')))
            self.assertEqual(labels_of(moved)[0], 'Top Level')
            # A folder: not into itself or what is inside it, nor the top level it is at.
            self.assertEqual(move_targets(tree, evenings),
                             (False, [('p.fd2', 'Mornings', True, [])]))
            self.assertEqual(move_targets(tree, tree.folder('p.fd3').item)[0], True)

    def test_main_menu_starts_with_new_playlist_and_folder(self):
        # New Playlist… is the window's win.new-playlist, whose key (Ctrl+N) the menu shows.
        self.assertEqual(actions_of(main_menu_section()), [
            ('win.new-playlist', None), ('win.item-new-folder', ('folder', 'root'))])

    def test_targets(self):
        self.assertEqual(queue_target(LIBRARY_TRACK), ('song', '1000000001'))
        self.assertEqual(queue_target(LIBRARY_ALBUM), ('album', 'l.alb1'))
        self.assertIsNone(queue_target(STATION))
        self.assertEqual(rating_target(LIBRARY_TRACK), ('song', '1000000001'))
        self.assertEqual(rating_target(UPLOAD_TRACK), ('song', 'i.song2'))
        self.assertIsNone(rating_target(FAVOURITES))
        self.assertIsNone(rating_target(CATALOG_ARTIST))
        self.assertIsNone(library_target(LIBRARY_TRACK))
        self.assertEqual(library_target(CATALOG_SONG), ('song', '1000000007'))
        self.assertEqual(playlist_song(LIBRARY_TRACK), 'i.song1')
        self.assertEqual(playlist_song(CATALOG_SONG), '1000000007')
        self.assertIsNone(playlist_song(LIBRARY_ALBUM))

    def test_a_music_video_is_a_video(self):
        # A track that is a music video (Track.kind) is rated and added as one.
        self.assertEqual(rating_target(VIDEO_TRACK), ('video', '1000000011'))
        self.assertEqual(playlist_track(VIDEO_TRACK), ('video', 'i.vid1'))
        self.assertEqual(playlist_track(LIBRARY_TRACK), ('song', 'i.song1'))
        self.assertEqual(playlist_track(CATALOG_VIDEO), ('video', '1000000012'))
        self.assertEqual(rating_target(CATALOG_VIDEO), ('video', '1000000012'))
        self.assertEqual(web_url(VIDEO_TRACK, 'gb'),
                         'https://music.apple.com/gb/music-video/1000000011')

    def test_a_music_video_is_played_and_queued_as_one(self):
        # Its menu offers Play, Play Next and Play Later as a song's does, queued as
        # MusicKit's musicVideo (by the catalog id when it has one), never as a song.
        library_video = Item({'id': 'i.mv0001', 'kind': 'video', 'title': 'Lantern (Video)',
                              'catalogId': '1000000014',
                              'play': {'kind': 'musicVideo', 'id': 'i.mv0001'}})
        for obj in (CATALOG_VIDEO, library_video, VIDEO_TRACK):
            with self.subTest(title=obj.title):
                self.assertTrue(can_play(obj))
                self.assertEqual(names(build_menu(obj))[:3], [
                    'win.item-play', 'win.item-play-next', 'win.item-play-later'])
        self.assertEqual(queue_target(CATALOG_VIDEO), ('musicVideo', '1000000012'))
        self.assertEqual(queue_target(library_video), ('musicVideo', '1000000014'))
        self.assertEqual(queue_target(VIDEO_TRACK), ('musicVideo', '1000000011'))
        self.assertEqual(queue_target(LIBRARY_TRACK), ('song', '1000000001'))
        self.assertFalse(can_play(Item({'id': '1000000015', 'kind': 'video', 'play': {}})))

    def test_web_urls(self):
        self.assertEqual(web_url(CATALOG_ALBUM), CATALOG_ALBUM.url)
        self.assertEqual(web_url(PLAYLIST), 'https://music.apple.com/library/playlist/p.pl1')
        self.assertEqual(web_url(LIBRARY_ALBUM), 'https://music.apple.com/library/albums/l.alb1')
        self.assertEqual(web_url(LIBRARY_TRACK, 'gb'), 'https://music.apple.com/gb/song/1000000001')
        self.assertEqual(web_url(CATALOG_ARTIST, 'gb'),
                         'https://music.apple.com/gb/artist/1000000005')
        for obj in (UPLOAD_TRACK, LIBRARY_ARTIST, MADE_UP_ALBUM, FOLDER, None):
            self.assertIsNone(web_url(obj))

    def test_a_foreign_url_never_comes_back(self):
        for url in ('file:///etc/hostname', 'http://evil.example/', 'https://evil.example/x',
                    'javascript:alert(1)', 'https://music.apple.com.evil.example/'):
            with self.subTest(url=url):
                self.assertFalse(is_apple_music_url(url))
                item = Item({'id': '1000000002', 'kind': 'album', 'title': 'X', 'url': url})
                self.assertEqual(web_url(item, 'gb'),
                                 'https://music.apple.com/gb/album/1000000002')
        self.assertTrue(is_apple_music_url(CATALOG_ALBUM.url))
        self.assertTrue(is_apple_music_url('https://geo.music.apple.com/us/album/x/1'))

    def test_shareable_addresses(self):
        self.assertEqual(share_url(CATALOG_ALBUM), CATALOG_ALBUM.url)
        self.assertEqual(share_url(LIBRARY_TRACK, 'gb'),
                         'https://music.apple.com/gb/song/1000000001')
        self.assertIsNone(share_url(PLAYLIST))  # the owner's route
        self.assertIsNone(share_url(LIBRARY_ALBUM))  # its catalog page needs the engine
        self.assertFalse(is_shareable(None))
        self.assertFalse(is_shareable('https://music.apple.com/library/albums/l.alb1'))
        self.assertTrue(is_shareable('https://music.apple.com/gb/album/x/1000000010'))

    def test_track_ref(self):
        self.assertEqual(track_ref(LIBRARY_TRACK), Ref('song', 'i.song1', 'Harbour Lights', 2))
        self.assertEqual(track_ref(CATALOG_SONG).id, '1000000007')
        self.assertEqual(track_ref(VIDEO_TRACK).kind, 'video')
        self.assertEqual(track_ref(CATALOG_VIDEO).kind, 'video')
        self.assertIsNone(track_ref(LIBRARY_ALBUM))


class FakeEngine(GObject.Object):
    """The Engine's surface the actions use: state, authorized, the `rated` signal, and the
    writes, recorded (nothing is sent anywhere)."""

    __gsignals__ = {
        'rated': (GObject.SignalFlags.RUN_FIRST, None, (str, str, int)),
    }

    state = GObject.Property(type=str, default='up')
    authorized = GObject.Property(type=bool, default=True)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail = None
        self.ratings = {}
        self.favourite_artists = set()  # the catalog artists is_favourite_artist() says are
        self.catalog_urls = {}
        self.catalog_artists = {}  # a library artist's name -> catalog_artist()'s answer
        self.items = {}  # (kind, id) -> the Item dict item() answers
        self.related_answers = {}  # (kind, id) -> related()'s answer
        self.listings = []  # folder_children()'s answers, one per call; then none
        self.moving = None  # an asyncio.Event move_to_folder() waits for, when set
        self.adding = None  # an asyncio.Event add_tracks_to_playlist() waits for, when set
        self.still_listed = []  # in_library()'s answers, one per call; then False

    async def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail is not None:
            raise self.fail

    async def love(self, kind, item_id):
        await self._record('love', kind, item_id)
        self.emit('rated', kind, item_id, 1)

    async def unlove(self, kind, item_id):
        await self._record('unlove', kind, item_id)
        self.emit('rated', kind, item_id, 0)

    async def suggest_less(self, kind, item_id):
        await self._record('suggest_less', kind, item_id)
        self.emit('rated', kind, item_id, -1)

    async def favourite_artist(self, artist_id):
        await self._record('favourite_artist', artist_id)
        self.emit('rated', 'artist', artist_id, 1)

    async def unfavourite_artist(self, artist_id):
        await self._record('unfavourite_artist', artist_id)
        self.emit('rated', 'artist', artist_id, 0)

    async def is_favourite_artist(self, artist_id):
        await self._record('is_favourite_artist', artist_id)
        favourite = artist_id in self.favourite_artists
        self.emit('rated', 'artist', artist_id, 1 if favourite else 0)
        return favourite

    async def rating(self, kind, item_id):
        await self._record('rating', kind, item_id)
        value = self.ratings.get((kind, item_id), 0)
        self.emit('rated', kind, item_id, value)
        return value

    async def add_to_library(self, kind, item_id):
        await self._record('add_to_library', kind, item_id)

    async def add_to_playlist(self, playlist_id, song_id, kind='song'):
        await self._record('add_to_playlist', playlist_id, song_id, kind)

    async def add_tracks_to_playlist(self, playlist_id, tracks):
        if self.adding is not None:
            await self.adding.wait()
        await self._record('add_tracks_to_playlist', playlist_id, tuple(tracks))
        return len(tracks)

    async def catalog_artist(self, name, song_ids):
        await self._record('catalog_artist', name, tuple(song_ids))
        return self.catalog_artists.get(name)

    async def catalog_url(self, kind, item_id):
        await self._record('catalog_url', kind, item_id)
        return self.catalog_urls.get(item_id)

    async def create_folder(self, name, folder_id=None):
        await self._record('create_folder', name, folder_id)
        return 'p.fdnew'

    async def move_to_folder(self, kind, item_id, folder_id=None):
        if self.moving is not None:
            await self.moving.wait()
        await self._record('move_to_folder', kind, item_id, folder_id)

    async def related(self, kind, item_id):
        await self._record('related', kind, item_id)
        return self.related_answers.get((kind, item_id), {'album': None, 'artists': []})

    async def create_playlist(self, name, description='', tracks=(), folder_id=None):
        await self._record('create_playlist', name, description, tuple(tracks), folder_id)
        return 'p.new'

    async def edit_playlist(self, playlist_id, name=None, description=None):
        await self._record('edit_playlist', playlist_id, name, description)

    async def delete_playlist(self, playlist_id):
        await self._record('delete_playlist', playlist_id)

    async def remove_from_library(self, kind, item_id):
        await self._record('remove_from_library', kind, item_id)
        return item_id

    async def in_library(self, kind, library_id):
        self.calls.append(('in_library', kind, library_id))
        return bool(self.still_listed and self.still_listed.pop(0))

    async def remove_from_playlist(self, playlist_id, track_id, index=None):
        await self._record('remove_from_playlist', playlist_id, track_id, index)
        return True

    async def reorder_playlist(self, playlist_id, shown, order):
        await self._record('reorder_playlist', playlist_id, tuple(shown), tuple(order))

    async def playlist_track_ids(self, playlist_id):
        self.calls.append(('playlist_track_ids', playlist_id))
        return []

    async def rename_folder(self, folder_id, name):
        await self._record('rename_folder', folder_id, name)

    async def delete_folder(self, folder_id):
        await self._record('delete_folder', folder_id)

    async def folder_children(self, folder_id=None):
        self.calls.append(('folder_children', folder_id))
        if self.listings:
            listing = self.listings.pop(0)
            if isinstance(listing, Exception):
                raise listing
            return listing
        return []

    async def item(self, kind, item_id):
        await self._record('item', kind, item_id)
        answer = self.items.get((kind, item_id))
        if answer is None:
            raise EngineError('api', f'item not found: {kind} {item_id}')
        return answer


class FakePlayer:
    def __init__(self, engine):
        self.engine = engine
        self.ensured = 0

    async def ensure_engine(self):
        self.ensured += 1

    async def play_next(self, kind, item_id):
        await self.engine._record('play_next', kind, item_id)

    async def play_later(self, kind, item_id):
        await self.engine._record('play_later', kind, item_id)

    async def remove_from_queue(self, index, entry_id):
        await self.engine._record('remove_from_queue', index, entry_id)
        return entry_id != 'i.gone'


class FakeLibrary:
    storefront = 'gb'

    def __init__(self, items, folders=()):
        self.items = {(item.kind, item.id): item for item in items}
        self.playlists = [item for item in items if item.kind == 'playlist']
        self.albums = [item for item in items if item.kind == 'album']
        self.artists = [item for item in items if item.kind == 'artist']
        self.folders = list(folders)
        self.changes = []  # hold()'s TreeChanges, as Library keeps them
        self.tree = PlaylistTree(folders, self.playlists)
        for node in self.tree.folders():
            self.items[('folder', node.id)] = node.item
        self.placed = 0
        self.released = []
        self.hidden = []  # ('hide' or 'unhide', the refs), in order
        self.held = {}  # playlist id -> its order held (reorder())
        self.noted = []  # note_added()'s Items

    def note_added(self, item):
        self.noted.append(item)

    def hold(self, change):
        self.changes.append(change)
        self._replant()
        return True

    def release(self, change):
        self.released.append(change)
        if change in self.changes:
            self.changes.remove(change)
            self._replant()

    def _replant(self):
        existing = {key: item for key, item in self.items.items() if key[0] == 'folder'}
        self.tree = PlaylistTree(apply_changes(self.folders, self.changes), self.playlists,
                                 existing)
        for node in self.tree.folders():
            self.items[('folder', node.id)] = node.item

    def by_id(self, kind, item_id):
        return self.items.get((kind, item_id))

    def library_id(self, kind, item_id, catalog_id=None):
        """As Library.library_id: a song by the albums' tracks' ids and catalog ids."""
        if kind == 'song':
            for album in self.albums:
                for group in album.raw.get('groups') or []:
                    for entry in group.get('entries') or []:
                        if item_id in (entry.get('id'), entry.get('catalogId')) or (
                                catalog_id and catalog_id == entry.get('catalogId')):
                            return entry.get('id')
            return None
        item = self.items.get((kind, item_id))
        return item.id if item is not None else None

    def playlists_holding(self, ids):
        return [playlist.id for playlist in self.playlists
                if any(entry.get('id') in ids or entry.get('catalogId') in ids
                       for group in playlist.raw.get('groups') or []
                       for entry in group.get('entries') or [])]

    def hide(self, refs):
        self.hidden.append(('hide', set(refs)))
        return asyncio.sleep(0)  # Library.hide's reload

    def unhide(self, refs):
        self.hidden.append(('unhide', set(refs)))
        return asyncio.sleep(0)

    def playlist_tree(self):
        return self.tree

    def place_playlists(self):
        self.placed += 1

    def favourite_songs(self):
        return next((item for item in self.playlists if item.favourites), None)

    def reorder(self, item, order):
        # Library.reorder()'s, the order held as it holds it.
        if not item.reorder(order):
            return False
        self.held[item.id] = item.track_ids()
        return True

    def release_order(self, playlist_id):
        self.held.pop(playlist_id, None)

    def with_held_order(self, raw):
        return raw


class FakeApp:
    def account_key(self, name):
        return name  # the release build's keys

    def __init__(self):
        self.engine = FakeEngine()
        self.player = FakePlayer(self.engine)
        # The playlists are this test's own: an add merges the engine's answer into them.
        self.playlist = Item(dict(PLAYLIST.raw))
        self.favourites = Item(dict(FAVOURITES.raw))
        self.library = FakeLibrary([LIBRARY_ALBUM, CATALOG_ALBUM, self.playlist, READ_ONLY,
                                    self.favourites, BAND])
        self.demo = False
        self.tasks = []
        self.reported = []
        self.toasts = []
        self.buttons = []  # (label, action, target) of the toasts' buttons
        self.syncs = []  # (quick,) per start_sync, ('tracks', ids) for a tracks pass
        self.library_sync = None

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task

    def report(self, error):
        self.reported.append(error.code)

    def toast(self, title, button_label=None, action_name=None, action_target=None):
        self.toasts.append(title)
        if button_label:
            self.buttons.append((button_label, action_name,
                                 action_target.unpack() if action_target else None))

    def start_sync(self, quick=False, playlists=False, videos=False, tracks_of=()):
        if playlists and tracks_of:
            self.syncs.append(('tracks', tuple(tracks_of)))
        elif videos or tracks_of:
            self.syncs.append(('quick', videos, tuple(tracks_of)))
        else:
            self.syncs.append('playlists' if playlists else quick)
        return None

    def refuse_in_demo(self):
        if self.demo:
            self.toast('Not available with the demo library')
        return self.demo


class FakeClipboard:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class FakeWindow:
    def __init__(self):
        self.actions = {}
        self.played = []
        self.opened = []
        self.artist_pages = []  # the artists in `opened` that open_artist_page() opened
        self.shown = None  # the Item of the page shown
        self.clipboard = FakeClipboard()
        self.left = []  # leave()'s (gone, parent)
        self.selected = []  # select_page()'s keys
        self.announced = []  # what assistive technology was told

    def leave(self, gone, parent=None):
        self.left.append((gone, parent))

    def announce(self, message, _priority):
        self.announced.append(message)

    def select_page(self, key):
        self.selected.append(key)

    def open_item(self, item):
        self.opened.append(item)

    def open_artist_page(self, item):
        # Apple Music's page of an artist: in `opened` too, in the order pages opened.
        self.opened.append(item)
        self.artist_pages.append(item)

    def shown_item(self):
        return self.shown

    def add_action(self, action):
        self.actions[action.get_name()] = action

    def play_request(self, play, start_with=None, shuffle=None, start_id=None):
        self.played.append((play, start_with))

    def get_clipboard(self):
        return self.clipboard


class DropTargetsTest(unittest.TestCase):
    """What the player bar queues and All Playlists makes a playlist of, from a drag's
    ItemRefs."""

    def test_queue_targets(self):
        self.assertEqual(queue_targets(ItemRefs.for_objects([LIBRARY_TRACK, VIDEO_TRACK,
                                                             PLAYLIST, CATALOG_ALBUM])),
                         [('song', '1000000001'), ('musicVideo', '1000000011'),
                          ('playlist', 'p.pl1'), ('album', '1000000002')])
        self.assertEqual(queue_targets(ItemRefs.for_objects([UPLOAD_TRACK])),
                         [('song', 'i.song2')])  # no catalog id: its own
        self.assertIsNone(queue_targets(ItemRefs.for_objects([PLAYLIST, FOLDER])))
        self.assertIsNone(queue_targets(ItemRefs.for_objects([MADE_UP_ALBUM])))
        self.assertIsNone(queue_targets(ItemRefs([Ref('song', 'i.song1', 'Song')])))  # no objects
        self.assertIsNone(queue_targets(None))

    def test_queue_message(self):
        self.assertEqual(queue_message('Shoreline', True), '“Shoreline” will play later')
        self.assertEqual(queue_message('Shoreline', False), '“Shoreline” will play next')
        self.assertEqual(queue_message('', True), 'Playing later')
        self.assertEqual(queue_message('Shoreline', True, 2), '2 items will play later')
        self.assertEqual(queue_message('Shoreline', False, 4), '4 items will play next')

    def test_new_playlist_tracks(self):
        self.assertEqual(new_playlist_tracks(ItemRefs.for_objects([LIBRARY_TRACK, CATALOG_SONG,
                                                                   VIDEO_TRACK])),
                         [('song', 'i.song1'), ('song', '1000000007'), ('video', 'i.vid1')])
        self.assertIsNone(new_playlist_tracks(ItemRefs.for_objects([PLAYLIST])))
        self.assertIsNone(new_playlist_tracks(ItemRefs.for_objects([LIBRARY_TRACK, PLAYLIST])))
        self.assertIsNone(new_playlist_tracks(None))


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
            'item-move-in-playlist', 'item-undo-reorder']))
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

    async def test_remove_from_up_next(self):
        await self.run_action('item-remove-from-queue', 4, 'i.song1')
        self.assertIn(('remove_from_queue', 4, 'i.song1'), self.app.engine.calls)
        self.assertEqual(self.window.announced, ['Removed from Up Next'])
        self.assertEqual(self.app.toasts, [])  # the row goes: no toast
        await self.run_action('item-remove-from-queue', 5, 'i.gone')
        self.assertEqual(self.window.announced, ['Removed from Up Next'])  # nothing taken

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
        self.actions.ask_name = lambda *args: asked.append(args)
        album = Item({'id': 'l.alb9', 'kind': 'album', 'title': 'Tidewater', 'groups': [
            {'entries': [{'id': 'i.s1', 'title': 'One'}, {'id': 'i.s2', 'title': 'Two'}]}]})
        self.actions.menu_for(album)
        self.actions.actions['item-new-playlist'].activate(GLib.Variant('(ss)',
                                                                        ('album', 'l.alb9')))
        _heading, _confirm, name, _description, done = asked[0]
        self.assertEqual(name, 'Tidewater')
        await done('Tidewater', '')
        self.assertIn(('create_playlist', 'Tidewater', '', (('song', 'i.s1'), ('song', 'i.s2')),
                       None), self.app.engine.calls)
        self.assertEqual(self.app.toasts[0], 'Added 2 songs to the new playlist “Tidewater”')

    def test_container_tracks_and_the_messages(self):
        self.assertIsNone(actions_module.container_tracks(CATALOG_ALBUM))  # read them first
        self.assertEqual(actions_module.container_tracks(LOOSE_ARTIST),
                         [('song', 'i.song7')])
        self.assertEqual(actions_module.added_message(1, 'Road Trip'),
                         'Added 1 song to “Road Trip”')
        self.assertEqual(actions_module.added_message(12, ''), 'Added 12 songs to the playlist')
        self.assertTrue(actions_module.adds_songs(CATALOG_ALBUM))
        self.assertTrue(actions_module.adds_songs(PLAYLIST))
        self.assertFalse(actions_module.adds_songs(FOLDER))
        self.assertFalse(actions_module.adds_songs(CATALOG_SONG))
        self.assertTrue(actions_module.new_playlist_refs(ItemRefs.for_objects([LIBRARY_ALBUM])))
        self.assertFalse(actions_module.new_playlist_refs(ItemRefs.for_objects([PLAYLIST])))

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

    def test_the_menu_shows_the_librarys_favourite_at_once(self):
        # library.json's favourites (Library.is_favourite), before the engine has said.
        self.app.engine.state = 'down'
        self.app.library.is_favourite = lambda obj: obj is LIBRARY_ALBUM
        self.actions.menu_for(LIBRARY_ALBUM)
        self.assertEqual(self.loved_shown(), (False, True))
        self.actions.menu_for(LIBRARY_TRACK)
        self.assertEqual(self.loved_shown(), (True, False))


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
        self.actions.ask_name = lambda *args: self.asked.append(args)
        self.actions.ask_confirm = lambda *args: self.confirms.append(args)
        delays = actions_module.SETTLE_DELAYS
        actions_module.SETTLE_DELAYS = (0, 0, 0)
        self.addCleanup(setattr, actions_module, 'SETTLE_DELAYS', delays)
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
        first, second, last = self.songs('i.a', 'i.b', 'i.c')
        moves = [entry for entry in actions_of(self.actions.menu_for(second))
                 if entry[0] == 'win.item-move-in-playlist']
        self.assertEqual(moves, [('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, -1)),
                                 ('win.item-move-in-playlist', ('p.pl1', 'i.b', 1, 1))])
        labels = labels_of(self.actions.menu_for(second))
        self.assertLess(labels.index('_Move Up'), labels.index('Remo_ve from Playlist'))
        letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label]
        self.assertEqual(len(letters), len(set(letters)), labels)
        # Not up from the first, nor down from the last.
        self.assertEqual([entry[1][3] for entry in actions_of(self.actions.menu_for(first))
                          if entry[0] == 'win.item-move-in-playlist'], [1])
        self.assertEqual([entry[1][3] for entry in actions_of(self.actions.menu_for(last))
                          if entry[0] == 'win.item-move-in-playlist'], [-1])
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
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.b', 1, 1)
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.c', 'i.b'])
        self.assertEqual(self.window.announced, ['“Song B” moved to position 3 of 3'])
        self.assertIn(('reorder_playlist', 'p.pl1', ('i.a', 'i.b', 'i.c'), (0, 2, 1)),
                      self.writes())
        self.assertEqual(self.app.toasts, ['Moved “Song B”'])
        # A menu made before the list changed names a song no longer there: nothing.
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.b', 1, -1)
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.c', 'i.b'])
        # Undo: the order before, written back.
        await self.run_action('item-undo-reorder', 'p.pl1')
        self.assertEqual(self.app.playlist.track_ids(), ['i.a', 'i.b', 'i.c'])
        self.assertEqual(self.writes()[-1],
                         ('reorder_playlist', 'p.pl1', ('i.a', 'i.c', 'i.b'), (0, 2, 1)))

    async def test_the_order_pending_goes_before_a_removal(self):
        self.app.engine.items[('playlist', 'p.pl1')] = PLAYLIST_ANSWER
        self.songs('i.a', 'i.b', 'i.c')
        await self.run_action('item-move-in-playlist', 'p.pl1', 'i.c', 2, -1)  # pending
        self.assertNotIn('reorder_playlist', [call[0] for call in self.writes()])
        await self.run_action('item-remove-from-playlist', 'p.pl1', 'i.c', 1)
        self.assertEqual([call[0] for call in self.writes()][:2],
                         ['reorder_playlist', 'remove_from_playlist'])

    async def test_rename_a_playlist_and_its_description(self):
        self.app.engine.listings = [[], [{'kind': 'playlist', 'id': 'p.pl1',
                                          'name': 'Night Drive'}]]
        await self.run_action('item-rename', 'playlist', 'p.pl1')
        heading, confirm, name, description, done = self.asked[0]
        self.assertEqual((heading, confirm, name, description),
                         ('Rename Playlist', '_Rename', 'Road Trip', ''))
        done('Night Drive', 'Late, with the windows down')
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
        self.assertEqual((self.asked, self.confirms, self.writes()), ([], [], []))
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
        heading, confirm, name, description, done = self.asked[0]
        self.assertEqual((heading, confirm, name, description),
                         ('New Playlist', '_Create', '', ''))
        done('Harbour Songs', None)
        await self.settle()
        self.assertEqual(self.writes(), [
            ('create_playlist', 'Harbour Songs', None, (('song', 'i.song1'),), None)])
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
        heading, confirm, name, description, done = self.asked[0]
        # Named after the first song, which the user may change.
        self.assertEqual((heading, confirm, name, description),
                         ('New Playlist', '_Create', 'Harbour Lights', ''))
        done('Harbour Lights', None)
        await self.settle()
        self.assertEqual(self.writes(), [
            ('create_playlist', 'Harbour Lights', None,
             (('song', 'i.song1'), ('video', 'i.vid1')), None)])
        self.assertEqual(self.app.toasts, ['Created “Harbour Lights”'])
        self.assertEqual(self.window.selected, ['playlist:p.new'])  # then shown
        # One song: the toast names it.
        self.assertTrue(self.actions.drop_new_playlist(ItemRefs.for_objects([UPLOAD_TRACK])))
        self.asked[1][4]('Takes', '')
        await self.settle()
        self.assertEqual(self.app.toasts[-1], 'Added “Demo Take” to the new playlist “Takes”')
        # Playlists dropped there are moved, not made into a playlist: refused here.
        for refused in (ItemRefs.for_objects([PLAYLIST]),
                        ItemRefs.for_objects([LIBRARY_TRACK, PLAYLIST]), None):
            self.assertFalse(self.actions.drop_new_playlist(refused))
        self.assertEqual(len(self.asked), 2)

    async def test_new_playlist_in_a_folder_is_shown(self):
        new = Item({'id': 'p.new', 'kind': 'playlist', 'title': 'Fresh'})

        def start_sync(quick=False, playlists=False, videos=False, tracks_of=()):
            self.app.library.items[('playlist', 'p.new')] = new  # the pass brought it

        self.app.start_sync = start_sync
        await self.run_action('item-new-playlist', 'folder', 'p.fd1')
        self.asked[0][4]('Fresh', 'Brand new')
        await self.settle()
        self.assertEqual(self.writes(), [('create_playlist', 'Fresh', 'Brand new', (), 'p.fd1')])
        self.assertEqual(self.app.toasts, ['Created “Fresh”'])
        self.assertEqual(self.window.selected, ['playlist:p.new'])

    async def test_the_demo_shows_the_dialog_and_writes_nothing(self):
        self.app.demo = True
        await self.run_action('item-new-playlist', 'folder', 'root')
        self.asked[0][4]('Fresh', None)
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
        await self.run_action('item-move-to-folder', 'root', 'playlist', 'p.pl1')  # gated
        await self.run_action('item-move-to-folder', 'p.fd2', 'folder', 'p.fd1')  # gated
        await self.run_action('item-move-to-folder', 'p.fd1', 'playlist', 'p.fav')
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.app.toasts, ['This cannot be moved there'] * 4)
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', True):
            await self.run_action('item-move-to-folder', 'root', 'playlist', 'p.pl1')
        self.assertEqual(self.writes(), [('move_to_folder', 'playlist', 'p.pl1', 'root')])
        self.assertEqual(self.app.toasts[-1], 'Moved “Road Trip” to the top level')

    async def test_dropping_playlists_on_a_folder(self):
        refs = ItemRefs.for_objects([self.app.playlist])
        self.assertTrue(self.actions.can_move_refs(refs, 'p.fd2'))
        self.assertFalse(self.actions.can_move_refs(refs, 'p.fd1'))  # where it is
        self.assertFalse(self.actions.can_move_refs(refs, 'root'))  # not confirmed yet
        self.assertFalse(self.actions.can_move_refs(ItemRefs.for_objects([self.folder]),
                                                    'p.fd2'))
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
        self.assertIn(('folder_children', 'p.fd1'), self.app.engine.calls)
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
        self.assertTrue(await self.actions.wait_listed('root', 'p.pl1', None))
        engine.listings = [listed] * 3
        self.assertFalse(await self.actions.wait_listed('root', 'p.pl1', 'Night Drive'))
        engine.listings = [EngineError('engine-down')]
        self.assertFalse(await self.actions.wait_listed('root', 'p.pl1', None))


# A library album with its tracks, a music video and a playlist of Apple's that may not be
# removed, for Remove from Library.
HELD_ALBUM = Item({'id': 'l.alb2', 'kind': 'album', 'title': 'Low Tide',
                   'play': {'kind': 'album', 'id': 'l.alb2'},
                   'groups': [{'name': 'Disc 1', 'play': {'kind': 'album', 'id': 'l.alb2'},
                               'entries': [
                                   {'id': 'i.song3', 'catalogId': '1000000021',
                                    'title': 'Undertow', 'type': 'library-songs'},
                                   {'id': 'i.song4', 'catalogId': '1000000022',
                                    'title': 'Slack Water', 'type': 'library-songs'}]}]})
LONE_ALBUM = Item({'id': 'l.alb3', 'kind': 'album', 'title': 'Single File',
                   'play': {'kind': 'album', 'id': 'l.alb3'},
                   'groups': [{'name': 'Disc 1', 'play': {'kind': 'album', 'id': 'l.alb3'},
                               'entries': [{'id': 'i.song5', 'catalogId': '1000000023',
                                            'title': 'Alone', 'type': 'library-songs'}]}]})
LIBRARY_VIDEO = Item({'id': 'i.vid2', 'kind': 'video', 'title': 'Undertow (Video)',
                      'catalogId': '1000000024',
                      'play': {'kind': 'musicVideo', 'id': '1000000024'}})
KEPT_PLAYLIST = Item({'id': 'p.pl3', 'kind': 'playlist', 'title': 'Apple Keeps',
                      'attributes': {'canEdit': False, 'canDelete': False},
                      'play': {'kind': 'playlist', 'id': 'p.pl3'}})
# A playlist of the user's holding the album's first song (by its catalog id) and the video.
HOLDING = Item({'id': 'p.pl4', 'kind': 'playlist', 'title': 'Undertows',
                'play': {'kind': 'playlist', 'id': 'p.pl4'},
                'groups': [{'name': 'Tracks', 'play': {'kind': 'playlist', 'id': 'p.pl4'},
                            'entries': [{'id': 'i.plt1', 'catalogId': '1000000021',
                                         'title': 'Undertow', 'type': 'library-songs'},
                                        {'id': 'i.vid2', 'catalogId': '1000000024',
                                         'title': 'Undertow (Video)',
                                         'type': 'library-music-videos'}]}]})
# A catalog album's track that the library holds too (HELD_ALBUM's second).
CATALOG_HELD = Track({'id': '1000000022', 'catalogId': '1000000022', 'title': 'Slack Water'},
                     play={'kind': 'album', 'id': '1000000002'})


def track_of(item, position):
    """The Track at `position` of an Item's first group, as its page shows it."""
    group = item.raw['groups'][0]
    return Track(group['entries'][position], play=group['play'])


class RemovalMenuTest(unittest.TestCase):
    """Which objects Remove from Library takes out of the library (removal_target), and
    the menus that offer it."""

    def setUp(self):
        self.library = FakeLibrary([LIBRARY_ALBUM, HELD_ALBUM, LONE_ALBUM, MADE_UP_ALBUM,
                                    CATALOG_ALBUM, PLAYLIST, READ_ONLY, FAVOURITES,
                                    KEPT_PLAYLIST, HOLDING, LIBRARY_VIDEO])

    def test_what_the_library_holds_is_removable(self):
        library = self.library
        self.assertEqual(removal_target(LIBRARY_TRACK, library), ('song', 'i.song1'))
        self.assertEqual(removal_target(track_of(HELD_ALBUM, 1), library), ('song', 'i.song4'))
        # A playlist's entry, a catalog album's track: the library's song of that catalog id.
        self.assertEqual(removal_target(track_of(HOLDING, 0), library), ('song', 'i.song3'))
        self.assertEqual(removal_target(CATALOG_HELD, library), ('song', 'i.song4'))
        self.assertEqual(removal_target(LIBRARY_ALBUM, library), ('album', 'l.alb1'))
        self.assertEqual(removal_target(LIBRARY_VIDEO, library), ('video', 'i.vid2'))
        self.assertEqual(removal_target(track_of(HOLDING, 1), library), ('video', 'i.vid2'))
        self.assertEqual(removal_target(READ_ONLY, library), ('playlist', 'p.pl2'))

    def test_what_is_not_removed_so(self):
        library = self.library
        for obj in (CATALOG_TRACK, CATALOG_SONG, CATALOG_ALBUM, CATALOG_VIDEO, MADE_UP_ALBUM,
                    STATION, LIBRARY_ARTIST, FOLDER,
                    PLAYLIST,  # the user's own: Delete Playlist…
                    FAVOURITES, KEPT_PLAYLIST):  # Apple says it cannot be deleted
            self.assertIsNone(removal_target(obj, library), obj)
        self.assertIsNone(removal_target(LIBRARY_TRACK, None))
        # An album the library no longer has (gone since the page was shown).
        self.assertIsNone(removal_target(LIBRARY_ALBUM, FakeLibrary([])))
        self.assertTrue(is_removable_playlist(READ_ONLY))
        self.assertFalse(is_removable_playlist(KEPT_PLAYLIST))

    def test_the_menu_offers_it_last_and_no_add_beside_it(self):
        menu = build_menu(LIBRARY_ALBUM, removable=('album', 'l.alb1'))
        self.assertEqual(actions_of(menu)[-1],
                         ('win.item-remove-from-library', ('album', 'l.alb1')))
        self.assertIn('Remove from Li_brary…', labels_of(menu))
        menu = build_menu(CATALOG_HELD, removable=('song', 'i.song4'))
        self.assertNotIn('win.item-add-to-library', names(menu))
        self.assertEqual(actions_of(menu)[-1],
                         ('win.item-remove-from-library', ('song', '1000000022')))
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_HELD)))
        self.assertNotIn('win.item-remove-from-library', names(build_menu(LIBRARY_ALBUM)))

    def test_the_mnemonics_stay_distinct(self):
        labels = labels_of(build_menu(LIBRARY_TRACK, playlists=[('p.pl1', 'Road Trip', None)],
                                      removable=('song', 'i.song1')))
        letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label
                   and label != 'Road Trip']
        self.assertEqual(len(letters), len(set(letters)), labels)

    def test_the_confirmation_says_what_goes_with_it(self):
        heading, body = removal_words('song', 'Undertow')
        self.assertEqual(heading, 'Remove from Library?')
        self.assertIn('“Undertow”', body)
        self.assertIn('from your playlists', body)
        self.assertIn('and its songs', removal_words('album', 'Low Tide')[1])
        self.assertNotIn('playlists', removal_words('playlist', 'Apple Picks')[1])
        self.assertNotIn('“', removal_words('song', '')[1])


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
        for name, value in (('SETTLE_DELAYS', (0, 0, 0)), ('REMOVAL_DELAYS', (0, 0, 0)),
                            ('LISTING_LAG', 0)):
            self.addCleanup(setattr, actions_module, name, getattr(actions_module, name))
            setattr(actions_module, name, value)

    async def settle(self):
        while self.app.tasks:
            tasks = list(self.app.tasks)
            self.app.tasks.clear()
            await asyncio.gather(*tasks)

    async def remove(self, obj, confirm=True):
        """Remove from Library on obj as its menu runs it, the dialog answered."""
        self.actions.menu_for(obj)
        self.window.actions['item-remove-from-library'].activate(
            GLib.Variant('(ss)', actions_module.describe(obj)))
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


if __name__ == '__main__':
    unittest.main()
