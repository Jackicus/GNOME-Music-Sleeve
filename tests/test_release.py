# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""release.py: which catalog album an album page asks for, the footer's words and the
shelves' titles, over invented Items and answers."""

import unittest

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)

from applemusic.library import Item
from gi.repository import GLib

from applemusic.release import (album_artist, album_shelves, album_target, coming_text,
                                curator, curator_item, footer_lines, hero_caption,
                                is_prerelease, length_text, playlist_shelves,
                                playlist_target, release_date_text, released_play,
                                shelf_title, updated_text)


def album(album_id='l.alb001', catalog_id=None, songs=(None, '1724049201'), **extra):
    """An invented album Item whose songs have these catalog ids."""
    play = {'kind': 'album', 'id': album_id}
    entries = [{'id': f'i.trk{number}', 'catalogId': song, 'title': f'Song {number}',
                'durationMs': 180000, 'index': number} for number, song in enumerate(songs)]
    data = {'id': album_id, 'kind': 'album', 'title': 'Invented Album',
            'subtitle': 'Invented Artist', 'catalogId': catalog_id, 'play': play,
            'groups': [{'name': '', 'play': play, 'entries': entries}] if entries else []}
    data.update(extra)
    return Item(data)


class AlbumTargetTest(unittest.TestCase):
    def test_a_catalog_album_by_its_id(self):
        self.assertEqual(album_target(album('1724049100')), ('1724049100', None))
        self.assertEqual(album_target(album('l.alb001', catalog_id='1724049100')),
                         ('1724049100', None))
        self.assertEqual(album_target(album('1724049100', songs=())), ('1724049100', None))

    def test_a_library_album_through_its_first_song_with_a_catalog_id(self):
        self.assertEqual(album_target(album()), ('l.alb001', '1724049201'))
        self.assertEqual(album_target(album(songs=('i.trk9', '1724049202'))),
                         ('l.alb001', '1724049202'))

    def test_none_to_ask(self):
        self.assertIsNone(album_target(album(songs=(None,))))  # no song to find it by
        self.assertIsNone(album_target(album(songs=())))
        self.assertIsNone(album_target(album('l.alb_0123456789ab')))  # loose songs' stand-in
        self.assertIsNone(album_target(Item({'id': 'p.1', 'kind': 'playlist'})))
        self.assertIsNone(album_target(None))


def playlist(playlist_id='pl.0123abcd', **extra):
    """An invented playlist Item."""
    data = {'id': playlist_id, 'kind': 'playlist', 'title': 'Invented Picks',
            'play': {'kind': 'playlist', 'id': playlist_id}, 'groups': []}
    data.update(extra)
    return Item(data)


