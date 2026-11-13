# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What plays: the playback commands the Player sends (play, the queue and its edits, the
controls, previews, autoplay, the streaming quality) and the lyrics of a song."""

import asyncio
import logging
import re

from .. import cache
from .. import lyrics as lyrics_model
from ..backend import cache_files, store
from ..backend.errors import EngineError

log = logging.getLogger(__name__)

PLAY_TIMEOUT = 60.0       # setQueue fetches the queue's items from Apple before playing
LYRICS_TIMEOUT = 30.0     # one catalog read, parsed in the page

# The streaming-quality setting's values and the bitrates (kbps) MusicKit streams them at
# (MusicKit.PlaybackBitrate HIGH and STANDARD), in the order Preferences lists them.
QUALITIES = (('high', 256), ('standard', 64))

# A catalog song id as it appears in a lyrics cache file name: digits, mostly; never a path.
CATALOG_ID_RE = re.compile(r'[A-Za-z0-9._-]{1,64}')


def quality_bitrate(quality):
    """The bitrate (kbps) of a streaming-quality value: 64 for 'standard' (High
    Efficiency), else 256 (High Quality)."""
    return dict(QUALITIES).get(quality, QUALITIES[0][1])


# What control(), shuffle() and repeat() take: the bridge's commands of the same names.
CONTROL_ACTIONS = ('play', 'pause', 'toggle', 'next', 'previous', 'stop')
SHUFFLE_COMMANDS = ('on', 'off', 'toggle')
REPEAT_COMMANDS = ('none', 'one', 'all', 'cycle')


def lyrics_answer(answer, languages=None, format=None):
    """The bridge's lyrics answer, or a kept one, as {synced: bool, lines: [line], languages,
    format}: the lines as lyrics.parse_lines reads them (the one validation: times as
    integers, entities decoded, words that join to their text, in time order), each with the
    fields src/lyrics.py's docstring lists, those that are empty left out (`agent` too,
    unless the song is a duet); anything odd is no lyrics. `languages` are the ones the
    translations and pronunciations were asked in (api.lyrics_languages), else the answer's
    own, else None (a file kept before they were asked for). `format` is the shape the lines
    were read in, lyrics.FORMAT for the bridge's answer, else the answer's own, else 1 (a
    file kept before the words were)."""
    parsed = lyrics_model.parse_lines(answer)
    duet = any(lyrics_model.is_secondary(line.agent) for line in parsed)
    lines = []
    for line in parsed:
        shaped = {'startMs': line.start_ms, 'endMs': line.end_ms, 'text': line.text}
        if line.stanza:
            shaped['stanza'] = True
        for key, value in (('words', line.words), ('background', line.background),
                           ('backgroundWords', line.background_words),
                           ('agent', line.agent if duet else ''),
                           ('pronunciation', line.pronunciation),
                           ('pronunciationWords', line.pronunciation_words),
                           ('pronunciationBackground', line.pronunciation_background),
                           ('pronunciationBackgroundWords',
                            line.pronunciation_background_words),
                           ('translation', line.translation),
                           ('translationBackground', line.translation_background)):
            if value and isinstance(value, str):
                shaped[key] = value
            elif value:
                shaped[key] = [{'startMs': word.start_ms, 'endMs': word.end_ms,
                                'text': word.text} for word in value]
        lines.append(shaped)
    synced = bool(isinstance(answer, dict) and answer.get('synced')) and bool(lines)
    own = answer if isinstance(answer, dict) else {}
    if languages is None and isinstance(own.get('languages'), dict):
        languages = own['languages']
    if format is None:
        kept = own.get('format')
        format = kept if isinstance(kept, int) and not isinstance(kept, bool) else 1
    return {'synced': synced, 'lines': lines, 'languages': languages, 'format': format}


# The bridge's codes for a queue edit it refused, as the engine's.
QUEUE_REFUSALS = {'NOT_EDITABLE': 'queue-locked', 'CURRENT': 'queue-changed',
                  'STALE': 'queue-changed', 'SECTION': 'queue-changed'}


def _edit_number(edit):
    """An edit's number as the bridge takes it: a positive int, else None."""
    return edit if isinstance(edit, int) and not isinstance(edit, bool) and edit > 0 else None


