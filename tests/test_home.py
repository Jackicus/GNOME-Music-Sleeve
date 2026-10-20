# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Home's Recently Played (src/home.py, pages/home.py): when Apple is asked again, where the
shelf goes, an answer coming into it in place, and the page over the stand-in engine:
the kept answer at once, Apple's after it, nothing toasted, Refresh."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.page_harness import PageTestCase, album

from gi.repository import Gio

from applemusic import home
from applemusic.backend.errors import EngineError
from applemusic.library import Item, ShelfModel

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def stamp(seconds_ago, now=NOW):
    return (now - timedelta(seconds=seconds_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')


def played(number, kind='album', **extra):
    """An invented item of a Recently Played answer, as normalize.recently_played gives it."""
    data = {'id': f'9000005{number:02d}', 'kind': kind, 'title': f'Invented Played {number}',
            'subtitle': 'Invented Artist', 'art': None, 'thumb': None, 'groups': [],
            'play': {'kind': kind, 'id': f'9000005{number:02d}'}}
    data.update(extra)
    return data


def answer(numbers, seconds_ago=0, now=NOW, **extra):
    return dict({'items': [played(n) for n in numbers], 'cached': stamp(seconds_ago, now)},
                **extra)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ThrottleTest(unittest.TestCase):
    def test_the_age_of_an_answer(self):
        self.assertEqual(home.answer_age(answer([], 90), NOW), 90)
        for nothing in (None, {}, {'cached': 'yesterday'}, {'cached': 5}):
            self.assertIsNone(home.answer_age(nothing, NOW))

    def test_apple_is_asked_once_an_answer_is_a_minute_old(self):
        throttle = home.Throttle(Clock())
        self.assertTrue(throttle.due(None, NOW))
        self.assertFalse(throttle.due(answer([1], 10), NOW))
        self.assertTrue(throttle.due(answer([1], home.RECENT_MAX_AGE), NOW))
        self.assertTrue(throttle.due({'items': []}, NOW))  # no stamp
        self.assertTrue(throttle.due(answer([1], 10, stale=True), NOW))

    def test_not_again_for_a_while_after_apple_failed(self):
        clock = Clock()
        throttle = home.Throttle(clock)
        old = answer([1], 600)
        throttle.failed(EngineError('timeout'))
        self.assertFalse(throttle.due(old, NOW))
        clock.now += home.RETRY_DELAY
        self.assertTrue(throttle.due(old, NOW))
        throttle.failed(EngineError('api'))
        throttle.answered()
        self.assertTrue(throttle.due(old, NOW))
        throttle.failed(EngineError('timeout'))
        throttle.reset()  # a sign-out
        self.assertTrue(throttle.due(old, NOW))

    def test_the_engine_down_or_signed_out_does_not_count(self):
        throttle = home.Throttle(Clock())
        throttle.failed(EngineError('engine-down'))
        throttle.failed(EngineError('not-signed-in'))
        self.assertTrue(throttle.due(answer([1], 600), NOW))


class RecentlyPlayedTest(unittest.TestCase):
    def test_an_answer_comes_in_place_keeping_the_items_still_played(self):
        recent = home.RecentlyPlayed()
        shelf = recent.shelf
        self.assertEqual((shelf.key, shelf.title), (home.RECENT_KEY, 'Recently Played'))
        self.assertTrue(recent.show(answer([1, 2, 3])))
        first = list(shelf.items)
        changes = []
        shelf.items.connect('items-changed', lambda *args: changes.append(args[1:]))
        # Item 4 played since: it leads, and the others keep their objects.
        self.assertTrue(recent.show(answer([4, 1, 2, 3])))
        self.assertEqual(changes, [(0, 0, 1)])  # one insertion, nothing rebuilt
        self.assertEqual(list(shelf.items)[1:], first)
        self.assertIs(recent.shelf, shelf)
        self.assertFalse(recent.show(answer([4, 1, 2, 3])))  # the same: nothing changes
        self.assertEqual(len(changes), 1)

    def test_a_kept_item_follows_its_new_fields_and_keeps_its_tracks(self):
        recent = home.RecentlyPlayed()
        recent.show(answer([1]))
        item = recent.shelf.items.get_item(0)
        item.raw['groups'] = [{'name': '', 'entries': []}]  # an album page fetched them
        renamed = {'items': [played(1, title='Invented Renamed')]}
        recent.show(renamed)
        self.assertIs(recent.shelf.items.get_item(0), item)
        self.assertEqual(item.title, 'Invented Renamed')
        self.assertEqual(item.raw['groups'], [{'name': '', 'entries': []}])

    def test_the_librarys_own_items_are_its_objects(self):
        class Library:
            def __init__(self, items):
                self.items = {(item.kind, item.id): item for item in items}

            def by_id(self, kind, item_id):
                return self.items.get((kind, item_id))

        own = Item(album(7))
        recent = home.RecentlyPlayed()
        recent.show({'items': [dict(album(7), groups=[]), played(1)]}, Library([own]))
        self.assertIs(recent.shelf.items.get_item(0), own)
        self.assertEqual(recent.shelf.items.get_item(1).id, '900000501')

    def test_items_without_an_id_or_met_twice_are_left_out(self):
        recent = home.RecentlyPlayed()
        recent.show({'items': [played(1), {'kind': 'album'}, played(1), 'junk', played(2)]})
        self.assertEqual([item.id for item in recent.shelf.items], ['900000501', '900000502'])
        for nothing in (None, {}, {'items': 'junk'}):
            recent.show(nothing)
            self.assertEqual(recent.shelf.items.get_n_items(), 0)

    def test_an_items_artwork_is_fetched_where_remote_art_keeps_it(self):
        recent = home.RecentlyPlayed()
        recent.show({'items': [played(1, art='https://x/a/100x100bb.jpg')]})
        item = recent.shelf.items.get_item(0)
        self.assertIn('remote-art', item.thumb)
        self.assertTrue(item.raw['thumbUrl'].startswith('https://'))

    def test_clear(self):
        recent = home.RecentlyPlayed()
        recent.show(answer([1, 2]))
        recent.clear()
        self.assertEqual(recent.shelf.items.get_n_items(), 0)


def shelf(key, items):
    return ShelfModel(key, key.title(), [Item(data) for data in items])


class ArrangeTest(unittest.TestCase):
    def setUp(self):
        self.recent = ShelfModel(home.RECENT_KEY, 'Recently Played', [])

    def test_after_the_first_shelf_or_alone_and_never_empty(self):
        picks = shelf('rec-top', [played(10), played(11)])
        rotation = shelf('heavy-rotation', [played(12)])
        empty = shelf('recently-added', [])
        self.assertEqual(home.arrange([picks, empty, rotation], self.recent), [picks, rotation])
        self.recent.items.append(Item(played(1)))
        self.assertEqual(home.arrange([picks, empty, rotation], self.recent),
                         [picks, self.recent, rotation])
        self.assertEqual(home.arrange([], self.recent), [self.recent])

    def test_apples_own_recently_played_is_left_out_while_the_shelf_shows(self):
        for number in (1, 2, 3):
            self.recent.items.append(Item(played(number, catalogId=f'cat{number}')))
        picks = shelf('rec-top', [played(10), played(11)])
        theirs = shelf('rec-recent', [played(1), dict(played(2), id='cat2')])  # by catalog id
        partly = shelf('rec-more', [played(1), played(12)])
        one = shelf('rec-one', [played(3)])  # one item proves nothing
        fixed = shelf('heavy-rotation', [played(1), played(2)])  # not one of Apple's picks
        self.assertEqual(home.arrange([picks, theirs, partly, one, fixed], self.recent),
                         [picks, self.recent, partly, one, fixed])
        self.recent.items.remove_all()
        self.assertEqual(home.arrange([picks, theirs], self.recent), [picks, theirs])

    def test_hold_back(self):
        self.assertFalse(home.hold_back(True, True, True, False))  # in place: fine anywhere
        self.assertFalse(home.hold_back(False, True, False, False))  # at the top: fine
        self.assertTrue(home.hold_back(False, True, True, False))  # comes above the user
        self.assertTrue(home.hold_back(True, False, True, False))  # goes from above them
        self.assertTrue(home.hold_back(True, True, False, True))  # the focus is in it


class HomePageTest(PageTestCase):
    async def asyncSetUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = cache.name
        patcher = mock.patch.dict(os.environ, {'APPLE_MUSIC_CACHE': self.cache})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def home_page(self, shelves=None):
        from applemusic.pages.home import HomePage

        if shelves is None:
            shelves = [{'key': 'rec-top', 'title': 'Invented Picks',
                        'items': [album(1), album(2)]},
                       {'key': 'heavy-rotation', 'title': '', 'items': [album(3)]}]
        data = {'version': 3, 'generated': '2026-01-01T00:00:00Z', 'storefront': 'gb',
                'sections': {'albums': [album(n) for n in range(1, 4)], 'playlists': []},
                'shelves': shelves}
        Path(self.cache, 'library.json').write_text(json.dumps(data), encoding='utf-8')
        await self.library.load()
        page = HomePage(self.library, 'Home', 'go-home-symbolic')
        await self.show_root(page)
        await self.settle()
        return page

    def shown(self, page):
        return [widget.shelf.key for widget in page._column.widgets if widget.get_visible()]

    def recent_ids(self, page):
        return [item.id for item in page._recent.shelf.items]

    def up(self):
        self.app.engine.authorized = True
        self.app.engine.state = 'up'

    async def test_the_kept_answer_then_apples_in_place(self):
        engine = self.app.engine
        self.up()
        kept = answer([1, 2], seconds_ago=3600, now=datetime.now(UTC))
        fresh = answer([3, 1, 2], now=datetime.now(UTC))
        engine.answers['recently_played'] = lambda refresh: fresh if refresh else kept
        page = await self.home_page()
        self.assertEqual(engine.recent_requests, [False, True])  # kept, then Apple's
        self.assertEqual(self.shown(page), ['rec-top', 'recently-played', 'heavy-rotation'])
        self.assertEqual(self.recent_ids(page), ['900000503', '900000501', '900000502'])
        self.assertEqual(page._column.widgets[1].shelf.title, 'Recently Played')
        self.assertEqual(self.app.reported, [])
        widget = page._column.widgets[1]
        items = list(page._recent.shelf.items)

        # Shown again within the minute: nothing asked; after it, Apple again, in place.
        self.window.navigation_view.push(album_page := self.pushed())
        self.assertTrue(await self.until(album_page.get_mapped))
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(page.get_mapped))
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, True])
        page._answer = dict(page._answer, cached=stamp(120, datetime.now(UTC)))
        engine.answers['recently_played'] = answer([4, 3, 1, 2], now=datetime.now(UTC))
        page.unmap()
        page.map()
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, True, True])
        self.assertEqual(self.recent_ids(page)[0], '900000504')
        self.assertIs(page._column.widgets[1], widget)  # the same shelf widget
        self.assertEqual(list(page._recent.shelf.items)[1:], items)  # the same Items

    def pushed(self):
        from gi.repository import Adw, Gtk

        return Adw.NavigationPage(title='Pushed', child=Gtk.Label(label='Invented'))

    async def test_the_engine_down_shows_the_kept_answer_and_asks_once_it_is_up(self):
        engine = self.app.engine
        kept = answer([1], seconds_ago=3600, now=datetime.now(UTC))

        def ask(refresh):
            if refresh and engine.state != 'up':
                return EngineError('engine-down')
            return kept if not refresh else answer([2, 1], now=datetime.now(UTC))

        engine.answers['recently_played'] = ask
        page = await self.home_page()
        self.assertEqual(self.recent_ids(page), ['900000501'])
        self.assertEqual(engine.recent_requests, [False, True])
        self.assertEqual((self.app.reported, self.app.toasts), ([], []))  # nothing toasted
        self.up()
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, True, True])
        self.assertEqual(self.recent_ids(page), ['900000502', '900000501'])

    async def test_nothing_kept_and_apple_failing_leaves_the_library_shelves(self):
        self.up()
        self.app.engine.answers['recently_played'] = EngineError('timeout')
        page = await self.home_page()
        self.assertEqual(self.shown(page), ['rec-top', 'heavy-rotation'])
        self.assertEqual((self.app.reported, self.app.toasts), ([], []))
        page.unmap()
        page.map()
        await self.settle()
        self.assertEqual(self.app.engine.recent_requests, [False])  # not again at once

    async def test_recently_played_alone_in_an_empty_library(self):
        self.up()
        self.app.engine.answers['recently_played'] = answer([1], now=datetime.now(UTC))
        page = await self.home_page(shelves=[])
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        self.assertEqual(self.shown(page), ['recently-played'])
        self.assertTrue(page._column.widgets[0].props.hero)

    async def test_an_answer_waits_while_the_focus_is_in_the_shelf(self):
        self.up()
        engine = self.app.engine
        engine.answers['recently_played'] = answer([1, 2], now=datetime.now(UTC))
        page = await self.home_page()
        widget = page._column.widget_for(page._recent.shelf)
        self.assertTrue(await self.until(lambda: widget.list_view.get_first_child()
                                         is not None))
        from gi.repository import Gtk

        self.assertTrue(widget.list_view.child_focus(Gtk.DirectionType.TAB_FORWARD))
        engine.answers['recently_played'] = answer([3, 1, 2], now=datetime.now(UTC))
        page.refresh()
        await self.settle()
        self.assertEqual(self.recent_ids(page), ['900000501', '900000502'])  # held back
        page.unmap()
        page.map()
        self.assertEqual(self.recent_ids(page)[0], '900000503')  # shown as the page is

    async def test_a_new_shelf_waits_while_the_page_is_scrolled_down(self):
        self.up()
        self.app.engine.answers['recently_played'] = EngineError('timeout')
        many = [{'key': f'rec-{n}', 'title': f'Invented {n}', 'items': [album(1), album(2)]}
                for n in range(8)]
        page = await self.home_page(shelves=many)
        adjustment = page.scrolled_window.get_vadjustment()
        self.assertTrue(await self.until(lambda: adjustment.get_upper()
                                         > adjustment.get_page_size() + 100))
        adjustment.set_value(100)
        page._show_recent(answer([1], now=datetime.now(UTC)))
        self.assertNotIn('recently-played', self.shown(page))
        page.unmap()
        page.map()
        self.assertEqual(self.shown(page)[1], 'recently-played')

    async def test_refresh_asks_apple_and_the_sync_for_the_shelves(self):
        self.up()
        engine = self.app.engine
        engine.answers['recently_played'] = answer([1], now=datetime.now(UTC))
        page = await self.home_page()
        self.assertEqual(engine.recent_requests, [False])  # fresh: Apple not asked again
        self.assertTrue(page.refresh_button.get_visible())
        page.refresh_button.emit('clicked')
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, True])
        self.assertEqual(self.app.syncs, [{'shelves': True}])
        page.refresh()  # F5's way (win.refresh)
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, True, True])

    async def test_refresh_while_the_engine_is_down_asks_once_it_is_up(self):
        engine = self.app.engine
        engine.answers['recently_played'] = lambda refresh: (
            EngineError('engine-down') if engine.state != 'up'
            else answer([1], now=datetime.now(UTC)))
        page = await self.home_page()
        page.refresh()
        await self.settle()
        self.assertEqual(self.app.syncs, [{'shelves': True}])  # which starts the engine
        self.assertEqual(self.recent_ids(page), [])
        self.assertEqual((self.app.reported, self.app.toasts), ([], []))
        self.up()
        await self.settle()
        self.assertEqual(self.recent_ids(page), ['900000501'])

    async def test_signed_out_nothing_is_asked_and_refresh_offers_the_sign_in(self):
        self.app.settings.set_boolean('signed-in', False)
        self.app.engine.answers['recently_played'] = answer([1], now=datetime.now(UTC))
        page = await self.home_page()
        self.assertEqual(self.app.engine.recent_requests, [])
        self.assertNotIn('recently-played', self.shown(page))
        page.refresh()
        self.assertEqual(self.app.actions, ['sign-in'])
        self.assertEqual(self.app.syncs, [])

    async def test_signing_out_takes_the_shelf_away(self):
        self.up()
        self.app.engine.answers['recently_played'] = answer([1], now=datetime.now(UTC))
        page = await self.home_page()
        self.assertIn('recently-played', self.shown(page))
        self.app.settings.set_boolean('signed-in', False)
        await self.settle()
        self.assertNotIn('recently-played', self.shown(page))
        self.assertIsNone(page._answer)

    async def test_a_sign_out_while_hidden_forgets_the_answer(self):
        # The window forgets Home's account state at sign-out (forget_account_pages()):
        # another account signed in, Home shows nothing of the old answer and asks Apple.
        engine = self.app.engine
        self.up()
        engine.answers['recently_played'] = answer([1, 2], now=datetime.now(UTC))
        page = await self.home_page()
        self.assertEqual(self.recent_ids(page), ['900000501', '900000502'])
        self.assertEqual(engine.recent_requests, [False])  # under a minute old: kept
        self.window.navigation_view.push(covering := self.pushed())
        self.assertTrue(await self.until(covering.get_mapped))
        self.app.settings.set_boolean('signed-in', False)
        page.forget_account()
        self.app.settings.set_boolean('signed-in', True)
        engine.answers['recently_played'] = (
            lambda refresh: answer([7, 8], now=datetime.now(UTC)) if refresh else {})
        self.assertEqual(self.recent_ids(page), [])
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(page.get_mapped))
        await self.settle()
        self.assertEqual(engine.recent_requests, [False, False, True])
        self.assertEqual(self.recent_ids(page), ['900000507', '900000508'])

    async def test_a_failure_before_the_sign_out_does_not_hold_the_next_account_back(self):
        self.up()
        self.app.engine.answers['recently_played'] = EngineError('timeout')
        page = await self.home_page()
        self.assertEqual(self.app.engine.recent_requests, [False])
        page.forget_account()
        self.app.engine.answers['recently_played'] = answer([3], now=datetime.now(UTC))
        page.unmap()
        page.map()
        await self.settle()
        self.assertEqual(self.recent_ids(page), ['900000503'])

    async def test_the_demo_shows_its_invented_answer_and_refresh_reads_it_again(self):
        self.app.demo = True
        self.app.engine.answers['recently_played'] = answer([1, 2], seconds_ago=10 ** 6,
                                                            demo=True)
        page = await self.home_page()
        self.assertEqual(self.app.engine.recent_requests, [False])  # old, but the demo's
        self.assertEqual(self.recent_ids(page), ['900000501', '900000502'])
        page.refresh()
        await self.settle()
        self.assertEqual(self.app.engine.recent_requests, [False, True])
        self.assertEqual(self.app.syncs, [])
        self.assertEqual((self.app.reported, self.app.toasts), ([], []))

    async def test_a_tile_opens_its_item_and_see_all_its_shelf(self):
        self.up()
        self.app.engine.answers['recently_played'] = answer([1], now=datetime.now(UTC))
        page = await self.home_page()
        widget = page._column.widget_for(page._recent.shelf)
        widget.list_view.emit('activate', 0)
        self.assertEqual([item.id for item in self.window.opened], ['900000501'])


class ShelfStoreTest(unittest.TestCase):
    def test_the_shelf_is_a_list_store_of_items(self):
        recent = home.RecentlyPlayed()
        self.assertIsInstance(recent.shelf.items, Gio.ListStore)
        self.assertIs(recent.shelf.items.get_item_type().pytype, Item)


if __name__ == '__main__':
    unittest.main()
