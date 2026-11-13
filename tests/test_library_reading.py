# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Reading library.json (library/reading.py): the parse in pieces, the read in the library's
thread, and what a load leaves out."""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_library import album, held_library, plain, track, write_library

from applemusic.library import Library, parse
from applemusic.library import model as model_module
from applemusic.library import reading as reading_module


class TestParse(unittest.TestCase):
    """parse(): json.loads' result, decoded a list element at a time."""

    DOCUMENTS = [
        '{}',
        '[]',
        '"text"',
        '12.5',
        'null',
        ' \n{ "a" : [ ] , "b" : { } }\n ',
        '{"sections": {"albums": [{"id": "l.1", "groups": [{"entries": [{"id": "i.1"}]}]}, '
        '{"id": "l.2"}], "empty": [], "n": 3}, "shelves": [[1, 2], {"k": [3]}], "x": "y"}',
        '{"a": 1, "a": 2}',
        '{"text": "caf\\u00e9 \\"quoted\\" [not a list] {nor this}", "list": ["]", "}"]}',
        '{"n": [1, -2.5e3, true, false, null, NaN, Infinity], "deep": {"deeper": {"x": [[]]}}}',
        '{\n  "sections": {\n    "albums": [\n      {\n        "id": "l.1"\n      }\n    ]\n  }\n}',
    ]

    def test_same_as_json_loads(self):
        for text in self.DOCUMENTS:
            with self.subTest(text=text):
                self.assertEqual(parse(text), json.loads(text))

    def test_bad_documents_raise_value_error(self):
        for text in ['', '{', '{"a" 1}', '{"a": 1,}', '{a: 1}', '{"a": [1 2]}', '{"a": 1} x',
                     '{"a": [1, 2}', '{"a": {"b": }}', '[1, 2', '{"a": "unterminated}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)

    def test_element_sees_each_list_element_with_its_key(self):
        seen = []

        def element(key, value):
            seen.append((key, value))
            return {'wrapped': value}

        data = parse('{"sections": {"albums": [1, {"id": 2}], "radio": []}, "shelves": [3]}',
                     element)
        self.assertEqual(seen, [('albums', 1), ('albums', {'id': 2}), ('shelves', 3)])
        self.assertEqual(data, {'sections': {'albums': [{'wrapped': 1}, {'wrapped': {'id': 2}}],
                                             'radio': []},
                                'shelves': [{'wrapped': 3}]})


class TestReadLibrary(unittest.TestCase):
    """What the load makes of the file beyond parsing it."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name, 'library.json')

    def artist(self, artist_id, album_ids):
        return {'id': artist_id, 'kind': 'artist', 'title': artist_id,
                'groups': [{'name': album_id, 'play': {'kind': 'album', 'id': album_id},
                            'entries': [track(f'i.{album_id}', 'Song', 0)]}
                           for album_id in album_ids]}

    def read(self, sections):
        self.path.write_text(json.dumps({'version': 1, 'sections': sections}), encoding='utf-8')
        return reading_module._read_library(self.path)

    def test_repeated_values_are_one_object(self):
        # SHARED_KEYS: two albums' songs of one genre and year share the decoder's strings
        # and ints (a year past 256 is an object of its own for each one decoded).
        albums = [album(f'l.a{n}', f'A{n}', [f'i.{n}.1', f'i.{n}.2']) for n in (1, 2)]
        for each in albums:
            for entry in each['groups'][0]['entries']:
                entry.update(genre='Nu-' + 'Jazz', year=2000 + 19)
        data, _count, _state = self.read({'albums': albums})
        entries = [entry for each in data['sections']['albums']
                   for entry in each['groups'][0]['entries']]
        self.assertEqual(len({id(entry.get('genre')) for entry in entries}), 1)
        self.assertEqual(len({id(entry.get('year')) for entry in entries}), 1)
        self.assertEqual(entries[0].get('year'), 2019)

    def test_artist_tracks_dropped_only_for_albums_in_the_library(self):
        albums = [album('l.a1', 'A1', ['i.1', 'i.2'])]
        artists = [self.artist('l.r1', ['l.a1', 'l.gone'])]
        for order in (('albums', 'artists'), ('artists', 'albums')):  # either order in the file
            with self.subTest(order=order):
                sections = {'albums': albums, 'artists': artists}
                data, count, state = self.read({key: sections[key] for key in order})
                self.assertEqual(state, 'ok')
                groups = data['sections']['artists'][0]['groups']
                self.assertEqual(groups[0]['entries'], [])
                self.assertEqual([entry['id'] for entry in groups[1]['entries']], ['i.l.gone'])
                self.assertEqual(len(data['sections']['albums'][0]['groups'][0]['entries']), 2)
                self.assertEqual(count, 2)

    def test_repeated_track_strings_are_one_object(self):
        data, _count, _state = self.read({'albums': [album('l.a1', 'A1', ['i.1']),
                                             album('l.a2', 'A2', ['i.2'])],
                                  'playlists': [dict(album('p.1', 'P', ['i.3']), kind='playlist')],
                                  'songs': [track('i.4', 'Loose', 0)]})
        sections = data['sections']
        entries = [sections['albums'][0]['groups'][0]['entries'][0],
                   sections['albums'][1]['groups'][0]['entries'][0],
                   sections['playlists'][0]['groups'][0]['entries'][0],
                   sections['songs'][0]]
        for key in ('artist', 'album', 'durationLabel', 'type'):
            with self.subTest(key=key):
                self.assertTrue(all(entry[key] is entries[0][key] for entry in entries))

    def test_a_byte_order_mark_is_read_as_json_load_reads_it(self):
        self.path.write_bytes(b'\xef\xbb\xbf' + json.dumps({'version': 1}).encode())
        self.assertEqual(reading_module._read_library(self.path), ({'version': 1}, 0, 'ok'))

    def test_load_starts_reading_before_it_is_awaited(self):
        write_library(self.temp_dir.name, [album('l.a1', 'A1', ['i.1'])])
        started = threading.Event()
        read = model_module._read_library

        def noting_read(path, *args):
            started.set()
            return read(path, *args)

        library = Library()
        with mock.patch.object(model_module, '_read_library', noting_read), \
                mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.temp_dir.name}):
            loading = library.load()
            self.assertTrue(started.wait(5))  # in the library's thread, nothing awaited yet
            asyncio.run(loading)
        self.assertEqual([item.id for item in library.albums], ['l.a1'])

    def test_a_held_parse_waits_for_resume_or_the_limit(self):
        write_library(self.temp_dir.name, [album(f'l.a{n}', 'A', []) for n in range(3)])
        library = Library()
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.temp_dir.name}), \
                mock.patch.object(reading_module, 'HOLD_LIMIT', 5):
            library.hold_reading()
            reading = library._read()
            self.assertRaises(TimeoutError, reading.result, 0.2)  # held at the first album
            library.resume_reading()
            data, _count, _state = reading.result(5)
        self.assertEqual(len(data['sections']['albums']), 3)
        with mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.temp_dir.name}), \
                mock.patch.object(reading_module, 'HOLD_LIMIT', 0.3):
            library.hold_reading()  # never resumed: HOLD_LIMIT in all, not an element
            started = time.monotonic()
            data, _count, _state = library._read().result(5)
        self.assertLess(time.monotonic() - started, 0.6)
        self.assertEqual(len(data['sections']['albums']), 3)


def entry_ids(item):
    return [entry['id'] for group in item['groups'] for entry in group['entries']]


class TestLeaveOut(unittest.TestCase):
    """leave_out(): what a removal takes out of a parsed library.json with it."""

    def test_a_song_goes_from_its_album_its_playlists_and_their_counts(self):
        data = held_library()
        found, removed = reading_module.leave_out(data, {('song', 'i.1')})
        sections = data['sections']
        first = sections['albums'][0]
        self.assertEqual(entry_ids(first), ['i.2'])
        self.assertEqual((first['trackCount'], first['durationMs']), (1, 180000))
        self.assertIn(('song', 'i.1'), found)
        self.assertEqual(removed, {'i.1'})
        # The playlist names it by its catalog id alone: that ref takes its entry.
        self.assertEqual(entry_ids(sections['playlists'][0]), ['i.p1', 'i.3'])
        data = held_library()
        found, removed = reading_module.leave_out(data, {('song', 'i.1'),
                                                         ('song', '1000000001')})
        playlist = data['sections']['playlists'][0]
        self.assertEqual(entry_ids(playlist), ['i.3'])
        self.assertEqual((playlist['trackCount'], playlist['durationMs']), (1, 180000))
        self.assertIn(('song', '1000000001'), found)
        self.assertEqual(removed, {'i.1'})

    def test_an_albums_only_song_takes_the_album_and_its_artist_group(self):
        data = held_library()
        _found, removed = reading_module.leave_out(data, {('song', 'i.3')})
        sections = data['sections']
        self.assertEqual([item['id'] for item in sections['albums']], ['l.a1'])
        self.assertEqual(entry_ids(sections['playlists'][0]), ['i.p1'])
        self.assertEqual(sections['playlists'][0]['trackCount'], 1)
        artist = sections['artists'][0]
        self.assertEqual([group['play']['id'] for group in artist['groups']], ['l.a1'])
        self.assertEqual(artist['albumCount'], 1)
        self.assertEqual([item['id'] for item in data['shelves'][0]['items']], ['i.v1'])
        self.assertEqual(removed, {'i.3'})

    def test_an_album_goes_with_its_songs(self):
        data = held_library()
        found, removed = reading_module.leave_out(data, {('album', 'l.a1')})
        sections = data['sections']
        self.assertEqual([item['id'] for item in sections['albums']], ['l.a2'])
        self.assertEqual(entry_ids(sections['playlists'][0]), ['i.3'])  # by catalog id
        self.assertEqual(found & {('album', 'l.a1')}, {('album', 'l.a1')})
        self.assertEqual(removed, {'i.1', 'i.2'})
        # Both albums gone: so is the artist made of them.
        data = held_library()
        reading_module.leave_out(data, {('album', 'l.a1'), ('album', 'l.a2')})
        self.assertEqual(data['sections']['artists'], [])

    def test_a_video_and_a_playlist(self):
        data = held_library()
        found, removed = reading_module.leave_out(data, {('video', 'i.v1'),
                                                         ('playlist', 'p.pl2')})
        sections = data['sections']
        self.assertEqual(sections['videos'], [])
        self.assertEqual([item['id'] for item in sections['playlists']], ['p.pl1'])
        self.assertEqual([item['id'] for item in data['shelves'][0]['items']], ['l.a2'])
        self.assertEqual(found, {('video', 'i.v1'), ('playlist', 'p.pl2')})
        self.assertEqual(removed, set())

    def test_what_is_not_there_is_not_found(self):
        data = held_library()
        found, removed = reading_module.leave_out(data, {('song', 'i.9'), ('album', 'l.a9')})
        self.assertEqual((found, removed), (set(), set()))
        self.assertEqual(plain(data), plain(held_library()))


if __name__ == '__main__':
    unittest.main()
