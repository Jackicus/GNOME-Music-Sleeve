# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Drags and drops inside the app: what a drag carries, the drag in progress, and what a
drop target shows while a drag is over it. Every drag source and drop target of the app
goes through here, so they look and behave alike.

    provider(refs)            # a Gdk.ContentProvider of a library.ItemRefs
    current()                 # the ItemRefs of the in-app drag in progress, or None
    offered()                 # the Gdk.DragAction its source offers, or 0
    attach_source(widget, find, actions=Gdk.DragAction.COPY,
                  phase=Gtk.PropagationPhase.BUBBLE)
                              # a Gtk.DragSource on widget: find(x, y), in widget's
                              # coordinates, answers (refs, icon_widget) or None

    feedback = DropFeedback(scrolled=None, edge=EDGE)
    feedback.highlight(widget)       # widget marked as where the drop goes (None: unmarked)
    feedback.insert(row, after)      # an insertion line on row's top (after=False) or bottom
    feedback.motion(y)               # y in feedback.scrolled: auto-scroll near its edges
    feedback.clear()                 # nothing marked, no scrolling (leave, drop, drag end)

    scroll_step(y, height, edge=EDGE, speed=MAX_SPEED)   # px a frame: <0 up, >0 down, 0
    insertion_point(row_tops, row_heights, y)            # (index, after) of the gap at y
    choose_action(actions, preferred=COPY)               # the one action a target answers
    shift_held(selected, offered, modifiers)             # whether the drop is a Shift-drop
    modifiers(widget)                                    # the keyboard's modifiers now

The payload is library.ItemRefs, the app's one drag type: one or more library objects in
order (tracks, albums, playlists, folders, stations), with the list they came from.

Only drags that start in the app are taken: a drop target decides what a drop would do from
current(), the ItemRefs its source made, and not from the drop's value, which GTK loads only
asynchronously (and AdwSidebar's `drop-enter` is told nothing but the item hovered). A drag
from another application carries no ItemRefs, so no target here accepts it.

The look is style.css's: `.drop-highlight` (an inset accent ring and a tint, as libadwaita
marks a drop target, a little stronger) on what takes the drop, `.drop-before` and
`.drop-after` (a 2 px accent line inside the row's top or bottom edge) for where a reorder
puts it. Neither changes the row's size or margins (a list's rows never get a vertical
margin). A DropFeedback holds its widgets by GObject weak references and its auto-scroll's
tick callback holds it weakly, so a page that can be dropped may own one; clear() removes
the tick.
"""

from gi.repository import Gdk, Graphene, Gtk

from .util import weak_method

# How near a scrolled view's top or bottom edge a drag starts scrolling it, in pixels, and
# how fast it scrolls at the very edge, in pixels a frame.
EDGE = 32
MAX_SPEED = 12

HIGHLIGHT = 'drop-highlight'
BEFORE = 'drop-before'
AFTER = 'drop-after'
MARKS = (HIGHLIGHT, BEFORE, AFTER)

_current = None  # the ItemRefs of the drag that started in the app, while it lasts
_offered = 0  # the actions its source offers


def provider(refs):
    """The Gdk.ContentProvider a drag of `refs` (a library.ItemRefs) offers."""
    return Gdk.ContentProvider.new_for_value(refs)


def current():
    """The library.ItemRefs of the drag in progress that started in the app (a source made by
    attach_source()), or None: no drag, or one from elsewhere."""
    return _current


def offered():
    """The actions (Gdk.DragAction) the source of the in-app drag in progress offers, or 0."""
    return _offered if _current is not None else 0


def _set_current(refs, actions=Gdk.DragAction.COPY | Gdk.DragAction.MOVE):
    global _current, _offered
    _current = refs
    _offered = actions if refs is not None else 0


def choose_action(actions, preferred=Gdk.DragAction.COPY):
    """The one action a drop target answers a drag with, of `actions` (the drop's, which
    it must be among): `preferred` when it is there, else MOVE, else COPY; 0 for neither."""
    for action in (preferred, Gdk.DragAction.MOVE, Gdk.DragAction.COPY):
        if actions & action:
            return action
    return 0


def shift_held(selected, offered, modifiers):
    """Whether a drop was made with Shift held: the keyboard's `modifiers` say so, or the
    drop's `selected` action is MOVE while its source `offered` COPY too (GTK under X11 and
    the compositor under Wayland turn Shift into a move, and a drag's own key state may not
    reach the app)."""
    return (bool(modifiers & Gdk.ModifierType.SHIFT_MASK)
            or (selected == Gdk.DragAction.MOVE and bool(offered & Gdk.DragAction.COPY)))


def modifiers(widget):
    """The modifiers held on the keyboard of widget's display now (0 without one)."""
    seat = widget.get_display().get_default_seat()
    keyboard = seat.get_keyboard() if seat is not None else None
    return keyboard.get_modifier_state() if keyboard is not None else 0


