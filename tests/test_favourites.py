# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The library's dates added and favourites (library.py): Item.added and Item.favourite,
Library.is_favourite() and set_favourite(), `favourites-changed`, and the Recently Added store,
over invented library.json files. No sync, no display."""

import json
import unittest
from pathlib import Path

from tests import ROOT  # noqa: F401  (registers src/ as applemusic)
from tests.test_reload import ReloadCase, album, playlist, shelf

from applemusic import library as library_module
from applemusic.library import Item, Track, added_seconds, favourite_set, recently_added_order


def dated(item, added):
    item['added'] = added
    return item


class FavouritesCase(ReloadCase):
    def write(self, albums=(), playlists=(), videos=(), shelves=(), favourites=None,
              version=3):
        data = {'version': version, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': list(albums), 'playlists': list(playlists),
                             'videos': list(videos)},
                'shelves': list(shelves)}
        if favourites is not None:
            data['favourites'] = favourites
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')

    def changes(self):
        seen = []
        self.library.connect('favourites-changed', lambda _library: seen.append(True))
        return seen


def video(video_id, catalog_id=None, added=None):
    item = {'id': video_id, 'kind': 'video', 'title': video_id, 'subtitle': 'Test Artist',
            'catalogId': catalog_id, 'play': {'kind': 'musicVideo', 'id': video_id},
            'groups': []}
    if added:
        item['added'] = added
    return item


class TestAdded(unittest.TestCase):
    def test_added_seconds(self):
        self.assertEqual(added_seconds('1970-01-01T00:01:00Z'), 60)
        self.assertEqual(added_seconds('1970-01-02'), 86400)  # a date is its midnight, UTC
        self.assertEqual(added_seconds('1971'), 365 * 86400)  # a year its first day
        self.assertEqual(added_seconds('1970-01-01T01:00:00+01:00'), 0)
        for value in (None, '', 'yesterday', 2020, '2020-13-45'):
            self.assertEqual(added_seconds(value), 0, value)

    def test_an_items_added_property(self):
        item = Item(dated(album('l.a1'), '2026-01-01T00:00:00Z'))
        self.assertEqual(item.added, 1767225600)
        self.assertEqual(item.props.added, 1767225600)  # an int64 GObject property
        self.assertEqual(Item(album('l.a2')).added, 0)

    def test_a_merge_that_changes_the_date_notifies_it(self):
        item = Item(dated(album('l.a1'), '2026-01-01T00:00:00Z'))
        self.assertEqual(item.added, 1767225600)
        seen = []
        item.connect('notify', lambda _item, pspec: seen.append(pspec.name))
        self.assertEqual(item.merge(dated(album('l.a1'), '2026-01-02T00:00:00Z'), replace=True),
                         ['added'])
        self.assertEqual(seen, ['added'])
        self.assertEqual(item.added, 1767225600 + 86400)
        self.assertIn('added', library_module.SORT_KEYS)  # a sort key: the stores place it

    def test_favourite_set(self):
        self.assertEqual(favourite_set({'songs': ['1', 'i.x'], 'albums': ['l.a', 7, ''],
                                        'other': ['nope'], 'videos': 'not a list'}),
                         {'1', 'i.x', 'l.a'})
        self.assertEqual(favourite_set(None), frozenset())
        self.assertEqual(favourite_set(['1']), frozenset())


class TestRecentlyAddedOrder(unittest.TestCase):
    def test_newest_first_ties_in_apples_order_undated_last(self):
        a = Item(dated(album('l.a', title='Alpha'), '2026-03-01T10:00:00Z'))
        b = Item(dated(album('l.b', title='Beta'), '2026-03-02T10:00:00Z'))
        c = Item(dated(album('l.c', title='Gamma'), '2026-03-01T10:00:00Z'))
        p = Item(dated(playlist('p.1', title='Mix'), '2026-02-01T10:00:00Z'))
        loose = Item(album('l.alb_loose', title='Loose'))
        zed = Item(album('l.alb_zed', title='Zed'))
        # Apple listed c before a: the same second, Apple's order decides.
        order = recently_added_order([zed, a, p, loose, b, c], [b, c, a])
        self.assertEqual([item.id for item in order],
                         ['l.b', 'l.c', 'l.a', 'p.1', 'l.alb_loose', 'l.alb_zed'])

    def test_ties_outside_apples_list_go_by_title(self):
        when = '2026-03-01T10:00:00Z'
        z = Item(dated(album('l.z', title='zulu'), when))
        a = Item(dated(album('l.a', title='Alpha'), when))
        e = Item(dated(album('l.e', title='Écho'), when))
        ten = Item(dated(album('l.10', title='10 Days'), when))
        two = Item(dated(album('l.2', title='2 Days'), when))
        listed = Item(dated(album('l.r', title='Zed'), when))
        newer = Item(dated(album('l.n', title='Zz'), '2026-03-02T10:00:00Z'))
        # Apple's list first among those of the second, then the rest by title_key().
        order = recently_added_order([z, a, e, ten, two, listed, newer], [listed])
        self.assertEqual([item.id for item in order],
                         ['l.n', 'l.r', 'l.10', 'l.2', 'l.a', 'l.e', 'l.z'])

    def test_without_dates_it_is_apples_list(self):
        a, b = Item(album('l.a')), Item(album('l.b'))
        self.assertEqual(recently_added_order([a, b], [b]), [b])
        self.assertEqual(recently_added_order([a, b], []), [])


class TestLibraryFavourites(FavouritesCase):
    def test_a_load_reads_the_dates_and_favourites(self):
        albums = [dated(album('l.a1', track_ids=['i.1', 'i.2']), '2026-01-01T00:00:00Z'),
                  dated(album('l.a2'), '2026-02-01T00:00:00Z')]
        albums[0]['groups'][0]['entries'][1]['catalogId'] = '9001'
        playlists = [dated(playlist('p.1', track_ids=['i.2']), '2025-12-01T00:00:00Z'),
                     dict(playlist('p.favs', track_ids=['i.2']),
                          attributes={'isFavourites': True})]
        self.write(albums, playlists, videos=[video('i.mv1', '5001', '2025-11-01T00:00:00Z')],
                   favourites={'songs': ['9001'], 'albums': ['l.a2'], 'playlists': [],
                               'videos': ['5001']})
        self.load()
        library = self.library
        self.assertTrue(library.by_id('album', 'l.a2').favourite)
        self.assertFalse(library.by_id('album', 'l.a1').favourite)
        self.assertTrue(library.by_id('video', 'i.mv1').favourite)  # by its catalog id
        tracks = list(library.by_id('album', 'l.a1').groups[0].entries)
        self.assertEqual([library.is_favourite(track) for track in tracks], [False, True])
        # Recently Added: every album, playlist and video, newest first, Favourite Songs not.
        self.assertEqual([item.id for item in library.recently_added],
                         ['l.a2', 'l.a1', 'p.1', 'i.mv1'])
        self.assertFalse(library.is_favourite(None))

    def test_a_file_from_before_has_apples_recently_added_and_no_favourites(self):
        albums = [album('l.a1'), album('l.a2'), album('l.a3')]
        self.write(albums, shelves=[shelf('recently-added', [albums[2], albums[0]])],
                   version=2)
        self.load()
        self.assertEqual([item.id for item in self.library.recently_added], ['l.a3', 'l.a1'])
        self.assertFalse(any(item.favourite for item in self.library.albums))
        self.assertEqual(self.library.version, 2)

    def test_a_reload_tells_only_what_changed(self):
        albums = [album('l.a1'), album('l.a2'), album('l.a3')]
        self.write(albums, favourites={'albums': ['l.a1', 'l.a2']})
        self.load()
        a1, a2, a3 = (self.library.by_id('album', f'l.a{n}') for n in (1, 2, 3))
        seen = [self.notifies(item) for item in (a1, a2, a3)]
        changes = self.changes()
        self.write(albums, favourites={'albums': ['l.a2', 'l.a3']})
        self.reload()
        self.assertEqual(seen, [['favourite'], [], ['favourite']])
        self.assertEqual((a1.favourite, a2.favourite, a3.favourite), (False, True, True))
        self.assertEqual(changes, [True])
        self.reload()  # the same file again: nothing
        self.assertEqual(changes, [True])
        self.assertEqual(seen, [['favourite'], [], ['favourite']])

    def test_recently_added_keeps_its_store_and_objects_through_a_reload(self):
        albums = [dated(album('l.a1'), '2026-01-01T00:00:00Z'),
                  dated(album('l.a2'), '2026-02-01T00:00:00Z')]
        self.write(albums)
        self.load()
        store = self.library.recently_added
        first = [store.get_item(n) for n in range(store.get_n_items())]
        albums.append(dated(album('l.a3'), '2026-03-01T00:00:00Z'))
        self.write(albums)
        splices = self.splices(store)
        self.reload()
        self.assertIs(self.library.recently_added, store)
        self.assertEqual([item.id for item in store], ['l.a3', 'l.a2', 'l.a1'])
        self.assertIs(store.get_item(1), first[0])
        self.assertEqual(splices, [(0, 0, 1)])  # the new album in, nothing else touched

    def test_set_favourite_marks_the_items_and_takes_aliases_away(self):
        albums = [dict(album('l.a1'), catalogId='7001'), album('l.a2', track_ids=['i.1'])]
        albums[1]['groups'][0]['entries'][0]['catalogId'] = '9001'
        self.write(albums, favourites={'albums': ['l.a1', '7001']})
        self.load()
        a1 = self.library.by_id('album', 'l.a1')
        changes = self.changes()
        # A song favourited by its catalog id, as the menus rate it.
        song = list(self.library.by_id('album', 'l.a2').groups[0].entries)[0]
        self.assertTrue(self.library.set_favourite('9001', True))
        self.assertTrue(self.library.is_favourite(song))
        self.assertEqual(changes, [True])
        self.assertFalse(self.library.set_favourite('9001', True))  # nothing new
        self.assertEqual(changes, [True])
        # The album unfavourited from its catalog page (the catalog id): its library id goes
        # too, or the heart would stay.
        seen = self.notifies(a1)
        self.assertTrue(self.library.set_favourite('7001', False))
        self.assertFalse(a1.favourite)
        self.assertFalse(self.library.is_favourite(a1))
        self.assertEqual(seen, ['favourite'])
        self.assertEqual(changes, [True, True])
        self.assertFalse(self.library.set_favourite('', True))

    def test_a_track_is_found_by_either_id(self):
        self.write([album('l.a1', track_ids=['i.1', 'i.2'])], favourites={'songs': ['i.2']})
        self.load()
        one, two = list(self.library.by_id('album', 'l.a1').groups[0].entries)
        self.assertIsInstance(one, Track)
        self.assertEqual((self.library.is_favourite(one), self.library.is_favourite(two)),
                         (False, True))


if __name__ == '__main__':
    unittest.main()
