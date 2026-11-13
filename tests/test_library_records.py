# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""TrackRecord (library/records.py): a track of library.json kept as a tuple that reads as
its dict."""

import tempfile
import unittest
from pathlib import Path

from tests.test_library import album, build_songs, load, track, write_library

from applemusic.library import Track, TrackRecord


class TestTrackRecord(unittest.TestCase):
    """A track dict kept as a tuple: it reads as the dict did."""

    def test_reads_as_the_dict(self):
        entry = dict(track('i.1', 'Song', 4), catalogId='1440833098', extra=[1, 2])
        del entry['thumb']
        record = TrackRecord(entry)
        for key, value in entry.items():
            with self.subTest(key=key):
                self.assertEqual(record.get(key), value)
                self.assertEqual(record[key], value)
                self.assertIn(key, record)
        self.assertEqual(record.get('catalogId'), '1440833098')  # kept as an int, read as text
        self.assertIsNone(record.get('thumb'))  # absent, as from the dict
        self.assertEqual(record.get('thumb', 'x'), 'x')
        self.assertEqual(record.get('nothing', 7), 7)
        self.assertNotIn('thumb', record)
        with self.assertRaises(KeyError):
            record['thumb']  # noqa: B018
        self.assertEqual(dict(record), entry)
        self.assertEqual(sorted(record.keys()), sorted(entry))

    def test_catalog_ids_that_are_not_plain_numbers_stay_text(self):
        for value in ('0123', '12a', '', '١٢٣', None, 42):
            with self.subTest(value=value):
                self.assertEqual(TrackRecord({'catalogId': value}).get('catalogId'), value)

    def test_equal_when_the_dicts_are(self):
        one = track('i.1', 'Song', 0)
        self.assertEqual(TrackRecord(one), TrackRecord(dict(one)))
        self.assertNotEqual(TrackRecord(one), TrackRecord(dict(one, title='Other')))
        self.assertNotEqual(TrackRecord(one), TrackRecord(dict(one, other=1)))
        without = dict(one)
        del without['thumb']
        self.assertNotEqual(TrackRecord(one), TrackRecord(without))  # null is not absent

    def test_a_track_reads_it_as_the_dict(self):
        entry = dict(track('i.1', 'Song', 4), catalogId=123, explicit=True, type='songs',
                     genre='Shoegaze', year=2019)
        over_dict, over_record = Track(entry), Track(TrackRecord(entry))
        for name in ('id', 'catalog-id', 'title', 'artist', 'album', 'track-number',
                     'disc-number', 'duration-ms', 'duration-label', 'explicit', 'index',
                     'kind', 'thumb', 'genre', 'year'):
            with self.subTest(name=name):
                self.assertEqual(over_record.get_property(name), over_dict.get_property(name))
        self.assertEqual(over_record.search_key, over_dict.search_key)

    def test_the_parse_keeps_records(self):
        with tempfile.TemporaryDirectory() as cache:
            write_library(cache, [album('l.a1', 'A1', ['i.1', 'i.2'])],
                          playlists=[dict(album('p.1', 'P', ['i.3']), kind='playlist')])
            Path(cache, 'library.json').write_text(
                Path(cache, 'library.json').read_text(encoding='utf-8').replace(
                    '"sections": {', '"sections": {"songs": [{"id": "i.9", "title": "L"}], '),
                encoding='utf-8')
            library = load(cache)
        album_item, playlist_item = library.albums.get_item(0), library.playlists.get_item(0)
        for item in (album_item, playlist_item):
            self.assertTrue(all(isinstance(entry, TrackRecord)
                                for entry in item.raw['groups'][0]['entries']))
        self.assertIsInstance(library._loose[0], TrackRecord)
        self.assertEqual([t.id for t in build_songs(library)], ['i.1', 'i.2', 'i.9'])
        self.assertEqual(library.song_count(), 3)


if __name__ == '__main__':
    unittest.main()
