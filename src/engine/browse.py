# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The browsing pages' answers, each kept for a day: Search's landing and categories, New
and the pages its links open, Radio, Charts and its genres, Replay, Made for You and Home's
Recently Played."""

import logging

from ..backend import api, cache_files, charts, editorial, recommendations, search
from ..backend.errors import EngineError
from .reads import READ_TIMEOUT, SEARCH_TIMEOUT, _raise_api_errors, _Unkept

log = logging.getLogger(__name__)

BROWSE_TIMEOUT = 60.0     # the editorial groupings: a big answer


def _made_for_you(raw, cache_dir):
    return {'shelves': recommendations.made_for_you_shelves(raw.get('data'), cache_dir)}


class BrowseCommands:
    """The Engine's browsing pages: a mixin of Engine (core.py), whose
    _api(), _kept_answer(), _current_storefront() and cache_dir they use."""

    async def landing(self, refresh=False):
        """The search page's Browse Categories: {categories: [{id, kind: 'category', title,
        subtitle, art, artColor, url}]} in Apple's order, `art` a small catalog URL. From
        <cache>/landing.json for a day (no engine needed then), else the bridge's
        searchLanding (the search-landing recommendation set) shaped by search.search_landing
        and kept there (_kept_answer). `refresh` asks Apple again."""
        async def fetch(client):
            raw = await client.bridge('searchLanding', timeout=SEARCH_TIMEOUT)
            _raise_api_errors(raw, 'search landing')
            return raw
        return await self._kept_answer(cache_files.landing_cache_path(str(self.cache_dir)),
                                       refresh, fetch, search.search_landing)

    async def category(self, category_id, refresh=False):
        """A category's page: {id, title, shelves: [{key, title, items}]}, the curator's
        grouping as shelves (Best New Songs, New Releases, Playlists, Stations…; a radio
        show's episodes), then its own playlists (editorial.category_page). From
        <cache>/categories/<id>.json for a day, else the bridge's category() and kept."""
        category_id = str(category_id or '')
        if not category_id:
            raise EngineError('usage', 'category needs an id')

        async def fetch(client):
            raw = await client.bridge('category', category_id, timeout=SEARCH_TIMEOUT)
            _raise_api_errors(raw, f'category {category_id}')
            return raw
        return await self._kept_answer(
            cache_files.category_cache_path(str(self.cache_dir), category_id), refresh, fetch,
            editorial.category_page)

    async def browse(self, refresh=False):
        """The New page: {shelves: [{key, title, items}]}, the editorial groupings behind
        music.apple.com's own New page (api.BROWSE_ENDPOINT, name=music, platform=web) as
        shelves in Apple's order, the featured banners first ("Featured"), then Best New
        Songs, New Releases, playlists, stations, videos; items as search() has them. From
        <cache>/browse.json for a day, else fetched and kept."""
        async def fetch(client):
            storefront = await self._current_storefront()
            return await self._api(client, api.BROWSE_ENDPOINT.format(storefront=storefront),
                                   api.BROWSE_PARAMS, timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(cache_files.browse_cache_path(str(self.cache_dir)),
                                       refresh, fetch, editorial.editorial_shelves)

    async def radio(self, refresh=False):
        """The Radio page: {shelves: [{key, title, items}], expires?}, the editorial grouping
        behind music.apple.com's own Radio page (api.BROWSE_ENDPOINT with api.RADIO_PARAMS:
        name=radio, the stations' programmes and shows) as editorial.radio_shelves shapes
        it: the live stations first (`live`, each with its `events`), then the hero's
        others, the shows, episodes and genre stations in Apple's order. From
        <cache>/radio.json for a day or until `expires` (the live programmes run out), else
        fetched and kept."""
        async def fetch(client):
            storefront = await self._current_storefront()
            return await self._api(client, api.BROWSE_ENDPOINT.format(storefront=storefront),
                                   api.RADIO_PARAMS, timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(cache_files.radio_cache_path(str(self.cache_dir)),
                                       refresh, fetch, editorial.radio_shelves)

    async def charts(self, genre=None, refresh=False):
        """The Charts page: {shelves: [{key, title, items, chart[, ranked][, form]}]}, the
        storefront's charts (api.CHARTS_ENDPOINT with api.CHARTS_PARAMS: every kind, most
        played, with the Daily Top 100 and City Charts playlists) as charts.charts_shelves
        shapes them: Top Songs (ranked, a list), Top Albums, Top Playlists (ranked), the Daily
        Top 100 and City Charts playlists, Top Music Videos (ranked). Apple refusing the
        playlists' `with` (a 400) is asked again without it (api.CHARTS_PLAIN_PARAMS). With a
        `genre` (a catalog genre's id, genres()'s), that genre's rankings alone
        (api.charts_params); Music's, api.ROOT_GENRE, are every genre's. From
        <cache>/charts.json (a genre's charts/<genre>.json) for a day, else fetched and
        kept."""
        genre = str(genre or '')
        if genre and not api.is_genre_id(genre):
            raise EngineError('usage', 'charts needs a genre id')
        genre = api.chart_genre(genre)  # Music's (api.ROOT_GENRE) are every genre's

        async def fetch(client):
            storefront = await self._current_storefront()
            endpoint = api.CHARTS_ENDPOINT.format(storefront=storefront)
            try:
                return await self._api(client, endpoint, api.charts_params(genre),
                                       timeout=BROWSE_TIMEOUT)
            except EngineError as error:
                if genre or error.status != 400:
                    raise
                log.info('charts: the daily and city charts refused (%s); without them', error)
                return await self._api(client, endpoint, api.CHARTS_PLAIN_PARAMS,
                                       timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(cache_files.charts_cache_path(str(self.cache_dir), genre),
                                       refresh, fetch, charts.charts_shelves)

    async def genres(self, refresh=False):
        """The genres the Charts page offers: {genres: [{id, title}]}, the catalog's
        (api.GENRES_ENDPOINT) in Apple's order, Music, every genre's, left out
        (charts.catalog_genres). From <cache>/genres.json for a day, else fetched and
        kept."""
        async def fetch(client):
            storefront = await self._current_storefront()
            return await self._api(client, api.GENRES_ENDPOINT.format(storefront=storefront),
                                   api.GENRES_PARAMS, timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(cache_files.genres_cache_path(str(self.cache_dir)),
                                       refresh, fetch, charts.catalog_genres)

    async def _editorial_page(self, what, page_id, refresh, endpoint, params, path, shaper):
        """One of the pages More to Explore's links open (a room, a grouping, a multiroom):
        `endpoint` with `params` for the id, shaped by `shaper` and kept at `path(cache_dir,
        id)` for a day (_kept_answer)."""
        page_id = str(page_id or '')
        if not api.is_editorial_id(page_id):
            raise EngineError('usage', f'{what} needs an editorial id')

        async def fetch(client):
            storefront = await self._current_storefront()
            return await self._api(
                client, endpoint.format(storefront=storefront, id=page_id), params,
                timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(path(str(self.cache_dir), page_id), refresh, fetch,
                                       shaper)

    async def room(self, room_id, refresh=False):
        """An editorial room (a More to Explore link's collection): {id, title, items}, its
        contents in Apple's order as editorial.editorial_room shapes them (api.ROOM_ENDPOINT).
        From <cache>/rooms/<id>.json for a day, else fetched and kept."""
        return await self._editorial_page('room', room_id, refresh, api.ROOM_ENDPOINT,
                                          api.ROOM_PARAMS, cache_files.room_cache_path,
                                          editorial.editorial_room)

    async def grouping(self, grouping_id, refresh=False):
        """An editorial grouping (a More to Explore link's page, New's shape): {id, title,
        shelves, links} as editorial.editorial_grouping shapes them (api.GROUPING_ENDPOINT
        with api.GROUPING_PARAMS). From <cache>/groupings/<id>.json for a day, else fetched
        and kept."""
        return await self._editorial_page('grouping', grouping_id, refresh,
                                          api.GROUPING_ENDPOINT, api.GROUPING_PARAMS,
                                          cache_files.grouping_cache_path,
                                          editorial.editorial_grouping)

    async def multiroom(self, multiroom_id, refresh=False):
        """An editorial multiroom (a More to Explore link's page of shelves): {id, title,
        shelves, links} as editorial.editorial_multiroom shapes them
        (api.MULTIROOM_ENDPOINT with api.MULTIROOM_PARAMS). From
        <cache>/multirooms/<id>.json for a day, else fetched and kept."""
        return await self._editorial_page('multiroom', multiroom_id, refresh,
                                          api.MULTIROOM_ENDPOINT, api.MULTIROOM_PARAMS,
                                          cache_files.multiroom_cache_path,
                                          editorial.editorial_multiroom)

    async def replay(self, year=None, refresh=False):
        """Replay, the account's year in music: {year, years, shelves} (charts.replay_page:
        the year's Top Songs, a list, then Top Artists and Top Albums, each ranked, then each
        year's Replay playlist), the summary of the latest year, or of `year` (four digits;
        anything else is 'usage'; api.replay_request() has how each is asked), its top songs
        read from the catalog by id (Apple's summary names them by id alone:
        charts.replay_song_ids, api.replay_songs_params, one read), beside the years Apple
        has a Replay of (api.REPLAY_YEARS_ENDPOINT: the year menu's choice). Apple refusing
        the summary (a 400 or a 404: no listening history for the year) is a summary of
        nothing, a 404 for the songs none of them, and the years failing are none (that
        answer shown, not kept); anything else is the command's. From <cache>/replay.json
        (a past year's replay/<year>.json) for a day, else fetched and kept, with
        charts.REPLAY_SHAPE as its basis, so one kept in an older shape is asked
        again."""
        year = str(year or '')
        if year and not api.is_replay_year(year):
            raise EngineError('usage', 'replay needs a year')

        async def fetch(client):
            path, params = api.replay_request(year)
            try:
                summary = await self._api(client, path, params, timeout=BROWSE_TIMEOUT)
            except EngineError as error:
                if error.status not in (400, 404):
                    raise
                log.info('replay: no summary of %s (%s)', year or 'the latest year', error)
                summary = None
            songs = None
            params = api.replay_songs_params(charts.replay_song_ids(summary))
            if params is not None:
                storefront = await self._current_storefront()
                try:
                    songs = await self._api(
                        client, api.REPLAY_SONGS_ENDPOINT.format(storefront=storefront),
                        params, timeout=BROWSE_TIMEOUT)
                except EngineError as error:
                    if error.status != 404:
                        raise
                    log.info('replay: none of the top songs in the catalog (%s)', error)
            try:
                years = await self._api(client, api.REPLAY_YEARS_ENDPOINT,
                                        api.REPLAY_YEARS_PARAMS, timeout=BROWSE_TIMEOUT)
            except EngineError as error:
                if error.code == 'engine-down':
                    raise
                log.info('replay: no years to choose from: %s', error)
                return _Unkept({'summary': summary, 'songs': songs, 'years': None,
                                'year': year})
            return {'summary': summary, 'songs': songs, 'years': years, 'year': year}
        return await self._kept_answer(cache_files.replay_cache_path(str(self.cache_dir), year),
                                       refresh, fetch, charts.replay_page,
                                       basis=charts.REPLAY_SHAPE)

    async def made_for_you(self, refresh=False):
        """Made for You: {shelves: [{key, title, items}]}, the recommendations
        (api.RECOMMENDATIONS_ENDPOINT) made only of the personal mixes and stations, each a
        shelf titled as Apple titles it. From <cache>/made-for-you.json for a day, else
        fetched and kept."""
        async def fetch(client):
            return await self._api(client, api.RECOMMENDATIONS_ENDPOINT,
                                   api.RECOMMENDATIONS_PARAMS, timeout=BROWSE_TIMEOUT)
        return await self._kept_answer(cache_files.made_for_you_cache_path(str(self.cache_dir)),
                                       refresh, fetch, _made_for_you)

    async def recently_played(self, refresh=False):
        """Home's Recently Played: {items: [Item]} (recommendations.recently_played), the albums,
        playlists and stations played last, newest first, from api.RECENT_PLAYED_ENDPOINT,
        api.RECENT_PLAYED_PAGE a read by offset, up to api.RECENT_PLAYED_LIMIT. A later page
        that fails answers the ones in hand, not kept; the first must answer. From
        <cache>/recent-played.json for a day, else fetched and kept: Home shows the kept one
        at once and asks with `refresh` once it is a minute old (src/home.py)."""
        async def fetch(client):
            page = api.RECENT_PLAYED_PAGE
            resources = []
            while len(resources) < api.RECENT_PLAYED_LIMIT:
                params = {'limit': page, 'offset': len(resources)}
                try:
                    answer = await self._api(client, api.RECENT_PLAYED_ENDPOINT, params,
                                             timeout=READ_TIMEOUT)
                except EngineError as error:
                    if not resources or error.code == 'engine-down':
                        raise
                    log.info('recently played, past %d: %s', len(resources), error)
                    return _Unkept(resources[:api.RECENT_PLAYED_LIMIT])
                data = api.page_data(answer)
                resources += data
                if len(data) < page or not answer.get('next'):
                    break
            return resources[:api.RECENT_PLAYED_LIMIT]
        return await self._kept_answer(
            cache_files.recent_played_cache_path(str(self.cache_dir)), refresh, fetch,
            recommendations.recently_played)
