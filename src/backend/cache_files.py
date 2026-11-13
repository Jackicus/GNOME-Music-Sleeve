# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the cache keeps: library.json and the answers the engine keeps for a
day, and pruning what nothing else trims.

Where each kept answer lives (the *_cache_path functions), its stamps (stamp_answer(): when
it was written and in what shape), writing, patching and reading it, and when it is fresh
(answer_current(), answer_expired()); save_library() for library.json; and the pruners:
prune_art() against the library, prune_remote_art() to its budget, prune_caches() for the
rest. Every write goes through store.py. The standard library only.
"""

import json
import logging
import os
import re
import time
from datetime import UTC, datetime

from . import store
from .art_cache import collect_art_paths

log = logging.getLogger(__name__)


# How long a kept answer (landing, a category, the New page, Made for You, Charts, Replay) is
# answered from the cache before Apple is asked again, and a song's lyrics (Apple replaces
# plain lyrics with synced ones, and corrects them).
ANSWER_MAX_AGE = 24 * 60 * 60
LYRICS_MAX_AGE = 30 * 24 * 60 * 60
# How long prune_caches() leaves a kept answer: past its day it is no longer fresh, but it is
# what the engine answers, marked stale, when Apple cannot be asked (the engine down, signed
# out, offline), so it stays until an answer from Apple replaces it, or for this long.
ANSWER_KEEP_AGE = 30 * 24 * 60 * 60
# The shape of the answers this version keeps (write_answer stamps it as `shape`). One kept by
# a version that shaped them otherwise (another `shape`, or none: 1) is not fresh, whatever
# its age (Engine._kept_answer asks Apple again), and is answered only when Apple cannot be
# asked, stale. Bump it when a shaper's answer carries something new: 2, New's banners and
# links, and a catalog playlist's More By the curator.
ANSWER_SHAPE = 2

# What prune_caches() leaves of the caches that only grow: the covers the pages fetch
# themselves, and the lyrics of the songs played last.
REMOTE_ART_BUDGET = 32 * 1024 * 1024
LYRICS_KEEP = 2000
# The day-long answers in the cache's top folder, beside categories/.
KEPT_ANSWERS = ('landing.json', 'browse.json', 'made-for-you.json', 'radio.json', 'charts.json',
                'genres.json', 'replay.json', 'recent-played.json')
# The folders of day-long answers, one file an item.
ANSWER_FOLDERS = ('categories', 'artists', 'albums', 'playlists', 'suggestions', 'credits',
                  'rooms', 'groupings', 'multirooms', 'charts', 'replay')


STAMP_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def answer_current(answer):
    """Whether a kept answer is in the shape this version keeps (ANSWER_SHAPE): one from
    an older version is not fresh, whatever its age."""
    return isinstance(answer, dict) and answer.get('shape', 1) == ANSWER_SHAPE


def answer_expired(answer, now=None):
    """Whether a kept answer's `expires` stamp (a Radio answer's: radio_shelves) has passed:
    it is not fresh then, whatever its age. False without one."""
    stamp = answer.get('expires') if isinstance(answer, dict) else None
    if not isinstance(stamp, str):
        return False
    now = now or datetime.now(UTC)
    return now.strftime(STAMP_FORMAT) >= stamp


def save_library(library_data, cache_dir, indent=2, generation=None):
    """Write library.json atomically and durably (store.atomic_write: a temporary file,
    fsync'd, renamed over the old one), so a reader sees the old file or the new one, never
    half of one, even after a crash. `indent` is json.dump's: None writes the compact form. A
    failure raises, and leaves the old file and no temporary one; store.CacheGone when the
    cache was cleared since `generation` (nothing written)."""
    lib_path = os.path.join(cache_dir, 'library.json')
    written = store.atomic_write(lib_path, lambda f: json.dump(library_data, f, indent=indent),
                                 root=cache_dir, text=True, generation=generation)
    if written is None:
        raise store.CacheGone(cache_dir)


def prune_art(library_data, cache_dir):
    """Remove artwork files in <cache_dir>/art/ and <cache_dir>/thumb/ that
    the library no longer refers to. Returns the count of pruned files."""
    if not cache_dir:
        return 0

    norm_refs = set()
    for p in collect_art_paths(library_data):
        norm_refs.add(os.path.abspath(p))
        norm_refs.add(os.path.basename(p))

    pruned = 0
    for folder in ('art', 'thumb'):
        art_dir = os.path.join(cache_dir, folder)
        if not os.path.isdir(art_dir):
            continue
        try:
            for entry in os.listdir(art_dir):
                file_path = os.path.join(art_dir, entry)
                # The sizes marker lives here too, and is nobody's artwork; a temporary file
                # is a download in progress, or a crash's leftover once it is old.
                if entry.startswith('.'):
                    if store.is_stale_temp(file_path) and _remove(file_path):
                        pruned += 1
                    continue
                abs_path = os.path.abspath(file_path)
                if abs_path not in norm_refs and entry not in norm_refs:
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.remove(file_path)
                            pruned += 1
                    except OSError as error:
                        log.debug('prune: %s', error)
        except OSError as error:
            log.debug('prune: %s', error)

    return pruned


def credits_cache_path(cache_dir, song_id):
    """Where a song's credits (song_credits) are kept for a day, by its catalog id."""
    return os.path.join(cache_dir, 'credits', f'{_safe_id(song_id)}.json')


def suggestions_cache_path(cache_dir, playlist_id):
    """Where a playlist's suggested songs (playlist_suggestions) are kept for a day."""
    return os.path.join(cache_dir, 'suggestions', f'{_safe_id(playlist_id)}.json')


def artist_cache_path(cache_dir, artist_id):
    """Where an artist's page (artist_page) is kept for a day."""
    return os.path.join(cache_dir, 'artists', f'{_safe_id(artist_id)}.json')


def album_cache_path(cache_dir, album_id):
    """Where an album's page (album_page) is kept for a day, under the id it was asked by: a
    library album's own, or a catalog one."""
    return os.path.join(cache_dir, 'albums', f'{_safe_id(album_id)}.json')


def playlist_cache_path(cache_dir, playlist_id):
    """Where a catalog playlist's page (playlist_page) is kept for a day, by its catalog
    id."""
    return os.path.join(cache_dir, 'playlists', f'{_safe_id(playlist_id)}.json')


# ---------------------------------------------------------------------------
# The other caches: artwork the pages fetch on their own, and answers kept
# ---------------------------------------------------------------------------


def prune_remote_art(cache_dir, max_bytes=REMOTE_ART_BUDGET):
    """Trim <cache_dir>/remote-art/ — the covers the pages fetch themselves
    (a search hit's, the player's, a category's picture) — to `max_bytes`,
    keeping the newest by mtime. Nothing else ever removes them. Returns
    how many went."""
    folder = os.path.join(cache_dir, 'remote-art')
    pruned = 0
    entries = []
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.startswith('.'):  # a download in progress, or a crash's leftover
                if store.is_stale_temp(path) and _remove(path):
                    pruned += 1
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            if os.path.isfile(path):
                entries.append((st.st_mtime, st.st_size, path))
    except FileNotFoundError:
        return 0
    except OSError as error:
        log.debug('remote art: %s', error)
        return pruned
    entries.sort(reverse=True)
    kept = 0
    for _mtime, size, path in entries:
        if kept + size <= max_bytes:
            kept += size
            continue
        try:
            os.remove(path)
            pruned += 1
        except OSError as error:
            log.debug('remote art: %s', error)
    return pruned


def prune_caches(cache_dir, now=None, remote_bytes=REMOTE_ART_BUDGET, lyrics_keep=LYRICS_KEEP,
                 answer_age=ANSWER_KEEP_AGE):
    """Trim the caches nothing else trims (in a thread, at startup and after a sync):
    remote-art/ to `remote_bytes` (prune_remote_art), lyrics/ to the
    `lyrics_keep` played last (by mtime: a cache hit touches the file), the kept answers
    (categories/, artists/, albums/, suggestions/, credits/, charts/, landing, New, Made for
    You, Radio, Charts, the genres) written longer than `answer_age` ago (by mtime;
    ANSWER_KEEP_AGE, well past their day, since a stale one is the answer while Apple
    cannot be asked), an
    items/ folder older versions kept, and the temporary files of writes a crash cut short
    (store.is_stale_temp) in the cache and its folders. Returns {what: how many went}. art/
    and thumb/ are the library's: prune_art keeps them."""
    now = time.time() if now is None else now
    gone = {'remote-art': prune_remote_art(cache_dir, remote_bytes), 'lyrics': 0,
            'answers': 0, 'items': 0, 'temps': 0}

    def files(folder):
        try:
            with os.scandir(folder) as entries:
                return [entry for entry in entries if entry.is_file(follow_symlinks=False)]
        except FileNotFoundError:
            return []
        except OSError as error:
            log.debug('prune: %s', error)
            return []

    for folder in (cache_dir, *(os.path.join(cache_dir, name) for name in
                                ('art', 'thumb', 'remote-art', 'lyrics',
                                 *ANSWER_FOLDERS))):
        for entry in files(folder):
            if store.is_stale_temp(entry.path, now) and _remove(entry.path):
                gone['temps'] += 1

    lyrics = [entry for entry in files(os.path.join(cache_dir, 'lyrics'))
              if not store.is_temp(entry.name)]
    lyrics.sort(key=_mtime, reverse=True)
    for entry in lyrics[max(0, lyrics_keep):]:
        if _remove(entry.path):
            gone['lyrics'] += 1

    answers = [entry for folder in ANSWER_FOLDERS
               for entry in files(os.path.join(cache_dir, folder))
               if not store.is_temp(entry.name)]
    answers += [entry for entry in files(cache_dir) if entry.name in KEPT_ANSWERS]
    for entry in answers:
        if now - _mtime(entry) > answer_age and _remove(entry.path):
            gone['answers'] += 1

    items = os.path.join(cache_dir, 'items')
    if os.path.isdir(items) and not os.path.islink(items):
        import shutil
        try:
            gone['items'] = sum(len(names) for _root, _dirs, names in os.walk(items))
            shutil.rmtree(items)
        except OSError as error:
            log.debug('prune: %s', error)
    if any(gone.values()):
        log.info('caches pruned: %s', ', '.join(f'{count} {what}'
                                               for what, count in gone.items() if count))
    return gone


def _mtime(entry):
    try:
        return entry.stat(follow_symlinks=False).st_mtime
    except OSError:
        return 0


def _remove(path):
    """Delete a file the cache no longer wants; one already gone is fine. True if deleted."""
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        log.debug('prune: %s', error)
        return False


def _safe_id(value):
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(value or ''))


