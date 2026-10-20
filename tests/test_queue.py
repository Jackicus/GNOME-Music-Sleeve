# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/queue.py: Up Next, the Player's queue from the entry playing on, follows the queue
while it is open, whichever entry plays: entries added at the queue's end and a new queue
reach the list; the entries autoplay added are a section of their own under its header; a
row is the queue's entry at its place; Remove from Up Next (the menu, Delete) and Clear,
and the Autoplay toggle. (The slice's start is tested in test_transport.py's
QueueSliceTest.)"""

import types
import unittest

from tests import ROOT  # noqa: F401  registers src/ as applemusic
from tests.gtk import pump, requires_gtk, wait_for
from tests.test_player import TRACK, make_player


def entries(count, autoplay=()):
    """An invented queue of `count` entries, as the bridge's queue() shapes it; those at the
    indices `autoplay` added by autoplay."""
    made = []
    for number in range(count):
        entry = dict(TRACK, id=f'i.queue{number:04}', catalogId=str(2000000000 + number),
                     title=f'Entry {number}', index=number)
        if number in autoplay:
            entry['autoplay'] = True
        made.append(entry)
    return made


class SectionBoundsTest(unittest.TestCase):
    """section_bounds(): where Up Next's two parts begin."""

    def test_bounds(self):
        from applemusic.widgets.queue import section_bounds

        def queue(*flags):
            return [types.SimpleNamespace(autoplay=flag) for flag in flags]

        self.assertEqual(section_bounds(queue(False, False, False), 1), (1, 3))
        self.assertEqual(section_bounds(queue(False, False, True, True), 0), (0, 2))
        # The entry playing autoplay's own: its part still starts with it.
        self.assertEqual(section_bounds(queue(False, True, True), 1), (1, 2))
        # Autoplay's entries before the one playing are history, not Up Next.
        self.assertEqual(section_bounds(queue(True, False, False), 1), (1, 3))
        self.assertEqual(section_bounds(queue(True, False), -1), (0, 0))
        self.assertEqual(section_bounds(queue(), -1), (0, 0))


@requires_gtk
class QueueSectionsTest(unittest.TestCase):
    """QueueSections: a model's items in two sections, its changes passed through."""

    def test_sections(self):
        from gi.repository import Gio, Gtk

        from applemusic.widgets.queue import QueueSections

        store = Gio.ListStore(item_type=Gtk.StringObject)
        sections = QueueSections(store)
        changed = []
        sections.connect('items-changed', lambda _m, *args: changed.append(args))
        sections.connect('sections-changed', lambda _m, *args: changed.append(('s', *args)))
        sections.set_split(2)  # nothing to tell an empty list
        for text in 'abcde':
            store.append(Gtk.StringObject.new(text))
        self.assertEqual(sections.get_n_items(), 5)
        self.assertEqual(sections.get_item(3).get_string(), 'd')
        self.assertEqual(changed, [(index, 0, 1) for index in range(5)])
        self.assertEqual([sections.get_section(p) for p in (0, 1, 2, 4)],
                         [(0, 2), (0, 2), (2, 5), (2, 5)])
        sections.set_split(5)  # no autoplay entries: one section
        self.assertEqual(changed[-1], ('s', 0, 5))
        self.assertEqual(sections.get_section(4), (0, 5))
        self.assertEqual(sections.get_section(7)[0], 5)  # past the end


