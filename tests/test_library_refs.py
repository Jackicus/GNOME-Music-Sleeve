# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What a drag carries (library/refs.py): Refs and ItemRefs."""

import unittest

from tests.test_library import playlist

from applemusic.library import Item, ItemRefs, Ref, Track, track_ref
from applemusic.library.refs import item_ref


class TestItemRefs(unittest.TestCase):
    """What a drag carries: library.ItemRefs of tracks and Items."""

    def test_refs_of_tracks_and_items(self):
        track = Track({'id': 'i.s1', 'catalogId': '100', 'title': 'Song', 'index': 4},
                      play={'kind': 'playlist', 'id': 'p.1'})
        video = Track({'id': '200', 'title': 'Clip', 'type': 'music-videos', 'index': 0})
        song = Item({'id': '300', 'kind': 'song', 'title': 'Single', 'catalogId': '300'})
        listed = playlist('p.2', 'List')
        box = Item({'id': 'p.f', 'kind': 'folder', 'title': 'Box'})
        album = Item({'id': 'l.a', 'kind': 'album', 'title': 'Album'})
        artist = Item({'id': 'l.art', 'kind': 'artist', 'title': 'Someone'})
        refs = ItemRefs.for_objects([track, video, song, listed, box, album, artist],
                                    origin=('playlist', 'p.1'))
        self.assertEqual(list(refs), [
            Ref('song', 'i.s1', 'Song', 4), Ref('video', '200', 'Clip', 0),
            Ref('song', '300', 'Single'), Ref('playlist', 'p.2', 'List'),
            Ref('folder', 'p.f', 'Box'), Ref('album', 'l.a', 'Album')])
        self.assertEqual(refs.origin, ('playlist', 'p.1'))
        # The objects named, in the refs' order, the artist left out with its ref.
        self.assertEqual(refs.objects, (track, video, song, listed, box, album))
        self.assertEqual(ItemRefs([Ref('song', 'x', 'X')]).objects, ())
        self.assertEqual([ref.id for ref in refs.tracks()], ['i.s1', '200', '300'])
        self.assertEqual([ref.id for ref in refs.containers()], ['p.2', 'p.f'])
        self.assertFalse(refs.only('song', 'video'))
        self.assertEqual(len(refs), 6)
        one = ItemRefs.for_objects([listed])
        self.assertTrue(one.only('playlist', 'folder'))
        self.assertIsNone(one.origin)
        self.assertIsNone(ItemRefs.for_objects([artist, Track({'title': 'No id'})]))
        self.assertIsNone(ItemRefs.for_objects([]))

    def test_track_ref_is_what_add_to_playlist_takes(self):
        track = Track({'id': '', 'catalogId': '100', 'title': 'Catalog Only', 'index': 1})
        self.assertEqual(track_ref(track), Ref('song', '100', 'Catalog Only', 1))
        self.assertIsNone(track_ref(playlist('p.1')))
        self.assertEqual(item_ref(playlist('p.1')), Ref('playlist', 'p.1', 'p.1'))


if __name__ == '__main__':
    unittest.main()
