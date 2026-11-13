# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The selection of a track list's selection mode (applemusic.selection): songs by their id,
not positions, so a filter, a sort or a reload keeps what it still shows. GObject only, no
display."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.library import Item, Library, SongEntry, Track, TrackRecord, selection_key
from applemusic.selection import Picks, Places, Selection


def tracks(count):
    # Invented songs; two of one id, as a playlist holding a song twice has them.
    return [Track({'id': f'i.s{n % 4}', 'title': f'Song {n}', 'index': n}) for n in range(count)]


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.selection = Selection()
        self.changes = []
        self.selection.connect('changed', lambda selection: self.changes.append(
            (selection.active, selection.count)))
        self.shown = tracks(6)

    def test_the_mode_on_and_off(self):
        self.assertFalse(self.selection.active)
        self.selection.start()
        self.assertTrue(self.selection.active)
        self.assertEqual(self.changes, [(True, 0)])
        self.selection.start()  # on already: nothing
        self.assertEqual(len(self.changes), 1)
        self.selection.toggle(self.shown[0])
        self.selection.stop()
        self.assertFalse(self.selection.active)
        self.assertEqual(self.selection.count, 0)  # leaving clears it
        self.assertEqual(self.changes[-1], (False, 0))

    def test_a_toggle_starts_the_mode_and_flips_one_track(self):
        a, b = self.shown[0], self.shown[4]  # the same song's two entries
        self.selection.toggle(a)
        self.assertTrue(self.selection.active)
        self.assertTrue(self.selection.has(a))
        self.assertFalse(self.selection.has(b))  # each entry by itself
        self.selection.toggle(a)
        self.assertFalse(self.selection.has(a))
        self.assertTrue(self.selection.active)  # the mode stays

    def test_a_range_from_the_last_toggled(self):
        shown = self.shown
        self.selection.toggle(shown[1])
        self.selection.extend(shown, shown[3])
        self.assertEqual(self.selection.ordered(shown), shown[1:4])
        # From the same anchor again, upwards, keeping what is selected.
        self.selection.extend(shown, shown[0])
        self.assertEqual(self.selection.ordered(shown), shown[:4])
        # No anchor shown (a filter took it away): the track alone, and it is the anchor.
        selection = Selection()
        selection.extend(shown, shown[2])
        self.assertEqual(selection.ordered(shown), [shown[2]])
        selection.extend(shown, shown[4])
        self.assertEqual(selection.ordered(shown), shown[2:5])
        selection.extend(shown, Track({'id': 'i.gone'}))  # not shown: nothing
        self.assertEqual(selection.count, 3)

    def test_all_and_none(self):
        self.selection.select_all(self.shown)
        self.assertTrue(self.selection.active)
        self.assertEqual(self.selection.count, 6)
        self.selection.select_none()
        self.assertEqual(self.selection.count, 0)
        self.assertTrue(self.selection.active)

    def test_what_a_filter_hides_leaves_the_selection(self):
        shown = self.shown
        for track in shown[:3]:
            self.selection.toggle(track)
        self.assertFalse(self.selection.keep(shown))  # all still shown: nothing changes
        self.assertTrue(self.selection.keep(shown[1:]))
        self.assertEqual(self.selection.ordered(shown), shown[1:3])
        # The anchor gone with it: a range starts again from the track.
        self.selection.toggle(shown[1])
        self.selection.keep(shown[2:])
        self.selection.extend(shown[2:], shown[5])
        self.assertEqual(self.selection.ordered(shown), [shown[2], shown[5]])

    def test_ordered_follows_the_order_shown(self):
        shown = self.shown
        self.selection.toggle(shown[4])
        self.selection.toggle(shown[0])
        self.assertEqual(self.selection.ordered(shown), [shown[0], shown[4]])
        self.assertEqual(self.selection.ordered(list(reversed(shown))), [shown[4], shown[0]])
        self.assertEqual(Selection().ordered(shown), [])

    def test_a_key_knows_an_entry_and_its_track_as_one(self):
        """The Songs table selects among SongEntries while its rows bind their Tracks: by
        library.song_key(), either selects the song, and ordered() answers what is shown."""
        from applemusic.library import SongEntry, song_key, song_track

        entries = [SongEntry({'id': f'i.e{n}', 'title': f'Song {n}'},
                             (None, 0, {'kind': 'song', 'id': f'i.e{n}'}, None))
                   for n in range(5)]
        tracks = [song_track(entry) for entry in entries]
        selection = Selection(song_key)
        selection.toggle(tracks[3])  # a click on a row
        self.assertTrue(selection.has(entries[3]))
        selection.extend(entries, tracks[1])  # a Shift+click, the list's entries shown
        self.assertEqual(selection.ordered(entries), entries[1:4])
        self.assertEqual(selection.ordered(tracks), tracks[1:4])
        self.assertTrue(selection.keep(entries[2:]))  # a filter left out the first
        self.assertEqual(selection.count, 2)
        selection.select_all(entries)
        self.assertTrue(all(selection.has(track) for track in tracks))
        self.assertEqual(selection.count, 5)

    def test_nothing_selected_asks_no_key(self):
        asked = []
        selection = Selection(lambda track: asked.append(track) or track)
        self.assertFalse(selection.has(self.shown[0]))  # a bind outside the mode
        self.assertEqual(asked, [])


