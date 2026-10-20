# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Radio page (pages/radio.py, src/radio.py): Apple's radio shelves over the stand-in
engine, the live stations subtitled with what is on air, and the library's own stations as
Recently Played, after the first shelf, or alone while Apple cannot answer."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.page_harness import PageTestCase

from applemusic.backend.errors import EngineError

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
EVENTS = [{'title': 'Morning Lanterns', 'start': '2026-10-20T14:00:00Z',
           'end': '2026-10-20T16:00:00Z'},
          {'title': 'The Late Tide', 'start': '2026-10-20T16:00:00Z',
           'end': '2026-10-20T18:00:00Z'}]


def station(number, title, **extra):
    data = {'id': f'ra.{number}', 'kind': 'station', 'title': title,
            'subtitle': 'Invented Radio', 'art': None, 'thumb': None,
            'play': {'kind': 'station', 'id': f'ra.{number}'}}
    data.update(extra)
    return data


def answer(events=None):
    """An invented Radio answer, as Engine.radio gives it: the live stations first."""
    live = station(900, 'Harbour One', events=events or EVENTS)
    show = {'id': '901', 'kind': 'category', 'title': 'The Lantern Hour',
            'subtitle': 'Ada Fenwick', 'art': None}
    return {'shelves': [
        {'key': 'radio-live', 'title': 'Invented Live Radio', 'live': True,
         'items': [live, station(902, 'Harbour Hits')]},
        {'key': 'radio-shows', 'title': 'Invented Shows', 'items': [show]},
    ]}


class OnAirTest(unittest.TestCase):
    def test_the_programme_on_air(self):
        from applemusic.radio import on_air

        self.assertEqual(on_air(EVENTS, NOW)['title'], 'Morning Lanterns')
        self.assertEqual(on_air(EVENTS, datetime(2026, 10, 20, 16, 0, tzinfo=UTC))['title'],
                         'The Late Tide')  # an end is the next one's start
        self.assertIsNone(on_air(EVENTS, datetime(2026, 10, 20, 18, 0, tzinfo=UTC)))
        self.assertIsNone(on_air(EVENTS, datetime(2026, 10, 20, 13, 0, tzinfo=UTC)))
        self.assertIsNone(on_air(None, NOW))
        self.assertIsNone(on_air([{'title': 'No Times'}], NOW))

    def test_stations_are_subtitled_with_it_and_their_own_between_programmes(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.radio import show_on_air

        live = Item(station(900, 'Harbour One', events=EVENTS))
        plain = Item(station(902, 'Harbour Hits'))
        shelves = [ShelfModel('radio-live', 'Live', [live, plain])]
        show_on_air(shelves, NOW)
        self.assertEqual((live.subtitle, plain.subtitle), ('Morning Lanterns', 'Invented Radio'))
        show_on_air(shelves, datetime(2026, 10, 20, 19, 0, tzinfo=UTC))
        self.assertEqual(live.subtitle, 'Invented Radio')  # its own again

    def test_recently_played_comes_after_the_first_shelf_or_alone(self):
        from applemusic.library import Item, ShelfModel
        from applemusic.radio import RecentlyPlayed, arrange
        from gi.repository import Gio

        stations = Gio.ListStore(item_type=Item)
        recent = RecentlyPlayed(stations)
        first, second = ShelfModel('a', 'A', []), ShelfModel('b', 'B', [])
        self.assertEqual(arrange([first, second], recent, NOW), [first, second])  # empty
        stations.append(Item(station(1, 'Played')))
        self.assertEqual(arrange([first, second], recent, NOW), [first, recent, second])
        self.assertEqual(arrange([], recent, NOW), [recent])
        self.assertEqual({recent: True}[recent], True)  # ShelfColumn keys shelves by them


class RadioPageTest(PageTestCase):
    async def asyncSetUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = cache.name
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache})
        patcher.start()
        self.addCleanup(patcher.stop)
        clock = mock.patch('applemusic.radio.datetime')
        fake = clock.start()
        fake.now.return_value = NOW
        self.addCleanup(clock.stop)

    def write(self, titles):
        data = {'version': 1, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': [], 'playlists': [],
                             'radio': [station(n, title) for n, title in enumerate(titles)]},
                'shelves': []}
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')

    async def radio_page(self, titles):
        from applemusic.pages import radio
        from applemusic.sections import Destination

        self.write(titles)
        await self.library.load()
        page = radio.create(Destination('radio', 'Radio', 'broadcast-symbolic'), self.library)
        await self.show_root(page)
        await self.settle()
        return page

    def shown(self, page):
        """(key, title, hero) of each shelf shown, in order."""
        return [(widget.shelf.key, widget.shelf.title, widget.props.hero)
                for widget in page._column.widgets if widget.get_visible()]

    async def test_apples_shelves_with_recently_played_after_the_live_stations(self):
        self.app.engine.answers['radio'] = answer()
        page = await self.radio_page(['Played'])
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        self.assertEqual(self.shown(page), [
            ('radio-live', 'Invented Live Radio', True),
            ('recently-played-stations', 'Recently Played', False),
            ('radio-shows', 'Invented Shows', False)])
        live = page._column.widgets[0].shelf.items.get_item(0)
        self.assertEqual(live.subtitle, 'Morning Lanterns')  # on air now
        self.assertEqual(page._column.widgets[1].shelf.items, self.library.radio)

    async def test_recently_played_comes_and_goes_with_the_librarys_stations(self):
        self.app.engine.answers['radio'] = answer()
        page = await self.radio_page([])
        self.assertEqual([key for key, _title, _hero in self.shown(page)],
                         ['radio-live', 'radio-shows'])
        self.write(['Played'])
        await self.library.reload()
        self.assertTrue(await self.until(lambda: len(self.shown(page)) == 3))
        self.assertEqual(self.shown(page)[1][0], 'recently-played-stations')

    async def test_recently_played_alone_while_apple_cannot_answer(self):
        page = await self.radio_page(['Played'])  # the engine down, nothing kept
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        self.assertEqual(self.shown(page), [('recently-played-stations', 'Recently Played',
                                             True)])
        # Refresh starts the engine, as the status page's button would, and once it answers
        # Apple's shelves come.
        self.app.engine.answers['radio'] = answer()
        page.refresh_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls, ['radio', 'start', 'radio'])
        self.assertEqual([key for key, _title, _hero in self.shown(page)],
                         ['radio-live', 'recently-played-stations', 'radio-shows'])

    async def test_the_status_page_without_stations(self):
        page = await self.radio_page([])
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_button.get_label(), 'Start Engine')
        self.write(['Played'])  # a sync brings some: they show
        await self.library.reload()
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'items'))

    async def test_signed_out_it_offers_sign_in(self):
        self.app.settings.set_boolean('signed-in', False)
        page = await self.radio_page([])
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_button.get_label(), 'Sign In…')

    async def test_a_failed_refresh_keeps_recently_played_and_says_why(self):
        self.app.engine.answers['radio'] = EngineError('timeout')
        page = await self.radio_page(['Played'])
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        self.assertEqual(self.app.reported, [])  # the first failure: the page says nothing
        page.refresh_button.emit('clicked')  # 'failed': Try Again
        await self.settle()
        self.assertEqual(self.app.reported, ['timeout'])
        self.assertEqual(self.shown(page)[0][0], 'recently-played-stations')

    async def test_a_show_opens_its_page(self):
        self.app.engine.answers['radio'] = answer()
        page = await self.radio_page([])
        shelf = page._column.widgets[1]
        shelf.list_view.emit('activate', 0)
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('category', '901')])


if __name__ == '__main__':
    unittest.main()