class HeroTest(unittest.TestCase):
    """The hero's line under the title and its caption."""

    # A Wednesday, at noon in the reader's time zone.
    NOW = GLib.DateTime.new_local(2026, 10, 21, 12, 0, 0)

    @staticmethod
    def utc(year, month, day, hour=12):
        """Noon (or `hour`) local time that day, as Apple writes a date: ISO 8601, in UTC."""
        date = GLib.DateTime.new_local(year, month, day, hour, 0, 0).to_utc()
        return date.format('%Y-%m-%dT%H:%M:%SZ')

    def test_when_a_playlist_was_updated(self):
        self.assertEqual(updated_text(self.utc(2026, 10, 21, 1), self.NOW), 'Updated today')
        self.assertEqual(updated_text(self.utc(2026, 10, 20, 23), self.NOW), 'Updated yesterday')
        self.assertEqual(updated_text(self.utc(2026, 10, 19), self.NOW), 'Updated Monday')
        self.assertEqual(updated_text(self.utc(2026, 10, 15), self.NOW), 'Updated Thursday')
        self.assertEqual(updated_text(self.utc(2026, 10, 14), self.NOW), 'Updated 14 October')
        self.assertEqual(updated_text(self.utc(2026, 1, 1), self.NOW), 'Updated 1 January')
        self.assertEqual(updated_text(self.utc(2025, 12, 31), self.NOW),
                         'Updated 31 December 2025')
        # A clock behind Apple's is still today.
        self.assertEqual(updated_text(self.utc(2026, 10, 22), self.NOW), 'Updated today')
        self.assertEqual(updated_text('2026-01-01', self.NOW), 'Updated 1 January')
        for text in (None, '', 'soon', '2026-13-01T00:00:00Z', 20261021):
            self.assertEqual(updated_text(text, self.NOW), '', text)

    def test_a_playlists_caption_says_when_and_how_long(self):
        apple = playlist(subtitle='Invented Curator', genre='Pop', year=2026,
                         modified=self.utc(2026, 10, 19), trackCount=22, durationMs=6120000)
        self.assertEqual(hero_caption(apple, self.NOW), 'Updated Monday · 22 songs, 1 hr 42 min')
        # No date (an older library.json, an answer without one): the songs alone.
        self.assertEqual(hero_caption(playlist(trackCount=3, durationMs=540000), self.NOW),
                         '3 songs, 9 min')
        self.assertEqual(hero_caption(playlist(), self.NOW), '')

    def test_an_albums_caption_is_unchanged(self):
        record = album(genre='Pop', year=2001, trackCount=12, durationMs=43 * 60000,
                       modified=self.utc(2026, 10, 19))
        self.assertEqual(hero_caption(record, self.NOW), 'Pop · 2001 · 12 songs, 43 min')
        self.assertEqual(hero_caption(None), '')

    def test_an_albums_artist(self):
        self.assertEqual(album_artist(album()), 'Invented Artist')
        # A shelf's album (an artist page's, Other Versions') is subtitled with its year.
        shelf = album('1724049100', subtitle='2018', artistName='Invented Band')
        self.assertEqual(album_artist(shelf), 'Invented Band')
        self.assertEqual(curator(shelf, 'Alex'), 'Invented Band')
        self.assertEqual(album_artist(playlist(subtitle='Invented Curator')), '')
        self.assertEqual(album_artist(None), '')

    def test_the_curator(self):
        self.assertEqual(curator(playlist(subtitle='Invented Curator'), 'Alex'),
                         'Invented Curator')
        self.assertEqual(curator(album(), 'Alex'), 'Invented Artist')
        # The user's own carry none: the account's name, when the app knows it.
        own = playlist('p.mine')
        self.assertEqual(curator(own, 'Alex Rivera'), 'Alex Rivera')
        self.assertEqual(curator(own, ''), '')
        favourites = playlist('p.fav', attributes={'isFavourites': True})
        self.assertEqual(curator(favourites, 'Alex Rivera'), 'Alex Rivera')
        # One of Apple's in the library, which names no curator, and a catalog one: nobody.
        self.assertEqual(curator(playlist('p.apple', attributes={'canEdit': False}), 'Alex'),
                         '')
        self.assertEqual(curator(playlist(), 'Alex'), '')
        self.assertEqual(curator(None, 'Alex'), '')


