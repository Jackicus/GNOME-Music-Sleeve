# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""release.py: which catalog album an album page asks for, the footer's words and the
shelves' titles, over invented Items and answers."""

import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.library import Item
from applemusic.release import (album_shelves, album_target, footer_lines, length_text,
                                release_date_text, shelf_title)


def album(album_id='l.alb001', catalog_id=None, songs=(None, '1724049201'), **extra):
    """An invented album Item whose songs have these catalog ids."""
    play = {'kind': 'album', 'id': album_id}
    entries = [{'id': f'i.trk{number}', 'catalogId': song, 'title': f'Song {number}',
                'durationMs': 180000, 'index': number} for number, song in enumerate(songs)]
    data = {'id': album_id, 'kind': 'album', 'title': 'Invented Album',
            'subtitle': 'Invented Artist', 'catalogId': catalog_id, 'play': play,
            'groups': [{'name': '', 'play': play, 'entries': entries}] if entries else []}
    data.update(extra)
    return Item(data)


class AlbumTargetTest(unittest.TestCase):
    def test_a_catalog_album_by_its_id(self):
        self.assertEqual(album_target(album('1724049100')), ('1724049100', None))
        self.assertEqual(album_target(album('l.alb001', catalog_id='1724049100')),
                         ('1724049100', None))
        self.assertEqual(album_target(album('1724049100', songs=())), ('1724049100', None))

    def test_a_library_album_through_its_first_song_with_a_catalog_id(self):
        self.assertEqual(album_target(album()), ('l.alb001', '1724049201'))
        self.assertEqual(album_target(album(songs=('i.trk9', '1724049202'))),
                         ('l.alb001', '1724049202'))

    def test_none_to_ask(self):
        self.assertIsNone(album_target(album(songs=(None,))))  # no song to find it by
        self.assertIsNone(album_target(album(songs=())))
        self.assertIsNone(album_target(album('l.alb_0123456789ab')))  # loose songs' stand-in
        self.assertIsNone(album_target(Item({'id': 'p.1', 'kind': 'playlist'})))
        self.assertIsNone(album_target(None))


class FooterTest(unittest.TestCase):
    def test_the_release_date_in_full(self):
        self.assertEqual(release_date_text('2026-09-24'), '24 September 2026')
        self.assertEqual(release_date_text('1999'), '1999')
        for text in ('', None, 'soon', '2026-13-40', '2026-09'):
            self.assertEqual(release_date_text(text), '', text)

    def test_the_length_in_words(self):
        self.assertEqual(length_text(12, 43 * 60000), '12 songs, 43 minutes')
        self.assertEqual(length_text(1, 61 * 60000), '1 song, 1 hour, 1 minute')
        self.assertEqual(length_text(20, 120 * 60000), '20 songs, 2 hours')
        self.assertEqual(length_text(1, 20000), '1 song, 1 minute')  # at least a minute
        self.assertEqual(length_text(3), '3 songs')
        self.assertEqual(length_text(3, 0), '3 songs')

    def test_the_lines_from_the_answer(self):
        answer = {'release': {'releaseDate': '2026-03-14',
                              'copyright': '℗ 2026 Invented Records Ltd',
                              'recordLabel': 'Invented Records'}}
        self.assertEqual(footer_lines(album(), answer, 12, 43 * 60000),
                         ['14 March 2026', '12 songs, 43 minutes', '℗ 2026 Invented Records Ltd'])
        # The label where Apple has no copyright line.
        label = {'release': {'recordLabel': 'Invented Records'}}
        self.assertEqual(footer_lines(album(), label, 2, 0), ['2 songs', 'Invented Records'])

    def test_the_lines_without_an_answer(self):
        # What the Item carries (an artist page's release has its date), and the counts.
        self.assertEqual(footer_lines(album(releaseDate='2026-09-24'), None, 2, 360000),
                         ['24 September 2026', '2 songs, 6 minutes'])
        self.assertEqual(footer_lines(album(), {}, 2, 360000), ['2 songs, 6 minutes'])
        self.assertEqual(footer_lines(album(), None, 0, 0), [])


class ShelvesTest(unittest.TestCase):
    def answer(self):
        def entry(number, kind='album'):
            return {'id': f'17240491{number:02d}', 'kind': kind, 'title': f'Invented {number}',
                    'subtitle': '2026', 'art': None, 'thumb': None, 'groups': [],
                    'play': {'kind': kind, 'id': f'17240491{number:02d}'}}
        return {'id': '1724049100', 'artistId': '1724049001', 'artistName': 'Paper Parachutes',
                'shelves': [
                    {'key': 'other-versions', 'title': 'Other Versions', 'more': False,
                     'items': [entry(50)]},
                    {'key': 'related-videos', 'title': '', 'more': False,
                     'items': [entry(60, 'video')]},
                    {'key': 'more-by-artist', 'title': '', 'more': True,
                     'items': [entry(10), entry(11)]},
                    {'key': 'appears-on', 'title': 'Featured On', 'more': False, 'items': []},
                    {'key': 'related-albums', 'title': 'You Might Also Like', 'more': False,
                     'items': [{'id': '', 'kind': 'album'}, entry(30)]},
                ]}

    def test_titled_in_order_the_empty_left_out(self):
        shelves = album_shelves(self.answer(), 'Invented Artist')
        self.assertEqual([(shelf.key, shelf.title, shelf.more) for shelf in shelves], [
            ('other-versions', 'Other Versions', False),
            ('related-videos', 'Music Videos', False),  # Apple gave no title
            ('more-by-artist', 'More By Invented Artist', True),
            ('related-albums', 'You Might Also Like', False)])
        self.assertEqual([item.id for item in shelves[3].items], ['1724049130'])

    def test_more_by_names_the_answers_artist_without_one(self):
        shelves = album_shelves(self.answer())
        self.assertEqual(shelves[2].title, 'More By Paper Parachutes')
        self.assertEqual(shelf_title('more-by-artist', '', ''), 'More By the Artist')
        self.assertEqual(album_shelves(None), [])


if __name__ == '__main__':
    unittest.main()
