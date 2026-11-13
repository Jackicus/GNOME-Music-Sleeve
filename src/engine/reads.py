# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""How the commands read Apple: one API read through the page, retried when it may pass
another time, a paged endpoint whole, several reads at once, and the day-long kept answer
(_kept_answer: the file while it is young, else Apple, else the older file, stale)."""

import asyncio
import logging
import os

from .. import cache
from ..backend import api, normalize, store
from ..backend.errors import EngineError

log = logging.getLogger(__name__)

API_RETRIES = 3           # tries of an API read that may pass another time (api.is_final)
API_RETRY_DELAY = 0.5     # before the first retry of a failed API read; doubles after
READ_TIMEOUT = 15.0       # one read a person waits on: an item's page, a rating, a link
PAGE_CONCURRENCY = 3      # pages of one endpoint fetched at once, when its total is known
SEARCH_TIMEOUT = 30.0     # a catalog search, its suggestions, the landing or a category


def _raise_api_errors(answer, what):
    """MusicKit answers a failed request with a 200 and {"errors": [...]}: an EngineError."""
    error = api.api_error(answer, what)
    if error is not None:
        raise error


class _Unkept:
    """A kept answer's fetch's raw answer, made while one of its secondary reads failed and
    was taken as none (Replay's years, a page's More By, Recently Played past its first
    page): _kept_answer shapes and answers it but keeps nothing, so Apple is asked again at
    the next visit and an older, complete answer kept there stays for the stale fallback."""

    __slots__ = ('raw',)

    def __init__(self, raw):
        self.raw = raw


def _shape_and_keep(shaper, raw, path, cache_dir, generation, basis=None):
    """In a thread: `shaper(raw, cache_dir)`'s answer, kept at `path` (stamped `cached`, and
    `basis` when there is one) unless the cache was cleared since `generation`, or `raw` is
    an _Unkept (stamped alike, kept nowhere). A shaper that raises (an answer of a type it
    does not expect, a list where a dict should be) is EngineError('api'), logged, and
    nothing is kept: only EngineError leaves the Engine."""
    keep = not isinstance(raw, _Unkept)
    if not keep:
        raw = raw.raw
    try:
        answer = shaper(raw, cache_dir)
    except Exception as error:
        what = os.path.basename(path)
        log.warning('could not read the answer for %s', what, exc_info=True)
        raise EngineError('api', f'an answer for {what} that could not be read: '
                                 f'{type(error).__name__}') from error
    if basis is not None:
        answer = dict(answer, basis=basis)
    if not keep:
        log.info('not keeping the answer for %s: one of its reads failed',
                 os.path.basename(path))
        return normalize.stamp_answer(answer)
    return normalize.write_answer(path, answer, cache_dir, generation)


async def _read_pages(read, path, params, page, limit, progress, concurrency):
    """Engine.api_pages' reads through `read` (the Engine's api()): (the items in order, the
    total Apple counted or None). A function of its own, so a stand-in engine that borrows
    api_pages needs only an api() of its own."""
    params = dict(params or {})
    first = await read(path, dict(params, limit=page, offset=0))
    items = api.page_data(first)
    meta = first.get('meta')
    total = meta.get('total') if isinstance(meta, dict) else None
    total = total if isinstance(total, int) and not isinstance(total, bool) else None
    if limit is not None:
        total = min(total, limit) if total is not None else None
    if progress:
        progress(len(items), total)
    if not items or not first.get('next') or (limit is not None and len(items) >= limit):
        return items, total
    if total is not None and total > len(items):
        # Every remaining offset is known: a few pages at a time, kept in order.
        offsets = list(range(len(items), total, page))
        for start in range(0, len(offsets), max(1, concurrency)):
            batch = offsets[start:start + max(1, concurrency)]
            answers = await asyncio.gather(
                *(read(path, dict(params, limit=page, offset=offset))
                  for offset in batch))
            for answer in answers:
                items.extend(api.page_data(answer))
            if progress:
                progress(min(len(items), total), total)
            if any(not api.page_data(answer) for answer in answers):
                break  # Apple ran out early (the total counted something we do not get)
        return items, total
    while True:
        answer = await read(path, dict(params, limit=page, offset=len(items)))
        data = api.page_data(answer)
        items.extend(data)
        if progress:
            progress(len(items), total)
        if not data or not answer.get('next') or (limit is not None and len(items) >= limit):
            break
    return items, total


class ApiReads:
    """The Engine's API reads and kept answers: a mixin of Engine (core.py), whose
    _ready(), _require_signed_in(), cache_dir and demo they use."""

    async def _api(self, client, path, params=None, timeout=None):
        """One API read through the bridge. MusicKit answers a failed request with a 200 and
        {"errors": [...]}, which is a failure here as much as a rejected promise. What may
        pass another time (a 5xx, a 429, an error without a status, a promise the page
        rejected) is tried again, API_RETRIES in all, after a growing pause; what would fail
        the same way (a 4xx, a timeout: api.is_final) raises at once, its `status` Apple's."""
        where = path.partition('?')[0]  # its query stays out of messages and the log
        last = None
        for attempt in range(API_RETRIES):
            if attempt:
                await asyncio.sleep(self.api_retry_delay * 2 ** (attempt - 1))
            try:
                answer = await client.bridge('api', path, params or {}, timeout=timeout)
            except EngineError as e:
                if e.code == 'engine-down':
                    raise
                last = EngineError(e.code, f'{where}: {e.message}', status=e.status)
            else:
                last = api.api_error(answer, where)
                if last is None:
                    return answer if isinstance(answer, dict) else {}
            if api.is_final(last):
                break
        raise last

    async def api(self, path, params=None, timeout=None):
        """One Apple Music API read through the page's MusicKit (the bridge's api(), that is
        mk.api.music(path, params)), retried when it may pass another time (_api); the
        answer's body as a dict ({data: [...], meta, next…}). EngineError('api') when Apple
        says no (its `status` the HTTP status: a 404 is final), 'timeout' when the page did
        not answer in time, 'engine-down' when there is no engine."""
        client = await self._ready()
        return await self._api(client, path, params, timeout)

    async def api_all(self, paths, timeout=60):
        """Several reads at once in the page (the bridge's apiAll): one answer per path, in
        order, None where one failed."""
        paths = list(paths)
        client = await self._ready()
        answers = await client.bridge('apiAll', paths, timeout=timeout)
        answers = answers if isinstance(answers, list) else []
        return (answers + [None] * len(paths))[:len(paths)]

    async def api_pages(self, path, params=None, page=100, limit=None, progress=None,
                        concurrency=PAGE_CONCURRENCY, unique=False):
        """Every item (`data`) of a paged endpoint, `page` at a time by offset, following
        `next` until there is none or `limit` items are in hand. An endpoint whose first
        answer carries `meta.total` has its remaining pages fetched `concurrency` at a time;
        the rest are followed one by one. `progress(done, total)` is called after each page
        (total None until it is known).

        With `unique`, an item met twice is kept once, where it came first: when the listing
        changes while it is read (a song added on another device), every offset after the
        change shifts, and the item at a page's edge comes back on the next page. For a
        listing of resources, not a playlist's tracks, where a song may be twice."""
        items, total = await _read_pages(self.api, path, params, page, limit, progress,
                                         concurrency)
        if limit is not None:
            items = items[:limit]
        if unique:
            seen = set()
            kept = []
            for item in items:
                item_id = item.get('id')
                if item_id is None or item_id not in seen:
                    seen.add(item_id)
                    kept.append(item)
            if len(kept) < len(items) or (total is not None and len(kept) < total):
                log.debug('%s: %d items, %d of them once (%s counted)', path.partition('?')[0],
                          len(items), len(kept), total if total is not None else 'none')
            items = kept
        return items

    async def _kept_answer(self, path, refresh, fetch, shaper, basis=None):
        """A day-long answer, kept at `path`: from the file while it is younger than
        normalize.ANSWER_MAX_AGE (no engine needed) unless `refresh`, else `await
        fetch(client)`'s raw answer, shaped by `shaper(raw, cache_dir)` in a thread and kept
        there, stamped `cached`. When Apple cannot be asked (the engine down or signed out,
        the page or the network failing) or its answer cannot be shaped (EngineError('api'),
        _shape_and_keep), an older answer kept there is answered instead,
        marked `stale: True`; with none, or on a refresh, the error. With a `basis` (what the
        answer was asked about, as a string), the answer is kept with it, and one kept with
        another is not fresh, whatever its age: Apple is asked again (and the old one is
        still answered, stale, when Apple cannot be asked). Nor is one whose `expires` has
        passed (normalize.answer_expired: Radio's live programmes), or one an older version
        kept in another shape (normalize.answer_current, ANSWER_SHAPE). Demo mode has none of
        Apple's answers: only an invented one the demo library wrote there (marked `demo`), at
        any age, else 'engine-down'."""
        if self.demo:
            kept = await asyncio.to_thread(cache.read_kept, path, allow_stale=True)
            if kept is None or kept.get('demo') is not True:
                raise EngineError('engine-down', 'the engine is not running')
            kept.pop('stale', None)
            return kept
        generation = store.cache_generation()
        if not refresh:
            kept = await asyncio.to_thread(cache.read_kept, path)
            if (kept is not None and (basis is None or kept.get('basis') == basis)
                    and normalize.answer_current(kept) and not normalize.answer_expired(kept)):
                return kept
        try:
            client = await self._require_signed_in('browse')
            raw = await fetch(client)
            return await asyncio.to_thread(_shape_and_keep, shaper, raw, path,
                                           str(self.cache_dir), generation, basis)
        except EngineError as error:
            stale = None
            if not refresh and error.code != 'usage':
                stale = await asyncio.to_thread(cache.read_kept, path, allow_stale=True)
            if stale is None:
                raise
            if basis is not None and stale.get('basis') != basis:
                stale['stale'] = True  # young, but for what the playlist held before
            if normalize.answer_expired(stale):
                stale['stale'] = True  # young, but its programmes are over
            if not normalize.answer_current(stale):
                stale['stale'] = True  # young, but kept by a version that shaped it otherwise
            log.info('answering a kept answer no longer fresh: %s', error)
            return stale
