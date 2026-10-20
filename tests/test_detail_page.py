# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The album, playlist and artist pages over the stand-in engine (tests/page_harness.py): an
item without tracks is fetched once, a popped page's fetch is cancelled, the pages follow
their Item, and a detail page fits the width it has, from the 360 px minimum up."""

import asyncio
import unittest

from tests.page_harness import PageTestCase, album, artist, artist_answer, playing, track

from applemusic.backend.errors import EngineError


class DetailPageTest(PageTestCase):
    def page(self, data):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        self.item = Item(data)
        return DetailPage(self.library, self.item)

    def rows(self, page):
        return page.list_view.get_model().get_n_items()

    def bound_row(self, page, track_id):
        """The bound list item showing the track with track_id."""
        return next(item for item in page._bound if item.get_item().id == track_id)

    def marked(self, page):
        """The ids of the tracks whose bound rows are marked as playing."""
        return sorted(item.get_item().id for item in page._bound
                      if item.get_child().track_row.playing)

    async def test_the_track_playing_is_marked(self):
        page = await self.push(self.page(album(1, tracks=3)))
        self.assertTrue(await self.until(lambda: len(page._bound) == 3))
        self.assertTrue(page.list_view.get_single_click_activate())  # a click plays
        self.assertEqual(self.marked(page), [])
        second = track('l.album001', 1)
        self.app.player.track = playing(second)
        self.assertEqual(self.marked(page), [second['id']])
        marked = self.bound_row(page, second['id'])
        row = marked.get_child().track_row
        self.assertEqual(row.number_stack.get_visible_child_name(), 'playing')
        self.assertEqual(marked.get_accessible_description(), 'Playing')
        other = self.bound_row(page, 'l.album001.t1.0')
        self.assertEqual(other.get_accessible_description(), '3:00')
        # The same song played from the catalog: its row is found by its catalog id.
        self.item.groups[0].entries.get_item(2).raw['catalogId'] = '123'
        self.app.player.track = playing(dict(track('l.album001', 2), id='123',
                                             catalogId='123'))
        self.assertEqual(self.marked(page), ['l.album001.t1.2'])
        self.assertEqual(marked.get_accessible_description(), '3:00')
        # Nothing playing: no row marked.
        self.app.player.track = None
        self.assertEqual(self.marked(page), [])
        self.assertEqual(self.bound_row(page, 'l.album001.t1.2').get_accessible_description(),
                         '3:00')

    async def test_the_mark_catches_up_when_shown_again(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        item = Item(album(1, tracks=3))
        page = await self.show_root(DetailPage(self.library, find=lambda: item, root=True,
                                               title='Invented Root'))
        self.assertTrue(await self.until(lambda: len(page._bound) == 3))
        self.window.navigation_view.replace([self.window.root_page])  # hidden
        self.assertTrue(await self.until(lambda: not page.get_mapped()))
        self.app.player.track = playing(track('l.album001', 0))
        self.assertEqual(self.marked(page), [])  # not followed while hidden
        self.window.navigation_view.replace([page])
        self.assertTrue(await self.until(page.get_mapped))
        self.assertEqual(self.marked(page), ['l.album001.t1.0'])

    def test_the_playing_song_s_place(self):
        from applemusic.library import Track
        from applemusic.pages.detail import playing_ordinal

        tracks = [Track(track('l.album001', number)) for number in range(4)]
        tracks[3] = Track(dict(track('l.album001', 1)))  # the same song again, fourth
        self.assertEqual(playing_ordinal(tracks, ('l.album001.t1.2', ''), 2), 2)
        # The same song twice: the one at the queue's index, else the first.
        self.assertEqual(playing_ordinal(tracks, ('l.album001.t1.1', ''), 3), 3)
        self.assertEqual(playing_ordinal(tracks, ('l.album001.t1.1', ''), 0), 1)
        self.assertIsNone(playing_ordinal(tracks, ('l.other.t1.0', ''), 0))
        self.assertIsNone(playing_ordinal(tracks, None, 0))
        self.assertIsNone(playing_ordinal([], ('l.album001.t1.0', ''), 0))

    async def test_go_to_current_song_focuses_its_row(self):
        page = await self.push(self.page(album(1, tracks=60)))
        self.assertTrue(await self.until(lambda: len(page._bound) > 3))
        self.app.player.track = playing(track('l.album001', 50))  # far below the fold
        page.reveal_playing()
        self.assertTrue(await self.until(
            lambda: (self.window.get_focus() is not None
                     and self.window.get_focus().is_ancestor(page.list_view)
                     and page._has_focus_at(51)), timeout=2))
        self.assertTrue(await self.until(lambda: not page._reveal_wanted))
        # A song the page does not hold: nothing moves, nothing is left waiting.
        self.app.player.track = playing(track('l.album009', 0))
        page.reveal_playing()
        await self.turn()
        self.assertFalse(page._reveal_wanted)
        self.assertTrue(page._has_focus_at(51))

    async def test_go_to_current_song_waits_for_the_tracks(self):
        tracks = album(1, tracks=5)
        self.app.engine.answers['item'] = tracks
        self.app.player.track = playing(track('l.album001', 3))
        page = await self.push(self.page(album(1, tracks=0)))
        page.reveal_playing()
        self.assertTrue(await self.until(lambda: page._has_focus_at(4), timeout=2))

    def test_should_fetch(self):
        from applemusic.library import Item
        from applemusic.pages.detail import should_fetch

        groupless = Item(album(1, tracks=0))
        self.assertTrue(should_fetch(groupless, None))
        self.assertFalse(should_fetch(groupless, groupless))  # asked once already
        self.assertFalse(should_fetch(Item(album(2)), None))  # has its tracks
        self.assertFalse(should_fetch(Item(dict(album(3, tracks=0), kind='station')), None))
        self.assertFalse(should_fetch(None, None))

    async def test_an_answer_without_tracks_is_asked_for_once(self):
        self.app.engine.answers['item'] = dict(album(1, tracks=0), summary='Invented notes')
        page = await self.push(self.page(album(1, tracks=0)))
        await self.settle()
        await self.turn()
        self.assertEqual(self.app.engine.calls, ['item'])
        self.assertEqual(page.status_title.get_label(), 'No Songs')
        self.assertFalse(page.status_button.get_visible())
        self.assertFalse(page.play_button.get_sensitive())  # nothing to play
        self.assertEqual(page.summary_label.get_label(), 'Invented notes')

    async def test_an_answer_with_tracks_shows_them(self):
        self.app.engine.answers['item'] = album(1, tracks=4)
        page = await self.push(self.page(album(1, tracks=0)))
        self.assertTrue(page.play_button.get_sensitive())  # the engine plays it by its id
        await self.settle()
        # The hero, four tracks and the footer.
        self.assertTrue(await self.until(lambda: self.rows(page) == 6))
        self.assertFalse(page.status_box.get_visible())
        self.assertTrue(page.play_button.get_sensitive())

    async def test_try_again_asks_again(self):
        self.app.engine.answers['item'] = EngineError('timeout')
        page = await self.push(self.page(album(1, tracks=0)))
        await self.settle()
        self.assertEqual(page.status_button.get_label(), 'Try Again')
        self.app.engine.answers['item'] = album(1, tracks=2)
        page.status_button.emit('clicked')
        await self.settle()
        self.assertEqual(self.app.engine.calls, ['item', 'item'])
        # The hero, two tracks and the footer.
        self.assertTrue(await self.until(lambda: self.rows(page) == 4))
        self.assertEqual(self.app.reported, [])  # shown on the page, not toasted too

    def album_answer(self):
        """An invented Engine.album_page answer: the release, and four shelves."""
        def entry(number):
            return {'id': str(1724049100 + number), 'kind': 'album', 'title': f'Other {number}',
                    'subtitle': '2026', 'art': None, 'thumb': None, 'groups': [],
                    'play': {'kind': 'album', 'id': str(1724049100 + number)}}
        return {'id': '1724049100', 'artistId': '42', 'artistName': 'Invented Artist',
                'release': {'releaseDate': '2026-03-14', 'copyright': '℗ 2026 Invented Records',
                            'recordLabel': 'Invented Records'},
                'shelves': [
                    {'key': 'other-versions', 'title': 'Other Versions', 'more': False,
                     'items': [entry(50)]},
                    {'key': 'more-by-artist', 'title': '', 'more': False,
                     'items': [entry(10), entry(11)]},
                    {'key': 'appears-on', 'title': 'Featured On', 'more': False,
                     'items': [dict(entry(70), kind='playlist', id='pl.70')]},
                    {'key': 'related-albums', 'title': 'You Might Also Like', 'more': True,
                     'items': [entry(30)]}]}

    async def test_an_album_ends_with_its_footer_and_the_catalogs_shelves(self):
        asked = []
        self.app.engine.answers['album_page'] = lambda *args: (asked.append(args),
                                                               self.album_answer())[1]
        page = await self.push(self.page(dict(album(1, tracks=3), catalogId='1724049100')))
        # The tracks and the footer at once, the shelves once the catalog answers.
        self.assertTrue(await self.until(lambda: self.rows(page) == 6))
        self.assertEqual(asked, [('1724049100', None)])
        self.assertEqual(page.footer_label.get_label().split('\n'),
                         ['14 March 2026', '3 songs, 9 minutes', '℗ 2026 Invented Records'])
        self.assertTrue(await self.until(lambda: page._shelf_column is not None
                                         and len(page._shelf_column.widgets) == 4))
        self.assertEqual([widget.title_label.get_label()
                          for widget in page._shelf_column.widgets],
                         ['Other Versions', 'More By Invented Artist', 'Featured On',
                          'You Might Also Like'])
        # See All fetches the rest of a shelf Apple has more of, the album left out.
        more = page._shelf_column.shelves[3]
        self.assertIsNone(page._shelf_column.shelves[0].complete)
        self.app.engine.answers['album_view'] = [
            {'id': '1724049130', 'kind': 'album', 'title': 'Other 30', 'groups': []},
            {'id': '1724049100', 'kind': 'album', 'title': 'This One', 'groups': []},
            {'id': '1724049131', 'kind': 'album', 'title': 'Other 31', 'groups': []}]
        await more.complete()
        self.assertEqual([item.id for item in more.items], ['1724049130', '1724049131'])
        self.assertFalse(more.more)
        # Asked once: the page shown again keeps its answer.
        self.window.navigation_view.push(self.page(album(2)))
        await self.settle()
        self.window.navigation_view.pop()
        await self.settle()
        self.assertEqual(len(asked), 1)

    async def test_a_library_album_is_asked_for_through_its_songs(self):
        asked = []
        self.app.engine.answers['album_page'] = lambda *args: (asked.append(args),
                                                               self.album_answer())[1]
        data = album(1, tracks=2)
        data['groups'][0]['entries'][1]['catalogId'] = '1724049201'
        page = await self.push(self.page(data))
        self.assertTrue(await self.until(lambda: self.rows(page) == 5))
        self.assertEqual(asked, [('l.album001', '1724049201')])

    async def test_an_album_without_an_answer_shows_what_it_has(self):
        # The engine down (or offline, or an album the catalog lacks): the tracks and the
        # footer's counts, no shelves, and nothing toasted.
        for answer in (EngineError('engine-down'), EngineError('api', 'gone', status=404)):
            with self.subTest(answer=answer.code):
                self.app.engine.answers['album_page'] = answer
                page = await self.push(self.page(dict(album(1, tracks=3),
                                                      catalogId='1724049100')))
                self.assertTrue(await self.until(
                    lambda: 'album_page' in self.app.engine.calls))
                await self.settle()
                self.assertEqual(self.rows(page), 5)  # the hero, three tracks, the footer
                self.assertEqual(page.footer_label.get_label(), '3 songs, 9 minutes')
                self.assertIsNone(page._shelf_column)  # none made
                self.assertEqual((self.app.reported, self.app.toasts), ([], []))
                self.window.navigation_view.pop()
                await self.settle()

    async def test_a_playlist_has_no_footer(self):
        page = await self.push(self.page(album(1, tracks=3, kind='playlist')))
        await self.settle()
        self.assertEqual(self.rows(page), 4)
        self.assertNotIn('album_page', self.app.engine.calls)

    async def test_popping_the_page_cancels_its_fetch(self):
        waiting = asyncio.get_running_loop().create_future()

        async def never(*_args):
            await waiting
            return album(1)

        self.app.engine.answers['item'] = never
        page = await self.push(self.page(album(1, tracks=0)))
        await self.turn()
        task = page._fetch_task
        self.assertFalse(task.done())
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: task.done()))
        self.assertTrue(task.cancelled())

    async def test_a_reload_that_changes_the_tracks_shows_them(self):
        page = await self.push(self.page(album(1, tracks=3, kind='playlist')))
        self.assertEqual(self.rows(page), 4)
        self.item.merge(album(1, tracks=5, kind='playlist'), replace=True)
        self.assertEqual(self.rows(page), 6)
        renamed = dict(album(1, tracks=5, kind='playlist'), title='Renamed Playlist')
        self.item.merge(renamed, replace=True)
        self.assertEqual(page.title_label.get_label(), 'Renamed Playlist')

    async def test_a_root_page_catches_up_when_shown_again(self):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        item = Item(album(1, tracks=3, kind='playlist'))
        page = await self.show_root(DetailPage(self.library, find=lambda: item, root=True,
                                               title='Invented Root'))
        self.assertEqual(self.rows(page), 4)
        self.window.navigation_view.replace([self.window.root_page])  # hidden
        self.assertTrue(await self.until(lambda: not page.get_mapped()))
        item.merge(album(1, tracks=1, kind='playlist'), replace=True)
        self.window.navigation_view.replace([page])
        self.assertTrue(await self.until(page.get_mapped))
        self.assertEqual(self.rows(page), 2)

    async def test_play_does_not_shuffle(self):
        page = await self.push(self.page(album(1)))
        page.play_button.emit('clicked')
        self.assertEqual(self.window.played, [(self.item.play, None, False)])

    def test_resolve_artist(self):
        from applemusic.library import Item
        from applemusic.pages.detail import resolve_artist

        artist_item = Item(artist([]))

        class Library:
            artists = [artist_item]

            def by_id(self, kind, item_id):
                return artist_item if (kind, item_id) == ('artist', 'l.artist001') else None

        library = Library()
        by_name = Item(dict(album(1), subtitle='INVENTED ARTIST'))
        self.assertIs(resolve_artist(library, by_name), artist_item)  # case folded
        by_id = Item(dict(album(2), subtitle='Another Name', artistId='l.artist001'))
        self.assertIs(resolve_artist(library, by_id), artist_item)
        self.assertIsNone(resolve_artist(library, Item(dict(album(3), subtitle='Nobody'))))
        playlist = Item(album(4, kind='playlist'))  # its subtitle is its curator
        self.assertIsNone(resolve_artist(library, playlist))

    async def test_the_artist_links_to_their_page(self):
        from applemusic.library import Item

        # The library's artist: what the library holds of them (window.open_item), at once.
        band = Item(artist([]))
        self.library.artists.append(band)
        page = await self.push(self.page(album(1)))
        self.assertTrue(page.artist_button.get_visible())
        self.assertFalse(page.subtitle_label.get_visible())
        page.artist_button.emit('clicked')
        self.assertEqual(self.window.opened, [band])
        self.assertEqual(self.window.item_actions.went, [])

    async def test_a_catalog_albums_artist_is_looked_up(self):
        # Not the library's: a catalog album's artist is linked, and found on a click.
        page = await self.push(self.page(dict(album(1), id='1000000300')))
        self.assertTrue(page.artist_button.get_visible())
        page.artist_button.emit('clicked')
        self.assertEqual(self.window.item_actions.went, [(self.item, 'artist')])
        # Nor in the demo, or for the library's own album of an artist it lacks.
        self.app.demo = True
        page = await self.push(self.page(dict(album(2), id='1000000301')))
        self.assertFalse(page.artist_button.get_visible())
        self.assertTrue(page.subtitle_label.get_visible())
        self.app.demo = False
        page = await self.push(self.page(album(3)))
        self.assertFalse(page.artist_button.get_visible())

    async def test_a_shelf_album_subtitled_with_its_year_is_by_its_artist(self):
        # An artist page's or Other Versions' album: subtitled with its year, its artist in
        # artistName. The page means the artist wherever it says one: the link, the rows.
        data = dict(album(1), id='1000000310', subtitle='2018', artistName='Invented Artist')
        page = await self.push(self.page(data))
        self.assertTrue(page.artist_button.get_visible())
        self.assertEqual(page.artist_label.get_label(), 'Invented Artist')
        self.assertEqual(page._album_artist, 'Invented Artist')  # its rows leave it out
        # One that came without its tracks: the answer merged in keeps the artist.
        answer = dict(album(2), id='1000000311')  # subtitled with the artist, as item() is
        self.app.engine.answers['item'] = answer
        data = dict(album(2, tracks=0), id='1000000311', subtitle='2019',
                    artistName='Invented Artist')
        page = await self.push(self.page(data))
        self.assertEqual(page.artist_label.get_label(), 'Invented Artist')
        await self.settle()
        self.assertTrue(await self.until(lambda: self.rows(page) > 1))
        self.assertEqual(self.item.subtitle, 'Invented Artist')
        self.assertEqual(page.artist_label.get_label(), 'Invented Artist')
        self.assertEqual(page._album_artist, 'Invented Artist')

    async def test_a_wide_playlist_is_a_table(self):
        # The stand-in window is 1000 px wide: the page's breakpoint makes it a table, its
        # column titles the tracks' header and each row's artist and album links.
        page = await self.push(self.page(album(1, tracks=3, kind='playlist')))
        self.assertTrue(await self.until(lambda: page.table and len(page._bound) == 3))
        self.assertIs(page.list_view.get_header_factory(), page._table_header_factory)
        rows = [item.get_child().track_row for item in page._bound]
        for row in rows:
            self.assertTrue(row.artist_link.get_visible())
            self.assertEqual(row.artist_link.get_text(), 'Invented Artist')
            self.assertEqual(row.album_link.get_text(), 'l.playlist001')
            self.assertFalse(row.artist_label.get_visible())
            self.assertTrue(row.columns.get_homogeneous())
        # Narrower: the list's rows again, the artist under the title.
        page.table = False
        self.assertIsNone(page.list_view.get_header_factory())
        for row in rows:
            self.assertFalse(row.artist_link.get_visible())
            self.assertTrue(row.artist_label.get_visible())
            self.assertFalse(row.columns.get_homogeneous())

    async def test_an_album_is_never_a_table(self):
        page = await self.push(self.page(album(1, tracks=3)))
        self.assertTrue(await self.until(lambda: page.table and len(page._bound) == 3))
        self.assertIsNone(page.list_view.get_header_factory())
        self.assertFalse(any(item.get_child().track_row.artist_link.get_visible()
                             for item in page._bound))

    async def test_a_link_opens_its_page(self):
        from applemusic.widgets import track_links

        page = await self.push(self.page(album(1, tracks=3, kind='playlist')))
        self.assertTrue(await self.until(lambda: page.table and len(page._bound) == 3))
        row = next(iter(page._bound)).get_child().track_row
        await self.until(lambda: row.album_link.get_width() > 0)
        self.assertTrue(row.album_link.active)
        found, centre = row.album_link.compute_bounds(page.list_view)
        self.assertTrue(found)
        x = centre.get_x() + centre.get_width() / 2
        y = centre.get_y() + centre.get_height() / 2
        self.assertIs(track_links.link_at(page.list_view, x, y), row.album_link)
        self.assertIsNone(track_links.link_at(page.list_view, x + centre.get_width(), y))
        self.assertTrue(track_links.open_link(page.list_view, row.album_link))
        self.assertEqual(self.window.item_actions.went,
                         [(row.context_item, 'album')])
        # The artist's link: the library's page of them when it has them (show_artist).
        self.assertTrue(track_links.open_link(page.list_view, row.artist_link))
        self.assertEqual(self.window.item_actions.went[-1],
                         (row.context_item, 'link to artist'))

    async def test_the_more_options_menu_is_the_items(self):
        page = await self.push(self.page(album(1)))
        page.more_button.popup()
        self.assertTrue(await self.until(lambda: self.window.item_actions.asked))
        self.assertIs(self.window.item_actions.asked[-1], self.item)
        page.more_button.popdown()

    @staticmethod
    def catalog(data):
        """An invented album or playlist dict as the catalog's: its id a catalog one."""
        catalog_id = '1724049' + data['id'][-3:]
        play = dict(data['play'], id=catalog_id)
        groups = [dict(group, play=play) for group in data['groups']]
        return dict(data, id=catalog_id, play=play, groups=groups)

    async def test_add_and_then_in_library(self):
        page = await self.push(self.page(self.catalog(album(1))))
        self.assertTrue(page.add_button.get_visible())
        self.assertFalse(page.in_library_box.get_visible())
        self.assertTrue(page.add_button.grab_focus())
        page.add_button.emit('clicked')
        [(item, task)] = self.window.item_actions.library_adds
        self.assertIs(item, self.item)
        page.add_button.emit('clicked')  # under way: not twice
        self.assertEqual(len(self.window.item_actions.library_adds), 1)
        # Apple took it: the item actions note it in the library, which the page follows.
        self.library.note_added(item)
        task.set_result(True)
        self.assertTrue(await self.until(lambda: page.in_library_box.get_visible()))
        self.assertFalse(page.add_button.get_visible())
        focus = self.window.get_focus()  # not lost with Add: More Options has it
        self.assertTrue(focus is page.more_button or focus.is_ancestor(page.more_button))

    async def test_an_add_that_fails_offers_add_again(self):
        page = await self.push(self.page(self.catalog(album(1, kind='playlist'))))
        page.add_button.emit('clicked')
        [(_item, task)] = self.window.item_actions.library_adds
        task.set_result(False)  # reported already, by the item actions
        await self.turn()
        self.assertTrue(page.add_button.get_visible())
        self.assertFalse(page.in_library_box.get_visible())
        page.add_button.emit('clicked')  # and it can be tried again
        self.assertEqual(len(self.window.item_actions.library_adds), 2)

    async def test_in_library_or_neither(self):
        from applemusic.library import Item

        # A catalog album the library holds (here, one just added, which it notes ahead of
        # Apple's listing).
        held = Item(self.catalog(album(2)))
        self.library.note_added(held)
        page = await self.push(self.page(held.raw))
        self.assertTrue(page.in_library_box.get_visible())
        self.assertFalse(page.add_button.get_visible())
        # The library's own album or playlist: its page is the library's, so neither.
        for kind in ('album', 'playlist'):
            page = await self.push(self.page(album(3, kind=kind)))
            self.assertFalse(page.add_button.get_visible(), kind)
            self.assertFalse(page.in_library_box.get_visible(), kind)

    async def test_a_playlists_curator_and_when_it_was_updated(self):
        data = album(1, kind='playlist')
        data.update(subtitle='Invented Curator', genre='Pop', modified='2026-01-01T12:00:00Z',
                    trackCount=3, durationMs=540000)
        page = await self.push(self.page(data))
        self.assertEqual(page.subtitle_label.get_label(), 'Invented Curator')
        self.assertTrue(page.caption_label.get_label().startswith('Updated '))
        self.assertTrue(page.caption_label.get_label().endswith(' · 3 songs, 9 min'))
        self.assertNotIn('Pop', page.caption_label.get_label())
        # One of the user's, which carries no curator: the account's name.
        self.app.settings.set_string('account-name', 'Alex Rivera')
        self.addCleanup(self.app.settings.reset, 'account-name')
        page = await self.push(self.page(dict(album(2, kind='playlist'), subtitle='')))
        self.assertEqual(page.subtitle_label.get_label(), 'Alex Rivera')
        self.assertTrue(page.subtitle_label.get_visible())
        # An album's caption is as it was: genre, year and songs.
        page = await self.push(self.page(album(3, year=2003)))
        self.assertTrue(page.caption_label.get_label().startswith('Pop · 2003 · '))

    async def shown_at(self, page, width):
        """page shown width px wide: in a clamp of that width (which hands its child that
        much, whatever the child's natural width) under the harness window's root page (its
        navigation view is 1000 px wide), laid out, its rows built. The clamp, for the test
        to remove."""
        from gi.repository import Adw

        clamp = Adw.Clamp(maximum_size=width, tightening_threshold=width,
                          unit=Adw.LengthUnit.PX, vexpand=True)
        clamp.set_child(page)
        self.window.root_box.append(clamp)
        self.assertTrue(await self.until(
            lambda: page.get_width() == width and page.list_view.get_first_child() is not None),
            f'{width} px')
        return clamp

    @staticmethod
    def minimum_width(page):
        """What the page asks of its width: its toolbar view's minimum, as the rows built so
        far make it (the breakpoint bin around it answers its own width-request, 360,
        whatever is inside)."""
        from gi.repository import Gtk

        toolbar_view = page.get_child().get_child()
        return toolbar_view.measure(Gtk.Orientation.HORIZONTAL, -1)[0]

    async def test_the_page_fits_the_width_it_has(self):
        # The hero's buttons row, beside the cover or under it, and the rows around it never
        # ask for more than the page has, from the 360 px minimum up (libadwaita would warn
        # "exceeds AdwBreakpointBin width" and cut the page's right edge): at 360, the narrow
        # breakpoints' stacked hero with the buttons' row whole; at 601sp, still the narrow
        # one (the cover beside the text needs 650); at 651sp, the wide one, which fits there.
        # Measured with the app's stylesheet (the rows' inset is its) and in GNOME's font, as
        # the screenshots are (scripts/harness.py's stock look): the test process's own may
        # be narrower. The setting reaches the widgets at the next style validation, which
        # their Pango context shows.
        from gi.repository import Gdk, Gtk

        from applemusic.widgets.shelf import text_scale

        provider = Gtk.CssProvider()
        provider.load_from_resource('/io/github/jackicus/MusicSleeve/style.css')
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display, display, provider)
        font = self.gtk_settings.props.gtk_font_name
        self.addCleanup(self.gtk_settings.set_property, 'gtk-font-name', font)
        self.gtk_settings.props.gtk_font_name = 'Adwaita Sans 11'
        self.assertTrue(await self.until(
            lambda: self.window.root_box.get_pango_context().get_font_description()
            .get_family() == 'Adwaita Sans'), 'the font setting applied')
        scale = text_scale(self.gtk_settings)  # the breakpoints are in sp
        narrow = 650 * scale
        for kind in ('album', 'playlist', 'catalog album'):
            for width in (360, round(600 * scale) + 1, round(narrow) + 1):
                data = album(1, tracks=3, kind=kind.split()[-1])
                page = self.page(self.catalog(data) if kind.startswith('catalog') else data)
                clamp = await self.shown_at(page, width)
                self.assertLessEqual(self.minimum_width(page), width, f'{kind} at {width}')
                hero_row = page.cover.get_parent()
                stacked = hero_row.get_orientation() == Gtk.Orientation.VERTICAL
                self.assertEqual(stacked, width <= narrow, f'{kind} at {width}')
                # Play, Shuffle and More Options on one line; Add, when there is one, on it
                # too or on the next, never cut.
                buttons = page.play_button.get_parent()
                self.assertEqual(page.add_button.get_visible(), kind.startswith('catalog'))
                lines = {child.compute_bounds(buttons)[1].get_y()
                         for child in (page.play_button, page.shuffle_button)}
                self.assertEqual(len(lines), 1, f'{kind} at {width}')
                for child in (page.play_button, page.shuffle_button, page.add_button,
                              page.more_button):
                    if child.get_visible():
                        natural = child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
                        bounds = child.compute_bounds(buttons)[1]  # padding included
                        self.assertGreaterEqual(bounds.get_width(), natural - 0.5,
                                                f'{kind} at {width}')
                        self.assertLessEqual(bounds.get_x() + bounds.get_width(),
                                             buttons.get_width() + 0.5, f'{kind} at {width}')
                self.window.root_box.remove(clamp)

    async def test_shift_tab_from_the_first_track_goes_back_to_the_hero(self):
        from gi.repository import Gdk, Gtk

        page = await self.push(self.page(album(1, tracks=3)))
        page.more_button.grab_focus()
        keys = next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Tab, 0, Gdk.ModifierType(0)))
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.list_view)))
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_ISO_Left_Tab, 0,
                                  Gdk.ModifierType.SHIFT_MASK))
        self.assertTrue(self.window.get_focus().is_ancestor(page.more_button))  # its toggle


