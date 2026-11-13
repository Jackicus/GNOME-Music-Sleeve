# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The item menus (applemusic.item_menu): the menu built per kind, its submenus and its
labels, and the Remove from Library it offers. Gio only, no display."""

import unittest
from unittest import mock

from gi.repository import Gio

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import action_messages
from applemusic import item_menu
from applemusic import item_targets
from applemusic.action_messages import removal_words
from applemusic.backend import api
from applemusic.item_menu import (RATING_ACTIONS, build_menu, main_menu_section, mnemonic_escaped,
                                  rating_actions)
from applemusic.item_targets import (can_play, credits_target, describe, favourite_target,
                                     is_removable_playlist, move_targets, now_playing_track,
                                     playlist_track, queue_target, queue_targets, rating_target,
                                     removal_target, station_target)
from applemusic.library import Item, ItemRefs, PlaylistTree, Track
from applemusic.player import NowPlaying
from tests.item_actions_harness import (BAND, CATALOG_ALBUM, CATALOG_ARTIST, CATALOG_PLAYLIST,
                                        CATALOG_SONG, CATALOG_TRACK, CATALOG_VIDEO, FAVOURITES,
                                        FOLDER, HELD_ALBUM, HOLDING, LIBRARY_ALBUM, LIBRARY_ARTIST,
                                        LIBRARY_TRACK, LIBRARY_VIDEO, LONE_ALBUM, LOOSE_ARTIST,
                                        MADE_UP_ALBUM, PLAYLIST, READ_ONLY, SHOW, STATION,
                                        UPCOMING_ALBUM, UPLOAD_TRACK, VIDEO_TRACK, FakeLibrary,
                                        actions_of, labels_of, mnemonic_clashes, names, submenu_of,
                                        track_of)


TOP_LEVEL = Item({'id': 'root', 'kind': 'folder', 'title': ''})  # the top level: All Playlists
CATEGORY = Item({'id': '1000000008', 'kind': 'category', 'title': 'Jazz'})
UNRELEASED_TRACK = Track({'id': '1000000061', 'catalogId': '1000000061', 'title': 'Soon',
                          'type': 'songs', 'index': 1, 'unreleased': True},
                         play={'kind': 'album', 'id': '1000000060'})


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


def section_of(menu, label):
    """The section headed `label` among a menu's items and sections, or None."""
    for position in range(menu.get_n_items()):
        found = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        if section is None:
            continue
        if found is not None and found.unpack() == label:
            return section
        inside = section_of(section, label)
        if inside is not None:
            return inside
    return None


def submenu_labels(menu):
    """The labels of every submenu in a menu, nested ones too, in order."""
    found = []
    for position in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        submenu = menu.get_item_link(position, Gio.MENU_LINK_SUBMENU)
        if submenu is not None:
            found.append(label.unpack())
        for linked in (submenu, menu.get_item_link(position, Gio.MENU_LINK_SECTION)):
            if linked is not None:
                found.extend(submenu_labels(linked))
    return found


