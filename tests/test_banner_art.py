# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Apple's wide artwork as headers and banners (backend.banner_art)."""

import shutil
import tempfile
import unittest

from tests import SRC  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.backend import (
    art_cache,
    banner_art,
    cache_files,
    item_pages,
)

# The sizes these tests were written against (the extension's defaults). The
# app's own defaults come from config; TestArtSizes covers those.
UPSTREAM_SIZES = {'cover': 512, 'thumb': 256}


class TestCuratorBanner(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        art_cache.ART_SIZES.update(UPSTREAM_SIZES)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)
        art_cache.ART_SIZES.update(art_cache.DEFAULT_ART_SIZES)

    def test_a_curators_banner_is_the_first_of_its_keys_it_has(self):
        def editorial(*names):
            return {'editorialArtwork': {
                name: {'url': f'https://x.invalid/{name}/{{w}}x{{h}}{{c}}.{{f}}',
                       'width': 3000, 'height': 1000} for name in names}}

        def chosen(attrs):
            banner = banner_art.curator_banner(attrs)
            return banner['url'].split('/')[3] if banner else None

        self.assertEqual(chosen(editorial('subscriptionHero', 'subscriptionCover',
                                          'bannerUber')), 'bannerUber')
        self.assertEqual(chosen(editorial('subscriptionHero', 'subscriptionCover')),
                         'subscriptionCover')
        self.assertEqual(chosen(editorial('subscriptionHero')), 'subscriptionHero')
        self.assertIsNone(chosen(editorial('superHeroWide')))  # not a curator's banner
        self.assertIsNone(chosen({}))
        self.assertIsNone(chosen(None))
        self.assertIsNone(chosen({'editorialArtwork': 'odd'}))
        # One without a size or an https template is passed over for the next.
        attrs = editorial('subscriptionHero')
        attrs['editorialArtwork']['bannerUber'] = {'url': 'https://x.invalid/{w}x{h}bb.jpg'}
        attrs['editorialArtwork']['subscriptionCover'] = {
            'url': 'http://x.invalid/{w}x{h}bb.jpg', 'width': 10, 'height': 10}
        self.assertEqual(chosen(attrs), 'subscriptionHero')


class TestArtistBanner(unittest.TestCase):
    """artist_banner: an artist's wide header as music.apple.com chooses it, from invented
    attributes in the shape Apple answers with `extend=editorialArtwork,hero`."""

    PORTRAIT = 'https://example.invalid/image/thumb/aW52ZW50ZWQ/{w}x{h}bb.jpg'
    BACKGROUND = 'https://example.invalid/image/thumb/ZWRpdG9yaWFs/{w}x{h}{c}.{f}'

    def hero(self, crops, url=PORTRAIT, size=3000):
        return [{'content': [{'artwork': {'url': url, 'width': size, 'height': size,
                                          'bgColor': '2a1f3d',
                                          'recommendedCropCodes': crops}}]}]

    def editorial(self):
        return {'centeredFullscreenBackground': {'url': self.BACKGROUND, 'width': 4320,
                                                 'height': 2160, 'bgColor': '#102030'}}

    def test_the_template_cut_with_a_crop(self):
        self.assertEqual(banner_art.banner_template(self.PORTRAIT, 'vf'),
                         'https://example.invalid/image/thumb/aW52ZW50ZWQ/{w}x{h}vf.jpg')
        self.assertEqual(banner_art.banner_template(self.BACKGROUND, 'sr'),
                         'https://example.invalid/image/thumb/ZWRpdG9yaWFs/{w}x{h}sr.jpg')
        self.assertIsNone(banner_art.banner_template('https://example.invalid/a/600x600bb.jpg',
                                                     'vf'))  # not a template
        self.assertIsNone(banner_art.banner_template('http://example.invalid/{w}x{h}bb.jpg',
                                                     'vf'))
        self.assertIsNone(banner_art.banner_template(None, 'vf'))

    def test_an_effect_coded_template_keeps_apples_effect(self):
        # A composite Apple made of a source (an Essentials playlist's banner: the artist's
        # picture placed on a colour, the playlist's word beside it): an `sr` cut of the
        # source would crop the picture, so the template is kept, query and all, and its
        # source's shape is the one asked for.
        url = ('https://example.invalid/image/thumb/aW52ZW50ZWQ/source_cropped.png/'
               '{w}x{h}SH.FPINV01.jpg?l=en-GB')
        self.assertEqual(banner_art.banner_template(url, 'sr'), url)
        banner = banner_art.wide_artwork({'url': url, 'width': 4320, 'height': 1080,
                                          'bgColor': '3f4e55'}, 'sr')
        self.assertEqual(banner, {'url': url, 'crop': 'SH.FPINV01', 'width': 4320,
                                  'height': 1080, 'color': '#3f4e55'})
        self.assertEqual(banner_art.banner_template(url.replace('?l=en-GB', ''), 'vf'),
                         url.replace('?l=en-GB', ''))
        for bad in ('https://example.invalid/a/{w}x{h}SH.FPINV01.jpg/more',
                    'https://example.invalid/a/600x600SH.FPINV01.jpg'):
            self.assertIsNone(banner_art.banner_template(bad, 'sr'))

    def test_the_editorial_background_first(self):
        banner = banner_art.artist_banner({'editorialArtwork': self.editorial(),
                                           'hero': self.hero(['vf', 'va'])})
        self.assertEqual(banner, {
            'url': 'https://example.invalid/image/thumb/ZWRpdG9yaWFs/{w}x{h}sr.jpg',
            'crop': 'sr', 'width': 4320, 'height': 2160, 'color': '#102030'})

    def test_else_the_hero_portrait_cut_wide(self):
        banner = banner_art.artist_banner({'editorialArtwork': {}, 'hero': self.hero(['va', 'vf'])})
        self.assertEqual(banner, {
            'url': 'https://example.invalid/image/thumb/aW52ZW50ZWQ/{w}x{h}vf.jpg',
            'crop': 'vf', 'width': 3000, 'height': 3000, 'color': '#2a1f3d'})

    def test_none_where_apple_recommends_no_wide_crop(self):
        for attrs in ({}, {'hero': self.hero(['va', 'vb'])}, {'hero': [{}]},
                      {'hero': [{'content': []}]}, {'hero': []}, {'hero': 'x'},
                      {'hero': self.hero(['vf'], url='https://example.invalid/a/600x600bb.jpg')},
                      {'hero': self.hero(['vf'], size=0)},
                      {'editorialArtwork': {'centeredFullscreenBackground': {'url': None}}}):
            with self.subTest(attrs=attrs):
                self.assertIsNone(banner_art.artist_banner(attrs))

    def test_the_page_carries_it(self):
        raw = {'data': [{'id': '1724049001', 'type': 'artists',
                         'attributes': {'name': 'Invented', 'hero': self.hero(['vf'])}}]}
        page = item_pages.artist_page(raw, tempfile.gettempdir())
        self.assertEqual(page['banner']['crop'], 'vf')

    def test_the_cache_path(self):
        self.assertEqual(cache_files.artist_cache_path('/c', '1724049001'),
                         '/c/artists/1724049001.json')
        self.assertEqual(cache_files.artist_cache_path('/c', '../x'), '/c/artists/.._x.json')


if __name__ == '__main__':
    unittest.main()
