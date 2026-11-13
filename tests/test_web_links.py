# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The music.apple.com addresses of items (applemusic.web_links)."""

import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic.library import Item
from applemusic.web_links import (drag_link, drag_links, is_apple_music_url, is_shareable,
                                  share_url, web_url)
from tests.item_actions_harness import (CATALOG_ALBUM, CATALOG_ARTIST, CATALOG_TRACK, FOLDER,
                                        LIBRARY_ALBUM, LIBRARY_ARTIST, LIBRARY_TRACK, MADE_UP_ALBUM,
                                        PLAYLIST, STATION, UPLOAD_TRACK, VIDEO_TRACK)


class WebLinksTest(unittest.TestCase):
    """An item's music.apple.com addresses (web_links): the page opened, the
    link copied, the links a drag offers."""

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

    def test_drag_links(self):
        # What a drag offers other applications: the addresses anyone can open.
        self.assertEqual(drag_link(CATALOG_ALBUM), CATALOG_ALBUM.url)
        self.assertEqual(drag_link(STATION), STATION.url)
        self.assertEqual(drag_link(LIBRARY_TRACK, 'gb'),
                         'https://music.apple.com/gb/song/1000000001')
        self.assertEqual(drag_link(VIDEO_TRACK, 'gb'),
                         'https://music.apple.com/gb/music-video/1000000011')
        # A library album by its catalog id, which Copy Link would ask the engine for.
        catalogued = Item({'id': 'l.alb2', 'kind': 'album', 'title': 'Tidewater',
                           'catalogId': '1000000020'})
        self.assertEqual(drag_link(catalogued, 'gb'),
                         'https://music.apple.com/gb/album/1000000020')
        self.assertEqual(drag_link(catalogued), 'https://music.apple.com/us/album/1000000020')
        for obj in (LIBRARY_ALBUM, MADE_UP_ALBUM, PLAYLIST, UPLOAD_TRACK, LIBRARY_ARTIST,
                    FOLDER, None):
            with self.subTest(obj=obj):
                self.assertIsNone(drag_link(obj))
        # Several: in order, each once, those without an address left out.
        self.assertEqual(drag_links([LIBRARY_TRACK, UPLOAD_TRACK, CATALOG_TRACK, LIBRARY_TRACK],
                                    'gb'),
                         ['https://music.apple.com/gb/song/1000000001',
                          'https://music.apple.com/gb/song/1000000009'])
        self.assertEqual(drag_links([UPLOAD_TRACK, PLAYLIST]), [])
        self.assertEqual(drag_links([]), [])


if __name__ == '__main__':
    unittest.main()
