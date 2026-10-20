# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The library pages' filter bar (widgets/filter_bar.py): what it matches (text_filter() as
library.filter_matches() has it), how it is shown, closed and offered, and ShownModel's
replacement of a whole list, which lets a grid or list recycle its rows."""

import unittest

from tests.gtk import requires_gtk
from tests.page_harness import PageTestCase, album, track


class MatchingTest(unittest.TestCase):
    def test_a_filter_matches_the_whole_text_in_one_field_case_and_accents_ignored(self):
        from applemusic.library import filter_matches, fold, search_key

        key = search_key('Café Lights', 'Beyoncé Invented', 'Night Album')
        self.assertTrue(filter_matches(fold('cafe'), key))
        self.assertTrue(filter_matches(fold('BEYONCÉ'), key))
        self.assertTrue(filter_matches(fold('é lig'), key))  # inside a word, spaces and all
        self.assertTrue(filter_matches(fold(''), key))  # no text: everything
        # The whole text, in one field: not words from two.
        self.assertFalse(filter_matches(fold('lights beyonce'), key))
        self.assertFalse(filter_matches(fold('dawn'), key))

    def test_an_items_key_is_its_title_and_subtitle_and_follows_them(self):
        from applemusic.library import Item

        item = Item(album(1))
        self.assertEqual(item.search_key, 'invented album 001\ninvented artist')
        item.merge(dict(album(1), title='Renamed Àlbum'), replace=True)  # a reload
        self.assertEqual(item.search_key, 'renamed album\ninvented artist')
        item.title = 'Another Name'  # a rename, written into its raw dict
        self.assertEqual(item.search_key, 'another name\ninvented artist')
        nameless = Item({'id': 'l.art9', 'kind': 'artist', 'title': ''})
        self.assertEqual(nameless.search_key, 'unknown artist\n')

    def test_a_tracks_key_is_its_title_artist_and_album(self):
        from applemusic.library import Track

        song = Track(dict(track('l.album001', 0, title='Señal'), artist='Ünder', album='Way'))
        self.assertEqual(song.search_key, 'senal\nunder\nway')


@requires_gtk
class TextFilterTest(unittest.TestCase):
    def test_the_string_filter_matches_as_filter_matches_does(self):
        from gi.repository import Gio, Gtk

        from applemusic.library import Item, filter_matches, fold
        from applemusic.widgets.filter_bar import text_filter

        items = [Item(dict(album(n), title=title, subtitle=artist))
                 for n, (title, artist) in enumerate([
                     ('Café Nights', 'Aura Invented'), ('Dawn', 'Ça Va Band'),
                     ('Night Café', 'Zephyr'), ('Ünder', 'Lines')])]
        store = Gio.ListStore(item_type=Item)
        store.splice(0, 0, items)
        string_filter = text_filter()
        model = Gtk.FilterListModel(model=store, filter=string_filter)
        self.assertEqual(model.get_n_items(), 4)  # no text: everything, no key read
        self.assertEqual(string_filter.get_strictness(), Gtk.FilterMatch.ALL)
        for text in ('cafe', 'CA', 'nder', 'night', 'a va', 'zz', 'é n'):
            string_filter.set_search(fold(text))
            shown = [model.get_item(n) for n in range(model.get_n_items())]
            self.assertEqual(shown, [item for item in items
                                     if filter_matches(fold(text), item.search_key)], text)


@requires_gtk
class ShownModelTest(unittest.TestCase):
    def strings(self, values):
        from gi.repository import Gtk

        return Gtk.StringList.new(values)

    def test_a_replacement_inserts_the_new_items_before_removing_the_old(self):
        from applemusic.widgets.filter_bar import ShownModel

        source = self.strings(['a', 'b', 'c'])
        model = ShownModel(source)
        changes = []

        def shown():
            return [model.get_item(n).get_string() for n in range(model.get_n_items())]

        model.connect('items-changed', lambda _model, *change: changes.append(
            (change, shown())))
        scrolled = []
        with model.replacing(lambda: scrolled.append(shown())):
            source.splice(0, 3, ['x', 'b'])
        # The new list in front of the old, the view moved meanwhile, then the old gone.
        self.assertEqual(changes, [((0, 0, 2), ['x', 'b', 'a', 'b', 'c']),
                                   ((2, 3, 0), ['x', 'b'])])
        self.assertEqual(scrolled, [['x', 'b', 'a', 'b', 'c']])
        # Outside replacing(), a change is passed on as it came.
        changes.clear()
        source.splice(1, 0, ['y'])
        self.assertEqual(changes, [((1, 0, 1), ['x', 'y', 'b'])])
        # A change that only removes, or only adds, has nothing to recycle.
        changes.clear()
        with model.replacing(lambda: scrolled.append(None)):
            source.splice(0, 1, [])
        self.assertEqual(changes, [((0, 1, 0), ['y', 'b'])])
        self.assertEqual(model.find(source.get_item(1)), 1)

    def test_backwards_a_replacement_is_shown_backwards_too(self):
        from applemusic.widgets.filter_bar import ShownModel

        source = self.strings(['a', 'b', 'c'])
        model = ShownModel(source)
        model.set_backwards(True)
        changes = []

        def shown():
            return [model.get_item(n).get_string() for n in range(model.get_n_items())]

        model.connect('items-changed', lambda _model, *change: changes.append(
            (change, shown())))
        with model.replacing(lambda: None):
            source.splice(1, 2, ['x', 'y'])  # a, x, y: shown y, x, a
        self.assertEqual(changes, [((0, 0, 3), ['y', 'x', 'a', 'c', 'b', 'a']),
                                   ((3, 3, 0), ['y', 'x', 'a'])])
        self.assertEqual(model.find(source.get_item(0)), 2)
        self.assertIsNone(model.get_item(3))


class FilterBarTest(PageTestCase):
    async def bar(self):
        from gi.repository import Gtk

        from applemusic.widgets.filter_bar import FilterBar

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_view = Gtk.Button(label='Invented list')  # takes the focus back
        bar = FilterBar('Filter Invented')
        page.append(bar)
        page.append(list_view)
        self.window.root_box.append(page)
        self.assertTrue(await self.until(bar.get_mapped))
        returned = []
        changes = []
        self._list = list_view

        def back(obj):
            returned.append(obj)
            if self._list.get_visible():
                list_view.grab_focus()
                return True
            return False  # no list shown: the bar's button takes the focus

        self._back = back  # held: the bar holds it weakly
        bar.set_focus_return(self._back_method)
        bar.connect('changed', lambda bar: changes.append(bar.search))
        return page, bar, returned, changes

    def _back_method(self, obj):
        return self._back(obj)

    async def test_offered_shown_by_focus_and_closed_by_escape(self):
        from gi.repository import Gdk, Gtk

        page, bar, returned, changes = await self.bar()
        self.assertFalse(bar.available)
        self.assertFalse(bar.button.get_visible())
        self.assertFalse(bar.focus())  # nothing to filter: Ctrl+F goes elsewhere
        self.assertIsNone(bar.get_key_capture_widget())
        bar.set_available(True, page)
        self.assertTrue(bar.button.get_visible())
        self.assertIs(bar.get_key_capture_widget(), page)  # typing on the page starts it
        self.assertEqual(bar.button.get_tooltip_text(), 'Filter Invented')
        self.assertEqual(bar.entry.get_placeholder_text(), 'Filter Invented')
        self.assertTrue(bar.focus())
        self.assertTrue(bar.get_search_mode())
        self.assertTrue(bar.button.get_active())
        self.assertTrue(await self.until_focused(bar.entry))
        # Typed: the text folded, after the entry's delay (here at once).
        bar.entry.set_text('Café')
        bar.entry.emit('search-changed')
        self.assertEqual(changes[-1], 'cafe')
        bar.entry.select_region(0, 1)
        bar.entry.delete_selection()
        bar.entry.insert_text('c', 0)  # retyped: the same folded, no change
        bar.entry.emit('search-changed')
        self.assertEqual(changes.count('cafe'), 1)
        # Escape in the entry: closed, cleared, the focus back on the page's list.
        bar.entry.emit('stop-search')
        self.assertFalse(bar.get_search_mode())
        self.assertFalse(bar.button.get_active())
        self.assertTrue(await self.until(lambda: bar.search == '' and returned))
        self.assertEqual(changes[-1], '')
        self.assertEqual(returned, [None])  # the focus was on no item of the page's
        self.assertTrue(await self.until(lambda: self.window.get_focus() is self._list))
        # Escape on the page while it shows closes it too; not while it is closed.
        escape = next(controller for controller in page.observe_controllers()
                      if isinstance(controller, Gtk.EventControllerKey))
        self.assertFalse(escape.emit('key-pressed', Gdk.KEY_Escape, 0, Gdk.ModifierType(0)))
        bar.set_text('dawn')
        self.assertEqual(changes[-1], 'dawn')  # at once, the bar shown with it
        self.assertTrue(bar.get_search_mode())
        self.assertFalse(escape.emit('key-pressed', Gdk.KEY_a, 0, Gdk.ModifierType(0)))
        self.assertTrue(escape.emit('key-pressed', Gdk.KEY_Escape, 0, Gdk.ModifierType(0)))
        self.assertFalse(bar.get_search_mode())
        self.assertTrue(await self.until(lambda: bar.search == ''))
        # No longer offered: the button and the capture go, and the page's controller.
        bar.set_available(False)
        self.assertFalse(bar.button.get_visible())
        self.assertIsNone(bar.get_key_capture_widget())
        self.assertFalse(any(isinstance(controller, Gtk.EventControllerKey)
                             for controller in page.observe_controllers()))

    async def test_with_no_list_to_go_back_to_the_focus_goes_to_the_button(self):
        page, bar, returned, _changes = await self.bar()
        page.prepend(bar.button)  # in the page's header bar
        bar.set_available(True, page)
        self.assertTrue(bar.focus())
        self.assertTrue(await self.until_focused(bar.entry))
        self._list.set_visible(False)  # a status page in its place
        bar.entry.emit('stop-search')
        self.assertTrue(await self.until(lambda: self.window.get_focus() is bar.button),
                        self.window.get_focus())
        self.assertEqual(returned, [None])

    async def test_the_count_is_announced_through_the_window(self):
        from gi.repository import Gtk

        _page, bar, _returned, _changes = await self.bar()
        said = []
        self.window.announce = lambda text, priority: said.append((text, priority))
        self.addCleanup(delattr, self.window, 'announce')
        bar.announce('3 of 9 invented things')
        self.assertEqual(said, [('3 of 9 invented things',
                                 Gtk.AccessibleAnnouncementPriority.LOW)])


if __name__ == '__main__':
    unittest.main()
