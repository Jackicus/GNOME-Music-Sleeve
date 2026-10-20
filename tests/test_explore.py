# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""More to Explore (src/explore.py, widgets/explore.py) and the New page's banners
(widgets/banner_tile.py), over invented answers: the links as Items and sections, New with
its banners and links, and the pages the links open (pages/editorial.py): a room's grid (a
GridPage that fetches) and a grouping's shelves."""

import unittest

from tests.page_harness import PageTestCase, album, find, find_all

from applemusic import explore
from applemusic.backend.errors import EngineError


def link(title, kind, link_id, **more):
    return dict(title=title, kind=kind, id=link_id,
                url=link_id if kind == 'link' else None, **more)


ROWS = [
    {'key': 'new-explore', 'title': 'Invented Explore', 'links': [
        link('Invented Room', 'room', '900000701'),
        link('Invented Grouping', 'grouping', '900000704'),
        link('Invented Multiroom', 'multiroom', '900000705'),
        link('Invented Web Page', 'link', 'https://example.com/invented'),
        link('Something Else', 'unknown', 'x'),  # a kind the app does not open
        link('', 'room', '900000702'),  # no title
    ]},
    {'key': 'new-genres', 'title': '', 'links': [
        link('Invented Folk', 'grouping', '900000706')]},
    {'key': 'new-empty', 'title': 'Nothing Here', 'links': [link('', 'room', '1')]},
    'junk',
]


class SectionsTest(unittest.TestCase):
    def test_rows_of_links_are_sections_of_items(self):
        found = explore.sections(ROWS)
        self.assertEqual([(section.key, section.title) for section in found],
                         [('new-explore', 'Invented Explore'), ('new-genres', '')])
        items = found[0].items
        self.assertEqual([(item.kind, item.id, item.title) for item in items], [
            ('room', '900000701', 'Invented Room'),
            ('grouping', '900000704', 'Invented Grouping'),
            ('multiroom', '900000705', 'Invented Multiroom'),
            ('link', 'https://example.com/invented', 'Invented Web Page'),
        ])
        self.assertEqual(items[3].url, 'https://example.com/invented')
        self.assertIsNone(items[0].url)
        self.assertEqual(explore.sections(None), [])

    def test_new_has_top_charts_first_in_its_first_titled_row(self):
        found = explore.sections(ROWS, charts=True)
        first = found[0].items[0]
        self.assertEqual((first.kind, first.id, first.title), ('charts', 'charts', 'Top Charts'))
        self.assertEqual(len(found[0].items), 5)
        self.assertEqual(len(found[1].items), 1)  # the untitled row as it was

    def test_without_a_titled_row_top_charts_has_a_more_to_explore_of_its_own(self):
        for rows in (None, [], ROWS[1:2]):
            found = explore.sections(rows, charts=True)
            self.assertEqual((found[0].key, found[0].title), ('explore', 'More to Explore'))
            self.assertEqual([item.kind for item in found[0].items], ['charts'])
            self.assertEqual(len(found), 1 + len(rows or []))

    def test_apples_own_link_to_the_charts_is_enough(self):
        rows = [{'key': 'k', 'title': 'Invented', 'links': [
            link('Invented Charts', 'charts', 'charts', genre='21')]}]
        found = explore.sections(rows, charts=True)
        self.assertEqual([(item.title, item.raw.get('genre')) for item in found[0].items],
                         [('Invented Charts', '21')])

    def test_same_links(self):
        self.assertTrue(explore.same_links(explore.sections(ROWS), explore.sections(ROWS)))
        self.assertFalse(explore.same_links(explore.sections(ROWS),
                                            explore.sections(ROWS, charts=True)))
        self.assertTrue(explore.same_links(None, []))


