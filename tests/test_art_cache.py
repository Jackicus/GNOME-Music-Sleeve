# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The artwork cache's names, sizes, thumbnails and downloads (backend.art_cache)."""

import http.server
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import (
    art_cache,
    cache_files,
    config,
    normalize,
)

# The sizes these tests were written against (the extension's defaults). The
# app's own defaults come from config; TestArtSizes covers those.
UPSTREAM_SIZES = {'cover': 512, 'thumb': 256}

try:
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
except (ImportError, ValueError):  # pragma: no cover - depends on the system
    GdkPixbuf = None


def pixbuf_scaler(src_path, dest_path, width, height):
    """An art_cache.scale_image, as the app installs one."""
    scaled = GdkPixbuf.Pixbuf.new_from_file_at_scale(src_path, width, height, True)
    scaled.savev(dest_path, 'jpeg', ['quality'], ['90'])


class TestArtworkUrl(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_artwork_url_and_path(self):
        art_obj = {'url': 'https://example.com/art/{w}x{h}bb.{f}', 'bgColor': '222222'}
        formatted_url = art_cache.format_artwork_url(art_obj, 512, 512)
        self.assertEqual(formatted_url, 'https://example.com/art/512x512bb.jpg')

        path = art_cache.artwork_cache_path(formatted_url, self.tmp_dir)
        self.assertTrue(path.endswith('.jpg'))
        self.assertTrue(path.startswith(os.path.join(self.tmp_dir, 'art')))


class TestArtworkDownload(unittest.TestCase):
    """Normalisation names the file; download_art fetches what is missing."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.art_urls = {}
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def _album(self, art_url):
        return {
            'id': 'l.one', 'type': 'library-albums',
            'attributes': {'name': 'One', 'artistName': 'A', 'artwork': {'url': art_url}},
        }

    def album(self, art_url, **changes):
        """An album normalised with this test's registry."""
        return normalize.normalize_album(dict(self._album(art_url), **changes),
                                         cache_dir=self.tmp_dir, art_urls=self.art_urls)

    def test_extract_registers_url_for_path(self):
        item = self.album('https://x/{w}x{h}bb.jpg')
        self.assertTrue(item['art'].startswith(os.path.join(self.tmp_dir, 'art')))
        self.assertEqual(self.art_urls[item['art']], 'https://x/512x512bb.jpg')
        self.assertTrue(item['thumb'].startswith(os.path.join(self.tmp_dir, 'thumb')))
        self.assertEqual(self.art_urls[item['thumb']], 'https://x/256x256bb.jpg')
        self.assertEqual(os.path.basename(item['thumb']), os.path.basename(item['art']))

    def video(self, art_url):
        """A library music video normalised with this test's registry."""
        return normalize.normalize_item(
            {'id': 'i.v1', 'type': 'library-music-videos',
             'attributes': {'name': 'V', 'artistName': 'A', 'artwork': {'url': art_url}}},
            cache_dir=self.tmp_dir, art_urls=self.art_urls)

    def test_a_videos_thumbnail_is_wide(self):
        # #383: a music video's thumbnail is asked by its shorter edge, the thumbnail size
        # high, and kept under a name of its own, so a square-boxed one is fetched again.
        item = self.video('https://x/{w}x{h}bb.jpg')
        self.assertEqual(self.art_urls[item['art']], 'https://x/512x512bb.jpg')
        self.assertEqual(self.art_urls[item['thumb']], 'https://x/455x256bb.jpg')
        album = self.album('https://x/{w}x{h}bb.jpg')
        self.assertEqual(item['art'], album['art'])  # the same cover
        self.assertNotEqual(item['thumb'], album['thumb'])
        self.assertTrue(item['thumb'].endswith('-wide.jpg'))
        self.assertTrue(art_cache.is_wide_thumb(item['thumb']))
        self.assertFalse(art_cache.is_wide_thumb(album['thumb']))
        self.assertEqual(art_cache.cover_of_thumb(item['thumb'], self.tmp_dir), item['art'])
        self.assertEqual(art_cache.cover_of_thumb(album['thumb'], self.tmp_dir), album['art'])
        # A video in a playlist's rows keeps the square box: a row draws a square.
        track = normalize.normalize_track(
            {'id': 'i.v1', 'type': 'library-music-videos',
             'attributes': {'name': 'V', 'artwork': {'url': 'https://x/{w}x{h}bb.jpg'}}},
            cache_dir=self.tmp_dir, art_urls=self.art_urls)
        self.assertEqual(track['thumb'], album['thumb'])

    def test_thumb_box_and_wide_art(self):
        self.assertEqual(art_cache.thumb_box(320), (320, 320))
        self.assertEqual(art_cache.thumb_box(320, wide=True), (569, 320))
        self.assertTrue(art_cache.wide_art({'kind': 'video'}))
        self.assertTrue(art_cache.wide_art({'kind': 'link', 'video': True}))
        for item in ({'kind': 'link'}, {'kind': 'album'}, {'kind': 'link', 'video': 'yes'},
                     None, []):
            self.assertFalse(art_cache.wide_art(item), item)

    def test_the_registry_is_the_callers(self):
        self.assertFalse(hasattr(normalize, 'ART_URLS'))  # no state kept between calls
        first, second = {}, {}
        album = normalize.normalize_album(self._album('https://x/{w}x{h}bb.jpg'),
                                          cache_dir=self.tmp_dir, art_urls=first)
        normalize.normalize_album(self._album('https://y/{w}x{h}bb.jpg'),
                                  cache_dir=self.tmp_dir, art_urls=second)
        self.assertEqual(set(first), {album['art'], album['thumb']})
        self.assertNotIn(album['art'], second)
        # Without one, the paths are named all the same.
        again = normalize.normalize_album(self._album('https://x/{w}x{h}bb.jpg'),
                                          cache_dir=self.tmp_dir)
        self.assertEqual((again['art'], again['thumb']), (album['art'], album['thumb']))
        library = {'sections': {'albums': [album]}, 'shelves': []}
        self.assertEqual(art_cache.collect_art_urls(library, first), first)
        self.assertEqual(art_cache.collect_art_urls(library, second), {})

    def test_download_art_fetches_only_missing(self):
        item = self.album('https://x/{w}x{h}bb.jpg')
        other = self.album('https://y/{w}x{h}bb.jpg', id='l.two')
        os.makedirs(os.path.dirname(other['art']), exist_ok=True)
        with open(other['art'], 'wb') as f:
            f.write(b'already here')
        lib = {'sections': {'albums': [item, other]}, 'shelves': []}

        fetched = []

        def fake_cache(url, cache_dir, timeout=10.0, dest_path=None, generation=None):
            fetched.append(url)
            path = dest_path or art_cache.artwork_cache_path(url, cache_dir)
            with open(path, 'wb') as f:
                f.write(b'img')
            return path

        def fake_thumb(url, cache_dir, dest_path, generation=None):
            fetched.append(url)
            with open(dest_path, 'wb') as f:
                f.write(b'img')
            return dest_path

        real = art_cache.cache_artwork, art_cache.cache_thumbnail
        art_cache.cache_artwork, art_cache.cache_thumbnail = fake_cache, fake_thumb
        try:
            counts = art_cache.download_art(art_cache.collect_art_urls(lib, self.art_urls),
                                            self.tmp_dir)
        finally:
            art_cache.cache_artwork, art_cache.cache_thumbnail = real
        # The one missing cover, then the thumbnails of both, in that order.
        self.assertEqual(fetched[0], 'https://x/512x512bb.jpg')
        self.assertEqual(sorted(fetched[1:]),
                         ['https://x/256x256bb.jpg', 'https://y/256x256bb.jpg'])
        self.assertEqual(counts, {'wanted': 4, 'fetched': 3, 'failed': 0})
        self.assertTrue(os.path.exists(item['art']))
        self.assertTrue(os.path.exists(item['thumb']))

    def test_download_art_counts_failures(self):
        self.album('https://x/{w}x{h}bb.jpg')
        real = art_cache.cache_artwork, art_cache.cache_thumbnail
        art_cache.cache_artwork = lambda url, cache_dir, **kwargs: None

        def broken(url, cache_dir, dest_path, generation=None):
            raise OSError('no space left')
        art_cache.cache_thumbnail = broken
        try:
            with self.assertLogs('applemusic.backend.art_cache', 'WARNING') as logs:
                counts = art_cache.download_art(self.art_urls, self.tmp_dir)
        finally:
            art_cache.cache_artwork, art_cache.cache_thumbnail = real
        # The cover and its thumbnail; the one that raised is logged with its reason (the one
        # that answered None logs its own).
        self.assertEqual(counts['failed'], 2)
        self.assertEqual(len(logs.output), 1)
        self.assertIn('no space left', logs.output[0])

    def test_a_cancelled_download_says_so(self):
        self.album('https://x/{w}x{h}bb.jpg')
        urls = self.art_urls
        fetched = []
        real = art_cache.cache_artwork, art_cache.cache_thumbnail
        art_cache.cache_artwork = lambda url, cache_dir, **kwargs: fetched.append(url)
        art_cache.cache_thumbnail = lambda url, cache_dir, dest, **kwargs: fetched.append(url)
        try:
            with self.assertRaises(art_cache.Cancelled):
                art_cache.download_art(urls, self.tmp_dir, cancelled=lambda: True)
            self.assertEqual(fetched, [])  # nothing started
            # Cancelled while the covers come in: the thumbnails are never started.
            asked = []

            def cancelled():
                asked.append(True)
                return len(asked) > 1
            with self.assertRaises(art_cache.Cancelled):
                art_cache.download_art(urls, self.tmp_dir, cancelled=cancelled)
            self.assertEqual(fetched, ['https://x/512x512bb.jpg'])
        finally:
            art_cache.cache_artwork, art_cache.cache_thumbnail = real

    @unittest.skipIf(GdkPixbuf is None, 'GdkPixbuf not available')
    def test_thumbnail_is_scaled_from_the_cached_cover(self):
        self.addCleanup(setattr, art_cache, 'scale_image', art_cache.scale_image)
        art_cache.scale_image = pixbuf_scaler
        item = self.album('https://x/{w}x{h}bb.jpg')
        os.makedirs(os.path.dirname(item['art']), exist_ok=True)
        cover = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 512, 512)
        cover.fill(0x336699ff)
        cover.savev(item['art'], 'jpeg', ['quality'], ['80'])
        # Nothing is fetched: the cover is on disk.
        real = art_cache.cache_artwork
        art_cache.cache_artwork = lambda *a, **k: self.fail('fetched a thumbnail it could scale')
        try:
            counts = art_cache.download_art({item['thumb']: self.art_urls[item['thumb']]},
                                            self.tmp_dir)
        finally:
            art_cache.cache_artwork = real
        self.assertEqual(counts, {'wanted': 1, 'fetched': 1, 'failed': 0})
        thumb = GdkPixbuf.Pixbuf.new_from_file(item['thumb'])
        self.assertEqual((thumb.get_width(), thumb.get_height()),
                         (art_cache.ART_SIZES['thumb'], art_cache.ART_SIZES['thumb']))

    @unittest.skipIf(GdkPixbuf is None, 'GdkPixbuf not available')
    def test_a_wide_thumbnail_is_scaled_from_the_cover_by_its_shorter_edge(self):
        self.addCleanup(setattr, art_cache, 'scale_image', art_cache.scale_image)
        art_cache.scale_image = pixbuf_scaler
        item = self.video('https://x/{w}x{h}bb.jpg')
        os.makedirs(os.path.dirname(item['art']), exist_ok=True)
        cover = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 512, 288)
        cover.fill(0x336699ff)
        cover.savev(item['art'], 'jpeg', ['quality'], ['80'])
        real = art_cache.cache_artwork
        art_cache.cache_artwork = lambda *a, **k: self.fail('fetched a thumbnail it could scale')
        try:
            counts = art_cache.download_art({item['thumb']: self.art_urls[item['thumb']]},
                                            self.tmp_dir)
        finally:
            art_cache.cache_artwork = real
        self.assertEqual(counts, {'wanted': 1, 'fetched': 1, 'failed': 0})
        thumb = GdkPixbuf.Pixbuf.new_from_file(item['thumb'])
        # 256 px high (UPSTREAM_SIZES' thumbnail), not 256 px wide.
        self.assertEqual((thumb.get_width(), thumb.get_height()), (455, 256))

    def test_thumbnail_is_fetched_without_a_scaler(self):
        # The backend imports no gi: with no scale_image installed, a cover on
        # disk does not help, and the thumbnail is fetched at its own size.
        self.addCleanup(setattr, art_cache, 'scale_image', art_cache.scale_image)
        art_cache.scale_image = None
        item = self.album('https://x/{w}x{h}bb.jpg')
        os.makedirs(os.path.dirname(item['art']), exist_ok=True)
        with open(item['art'], 'wb') as f:
            f.write(b'a cover')
        self.assertFalse(art_cache.make_thumbnail(item['art'], item['thumb'], self.tmp_dir))
        fetched = []
        real = art_cache.cache_artwork
        def fake_cache_artwork(url, cache_dir, dest_path=None, generation=None):
            fetched.append((url, dest_path))
            return dest_path
        art_cache.cache_artwork = fake_cache_artwork
        try:
            self.assertEqual(art_cache.cache_thumbnail(self.art_urls[item['thumb']],
                                                       self.tmp_dir, item['thumb']), item['thumb'])
        finally:
            art_cache.cache_artwork = real
        self.assertEqual(fetched, [('https://x/256x256bb.jpg', item['thumb'])])

    def test_download_item_art_takes_the_rows_thumbnails_too(self):
        raw = {'id': 'p.one', 'type': 'library-playlists',
               'attributes': {'name': 'Mix', 'artwork': {'url': 'https://p/{w}x{h}bb.jpg'}}}
        tracks = [{'id': 'i.1',
                   'attributes': {'name': 'A', 'artwork': {'url': 'https://a/{w}x{h}bb.jpg'}}},
                  {'id': 'i.2',
                   'attributes': {'name': 'B', 'artwork': {'url': 'https://b/{w}x{h}bb.jpg'}}}]
        item = normalize.normalize_playlist(raw, cache_dir=self.tmp_dir, tracks=tracks,
                                            art_urls=self.art_urls)
        asked = []
        real = art_cache.download_art
        art_cache.download_art = lambda urls, cache_dir, **k: asked.append(sorted(urls.values()))
        try:
            art_cache.download_item_art(item, self.tmp_dir, self.art_urls)
            art_cache.download_item_art(item, self.tmp_dir, {})  # a registry without them
        finally:
            art_cache.download_art = real
        self.assertEqual(asked, [[
            'https://a/256x256bb.jpg', 'https://b/256x256bb.jpg',
            'https://p/256x256bb.jpg', 'https://p/512x512bb.jpg',
        ], []])

    def test_album_stub_without_attributes_takes_song_name(self):
        songs = [{
            'id': 'i.1', 'type': 'library-songs',
            'attributes': {
                'name': 'First Light', 'albumName': 'Collected Postcards',
                'artistName': 'Isla Marren',
                'trackNumber': 1, 'discNumber': 1, 'durationInMillis': 1000,
                'artwork': {'url': 'https://x/{w}x{h}bb.jpg'},
            },
            'relationships': {'albums': {'data': [{'id': 'l.gone', 'type': 'library-albums'}]}},
        }]
        albums, artists = normalize.group_songs_into_albums_and_artists(songs, self.tmp_dir)
        self.assertEqual(albums[0]['id'], 'l.gone')
        self.assertEqual(albums[0]['title'], 'Collected Postcards')
        self.assertEqual(albums[0]['subtitle'], 'Isla Marren')
        self.assertIsNotNone(albums[0]['art'])
        self.assertEqual(artists[0]['title'], 'Isla Marren')