def landing_cache_path(cache_dir):
    return os.path.join(cache_dir, 'landing.json')


def demo_search_path(cache_dir):
    """The invented catalog the demo searches (scripts/demo_library.py writes it, marked
    `demo`; Engine.search answers from it in demo mode only): {shelves: [{key, items}]}."""
    return os.path.join(cache_dir, 'demo-search.json')


def category_cache_path(cache_dir, category_id):
    return os.path.join(cache_dir, 'categories', f'{_safe_id(category_id)}.json')


def browse_cache_path(cache_dir):
    """Where the New page's shelves (editorial_shelves) are kept for a day."""
    return os.path.join(cache_dir, 'browse.json')


def made_for_you_cache_path(cache_dir):
    """Where the Made for You shelves (made_for_you_shelves) are kept for a day."""
    return os.path.join(cache_dir, 'made-for-you.json')


def recent_played_cache_path(cache_dir):
    """Where Home's Recently Played (recently_played) is kept: the last answer, shown while
    the next is asked for (a day, as the other answers)."""
    return os.path.join(cache_dir, 'recent-played.json')


def radio_cache_path(cache_dir):
    """Where the Radio page's shelves (radio_shelves) are kept: a day, or until their
    programmes run out (`expires`)."""
    return os.path.join(cache_dir, 'radio.json')