def _queue_index(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _queue_answer(answer, what):
    """A queue edit's answer, or the EngineError its {error, code} means."""
    if not isinstance(answer, dict):
        raise EngineError('api', f'queue {what}: the page gave no answer')
    if answer.get('error'):
        code = QUEUE_REFUSALS.get(answer.get('code'), 'api')
        raise EngineError(code, f'queue {what}: {answer["error"]}')
    return answer


class PlaybackCommands:
    """The Engine's playback commands and lyrics: a mixin of Engine (core.py),
    whose _ready(), _require_signed_in(), _require_widevine(), _send_bitrate(),
    lyrics_languages and cache_dir they use."""

    # -- playback ------------------------------------------------------------------------
    # Thin wrappers over the bridge's methods of the same names, which the Player calls; the
    # outcome shows up as MusicKit events (the `event` signal), which is where the Player
    # takes its state from, not from these answers.

    async def play(self, kind, item_id, start_with=None, shuffle=None, start_id=None,
                   start_time=None, paused=False):
        """Play an album, playlist, station, song, musicVideo or artist (its top songs) by
        id, or `songs` (song ids joined by commas: a stand-in album of loose songs), from
        queue position `start_with` (a track row): the bridge's play(), that is
        mk.setQueue({kind: id, startWith, startPlaying}) and mk.play(). `start_id`, the track
        row's own id, is the item that must play: where MusicKit's queue holds another at
        `start_with`, the bridge moves to the one with that id (logged). `shuffle` True turns
        MusicKit's shuffle on (a Shuffle button), False off (a Play button plays in order),
        None leaves it as it is (a track row). `start_time` (seconds, a restored session's
        position) starts the item that far in: setQueue's startTime, and a seek once it plays
        when MusicKit began it further back (logged). `paused` queues it without playing
        (the start waits for the next control('play')). Needs a signed-in engine: library ids
        and full songs are the account's. MusicKit refusing is EngineError('api') with its
        code as `musickit_code` ('CONTENT_UNAVAILABLE'…)."""
        client = await self._require_signed_in('play')
        if not kind or item_id in (None, ''):
            raise EngineError('usage', 'play needs a kind and an id')
        await self._require_widevine()
        options = {'startWith': int(start_with or 0),
                   'shuffle': None if shuffle is None else bool(shuffle)}
        if start_id:
            options['startId'] = str(start_id)
        if start_time:
            options['startTime'] = max(0.0, float(start_time))
        if paused:
            options['paused'] = True
        answer = await client.bridge('play', str(kind), str(item_id), options,
                                     timeout=PLAY_TIMEOUT)
        if isinstance(answer, dict) and answer.get('error'):
            raise EngineError('api', f'play {kind}: {answer["error"]}',
                              musickit_code=str(answer.get('code') or '') or None)
        moved = answer.get('moved') if isinstance(answer, dict) else None
        if isinstance(moved, dict):
            log.info('play %s: MusicKit queued %s at %s, not %s; moved to %s', kind, start_id,
                     moved.get('to'), moved.get('from'), moved.get('to'))
        if isinstance(answer, dict) and answer.get('sought'):
            log.info('play %s: MusicKit began before %.0f s; sought there', kind, start_time)

    async def play_next(self, kind, item_id):
        """Queue an item right after the one playing (mk.playNext)."""
        client = await self._require_signed_in('play')
        await client.bridge('playNext', str(kind), str(item_id), timeout=PLAY_TIMEOUT)

    async def play_later(self, kind, item_id):
        """Queue an item at the end (mk.playLater)."""
        client = await self._require_signed_in('play')
        await client.bridge('playLater', str(kind), str(item_id), timeout=PLAY_TIMEOUT)

    async def preview(self, song_id, url):
        """Play Apple's 30-second preview of a catalog song, `url` the https address of its
        clip (a suggested song's `previewUrl`): the bridge's preview(), which pauses MusicKit
        and plays the clip in the page's own audio element, so MusicKit's queue stays as it
        was; one at a time, a new one in place of the one before. Its `previewDidChange`
        events, {id} as it plays and {id: None, ended, reason} as it stops, say what plays;
        MusicKit playing again (a play, a control) stops it. Previews are Apple's to anyone:
        no sign-in needed. A clip the page cannot play is EngineError('api') with the
        page's code as `musickit_code`."""
        song_id, url = str(song_id or ''), str(url or '')
        if not song_id or not url.startswith('https://'):
            raise EngineError('usage', 'preview needs a song id and its preview address')
        client = await self._ready()
        answer = await client.bridge('preview', song_id, url, timeout=PLAY_TIMEOUT)
        if isinstance(answer, dict) and answer.get('error'):
            raise EngineError('api', f'preview: {answer["error"]}',
                              musickit_code=str(answer.get('code') or '') or None)

    async def stop_preview(self):
        """Stop the preview playing (preview()), if one is: whether one was."""
        client = await self._ready()
        answer = await client.bridge('stopPreview')
        return bool(isinstance(answer, dict) and answer.get('stopped'))

    async def control(self, action):
        """One of CONTROL_ACTIONS: play, pause, toggle, next, previous, stop."""
        if action not in CONTROL_ACTIONS:
            raise EngineError('usage', f'unknown control action: {action}')
        client = await self._ready()
        await client.bridge('control', action)

    async def seek(self, seconds):
        """Jump to `seconds` into the item playing (mk.seekToTime)."""
        client = await self._ready()
        await client.bridge('seek', max(0.0, float(seconds)))

    async def volume(self, level):
        """Set MusicKit's volume, 0 to 1 (the engine's own, not the system's; Apple's page
        keeps it across restarts). Answers the level as MusicKit has it after the set."""
        client = await self._ready()
        level = min(1.0, max(0.0, float(level)))
        answer = await client.bridge('volume', level)
        value = answer.get('volume') if isinstance(answer, dict) else None
        return float(value) if isinstance(value, (int, float)) else level

    async def shuffle(self, mode):
        """Shuffle on, off or toggle; answers {shuffle: 'on'|'off', repeat: 'none'|'one'|'all'}
        as MusicKit has them after the change."""
        if mode not in SHUFFLE_COMMANDS:
            raise EngineError('usage', f'unknown shuffle mode: {mode}')
        client = await self._ready()
        answer = await client.bridge('shuffle', mode)
        return answer if isinstance(answer, dict) else {}

    async def repeat(self, mode):
        """Repeat none, one, all, or cycle through them; answers as shuffle() does."""
        if mode not in REPEAT_COMMANDS:
            raise EngineError('usage', f'unknown repeat mode: {mode}')
        client = await self._ready()
        answer = await client.bridge('repeat', mode)
        return answer if isinstance(answer, dict) else {}

    async def now_playing(self):
        """What plays: {state, track, position, duration, shuffle, repeat, volume,
        capabilities}, the state MusicKit's PlaybackStates name as playbackStateDidChange
        carries it ('loading', 'playing', 'paused'…; 'stopped' without MusicKit), the track
        the Track shape (or None; `isLive` for a live radio station) and the capabilities
        what MusicKit allows now ({canSeek, canPause, canSkipToNextItem,
        canSkipToPreviousItem, canSetShuffleMode, canSetRepeatMode}; none without
        MusicKit)."""
        client = await self._ready()
        answer = await client.bridge('nowPlaying')
        if not isinstance(answer, dict):
            raise EngineError('api', 'the page gave no now-playing answer')
        return answer

    async def queue(self):
        """The queue: {index, items: [Track…]}."""
        client = await self._ready()
        answer = await client.bridge('queue')
        return answer if isinstance(answer, dict) else {'index': 0, 'items': []}

    async def queue_jump(self, index):
        """Play the queue's entry at `index` (the Up Next list): mk.changeToMediaAtIndex. The
        queue position and now-playing events follow."""
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise EngineError('usage', f'not a queue index: {index!r}')
        client = await self._ready()
        await self._require_widevine()
        await client.bridge('queueJump', index, timeout=PLAY_TIMEOUT)

    async def queue_remove(self, index, entry_id, edit=None):
        """Take the queue's entry at `index` out, when it is still the entry `entry_id` and
        not the item playing (the bridge's queueRemove: queue.spliceQueueItems). One
        queueItemsDidChange follows, its snapshot's `edit` this `edit` (the Player's number
        for the edit, so it knows the snapshot holds it). EngineError('queue-locked') when
        MusicKit allows no edits (a station's queue), 'queue-changed' when the entry there is
        another now (or it is the item playing), 'usage' for an index that is none."""
        if not _queue_index(index) or not entry_id:
            raise EngineError('usage', f'not a queue entry: {index!r}, {entry_id!r}')
        client = await self._ready()
        _queue_answer(await client.bridge('queueRemove', index, str(entry_id),
                                          _edit_number(edit)), 'remove')

    async def queue_move(self, from_index, to_index, entry_id, edit=None):
        """Move the queue's entry at `from_index`, when it is still the entry `entry_id` and
        comes after the item playing, to `to_index` (its index once moved), within its
        section of Up Next (what the user queued, or what autoplay added): the bridge's
        queueMove, two queue.spliceQueueItems, of which only the second's queueItemsDidChange
        is posted, its snapshot's `edit` this `edit`. EngineError('queue-locked') as
        queue_remove(), 'queue-changed' when the entry there is another now, `to_index` is no
        place for it or in the other section, or MusicKit did not take the move; 'usage' for
        an index that is none."""
        if not (_queue_index(from_index) and _queue_index(to_index)) or not entry_id:
            raise EngineError('usage', f'not a queue move: {from_index!r} to {to_index!r}, '
                                       f'{entry_id!r}')
        client = await self._ready()
        _queue_answer(await client.bridge('queueMove', from_index, to_index, str(entry_id),
                                          _edit_number(edit)), 'move')

    async def queue_clear(self):
        """Take everything after the item playing out of the queue (the bridge's queueClear:
        queue.clearAfterCurrent), keeping it in the page for queue_undo_clear(). How many
        entries went. EngineError('queue-locked') as queue_remove()."""
        client = await self._ready()
        answer = _queue_answer(await client.bridge('queueClear'), 'clear')
        cleared = answer.get('cleared')
        return cleared if isinstance(cleared, int) else 0

    async def queue_undo_clear(self):
        """Put the entries the last queue_clear() took back after the item playing, while
        it is the item it was. How many came back; EngineError('queue-changed') when there is
        nothing to put back, or another item plays now."""
        client = await self._ready()
        answer = _queue_answer(await client.bridge('queueUndoClear'), 'undo clear')
        restored = answer.get('restored')
        return restored if isinstance(restored, int) else 0

    async def set_autoplay(self, on):
        """MusicKit's autoplay on or off (mk.autoplayEnabled), or only read (None): the
        page's own switch, which the web player sets from its local storage as it loads.
        Answers {autoplay, canAutoplay} as MusicKit has them after the set."""
        client = await self._ready()
        answer = await client.bridge('autoplay', None if on is None else bool(on))
        if not isinstance(answer, dict):
            return {'autoplay': bool(on), 'canAutoplay': True}
        return {'autoplay': bool(answer.get('autoplay')),
                'canAutoplay': answer.get('canAutoplay') is not False}

    async def set_bitrate(self, kbps):
        """The streaming bitrate (256 or 64 kbps: quality_bitrate()) set on MusicKit
        (mk.bitrate) now, and kept as `preferred_bitrate` for every start and page load to
        come, even when this raises (EngineError('engine-down') with the engine down). Answers
        the bitrate MusicKit has after the set, as `bitrate` (0: the page says none)."""
        self.preferred_bitrate = kbps
        client = await self._ready()
        return await self._send_bitrate(client)

    def lyrics_path(self, catalog_song_id):
        """Where a song's lyrics are kept: <cache>/lyrics/<catalog id>.json."""
        return self.cache_dir / 'lyrics' / f'{catalog_song_id}.json'

    async def lyrics(self, catalog_song_id):
        """A catalog song's lyrics: {synced, lines: [{startMs, endMs, text, words?,
        background?, agent?, pronunciation?, translation?…}], languages, format}
        (lyrics_answer's shape), from <cache>/lyrics/<id>.json when they were fetched in the
        last cache_files.LYRICS_MAX_AGE in today's lyrics.FORMAT, with their translations and
        pronunciations in `lyrics_languages` (no engine needed then; the read marks the
        file as played, for prune_caches), else through the bridge (the catalog's TTML with
        its translations and transliterations, parsed in the page) and kept there, stamped,
        when Apple had any. A file kept in other languages or an older format (or before
        either was kept) is still the answer when the engine cannot give a new one. No
        lyrics ({synced: False, lines: []}) is also what the page answers when Apple refuses
        (no subscription, a network failure), so an empty answer is not kept: the next play
        asks again."""
        generation = store.cache_generation()
        catalog_song_id = str(catalog_song_id or '')
        if not CATALOG_ID_RE.fullmatch(catalog_song_id):
            raise EngineError('usage', 'lyrics need a catalog song id')
        languages = dict(self.lyrics_languages)
        path = self.lyrics_path(catalog_song_id)
        cached = await asyncio.to_thread(cache.read_kept, path, cache_files.LYRICS_MAX_AGE, True)
        kept = lyrics_answer(cached) if cached is not None and cached.get('lines') else None
        if (kept is not None and kept['languages'] == languages
                and kept['format'] == lyrics_model.FORMAT):
            return kept
        try:
            client = await self._ready()
            answer = lyrics_answer(
                await client.bridge('lyrics', catalog_song_id, languages, timeout=LYRICS_TIMEOUT),
                languages, lyrics_model.FORMAT)
        except EngineError:
            if kept is None:
                raise
            return kept
        if answer['lines']:
            await asyncio.to_thread(cache_files.write_answer, str(path), answer,
                                    str(self.cache_dir), generation)
        elif kept is not None:
            return kept
        return answer
