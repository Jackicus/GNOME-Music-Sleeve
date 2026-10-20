# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""widgets/queue.py: Up Next, the Player's queue from the entry playing on, follows the queue
while it is open, whichever entry plays: entries added at the queue's end and a new queue
reach the list; the entry playing, Playing Next and the entries autoplay added are sections
of their own, the last two under their headers; a row is the queue's entry at its place,
with its cover; Remove from Up Next (the menu, Delete) and Clear, and the Autoplay toggle;
History, the entries before the one playing, most recent first; EntryArt, which finds each
entry's cover once, for the rows bound. (The slice's start is tested in test_transport.py's
QueueSliceTest.)"""

import asyncio
import os
import tempfile
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
    """section_bounds(): where Up Next's parts begin; section_at(): the part a row is in."""

    def test_bounds(self):
        from applemusic.widgets.queue import section_bounds

        def queue(*flags):
            return [types.SimpleNamespace(autoplay=flag) for flag in flags]

        self.assertEqual(section_bounds(queue(False, False, False), 1), (1, 2, 3))
        self.assertEqual(section_bounds(queue(False, False, True, True), 0), (0, 1, 2))
        # The entry playing autoplay's own: Playing Next is empty, Autoplay follows it.
        self.assertEqual(section_bounds(queue(False, True, True), 1), (1, 2, 2))
        # Autoplay's entries before the one playing are history, not Up Next.
        self.assertEqual(section_bounds(queue(True, False, False), 1), (1, 2, 3))
        # The last entry playing: nothing after it.
        self.assertEqual(section_bounds(queue(False, False), 1), (1, 2, 2))
        # Nothing playing: no part of its own for it.
        self.assertEqual(section_bounds(queue(False, True), -1), (0, 0, 1))
        self.assertEqual(section_bounds(queue(True, False), -1), (0, 0, 0))
        self.assertEqual(section_bounds(queue(), -1), (0, 0, 0))

    def test_section_at(self):
        from applemusic.widgets.queue import section_at

        # The entry playing, Playing Next, Autoplay.
        self.assertEqual([section_at(p, 6, (1, 4)) for p in range(6)],
                         [(0, 1), (1, 4), (1, 4), (1, 4), (4, 6), (4, 6)])
        # An empty Playing Next: two parts.
        self.assertEqual([section_at(p, 3, (1, 1)) for p in range(3)],
                         [(0, 1), (1, 3), (1, 3)])
        # Bounds at the start or past the end divide nothing.
        self.assertEqual([section_at(p, 3, (0, 3)) for p in range(3)], [(0, 3)] * 3)
        self.assertEqual(section_at(1, 3, ()), (0, 3))


@requires_gtk
class QueueSectionsTest(unittest.TestCase):
    """QueueSections: a model's items in sections, its changes passed through."""

    def test_sections(self):
        from gi.repository import Gio, Gtk

        from applemusic.widgets.queue import QueueSections

        store = Gio.ListStore(item_type=Gtk.StringObject)
        sections = QueueSections(store)
        changed = []
        sections.connect('items-changed', lambda _m, *args: changed.append(args))
        sections.connect('sections-changed', lambda _m, *args: changed.append(('s', *args)))
        sections.set_bounds(1, 3)  # nothing to tell an empty list
        for text in 'abcde':
            store.append(Gtk.StringObject.new(text))
        self.assertEqual(sections.get_n_items(), 5)
        self.assertEqual(sections.get_item(3).get_string(), 'd')
        self.assertEqual(changed, [(index, 0, 1) for index in range(5)])
        self.assertEqual([sections.get_section(p) for p in (0, 1, 2, 3, 4)],
                         [(0, 1), (1, 3), (1, 3), (3, 5), (3, 5)])
        sections.set_bounds(1, 5)  # no autoplay entries: the entry playing, then the rest
        self.assertEqual(changed[-1], ('s', 0, 5))
        self.assertEqual(sections.get_section(4), (1, 5))
        self.assertEqual(sections.get_section(7)[0], 5)  # past the end
        changed.clear()
        sections.set_bounds(1, 5)  # the same: nothing to tell
        self.assertEqual(changed, [])