def section_headings(menu):
    """The headings of a menu's sections, nested ones too, in order."""
    found = []
    for position in range(menu.get_n_items()):
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        if section is None:
            continue
        label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        if label is not None:
            found.append(label.unpack())
        found.extend(section_headings(section))
    return found


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
                    self.assertIsNone(section_of(menu, 'Evenings'))
                else:
                    self.assertEqual(added, [('p.pl3', *describe(obj)), ('p.pl1', *describe(obj))])
                self.assertIn(('win.item-new-playlist', describe(obj)), actions_of(menu))
        # Nothing else takes it: a folder, a station, an artist.
        for obj in (FOLDER, STATION, CATALOG_ARTIST):
            with self.subTest(title=obj.title):
                self.assertNotIn('win.item-add-to-playlist',
                                 names(build_menu(obj, playlists=playlists)) or [])

    def test_catalog_album_can_be_added(self):
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_ALBUM)))

    def test_a_prerelease_album_is_pre_added(self):
        # Add to Library, under Apple Music's word for an album not out yet.
        menu = build_menu(UPCOMING_ALBUM)
        self.assertIn('win.item-add-to-library', names(menu))
        self.assertIn('Pre-_Add to Library', labels_of(menu))
        self.assertNotIn('_Add to Library', labels_of(menu))
        self.assertIn('_Add to Library', labels_of(build_menu(CATALOG_ALBUM)))
        self.assertTrue(item_targets.pre_adds(UPCOMING_ALBUM))
        self.assertFalse(item_targets.pre_adds(CATALOG_ALBUM))
        self.assertFalse(item_targets.pre_adds(UNRELEASED_TRACK))

    def test_a_song_not_out_yet_plays_nothing(self):
        # Its menu has no Play, Play Next or Play Later, and nothing queues it.
        self.assertFalse(can_play(UNRELEASED_TRACK))
        self.assertIsNone(queue_target(UNRELEASED_TRACK))
        actions = names(build_menu(UNRELEASED_TRACK)) or []
        for action in ('win.item-play', 'win.item-play-next', 'win.item-play-later'):
            self.assertNotIn(action, actions)
        self.assertIsNone(queue_targets(ItemRefs([CATALOG_TRACK, UNRELEASED_TRACK])))

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
        menu = build_menu(LIBRARY_TRACK, playlists=[('p.pl1', 'Road Trip', None)])
        labels = labels_of(menu)
        self.assertEqual(mnemonic_clashes(menu, ('Road Trip',)), [])
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
            ('win.item-view-credits', ('song', 'i.song1')),
            ('win.item-love', ('song', 'i.song1')),
            ('win.item-unlove', ('song', 'i.song1')),
            ('win.item-suggest-less', ('song', 'i.song1')),
            ('win.item-undo-suggest-less', ('song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl1', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl3', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl4', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl2', 'song', 'i.song1')),
            ('win.item-add-to-playlist', ('p.pl5', 'song', 'i.song1')),
            ('win.item-new-playlist', ('song', 'i.song1')),
            ('win.item-open-in-browser', ('song', 'i.song1')),
            ('win.item-copy-link', ('song', 'i.song1'))])
        # A playlist's name is shown as it is: its underscores are not mnemonics.
        self.assertIn('work__focus', labels_of(menu))
        # The top level's playlists, then each folder as a submenu of its name (no
        # mnemonic) holding its own playlists, then its folders, as the sidebar nests them.
        listed = submenu_of(menu, 'Add to Pla_ylist')
        self.assertEqual(labels_of(listed), [
            'Road Trip', 'Untitled Playlist', 'work__focus',
            'Evenings', 'Dusk', 'Untitled Folder', 'Late', 'Ne_w Playlist…'])
        evenings = submenu_of(listed, 'Evenings')
        self.assertEqual(labels_of(evenings), ['Dusk', 'Untitled Folder', 'Late'])
        self.assertEqual(actions_of(submenu_of(evenings, 'Untitled Folder')),
                         [('win.item-add-to-playlist', ('p.pl5', 'song', 'i.song1'))])
        self.assertIsNone(section_of(listed, 'Evenings'))
        self.assertEqual(submenu_labels(menu), ['Add to Pla_ylist', 'Evenings', 'Untitled Folder'])
        self.assertEqual(mnemonic_escaped('a_b__c'), 'a__b____c')
        # No playlists: the submenu has New Playlist… alone. A catalog track can be added to
        # the library.
        self.assertNotIn('win.item-add-to-playlist', names(build_menu(LIBRARY_TRACK)))
        self.assertIn('win.item-new-playlist', names(build_menu(LIBRARY_TRACK)))
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_TRACK)))

    def test_add_to_playlist_nests_deeply_and_leaves_out_empty_folders(self):
        # Folders inside folders, as deep as the sidebar has them; a folder whose playlists
        # (at any depth) cannot take the songs is left out, as is one holding only the
        # playlist whose songs these are.
        playlists = [('p.fd1', 'A', [('p.fd2', 'B', [('p.fd3', 'C', [('p.pl1', 'Deep', None)]),
                                                      ('p.fd4', 'Empty', [('p.fd5', 'Emptier', [])])
                                                      ])]),
                     ('p.fd6', 'Itself', [('p.fd7', 'Inside', [('p.pl9', 'Mine', None)])])]
        mine = Item({'id': 'p.pl9', 'kind': 'playlist', 'title': 'Mine',
                     'play': {'kind': 'playlist', 'id': 'p.pl9'}})
        listed = submenu_of(build_menu(mine, playlists=playlists), 'Add to Pla_ylist')
        self.assertEqual(submenu_labels(listed), ['A', 'B', 'C'])
        deep = submenu_of(submenu_of(submenu_of(listed, 'A'), 'B'), 'C')
        self.assertEqual(actions_of(deep),
                         [('win.item-add-to-playlist', ('p.pl1', 'playlist', 'p.pl9'))])
        self.assertEqual(labels_of(listed), ['A', 'B', 'C', 'Deep', 'Ne_w Playlist…'])

    def test_add_to_playlist_falls_back_to_sections_on_a_shared_page(self):
        # A Gtk.PopoverMenu names a submenu's page by its label and its own `main`: two
        # folders of one name (at any depth), a folder named `main` or like another submenu
        # of the menu (Move to Folder, in a translation that gives it no mnemonic: a
        # folder's label has its underscores doubled, so never reads as one of the menu's
        # mnemonic labels) would open another's page, so then every folder is a section
        # headed by its name, as before folders nested.
        labels = item_menu.action_labels()
        unmarked = dict(labels, **{'item-move-to-folder': 'Move to Folder'})
        self.enterContext(mock.patch.object(item_menu, 'action_labels',
                                            lambda: unmarked))
        dusk, dawn = ('p.pl2', 'Dusk', None), ('p.pl3', 'Dawn', None)
        moves = (True, [('p.fd1', 'Evenings', True, [])])
        cases = [
            ([('p.fd1', '', [dusk]), ('p.fd2', '', [dawn])], None,
             ['Untitled Folder', 'Untitled Folder']),
            ([('p.fd1', 'Late', [dusk, ('p.fd2', 'Late', [dawn])])], None,
             ['Late', 'Late › Late']),
            ([('p.fd1', 'main', [dusk]), ('p.fd2', 'Evenings', [dawn])], None,
             ['main', 'Evenings']),
            ([('p.fd1', 'Move to Folder', [dusk]), ('p.fd2', 'Evenings', [dawn])], moves,
             ['Move to Folder', 'Evenings']),
        ]
        for playlists, moved, headings in cases:
            with self.subTest(headings=headings):
                menu = build_menu(PLAYLIST, playlists=playlists, moves=moved)
                listed = submenu_of(menu, 'Add to Pla_ylist')
                self.assertEqual(submenu_labels(listed), [])
                self.assertEqual(section_headings(listed), headings)
                self.assertEqual([target[0] for action, target in actions_of(listed)
                                  if action == 'win.item-add-to-playlist'],
                                 ['p.pl2', 'p.pl3'])
        # Labels that read alike but are not the same: a folder named like Add to
        # Playlist (its underscore doubled), Move to Folder in a menu without it.
        for title, moved in (('Add to Pla_ylist', moves), ('Move to Folder', None),
                             ('Main', None)):
            with self.subTest(title=title):
                menu = build_menu(PLAYLIST, playlists=[('p.fd1', title, [dusk])], moves=moved)
                labels = submenu_labels(menu)
                self.assertEqual(labels[1], mnemonic_escaped(title))
                self.assertTrue(item_menu.pages_distinct(labels), labels)
        # The selection's menu has no other submenu: two folders of one name alone.
        both = [('p.fd1', 'Late', [dusk]), ('p.fd2', 'Late', [dawn])]
        menu = item_menu.playlist_submenu(both, None, action='selection.add-to-playlist')
        self.assertEqual((submenu_labels(menu), section_headings(menu)), ([], ['Late', 'Late']))
        menu = item_menu.playlist_submenu(both[:1], None, action='selection.add-to-playlist')
        self.assertEqual(submenu_labels(menu), ['Late'])
        self.assertTrue(item_menu.pages_distinct(['a', 'b']))
        self.assertFalse(item_menu.pages_distinct(['a', 'a']))
        self.assertFalse(item_menu.pages_distinct(['main']))

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
        self.assertEqual(mnemonic_clashes(menu), [])
        self.assertNotIn('win.item-remove-from-queue',
                         names(build_menu(LIBRARY_TRACK, queued=True)))
        self.assertNotIn('win.item-remove-from-queue', names(build_menu(LIBRARY_TRACK)))

    def test_an_up_next_entry_moves_where_its_menu_says(self):
        # The fifth entry of a section from 3 to 9 (QueueView.moves()).
        menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=(4, 'i.song1'),
                          queue_moves={'top': 3, -1: 3, 1: 5, 'bottom': 9})
        moves = [(name, target) for name, target in actions_of(menu)
                 if name in ('win.item-move-in-queue', 'win.item-remove-from-queue')]
        self.assertEqual(moves, [('win.item-move-in-queue', (4, 3, 'i.song1')),
                                 ('win.item-move-in-queue', (4, 3, 'i.song1')),
                                 ('win.item-move-in-queue', (4, 5, 'i.song1')),
                                 ('win.item-move-in-queue', (4, 9, 'i.song1')),
                                 ('win.item-remove-from-queue', (4, 'i.song1'))])
        labels = labels_of(menu)
        self.assertEqual([label for label in labels
                          if label.replace('_', '').startswith('Move')],
                         ['Move to T_op', '_Move Up', 'Move _Down', 'Mov_e to Bottom'])
        self.assertEqual(mnemonic_clashes(menu), [])
        # At the end of its section: Move to Top and Move Up alone; with no queue entry,
        # none.
        menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=(4, 'i.song1'),
                          queue_moves={'top': 2, -1: 3})
        self.assertEqual([target for name, target in actions_of(menu)
                          if name == 'win.item-move-in-queue'],
                         [(4, 2, 'i.song1'), (4, 3, 'i.song1')])
        self.assertNotIn('win.item-move-in-queue',
                         names(build_menu(LIBRARY_TRACK, queued=True,
                                          queue_moves={-1: 3, 1: 5})))

    def test_play_next_on_an_up_next_entry_moves_it(self):
        # Its section begins just after the entry playing (2): Play Next moves it there.
        menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=(6, 'i.song1'),
                          queue_moves={'next': 3, 'top': 3, -1: 5})
        self.assertEqual(actions_of(menu)[0], ('win.item-move-in-queue', (6, 3, 'i.song1')))
        self.assertEqual(labels_of(menu)[0], 'Play _Next')
        self.assertNotIn('win.item-play-next', names(menu))  # not queued again
        self.assertIn('win.item-play-later', names(menu))
        self.assertEqual(mnemonic_clashes(menu), [])
        # The entry after the one playing plays next already: no Play Next.
        menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=(3, 'i.song1'),
                          queue_moves={'next': None, 1: 4})
        self.assertNotIn('Play _Next', labels_of(menu))
        self.assertEqual([target for name, target in actions_of(menu)
                          if name == 'win.item-move-in-queue'], [(3, 4, 'i.song1')])
        # Autoplay's entry behind the songs queued (no 'next': MusicKit's queue moves it
        # within its section only), the item playing and History's: queued again.
        for queue_entry, queue_moves in (((8, 'i.song1'), {'top': 7}), (None, None)):
            menu = build_menu(LIBRARY_TRACK, queued=True, queue_entry=queue_entry,
                              queue_moves=queue_moves)
            self.assertEqual(actions_of(menu)[0][0], 'win.item-play-next')

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
        self.assertIsNone(item_targets.rating_target(SHOW))
        self.assertIsNone(item_targets.queue_target(SHOW))
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
            'win.item-open-in-browser',  # its library route is the owner's: no Copy Link
            'win.item-duplicate'])  # a copy of its songs, of the user's own
        self.assertEqual(names(build_menu(MADE_UP_ALBUM)), ['win.item-play',
                                                            'win.item-new-playlist'])
        self.assertNotIn('win.item-open-in-browser', names(build_menu(UPLOAD_TRACK)))

    def test_view_credits_for_a_song_with_a_catalog_id(self):
        # Apple's credits are the catalog's: a song by the catalog id it carries.
        library_song = Item({'id': 'i.song9', 'kind': 'song', 'title': 'Lantern',
                             'catalogId': '1000000018'})
        catalog_only = Track({'id': '1000000019', 'title': 'Undertow'})
        playing = now_playing_track(NowPlaying({'id': 'i.song1', 'catalogId': '1000000001',
                                                'title': 'Harbour Lights', 'type': 'song'}))
        for obj, song_id in ((LIBRARY_TRACK, '1000000001'), (CATALOG_TRACK, '1000000009'),
                             (CATALOG_SONG, '1000000007'), (library_song, '1000000018'),
                             (catalog_only, '1000000019'), (playing, '1000000001')):
            with self.subTest(title=obj.title):
                self.assertEqual(credits_target(obj), song_id)
                self.assertIn(('win.item-view-credits', describe(obj)),
                              actions_of(build_menu(obj, queued=obj is playing)))
        # After Go to Album and Go to Artist, beside them.
        menu = names(build_menu(LIBRARY_TRACK))
        self.assertEqual(menu[menu.index('win.item-go-to-album'):][:3], [
            'win.item-go-to-album', 'win.item-go-to-artist', 'win.item-view-credits'])
        # None without a catalog id (an upload, a library song without one), nor for a music
        # video or anything but a song.
        library_only = Item({'id': 'i.song10', 'kind': 'song', 'title': 'Demo Take'})
        for obj in (UPLOAD_TRACK, library_only, VIDEO_TRACK, CATALOG_VIDEO, LIBRARY_ALBUM,
                    CATALOG_ALBUM, CATALOG_ARTIST, PLAYLIST, STATION, FOLDER):
            with self.subTest(title=obj.title):
                self.assertIsNone(credits_target(obj))
                self.assertNotIn('win.item-view-credits', names(build_menu(obj)) or [])

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

    def test_add_songs_and_duplicate(self):
        # Add Songs… on a playlist of the user's; Duplicate on any of the library's, before
        # Rename… and Delete Playlist….
        self.assertEqual(names(build_menu(PLAYLIST))[-4:], [
            'win.item-add-songs', 'win.item-duplicate', 'win.item-rename', 'win.item-delete'])
        self.assertIn('Add Son_gs…', labels_of(build_menu(PLAYLIST)))
        self.assertIn('Dupl_icate', labels_of(build_menu(PLAYLIST)))
        for playlist in (READ_ONLY, FAVOURITES):
            self.assertNotIn('win.item-add-songs', names(build_menu(playlist)))
            self.assertIn(('win.item-duplicate', ('playlist', playlist.id)),
                          actions_of(build_menu(playlist)))
        # A catalog playlist is added to the library (or Add to Playlist's New Playlist…);
        # nothing else is duplicated.
        catalog = Item({'id': 'pl.1000000003', 'kind': 'playlist', 'title': 'Harbour Mix',
                        'play': {'kind': 'playlist', 'id': 'pl.1000000003'}})
        for obj in (catalog, LIBRARY_ALBUM, FOLDER, LIBRARY_TRACK):
            self.assertFalse({'win.item-add-songs', 'win.item-duplicate'}
                             & set(names(build_menu(obj)) or ()), obj.title)
        self.assertTrue(item_targets.adds_to(PLAYLIST))
        self.assertFalse(item_targets.adds_to(FAVOURITES))
        self.assertTrue(item_targets.duplicates(READ_ONLY))
        self.assertFalse(item_targets.duplicates(catalog))
        self.assertEqual(action_messages.duplicate_name('Road Trip'), 'Road Trip Copy')
        self.assertEqual(action_messages.duplicate_name(''), 'Untitled Playlist Copy')

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
        # Every label of the fullest menus has a mnemonic of its own in its level.
        for fullest in (menu, build_menu(PLAYLIST), build_menu(FOLDER)):
            self.assertEqual(mnemonic_clashes(fullest), [])

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
        # A folder is renamed; a playlist's details are edited, in the playlist dialog.
        self.assertIn('Rena_me…', labels_of(build_menu(FOLDER)))
        self.assertIn('Edit De_tails…', labels_of(build_menu(PLAYLIST)))
        self.assertNotIn('Rena_me…', labels_of(build_menu(PLAYLIST)))
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
            'win.item-open-in-browser', 'win.item-add-songs', 'win.item-duplicate',
            'win.item-rename', 'win.item-delete'])
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
        # Its own folder is no target, but holds one; the top level is, out of its folder.
        moves = move_targets(tree, playlist)
        self.assertEqual(moves, (True, [('p.fd1', 'Evenings', False,
                                         [('p.fd3', 'Late_Night', True, [])]),
                                        ('p.fd2', 'Mornings', True, [])]))
        menu = build_menu(playlist, moves=moves)
        submenu = submenu_of(menu, 'Mov_e to Folder')
        self.assertEqual(actions_of(submenu), [
            ('win.item-move-to-folder', ('root', 'playlist', 'p.pl1')),  # Top Level
            ('win.item-move-to-folder', ('p.fd3', 'playlist', 'p.pl1')),
            ('win.item-move-to-folder', ('p.fd2', 'playlist', 'p.pl1')),
            ('win.item-move-to-folder', ('', 'playlist', 'p.pl1'))])  # New Folder…
        # One list: a folder inside another named with the one holding it (its own folder,
        # Evenings, not offered), underscores no mnemonics; no folder is a submenu.
        self.assertEqual(labels_of(submenu), ['_Top Level', 'Evenings › Late__Night',
                                              'Mornings', 'New _Folder…'])
        # A Gtk.PopoverMenu names a submenu's page by its label: with the same folders in
        # Add to Playlist, nested there, still no two submenus of one label
        # (test_context_menu opens them).
        both = build_menu(playlist, moves=moves, playlists=[
            ('p.fd1', 'Evenings', [('p.fd3', 'Late_Night', [('p.pl7', 'Owls', None)])]),
            ('p.fd2', 'Mornings', [('p.pl8', 'Larks', None)])])
        self.assertEqual(submenu_labels(both), ['Add to Pla_ylist', 'Evenings', 'Late__Night',
                                                'Mornings', 'Mov_e to Folder'])
        # Every level has mnemonics of its own (a popover shows one level at a time).
        self.assertEqual(mnemonic_clashes(menu), [])
        # Apple's own playlist at the top level: every folder, not the top level it is at;
        # Favourite Songs: never.
        self.assertEqual(move_targets(tree, playlists[1])[0], False)
        self.assertEqual(move_targets(tree, playlists[1])[1][1][:3], ('p.fd2', 'Mornings', True))
        self.assertIsNone(move_targets(tree, playlists[2]))
        self.assertIsNone(move_targets(tree, LIBRARY_ALBUM))
        self.assertIsNone(move_targets(tree, tree.root.item))
        # A folder: not into itself or what is inside it, nor the top level it is at; one
        # inside a folder to the top level too, and Move to Folder in its menu.
        self.assertEqual(move_targets(tree, evenings),
                         (False, [('p.fd2', 'Mornings', True, [])]))
        late = tree.folder('p.fd3').item
        self.assertEqual(move_targets(tree, late), (True, [('p.fd2', 'Mornings', True, [])]))
        folder_menu = submenu_of(build_menu(late, moves=move_targets(tree, late)),
                                 'Mov_e to Folder')
        self.assertEqual(actions_of(folder_menu), [
            ('win.item-move-to-folder', ('root', 'folder', 'p.fd3')),
            ('win.item-move-to-folder', ('p.fd2', 'folder', 'p.fd3')),
            ('win.item-move-to-folder', ('', 'folder', 'p.fd3'))])
        # A move switched off in api is offered nowhere: no Top Level, no folder moved.
        with mock.patch.object(api, 'MOVE_TO_TOP_LEVEL', False), \
                mock.patch.object(api, 'MOVE_FOLDERS', False):
            self.assertEqual(move_targets(tree, playlist)[0], False)
            moved = submenu_of(build_menu(playlist, moves=move_targets(tree, playlist)),
                               'Mov_e to Folder')
            self.assertNotIn('_Top Level', labels_of(moved))
            self.assertIsNone(move_targets(tree, evenings))

    def test_main_menu_starts_with_new_playlist_and_folder(self):
        # New Playlist… is the window's win.new-playlist, whose key (Ctrl+N) the menu shows.
        self.assertEqual(actions_of(main_menu_section()), [
            ('win.new-playlist', None), ('win.item-new-folder', ('folder', 'root'))])

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