def song(song_id, title, index=0):
    """An invented library song as library.json holds it."""
    return {'id': song_id, 'catalogId': None, 'title': title, 'artist': 'Invented Artist',
            'album': 'Invented Album', 'trackNumber': index + 1, 'discNumber': 1,
            'durationMs': 180000, 'durationLabel': '3:00', 'explicit': False, 'index': index,
            'thumb': None, 'type': 'library-songs'}


class SelectionKeyTest(unittest.TestCase):
    """library.selection_key(): a song by its id, the same for its entry and its Track and
    for the new record a reload gives it."""

    def test_by_the_songs_id(self):
        record = TrackRecord(song('i.a1', 'Tidewater'))
        entry = SongEntry(record, (None, 0, {}, None))
        self.assertEqual(selection_key(entry), 'i.a1')
        self.assertEqual(selection_key(entry.track()), 'i.a1')
        again = TrackRecord(song('i.a1', 'Tidewater (Remastered)'))  # a reload's
        self.assertEqual(selection_key(Track(again)), 'i.a1')
        self.assertEqual(selection_key(Track({'id': 'i.a2'})), 'i.a2')  # a dict too
        # No id: the record itself, so two such songs are two.
        loose = Track({'title': 'Untitled'})
        self.assertEqual(selection_key(loose), id(loose.raw))
        other = Track(TrackRecord({'title': 'Untitled'}))
        self.assertEqual(selection_key(other), id(other.raw))


class ReloadTest(unittest.TestCase):
    """#574: a sync that changes an album gives it new records and Tracks; its songs stay
    selected, and only a song the reload took out leaves the selection."""

    def write(self, albums):
        def album(album_id, ids):
            play = {'kind': 'album', 'id': album_id}
            return {'id': album_id, 'kind': 'album', 'title': album_id, 'play': play,
                    'groups': [{'name': 'Disc 1', 'play': play, 'entries': [
                        song(song_id, f'Song {song_id}', n) for n, song_id in enumerate(ids)]}]}

        data = {'version': 5, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': [album(album_id, ids) for album_id, ids in albums]},
                'shelves': []}
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')

    def run_library(self, call):
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache}):
            asyncio.run(call())

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = directory.name

    def test_a_changed_album_keeps_its_songs_selected(self):
        first = [f'i.a{n}' for n in range(4)]
        second = [f'i.b{n}' for n in range(4)]
        self.write([('l.a', first), ('l.b', second)])
        library = Library()
        self.run_library(library.load)
        self.run_library(library.build_songs)
        selection = Selection(selection_key)
        selection.select_all(library.songs.entries)
        self.assertEqual(selection.count, 8)
        # One more song on the first album: its records are new, its songs the same.
        self.write([('l.a', first + ['i.a4']), ('l.b', second)])
        old = list(library.songs.entries)
        self.run_library(library.reload)
        self.assertFalse(any(entry is old[0] for entry in library.songs.entries))
        self.assertFalse(selection.keep(library.songs.entries))
        self.assertEqual(selection.count, 8)
        self.assertEqual(len(selection.ordered(library.songs.entries)), 8)
        self.assertFalse(selection.has(library.songs.entries[4]))  # the new song
        # The album's own Tracks, made again, are selected too (a detail page's rows).
        album = library.by_id('album', 'l.a')
        self.assertTrue(selection.has(album.groups[0].entries.get_item(0)))
        # A song taken out leaves the selection; the rest stay.
        self.write([('l.a', first[1:] + ['i.a4']), ('l.b', second)])
        self.run_library(library.reload)
        self.assertTrue(selection.keep(library.songs.entries))
        self.assertEqual(selection.count, 7)


