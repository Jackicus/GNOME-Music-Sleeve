# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The model's own words (library/words.py): counts, shelf titles and missing names, through
gettext."""

import tempfile
import unittest
from unittest import mock

from tests.test_library import album, load, track, write_library

from applemusic.library import Item
from applemusic.library import words as words_module


class TestWords(unittest.TestCase):
    """The model's own words: counts, shelf titles and missing names, through gettext."""

    def setUp(self):
        words_module._unknown_titles.clear()
        self.addCleanup(words_module._unknown_titles.clear)

    def translated(self):
        """gettext and ngettext patched to mark what they return, and count their calls."""
        calls = []

        def gettext(text):
            calls.append(text)
            return f'<{text}>'

        def ngettext(one, many, count):
            calls.append(one)
            return f'<{one if count == 1 else many}>'

        for name, function in (('_', gettext), ('ngettext', ngettext)):
            patcher = mock.patch.object(words_module, name, function)
            patcher.start()
            self.addCleanup(patcher.stop)
        return calls

    def count(self, **raw):
        return Item(raw).count_label

    def test_songs_and_their_time(self):
        for track_count, duration, text in (
                (12, 43 * 60000, '12 songs, 43 min'),
                (1, 180000, '1 song, 3 min'),
                (15, 65 * 60000, '15 songs, 1 hr 5 min'),
                (20, 120 * 60000, '20 songs, 2 hr'),
                (1, 20000, '1 song, 1 min'),  # any time at all is a minute
                (3, 0, '3 songs, 0 min'),
                (12, None, '12 songs'),  # a shelf's album: no tracks, so no time
                (0, None, '0 songs')):
            for kind in ('album', 'playlist'):
                with self.subTest(kind=kind, tracks=track_count, ms=duration):
                    self.assertEqual(self.count(kind=kind, trackCount=track_count,
                                                durationMs=duration), text)

    def test_albums_of_an_artist(self):
        self.assertEqual(self.count(kind='artist', albumCount=1), '1 album')
        self.assertEqual(self.count(kind='artist', albumCount=3), '3 albums')

    def test_a_library_from_before_the_counts(self):
        # Its English caption is shown as it is; the numbers win when both are there.
        self.assertEqual(self.count(kind='album', countLabel='10 songs, 44 min'),
                         '10 songs, 44 min')
        self.assertEqual(self.count(kind='station', countLabel='Radio Station'), 'Radio Station')
        self.assertEqual(self.count(kind='album', countLabel='9 songs', trackCount=10), '10 songs')

    def test_else_the_groups_count(self):
        play = {'kind': 'album', 'id': 'l.a'}
        groups = [{'name': 'Disc 1', 'play': play,
                   'entries': [track('i.1', 'One', 0), track('i.2', 'Two', 1)]}]
        self.assertEqual(self.count(kind='album', groups=groups), '2 songs, 6 min')
        self.assertEqual(self.count(kind='artist', groups=groups * 2), '2 albums')
        self.assertEqual(self.count(kind='album', groups=[]), '')
        self.assertEqual(self.count(kind='station'), '')
        self.assertEqual(self.count(kind='album', trackCount=True, countLabel=None), '')

    def test_through_gettext_once(self):
        calls = self.translated()
        item = Item({'kind': 'album', 'trackCount': 12, 'durationMs': 43 * 60000})
        self.assertEqual(item.count_label, '<<12 songs>, <43 min>>')
        self.assertEqual(item.get_property('count-label'), '<<12 songs>, <43 min>>')
        self.assertEqual(len(calls), 3)  # made once, then kept
        self.assertEqual(self.count(kind='artist', albumCount=2), '<2 albums>')

    def test_a_merge_tells_a_new_count(self):
        item = Item({'kind': 'playlist', 'id': 'p.1', 'trackCount': 2, 'durationMs': 360000})
        self.assertEqual(item.count_label, '2 songs, 6 min')
        seen = []
        item.connect('notify::count-label', lambda obj, _pspec: seen.append(obj.count_label))
        item.merge({'kind': 'playlist', 'id': 'p.1', 'trackCount': 2, 'durationMs': 360000,
                    'title': 'Renamed'}, replace=True)
        self.assertEqual(seen, [])
        item.merge({'trackCount': 3, 'durationMs': 540000})
        self.assertEqual(seen, ['3 songs, 9 min'])

    def test_shelf_titles(self):
        self.assertEqual(words_module.shelf_title('heavy-rotation', 'X'), 'Heavy Rotation')
        self.assertEqual(words_module.shelf_title('recently-added', None), 'Recently Added')
        self.assertEqual(words_module.shelf_title('rec-1', 'Chill Mornings'), 'Chill Mornings')
        self.assertEqual(words_module.shelf_title('rec-2', ''), 'For You')
        self.translated()
        self.assertEqual(words_module.shelf_title('heavy-rotation', 'X'), '<Heavy Rotation>')
        self.assertEqual(words_module.shelf_title('rec-2', None), '<For You>')
        with tempfile.TemporaryDirectory() as cache:
            write_library(cache, [album('l.a1', 'A1', [])], shelves=[
                {'key': 'heavy-rotation', 'title': 'X', 'items': []},
                {'key': 'rec-9', 'title': '', 'items': []}])
            library = load(cache)
        self.assertEqual([shelf.title for shelf in library.shelves],
                         ['<Heavy Rotation>', '<For You>'])

    def test_unknown_titles(self):
        calls = self.translated()
        artist = Item({'kind': 'artist', 'title': ''})
        self.assertEqual(artist.title, '<Unknown Artist>')
        self.assertEqual(Item({'kind': 'artist'}).title, '<Unknown Artist>')
        self.assertEqual(calls, ['Unknown Artist'])  # looked up once
        self.assertEqual(Item({'kind': 'album', 'title': None}).title, '<Unknown Album>')
        self.assertEqual(Item({'kind': 'playlist', 'title': ''}).title, '')
        self.assertEqual(Item({'kind': 'album', 'title': 'Named'}).title, 'Named')
        artist.title = 'Set'
        self.assertEqual((artist.title, artist.raw['title']), ('Set', 'Set'))


if __name__ == '__main__':
    unittest.main()
