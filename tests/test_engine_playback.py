# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Unit tests for src/engine/playback.py: the playback commands, lyrics and previews."""

import asyncio
import json
import os
import unittest

from tests import ROOT, SRC  # noqa: F401  (registers src/ as the applemusic package)


from applemusic import engine as engine_module
from applemusic.backend import cache_files
from applemusic.backend import client as client_module
from applemusic.backend.errors import EngineError
from applemusic.engine import playback as playback_module
from tests.engine_fixture import EngineFixture
from tests.test_client import context_created, until


class PlaybackTest(EngineFixture):
    """The playback commands: thin calls into the bridge, their arguments as the bridge takes
    them, their answers shaped, and the errors when the engine is down or signed out."""

    async def up(self, authorized=True):
        self.page.authorized = authorized
        await self.engine.start()

    async def test_play_sends_kind_id_and_options(self):
        await self.up()
        await self.engine.play('album', 'l.alb1')
        await self.engine.play('playlist', 'p.pl1', start_with=3)
        await self.engine.play('station', 'ra.1', shuffle=True)
        await self.engine.play('album', 'l.alb1', shuffle=False)
        self.assertEqual(self.page.bridge_calls, [
            ('play', 'album', 'l.alb1', {'startWith': 0, 'shuffle': None}),   # as it is
            ('play', 'playlist', 'p.pl1', {'startWith': 3, 'shuffle': None}),
            ('play', 'station', 'ra.1', {'startWith': 0, 'shuffle': True}),
            ('play', 'album', 'l.alb1', {'startWith': 0, 'shuffle': False}),  # in order
        ])

    async def test_a_track_row_names_the_item_that_must_play(self):
        await self.up()
        self.page.bridge_answers['play'] = {'ok': True, 'moved': {'from': 2, 'to': 3}}
        with self.assertLogs('applemusic.engine', 'INFO') as logged:
            await self.engine.play('album', 'l.alb1', start_with=2, start_id='i.song3')
        self.assertEqual(self.page.bridge_calls[-1], (
            'play', 'album', 'l.alb1', {'startWith': 2, 'shuffle': None, 'startId': 'i.song3'}))
        self.assertIn('moved to 3', logged.output[0])

    async def test_a_restored_session_starts_at_its_position_or_waits_paused(self):
        await self.up()
        self.page.bridge_answers['play'] = {'ok': True, 'sought': True}
        with self.assertLogs('applemusic.engine', 'INFO') as logged:
            await self.engine.play('songs', 'i.a,i.b', start_with=1, shuffle=False,
                                   start_id='i.b', start_time=83)
        self.assertIn('sought there', logged.output[0])
        self.page.bridge_answers['play'] = {'ok': True}
        await self.engine.play('album', 'l.alb1', start_with=1, start_id='i.b',
                               start_time=83.5, paused=True)
        self.assertEqual(self.page.bridge_calls[-2:], [
            ('play', 'songs', 'i.a,i.b', {'startWith': 1, 'shuffle': False, 'startId': 'i.b',
                                          'startTime': 83.0}),
            ('play', 'album', 'l.alb1', {'startWith': 1, 'shuffle': None, 'startId': 'i.b',
                                         'startTime': 83.5, 'paused': True}),
        ])

    async def test_a_refused_play_carries_musickits_code(self):
        await self.up()
        self.page.bridge_answers['play'] = {'error': 'Content unavailable',
                                            'code': 'CONTENT_UNAVAILABLE'}
        with self.assertRaises(EngineError) as raised:
            await self.engine.play('album', '1000000002')
        error = raised.exception
        self.assertEqual((error.code, error.musickit_code), ('api', 'CONTENT_UNAVAILABLE'))
        self.assertIn('Content unavailable', error.message)
        self.page.bridge_answers['play'] = {'error': 'Something odd', 'code': ''}
        with self.assertRaises(EngineError) as raised:
            await self.engine.play('album', '1000000002')
        self.assertIsNone(raised.exception.musickit_code)

    async def test_play_needs_a_signed_in_engine(self):
        with self.assertRaises(EngineError) as raised:
            await self.engine.play('album', 'l.alb1')
        self.assertEqual(raised.exception.code, 'engine-down')
        await self.up(authorized=False)
        with self.assertRaises(EngineError) as raised:
            await self.engine.play('album', 'l.alb1')
        self.assertEqual(raised.exception.code, 'not-signed-in')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_play_needs_a_target(self):
        await self.up()
        for kind, item_id in (('', 'x'), (None, 'x'), ('album', ''), ('album', None)):
            with self.assertRaises(EngineError) as raised:
                await self.engine.play(kind, item_id)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_a_browser_without_widevine_plays_no_song(self):
        self.page.widevine = False
        with self.assertLogs('applemusic.engine', 'WARNING') as logged:
            await self.up()
            await until(lambda: not self.engine.widevine)
        self.assertIn('cannot decrypt Widevine (Unsupported keySystem', logged.output[0])
        self.assertEqual(self.engine.state, 'up')  # the library, browsing and previews need none
        for play in (self.engine.play('album', 'l.alb1'), self.engine.queue_jump(2)):
            with self.assertRaises(EngineError) as raised:
                await play
            self.assertEqual(raised.exception.code, 'no-widevine')
        await self.engine.preview('1724049301', 'https://example.invalid/tin-roof.m4a')
        self.assertEqual([call[0] for call in self.page.bridge_calls], ['preview'])

    async def test_a_play_waits_for_the_widevine_check(self):
        self.page.widevine = False
        with self.assertLogs('applemusic.engine', 'WARNING'):
            await self.up()
            # At once, before the check has answered: the play waits for it, then refuses.
            with self.assertRaises(EngineError) as raised:
                await self.engine.play('album', 'l.alb1')
        self.assertEqual(raised.exception.code, 'no-widevine')
        self.assertEqual(self.page.bridge_calls, [])

    async def test_widevine_is_asked_once_per_start(self):
        self.page.widevine = False
        with self.assertLogs('applemusic.engine', 'WARNING'):
            await self.up()
            await until(lambda: not self.engine.widevine)
        self.page.widevine = True   # another browser, named in Preferences
        await self.engine.restart()
        await self.engine.play('album', 'l.alb1')
        self.assertTrue(self.engine.widevine)
        self.assertEqual(self.page.drm_reads, 2)
        await self.engine.status()
        self.assertEqual(self.page.drm_reads, 2)

    async def test_a_check_that_cannot_answer_lets_songs_play(self):
        self.page.widevine = None
        await self.up()
        await self.engine.play('album', 'l.alb1')
        self.assertTrue(self.engine.widevine)
        self.assertEqual(self.page.drm_reads, 1)
        self.assertEqual(self.page.bridge_calls[0][0], 'play')

    async def test_play_next_and_later(self):
        await self.up()
        await self.engine.play_next('song', 'i.1')
        await self.engine.play_later('album', 'l.2')
        self.assertEqual(self.page.bridge_calls,
                         [('playNext', 'song', 'i.1'), ('playLater', 'album', 'l.2')])

    async def test_control_seek_volume(self):
        await self.up()
        for action in playback_module.CONTROL_ACTIONS:
            await self.engine.control(action)
        await self.engine.seek(42)
        await self.engine.seek(-3)
        self.page.bridge_answers['volume'] = {'volume': 0.5}
        self.assertEqual(await self.engine.volume(0.5), 0.5)
        self.page.bridge_answers['volume'] = None  # not a dict: the level asked for
        self.assertEqual(await self.engine.volume(2), 1.0)
        self.assertEqual(self.page.bridge_calls, [
            ('control', 'play'), ('control', 'pause'), ('control', 'toggle'),
            ('control', 'next'), ('control', 'previous'), ('control', 'stop'),
            ('seek', 42.0), ('seek', 0.0), ('volume', 0.5), ('volume', 1.0)])
        with self.assertRaises(EngineError) as raised:
            await self.engine.control('rewind')
        self.assertEqual(raised.exception.code, 'usage')

    async def test_shuffle_and_repeat(self):
        await self.up()
        self.page.bridge_answers['shuffle'] = {'shuffle': 'on', 'repeat': 'none'}
        self.page.bridge_answers['repeat'] = {'shuffle': 'on', 'repeat': 'all'}
        self.assertEqual(await self.engine.shuffle('toggle'), {'shuffle': 'on', 'repeat': 'none'})
        self.assertEqual(await self.engine.repeat('cycle'), {'shuffle': 'on', 'repeat': 'all'})
        self.assertEqual(self.page.bridge_calls, [('shuffle', 'toggle'), ('repeat', 'cycle')])
        for method, mode in (('shuffle', 'maybe'), ('repeat', 'twice')):
            with self.assertRaises(EngineError) as raised:
                await getattr(self.engine, method)(mode)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_now_playing_and_queue(self):
        await self.up()
        answer = {'state': 'playing', 'track': {'id': 'i.1', 'title': 'Harbour Lights'},
                  'position': 3, 'duration': 200, 'shuffle': 'off', 'repeat': 'none',
                  'volume': 1}
        self.page.bridge_answers['nowPlaying'] = answer
        self.page.bridge_answers['queue'] = {'index': 1, 'items': [{'id': 'i.0'}, {'id': 'i.1'}]}
        self.assertEqual(await self.engine.now_playing(), answer)
        self.assertEqual((await self.engine.queue())['index'], 1)
        self.assertEqual(self.page.bridge_calls, [('nowPlaying',), ('queue',)])
        self.page.bridge_answers['nowPlaying'] = None
        with self.assertRaises(EngineError) as raised:
            await self.engine.now_playing()
        self.assertEqual(raised.exception.code, 'api')

    async def test_queue_jump(self):
        await self.up()
        await self.engine.queue_jump(3)
        self.assertEqual(self.page.bridge_calls, [('queueJump', 3)])
        for index in (-1, 'x', None, 2.5, True):
            with self.assertRaises(EngineError) as raised:
                await self.engine.queue_jump(index)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_queue_edits(self):
        await self.up()
        await self.engine.queue_remove(4, 'i.abc')
        await self.engine.queue_remove(4, 'i.abc', edit=7)
        await self.engine.queue_move(4, 2, 'i.abc', edit=8)
        await self.engine.queue_move(2, 5, 'i.abc', edit=True)  # not a number: none
        self.page.bridge_answers['queueClear'] = {'ok': True, 'cleared': 3}
        self.assertEqual(await self.engine.queue_clear(), 3)
        self.page.bridge_answers['queueUndoClear'] = {'ok': True, 'restored': 3}
        self.assertEqual(await self.engine.queue_undo_clear(), 3)
        self.assertEqual(self.page.bridge_calls, [('queueRemove', 4, 'i.abc', None),
                                                  ('queueRemove', 4, 'i.abc', 7),
                                                  ('queueMove', 4, 2, 'i.abc', 8),
                                                  ('queueMove', 2, 5, 'i.abc', None),
                                                  ('queueClear',), ('queueUndoClear',)])
        for bad in ((-1, 'i.a'), ('1', 'i.a'), (True, 'i.a'), (2, '')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.queue_remove(*bad)
            self.assertEqual(raised.exception.code, 'usage')
        for bad in ((-1, 2, 'i.a'), (2, -1, 'i.a'), (2, '3', 'i.a'), (False, 2, 'i.a'),
                    (2, 3, '')):
            with self.assertRaises(EngineError) as raised:
                await self.engine.queue_move(*bad)
            self.assertEqual(raised.exception.code, 'usage')
        refusals = {'NOT_EDITABLE': 'queue-locked', 'CURRENT': 'queue-changed',
                    'STALE': 'queue-changed', 'SECTION': 'queue-changed', 'ODD': 'api'}
        for refusal, code in refusals.items():
            self.page.bridge_answers['queueRemove'] = {'error': 'no', 'code': refusal}
            self.page.bridge_answers['queueMove'] = {'error': 'no', 'code': refusal}
            with self.assertRaises(EngineError) as raised:
                await self.engine.queue_remove(2, 'i.a')
            self.assertEqual(raised.exception.code, code, refusal)
            with self.assertRaises(EngineError) as raised:
                await self.engine.queue_move(2, 3, 'i.a')
            self.assertEqual(raised.exception.code, code, refusal)
        self.page.bridge_answers['queueUndoClear'] = {'error': 'nothing', 'code': 'STALE'}
        with self.assertRaises(EngineError) as raised:
            await self.engine.queue_undo_clear()
        self.assertEqual(raised.exception.code, 'queue-changed')

    async def test_autoplay(self):
        await self.up()
        self.page.bridge_answers['autoplay'] = {'autoplay': True, 'canAutoplay': False}
        self.assertEqual(await self.engine.set_autoplay(True),
                         {'autoplay': True, 'canAutoplay': False})
        self.page.bridge_answers['autoplay'] = None   # not a dict: what was asked
        self.assertEqual(await self.engine.set_autoplay(False),
                         {'autoplay': False, 'canAutoplay': True})
        await self.engine.set_autoplay(None)
        self.assertEqual(self.page.bridge_calls, [('autoplay', True), ('autoplay', False),
                                                  ('autoplay', None)])

    async def test_the_bitrate_is_kept_and_followed(self):
        self.assertEqual(playback_module.quality_bitrate('high'), 256)
        self.assertEqual(playback_module.quality_bitrate('standard'), 64)
        self.assertEqual(playback_module.quality_bitrate('lossless'), 256)
        await self.up()
        await until(lambda: not self.engine._tasks)  # what runs beside the start is done
        self.assertEqual(self.engine.bitrate, 256)  # the start's status read
        self.assertEqual(self.page.bitrate_calls, [])  # MusicKit has it already
        self.assertEqual(await self.engine.set_bitrate(64), 64)
        self.assertEqual((self.page.bitrate_calls, self.engine.bitrate), ([64], 64))
        self.assertEqual(self.engine.preferred_bitrate, 64)
        # MusicKit's own choice (a slow connection), as its event says.
        await self.chrome.send_binding('playbackBitrateDidChange', {'bitrate': 256})
        await until(lambda: self.engine.bitrate == 256)
        await self.engine.stop()
        self.assertEqual(self.engine.bitrate, 0)
        with self.assertRaises(EngineError) as raised:
            await self.engine.set_bitrate(256)
        self.assertEqual(raised.exception.code, 'engine-down')
        self.assertEqual(self.engine.preferred_bitrate, 256)  # kept for the next start

    async def test_the_preferred_bitrate_is_set_at_each_start_and_page_load(self):
        self.engine.preferred_bitrate = 64
        await self.up()
        await until(lambda: self.engine.bitrate == 64)
        self.assertEqual(self.page.bitrate_calls, [64])
        # A new document: MusicKit there starts at its own, and is set again.
        seen = []
        self.engine.connect('event', lambda e, name, data: seen.append(name))
        self.page.bitrate = 256
        self.page.bridge = None
        await self.chrome.send_event(*context_created(9))
        await until(lambda: 'bridgeReset' in seen, timeout=3)
        await until(lambda: self.page.bitrate_calls == [64, 64])
        await until(lambda: self.engine.bitrate == 64)
        # A page that refuses (MusicKit gone) leaves the engine up, the bitrate as it was.
        self.page.bitrate_calls.clear()
        self.page.bitrate = 256
        self.page.bridge = None
        self.page.ready = False
        self.engine._client.reinject_timeout = 0.05
        seen.clear()
        with self.assertLogs(client_module.log, 'WARNING'):
            await self.chrome.send_event(*context_created(10))
            await asyncio.sleep(0.1)
            self.page.ready = True
            await until(lambda: 'bridgeReset' in seen, timeout=3)
        await until(lambda: self.page.bitrate_calls == [64])
        self.assertEqual(self.engine.state, 'up')

    LANGUAGES = {'lyrics': 'en-GB', 'script': 'en-Latn'}

    async def up_for_lyrics(self):
        await self.up()
        self.engine.lyrics_languages = dict(self.LANGUAGES)

    async def test_lyrics_are_fetched_once_and_kept(self):
        await self.up_for_lyrics()
        answer = {'synced': True, 'lines': [
            {'startMs': 1000, 'endMs': 3000.4, 'text': ' Harbour lights ',
             'pronunciation': ' Minato no akari '},
            {'startMs': 'x', 'text': ''},
            {'startMs': 4000, 'endMs': 6000, 'text': 'Out on the water',
             'pronunciation': 'Out on the water'}]}  # the same as the line: none
        self.page.bridge_answers['lyrics'] = answer
        lyrics = await self.engine.lyrics('1000000001')
        self.assertEqual(lyrics, {'synced': True, 'languages': self.LANGUAGES, 'format': 2,
                                  'lines': [
            {'startMs': 1000, 'endMs': 3000, 'text': 'Harbour lights',
             'pronunciation': 'Minato no akari'},
            {'startMs': 4000, 'endMs': 6000, 'text': 'Out on the water'}]})
        path = self.cache / 'lyrics' / '1000000001.json'
        self.assertTrue(path.is_file())
        kept = json.loads(path.read_text(encoding='utf-8'))
        self.assertIn('cached', kept)  # stamped: lyrics expire
        self.assertEqual({key: kept[key] for key in ('synced', 'lines', 'languages', 'format')},
                         lyrics)
        # Again: from the file, no bridge call, and no engine needed.
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': []}
        self.assertEqual(await self.engine.lyrics('1000000001'), lyrics)
        await self.engine.stop()
        self.assertEqual(await self.engine.lyrics('1000000001'), lyrics)
        # The bridge is told the language and the script the extras are asked in.
        self.assertEqual(self.page.bridge_calls, [('lyrics', '1000000001', self.LANGUAGES)])

    async def test_lyrics_kept_in_other_languages_are_asked_again(self):
        await self.up_for_lyrics()
        path = self.cache / 'lyrics' / '1000000006.json'
        older = {'synced': False, 'lines': [{'startMs': 0, 'endMs': 0, 'text': 'Kept'}]}
        cache_files.write_answer(str(path), older, str(self.cache))  # before pronunciations
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': [
            {'startMs': 0, 'endMs': 0, 'text': '\u6f6e', 'pronunciation': 'Shio',
             'translation': 'Tide'}]}
        lyrics = await self.engine.lyrics('1000000006')
        self.assertEqual((lyrics['lines'][0]['pronunciation'], lyrics['lines'][0]['translation']),
                         ('Shio', 'Tide'))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['languages'],
                         self.LANGUAGES)
        # A Japanese user's pronunciations are another script's: asked again, in theirs.
        japanese = {'lyrics': 'ja-JP', 'script': 'ja-Kana'}
        self.engine.lyrics_languages = dict(japanese)
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': [
            {'startMs': 0, 'endMs': 0, 'text': '\u6f6e', 'pronunciation': '\u3057\u304a'}]}
        self.assertEqual((await self.engine.lyrics('1000000006'))['languages'], japanese)
        self.assertEqual(len(self.page.bridge_calls), 2)
        # With the engine down, the file kept in another script is still the answer.
        self.engine.lyrics_languages = dict(self.LANGUAGES)
        await self.engine.stop()
        kept = await self.engine.lyrics('1000000006')
        self.assertEqual((kept['languages'], kept['lines'][0]['pronunciation']),
                         (japanese, '\u3057\u304a'))
        # And when Apple answers none this time (refused), the kept one.
        await self.up_for_lyrics()
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': []}
        self.assertEqual((await self.engine.lyrics('1000000006'))['languages'], japanese)
        # Never a file at all, and the engine down: the engine's error.
        await self.engine.stop()
        with self.assertRaises(EngineError) as raised:
            await self.engine.lyrics('1000000007')
        self.assertEqual(raised.exception.code, 'engine-down')

    async def test_lyrics_carry_words_background_vocals_and_singers(self):
        await self.up_for_lyrics()

        def words(*pieces):
            return [{'startMs': start, 'endMs': end, 'text': text}
                    for start, end, text in pieces]
        self.page.bridge_answers['lyrics'] = {'synced': True, 'lines': [
            {'startMs': 1000, 'endMs': 4000, 'text': 'Harbour lights', 'agent': 'v1',
             'words': words((1000, 1500, 'Har'), (1500, 2000, 'bour '), (2000, 3000, 'lights')),
             'background': '(lights)', 'backgroundWords': words((3000, 4000, '(lights)'))},
            {'startMs': 5000, 'endMs': 8000, 'text': '\u6f6e', 'agent': 'v2',
             'words': words((5000, 6000, 'Tide')),            # not the text: no words
             'pronunciation': 'Shio', 'pronunciationWords': words((5000, 6000, 'Shio')),
             'pronunciationBackground': '', 'translation': 'Tide',
             'translationBackground': '(tide)'}]}
        lyrics = await self.engine.lyrics('1000000010')
        self.assertEqual(lyrics['lines'], [
            {'startMs': 1000, 'endMs': 4000, 'text': 'Harbour lights', 'agent': 'v1',
             'words': words((1000, 1500, 'Har'), (1500, 2000, 'bour '), (2000, 3000, 'lights')),
             'background': '(lights)', 'backgroundWords': words((3000, 4000, '(lights)'))},
            {'startMs': 5000, 'endMs': 8000, 'text': '\u6f6e', 'agent': 'v2',
             'pronunciation': 'Shio', 'pronunciationWords': words((5000, 6000, 'Shio')),
             'translation': 'Tide', 'translationBackground': '(tide)'}])
        kept = json.loads((self.cache / 'lyrics' / '1000000010.json').read_text('utf-8'))
        self.assertEqual((kept['lines'], kept['format']), (lyrics['lines'], 2))
        # One singer only: no agents kept.
        self.page.bridge_answers['lyrics'] = {'synced': True, 'lines': [
            {'startMs': 1000, 'text': 'One', 'agent': 'v1'},
            {'startMs': 2000, 'text': 'Two', 'agent': 'v1'}]}
        solo = await self.engine.lyrics('1000000011')
        self.assertEqual([sorted(line) for line in solo['lines']],
                         [['endMs', 'startMs', 'text']] * 2)

    async def test_lyrics_kept_in_an_older_format_are_asked_again(self):
        await self.up_for_lyrics()
        older = {'synced': True, 'languages': self.LANGUAGES, 'lines': [
            {'startMs': 1000, 'endMs': 3000, 'text': 'Harbour lights (lights)'}]}
        path = self.cache / 'lyrics' / '1000000012.json'
        cache_files.write_answer(str(path), older, str(self.cache))  # before the words
        self.assertEqual(playback_module.lyrics_answer(older)['format'], 1)
        self.page.bridge_answers['lyrics'] = {'synced': True, 'lines': [
            {'startMs': 1000, 'endMs': 3000, 'text': 'Harbour lights',
             'background': '(lights)'}]}
        lyrics = await self.engine.lyrics('1000000012')
        self.assertEqual((lyrics['format'], lyrics['lines'][0]['background']), (2, '(lights)'))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['format'], 2)
        self.assertEqual(len(self.page.bridge_calls), 1)
        # Kept now: not asked again.
        await self.engine.lyrics('1000000012')
        self.assertEqual(len(self.page.bridge_calls), 1)
        # An older file is still the answer while the engine cannot give a new one, and
        # when Apple answers none.
        path = self.cache / 'lyrics' / '1000000013.json'
        cache_files.write_answer(str(path), older, str(self.cache))
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': []}
        kept = await self.engine.lyrics('1000000013')
        self.assertEqual((kept['format'], kept['lines'][0]['text']),
                         (1, 'Harbour lights (lights)'))
        await self.engine.stop()
        self.assertEqual((await self.engine.lyrics('1000000013'))['format'], 1)
        # A format that is not a number is the oldest.
        for odd in ('2', True, None, 2.0):
            self.assertEqual(playback_module.lyrics_answer(dict(older, format=odd))['format'],
                             1, odd)

    async def test_lyrics_are_decoded_even_when_kept_before(self):
        await self.up_for_lyrics()
        self.page.bridge_answers['lyrics'] = {'synced': True, 'lines': [
            {'startMs': 1000, 'endMs': 2000, 'text': 'Rock &amp; Roll &#8217;til dawn',
             'stanza': True},
            {'startMs': 2000, 'endMs': 3000, 'text': 'Again', 'stanza': False}]}
        lyrics = await self.engine.lyrics('1000000004')
        self.assertEqual(lyrics['lines'], [
            {'startMs': 1000, 'endMs': 2000, 'text': 'Rock & Roll \u2019til dawn',
             'stanza': True},
            {'startMs': 2000, 'endMs': 3000, 'text': 'Again'}])
        # A file an older version kept with the entities in it reads decoded.
        path = self.cache / 'lyrics' / '1000000005.json'
        cache_files.write_answer(str(path), {'synced': False, 'languages': self.LANGUAGES,
                                             'format': 2, 'lines': [
            {'startMs': 0, 'endMs': 0, 'text': 'Salt &amp; &quot;air&quot;',
             'pronunciation': 'Shio &amp; kaze'}]}, str(self.cache))
        line = (await self.engine.lyrics('1000000005'))['lines'][0]
        self.assertEqual((line['text'], line['pronunciation']), ('Salt & "air"', 'Shio & kaze'))
        self.assertEqual(len(self.page.bridge_calls), 1)

    async def test_lyrics_expire_and_a_hit_marks_them_played(self):
        await self.up_for_lyrics()
        answer = {'synced': False, 'lines': [{'startMs': 0, 'endMs': 0, 'text': 'Tide'}]}
        self.page.bridge_answers['lyrics'] = answer
        await self.engine.lyrics('1000000003')
        path = self.cache / 'lyrics' / '1000000003.json'
        os.utime(path, (1000, 1000))
        await self.engine.lyrics('1000000003')  # kept: no new call, and marked as played
        self.assertEqual(len(self.page.bridge_calls), 1)
        self.assertGreater(path.stat().st_mtime, 1000)
        # Fetched longer ago than a month: asked again.
        kept = json.loads(path.read_text())
        kept['cached'] = '2020-01-01T00:00:00Z'
        path.write_text(json.dumps(kept))
        await self.engine.lyrics('1000000003')
        self.assertEqual(len(self.page.bridge_calls), 2)
        # A file an older version wrote, without a stamp, is asked again too.
        path.write_text(json.dumps(answer))
        await self.engine.lyrics('1000000003')
        self.assertEqual(len(self.page.bridge_calls), 3)

    async def test_no_lyrics_are_not_kept(self):
        await self.up_for_lyrics()
        none = {'synced': False, 'lines': [], 'languages': self.LANGUAGES, 'format': 2}
        self.page.bridge_answers['lyrics'] = {'synced': False, 'lines': []}
        self.assertEqual(await self.engine.lyrics('1000000002'), none)
        self.page.bridge_answers['lyrics'] = None  # not a dict either
        self.assertEqual(await self.engine.lyrics('1000000002'), none)
        self.assertFalse((self.cache / 'lyrics').exists())
        self.assertEqual(len(self.page.bridge_calls), 2)
        for bad in ('', None, '../x', 'a/b'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.lyrics(bad)
            self.assertEqual(raised.exception.code, 'usage')

    async def test_commands_when_down(self):
        for coro in (self.engine.control('toggle'), self.engine.seek(1), self.engine.volume(1),
                     self.engine.shuffle('on'), self.engine.repeat('all'),
                     self.engine.now_playing(), self.engine.queue(),
                     self.engine.play_next('song', 'i.1'), self.engine.queue_jump(0),
                     self.engine.queue_remove(1, 'i.1'), self.engine.queue_move(1, 2, 'i.1'),
                     self.engine.queue_clear(),
                     self.engine.queue_undo_clear(), self.engine.set_autoplay(True),
                     self.engine.lyrics('1000000001'), self.engine.search('x'),
                     self.engine.suggest('x'), self.engine.landing(), self.engine.category('1'),
                     self.engine.browse(), self.engine.made_for_you()):
            with self.assertRaises(EngineError) as raised:
                await coro
            self.assertEqual(raised.exception.code, 'engine-down')


class PreviewTest(EngineFixture):
    """preview and stop_preview: the bridge's calls, a clip the page refuses, no sign-in."""

    async def test_preview_and_stop(self):
        await self.engine.start()  # not signed in: a preview is anyone's
        await self.engine.preview(1724049301, 'https://example.invalid/tin-roof.m4a')
        self.page.bridge_answers['stopPreview'] = {'stopped': True}
        self.assertTrue(await self.engine.stop_preview())
        self.page.bridge_answers['stopPreview'] = {'stopped': False}
        self.assertFalse(await self.engine.stop_preview())
        self.assertEqual(self.page.bridge_calls, [
            ('preview', '1724049301', 'https://example.invalid/tin-roof.m4a'),
            ('stopPreview',), ('stopPreview',)])

    async def test_a_clip_the_page_cannot_play(self):
        await self.engine.start()
        self.page.bridge_answers['preview'] = {'error': 'denied', 'code': 'NotAllowedError'}
        with self.assertRaises(EngineError) as raised:
            await self.engine.preview('1724049301', 'https://example.invalid/tin-roof.m4a')
        self.assertEqual((raised.exception.code, raised.exception.musickit_code),
                         ('api', 'NotAllowedError'))
        for url in ('', 'http://example.invalid/tin-roof.m4a'):
            with self.assertRaises(EngineError) as raised:
                await self.engine.preview('1724049301', url)
            self.assertEqual(raised.exception.code, 'usage')
        self.assertEqual(len(self.page.bridge_calls), 1)

    async def test_down_or_demo(self):
        with self.assertRaises(EngineError) as raised:
            await self.engine.preview('1724049301', 'https://example.invalid/tin-roof.m4a')
        self.assertEqual(raised.exception.code, 'engine-down')
        with self.assertRaises(EngineError) as raised:
            await engine_module.Engine(demo=True).stop_preview()
        self.assertEqual(raised.exception.code, 'engine-down')


if __name__ == '__main__':
    unittest.main()