class FooterTest(unittest.TestCase):
    def test_the_release_date_in_full(self):
        self.assertEqual(release_date_text('2026-09-24'), '24 September 2026')
        self.assertEqual(release_date_text('1999'), '1999')
        for text in ('', None, 'soon', '2026-13-40', '2026-09'):
            self.assertEqual(release_date_text(text), '', text)

    def test_the_length_in_words(self):
        self.assertEqual(length_text(12, 43 * 60000), '12 songs, 43 minutes')
        self.assertEqual(length_text(1, 61 * 60000), '1 song, 1 hour, 1 minute')
        self.assertEqual(length_text(20, 120 * 60000), '20 songs, 2 hours')
        self.assertEqual(length_text(1, 20000), '1 song, 1 minute')  # at least a minute
        self.assertEqual(length_text(3), '3 songs')
        self.assertEqual(length_text(3, 0), '3 songs')

    def test_the_lines_from_the_answer(self):
        answer = {'release': {'releaseDate': '2026-03-14',
                              'copyright': '℗ 2026 Invented Records Ltd',
                              'recordLabel': 'Invented Records'}}
        self.assertEqual(footer_lines(album(), answer, 12, 43 * 60000),
                         ['14 March 2026', '12 songs, 43 minutes', '℗ 2026 Invented Records Ltd'])
        # The label where Apple has no copyright line.
        label = {'release': {'recordLabel': 'Invented Records'}}
        self.assertEqual(footer_lines(album(), label, 2, 0), ['2 songs', 'Invented Records'])

    def test_the_lines_without_an_answer(self):
        # What the Item carries (an artist page's release has its date), and the counts.
        self.assertEqual(footer_lines(album(releaseDate='2026-09-24'), None, 2, 360000),
                         ['24 September 2026', '2 songs, 6 minutes'])
        self.assertEqual(footer_lines(album(), {}, 2, 360000), ['2 songs, 6 minutes'])
        self.assertEqual(footer_lines(album(), None, 0, 0), [])


def upcoming(out=(1, 3), count=4, **extra):
    """An invented pre-release catalog album of `count` songs, those at the places `out`
    released already (its singles), the others `unreleased`."""
    play = {'kind': 'album', 'id': '1724049300'}
    entries = []
    for number in range(count):
        entry = {'id': f'17240493{number:02d}', 'catalogId': f'17240493{number:02d}',
                 'title': f'Song {number}', 'durationMs': 180000, 'index': number,
                 'type': 'songs'}
        if number not in out:
            entry['unreleased'] = True
        entries.append(entry)
    data = {'id': '1724049300', 'kind': 'album', 'title': 'Invented Album To Come',
            'subtitle': 'Invented Artist', 'genre': 'Pop', 'year': 2026, 'trackCount': count,
            'durationMs': count * 180000, 'prerelease': True, 'releaseDate': '2026-12-04',
            'play': play, 'groups': [{'name': '', 'play': play, 'entries': entries}]}
    data.update(extra)
    return Item(data)


class PrereleaseTest(unittest.TestCase):
    """An album not out yet: when it comes, and what of it plays."""

    def test_which_albums_are_to_come(self):
        self.assertTrue(is_prerelease(upcoming()))
        self.assertFalse(is_prerelease(album()))
        self.assertFalse(is_prerelease(playlist(prerelease=True)))  # only an album
        self.assertFalse(is_prerelease(None))

    def test_the_caption_and_the_footer_say_when_it_comes(self):
        self.assertEqual(coming_text('4 December 2026'), 'Coming 4 December 2026')
        self.assertEqual(coming_text(''), 'Coming Soon')
        self.assertEqual(hero_caption(upcoming()),
                         'Pop · Coming 4 December 2026 · 4 songs, 12 min')
        self.assertEqual(hero_caption(upcoming(releaseDate=None)),
                         'Pop · Coming Soon · 4 songs, 12 min')
        self.assertEqual(footer_lines(upcoming(), None, 4, 720000),
                         ['Coming 4 December 2026', '4 songs, 12 minutes'])
        # The catalog's answer's date over the Item's; a date always, a year alone too.
        answer = {'release': {'releaseDate': '2026-12-11', 'recordLabel': 'Invented Records'}}
        self.assertEqual(footer_lines(upcoming(), answer, 4, 720000),
                         ['Coming 11 December 2026', '4 songs, 12 minutes', 'Invented Records'])
        self.assertEqual(footer_lines(upcoming(releaseDate=None), None, 4, 0),
                         ['Coming Soon', '4 songs'])
        # Out now (an answer without the flag): the date as any album's.
        self.assertEqual(footer_lines(album(releaseDate='2026-12-04'), None, 0, 0),
                         ['4 December 2026'])

    def test_play_plays_the_released_songs_by_id(self):
        record = upcoming()
        songs = {'kind': 'songs', 'id': '1724049301,1724049303'}
        self.assertEqual(released_play(record), (songs, None, None))
        tracks = list(record.groups[0].entries)
        # A released song plays among them, from its place there.
        self.assertEqual(released_play(record, tracks[3]), (songs, 1, '1724049303'))
        self.assertEqual(released_play(record, tracks[1]), (songs, 0, '1724049301'))
        # One not out yet plays nothing.
        self.assertIsNone(released_play(record, tracks[0]))
        self.assertTrue(tracks[0].unreleased)
        self.assertFalse(tracks[1].unreleased)

    def test_none_out_plays_nothing(self):
        record = upcoming(out=())
        self.assertIsNone(released_play(record))
        self.assertIsNone(released_play(record, record.groups[0].entries.get_item(2)))

    def test_anything_else_plays_its_own_target(self):
        record = album()
        track = record.groups[0].entries.get_item(1)
        self.assertEqual(released_play(record), (record.play, None, None))
        self.assertEqual(released_play(record, track), (track.play, 1, 'i.trk1'))
        # A pre-release album whose songs are all out (a day-old answer) plays as an album.
        whole = upcoming(out=range(4))
        self.assertEqual(released_play(whole), (whole.play, None, None))
        self.assertIsNone(released_play(None))