class ReorderTest(PageTestCase):
    """A playlist's songs moved on its page: Alt+Up and Alt+Down on the focused song, and a
    drag of one of its own songs, with the insertion line where it would go."""

    async def show(self, **attributes):
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        data = album(1, tracks=4, kind='playlist')
        if attributes:
            data['attributes'] = attributes
        self.item = Item(data)
        page = await self.push(DetailPage(self.library, self.item))
        self.assertTrue(await self.until(
            lambda: len(page._bound) == 4 and page._row_at(3) is not None
            and page._row_at(3).get_height() > 0, timeout=2))
        return page

    def ids(self):
        return [track_id.rsplit('.', 1)[1] for track_id in self.item.track_ids()]

    def row(self, page, index):
        return page._row_at(index)

    def keys(self, page):
        from gi.repository import Gtk

        return next(controller for controller in _controllers(page.list_view)
                    if isinstance(controller, Gtk.EventControllerKey))

    async def test_which_pages_can_reorder(self):
        page = await self.show()
        self.assertTrue(page.can_reorder())
        for attributes in ({'isFavourites': True}, {'canEdit': False}):
            other = await self.show(**attributes)
            self.assertFalse(other.can_reorder())
        from applemusic.library import Item
        from applemusic.pages.detail import DetailPage

        album_page = await self.push(DetailPage(self.library, Item(album(2, tracks=3))))
        self.assertFalse(album_page.can_reorder())

    async def test_alt_down_and_alt_up_move_the_focused_song(self):
        from gi.repository import Gdk

        page = await self.show()
        self.row(page, 1).get_parent().grab_focus()  # the second song's row
        self.assertTrue(await self.until(
            lambda: self.window.get_focus() is not None
            and self.window.get_focus().is_ancestor(page.list_view)))
        keys = self.keys(page)
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Down, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['0', '2', '1', '3'])
        self.assertEqual(self.window.item_actions.moved, [('l.playlist001', 1, 2, False)])
        await self.turn()
        focus = self.window.get_focus()
        self.assertTrue(focus.is_ancestor(page.list_view) or focus is page.list_view)
        self.assertEqual(self.focused_track(page), 'l.playlist001.t1.1')  # it went with it
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['0', '1', '2', '3'])
        await self.turn()
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['1', '0', '2', '3'])
        await self.turn()
        # At the top: nothing moves, the key is the page's all the same.
        self.assertTrue(keys.emit('key-pressed', Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK))
        self.assertEqual(self.ids(), ['1', '0', '2', '3'])
        self.assertEqual(len(self.window.item_actions.moved), 3)
        # The hero's button focused: not a song, the key is not taken.
        page.play_button.grab_focus()
        self.assertFalse(keys.emit('key-pressed', Gdk.KEY_Down, 0, Gdk.ModifierType.ALT_MASK))

    def focused_track(self, page):
        from applemusic.pages.detail import _row_of

        row = _row_of(self.window.get_focus())
        return row.track_row.context_item.id if row is not None else None

    async def test_a_drag_of_its_own_song_shows_where_it_goes_and_moves_it(self):
        from gi.repository import Gdk

        from applemusic.library import ItemRefs
        from applemusic.widgets import dnd

        page = await self.show()
        song = self.item.groups[0].entries.get_item(0)
        dnd._set_current(ItemRefs.for_objects([song], origin=('playlist', 'l.playlist001')))
        self.addCleanup(dnd._set_current, None)
        self.assertTrue(page._on_drop_accept(None, None))

        def at(index, lower):
            bounds = self.row(page, index).compute_bounds(page.list_view)[1]
            return (bounds.origin.x + 10,
                    bounds.origin.y + (bounds.size.height - 2 if lower else 2))

        # The top half of the third song: the line on its top edge.
        self.assertEqual(page._on_drop_motion(None, *at(2, False)), Gdk.DragAction.MOVE)
        self.assertTrue(self.row(page, 2).has_css_class('drop-before'))
        # The bottom half of the last: on its bottom edge.
        self.assertEqual(page._on_drop_motion(None, *at(3, True)), Gdk.DragAction.MOVE)
        self.assertFalse(self.row(page, 2).has_css_class('drop-before'))
        self.assertTrue(self.row(page, 3).has_css_class('drop-after'))
        # Beside itself: where it is, no line and no drop.
        self.assertEqual(page._on_drop_motion(None, *at(0, True)), 0)
        self.assertEqual(page._on_drop_motion(None, *at(1, False)), 0)
        self.assertFalse(self.row(page, 3).has_css_class('drop-after'))
        # Dropped on the bottom half of the third song: after it, written at once.
        self.assertTrue(page._on_drop(None, None, *at(2, True)))
        self.assertEqual(self.window.item_actions.moved, [('l.playlist001', 0, 2, True)])
        self.assertEqual(self.ids(), ['1', '2', '0', '3'])
        for index in range(4):
            self.assertFalse(self.row(page, index).has_css_class('drop-after'))

    async def test_other_drags_are_not_taken(self):
        from applemusic.library import Item, ItemRefs
        from applemusic.widgets import dnd

        page = await self.show()
        song = self.item.groups[0].entries.get_item(0)
        self.addCleanup(dnd._set_current, None)
        for refs in (ItemRefs.for_objects([song], origin=('playlist', 'p.other')),
                     ItemRefs.for_objects([song], origin=('album', 'l.album001')),
                     ItemRefs.for_objects([song, self.item.groups[0].entries.get_item(1)],
                                          origin=('playlist', 'l.playlist001')),
                     ItemRefs.for_objects([Item({'id': 'p.x', 'kind': 'playlist'})]), None):
            dnd._set_current(refs)
            self.assertFalse(page._on_drop_accept(None, None), refs)
            self.assertEqual(page._on_drop_motion(None, 10, 10), 0)
            self.assertFalse(page._on_drop(None, None, 10, 10))
        self.assertEqual(self.window.item_actions.moved, [])