class BannerSizeTest(unittest.TestCase):
    def test_a_card_fits_its_row(self):
        from applemusic.widgets import banner_tile

        self.assertEqual(banner_tile.card_width(0), banner_tile.BANNER_WIDTH)  # not laid out
        self.assertEqual(banner_tile.card_width(1200), banner_tile.BANNER_WIDTH)
        self.assertEqual(banner_tile.card_width(360), 360 - 2 * banner_tile.ROW_INSET)
        self.assertEqual(banner_tile.card_width(100), banner_tile.MIN_WIDTH)
        self.assertEqual(banner_tile.image_height(384), 216)  # 16:9

    def test_the_edge_decoded(self):
        from applemusic.widgets.banner_tile import drawn_edge

        self.assertEqual(drawn_edge(384, None), 216)  # a cover, whole
        self.assertEqual(drawn_edge(384, 16 / 9), 216)
        self.assertEqual(drawn_edge(384, 4), 216)  # wider: its height is the card's
        self.assertEqual(drawn_edge(384, 1.5), 256)  # squarer: its width is the card's


def banner_item(number, banner=True):
    item = dict(album(number, tracks=0), id=f'n.{number}', badge=f'INVENTED BADGE {number}',
                tagline=f'Invented tagline {number}')
    if banner:
        item['banner'] = {'url': None, 'art': None, 'crop': 'sr', 'width': 1600,
                          'height': 900, 'color': '#203040'}
    return item


def new_answer():
    return {'shelves': [
        {'key': 'new-featured', 'title': '', 'featured': True, 'form': 'banners',
         'items': [banner_item(1), banner_item(2, banner=False)]},
        {'key': 'new-albums', 'title': 'Invented Albums',
         'items': [dict(album(n, tracks=0), id=f'a.{n}') for n in range(3)]},
    ], 'links': ROWS[:2]}


class NewPageTest(PageTestCase):
    async def new_page(self):
        from applemusic.pages import new
        from applemusic.sections import Destination

        self.app.engine.answers['browse'] = new_answer()
        page = await self.show_root(new.create(Destination('new', 'New',
                                                            'view-grid-symbolic')))
        await self.settle()
        self.assertTrue(await self.until_frames(page, lambda: len(page._column.widgets) == 2))
        return page

    async def test_the_featured_shelf_is_banners_with_apples_words(self):
        from applemusic.widgets.banner_tile import BannerTile
        from applemusic.widgets.shelf import Shelf

        page = await self.new_page()
        featured = page._column.widgets[0]
        self.assertIsInstance(featured, Shelf)
        self.assertTrue(featured.banners)
        self.assertTrue(await self.until(lambda: len(find_all(featured, BannerTile)) == 2))
        first, second = find_all(featured, BannerTile)
        self.assertEqual((first.badge_label.get_text(), first.title_label.get_text(),
                          first.subtitle_label.get_text()),
                         ('INVENTED BADGE 1', 'Invented Album 001', 'Invented tagline 1'))
        self.assertIsNotNone(first.art.banner)
        self.assertIsNone(second.art.banner)  # its cover stands in
        self.assertEqual(first.context_item.id, 'n.1')
        # The next shelf is tiles, as before.
        self.assertFalse(page._column.widgets[1].banners)

    async def test_the_links_follow_the_shelves_and_open_their_pages(self):
        from applemusic.widgets.explore import ExploreBox, LinkChild

        page = await self.new_page()
        box = find(page, ExploreBox)
        self.assertTrue(box.get_visible())
        children = find_all(box, LinkChild)
        self.assertEqual([child.item.title for child in children],
                         ['Top Charts', 'Invented Room', 'Invented Grouping',
                          'Invented Multiroom', 'Invented Web Page', 'Invented Folk'])
        flow_box = children[1].get_parent()
        flow_box.emit('child-activated', children[1])
        self.assertEqual([(item.kind, item.id) for item in self.window.opened],
                         [('room', '900000701')])
        # The same links again keep their cards.
        page._present()
        self.assertIs(find_all(box, LinkChild)[1], children[1])

    async def test_banner_cards_fit_a_narrow_window(self):
        from applemusic.pages import new
        from applemusic.sections import Destination
        from applemusic.widgets.banner_tile import BANNER_WIDTH, BannerTile

        self.app.engine.answers['browse'] = new_answer()
        page = await self.show_at(new.create(Destination('new', 'New', 'view-grid-symbolic')),
                                  360)
        await self.settle()
        self.assertTrue(await self.until_frames(page, lambda: find(page, BannerTile)))
        card = find(page, BannerTile)
        self.assertTrue(await self.until_frames(
            page, lambda: 0 < card.get_width() < BANNER_WIDTH), card.get_width())
        shelf = page._column.widgets[0]
        self.assertLessEqual(card.get_width(), shelf.get_width() - 48)


