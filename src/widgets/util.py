# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""connect_weak(): a signal connection that does not keep the handler's widget alive (and
weak_method(), the same for any other callback a child holds); MappedHandlers: a widget's
handlers on objects that outlive it (the library, the engine), connected only while it is
mapped; next_frame(): wait for a widget's next frame; each_frame(), rows_kept(), grown(),
holds_in_order() and GrowBack: a list's rows given to it a few a frame; HeaderTitle: a page's
title in its
header bar only while its big title is out of view; descendants(), first_descendant() and
has_ancestor(): the widget tree by class; focus_position(): the focus on a list's item.

A widget that connects one of its children's signals (or an owned object's: a list factory,
an adjustment, a sort model, an event controller) to one of its own bound methods makes a
reference cycle that runs through C: the widget holds the child, the child holds the
signal's closure, the closure holds the bound method, and the bound method holds the
widget's Python wrapper, which holds the widget. Python's collector cannot see the C part,
so the widget is never freed, nor anything it holds (a page's rows and tiles). Blueprint's
`=> $handler()` callbacks make the same cycle (PyGObject connects them to the template's
bound methods).

connect_weak() breaks it: the closure holds the method's function and a GObject weak
reference to the widget (GObject.Object.weak_ref()), so the widget is freed when nothing
else holds it, and the handler disconnects itself the first time it is emitted after that (a
long-lived emitter, such as a library Item, never piles up dead handlers).

Not a Python weakref: with PyGObject 3.56 a GObject's Python wrapper lives only while Python
holds it. The GObject keeps the wrapper's attributes, and a new wrapper is made the next time
Python gets the object (from get_visible_page(), a signal's arguments...). A weakref.ref or
weakref.WeakMethod of a widget therefore dies as soon as Python lets go of it, however long
the widget lives, and says nothing about whether it was freed; a GObject weak reference
follows the object itself.

A widget that can be dropped (a pushed page, a Shelf, a dialog) connects every signal of an
object it holds this way. Handlers on the widget itself (`self.connect('map', ...)`) and
GObject vfuncs (`do_map`) need nothing: PyGObject sees those.
"""

import asyncio
import weakref

from gi.repository import GLib, GObject, Gtk


def _weak_target(method):
    """(a callable answering the method's object or None, the method's function)."""
    target, function = method.__self__, method.__func__
    if isinstance(target, GObject.Object):
        return target.weak_ref(), function
    return weakref.ref(target), function


def connect_weak(obj, signal, method, *extra):
    """obj.connect(signal, method, *extra), holding the object of `method` (a bound method)
    weakly.

    The handler returns the method's result (a signal that wants one, such as
    GtkOverlay::get-child-position, gets it) and, once the method's object has been freed,
    disconnects itself and returns None. Returns the handler id, as connect() does. `extra`
    is held strongly: never pass the method's object there.
    """
    target, function = _weak_target(method)
    handler_id = None

    def handler(emitter, *args):
        instance = target()
        if instance is None:
            if handler_id is not None and emitter.handler_is_connected(handler_id):
                emitter.disconnect(handler_id)
            return None
        return function(instance, emitter, *args, *extra)

    handler_id = obj.connect(signal, handler)
    return handler_id


def weak_method(method):
    """A function that calls `method` (a bound method) with its object held weakly, as
    connect_weak() does, for a callback that is not a signal handler but is held by a child
    all the same (the create function of Gtk.FlowBox.bind_model). It returns None once the
    method's object has been freed."""
    target, function = _weak_target(method)

    def call(*args):
        instance = target()
        return None if instance is None else function(instance, *args)

    return call


class MappedHandlers:
    """The handlers a widget holds on objects that outlive it (the library, the engine),
    connected while the widget is mapped: declared once, in __init__,

        self._handlers = MappedHandlers(self)
        self._handlers.add(library, 'notify::state', self._update)

    each is connected when the widget maps (and at once if it is mapped), weakly, as
    connect_weak() does, and disconnected when it unmaps, so a hidden page does no work for a
    library that changes and a dropped one leaves nothing connected. The widget's do_map runs
    before the handlers are connected: it catches up with what changed while it was hidden.
    remove(obj) forgets an object's handlers (an item the page no longer shows).
    """

    def __init__(self, widget):
        self._widget = widget.weak_ref()
        self._entries = []  # [obj, signal, the callback's target (weak), function, handler id]
        # The closures hold this object, which holds the widget weakly: no cycle.
        widget.connect('map', self._on_map)
        widget.connect('unmap', self._on_unmap)

    def add(self, obj, signal, callback):
        """Call callback (a bound method of the widget, or of an object it holds) with the
        signal's arguments whenever obj emits signal while the widget is mapped."""
        target, function = _weak_target(callback)
        entry = [obj, signal, target, function, None]
        self._entries.append(entry)
        widget = self._widget()
        if widget is not None and widget.get_mapped():
            self._connect(entry)

    def remove(self, obj):
        """Disconnect and forget every handler on obj."""
        for entry in [entry for entry in self._entries if entry[0] is obj]:
            self._disconnect(entry)
            self._entries.remove(entry)

    def _connect(self, entry):
        if entry[4] is not None:
            return
        obj, signal, target, function, _handler = entry

        def handler(emitter, *args):
            instance = target()
            return None if instance is None else function(instance, emitter, *args)

        entry[4] = obj.connect(signal, handler)

    @staticmethod
    def _disconnect(entry):
        if entry[4] is not None:
            entry[0].disconnect(entry[4])
            entry[4] = None

    def _on_map(self, _widget):
        for entry in self._entries:
            self._connect(entry)

    def _on_unmap(self, _widget):
        for entry in self._entries:
            self._disconnect(entry)


# How long next_frame() waits for a tick at most: a widget unmapped before its next frame
# gets none.
FRAME_TIMEOUT_MS = 100


def next_frame(widget):
    """A future resolved at the widget's next frame (its frame clock's tick), so that a page
    building in steps builds one a frame and GTK paints in between; while the widget is not
    mapped (it gets no frames), in an idle. Await it in a task on the running loop."""
    future = asyncio.get_running_loop().create_future()

    def done(*_args):
        if not future.done():
            future.set_result(None)
        return GLib.SOURCE_REMOVE

    if widget.get_mapped():
        widget.add_tick_callback(done)
        GLib.timeout_add(FRAME_TIMEOUT_MS, done)
    else:
        GLib.idle_add(done)
    return future


def each_frame(widget, step):
    """Call step(), a bound method, at each of widget's frames (a tick callback: while it is
    mapped) until it answers false: work spread over frames a little at a time, such as a
    list's rows given to it a few a frame (grown()). step's object is held weakly, as
    connect_weak() holds it (the widget is its child), and the calls stop once it is freed.
    Returns the tick callback's id."""
    call = weak_method(step)
    return widget.add_tick_callback(lambda _widget, _clock: bool(call()))


# The rows a Gtk.ListView (or ColumnView) keeps whatever it shows: one for each item up to about
# this many; a Gtk.GridView keeps this many rows of its `max-columns` (gtk-notes.md).
LIST_ROWS_KEPT = 200
GRID_ROWS_KEPT = 30


def rows_kept(view):
    """About how many items `view`, a Gtk.ListView, ColumnView or GridView, makes a row or a
    tile for, however few of them show."""
    if isinstance(view, Gtk.GridView):
        return GRID_ROWS_KEPT * view.get_max_columns()
    return LIST_ROWS_KEPT


def grown(shown, total, step, kept):
    """How many of a list's `total` items to show next while it is given them `step` a frame,
    `shown` showing now: a view makes a row for each item up to `kept` (rows_kept()) whatever
    it shows, about half a millisecond a row, so `step` more until that, then all at once
    (the rows past it are never made)."""
    size = shown + step
    return total if size >= min(total, kept) else size


def holds_in_order(old, new):
    """Whether the list `new` holds every item of `old`, in the same order (a filter loosened:
    what the stricter text matched still matches, where it was)."""
    index, count = 0, len(old)
    if count > len(new):
        return False
    for item in new:
        if index == count:
            break
        if item == old[index]:
            index += 1
    return index == count


class GrowBack:
    """A list that shows a few items given the many it grows back to (a filter loosened from
    five albums back to three hundred) a few a frame, in place. A view makes a row for each
    item it gets up to the rows it keeps (rows_kept()), about a millisecond each, and keeps
    the row of an item that a change removes and puts back.

    start(old, new) makes the list `old` (what it shows) into `new`, when `new` holds all of
    `old` in order (holds_in_order(); False otherwise, and nothing is done): from the top,
    each change puts in the next `step` new items with the old ones among them, which keep
    their rows, `step` at once and `step` more at each of `view`'s frames, until the rest
    would be past the rows the view keeps, where it makes none: then the rest in one change.
    The old items that will be past those rows are taken out at once, at the end of the
    list: a row is laid out again whenever a change above moves it (six rows inserted above
    65 cost a frame three times what six at the end do), and theirs would go in the end.
    replace(position, removed, items) makes each change (a store's splice, a model's
    items_changed()). It is the owner's method, held weakly: the owner holds this object.
    """

    def __init__(self, view, replace, step):
        self._view = view.weak_ref()
        self._replace = weak_method(replace)
        self._step = step
        self._new = None  # the list it grows into, while it does
        self._old = None  # the list it showed
        self._done = 0  # new[:done] shows, then old[old_done:]
        self._old_done = 0
        self._tick = None  # the view's tick callback while it grows

    @property
    def pending(self):
        """Whether some items are still to come."""
        return self._new is not None

    def start(self, old, new):
        """Grow `old` into `new`: the first `step` new items now, the rest a few a frame.
        False when `new` does not hold `old` in order (an earlier growth goes on then)."""
        if not holds_in_order(old, new):
            return False
        self.stop()
        if len(new) == len(old):
            return True  # the same items
        view = self._view()
        kept = rows_kept(view) if view is not None else 0
        self._new, self._done = new, 0
        # The old items before position `kept` in new keep their rows; the rest go now.
        near = 0
        for item in new[:kept]:
            if near < len(old) and item == old[near]:
                near += 1
        self._old, self._old_done = old[:near], 0
        if near < len(old):
            self._replace(near, len(old) - near, [])
        if self._grow() and view is not None:
            self._tick = each_frame(view, self._on_frame)
        return True

    def finish(self):
        """Show everything still to come, now, in one change (the old items there keep their
        rows; the view makes the new ones' up to the rows it keeps)."""
        if self._new is not None:
            self._stop_ticking()
            self._rest()

    def stop(self):
        """Nothing more: the list stays as it is."""
        self._stop_ticking()
        self._new = self._old = None

    def _grow(self):
        """The next change; whether there are more to come."""
        view = self._view()
        if view is None or self._done >= rows_kept(view):
            self._rest()
            return False
        new, old = self._new, self._old
        end, old_end, added = self._done, self._old_done, 0
        while end < len(new) and added < self._step:
            if old_end < len(old) and new[end] == old[old_end]:
                old_end += 1
            else:
                added += 1
            end += 1
        if end == len(new):
            self._rest()
            return False
        start, removed = self._done, old_end - self._old_done
        self._done, self._old_done = end, old_end
        self._replace(start, removed, new[start:end])
        return True

    def _rest(self):
        new, start, removed = self._new, self._done, len(self._old) - self._old_done
        self._new = self._old = None
        self._replace(start, removed, new[start:])

    def _on_frame(self):
        if self._new is not None and self._grow():
            return True
        self._tick = None  # answering False removes the tick callback
        return False

    def _stop_ticking(self):
        view = self._view()
        if self._tick is not None and view is not None:
            view.remove_tick_callback(self._tick)
        self._tick = None


class HeaderTitle:
    """A page's title in its header bar exactly when the page's own big title (a `title-1`
    label in its content) is not in view: while the content shows a spinner or a status page
    instead, or once the title has scrolled away. The header then always names the page, and
    never twice.

        self._header_title = HeaderTitle(self.header_bar, self.title_label, scrolled_window)

    update() looks again (the page calls it when its content changes: a stack switched, the
    title moved); scrolling `scrolled_window` (any of them, for a page with several) and the
    title mapping and unmapping look again by themselves. The header bar is changed only
    when the answer flips. hold(True) shows the header's title whatever the answer (a list's
    selection mode puts its count there), hold(False) the answer again.
    """

    def __init__(self, header_bar, title_label, *scrolled_windows):
        self._header_bar = header_bar
        self._title_label = title_label
        self._shown = None
        self._held = False
        self._painted = None  # (the frame clock, the after-paint handler) while waiting
        for scrolled_window in scrolled_windows:
            connect_weak(scrolled_window.get_vadjustment(), 'value-changed', self._on_moved)
        connect_weak(title_label, 'map', self._on_moved)
        connect_weak(title_label, 'unmap', self._on_moved)
        self.update()

    def _on_moved(self, *_args):
        self.update()
        clock = self._title_label.get_frame_clock()
        if self._painted is not None and self._painted[0] is not clock:
            self._stop_waiting()
        if clock is not None and self._painted is None:
            # Again once the frame has been laid out and painted: a title just mapped has no
            # size yet, and the grid's moves only as it is allocated (a frame's ticks come
            # before its layout).
            self._painted = (clock, connect_weak(clock, 'after-paint', self._after_paint))

    def _after_paint(self, _clock):
        if self.update():
            self._stop_waiting()

    def _stop_waiting(self):
        if self._painted is not None:
            clock, handler = self._painted
            if clock.handler_is_connected(handler):
                clock.disconnect(handler)
            self._painted = None

    def update(self):
        """Show the title in the header bar or not; False when the title is not laid out
        yet, and nothing was changed."""
        label = self._title_label
        in_view = label.get_mapped() and label.get_label() != ''
        if in_view:
            if label.get_height() <= 0:
                return False
            root = label.get_native()
            found, bounds = label.compute_bounds(root) if root is not None else (False, None)
            # What clips it: the scrolled window it scrolls in, or the parent it is laid
            # over (the grid's title, an overlay moved up as the grid scrolls).
            clip = label.get_ancestor(Gtk.ScrolledWindow) or label.get_parent()
            if found and clip is not None:
                found_top, top = clip.compute_bounds(root)
                if found_top:
                    in_view = bounds.get_y() + bounds.get_height() > top.get_y()
        show = not in_view
        if show != self._shown:
            self._shown = show
            if not self._held:
                self._header_bar.set_show_title(show)
        return True

    def hold(self, held):
        """Show the header's title while `held`, whatever update() answers; the answer again
        once let go."""
        held = bool(held)
        if held == self._held:
            return
        self._held = held
        self._header_bar.set_show_title(True if held else bool(self._shown))


# The widget tree by class, for the few places that need a widget the toolkit does not hand
# out (a sidebar's rows, a page's toolbar view, the popover the focus is in).

def descendants(widget, cls):
    """The descendants of widget that are a cls, depth first (not looking inside them)."""
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, cls):
            yield child
        else:
            yield from descendants(child, cls)
        child = child.get_next_sibling()