def _controllers(widget):
    model = widget.observe_controllers()
    return [model.get_item(position) for position in range(model.get_n_items())]


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
        from applemusic.pages.detail import held_songs, suggestion_items, wants_suggestions

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
        from applemusic.pages.detail import held_songs
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


class ArtistPageTest(PageTestCase):
    """The artist page over the catalog's answer (Engine.artist_page), and without it."""

    async def artist_page(self, data, answer=None):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage

        if answer is not None:
            self.app.engine.answers['artist_page'] = answer
        page = await self.push(ArtistPage(self.library, Item(data)))
        await self.settle()
        await self.turn()
        return page

    async def test_the_catalog_answers_the_page(self):
        page = await self.artist_page(dict(artist([album(1)]), catalogId='42'),
                                      artist_answer())
        self.assertEqual(self.app.engine.calls, ['artist_page'])
        self.assertEqual(page.release_title.get_label(), 'Latest Release')
        self.assertEqual(page.release_name.get_label(), 'Invented album 99')
        self.assertTrue(page.release_date.get_label().endswith('2026'))
        self.assertTrue(page.top_songs.get_visible())
        self.assertEqual(page.top_songs.shelf.items.get_n_items(), 4)
        # The library's albums of theirs first, then Apple's shelves in its order, About
        # before Similar Artists.
        self.assertEqual([shelf.key for shelf in page._column.shelves],
                         ['library', 'featured-albums', 'full-albums'])
        self.assertEqual([shelf.key for shelf in page._after.shelves], ['similar-artists'])
        self.assertFalse(page._column.widgets[0].props.hero)
        self.assertTrue(page._column.widgets[1].props.hero)  # Essential Albums: large cards
        self.assertFalse(page.status_page.get_visible())
        self.assertEqual(page.about_title.get_label(), 'About Invented Artist')
        self.assertEqual(page.summary_label.get_label(), 'An invented biography.')
        self.assertEqual(page.origin_label.get_label(), 'Invented Town, Nowhere')
        self.assertEqual(page.born_heading.get_label(), 'Born')
        self.assertTrue(page.play_button.get_visible())  # the catalog artist's top songs

    async def test_the_portrait_without_a_banner(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        self.assertTrue(page.avatar.get_visible())
        self.assertFalse(page.banner.get_visible())
        self.assertFalse(page.hero.has_css_class('on-banner'))
        self.assertEqual(page.content_box.get_margin_top(), 24)

    async def test_a_banner_heads_the_page(self):
        from gi.repository import Gtk

        banner = {'url': None, 'art': '/invented/banner.jpg', 'crop': 'vf', 'width': 1920,
                  'height': 640, 'color': '#102030'}
        page = await self.artist_page(dict(artist([]), catalogId='42'),
                                      artist_answer(banner=banner))
        self.assertTrue(page.banner.get_visible())
        self.assertEqual(page.banner.banner, banner)
        self.assertFalse(page.avatar.get_visible())
        self.assertTrue(page.hero.has_css_class('on-banner'))
        self.assertTrue(page.more_button.has_css_class('osd'))
        self.assertEqual(page.hero_row.get_valign(), Gtk.Align.END)
        self.assertEqual(page.content_box.get_margin_top(), 0)  # edge to edge
        # The name and buttons over its foot, inside it, the banner at least as tall as the
        # banner's height for its width.
        self.assertTrue(await self.until(lambda: page.banner.get_height() > 0))
        found, bounds = page.hero_row.compute_bounds(page.hero)
        self.assertTrue(found)
        self.assertLessEqual(bounds.get_y() + bounds.get_height(),
                             page.hero.get_height() - 24 + 0.5)
        self.assertGreaterEqual(page.banner.get_height(), 240)

    def star(self, page):
        """(shown, pressed, icon, tooltip) of the page's star."""
        button = page.favourite_button
        return (button.get_visible(), button.get_active(), button.get_icon_name(),
                button.get_tooltip_text())

    async def test_the_star_says_what_the_answer_says(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        self.assertEqual(self.star(page), (True, False, 'non-starred-symbolic', 'Favourite'))
        self.assertEqual(self.app.engine.calls, ['artist_page'])  # no request more
        page = await self.artist_page(dict(artist([]), catalogId='42'),
                                      artist_answer(favourite=True))
        self.assertEqual(self.star(page),
                         (True, True, 'starred-symbolic', 'Remove from Favourites'))
        self.assertFalse(page.favourite_button.has_css_class('osd'))  # the plain header

    async def test_an_answer_that_does_not_say_is_read(self):
        self.app.engine.answers['is_favourite_artist'] = True
        page = await self.artist_page(dict(artist([]), catalogId='42'),
                                      artist_answer(favourite=None))
        self.assertTrue(await self.until(lambda: page.favourite_button.get_visible()))
        self.assertEqual(self.app.engine.calls, ['artist_page', 'is_favourite_artist'])
        self.assertTrue(page.favourite_button.get_active())

    async def test_no_star_without_an_answer(self):
        # The engine down: the page shows the library's albums, and no star.
        page = await self.artist_page(dict(artist([album(1)]), catalogId='42'))
        self.assertFalse(page.favourite_button.get_visible())

    async def test_a_press_shows_at_once_and_a_failure_puts_it_back(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        page.favourite_button.set_active(True)
        self.assertEqual(self.star(page),
                         (True, True, 'starred-symbolic', 'Remove from Favourites'))
        [(obj, favourite, task)] = self.window.item_actions.favourites
        self.assertEqual((obj.kind, obj.id, favourite), ('artist', '42', True))
        task.set_result(False)  # the write failed (the item actions reported it)
        self.assertTrue(await self.until(lambda: not page.favourite_button.get_active()))
        self.assertEqual(self.star(page), (True, False, 'non-starred-symbolic', 'Favourite'))
        # Done: it stays.
        page.favourite_button.set_active(True)
        self.window.item_actions.favourites[-1][2].set_result(True)
        await self.settle()
        self.assertTrue(page.favourite_button.get_active())
        self.assertEqual(len(self.window.item_actions.favourites), 2)

    async def test_the_star_follows_the_engine(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        self.app.engine.emit('rated', 'artist', '42', 1)  # a menu's Favourite
        self.assertTrue(page.favourite_button.get_active())
        self.app.engine.emit('rated', 'artist', '43', 0)  # another artist's
        self.assertTrue(page.favourite_button.get_active())
        self.assertEqual(self.window.item_actions.favourites, [])  # nothing written for it
        # Hidden meanwhile: shown again, it says what the item actions last heard.
        self.window.navigation_view.pop()
        self.assertTrue(await self.until(lambda: not page.get_mapped()))
        self.window.item_actions.ratings[('artist', '42')] = 0
        await self.push(page)
        self.assertFalse(page.favourite_button.get_active())

    async def test_the_star_over_a_banner(self):
        banner = {'url': None, 'art': '/invented/banner.jpg', 'crop': 'vf', 'width': 1920,
                  'height': 640, 'color': '#102030'}
        page = await self.artist_page(dict(artist([]), catalogId='42'),
                                      artist_answer(banner=banner, favourite=True))
        self.assertTrue(page.favourite_button.has_css_class('osd'))
        self.assertTrue(page.favourite_button.get_active())

    async def test_a_group_was_formed(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'),
                                      artist_answer(group=True))
        self.assertEqual(page.born_heading.get_label(), 'Formed')

    async def test_a_library_artist_is_found_through_its_songs(self):
        data = artist([album(1), album(2)])
        for group in data['groups']:
            for number, entry in enumerate(group['entries']):
                entry['catalogId'] = f'{group["play"]["id"]}.{number}'
        asked = []

        def catalog_artist(name, song_ids):
            asked.append((name, song_ids))
            return '42'

        self.app.engine.answers['catalog_artist'] = catalog_artist
        await self.artist_page(data, artist_answer())
        self.assertEqual(self.app.engine.calls, ['catalog_artist', 'artist_page'])
        # One song an album, as the engine reads each with its artists.
        self.assertEqual(asked, [('Invented Artist', ['l.album001.0', 'l.album002.0'])])

    async def test_the_songs_asked_about_are_the_library_albums(self):
        # As the library loads them: the artist's groups of albums it has are empty, the
        # tracks being the albums' own.
        from applemusic.library import Item

        albums = [Item(album(1)), Item(album(2))]
        for item in albums:
            for group in item.groups:
                for number in range(group.entries.get_n_items()):
                    group.entries.get_item(number).raw['catalogId'] = f'{item.id}.{number}'
            self.library._index[('album', item.id)] = item
        # The second album's first song is someone else's (a compilation's): its second is
        # the one to ask about.
        albums[1].groups[0].entries.get_item(0).raw['artist'] = 'Someone Else'
        albums[1].groups[0].entries.get_item(1).raw['artist'] = 'Invented Artist feat. X'
        data = artist([album(1), album(2)])
        for group in data['groups']:
            group['entries'] = []
        asked = []

        def catalog_artist(name, song_ids):
            asked.append(song_ids)
            return '42'

        self.app.engine.answers['catalog_artist'] = catalog_artist
        page = await self.artist_page(data, artist_answer())
        self.assertEqual(asked, [['l.album001.0', 'l.album002.1']])
        self.assertEqual(self.app.engine.calls, ['catalog_artist', 'artist_page'])
        # Apple Music's page, with the library's two albums first.
        self.assertEqual([shelf.key for shelf in page._column.shelves][:2],
                         ['library', 'featured-albums'])
        self.assertIs(page._library_shelf.items.get_item(0), albums[1])  # newest first

    async def test_an_artist_with_nothing_to_find_shows_no_albums(self):
        page = await self.artist_page(artist([]))
        self.assertEqual(self.app.engine.calls, [])  # no catalog id, no songs to ask about
        self.assertTrue(page.status_page.get_visible())
        self.assertEqual(page.status_page.get_title(), 'No Albums')

    async def test_without_the_catalog_the_library_albums_show(self):
        page = await self.artist_page(dict(artist([album(1), album(2)]), catalogId='42'))
        self.assertEqual(self.app.engine.calls, ['artist_page'])  # the engine is down
        self.assertEqual([shelf.key for shelf in page._column.shelves], ['library'])
        self.assertEqual(page._column.widgets[0].shelf.items.get_n_items(), 2)
        self.assertTrue(page.status_page.get_visible())  # Start Engine, under the albums
        self.assertTrue(page.status_button.get_visible())

    async def test_a_top_song_plays_the_songs_from_it(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        page.top_songs.grid_view.emit('activate', 2)
        window = page.get_root()
        self.assertEqual(window.played[-1],
                         ({'kind': 'songs', 'id': '900,901,902,903'}, 2, None))
        self.assertEqual(window.started_with[-1], '902')

    async def test_see_all_fetches_the_rest_of_a_shelf(self):
        page = await self.artist_page(dict(artist([]), catalogId='42'), artist_answer())
        albums = page._column.shelves[1]
        first = albums.items.get_item(0)
        self.assertTrue(albums.more)
        rest = artist_answer()['shelves'][1]['items'] + [
            dict(artist_answer()['shelves'][1]['items'][0], id=f'album{n}',
                 title=f'Invented album {n}') for n in range(4, 8)]
        self.app.engine.answers['artist_view'] = rest
        await albums.complete()
        self.assertEqual(albums.items.get_n_items(), 7)
        self.assertIs(albums.items.get_item(0), first)  # what was shown stays
        self.assertFalse(albums.more)

    async def test_an_album_the_library_lacks_is_fetched_when_opened(self):
        page = await self.artist_page(artist([album(1), album(2)]))
        albums = page._library_shelf.items
        self.assertEqual(albums.get_n_items(), 2)
        stand_in = albums.get_item(0)
        self.assertEqual(stand_in.kind, 'album')
        self.assertEqual(stand_in.groups, [])  # its page asks the engine for the whole album
        self.assertEqual(stand_in.subtitle, 'Invented Artist')

    async def test_the_page_follows_its_artist(self):
        from applemusic.library import Item
        from applemusic.pages.artist import ArtistPage

        item = Item(artist([album(1)]))
        page = await self.push(ArtistPage(self.library, item))
        item.merge(artist([album(1), album(2), album(3)]), replace=True)
        self.assertEqual(page._library_shelf.items.get_n_items(), 3)


class ArtistWordsTest(PageTestCase):
    def test_a_release_date_in_the_readers_words(self):
        from applemusic.pages.artist import release_date

        self.assertRegex(release_date('2026-09-24'), r'^24 \w+ 2026$')
        self.assertEqual(release_date(''), '')
        self.assertEqual(release_date('soon'), '')
        self.assertEqual(release_date('2026-13-40'), '')

    def test_a_catalog_artist_and_a_library_one(self):
        from applemusic.library import Item
        from applemusic.related import artist_catalog_id

        self.assertEqual(artist_catalog_id(Item({'id': '42', 'kind': 'artist'})), '42')
        self.assertEqual(artist_catalog_id(Item({'id': 'l.art001', 'kind': 'artist',
                                                 'catalogId': '43'})), '43')
        self.assertIsNone(artist_catalog_id(Item({'id': 'l.art_abc', 'kind': 'artist'})))


if __name__ == '__main__':
    unittest.main()