class ShelvesTest(unittest.TestCase):
    def answer(self):
        def entry(number, kind='album'):
            return {'id': f'17240491{number:02d}', 'kind': kind, 'title': f'Invented {number}',
                    'subtitle': '2026', 'art': None, 'thumb': None, 'groups': [],
                    'play': {'kind': kind, 'id': f'17240491{number:02d}'}}
        return {'id': '1724049100', 'artistId': '1724049001', 'artistName': 'Paper Parachutes',
                'shelves': [
                    {'key': 'other-versions', 'title': 'Other Versions', 'more': False,
                     'items': [entry(50)]},
                    {'key': 'related-videos', 'title': '', 'more': False,
                     'items': [entry(60, 'video')]},
                    {'key': 'more-by-artist', 'title': '', 'more': True,
                     'items': [entry(10), entry(11)]},
                    {'key': 'appears-on', 'title': 'Featured On', 'more': False, 'items': []},
                    {'key': 'you-might-also-like', 'title': 'You Might Also Like', 'more': False,
                     'items': [{'id': '', 'kind': 'album'}, entry(30)]},
                ]}

    def test_titled_in_order_the_empty_left_out(self):
        shelves = album_shelves(self.answer(), 'Invented Artist')
        self.assertEqual([(shelf.key, shelf.title, shelf.more) for shelf in shelves], [
            ('other-versions', 'Other Versions', False),
            ('related-videos', 'Music Videos', False),  # Apple gave no title
            ('more-by-artist', 'More By Invented Artist', True),
            ('you-might-also-like', 'You Might Also Like', False)])
        self.assertEqual([item.id for item in shelves[3].items], ['1724049130'])

    def test_more_by_names_the_answers_artist_without_one(self):
        shelves = album_shelves(self.answer())
        self.assertEqual(shelves[2].title, 'More By Paper Parachutes')
        self.assertEqual(shelf_title('more-by-artist', '', ''), 'More By the Artist')
        self.assertEqual(album_shelves(None), [])


def catalog_playlist(playlist_id='pl.aW52ZW50ZWRwbA', catalog_id=None, **extra):
    """An invented playlist Item."""
    play = {'kind': 'playlist', 'id': playlist_id}
    data = {'id': playlist_id, 'kind': 'playlist', 'title': 'Invented Night Drive',
            'subtitle': 'Apple Music Invented', 'catalogId': catalog_id, 'play': play,
            'groups': []}
    data.update(extra)
    return Item(data)


