# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""SongOrder (library/songs.py): the Songs table's orders, sorted in Python."""

import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as applemusic)

from applemusic.library import SongOrder, Track, fold
from applemusic.library import songs as songs_module


class TestSongOrder(unittest.TestCase):
    def setUp(self):
        rows = [
            # id, title, artist, album, disc, track, ms
            ('i.1', 'beta', 'Zed', 'Second', 1, 2, 200000),
            ('i.2', 'Alpha', 'zed', 'Second', 1, 1, 100000),
            ('i.3', 'alpha', 'Ann', 'First', 2, 1, 300000),
            ('i.4', 'Gamma', 'Ann', 'First', 1, 1, 100000),
            ('i.5', 'delta', 'Ann', 'Third', 1, 1, 250000),
        ]
        self.tracks = [Track({'id': i, 'title': title, 'artist': artist, 'album': name,
                              'discNumber': disc, 'trackNumber': number, 'durationMs': ms})
                       for i, title, artist, name, disc, number, ms in rows]
        self.order = SongOrder(self.tracks)

    def ids(self, column, descending=False):
        return [t.id for t in self.order.tracks(column, descending)]

    def test_title_ignores_case_and_breaks_ties_by_artist(self):
        self.assertEqual(self.ids('title'), ['i.3', 'i.2', 'i.1', 'i.5', 'i.4'])
        self.assertEqual(self.ids('title', descending=True), ['i.4', 'i.5', 'i.1', 'i.3', 'i.2'])

    def test_artist_keeps_albums_and_tracks_in_order_both_ways(self):
        self.assertEqual(self.ids('artist'), ['i.4', 'i.3', 'i.5', 'i.2', 'i.1'])
        self.assertEqual(self.ids('artist', descending=True), ['i.2', 'i.1', 'i.4', 'i.3', 'i.5'])

    def test_album_then_artist_then_track(self):
        self.assertEqual(self.ids('album'), ['i.4', 'i.3', 'i.2', 'i.1', 'i.5'])
        self.assertEqual(self.ids('album', descending=True), ['i.5', 'i.2', 'i.1', 'i.4', 'i.3'])

    def test_time_is_numeric(self):
        self.assertEqual(self.ids('time'), ['i.2', 'i.4', 'i.1', 'i.5', 'i.3'])
        self.assertEqual(self.ids('time', descending=True), ['i.3', 'i.5', 'i.1', 'i.2', 'i.4'])

    def test_fold_ignores_case_and_accents(self):
        self.assertEqual(fold('Beyoncé'), 'beyonce')
        self.assertEqual(fold('ÉLAN Straße'), 'elan strasse')
        self.assertEqual(fold('Ｆｕｌｌ'), 'full')  # compatibility forms too
        self.assertEqual(fold('Plain ASCII'), 'plain ascii')
        track = Track({'title': 'Café', 'artist': 'Zoë', 'album': 'Über'})
        self.assertEqual(track.search_key, 'cafe\nzoe\nuber')

    def test_prepare_computes_the_keys_a_few_at_a_time(self):
        pauses = []
        yield_to_frames = songs_module.yield_to_frames

        async def counting_yield():
            pauses.append(True)
            await yield_to_frames()

        order = SongOrder(self.tracks)
        with mock.patch.object(SongOrder, 'STEP', 2), \
                mock.patch.object(songs_module, 'FRAME_BUDGET', 0), \
                mock.patch.object(songs_module, 'yield_to_frames', counting_yield):
            asyncio.run(order.prepare('title'))
        self.assertEqual(set(order._keys), {'title', 'artist', 'album', 'track'})
        # 5 tracks in steps of 2 (3 steps): the track numbers pause after each step; a text
        # column after each step of collation and of ranks, after each sorted run of its
        # distinct texts, and after each step of their merge; the search keys after each step.
        distinct = {'title': 5, 'artist': 3, 'album': 3}
        self.assertEqual(len(pauses), 3 + sum(3 + (count + 1) // 2 + count // 2 + 3
                                              for count in distinct.values()) + 3)
        # Every search key is made: the filter's first letter folds nothing.
        self.assertTrue(all(t._search_key is not None for t in self.tracks))
        pauses.clear()
        with mock.patch.object(songs_module, 'yield_to_frames', counting_yield):
            asyncio.run(order.prepare('album'))  # its keys are there, and the search keys
        self.assertEqual(pauses, [])
        self.assertEqual([t.id for t in order.tracks('title')], self.ids('title'))

    def test_same_objects_and_repeatable(self):
        first = self.order.tracks('artist')
        self.assertTrue(all(any(t is u for u in self.tracks) for t in first))
        self.assertEqual(self.order.tracks('artist'), first)
        self.assertEqual(SongOrder([]).tracks('title'), [])

    def test_genre_and_year_break_ties_by_artist_album_and_track(self):
        # The optional columns (song_columns.py): a genre's text ignoring case, a year as a
        # number (none is 0, first), each then by artist, album and disc and track.
        rows = [
            # id, artist, album, track, genre, year
            ('i.1', 'Bea', 'North', 2, 'Shoegaze', 2019),
            ('i.2', 'Bea', 'North', 1, 'shoegaze', 2019),
            ('i.3', 'Abe', 'South', 1, 'Ambient', 2021),
            ('i.4', 'Cy', 'East', 1, None, None),
            ('i.5', 'Abe', 'West', 1, 'Shoegaze', 2007),
        ]
        tracks = [Track({'id': i, 'title': i, 'artist': artist, 'album': name,
                         'discNumber': 1, 'trackNumber': number, 'genre': genre, 'year': year})
                  for i, artist, name, number, genre, year in rows]
        order = SongOrder(tracks)
        asyncio.run(order.prepare('genre'))

        def ids(column, descending=False):
            return [t.id for t in order.tracks(column, descending)]

        self.assertEqual(ids('genre'), ['i.4', 'i.3', 'i.5', 'i.2', 'i.1'])
        self.assertEqual(ids('genre', descending=True), ['i.5', 'i.2', 'i.1', 'i.3', 'i.4'])
        self.assertEqual(ids('year'), ['i.4', 'i.5', 'i.2', 'i.1', 'i.3'])
        self.assertEqual(ids('year', descending=True), ['i.3', 'i.2', 'i.1', 'i.5', 'i.4'])


if __name__ == '__main__':
    unittest.main()