class CannedHandler(http.server.BaseHTTPRequestHandler):
    """Answers /ok.jpg with a few bytes and anything else with 404."""

    def do_GET(self):
        if self.path == '/ok.jpg':
            body = b'not really a jpeg'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class TestCacheArtwork(unittest.TestCase):
    """cache_artwork against a server on the loopback interface."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), CannedHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        # No proxy between this test and its server.
        patcher = mock.patch.dict(os.environ, {'no_proxy': '*', 'NO_PROXY': '*'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self):
        return sorted(os.path.relpath(os.path.join(folder, name), self.tmp_dir)
                      for folder, _dirs, names in os.walk(self.tmp_dir) for name in names)

    def test_a_download_lands_under_the_urls_name(self):
        url = f'{self.base}/ok.jpg'
        path = art_cache.cache_artwork(url, self.tmp_dir)
        self.assertEqual(path, art_cache.artwork_cache_path(url, self.tmp_dir))
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), b'not really a jpeg')
        self.assertEqual(self.files(), [os.path.join('art', art_cache.artwork_filename(url))])

    def test_a_404_is_none_logged_with_its_reason_and_leaves_nothing(self):
        with self.assertLogs('applemusic.backend.art_cache', 'WARNING') as logs:
            self.assertIsNone(art_cache.cache_artwork(f'{self.base}/missing.jpg', self.tmp_dir))
        self.assertIn('404', logs.output[0])
        self.assertEqual(self.files(), [])  # no temp file left


class TestArtSizes(unittest.TestCase):
    """The cover and thumbnail sizes: set per sync, recorded beside the
    covers, read back by every other command."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_defaults_without_a_marker(self):
        self.assertEqual(art_cache.load_art_sizes(self.tmp_dir),
                         {'cover': config.COVER_SIZE, 'thumb': config.THUMB_SIZE})

    def test_apply_writes_the_marker_and_clamps(self):
        self.assertEqual(art_cache.apply_art_sizes(self.tmp_dir, 768, 128),
                         {'cover': 768, 'thumb': 128})
        with open(os.path.join(self.tmp_dir, 'art', '.sizes')) as f:
            self.assertEqual(json.load(f), {'cover': 768, 'thumb': 128})
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)
        self.assertEqual(art_cache.load_art_sizes(self.tmp_dir), {'cover': 768, 'thumb': 128})
        self.assertEqual(art_cache.ART_SIZES, {'cover': 768, 'thumb': 128})
        # Out of range, or not a number: the nearest sane size, or the one standing.
        self.assertEqual(art_cache.apply_art_sizes(self.tmp_dir, 9000, 10),
                         {'cover': 1024, 'thumb': 96})
        self.assertEqual(art_cache.apply_art_sizes(self.tmp_dir, 'x', None),
                         {'cover': 1024, 'thumb': 96})

    def test_sizes_name_the_urls(self):
        art_cache.apply_art_sizes(self.tmp_dir, 640, 192)
        art_urls = {}
        item = normalize.normalize_album({'id': 'l.one', 'type': 'library-albums', 'attributes': {
            'name': 'One', 'artistName': 'A', 'artwork': {'url': 'https://x/{w}x{h}bb.jpg'}}},
                                         cache_dir=self.tmp_dir, art_urls=art_urls)
        self.assertEqual(art_urls[item['art']], 'https://x/640x640bb.jpg')
        self.assertEqual(art_urls[item['thumb']], 'https://x/192x192bb.jpg')
        # A search hit without a cover on disk takes the thumbnail's size.
        hit = {'art': item['art'], 'thumb': item['thumb']}
        raw = {'attributes': {'artwork': {'url': 'https://x/{w}x{h}bb.jpg'}}}
        normalize._settle_search_art(hit, raw)
        self.assertEqual(hit['art'], 'https://x/192x192bb.jpg')
        self.assertIsNone(hit['thumb'])

    def test_changed_thumb_size_wipes_the_thumbnails(self):
        thumb_dir = os.path.join(self.tmp_dir, 'thumb')
        os.makedirs(thumb_dir)
        with open(os.path.join(thumb_dir, 'a.jpg'), 'wb') as f:
            f.write(b'old')
        # The same size as the (implied) default: nothing happens.
        art_cache.apply_art_sizes(self.tmp_dir, config.COVER_SIZE, config.THUMB_SIZE)
        self.assertTrue(os.path.exists(os.path.join(thumb_dir, 'a.jpg')))
        # A changed cover size alone: the thumbnails stay too.
        art_cache.apply_art_sizes(self.tmp_dir, 768, config.THUMB_SIZE)
        self.assertTrue(os.path.exists(os.path.join(thumb_dir, 'a.jpg')))
        # A changed thumbnail size: they go, to be rebuilt from the covers.
        art_cache.apply_art_sizes(self.tmp_dir, 768, 128)
        self.assertEqual(os.listdir(thumb_dir), [])


