# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the item actions say (applemusic.action_messages)."""

import locale
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic

from applemusic import action_messages
from applemusic.action_messages import queue_message


class MessagesTest(unittest.TestCase):
    """What the actions say (action_messages): the toasts that count, in the
    locale's numbers."""

    def test_queue_message(self):
        self.assertEqual(queue_message('Shoreline', True), '“Shoreline” will play later')
        self.assertEqual(queue_message('Shoreline', False), '“Shoreline” will play next')
        self.assertEqual(queue_message('', True), 'Playing later')
        self.assertEqual(queue_message('Shoreline', True, 2), '2 items will play later')
        self.assertEqual(queue_message('Shoreline', False, 4), '4 items will play next')

    def test_counts_are_written_as_the_locale_writes_numbers(self):
        numeric = locale.setlocale(locale.LC_NUMERIC)
        self.addCleanup(locale.setlocale, locale.LC_NUMERIC, numeric)
        try:
            locale.setlocale(locale.LC_NUMERIC, 'en_GB.UTF-8')
        except locale.Error:
            self.skipTest('en_GB.UTF-8 is not installed here')
        self.assertEqual(queue_message('', True, 1200), '1,200 items will play later')
        self.assertEqual(action_messages.added_message(4000, 'Road Trip'),
                         'Added 4,000 songs to “Road Trip”')
        self.assertEqual(action_messages.removed_message(2500, ''),
                         'Removed 2,500 songs from the playlist')


if __name__ == '__main__':
    unittest.main()