class HistoryTest(unittest.TestCase):
    """history_entries() and HistoryModel: what played before, most recent first, changed
    by one splice of what differs."""

    def test_entries_most_recent_first(self):
        from gi.repository import Gio

        from applemusic.player import NowPlaying
        from applemusic.widgets.queue import history_entries

        store = Gio.ListStore(item_type=NowPlaying)
        for entry in entries(4):
            store.append(NowPlaying(entry))
        self.assertEqual([entry.title for entry in history_entries(store, 3)],
                         ['Entry 2', 'Entry 1', 'Entry 0'])
        self.assertEqual(history_entries(store, 0), [])
        self.assertEqual(history_entries(store, -1), [])
        self.assertEqual(len(history_entries(store, 9)), 4)  # past the end: all of it

    def test_the_model_splices_only_what_differs(self):
        from applemusic.player import NowPlaying
        from applemusic.widgets.queue import HistoryModel

        made = [NowPlaying(entry) for entry in entries(6)]
        model = HistoryModel()
        changed = []
        model.connect('items-changed', lambda _m, *args: changed.append(args))
        model.update(made[2::-1])            # Entry 3 plays: 2, 1, 0
        self.assertEqual(changed, [(0, 0, 3)])
        self.assertIs(model.get_item(0), made[2])
        self.assertIsNone(model.get_item(3))
        model.update(made[3::-1])            # the next entry plays: one row on top
        self.assertEqual(changed[-1], (0, 0, 1))
        model.update(made[3::-1])            # nothing new
        self.assertEqual(len(changed), 2)
        model.update(made[1::-1])            # back two: two rows off the top
        self.assertEqual(changed[-1], (0, 2, 0))
        other = [NowPlaying(entry) for entry in entries(2)]
        model.update(other)                  # another queue: all of it
        self.assertEqual(changed[-1], (0, 2, 2))
        model.update(())
        self.assertEqual(changed[-1], (0, 2, 0))
        self.assertEqual(model.get_n_items(), 0)


