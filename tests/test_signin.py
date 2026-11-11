# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The sign-in dialog (src/dialogs/signin.py) around a stand-in for account.sign_in(): the
flow starts as the dialog is presented, once; each step shows; the flow's end, its failure,
Cancel and the dialog's closing each end the other. (The flow itself: test_account.py; that a
closed dialog is freed and stops the engine: test_page_lifetime.py.)
"""

import asyncio
import unittest
from unittest import mock

from tests import ROOT  # noqa: F401  (registers src/ as the applemusic package)
from tests.gtk import pump, requires_gtk, wait_for


class App:
    def __init__(self):
        self.tasks = []

    def spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task


@requires_gtk
class SignInDialogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from gi.repository import Adw, Gtk

        from applemusic.dialogs import signin

        self.gtk_settings = Gtk.Settings.get_default()
        animations = self.gtk_settings.props.gtk_enable_animations
        self.gtk_settings.props.gtk_enable_animations = False
        self.addCleanup(setattr, self.gtk_settings.props, 'gtk_enable_animations', animations)
        # An Adw window, as the app's: over a plain Gtk.Window, an Adw.Dialog's force_close()
        # never emits `closed` (libadwaita 1.10).
        self.window = Adw.Window(default_width=600, default_height=500)
        self.window.present()
        self.addCleanup(self.window.destroy)
        self.app = App()
        self.flows = []  # (set_status, the future the flow waits on), per flow started
        self.cancelled = []

        async def sign_in(app, set_status):
            self.assertIs(app, self.app)
            done = asyncio.get_running_loop().create_future()
            self.flows.append((set_status, done))
            try:
                await done
            except asyncio.CancelledError:
                self.cancelled.append(True)
                raise

        patcher = mock.patch.object(signin.account, 'sign_in', sign_in)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dialog = signin.SignInDialog(self.app)
        self.closed = []
        self.dialog.connect('closed', lambda _dialog: self.closed.append(True))

    async def asyncTearDown(self):
        if not self.closed:
            self.dialog.force_close()
            self.assertTrue(wait_for(lambda: self.closed))
        await self.turn()
        pending = [task for task in self.app.tasks if not task.done()]
        for task in pending:  # never left waiting on a flow, whatever the test did
            task.cancel()
        await asyncio.gather(*self.app.tasks, return_exceptions=True)
        self.assertEqual(pending, [])

    async def present(self):
        """Present the dialog over the window, mapped (a dialog not mapped yet cannot be
        closed), and let the flow start."""
        self.dialog.present(self.window)
        self.assertTrue(wait_for(self.dialog.get_mapped))
        await self.turn()

    async def turn(self):
        """Let what is pending run: GTK's main context (the dialog's closing), and the
        tasks up to their next wait."""
        for _round in range(5):
            pump(10)
            await asyncio.sleep(0)

    async def test_presenting_starts_the_flow_once(self):
        await self.present()
        self.dialog.present(self.window)
        await self.turn()
        self.assertEqual(len(self.flows), 1)
        self.assertEqual(len(self.app.tasks), 1)

    async def test_each_step_shows(self):
        await self.present()
        set_status, _done = self.flows[0]
        set_status('Waiting for the invented step…')
        self.assertEqual(self.dialog.status_page.get_description(),
                         'Waiting for the invented step…')

    async def test_the_flows_end_closes_the_dialog(self):
        await self.present()
        self.flows[0][1].set_result(None)
        await self.turn()
        self.assertEqual(self.closed, [True])
        self.assertEqual(self.cancelled, [])

    async def test_a_failure_closes_it_too(self):
        await self.present()
        self.flows[0][1].set_exception(RuntimeError('invented'))
        await self.turn()
        self.assertEqual(self.closed, [True])

    async def test_cancel_cancels_the_flow_and_closes(self):
        await self.present()
        self.dialog.cancel_button.emit('clicked')
        await self.turn()
        self.assertEqual(self.cancelled, [True])
        self.assertEqual(self.closed, [True])

    async def test_closing_cancels_the_flow_and_steps_after_show_nothing(self):
        await self.present()
        set_status, _done = self.flows[0]
        set_status('First step')
        self.dialog.force_close()  # Escape, the close button
        self.assertTrue(wait_for(lambda: self.closed))
        await self.turn()
        self.assertEqual((self.closed, self.cancelled), ([True], [True]))
        set_status('A step after the close')
        self.assertEqual(self.dialog.status_page.get_description(), 'First step')


if __name__ == '__main__':
    unittest.main()