class TestRemoteArtItems(unittest.TestCase):
    """An item fetched on demand keeps its artwork in remote-art/."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir)

    def test_place_in_remote_art(self):
        raw = {'id': 'pl.one', 'type': 'playlists',
               'attributes': {'name': 'Mix', 'artwork': {'url': 'https://p/{w}x{h}bb.jpg'}}}
        tracks = [{'id': '1', 'attributes': {'name': 'A',
                                             'artwork': {'url': 'https://a/{w}x{h}bb.jpg'}}}]
        art_urls = {}
        item = normalize.normalize_playlist(raw, self.tmp_dir, tracks=tracks, art_urls=art_urls)
        # The library has the row's thumbnail already: that one stays where it is.
        row_thumb = item['groups'][0]['entries'][0]['thumb']
        os.makedirs(os.path.dirname(row_thumb))
        with open(row_thumb, 'wb') as f:
            f.write(b'img')
        placed = art_cache.place_in_remote_art(item, art_urls, self.tmp_dir)
        remote = os.path.join(self.tmp_dir, 'remote-art')
        cover = art_cache.template_artwork_url('https://p/{w}x{h}bb.jpg')
        self.assertEqual(item['art'], os.path.join(remote, art_cache.artwork_filename(cover)))
        size = art_cache.ART_SIZES['thumb']
        thumb_url = art_cache.template_artwork_url('https://p/{w}x{h}bb.jpg', size, size)
        self.assertEqual(item['thumb'],
                         os.path.join(remote, art_cache.artwork_filename(thumb_url)))
        self.assertEqual(item['groups'][0]['entries'][0]['thumb'], row_thumb)
        self.assertEqual(placed, {item['art']: cover, item['thumb']: thumb_url,
                                  row_thumb: art_urls[row_thumb]})

    def test_downloads_land_where_the_item_points(self):
        # #538: a catalog playlist's rows read their thumbnails from remote-art/, so that is
        # where item()'s download writes them (not art/, under the same name), and the
        # library's prune, which knows nothing of them, leaves them alone.
        raw = {'id': 'pl.two', 'type': 'playlists',
               'attributes': {'name': 'Mix', 'artwork': {'url': 'https://p/{w}x{h}bb.jpg'}}}
        tracks = [{'id': str(n), 'type': 'songs',
                   'attributes': {'name': f'Song {n}',
                                  'artwork': {'url': f'https://t{n}/{{w}}x{{h}}bb.jpg'}}}
                  for n in range(3)]
        art_urls = {}
        item = normalize.normalize_playlist(raw, self.tmp_dir, tracks=tracks, art_urls=art_urls)
        placed = art_cache.place_in_remote_art(item, art_urls, self.tmp_dir)
        fetched = []

        class Answer(io.BytesIO):
            status = 200

        def urlopen(request, timeout=None):
            fetched.append(request.full_url)
            return Answer(b'image')

        with mock.patch('urllib.request.urlopen', urlopen):
            art_cache.download_item_art(item, self.tmp_dir, placed)
        remote = os.path.join(self.tmp_dir, 'remote-art')
        rows = [entry['thumb'] for entry in item['groups'][0]['entries']]
        self.assertEqual(len(rows), 3)
        for path in rows + [item['art'], item['thumb']]:
            self.assertEqual(os.path.dirname(path), remote)
            self.assertTrue(os.path.isfile(path), path)
        self.assertEqual(sorted(fetched), sorted(placed.values()))
        for folder in ('art', 'thumb'):
            self.assertEqual(os.listdir(os.path.join(self.tmp_dir, folder))
                             if os.path.isdir(os.path.join(self.tmp_dir, folder)) else [], [])
        cache_files.prune_art({'sections': {}}, self.tmp_dir)
        for path in rows + [item['art'], item['thumb']]:
            self.assertTrue(os.path.isfile(path), path)


if __name__ == '__main__':
    unittest.main()
