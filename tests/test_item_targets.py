# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What each item action takes of an object (applemusic.item_targets)."""

import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import item_targets
from applemusic.item_targets import (library_target, new_playlist_tracks, playlist_song,
                                     playlist_track, queue_target, queue_targets, rating_target)
from applemusic.library import ItemRefs, Ref, track_ref
from applemusic.web_links import web_url
from tests.item_actions_harness import (CATALOG_ALBUM, CATALOG_ARTIST, CATALOG_SONG, CATALOG_VIDEO,
                                        FAVOURITES, FOLDER, LIBRARY_ALBUM, LIBRARY_TRACK,
                                        MADE_UP_ALBUM, PLAYLIST, STATION, UPLOAD_TRACK, VIDEO_TRACK)


class TargetsTest(unittest.TestCase):
    """What each action takes of an object (item_targets): the targets it is
    queued, rated, added and removed by, and what a drag of it queues or
    makes a playlist of."""

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

    def test_track_ref(self):
        self.assertEqual(track_ref(LIBRARY_TRACK), Ref('song', 'i.song1', 'Harbour Lights', 2))
        self.assertEqual(track_ref(CATALOG_SONG).id, '1000000007')
        self.assertEqual(track_ref(VIDEO_TRACK).kind, 'video')
        self.assertEqual(track_ref(CATALOG_VIDEO).kind, 'video')
        self.assertIsNone(track_ref(LIBRARY_ALBUM))

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

    def test_new_playlist_tracks(self):
        self.assertEqual(new_playlist_tracks(ItemRefs.for_objects([LIBRARY_TRACK, CATALOG_SONG,
                                                                   VIDEO_TRACK])),
                         [('song', 'i.song1'), ('song', '1000000007'), ('video', 'i.vid1')])
        self.assertIsNone(new_playlist_tracks(ItemRefs.for_objects([PLAYLIST])))
        self.assertIsNone(new_playlist_tracks(ItemRefs.for_objects([LIBRARY_TRACK, PLAYLIST])))
        self.assertIsNone(new_playlist_tracks(None))

    def test_runs_of_songs_are_one_command(self):
        commands = item_targets.queue_commands([
            ('song', '1'), ('song', '2'), ('musicVideo', 'v1'), ('song', '3'),
            ('album', 'a1'), ('song', '4'), ('song', '5'), ('song', '6')])
        self.assertEqual(commands, [('songs', '1,2'), ('musicVideo', 'v1'), ('song', '3'),
                                    ('album', 'a1'), ('songs', '4,5,6')])
        self.assertEqual(item_targets.queued_count(commands), 8)
        with mock.patch.object(item_targets, 'QUEUE_BATCH', 2):
            self.assertEqual(item_targets.queue_commands([('song', str(n)) for n in range(5)]),
                             [('songs', '0,1'), ('songs', '2,3'), ('song', '4')])
        self.assertEqual(item_targets.queue_commands([]), [])


if __name__ == '__main__':
    unittest.main()