def charts_cache_path(cache_dir, genre=None):
    """Where the Charts page's shelves (charts_shelves) are kept for a day: every genre's in
    charts.json, a genre's in charts/<genre>.json."""
    if genre:
        return os.path.join(cache_dir, 'charts', f'{_safe_id(genre)}.json')
    return os.path.join(cache_dir, 'charts.json')


def genres_cache_path(cache_dir):
    """Where the catalog's genres (catalog_genres), the Charts page's choice, are kept for a
    day."""
    return os.path.join(cache_dir, 'genres.json')


def replay_cache_path(cache_dir, year=None):
    """Where Replay (replay_page) is kept for a day: the latest year's in replay.json, a past
    year's in replay/<year>.json."""
    if year:
        return os.path.join(cache_dir, 'replay', f'{_safe_id(year)}.json')
    return os.path.join(cache_dir, 'replay.json')


def room_cache_path(cache_dir, room_id):
    """Where an editorial room's contents (editorial_room) are kept for a day, by its id."""
    return os.path.join(cache_dir, 'rooms', f'{_safe_id(room_id)}.json')


def grouping_cache_path(cache_dir, grouping_id):
    """Where an editorial grouping's shelves (editorial_grouping) are kept for a day."""
    return os.path.join(cache_dir, 'groupings', f'{_safe_id(grouping_id)}.json')