def attach_source(widget, find, actions=Gdk.DragAction.COPY,
                  phase=Gtk.PropagationPhase.BUBBLE):
    """Make widget a drag source of library.ItemRefs. When a drag starts, find(x, y) (the
    pointer in widget's coordinates) answers (refs, icon_widget), or None when nothing there
    can be dragged; the icon is icon_widget as it looks, held at the pointer. Not from a
    touchscreen, where a drag scrolls (a long press opens the menu instead). While the drag
    lasts, current() is its refs. `phase` CAPTURE lets the source see the press before the
    widget's children's gestures (a row's click), which it cancels once the drag starts. The
    Gtk.DragSource.

    The source holds `find`: for a widget that can be dropped, pass a function that does not
    hold the widget (weak_method(), or one that finds it through a GObject weak reference).
    """
    source = Gtk.DragSource(actions=actions, propagation_phase=phase)
    prepared = [None]  # the refs prepare() found, for drag-begin

    def on_prepare(source, x, y):
        prepared[0] = None
        device = source.get_current_event_device()
        if device is not None and device.get_source() == Gdk.InputSource.TOUCHSCREEN:
            return None
        found = find(x, y)
        if not found:
            return None
        refs, icon_widget = found
        if refs is None:
            return None
        hot_x, hot_y = 0, 0
        owner = source.get_widget()
        if icon_widget is not None and owner is not None:
            point = Graphene.Point()
            point.x, point.y = x, y
            ok, local = owner.compute_point(icon_widget, point)
            if ok:
                hot_x, hot_y = int(local.x), int(local.y)
            source.set_icon(Gtk.WidgetPaintable.new(icon_widget), hot_x, hot_y)
        prepared[0] = refs
        return provider(refs)

    def on_begin(source, _drag):
        _set_current(prepared[0], source.get_actions())

    def on_end(_source, *_args):
        if _current is prepared[0]:
            _set_current(None)
        prepared[0] = None

    def on_cancel(source, *args):
        on_end(source)
        return False  # GTK's own animation of the icon going back

    source.connect('prepare', on_prepare)
    source.connect('drag-begin', on_begin)
    source.connect('drag-end', on_end)
    source.connect('drag-cancel', on_cancel)
    widget.add_controller(source)
    return source


def scroll_step(y, height, edge=EDGE, speed=MAX_SPEED):
    """How far a drag at y in a scrolled view `height` pixels tall scrolls it each frame: up
    (negative) within `edge` of the top, down within `edge` of the bottom, faster the nearer
    the edge (`speed` at it, or past it); 0 elsewhere, and in a view too short for both
    edges."""
    if height <= 2 * edge or edge <= 0:
        return 0.0
    if y < edge:
        return -speed * min(1.0, (edge - y) / edge)
    if y > height - edge:
        return speed * min(1.0, (y - (height - edge)) / edge)
    return 0.0


def insertion_point(row_tops, row_heights, y):
    """Where a drop at y goes among rows (their tops and heights, in order, in y's
    coordinates): (index, after), the row the line is drawn on and whether below it (after
    its middle) or above. Above the first row is (0, False), below the last (last, True);
    no rows is (-1, False)."""
    if not row_tops:
        return -1, False
    for index, (top, height) in enumerate(zip(row_tops, row_heights, strict=True)):
        if y < top + height:
            return index, y >= top + height / 2
    return len(row_tops) - 1, True


class DropFeedback:
    """What a drop target shows while a drag is over it: at most one mark at a time, a
    highlighted widget (highlight(): `.drop-highlight`) or an insertion line on a row
    (insert(): `.drop-before` or `.drop-after`), and auto-scroll of `scrolled` (a
    Gtk.ScrolledWindow, or None; it may be set again, as a sidebar's mode change builds
    another) while motion() places the pointer within `edge` pixels of its top or bottom.
    clear() takes the mark away and stops the scrolling: call it on leave, drop and drag
    end. See the module."""

    def __init__(self, scrolled=None, edge=EDGE):
        self.scrolled = scrolled
        self.edge = edge
        self._marked = None  # (a GObject weak reference to the widget, its class)
        self._step = 0.0
        self._tick = None  # (a weak reference to the widget ticking, the callback id)

    @property
    def scrolled(self):
        return self._scrolled() if self._scrolled is not None else None

    @scrolled.setter
    def scrolled(self, scrolled):
        self._scrolled = scrolled.weak_ref() if scrolled is not None else None

    def marked(self):
        """(widget, style class) of the mark shown, or None."""
        if self._marked is None:
            return None
        widget = self._marked[0]()
        return (widget, self._marked[1]) if widget is not None else None

    def _mark(self, widget, name):
        shown = self.marked()
        if shown is not None and shown == (widget, name):
            return
        self._unmark()
        if widget is not None:
            widget.add_css_class(name)
            self._marked = (widget.weak_ref(), name)

    def _unmark(self):
        shown = self.marked()
        if shown is not None:
            shown[0].remove_css_class(shown[1])
        self._marked = None

    def highlight(self, widget):
        """Mark widget as where the drop goes (None: nothing marked)."""
        self._mark(widget, HIGHLIGHT)

    def insert(self, widget, after):
        """Draw the insertion line on widget's bottom edge (`after`) or top edge."""
        self._mark(widget, AFTER if after else BEFORE)

    def motion(self, y):
        """The pointer at y in `scrolled`: scroll it while y is near an edge
        (scroll_step()), a frame at a time, until motion() moves it away or clear()."""
        scrolled = self.scrolled
        self._step = scroll_step(y, scrolled.get_height(), self.edge) if scrolled else 0.0
        if self._step and self._tick is None:
            self._tick = (scrolled.weak_ref(),
                          scrolled.add_tick_callback(weak_method(self._on_tick)))
        elif not self._step:
            self._stop()

    def _on_tick(self, scrolled, _clock):
        adjustment = scrolled.get_vadjustment()
        top = adjustment.get_lower()
        bottom = adjustment.get_upper() - adjustment.get_page_size()
        value = min(max(adjustment.get_value() + self._step, top), max(top, bottom))
        adjustment.set_value(value)
        if not self._step or value in (top, bottom):
            self._tick = None
            return False
        return True

    def _stop(self):
        if self._tick is not None:
            widget = self._tick[0]()
            if widget is not None:
                widget.remove_tick_callback(self._tick[1])
            self._tick = None
        self._step = 0.0

    def clear(self):
        """No mark and no scrolling."""
        self._unmark()
        self._stop()