class PlaylistTest(unittest.TestCase):
    def test_the_catalog_playlist_asked_for(self):
        self.assertEqual(playlist_target(catalog_playlist()), 'pl.aW52ZW50ZWRwbA')
        # One of Apple's added to the library: by the catalog id it carries.
        added = catalog_playlist('p.aW52ZW50ZWQ', catalog_id='pl.aW52ZW50ZWRwbA',
                         attributes={'canEdit': False})
        self.assertEqual(playlist_target(added), 'pl.aW52ZW50ZWRwbA')

    def test_none_to_ask(self):
        self.assertIsNone(playlist_target(None))
        self.assertIsNone(playlist_target(album('1724049100')))
        # The user's own (editable, though it carries a catalog id), Favourite Songs, one
        # shared from an account, and one without a catalog playlist.
        apples = {'canEdit': False}
        for item in (catalog_playlist('p.aW52', catalog_id='pl.u-aW52ZW50'),
                     catalog_playlist('p.aW52', catalog_id='pl.aW52ZW50ZWRwbA'),
                     catalog_playlist('p.aW52', catalog_id='pl.aW52ZW50ZWRwbA',
                                      attributes=dict(apples, isFavourites=True)),
                     catalog_playlist('pl.u-aW52ZW50ZWQ'),
                     catalog_playlist('p.aW52', attributes=apples),
                     catalog_playlist('1724042001')):
            with self.subTest(item=(item.id, item.catalog_id)):
                self.assertIsNone(playlist_target(item))

    def answer(self, curator=None):
        def entry(number, kind='playlist'):
            return {'id': f'pl.aW52{number}', 'kind': kind, 'title': f'Other {number}',
                    'groups': []}
        return {'id': 'pl.aW52ZW50ZWRwbA', 'curator': curator, 'shelves': [
            {'key': 'featured-artists', 'title': '', 'more': False,
             'items': [dict(entry(1, 'artist'), id='1724049001')]},
            {'key': 'more-by-curator', 'title': '', 'more': True, 'items': [entry(2)]},
            {'key': 'you-might-also-like', 'title': 'Alike', 'more': False, 'items': [entry(3)]},
            {'key': 'more-by-curator', 'title': '', 'more': False, 'items': []}]}

    def test_the_shelves_titled(self):
        shelves = playlist_shelves(self.answer(), 'Apple Music Invented')
        self.assertEqual([(shelf.key, shelf.title, shelf.more) for shelf in shelves], [
            ('featured-artists', 'Featured Artists', False),
            ('more-by-curator', 'More By Apple Music Invented', True),
            ('you-might-also-like', 'Alike', False)])  # Apple's title
        # The curator named by the answer, else not at all.
        named = playlist_shelves(self.answer({'id': '1', 'kind': 'category',
                                              'title': 'Harbour Editors'}))
        self.assertEqual(named[1].title, 'More By Harbour Editors')
        self.assertEqual(playlist_shelves(self.answer())[1].title, 'More By the Curator')
        self.assertEqual(playlist_shelves(None), [])

    def test_the_curators_link(self):
        category = {'id': '1724049500', 'kind': 'category', 'title': 'Apple Music Invented',
                    'art': None}
        item = curator_item({'curator': category})
        self.assertEqual((item.kind, item.id, item.title),
                         ('category', '1724049500', 'Apple Music Invented'))
        url = 'https://music.apple.com/gb/curator/harbour-editors/1724049700'
        link = curator_item({'curator': {'id': '1724049700', 'kind': 'link',
                                         'title': 'Harbour Editors', 'url': url}})
        self.assertEqual((link.kind, link.url), ('link', url))
        for answer in (None, {}, {'curator': None}, {'curator': dict(category, id='')},
                       {'curator': dict(category, kind='playlist')},
                       {'curator': {'id': '1', 'kind': 'link', 'title': 'No Page'}}):
            with self.subTest(answer=answer):
                self.assertIsNone(curator_item(answer))


if __name__ == '__main__':
    unittest.main()
