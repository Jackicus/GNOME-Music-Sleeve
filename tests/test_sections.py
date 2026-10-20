# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

import pathlib
import unittest

from tests import SRC

from applemusic import sections

ADWAITA_SYMBOLIC = pathlib.Path('/usr/share/icons/Adwaita/symbolic')


def all_destinations():
    return [d for section in sections.sidebar_sections() for d in section.destinations]


class SectionsTest(unittest.TestCase):
    def test_keys_unique_and_non_empty(self):
        keys = [d.key for d in all_destinations()]
        self.assertTrue(keys)
        self.assertTrue(all(keys), keys)
        self.assertEqual(len(keys), len(set(keys)), keys)

    def test_home_exists(self):
        self.assertIn(sections.HOME, [d.key for d in all_destinations()])

    def test_section_ids_are_unique(self):
        ids = [section.id for section in sections.sidebar_sections()]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertTrue(all(ids), ids)

    def test_one_playlists_section_with_both_fixed_keys(self):
        found = [section for section in sections.sidebar_sections()
                 if section.id == sections.PLAYLISTS_SECTION]
        self.assertEqual(len(found), 1)
        keys = [d.key for d in found[0].destinations]
        self.assertIn(sections.ALL_PLAYLISTS, keys)
        self.assertIn(sections.FAVOURITE_SONGS, keys)

    def test_favourite_is_a_heart_everywhere(self):
        """One symbol for Favourite: the heart of the player bar's and the sheet's button,
        on the Favourite Songs destination (its sidebar row and its page's empty state)."""
        icons = {d.key: d.icon_name for d in all_destinations()}
        self.assertEqual(icons[sections.FAVOURITE_SONGS], 'heart-filled-symbolic')
        self.assertNotIn('starred-symbolic', icons.values())
        self.assertNotIn('non-starred-symbolic', icons.values())

    def test_every_destination_has_a_page(self):
        from applemusic import pages

        keys = [d.key for d in all_destinations()]
        self.assertEqual(sorted(keys), sorted(pages.PAGES))

    def test_genres_is_the_librarys_and_offered_by_its_setting(self):
        """Genres (#363) is in the Library section, after Songs, listed while show-genres
        is on; every other destination always is. A destination's setting is a boolean key
        of the schema."""
        from gi.repository import Gio

        library = next(section for section in sections.sidebar_sections()
                       if section.id == 'library')
        keys = [d.key for d in library.destinations]
        self.assertEqual(keys[keys.index('songs') + 1], 'genres')
        settings = {d.key: d.setting for d in all_destinations() if d.setting}
        self.assertEqual(settings, {'genres': 'show-genres'})
        schema = Gio.Settings.new('io.github.jackicus.MusicSleeve').props.settings_schema
        key = schema.get_key('show-genres')
        self.assertEqual(key.get_value_type().dup_string(), 'b')
        self.assertFalse(key.get_default_value().get_boolean())  # off until chosen

    def test_titles_non_empty(self):
        for destination in all_destinations():
            self.assertTrue(destination.title, destination.key)

    @unittest.skipUnless(ADWAITA_SYMBOLIC.is_dir(), 'Adwaita icon theme not installed')
    def test_icons_exist(self):
        from applemusic.sidebar import FOLDER_ICON, PLAYLIST_ICON

        bundled = {p.stem for p in (SRC / 'icons').glob('*.svg')}
        adwaita = {p.stem for p in ADWAITA_SYMBOLIC.rglob('*.svg')}
        gresource = (SRC / 'applemusic.gresource.xml').read_text()
        names = [destination.icon_name for destination in all_destinations()]
        # The sidebar's own icons: a folder's, a playlist's, and a folder's arrow both ways.
        names += [FOLDER_ICON, PLAYLIST_ICON, 'pan-end-symbolic', 'pan-down-symbolic']
        for name in names:
            with self.subTest(icon=name):
                self.assertTrue(name in bundled or name in adwaita,
                                f'{name} is neither in src/icons/ nor in Adwaita')
                if name in bundled and name not in adwaita:
                    self.assertIn(f'alias="icons/scalable/actions/{name}.svg"', gresource,
                                  f'{name} is bundled but not aliased in the gresource')


if __name__ == '__main__':
    unittest.main()
