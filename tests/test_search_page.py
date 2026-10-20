# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Search page over the stand-in engine (tests/page_harness.py): stale Apple Music answers
never take over, Your Library follows the library's state (and marks the song playing), and
the status pages offer Your Library."""

import asyncio
import unittest

from tests.page_harness import PageTestCase, album, playing, track

from applemusic.backend.errors import EngineError
from applemusic.library import Item


class SearchPageTest(PageTestCase):
    async def search_page(self):
        from applemusic.pages.search import SearchPage

        page = await self.show_root(SearchPage(self.library, 'Search'))
        await self.settle()
        return page

    def held(self, name, answer):
        """Make the engine's `name` requests wait for the returned future, then answer."""
        waiting = asyncio.get_running_loop().create_future()

        async def respond(*_args):
            await waiting
            return answer

        self.app.engine.answers[name] = respond
        return waiting

    def type(self, page, text):
        """Type text, and let the pause after typing pass at once."""
        page.search_entry.set_text(text)
        page._cancel_debounce()
        page._refresh()

    SUGGESTIONS = {'terms': [{'term': 'invented', 'display': 'invented'}], 'items': []}
    RESULTS = {'shelves': [{'key': 'albums', 'title': '',
                            'items': [dict(album(1, tracks=0), id='c1')]}]}

    async def test_a_late_suggestion_does_not_take_over_your_library(self):
        page = await self.search_page()
        waiting = self.held('suggest', self.SUGGESTIONS)
        self.type(page, 'inv')
        await self.turn()
        page.set_mode('library')
        waiting.set_result(None)
        await self.settle()
        self.assertEqual(page.mode, 'library')
        self.assertNotEqual(page.stack.get_visible_child_name(), 'suggestions')

    async def test_a_late_suggestion_does_not_take_over_a_cleared_entry(self):
        page = await self.search_page()
        waiting = self.held('suggest', self.SUGGESTIONS)
        self.type(page, 'inv')
        await self.turn()
        self.type(page, '')
        waiting.set_result(None)
        await self.settle()
        self.assertNotEqual(page.stack.get_visible_child_name(), 'suggestions')

    async def test_late_results_do_not_take_over_after_enter_then_clear(self):
        page = await self.search_page()
        waiting = self.held('search', self.RESULTS)
        page.search_entry.set_text('inv')
        page._on_entry_activated(page.search_entry)  # Enter: the search
        await self.turn()
        page.search_entry.set_text('')
        page._on_entry_activated(page.search_entry)  # Enter on nothing: the landing
        waiting.set_result(None)
        await self.settle()
        self.assertNotEqual(page.stack.get_visible_child_name(), 'results')

    async def test_results_show_when_nothing_newer_was_asked(self):
        page = await self.search_page()
        self.app.engine.answers['search'] = self.RESULTS
        page.search_entry.set_text('inv')
        page._on_entry_activated(page.search_entry)
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'results')

    async def test_the_engine_status_offers_your_library(self):
        page = await self.search_page()  # the landing: engine-down
        self.assertEqual(page.status_button.get_label(), 'Start Engine')
        self.assertTrue(page.status_library_button.get_visible())
        page.status_library_button.emit('clicked')
        self.assertEqual(page.mode, 'library')
        self.assertEqual(page.status_page.get_title(), 'Search Your Library')
        self.assertFalse(page.status_library_button.get_visible())

    async def test_the_demo_status_offers_your_library(self):
        self.app.demo = True
        page = await self.search_page()
        self.assertEqual(page.status_page.get_title(), 'Not Available in the Demo')
        self.assertFalse(page.status_button.get_visible())
        self.assertTrue(page.status_library_button.get_visible())

    async def test_a_failure_after_a_switch_to_your_library_is_dropped(self):
        page = await self.search_page()
        waiting = asyncio.get_running_loop().create_future()

        async def fail(*_args):
            await waiting
            raise EngineError('timeout')

        self.app.engine.answers['suggest'] = fail
        self.type(page, 'inv')
        await self.turn()
        page.set_mode('library')
        waiting.set_result(None)
        await self.settle()
        self.assertEqual(page.status_page.get_title(), 'No Results Found')

    async def test_your_library_leaves_its_spinner_when_the_library_is_ready(self):
        page = await self.search_page()
        self.library.songs_ready = True
        self.library.state = 'loading'
        page.set_mode('library')
        page.search_entry.set_text('no such thing')
        page._on_entry_activated(page.search_entry)
        self.assertEqual(page.stack.get_visible_child_name(), 'loading')
        self.library.state = 'ready'
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_title(), 'No Results Found')

    async def test_focus_waits_until_the_page_shows(self):
        from applemusic.pages.search import SearchPage

        page = SearchPage(self.library, 'Search')
        page.focus_entry()  # not shown yet: nothing to focus
        await self.show_root(page)
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.search_entry)))

    async def test_your_library_marks_the_song_playing(self):
        from applemusic.library import Track

        page = await self.search_page()
        self.assertTrue(page.songs_list.get_single_click_activate())  # a click plays
        songs = [track('l.album001', n) for n in range(3)]
        self.library.songs_ready = True
        self.library.songs.splice(0, 0, [Track(song) for song in songs])
        page.set_mode('library')
        self.type(page, 'song')
        self.assertTrue(await self.until(lambda: len(page._bound_songs) == 3))
        self.app.player.track = playing(songs[1])
        rows = {item.get_item().id: item for item in page._bound_songs}
        self.assertEqual([song_id for song_id, item in rows.items()
                          if item.get_child().playing], [songs[1]['id']])
        self.assertEqual(rows[songs[1]['id']].get_accessible_description(), 'Playing')
        self.assertEqual(rows[songs[0]['id']].get_accessible_description(), '3:00')
        self.app.player.track = None
        self.assertFalse(any(item.get_child().playing for item in page._bound_songs))

    LANDING = {'categories': [{'id': 'g1', 'kind': 'category', 'title': 'Invented Genre'}]}

    def signed_in_engine(self):
        self.app.engine.state = 'ready'
        self.app.engine.authorized = True
        self.app.engine.answers['landing'] = self.LANDING

    async def test_an_opened_result_is_recently_searched_on_the_landing(self):
        self.signed_in_engine()
        self.app.engine.answers['search'] = self.RESULTS
        page = await self.search_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'landing')
        self.assertFalse(page.recent_box.get_visible())  # nothing searched yet
        page.search_entry.set_text('inv')
        page._on_entry_activated(page.search_entry)
        await self.settle()
        shelf = page._column.widgets[0]
        shelf.list_view.emit('activate', 0)  # a result's tile
        self.assertEqual([item.id for item in self.window.opened], ['c1'])
        self.assertEqual(self.app.recent_searches.items.get_item(0).id, 'c1')
        self.type(page, '')
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'landing')
        self.assertTrue(page.recent_box.get_visible())
        child = page.recent_box.get_child_at_index(0)
        self.assertEqual(child.get_child().context_item.id, 'c1')
        page.recent_box.emit('child-activated', child)  # opened again from the landing
        self.assertEqual([item.id for item in self.window.opened], ['c1', 'c1'])
        page.recent_clear_button.emit('clicked')
        self.assertFalse(page.recent_box.get_visible())
        self.assertFalse(page.recent_header.get_visible())

    async def test_a_top_hit_and_your_library_are_remembered_a_category_not(self):
        self.signed_in_engine()
        self.app.engine.answers['suggest'] = {
            'terms': [], 'items': [{'id': 'c9', 'kind': 'artist', 'title': 'Invented Band'}]}
        self.library.albums.append(Item(album(1, tracks=0)))
        page = await self.search_page()
        page.categories_box.emit('child-activated', page.categories_box.get_child_at_index(0))
        self.assertEqual(self.app.recent_searches.items.get_n_items(), 0)
        self.type(page, 'inv')
        await self.settle()
        page.suggestions_list.emit('row-activated', page.suggestions_list.get_row_at_index(0))
        page.set_mode('library')
        self.type(page, 'invented')
        page.albums_shelf.list_view.emit('activate', 0)
        recent = self.app.recent_searches.items
        self.assertEqual([recent.get_item(i).kind for i in range(recent.get_n_items())],
                         ['album', 'artist'])

    async def test_top_charts_leads_the_categories_and_opens_the_charts(self):
        self.signed_in_engine()
        page = await self.search_page()
        tiles = [page.categories_box.get_child_at_index(n).get_child() for n in range(2)]
        self.assertEqual([(tile.item.kind, tile.item.title) for tile in tiles],
                         [('charts', 'Top Charts'), ('category', 'Invented Genre')])
        page.categories_box.emit('child-activated', page.categories_box.get_child_at_index(0))
        self.assertEqual([item.kind for item in self.window.opened], ['charts'])
        self.assertEqual(self.app.recent_searches.items.get_n_items(), 0)

    async def test_recently_searched_shows_without_categories(self):
        self.signed_in_engine()
        self.app.engine.answers['landing'] = {'categories': []}
        self.app.recent_searches.add(Item(album(1, tracks=0)))
        page = await self.search_page()
        self.assertEqual(page.stack.get_visible_child_name(), 'landing')
        self.assertTrue(page.recent_box.get_visible())
        self.assertFalse(page.categories_title_label.get_visible())
        self.assertIsNone(page.categories_box.get_child_at_index(0))  # nor Top Charts

    @staticmethod
    def songs_answer(text, kind, offset, count=40, limit=25):
        """Engine.search's answer for `count` invented songs, `limit` a page (the All
        search's: Top Results and the first 20)."""
        def song(number):
            return {'id': f'17240{number:05d}', 'kind': 'song', 'title': f'Song {number}',
                    'subtitle': 'Invented Artist'}
        if kind is None:
            return {'shelves': [
                {'key': 'top', 'title': '', 'items': [song(0)], 'next': None},
                {'key': 'songs', 'title': '', 'items': [song(n) for n in range(20)],
                 'next': 20}]}
        end = min(count, offset + limit)
        return {'shelves': [{'key': kind, 'title': '',
                             'items': [song(n) for n in range(offset, end)],
                             'next': end if end < count else None}]}

    async def test_the_filter_shows_one_kind_and_pages_on(self):
        self.signed_in_engine()
        self.app.engine.answers['search'] = self.songs_answer
        page = await self.search_page()
        self.assertTrue(page.kind_dropdown.get_visible())
        page.set_kind('songs')  # nothing typed: nothing asked
        self.assertEqual(self.app.engine.search_requests, [])
        self.type(page, 'invented')
        page._on_entry_activated(page.search_entry)
        self.assertTrue(await self.until(lambda: page.stack.get_visible_child_name() == 'kind'))
        # The first page, then the rest as the list (shorter than the window) asks for it.
        self.assertTrue(await self.until(lambda: page.kind_list.pager.state == 'done'))
        self.assertEqual([(r['kind'], r['offset'], r['limit'])
                          for r in self.app.engine.search_requests],
                         [('songs', 0, 25), ('songs', 25, 25)])
        self.assertEqual(page.kind_list.pager.items.get_n_items(), 40)
        self.assertTrue(await self.until(lambda: page.kind_list._footer_item is not None))
        footer = page.kind_list._footer_item
        self.assertEqual(footer.get_accessible_label(), '40 songs')
        self.assertFalse(footer.get_activatable())
        # A hit opens, and is remembered.
        page.kind_list.list_view.emit('activate', 3)
        self.assertEqual([item.id for item in self.window.opened], ['1724000003'])
        self.assertEqual(self.app.recent_searches.items.get_item(0).id, '1724000003')
        # Back to every kind: the shelves again.
        page.set_kind('all')
        self.assertTrue(await self.until(
            lambda: page.stack.get_visible_child_name() == 'results'))
        # Your Library has no filter.
        page.set_mode('library')
        self.assertFalse(page.kind_dropdown.get_visible())

    async def test_a_kind_with_nothing_found(self):
        self.signed_in_engine()
        self.app.engine.answers['search'] = {'shelves': []}
        page = await self.search_page()
        page.set_kind('radio-shows')
        self.type(page, 'invented')
        page._on_entry_activated(page.search_entry)
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'status')
        self.assertEqual(page.status_page.get_title(), 'No Results Found')

    async def test_a_failed_page_is_tried_again_from_the_footer(self):
        self.signed_in_engine()
        failing = []

        def answer(text, kind, offset):
            if offset and not failing:
                failing.append(offset)
                return EngineError('timeout')
            return self.songs_answer(text, kind, offset)

        self.app.engine.answers['search'] = answer
        page = await self.search_page()
        page.set_kind('songs')
        self.type(page, 'invented')
        page._on_entry_activated(page.search_entry)
        self.assertTrue(await self.until(lambda: page.kind_list.pager is not None
                                         and page.kind_list.pager.state == 'failed'))
        self.assertTrue(await self.until(lambda: page.kind_list._footer_item is not None))
        footer = page.kind_list._footer_item
        self.assertTrue(footer.get_activatable())
        self.assertEqual(footer.get_accessible_label(), 'Could not load more results')
        self.assertTrue(footer.get_child().retry_button.get_visible())
        footer.get_child().retry_button.emit('clicked')
        self.assertTrue(await self.until(lambda: page.kind_list.pager.state == 'done'))
        self.assertEqual(page.kind_list.pager.items.get_n_items(), 40)

    async def test_typing_on_stops_the_kinds_paging_for_good(self):
        # Typed on while the next page of a kind is on its way: the page is dropped, and the
        # list, still shown until the new answer replaces it, asks for it no more.
        self.signed_in_engine()
        waiting = asyncio.Event()

        async def answer(text, kind, offset):
            if offset:
                await waiting.wait()
            return self.songs_answer(text, kind, offset)

        self.app.engine.answers['search'] = answer
        self.held('suggest', self.SUGGESTIONS)
        page = await self.search_page()
        page.set_kind('songs')
        self.type(page, 'invented')
        page._on_entry_activated(page.search_entry)
        self.assertTrue(await self.until(lambda: page.kind_list.pager is not None
                                         and page.kind_list.pager.state == 'loading'))
        pager = page.kind_list.pager
        self.type(page, 'invente')
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'kind')
        self.assertIs(page.kind_list.pager, pager)
        self.assertEqual(pager.state, 'idle')
        self.assertEqual([(r['text'], r['offset']) for r in self.app.engine.search_requests],
                         [('invented', 0), ('invented', 25)])
        waiting.set()
        await self.settle()
        self.assertEqual(len(self.app.engine.search_requests), 2)
        self.assertEqual(pager.items.get_n_items(), 25)

    async def test_see_all_of_a_kind_is_a_page_that_pages_on(self):
        from applemusic.pages.search_all import SearchAllPage

        self.signed_in_engine()
        self.app.engine.answers['search'] = self.songs_answer
        page = await self.search_page()
        self.type(page, 'invented')
        page._on_entry_activated(page.search_entry)
        await self.settle()
        top, songs = page._column.shelves
        self.assertIsNone(getattr(top, 'make_page', None))  # Top Results: the grid
        self.assertEqual((songs.next, songs.more), (20, True))
        see_all = songs.make_page(songs)
        self.assertIsInstance(see_all, SearchAllPage)
        self.assertEqual((see_all.window_title.get_title(), see_all.window_title.get_subtitle()),
                         ('Songs', '“invented”'))
        await self.push(see_all)
        self.assertTrue(await self.until(lambda: see_all.pager.state == 'done'))
        self.assertEqual([(r['kind'], r['offset']) for r in self.app.engine.search_requests],
                         [(None, 0), ('songs', 20)])
        self.assertEqual(see_all.pager.items.get_n_items(), 40)
        see_all.results_list.list_view.emit('activate', 0)
        self.assertEqual([item.id for item in self.window.opened], ['1724000000'])

    async def test_see_all_covered_stops_and_shown_again_pages_on(self):
        from applemusic.pages.search_all import SearchAllPage
        from applemusic.search_pager import SearchPager

        self.signed_in_engine()
        waiting = asyncio.Event()

        async def answer(text, kind, offset):
            if offset:
                await waiting.wait()
            return self.songs_answer(text, kind, offset)

        self.app.engine.answers['search'] = answer
        first = self.songs_answer('invented', None, 0)['shelves'][1]['items']
        pager = SearchPager('invented', 'songs', [Item(data) for data in first], 20,
                            search=self.app.engine.search, spawn=self.app.spawn)
        see_all = await self.push(SearchAllPage(pager, 'Songs'))
        self.assertTrue(await self.until(lambda: pager.state == 'loading'))
        # Covered: the page on its way is dropped, and not asked for again while hidden.
        await self.push(SearchAllPage(SearchPager('other', 'albums', [], None), 'Albums'))
        self.assertTrue(await self.until(lambda: not see_all.get_mapped()))
        await self.turn()
        waiting.set()
        await self.turn()
        self.assertEqual((pager.state, len(self.app.engine.search_requests)), ('idle', 1))
        # Shown again: it pages on.
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: pager.state == 'done'))
        self.assertEqual([r['offset'] for r in self.app.engine.search_requests], [20, 20])
        self.assertEqual(pager.items.get_n_items(), 40)

    async def test_a_dropped_page_is_freed(self):
        # Sign-out drops the page (window.forget_account_pages()).
        import gc

        from applemusic.pages.search import SearchPage

        page = SearchPage(self.library, 'Search')
        self.window.navigation_view.add(page)
        self.window.navigation_view.replace([page])
        self.assertTrue(await self.until(page.get_mapped))
        page.set_mode('library')
        page.search_entry.set_text('invented')
        page._on_entry_activated(page.search_entry)
        finalized = []
        page.weak_ref(lambda: finalized.append(True))
        self.window.navigation_view.replace([self.window.root_page])
        self.window.navigation_view.remove(page)
        del page
        await self.settle()

        def freed():
            gc.collect()
            return finalized

        self.assertTrue(await self.until(freed))


if __name__ == '__main__':
    unittest.main()