def multiroom_cache_path(cache_dir, multiroom_id):
    """Where an editorial multiroom's shelves (editorial_multiroom) are kept for a day."""
    return os.path.join(cache_dir, 'multirooms', f'{_safe_id(multiroom_id)}.json')


def stamp_answer(answer):
    """A copy of `answer` stamped as write_answer keeps it: `cached` with now, `shape` with
    ANSWER_SHAPE (an answer shown without being kept carries the same stamps)."""
    answer = dict(answer)
    answer['cached'] = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    answer['shape'] = ANSWER_SHAPE
    return answer


def write_answer(path, answer, cache_dir, generation=None):
    """Keep `answer` at `path` (in the cache at `cache_dir`), atomically, as
    JSON without spaces, stamped `cached` with when and `shape` with ANSWER_SHAPE; not once
    the cache's generation has moved from `generation` (store.py). Best effort: a cache
    that cannot be written is only a cache."""
    answer = stamp_answer(answer)
    try:
        store.atomic_write(path, lambda f: json.dump(answer, f, separators=(',', ':')),
                           root=cache_dir, text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not keep %s: %s', path, error)
    return answer


def patch_answer(path, changes, cache_dir, generation=None):
    """Set `changes` (a dict) in the answer kept at `path`, keeping its `cached` stamp (the
    answer is no fresher for it): a write of the account's that the kept answer has to show
    until it is read again (an artist's page after a favourite). Nothing when there is no
    answer there, or the cache's generation has moved from `generation`; best effort, as
    write_answer."""
    try:
        with open(path, encoding='utf-8') as f:
            answer = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(answer, dict):
        return
    answer.update(changes)
    try:
        store.atomic_write(path, lambda f: json.dump(answer, f, separators=(',', ':')),
                           root=cache_dir, text=True, generation=generation)
    except (OSError, ValueError) as error:
        log.warning('could not update %s: %s', path, error)


def read_answer(path, max_age_seconds):
    """The answer kept at `path`, or None when there is none, it cannot be
    read, or it was stamped longer than `max_age_seconds` ago."""
    try:
        with open(path, encoding='utf-8') as f:
            answer = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.debug('kept answer %s: %s', path, error)
        return None
    stamp = answer.get('cached') if isinstance(answer, dict) else None
    try:
        when = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
    except (TypeError, ValueError):
        log.debug('kept answer %s: no stamp', path)
        return None
    if (datetime.now(UTC) - when).total_seconds() > max_age_seconds:
        return None
    return answer
