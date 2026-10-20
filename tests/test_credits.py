# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""View Credits: src/credits.py's words for Engine.credits' answer (no display), and the
dialog that shows it (dialogs/credits.py) over a presented stand-in window: the spinner while
the engine is asked, a boxed list for each kind of credit, No Credits, and what the engine's
failure means, with its button. Every name and role here is invented."""

import asyncio
import unittest

from tests.page_harness import PageTestCase, find_all

from applemusic.backend.errors import EngineError
from applemusic.credits import heading, roles_text, sections

# Engine.credits' answer for an invented song (normalize.song_credits' shape).
ANSWER = {'categories': [
    {'kind': 'performer', 'title': 'Performers', 'people': [
        {'name': 'The Invented Band', 'roles': ['Performer']},
        {'name': 'Ada Brightwater', 'roles': ['Vocals', 'Guitar']}]},
    {'kind': 'composer-and-lyrics', 'title': '', 'people': [
        {'name': 'Bram & Holloway <b>', 'roles': []}]},
    {'kind': 'production-and-engineering', 'title': 'Production & Engineering', 'people': [
        {'name': 'Cleo Ashdown', 'roles': ['Producer']}]},
], 'cached': '2026-10-20T12:00:00Z'}


class WordsTest(unittest.TestCase):
    def test_apples_title_else_the_apps_by_kind(self):
        self.assertEqual(heading('performer', 'Mitwirkende'), 'Mitwirkende')
        self.assertEqual(heading('performer', ' '), 'Performers')
        self.assertEqual(heading('composer-and-lyrics', None), 'Composition and Lyrics')
        self.assertEqual(heading('production-and-engineering', ''),
                         'Production and Engineering')
        self.assertEqual(heading('choir', ''), 'Other Credits')  # a kind Apple adds later

    def test_roles_on_one_line(self):
        self.assertEqual(roles_text(['Vocals', 'Guitar']), 'Vocals, Guitar')
        self.assertEqual(roles_text(['Producer', '']), 'Producer')
        self.assertEqual(roles_text([]), '')
        self.assertEqual(roles_text(None), '')
        self.assertEqual(roles_text('Vocals'), '')  # not a list: none

    def test_sections_in_apples_order(self):
        self.assertEqual(sections(ANSWER), [
            ('Performers', [('The Invented Band', 'Performer'),
                            ('Ada Brightwater', 'Vocals, Guitar')]),
            ('Composition and Lyrics', [('Bram & Holloway <b>', '')]),
            ('Production & Engineering', [('Cleo Ashdown', 'Producer')])])

    def test_nobody_is_no_sections(self):
        for answer in (None, {}, {'categories': []}, {'categories': 'x'},
                       {'categories': [{'kind': 'performer', 'people': []}]},
                       {'categories': [{'kind': 'performer', 'people': [{'name': ''}]}]}):
            self.assertEqual(sections(answer), [], answer)


class CreditsDialogTest(PageTestCase):
    async def presented(self, title='Invented Song'):
        from applemusic.dialogs.credits import CreditsDialog

        dialog = CreditsDialog(self.app, '1000000001', title)
        dialog.present(self.window)
        self.assertTrue(await self.until(dialog.get_mapped))
        self.addCleanup(dialog.force_close)
        return dialog

    def rows(self, dialog):
        from gi.repository import Adw

        return [[(row.get_title(), row.get_subtitle())
                 for row in find_all(group, Adw.ActionRow)]
                for group in find_all(dialog.credits_page, Adw.PreferencesGroup)]

    def groups(self, dialog):
        from gi.repository import Adw

        return [group.get_title()
                for group in find_all(dialog.credits_page, Adw.PreferencesGroup)]

    async def test_a_spinner_then_a_boxed_list_for_each_kind(self):
        gate = asyncio.get_running_loop().create_future()

        async def held(_song_id):
            await gate
            return ANSWER

        self.app.engine.answers['credits'] = held
        dialog = await self.presented()
        await self.until(lambda: dialog.status == 'loading')
        self.assertEqual(dialog.stack.get_visible_child_name(), 'loading')
        self.assertEqual(dialog.window_title.get_subtitle(), 'Invented Song')
        gate.set_result(None)
        self.assertTrue(await self.until(lambda: dialog.status == 'credits'))
        self.assertEqual(self.app.engine.calls, ['credits'])
        self.assertEqual(dialog.stack.get_visible_child_name(), 'credits')
        self.assertEqual(self.groups(dialog), ['Performers', 'Composition and Lyrics',
                                               'Production &amp; Engineering'])
        self.assertEqual(self.rows(dialog), [
            [('The Invented Band', 'Performer'), ('Ada Brightwater', 'Vocals, Guitar')],
            [('Bram & Holloway <b>', '')],  # a name as it is, never markup
            [('Cleo Ashdown', 'Producer')]])

    async def test_no_credits(self):
        self.app.engine.answers['credits'] = {'categories': []}
        dialog = await self.presented()
        self.assertTrue(await self.until(lambda: dialog.status == 'empty'))
        self.assertEqual(dialog.stack.get_visible_child_name(), 'status')
        self.assertEqual(dialog.status_page.get_title(), 'No Credits')
        self.assertFalse(dialog.status_button.get_visible())
        self.assertEqual(self.groups(dialog), [])

    async def test_signed_out_offers_sign_in(self):
        self.app.settings.set_boolean('signed-in', False)
        dialog = await self.presented()
        self.assertTrue(await self.until(lambda: dialog.status == 'not-signed-in'))
        self.assertEqual(dialog.status_page.get_title(), 'Sign In to Apple Music')
        self.assertTrue(dialog.status_button.get_visible())
        dialog.status_button.emit('clicked')
        self.assertEqual(self.app.actions, ['sign-in'])

    async def test_engine_down_starts_it_and_loads_once_it_is_up(self):
        answers = [EngineError('engine-down'), ANSWER]
        self.app.engine.answers['credits'] = lambda _song_id: answers.pop(0)
        dialog = await self.presented()
        self.assertTrue(await self.until(lambda: dialog.status == 'engine-down'))
        self.assertEqual(dialog.status_page.get_title(), 'Engine Not Running')
        self.assertEqual(dialog.status_button.get_label(), 'Start Engine')
        dialog.status_button.emit('clicked')
        self.assertTrue(await self.until(lambda: dialog.status == 'credits'))
        self.assertEqual(self.app.engine.calls, ['credits', 'start', 'credits'])

    async def test_a_failure_offers_try_again(self):
        answers = [EngineError('api', 'invented', status=500), {'categories': []}]
        self.app.engine.answers['credits'] = lambda _song_id: answers.pop(0)
        dialog = await self.presented()
        self.assertTrue(await self.until(lambda: dialog.status == 'failed'))
        self.assertEqual(dialog.status_page.get_title(), 'Could Not Load the Credits')
        self.assertEqual(dialog.status_button.get_label(), 'Try Again')
        dialog.status_button.emit('clicked')
        self.assertTrue(await self.until(lambda: dialog.status == 'empty'))

    async def test_the_demo_says_so_without_a_button(self):
        self.app.demo = True
        dialog = await self.presented()
        self.assertTrue(await self.until(lambda: dialog.status == 'demo'))
        self.assertEqual(dialog.status_page.get_title(), 'Not Available in the Demo')
        self.assertFalse(dialog.status_button.get_visible())

    async def test_closing_cancels_the_request(self):
        gate = asyncio.get_running_loop().create_future()

        async def held(_song_id):
            await gate
            return ANSWER

        self.app.engine.answers['credits'] = held
        dialog = await self.presented()
        await self.until(lambda: self.app.tasks)
        task = self.app.tasks[-1]
        dialog.force_close()
        self.assertTrue(await self.until(task.done))
        self.assertTrue(task.cancelled())


if __name__ == '__main__':
    unittest.main()
