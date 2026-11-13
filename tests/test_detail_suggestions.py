# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The songs Apple suggests adding to a playlist, under its tracks on its page
(pages/detail_suggestions.py), over the stand-in engine (tests/page_harness.py)."""

import asyncio

from tests.page_harness import PageTestCase, album


def suggestion(number):
    """An invented song as Engine.playlist_suggestions answers one."""
    song_id = str(2000 + number)
    return {'id': song_id, 'kind': 'song', 'title': f'Suggested Song {number}',
            'subtitle': 'Other Artist', 'album': 'Other Album', 'art': None, 'thumb': None,
            'catalogId': song_id, 'play': {'kind': 'song', 'id': song_id}, 'groups': []}


class SuggestionsTest(PageTestCase):
    """A playlist's Suggested Songs: asked once for a playlist the user can change, six (or
    twelve) at a time less the songs it holds, played, added (the place filled from the
    spares, a few more asked for when they run out) and refreshed (Apple told what it
    offered)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.app.settings.reset, 'more-suggestions')

    def playlist(self):
        data = album(1, tracks=3, kind='playlist')
        data['groups'][0]['entries'][1]['catalogId'] = '2001'  # suggestion 1, held already
        return data

    async def show(self, data, answer=None):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        if answer is not None:
            self.app.engine.answers['playlist_suggestions'] = answer
        self.item = Item(data)
        page = await self.push(DetailPage(self.library, self.item))
        await self.settle()
        return page

    def shown(self, page):
        return [item.id for item in page.suggested_songs.items]

    def answer(self, numbers):
        return {'items': [suggestion(number) for number in numbers]}

    def test_which_playlists_and_songs(self):
        from applemusic.library import Item
        from applemusic.pages.detail_suggestions import (held_songs, suggestion_items,
                                                         wants_suggestions)

        self.assertTrue(wants_suggestions(Item({'id': 'p.1', 'kind': 'playlist'})))
        for data in ({'id': 'pl.u-1', 'kind': 'playlist'}, {'id': 'l.1', 'kind': 'album'},
                     {'id': 'p.2', 'kind': 'playlist', 'attributes': {'isFavourites': True}},
                     {'id': 'p.3', 'kind': 'playlist', 'attributes': {'canEdit': False}}):
            self.assertFalse(wants_suggestions(Item(data)), data)
        self.assertFalse(wants_suggestions(None))
        playlist = Item(self.playlist())
        self.assertEqual(held_songs(playlist), {
            'l.playlist001.t1.0', 'l.playlist001.t1.1', '2001', 'l.playlist001.t1.2'})
        answer = self.answer(range(2))
        answer['items'].append({'id': '9', 'kind': 'station'})
        self.assertEqual([item.id for item in suggestion_items(answer)], ['2000', '2001'])

    async def test_six_after_the_tracks_less_what_the_playlist_holds(self):
        page = await self.show(self.playlist(), self.answer(range(12)))
        self.assertEqual(self.app.engine.calls, ['playlist_suggestions'])
        self.assertEqual(self.shown(page), ['2000', '2002', '2003', '2004', '2005', '2006'])
        self.assertEqual(page._rows.get_n_items(), 1 + 3 + 1)  # hero, tracks, suggestions
        section = page.suggested_songs
        self.assertTrue(await self.until(lambda: section.get_mapped()))
        self.assertEqual(section.title_label.get_label(), 'Suggested Songs')
        self.assertTrue(section.subtitle_label.get_visible())
        self.assertEqual(section.refresh_button.get_tooltip_text(), 'Suggest Other Songs')
        # A song plays alone.
        section.grid.rows[1].play_button.emit('clicked')
        self.assertEqual(self.window.played[-1], ({'kind': 'song', 'id': '2002'}, None, None))

    async def test_the_row_holding_them_is_as_tall_as_their_lines(self):
        # The grid is taller the narrower it is. Its row in the list asks for the height of
        # the lines it has at the width given: in a horizontal box it asked for the one
        # column's at every width (GTK's "natural size must be >= min size", and room left
        # empty under a wide grid).
        from gi.repository import Gtk

        page = await self.show(self.playlist(), self.answer(range(12)))
        row = page.suggested_songs.get_parent()
        heights = {}
        for width in (360, 996):
            minimum, natural, _, _ = row.measure(Gtk.Orientation.VERTICAL, width)
            self.assertEqual(minimum, natural, width)
            heights[width] = minimum
        self.assertLess(heights[996], heights[360])

    async def test_an_add_that_fails_gives_the_song_its_place_back(self):
        page = await self.show(self.playlist(), self.answer(range(9)))
        actions = self.window.item_actions
        actions.add_succeeds = False  # reported by the item actions
        self.addCleanup(setattr, actions, 'add_succeeds', True)  # the window outlives the test
        rows = list(page.suggested_songs.grid.rows)
        rows[1].add_button.emit('clicked')
        await self.settle()
        # Back in its place, the spare that took it back at the front of the spares, and not
        # told to Apple as chosen.
        self.assertEqual(self.shown(page), ['2000', '2002', '2003', '2004', '2005', '2006'])
        self.assertEqual(page.suggested_songs.grid.rows, rows)
        self.assertEqual(page._suggestions.selected, [])
        self.assertEqual([item.id for item in page._suggestions.spares], ['2007', '2008'])

    async def test_an_add_that_fails_after_the_page_has_gone_leaves_it_alone(self):
        page = await self.show(self.playlist(), self.answer(range(9)))
        written = asyncio.get_running_loop().create_future()
        actions = self.window.item_actions
        actions.add_to_playlist = lambda *args: written
        self.addCleanup(delattr, actions, 'add_to_playlist')  # the window outlives the test
        page.suggested_songs.grid.rows[1].add_button.emit('clicked')
        suggestions = page._suggestions
        page._suggestions = None  # the page shows another playlist, or none, by now
        written.set_result(False)
        await self.settle()
        self.assertEqual(suggestions.selected, [])  # still not reported as chosen
        self.assertIsNone(page._suggestions)

    async def test_an_added_song_gives_its_place_to_the_next(self):
        page = await self.show(self.playlist(), self.answer(range(9)))
        rows = list(page.suggested_songs.grid.rows)
        rows[1].add_button.emit('clicked')
        self.assertEqual(self.window.item_actions.added,
                         [('l.playlist001', '2002', 'Suggested Song 2')])
        # In place: the same rows, the second bound to the next spare.
        self.assertEqual(self.shown(page), ['2000', '2007', '2003', '2004', '2005', '2006'])
        self.assertEqual(page.suggested_songs.grid.rows, rows)
        self.assertEqual(rows[1].song_row.caption.get_text(), 'Other Artist · Other Album')
        self.assertEqual(rows[1].add_button.get_tooltip_text(), 'Add to Playlist')
        # The last spare goes: a few more are asked for, telling Apple what it offered and
        # what was added.
        self.app.engine.answers['more_suggestions'] = self.answer(range(20, 24))
        rows[2].add_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls[-1], 'more_suggestions')
        request = self.app.engine.suggestion_requests[-1]
        self.assertTrue(request['more'])
        self.assertEqual(request['limit'], 4)
        self.assertEqual(request['selected'], ['2002', '2003'])
        self.assertEqual(request['offered'],
                         ['2000', '2002', '2003', '2004', '2005', '2006', '2007', '2008'])
        self.assertEqual(self.shown(page), ['2000', '2007', '2008', '2004', '2005', '2006'])
        rows[0].add_button.emit('clicked')
        self.assertEqual(self.shown(page)[0], '2020')

    async def test_asked_for_what_the_playlist_holds_and_not_again_after_an_add(self):
        from applemusic.pages.detail_suggestions import held_songs
        from applemusic.suggestions import basis

        page = await self.show(self.playlist(), self.answer(range(12)))
        held = basis(held_songs(self.item))
        self.assertEqual(self.app.engine.suggestion_requests[0]['basis'], held)
        # A song added: the playlist is fetched again and shows it, and the open page keeps
        # its suggestions (the next page shown asks again, for the new basis).
        page.suggested_songs.grid.rows[0].add_button.emit('clicked')
        data = self.playlist()
        data['groups'][0]['entries'].append(dict(data['groups'][0]['entries'][0],
                                                 id='l.playlist001.t1.3', catalogId='2000'))
        self.item.merge(data)
        await self.settle()
        self.assertEqual(self.app.engine.calls.count('playlist_suggestions'), 1)
        self.assertEqual(self.shown(page)[0], '2007')
        # A Refresh asks for what the playlist holds now.
        page.suggested_songs.refresh_button.emit('clicked')
        await self.settle()
        request = next(request for request in self.app.engine.suggestion_requests
                       if request['refresh'])
        self.assertNotEqual(request['basis'], held)
        self.assertEqual(request['basis'], basis(held_songs(self.item)))

    async def test_with_no_spares_a_place_is_given_up(self):
        page = await self.show(self.playlist(), self.answer([0]))
        self.assertEqual(self.app.engine.calls, ['playlist_suggestions', 'more_suggestions'])
        page.suggested_songs.grid.rows[0].add_button.emit('clicked')
        await self.settle()
        # Apple had none more when asked: not asked again until a Refresh.
        self.assertEqual(self.app.engine.calls.count('more_suggestions'), 1)
        self.assertEqual(page._rows.get_n_items(), 4)  # none left: the section goes

    async def test_refresh_asks_for_new_ones_telling_apple_what_it_offered(self):
        page = await self.show(self.playlist(), self.answer(range(12)))
        self.app.engine.answers['playlist_suggestions'] = lambda _id, refresh: (
            self.answer(range(30, 40)) if refresh else self.answer([]))
        page.suggested_songs.refresh_button.emit('clicked')
        await self.settle()
        request = self.app.engine.suggestion_requests[-1]
        self.assertTrue(request['refresh'])
        self.assertEqual(request['limit'], 6 + 4)
        self.assertEqual(request['offered'], ['2000', '2002', '2003', '2004', '2005', '2006'])
        self.assertEqual(self.shown(page), [str(2000 + n) for n in range(30, 36)])

    async def test_a_refresh_apple_cannot_answer_shows_the_spares(self):
        from applemusic.backend.errors import EngineError

        page = await self.show(self.playlist(), self.answer(range(14)))
        self.app.engine.answers['playlist_suggestions'] = EngineError('engine-down')
        page.suggested_songs.refresh_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.shown(page), ['2007', '2008', '2009', '2010', '2011', '2012'])

    async def test_twelve_with_the_setting_followed_while_shown(self):
        page = await self.show(self.playlist(), self.answer(range(16)))
        self.assertEqual(len(self.shown(page)), 6)
        self.app.settings.set_boolean('more-suggestions', True)
        await self.settle()
        self.assertEqual(self.shown(page),
                         ['2000'] + [str(2000 + n) for n in range(2, 13)])
        self.app.settings.set_boolean('more-suggestions', False)
        await self.settle()
        self.assertEqual(len(self.shown(page)), 6)

    async def test_none_when_the_engine_cannot_answer_or_for_an_album(self):
        page = await self.show(self.playlist())  # the stand-in engine is down
        self.assertEqual(self.app.engine.calls, ['playlist_suggestions'])
        self.assertEqual(page._rows.get_n_items(), 4)
        self.assertIsNone(page._suggestions_start)
        self.assertIsNone(page.suggested_songs)  # made only when there are suggestions
        self.app.engine.calls.clear()
        await self.show(album(2), self.answer([0]))
        self.assertEqual(self.app.engine.calls, [])

    def previewing(self, page):
        """The ids of the rows marked as previewing, and their descriptions said."""
        return [row.context_item.id for row in page.suggested_songs.grid.rows
                if row.song_row.preview_scrim.get_opacity() == 1]

    async def test_a_click_plays_a_preview_with_the_setting(self):
        self.addCleanup(self.app.settings.reset, 'preview-suggestions')
        answer = self.answer(range(12))
        for entry in answer['items']:
            if entry['id'] != '2003':  # one without a preview: it plays in full
                entry['previewUrl'] = f"https://example.invalid/{entry['id']}.m4a"
        page = await self.show(self.playlist(), answer)
        rows = page.suggested_songs.grid.rows
        # Off (the default): the song in full.
        rows[0].play_button.emit('clicked')
        self.assertEqual(self.window.played[-1][0], {'kind': 'song', 'id': '2000'})
        self.assertEqual(self.app.player.previews, [])
        # On: its preview, its row marked; clicked again, stopped.
        self.app.settings.set_boolean('preview-suggestions', True)
        played = len(self.window.played)
        rows[0].play_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.player.previews,
                         [('start', '2000', 'https://example.invalid/2000.m4a')])
        self.assertEqual(len(self.window.played), played)
        self.assertEqual(self.previewing(page), ['2000'])
        rows[0].play_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.player.previews[-1], ('stop',))
        self.assertEqual(self.previewing(page), [])
        # Without a preview: in full.
        rows[2].play_button.emit('clicked')
        self.assertEqual(self.window.played[-1][0], {'kind': 'song', 'id': '2003'})
        # A preview that ends on its own unmarks its row; the songs previewed are told to
        # Apple with the next request.
        rows[1].play_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.previewing(page), ['2002'])
        self.app.player.preview = ''
        self.assertEqual(self.previewing(page), [])
        page.suggested_songs.refresh_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.suggestion_requests[-1]['previewed'], ['2000', '2002'])

    async def test_a_preview_stops_when_the_page_is_left(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        self.addCleanup(self.app.settings.reset, 'preview-suggestions')
        self.app.settings.set_boolean('preview-suggestions', True)
        answer = self.answer(range(8))
        for entry in answer['items']:
            entry['previewUrl'] = f"https://example.invalid/{entry['id']}.m4a"
        page = await self.show(self.playlist(), answer)
        page.suggested_songs.grid.rows[0].play_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.player.preview, '2000')
        await self.push(DetailPage(self.library, Item(album(2))))
        await self.settle()
        self.assertEqual(self.app.player.previews[-1], ('stop',))
        self.assertEqual(self.app.player.preview, '')

    async def test_no_preview_with_the_demo_library(self):
        self.addCleanup(self.app.settings.reset, 'preview-suggestions')
        self.app.settings.set_boolean('preview-suggestions', True)
        answer = self.answer(range(8))
        answer['items'][0]['previewUrl'] = 'https://example.invalid/2000.m4a'
        page = await self.show(self.playlist(), answer)
        self.app.demo = True
        page.suggested_songs.grid.rows[0].play_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.player.previews, [])

    async def test_tab_from_a_track_reaches_them_and_back(self):
        from gi.repository import Gdk

        page = await self.show(self.playlist(), self.answer(range(8)))
        self.assertTrue(await self.until(lambda: len(page._bound) == 3))
        track_item = next(item for item in page._bound if item.get_item().index == 2)
        track_item.get_child().get_parent().grab_focus()
        handled = page._on_list_key_pressed(None, Gdk.KEY_Tab, 0, 0)
        self.assertTrue(handled)
        await self.turn()
        self.assertIs(self.window.get_focus(), page.suggested_songs.refresh_button)
        handled = page._on_list_key_pressed(None, Gdk.KEY_ISO_Left_Tab, 0,
                                            Gdk.ModifierType.SHIFT_MASK)
        self.assertTrue(handled)
        await self.turn()
        focus = self.window.get_focus()  # the last track's list item
        self.assertIsNotNone(focus)
        self.assertIs(focus.get_first_child().track_row.context_item.index, 2)