class EntryArtTest(unittest.TestCase):
    """EntryArt: each URL's file found once, on disk or fetched, only for the rows bound."""

    def setUp(self):
        self.spawned = []
        self.bound = set()
        self.found = []
        self.fetched = []
        self.on_disk = {}

    def make(self, fetch=True):
        from applemusic.widgets.queue import EntryArt

        async def fetch_one(url):
            self.fetched.append(url)
            return f'/fetched/{url}' if 'broken' not in url else None

        def find(urls):
            return {url: self.on_disk[url] for url in urls if url in self.on_disk}

        art = EntryArt(self.spawned.append, lambda: self.bound,
                       lambda url, path: self.found.append((url, path)),
                       fetch=fetch_one if fetch else None, find=find)
        self.addCleanup(self.remove_source, art)
        return art

    @staticmethod
    def remove_source(art):
        from gi.repository import GLib

        if art._source:
            GLib.source_remove(art._source)
            art._source = 0

    def look(self, art):
        """The look EntryArt's timeout would make, and the coroutines it spawned run."""
        self.remove_source(art)
        art._look()
        while self.spawned:
            asyncio.run(self.spawned.pop(0))

    def test_found_on_disk_or_fetched_once_for_the_rows_bound(self):
        art = self.make()
        self.on_disk['a'] = '/disk/a'
        for url in ('a', 'b', 'gone', 'a', None, ''):
            art.want(url)
        self.assertEqual(art.paths('a'), ())
        self.bound.update({'a', 'b'})  # 'gone' was scrolled past before the look
        self.look(art)
        self.assertEqual(sorted(self.found), [('a', '/disk/a'), ('b', '/fetched/b')])
        self.assertEqual(self.fetched, ['b'])   # what is on disk is never fetched
        self.assertEqual(art.paths('a'), ('/disk/a',))
        self.assertEqual(art.paths('b'), ('/fetched/b',))
        self.assertEqual(art.paths(None), ())
        # Known now: never asked about again.
        art.want('a')
        art.want('b')
        self.assertEqual(art.pending(), 0)
        self.assertFalse(art._source)
        # 'gone' is asked about again when a row bound wants it.
        self.bound.add('gone')
        art.want('gone')
        self.look(art)
        self.assertEqual(self.fetched, ['b', 'gone'])

    def test_a_failed_fetch_is_not_tried_again(self):
        art = self.make()
        self.bound.add('broken')
        art.want('broken')
        self.look(art)
        self.assertEqual(self.found, [])
        self.assertEqual(art.paths('broken'), ())
        art.want('broken')
        self.assertEqual(art.pending(), 0)
        self.assertEqual(self.fetched, ['broken'])

    def test_without_fetching_only_what_is_on_disk(self):
        art = self.make(fetch=False)   # the demo
        self.on_disk['a'] = '/disk/a'
        self.bound.update({'a', 'b'})
        art.want('a')
        art.want('b')
        self.look(art)
        self.assertEqual(self.found, [('a', '/disk/a')])
        self.assertEqual(self.fetched, [])
        art.want('b')
        self.assertEqual(art.pending(), 0)

    def test_a_cleared_cache_is_looked_in_again(self):
        # Clear Cache or a sign-out deletes the files found: each is looked for again (on
        # disk, else fetched), never named from before.
        from applemusic.backend import store

        art = self.make()
        self.on_disk['a'] = '/disk/a'
        self.bound.update({'a', 'b', 'broken'})
        for url in ('a', 'b', 'broken'):
            art.want(url)
        self.look(art)
        self.assertEqual(art.paths('a'), ('/disk/a',))
        store.bump_cache_generation()
        self.on_disk.clear()
        self.assertEqual(art.paths('a'), ())
        self.assertEqual(art.paths('b'), ())
        for url in ('a', 'b', 'broken'):
            art.want(url)
        self.look(art)
        self.assertEqual(sorted(self.fetched[2:]), ['a', 'b', 'broken'])
        self.assertEqual(art.paths('a'), ('/fetched/a',))

    def test_a_look_under_way_as_the_cache_is_cleared_is_not_kept(self):
        from applemusic.backend import store

        art = self.make()
        self.on_disk['a'] = '/disk/a'
        self.bound.add('a')
        art.want('a')
        self.remove_source(art)
        art._look()
        store.bump_cache_generation()  # while the look runs
        while self.spawned:
            asyncio.run(self.spawned.pop(0))
        self.assertEqual(art.paths('a'), ())
        self.assertEqual(self.found, [])
        art.want('a')
        self.assertEqual(art.pending(), 1)  # asked about again

    def test_the_candidates_and_the_first_on_disk(self):
        from applemusic.backend import config
        from applemusic.remote import remote_art_path
        from applemusic.widgets.queue import art_candidates, find_art

        url = 'https://example.invalid/art/{w}x{h}bb.jpg'
        with tempfile.TemporaryDirectory() as cache:
            candidates = art_candidates(url, cache)
            self.assertEqual(len(candidates), 3)
            self.assertEqual(candidates[0], remote_art_path(url, config.THUMB_SIZE))
            self.assertEqual(candidates[2], remote_art_path(url, config.COVER_SIZE))
            self.assertTrue(candidates[1].startswith(os.path.join(cache, 'thumb')))
            self.assertEqual(art_candidates(None, cache), [])
            on_disk = {candidates[1], candidates[2]}
            self.assertEqual(find_art([url, 'https://example.invalid/none.jpg'],
                                      lambda each: art_candidates(each, cache),
                                      on_disk.__contains__), {url: candidates[1]})


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
        # The covers: never fetched here, and looked for at once (no asyncio loop runs).
        self.view.art._fetch = None
        self.view.art._find = lambda urls: {}
        self.view.art._spawn = asyncio.run
        self.addCleanup(EntryArtTest.remove_source, self.view.art)  # no look after the test
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
        return {row.list_item.get_position(): row for row in self.view._rows
                if not row.history}

    def rows(self):
        """The titles of the rows the list view has bound, in order."""
        rows = self.bound()
        return [rows[position].title_label.get_label() for position in sorted(rows)]

    def marked(self):
        """Which bound rows show the play symbol over their cover, in order."""
        rows = self.bound()
        return [rows[position].playing_scrim.get_opacity() == 1 for position in sorted(rows)]

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
        self.assertTrue(wait_for(lambda: self.marked() == [True, False, False, False]),
                        self.marked())

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
        # The parts: the entry playing, what follows it (Playing Next), then autoplay's.
        self.assertEqual(self.view.model.get_section(0), (0, 1))
        self.assertEqual(self.view.model.get_section(1), (1, 3))
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
        # The headers: none over the entry playing, then Playing Next's and Autoplay's.
        # (Once the list has laid the headers out where their sections begin.)
        self.assertTrue(wait_for(lambda: self.headers() == ['', 'Playing Next', 'Autoplay']),
                        self.headers())
        # Play Later puts its entry before autoplay's: it joins Playing Next.
        later = dict(TRACK, id='i.later', catalogId='2000000099', title='Later')
        items = entries(5) + [later] + entries(7, autoplay=(5, 6))[5:]
        self.player.apply_queue({'index': 2, 'items': items})
        self.assertEqual(self.view.model.get_section(1), (1, 4))
        self.assertEqual(self.view.model.get_section(4), (4, 6))
        # Autoplay turned off: its entries go, one event each, and its part with them.
        for count in (7, 6):
            self.player.apply_queue({'index': 2, 'items': items[:count]})
        self.assertEqual(self.model.get_n_items(), 4)
        self.assertEqual(self.view.model.get_section(1), (1, 4))
        self.assertTrue(wait_for(lambda: self.rows()[-1:] == ['Later']), self.rows())

    def test_a_queue_of_one_has_no_header(self):
        """A live station's queue (one entry) on an empty Up Next: the Player splices it in
        before it sets the index, so the header is bound while nothing plays; it is named
        again once the entry plays (#420)."""
        self.player.apply_queue(None)
        self.assertEqual(self.player.queue_index, -1)
        station = dict(TRACK, id='ra.invented', catalogId='ra.invented', title='Station',
                       isLive=True)
        self.player.apply_queue({'index': 0, 'items': [station], 'editable': False})
        self.assertEqual(self.player.queue_index, 0)
        self.assertEqual(self.view.model.get_section(0), (0, 1))
        self.assertTrue(wait_for(lambda: self.rows() == ['Station']), self.rows())
        self.assertTrue(wait_for(lambda: self.headers() == ['']), self.headers())
        pump()
        self.assertEqual(self.headers(), [''])
        # The same entry, playing no more: the queue from its top is Playing Next.
        self.player._set_queue_index(-1)
        self.assertTrue(wait_for(lambda: self.headers() == ['Playing Next']), self.headers())
        self.player._set_queue_index(0)
        self.assertTrue(wait_for(lambda: self.headers() == ['']), self.headers())

    def test_the_last_entry_playing_has_no_header(self):
        self.player.apply_queue({'index': 4, 'items': entries(5)})
        self.assertTrue(wait_for(lambda: self.rows() == ['Entry 4']), self.rows())
        self.assertTrue(wait_for(lambda: self.headers() == ['']), self.headers())
        # From a queue that was empty, too.
        self.player.apply_queue(None)
        self.player.apply_queue({'index': 1, 'items': entries(2)})
        self.assertTrue(wait_for(lambda: self.rows() == ['Entry 1']), self.rows())
        self.assertTrue(wait_for(lambda: self.headers() == ['']), self.headers())

    def test_only_autoplay_after_the_entry_playing_has_no_playing_next(self):
        self.player.apply_queue(None)
        self.player.apply_queue({'index': 0, 'items': entries(3, autoplay=(1, 2))})
        self.assertEqual(self.view.model.get_section(1), (1, 3))
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3), self.rows())
        self.assertTrue(wait_for(lambda: self.headers() == ['', 'Autoplay']), self.headers())
        # The next entry plays (autoplay's own): Autoplay still, with no Playing Next.
        self.player.apply_queue({'index': 1, 'items': entries(3, autoplay=(1, 2))})
        self.assertTrue(wait_for(lambda: self.rows() == ['Entry 1', 'Entry 2']), self.rows())
        self.assertTrue(wait_for(lambda: self.headers() == ['', 'Autoplay']), self.headers())

    def test_history_has_no_headers(self):
        self.view.history_button.set_active(True)
        self.assertIsNone(self.view.history_view.get_header_factory())
        self.assertTrue(wait_for(lambda: self.history_rows() == ['Entry 1', 'Entry 0']),
                        self.history_rows())

    def headers(self):
        """The texts of the section headers shown, top to bottom ('' for a hidden one)."""
        from gi.repository import Gtk

        found = []

        def walk(widget):
            if (isinstance(widget, Gtk.Label) and widget.has_css_class('queue-section')
                    and widget.get_parent().get_mapped()):
                _ok, bounds = widget.compute_bounds(self.view.list_view)
                found.append((bounds.get_y(), widget.get_label() if widget.get_visible()
                              else ''))
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        found.clear()
        walk(self.view.list_view)
        return [text for _y, text in sorted(found)]

    def test_rows_show_their_covers(self):
        """Each row's cover from EntryArt: found once for the rows bound, then shown."""
        url = 'https://example.invalid/{w}x{h}bb.jpg'
        asked = []

        def find(urls):
            asked.extend(urls)
            return {each: '/disk/cover.jpg' for each in urls if each == url}
        self.view.art._find = find
        self.player.apply_queue({'index': 0, 'items': [dict(entry, artUrl=url)
                                                       for entry in entries(3)]})
        self.assertTrue(wait_for(lambda: len(self.rows()) == 3))
        self.assertTrue(wait_for(lambda: self.view.art.paths(url) == ('/disk/cover.jpg',)))
        self.assertTrue(wait_for(lambda: all(
            row.cover.paths == ('/disk/cover.jpg',) for row in self.bound().values())))
        self.assertEqual(asked.count(url), 1)   # one look for the URL, however many rows

    def test_history_shows_what_played_before_most_recent_first(self):
        view = self.view
        self.assertFalse(view.history_shown)
        self.assertEqual(view.history_model.get_n_items(), 0)   # nothing while hidden
        view.history_button.set_active(True)
        self.assertEqual(view.lists.get_visible_child_name(), 'history')
        self.assertFalse(view.clear_button.get_visible())
        self.assertFalse(view.autoplay_button.get_visible())
        self.assertTrue(wait_for(lambda: self.history_rows() == ['Entry 1', 'Entry 0']),
                        self.history_rows())
        rows = self.bound_history()
        self.assertIsNone(rows[0].context_queue_entry)   # no Remove in History
        self.assertEqual(rows[0].context_item.id, 'i.queue0001')
        view.history_view.emit('activate', 1)
        self.assertEqual(self.engine.calls[-1], ('queue_jump', 0))
        # The next entry plays: it joins History at the top, the rows there kept.
        changed = []
        view.history_model.connect('items-changed', lambda _m, *args: changed.append(args))
        self.player.apply_queue({'index': 3, 'items': entries(5)})
        self.assertEqual(changed, [(0, 0, 1)])
        self.assertTrue(wait_for(
            lambda: self.history_rows() == ['Entry 2', 'Entry 1', 'Entry 0']),
            self.history_rows())
        # A new queue from its top: nothing played yet.
        self.player.apply_queue({'index': 0, 'items': entries(2)})
        self.assertEqual(view.lists.get_visible_child_name(), 'no-history')
        # Back to Up Next, and History follows nothing meanwhile.
        view.history_button.set_active(False)
        self.assertEqual(view.lists.get_visible_child_name(), 'up-next')
        self.assertTrue(view.clear_button.get_visible())
        self.player.apply_queue({'index': 1, 'items': entries(2)})
        self.assertEqual(view.history_model.get_n_items(), 0)

    def test_leaving_the_tab_leaves_history(self):
        self.view.history_button.set_active(True)
        self.view.set_active(True)
        self.view.set_active(False)
        self.assertFalse(self.view.history_shown)
        self.assertEqual(self.view.lists.get_visible_child_name(), 'up-next')

    def bound_history(self):
        return {row.list_item.get_position(): row for row in self.view._rows if row.history}

    def history_rows(self):
        rows = self.bound_history()
        return [rows[position].title_label.get_label() for position in sorted(rows)]

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
