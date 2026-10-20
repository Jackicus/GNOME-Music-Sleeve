# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Add Songs… (dialogs/add_songs.py) over a presented stand-in window: the library's songs
narrowed by what is typed, Apple Music's for a search (the stand-in engine's answer), songs
picked from both and handed over in the order picked, and what the engine's failure means.
Every title here is invented."""

import unittest

from tests.page_harness import PageTestCase, find_all

from applemusic.backend.errors import EngineError


def song(number, title):
    """An invented catalogue song as a search's shelf has one."""
    song_id = str(3000 + number)
    return {'id': song_id, 'kind': 'song', 'title': title, 'subtitle': 'Invented Artist',
            'art': None, 'thumb': None, 'catalogId': song_id,
            'play': {'kind': 'song', 'id': song_id}, 'groups': []}


def songs_answer(*titles):
    return {'shelves': [{'key': 'songs', 'title': 'Songs', 'next': None,
                         'items': [song(n, title) for n, title in enumerate(titles)]}]}


class WordsTest(unittest.TestCase):
    def test_the_header_bars_subtitle(self):
        from applemusic.dialogs.add_songs import picked_text, track_subtitle
        from applemusic.library import Track

        self.assertEqual(picked_text(0, 'Road Trip'), 'To “Road Trip”')
        self.assertEqual(picked_text(1, 'Road Trip'), '1 song selected')
        self.assertEqual(picked_text(3), '3 songs selected')
        self.assertEqual(picked_text(0), '')
        self.assertEqual(track_subtitle(Track({'artist': 'Aura', 'album': 'Tidewater'})),
                         'Aura · Tidewater')
        self.assertEqual(track_subtitle(Track({'artist': 'Aura'})), 'Aura')