KEPT_PLAYLIST = Item({'id': 'p.pl3', 'kind': 'playlist', 'title': 'Apple Keeps',
                      'attributes': {'canEdit': False, 'canDelete': False},
                      'play': {'kind': 'playlist', 'id': 'p.pl3'}})
# A catalog album's track that the library holds too (HELD_ALBUM's second).
CATALOG_HELD = Track({'id': '1000000022', 'catalogId': '1000000022', 'title': 'Slack Water'},
                     play={'kind': 'album', 'id': '1000000002'})


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

    def test_a_held_catalog_album_or_playlist_goes_as_the_librarys(self):
        # Found as the library's own (Library.held_item, the page's In Library test).
        library = FakeLibrary([HELD_ALBUM, READ_ONLY, PLAYLIST, MADE_UP_ALBUM])
        library.twins = {('album', CATALOG_ALBUM.id): HELD_ALBUM,
                         ('playlist', CATALOG_PLAYLIST.id): READ_ONLY}
        self.assertEqual(removal_target(CATALOG_ALBUM, library), ('album', 'l.alb2'))
        self.assertEqual(removal_target(CATALOG_PLAYLIST, library), ('playlist', 'p.pl2'))
        # A twin that is not removable so: the user's own playlist, a made-up album.
        library.twins = {('album', CATALOG_ALBUM.id): MADE_UP_ALBUM,
                         ('playlist', CATALOG_PLAYLIST.id): PLAYLIST}
        self.assertIsNone(removal_target(CATALOG_ALBUM, library))
        self.assertIsNone(removal_target(CATALOG_PLAYLIST, library))
        # Noted as just added, not listed yet: nothing to take out.
        library = FakeLibrary([HELD_ALBUM])
        library.noted.append(CATALOG_ALBUM)
        self.assertTrue(library.holds(CATALOG_ALBUM))
        self.assertIsNone(removal_target(CATALOG_ALBUM, library))

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
        # Held, as the page's In Library says, though there is nothing to remove yet.
        self.assertNotIn('win.item-add-to-library', names(build_menu(CATALOG_ALBUM, held=True)))
        self.assertIn('win.item-add-to-library', names(build_menu(CATALOG_ALBUM)))

    def test_the_mnemonics_stay_distinct(self):
        menu = build_menu(LIBRARY_TRACK, playlists=[('p.pl1', 'Road Trip', None)],
                          removable=('song', 'i.song1'))
        self.assertEqual(mnemonic_clashes(menu, ('Road Trip',)), [])

    def test_the_confirmation_says_what_goes_with_it(self):
        heading, body = removal_words('song', 'Undertow')
        self.assertEqual(heading, 'Remove from Library?')
        self.assertIn('“Undertow”', body)
        self.assertIn('from your playlists', body)
        self.assertIn('and its songs', removal_words('album', 'Low Tide')[1])
        self.assertNotIn('playlists', removal_words('playlist', 'Apple Picks')[1])
        self.assertNotIn('“', removal_words('song', '')[1])


if __name__ == '__main__':
    unittest.main()