class LinkPagesTest(PageTestCase):
    async def room_page(self, answer):
        from applemusic.explore import link_item
        from applemusic.pages import editorial

        self.app.engine.answers['room'] = answer
        item = link_item(link('Invented Room', 'room', '900000701'))
        page = await self.push(editorial.create(self.library, item))
        await self.settle()
        return page

    async def test_a_room_is_a_grid_of_its_contents(self):
        answer = {'id': '900000701', 'title': 'Invented Room',
                  'items': [dict(album(n, tracks=0), id=f'r.{n}') for n in range(5)]}
        page = await self.room_page(answer)
        self.assertEqual(page.get_title(), 'Invented Room')
        self.assertEqual(page.stack.get_visible_child_name(), 'items')
        self.assertEqual(page._fetched.get_n_items(), 5)
        self.assertEqual(self.app.engine.calls, ['room'])
        self.assertEqual(page.item.kind, 'room')
        # Refresh asks again, past the cache.
        asked = []
        self.app.engine.answers['room'] = lambda room_id, refresh: asked.append(
            (room_id, refresh)) or answer
        self.assertTrue(callable(page.refresh))
        page.refresh()
        await self.settle()
        self.assertEqual(asked, [('900000701', True)])

    async def test_a_room_of_music_videos_has_their_frames(self):
        from applemusic.widgets.tile import VIDEO

        videos = [dict(album(n, tracks=0), id=f'v.{n}', kind='video') for n in range(2)]
        page = await self.room_page({'items': videos})
        self.assertEqual(page._shape, VIDEO)

    async def test_the_engine_down_says_so_and_offers_to_start_it(self):
        page = await self.room_page(EngineError('engine-down'))
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'Engine Not Running')
        self.assertTrue(page._status_button.get_visible())
        self.assertEqual(page._status_button.get_label(), 'Start Engine')

    async def test_an_empty_room(self):
        page = await self.room_page({'items': []})
        self.assertEqual(page.stack.get_visible_child_name(), 'empty')
        self.assertEqual(page.empty_page.get_title(), 'Nothing Here')
        self.assertFalse(page._status_button.get_visible())

    async def test_a_library_grid_has_no_refresh(self):
        from applemusic.pages.grid import GridPage

        page = GridPage(self.library, 'Invented', self.library.albums)
        self.assertIsNone(page.refresh)

    async def test_a_grouping_is_its_shelves_and_links(self):
        from applemusic.explore import link_item
        from applemusic.pages import editorial
        from applemusic.widgets.explore import LinkChild

        self.app.engine.answers['grouping'] = {
            'title': 'Invented Grouping', 'shelves': new_answer()['shelves'][1:],
            'links': ROWS[1:2]}
        item = link_item(link('Invented Grouping', 'grouping', '900000704'))
        page = await self.push(editorial.create(self.library, item))
        await self.settle()
        self.assertTrue(await self.until_frames(page, lambda: len(page._column.widgets) == 1))
        self.assertEqual([child.item.title for child in find_all(page, LinkChild)],
                         ['Invented Folk'])  # no Top Charts: New's alone
        self.assertEqual(self.app.engine.calls, ['grouping'])

    async def test_a_page_of_links_alone_is_shown(self):
        from applemusic.explore import link_item
        from applemusic.pages import editorial

        self.app.engine.answers['multiroom'] = {'shelves': [], 'links': ROWS[:1]}
        item = link_item(link('Invented Multiroom', 'multiroom', '900000705'))
        page = await self.push(editorial.create(self.library, item))
        await self.settle()
        self.assertEqual(page.stack.get_visible_child_name(), 'items')


if __name__ == '__main__':
    unittest.main()