@requires_gtk
class QueueViewTest(unittest.TestCase):
    def setUp(self):
        from gi.repository import Gtk

        from applemusic.widgets.queue import QueueView

        self.player, self.engine, self.app = make_player()
        self.app.player_command = self.run_command
        self.player.apply_queue({'index': 2, 'items': entries(5)})  # Entry 2 plays
        self.view = QueueView()
        self.view.set_player(self.player, self.app)
        self.window = Gtk.Window(default_width=400, default_height=600, child=self.view)
        self.window.present()
        self.addCleanup(self.window.destroy)
        self.assertTrue(wait_for(self.window.get_mapped))
        # The count the list view has been told: its model's items-changed, added up.
        self.model = self.view.list_view.get_model()
        self.told = self.model.get_n_items()
        self.model.connect('items-changed', self.on_items_changed)

    @staticmethod
    def run_command(coro, on_error=None):
        """The app's player_command, run to its end at once (no asyncio loop runs here)."""
        import asyncio

        asyncio.run(coro)

    def on_items_changed(self, _model, _position, removed, added):
        self.told += added - removed

    def bound(self):
        """{list position: QueueRow} of the rows bound."""
        return {row.list_item.get_position(): row for row in self.view._rows}

    def rows(self):
        """The titles of the rows the list view has bound, in order."""
        rows = self.bound()
        return [rows[position].title_label.get_label() for position in sorted(rows)]

    def numbers(self):
        rows = self.bound()
        return [rows[position].number_label.get_text() for position in sorted(rows)]

    def test_an_entry_added_at_the_end_reaches_the_list(self):
        from applemusic.player import NowPlaying

        self.assertEqual(self.told, 3)
        self.assertTrue(wait_for(lambda: self.rows() == ['Entry 2', 'Entry 3', 'Entry 4']))
        self.player.queue.append(NowPlaying(entries(6)[5]))
        self.assertEqual(self.model.get_n_items(), 4)
        self.assertEqual(self.told, 4)
        self.assertTrue(wait_for(lambda: self.rows()[-1:] == ['Entry 5']), self.rows())

    def test_a_longer_queue_from_musickit_reaches_the_list(self):
        # Play Later: MusicKit sends the whole queue again, one entry longer.
        self.player.apply_queue({'index': 2, 'items': entries(6)})
        self.assertEqual(self.told, 4)
        # The next entry plays, and another is added.
        self.player.apply_queue({'index': 3, 'items': entries(6)})
        self.assertEqual(self.told, 3)
        self.player.apply_queue({'index': 3, 'items': entries(7)})
        self.assertEqual(self.model.get_n_items(), 4)
        self.assertEqual(self.told, 4)
        self.assertTrue(wait_for(
            lambda: self.rows() == ['Entry 3', 'Entry 4', 'Entry 5', 'Entry 6']), self.rows())
        self.assertTrue(wait_for(lambda: self.numbers() == ['1', '2', '3', '4']),
                        self.numbers())

    def test_a_shorter_queue_from_the_top(self):
        self.player.apply_queue({'index': 0, 'items': entries(2)})
        self.assertEqual(self.told, 2)
        self.assertTrue(wait_for(lambda: self.rows() == ['Entry 0', 'Entry 1']), self.rows())

    def test_a_rows_menu_is_its_entrys_without_play(self):
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3))
        row = self.bound()[1]
        track = row.context_item
        self.assertEqual((track.id, track.catalog_id, track.title),
                         ('i.queue0003', '2000000003', 'Entry 3'))
        self.assertTrue(row.context_queued)  # activating the row plays it: no Play
        self.assertEqual(row.context_queue_entry, (3, 'i.queue0003'))
        self.assertIsNone(self.bound()[0].context_queue_entry)  # the entry playing
        row.unbind()
        self.assertIsNone(row.context_item)
        self.assertIsNone(row.context_queue_entry)

    def test_a_rows_menu_carries_its_queue_entry(self):
        from gi.repository import Gio

        from applemusic.widgets import context_menu

        asked = []

        class Actions:
            def menu_for(self, obj, queued=False, queue_entry=None):
                asked.append((obj.id, queued, queue_entry))
                menu = Gio.Menu()
                menu.append('Invented', 'win.invented')
                return menu
        self.window.item_actions = Actions()
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3))
        rows = self.bound()
        for position in (1, 0):
            popover = context_menu.popup(rows[position], rows[position].context_item)
            self.assertIsNotNone(popover)
            popover.popdown()
        pump()
        self.assertEqual(asked, [('i.queue0003', True, (3, 'i.queue0003')),
                                 ('i.queue0002', True, None)])  # the entry playing: none

    def test_autoplay_entries_are_a_section_under_its_header(self):
        self.player.apply_queue({'index': 2, 'items': entries(7, autoplay=(5, 6))})
        self.assertEqual(self.model.get_n_items(), 5)
        # The parts: the entry playing and what follows it, then autoplay's.
        self.assertEqual(self.view.model.get_section(0), (0, 3))
        self.assertEqual(self.view.model.get_section(3), (3, 5))
        self.assertTrue(wait_for(lambda: len(self.rows()) == 5), self.rows())
        rows = self.bound()
        self.assertEqual([rows[p].list_item.get_accessible_description() for p in range(5)],
                         ['Playing', '', '', 'Autoplay', 'Autoplay'])
        # A row's queue index runs on across the parts.
        self.assertEqual(self.view.queue_index_at(4), 6)
        self.assertEqual(rows[4].context_queue_entry, (6, 'i.queue0006'))
        self.view.list_view.emit('activate', 4)
        self.assertEqual(self.engine.calls[-1], ('queue_jump', 6))
        # Play Later puts its entry before autoplay's: it joins the first part.
        later = dict(TRACK, id='i.later', catalogId='2000000099', title='Later')
        items = entries(5) + [later] + entries(7, autoplay=(5, 6))[5:]
        self.player.apply_queue({'index': 2, 'items': items})
        self.assertEqual(self.view.model.get_section(0), (0, 4))
        self.assertEqual(self.view.model.get_section(4), (4, 6))
        # Autoplay turned off: its entries go, one event each, and its part with them.
        for count in (7, 6):
            self.player.apply_queue({'index': 2, 'items': items[:count]})
        self.assertEqual(self.model.get_n_items(), 4)
        self.assertEqual(self.view.model.get_section(0), (0, 4))
        self.assertTrue(wait_for(lambda: self.rows()[-1:] == ['Later']), self.rows())

    def test_delete_removes_the_focused_row_and_the_focus_moves_on(self):
        from gi.repository import Gdk, Gio, GLib, Gtk

        removed = []

        def remove(_action, parameter):
            index, entry_id = parameter.unpack()
            removed.append((index, entry_id))
            self.player.queue.remove(index)  # as the Player does, at once
        group = Gio.SimpleActionGroup()
        action = Gio.SimpleAction.new('item-remove-from-queue', GLib.VariantType('(is)'))
        action.connect('activate', remove)
        group.add_action(action)
        self.window.insert_action_group('win', group)
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3))
        self.view.list_view.grab_focus()
        self.view.list_view.scroll_to(1, Gtk.ListScrollFlags.FOCUS, None)
        self.assertTrue(wait_for(lambda: self.focused_title() == 'Entry 3'))
        self.press(Gdk.KEY_Delete)
        self.assertEqual(removed, [(3, 'i.queue0003')])
        self.assertTrue(wait_for(lambda: self.focused_title() == 'Entry 4'),
                        self.focused_title())
        # At the end: the row before takes the focus.
        self.press(Gdk.KEY_Delete)
        self.assertEqual(removed[-1], (3, 'i.queue0004'))
        self.assertTrue(wait_for(lambda: self.focused_title() == 'Entry 2'),
                        self.focused_title())
        # The entry playing is not removed.
        self.press(Gdk.KEY_Delete)
        self.assertEqual(len(removed), 2)

    def focused_title(self):
        from applemusic.widgets import context_menu

        focus = self.window.get_focus()
        found = context_menu.find(self.view.list_view, focus) if focus is not None else None
        return found[0].title_label.get_label() if found is not None else None

    def press(self, keyval):
        """`keyval` pressed on the focused row: the list's shortcut for it run."""
        from gi.repository import Gdk, Gtk

        name = Gdk.keyval_name(keyval)
        for controller in list(self.view.list_view.observe_controllers()):
            if not isinstance(controller, Gtk.ShortcutController):
                continue
            for shortcut in list(controller):
                if name in shortcut.get_trigger().to_string().split('|'):
                    shortcut.get_action().activate(0, self.view.list_view, None)
                    pump()
                    return
        self.fail(f'no shortcut for {name}')

    def test_clear_and_its_undo_toast(self):
        self.assertTrue(self.view.clear_button.get_sensitive())
        self.view.clear_button.emit('clicked')
        self.assertTrue(wait_for(lambda: self.app.toasts == ['Up Next cleared']),
                        self.app.toasts)
        self.assertEqual(self.engine.calls[-1], ('queue_clear',))
        self.assertEqual(self.model.get_n_items(), 1)
        self.assertFalse(self.view.clear_button.get_sensitive())  # nothing after the entry

    def test_the_tools_follow_what_musickit_allows(self):
        view, player = self.view, self.player
        self.assertTrue(view.autoplay_button.get_active())  # the setting's
        self.assertTrue(view.autoplay_button.get_sensitive())
        player.apply_queue({'index': 2, 'items': entries(5), 'editable': False,
                            'canAutoplay': False})
        self.assertFalse(view.clear_button.get_sensitive())
        self.assertFalse(view.autoplay_button.get_sensitive())
        self.assertEqual(view.autoplay_button.get_tooltip_text(),
                         'Autoplay Is Not Available Here')
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3))
        self.assertIsNone(self.bound()[1].context_queue_entry)  # a station's: no Remove
        player.apply_queue({'index': 2, 'items': entries(5)})
        player._set_repeat('all')
        self.assertFalse(view.autoplay_button.get_sensitive())
        self.assertEqual(view.autoplay_button.get_tooltip_text(),
                         'Autoplay Is Off While Repeat Is On')
        player._set_repeat('none')
        self.assertTrue(view.autoplay_button.get_sensitive())
        self.assertEqual(view.autoplay_button.get_tooltip_text(), 'Autoplay')


if __name__ == '__main__':
    unittest.main()