class AddSongsDialogTest(PageTestCase):
    def library_songs(self, *titles):
        from applemusic.library import Track

        self.library.songs_ready = True
        self.library.songs.splice(0, 0, [
            Track({'id': f'i.s{n}', 'title': title, 'artist': 'Invented Artist',
                   'album': 'Invented Album', 'type': 'library-songs', 'index': n})
            for n, title in enumerate(titles)])

    async def presented(self):
        from applemusic.dialogs.add_songs import AddSongsDialog

        self.picked = []
        dialog = AddSongsDialog(self.app, self.library, 'Road Trip', self.picked.append)
        dialog.present(self.window)
        self.assertTrue(await self.until(dialog.get_mapped))
        # The compositor's answer to the first focused entry's text input (the dialog's
        # search), before the entry goes (docs/notes.md).
        await self.until(lambda: False, timeout=0.1)
        self.addCleanup(dialog.force_close)
        return dialog

    async def typed(self, dialog, text):
        dialog.search_entry.set_text(text)
        self.assertTrue(await self.until(lambda: dialog.term == text, timeout=2))
        await self.until(lambda: not dialog._library_model.get_pending())

    def library_titles(self, dialog):
        model = dialog._library_model
        return [model.get_item(n).title for n in range(model.get_n_items())]

    async def test_the_library_songs_narrowed_and_picked(self):
        self.library_songs('Harbour Lights', 'Dawn', 'Night Harbour')
        dialog = await self.presented()
        self.assertEqual(dialog.stack.get_visible_child_name(), 'library')
        self.assertEqual(dialog.window_title.get_subtitle(), 'To “Road Trip”')
        self.assertFalse(dialog.add_button.get_sensitive())
        await self.typed(dialog, 'harbour')
        self.assertEqual(self.library_titles(dialog), ['Harbour Lights', 'Night Harbour'])
        # Enter in the search: the focus on the first song shown.
        dialog.search_entry.emit('activate')
        self.assertTrue(await self.until(lambda: dialog.get_root().get_focus() is not None
                                         and dialog.get_root().get_focus().is_ancestor(
                                             dialog.library_view)))
        dialog.library_view.emit('activate', 1)  # Night Harbour
        dialog.library_view.emit('activate', 0)
        self.assertEqual(dialog.window_title.get_subtitle(), '2 songs selected')
        self.assertTrue(dialog.add_button.get_sensitive())
        self.assertTrue(await self.until(lambda: len(dialog._bound) == 2))
        for list_item in dialog._bound:
            self.assertTrue(list_item.get_child().check.get_active())
            self.assertEqual(list_item.get_accessible_description(), 'Selected')
        # Unpicked again; then nothing typed shows them all, the picks kept.
        dialog.library_view.emit('activate', 0)
        await self.typed(dialog, '')
        self.assertEqual(len(self.library_titles(dialog)), 3)
        self.assertEqual([obj.title for obj in dialog.picks.objects()], ['Night Harbour'])
        dialog.add_button.emit('clicked')
        self.assertEqual([[obj.title for obj in objects] for objects in self.picked],
                         [['Night Harbour']])
        self.assertTrue(await self.until(lambda: not dialog.get_mapped()))

    async def test_a_search_of_apple_music_picked_beside_the_library(self):
        self.library_songs('Harbour Lights')
        self.app.engine.answers['search'] = lambda text, kind, offset: songs_answer(
            'Tidewater', 'Tide Pool')
        dialog = await self.presented()
        dialog.library_view.emit('activate', 0)
        dialog.scope_toggle.set_active_name('catalog')
        self.assertEqual(dialog.status, 'search')  # nothing typed: what to do
        await self.typed(dialog, 'tide')
        self.assertTrue(await self.until(
            lambda: dialog.stack.get_visible_child_name() == 'catalog'))
        self.assertEqual(self.app.engine.search_requests[-1]['kind'], 'songs')
        dialog.catalog_list.list_view.emit('activate', 1)  # Tide Pool
        self.assertTrue(await self.until(lambda: any(
            row.check.get_active() for row in self.pick_rows(dialog.catalog_list))))
        # Both lists' picks, in the order picked.
        dialog.add_button.emit('clicked')
        self.assertEqual([[obj.title for obj in objects] for objects in self.picked],
                         [['Harbour Lights', 'Tide Pool']])

    def pick_rows(self, widget):
        from applemusic.dialogs.add_songs import PickRow

        return [row for row in find_all(widget, PickRow) if row.context_item is not None]

    async def test_what_apple_music_cannot_answer(self):
        self.library_songs('Harbour Lights')
        dialog = await self.presented()
        dialog.scope_toggle.set_active_name('catalog')
        await self.typed(dialog, 'tide')  # the stand-in engine is down
        self.assertTrue(await self.until(lambda: dialog.status == 'engine-down'))
        self.assertTrue(dialog.status_button.get_visible())
        self.assertEqual(dialog.status_button.get_label(), 'Start Engine')
        self.app.engine.answers['search'] = songs_answer()
        dialog.status_button.emit('clicked')  # started, then asked again
        self.assertTrue(await self.until(lambda: dialog.status == 'no-results'))
        self.app.engine.answers['search'] = EngineError('api', 'HTTP 500')
        await self.typed(dialog, 'tides')
        self.assertTrue(await self.until(lambda: dialog.status == 'failed'))
        self.assertEqual(dialog.status_button.get_label(), 'Try Again')

    async def test_a_library_without_songs_and_escape(self):
        self.library_songs()
        dialog = await self.presented()
        self.assertEqual(dialog.status, 'empty')
        await self.typed(dialog, 'harbour')
        self.assertEqual(dialog.status, 'no-results')
        # Escape in the entry: what is typed goes first, then the dialog.
        dialog.search_entry.emit('stop-search')
        self.assertEqual(dialog.search_entry.get_text(), '')
        self.assertTrue(dialog.get_mapped())
        dialog.search_entry.emit('stop-search')
        self.assertTrue(await self.until(lambda: not dialog.get_mapped()))
        self.assertEqual(self.picked, [])


if __name__ == '__main__':
    unittest.main()