def first_descendant(widget, cls):
    """The first descendant of widget (depth first, itself included) that is a cls, or
    None."""
    if isinstance(widget, cls):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = first_descendant(child, cls)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def has_ancestor(widget, cls):
    """Whether widget is, or is inside, a cls (a popover: its keys are the menu's)."""
    while widget is not None:
        if isinstance(widget, cls):
            return True
        widget = widget.get_parent()
    return False


def focus_position(view, position):
    """The keyboard focus on the row or tile at `position` of view (a Gtk.ListView,
    GridView or ColumnView), scrolled into view. scroll_to(FOCUS) focuses the item only when
    the focus is in the view already; from elsewhere (a header bar, an entry, the sidebar) it
    only moves the view's own focus item there, which the view's grab_focus() then focuses.
    The view's grab alone would focus the widget it last focused, which the view may have
    recycled for another item since and scrolled out of view (gtk-notes.md)."""
    if isinstance(view, Gtk.ColumnView):
        view.scroll_to(position, None, Gtk.ListScrollFlags.FOCUS, None)
    else:
        view.scroll_to(position, Gtk.ListScrollFlags.FOCUS, None)
    root = view.get_root()
    focus = root.get_focus() if root is not None else None
    if focus is None or focus is view or not focus.is_ancestor(view):
        view.grab_focus()
