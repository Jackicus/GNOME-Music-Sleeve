# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Track (library/objects.py): its properties read from its raw entry."""

import unittest

from tests.test_library import album, track

from applemusic.library import Item, SongEntry, Track, TrackRecord, release_passed


class TestTrack(unittest.TestCase):
    def test_properties_read_the_raw_dict(self):
        raw = dict(track('i.1', 'Song', 4), catalogId=123, explicit=True, discNumber=None)
        entry = Track(raw, {'kind': 'album', 'id': 'l.a'}, thumb='/album.jpg')
        self.assertEqual((entry.id, entry.title, entry.artist, entry.album), (
            'i.1', 'Song', 'Test Artist', 'Test Album'))
        self.assertEqual(entry.catalog_id, '123')  # a number in a string property
        self.assertEqual((entry.index, entry.track_number, entry.disc_number), (4, 5, 0))
        self.assertTrue(entry.explicit)
        self.assertEqual(entry.get_property('duration-ms'), 180000)
        self.assertEqual(entry.thumb, '/album.jpg')  # its own is null: the album's
        self.assertEqual(Track({}).title, '')
        # A library.json from before version 5 has no genre or year: '' and 0.
        self.assertEqual((Track({}).genre, Track({}).year), ('', 0))
        self.assertEqual((Track({'genre': 'Nu-Jazz', 'year': 2021}).genre,
                          Track({'genre': 'Nu-Jazz', 'year': 2021}).year), ('Nu-Jazz', 2021))
        self.assertIsNone(Track({}).id)
        with self.assertRaises(TypeError):
            entry.set_property('title', 'Other')  # read-only: the dict is the truth

    def test_kind_by_the_api_type(self):
        for kind, types in (('song', ('songs', 'library-songs')),
                            ('video', ('music-videos', 'library-music-videos')),
                            ('', ('stations', 'uploaded-videos', None, 7, ['songs']))):
            for value in types:
                with self.subTest(type=value):
                    self.assertEqual(Track({'id': 'i.1', 'type': value}).kind, kind)
        self.assertEqual(Track({'id': 'i.1'}).kind, '')  # an entry without a type

    def test_a_track_not_out_yet(self):
        # A pre-release album's track not out yet, as a dict and as a TrackRecord.
        raw = dict(track('17240498', 'Song', 0), unreleased=True)
        self.assertTrue(Track(raw).unreleased)
        self.assertTrue(Track(TrackRecord(raw)).unreleased)
        self.assertFalse(Track(track('17240499', 'Song', 1)).unreleased)

    def test_release_passed(self):
        # Whether a release date has come, against an injected day (#606).
        today = '2026-11-13'
        for date, out in (('2026-11-12', True), ('2026-11-13', True), ('2026-11-14', False),
                          (' 2025-01-01 ', True), ('2025', True), ('2026', False),
                          ('2027', False), ('', False), (None, False), ('soon', False),
                          ('2026-11', False), (20261112, False)):
            with self.subTest(date=date):
                self.assertIs(release_passed(date, today), out)
        self.assertTrue(release_passed('2001-01-01'))  # against the local date
        self.assertFalse(release_passed('2999-01-01'))

    def test_a_prerelease_album_out_on_its_date(self):
        # A pre-release album whose date has passed since the sync: out, its songs too, the
        # Songs store's Track as well as the album's; the file's flags as they were.
        data = album('1724049800', 'Came Out', ['1724049801', '1724049802'])
        data.update(prerelease=True, releaseDate='2001-01-01')
        data['groups'][0]['entries'][1]['unreleased'] = True
        item = Item(data)
        self.assertFalse(item.prerelease)
        self.assertFalse(item.groups[0].entries.get_item(1).unreleased)
        self.assertIs(item.raw['prerelease'], True)
        entry = SongEntry(data['groups'][0]['entries'][1], (None, 0, item.play, None))
        self.assertTrue(entry.track().unreleased)  # a loose song: no album date to go by
        stale = SongEntry(dict(data['groups'][0]['entries'][1]), (item, 0, item.play, None))
        self.assertFalse(stale.track().unreleased)
        data = album('1724049810', 'To Come', ['1724049811'])
        data.update(prerelease=True, releaseDate='2999-01-01')
        data['groups'][0]['entries'][0]['unreleased'] = True
        item = Item(data)
        self.assertTrue(item.prerelease)
        self.assertTrue(item.groups[0].entries.get_item(0).unreleased)


if __name__ == '__main__':
    unittest.main()