class PlacesTest(unittest.TestCase):
    """A detail page's key: a song a playlist holds twice is two entries, each selected by
    itself, and each keeps its selection when the playlist is read again."""

    def playlist(self, ids):
        return [Track(TrackRecord(song(song_id, f'Song {song_id}', n)))
                for n, song_id in enumerate(ids)]

    def test_a_song_held_twice_is_selected_twice(self):
        shown = self.playlist(['i.x', 'i.y', 'i.x', 'i.z'])
        places = Places(lambda: shown)
        selection = Selection(places.key)
        self.assertEqual([places.key(track) for track in shown],
                         [('i.x', 0), ('i.y', 0), ('i.x', 1), ('i.z', 0)])
        selection.toggle(shown[2])  # the second Song i.x
        self.assertEqual(selection.ordered(shown), [shown[2]])
        self.assertFalse(selection.has(shown[0]))

    def test_a_reload_keeps_each_entry_selected(self):
        shown = self.playlist(['i.x', 'i.y', 'i.x', 'i.z'])
        places = Places(lambda: shown)
        selection = Selection(places.key)
        selection.toggle(shown[2])
        selection.toggle(shown[3])
        # Read again with a song added at the top: new Tracks, each place moved down one.
        shown = self.playlist(['i.w', 'i.x', 'i.y', 'i.x', 'i.z'])
        places.forget()
        self.assertFalse(selection.keep(shown))
        self.assertEqual(selection.ordered(shown), [shown[3], shown[4]])
        # The first Song i.x taken out: the second is the first now, which was not selected.
        shown = self.playlist(['i.w', 'i.y', 'i.x', 'i.z'])
        places.forget()
        self.assertTrue(selection.keep(shown))
        self.assertEqual(selection.ordered(shown), [shown[3]])

    def test_worked_out_once_until_forgotten(self):
        shown = self.playlist(['i.x', 'i.x'])
        asked = []

        def tracks():
            asked.append(True)
            return shown

        places = Places(tracks)
        for track in shown + shown:
            places.key(track)
        self.assertEqual(len(asked), 1)
        places.forget()
        places.key(shown[0])
        self.assertEqual(len(asked), 2)


class PicksTest(unittest.TestCase):
    """Add Songs…'s picks: songs from the library's list and a search's, each once by its
    kind and id, in the order picked."""

    def test_picked_once_wherever_it_shows(self):
        picks = Picks()
        changes = []
        picks.connect('changed', lambda picks: changes.append(picks.count))
        library = Track({'id': 'i.s1', 'title': 'Harbour Lights', 'type': 'library-songs'})
        again = Track({'id': 'i.s1', 'title': 'Harbour Lights', 'type': 'library-songs'})
        catalog = Item({'id': '1000000001', 'kind': 'song', 'title': 'Tidewater'})
        video = Item({'id': '1000000002', 'kind': 'video', 'title': 'Lantern'})
        self.assertTrue(picks.toggle(catalog))
        self.assertTrue(picks.toggle(library))
        self.assertTrue(picks.toggle(video))
        self.assertTrue(picks.has(again))  # the same song in another list
        self.assertEqual(picks.objects(), [catalog, library, video])
        self.assertEqual(Picks.key(video), ('video', '1000000002'))
        self.assertTrue(picks.toggle(again))  # unpicked from there
        self.assertFalse(picks.has(library))
        self.assertEqual(picks.objects(), [catalog, video])
        self.assertEqual(changes, [1, 2, 3, 2])

    def test_only_songs_and_videos(self):
        picks = Picks()
        album = Item({'id': 'l.alb1', 'kind': 'album', 'title': 'Tidewater'})
        self.assertFalse(picks.toggle(album))
        self.assertFalse(picks.toggle(Track({'title': 'No Id'})))
        self.assertFalse(picks.has(album))
        self.assertEqual(picks.count, 0)


if __name__ == '__main__':
    unittest.main()
