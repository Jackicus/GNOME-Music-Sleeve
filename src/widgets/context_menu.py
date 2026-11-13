# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Context menus and track drags for the items of a view: a Gtk.GridView, Gtk.ListView or
Gtk.ColumnView of tiles or rows, a Gtk.FlowBox or Gtk.ListBox, or a single widget.

    context_menu.attach(view)              # menus on right-click, long-press, Menu, Shift+F10
    context_menu.attach(view, drag=True)   # and its items dragged (widgets/dnd.py)
    context_menu.set_drag_objects(view, objects)   # a drag of obj carries objects(obj), when
                                                   # not None (a selection: several rows)
    context_menu.popup(widget, obj, x, y)  # the menu for obj, at (x, y) in widget
    context_menu.attach_playing(area, source)   # the item playing's menu over an area
    context_menu.attach_playing_keys(widget, source)   # and on Menu, Shift+F10 in widget

A widget offering a menu has a `context_item` attribute: the Item or Track it shows, or None
(an unbound row), and `context_queued` true when that is an entry of the player's queue (the
player bar's item, Up Next's rows: a menu without Play, actions.build_menu), and
`context_queue_entry` its (index, id) there when Up Next may take it out (Remove from Up Next;
None otherwise), and `context_queue_moves` where it can go there (Move Up and the rest),
and `context_extra` a Gio.MenuModel section of its own the menu ends with (the player bar's
Mini Player).
The controllers
sit on the view, not on each recycled tile: the right click and the long press in the capture
phase, so they come before the rows' own click gestures (which would select or activate), the
shortcuts for the focused row. What was pressed is found by picking the widget under the
pointer and going up to the one with a context_item, or, from a row or tile of the view (a
list item, a column view's row, a FlowBoxChild), down into it: a click on a Songs row's album
column finds its title cell.

The menu is the window's (window.item_actions.menu_for(obj): see actions.py), shown in a
Gtk.PopoverMenu parented to that widget, without an arrow, pointing at the pointer, or beside
the widget from the keyboard; it is unparented once closed (after an idle: its action is
activated after it closes, and looks the window's actions up through its parent). Before it
is, a focus still in the menu goes back to the row or tile it was opened for, or to its
list when a change has taken that row away or given it another item: GTK would give it back
only after the next frame, walking up from the popover's parent, which the idle may have
unparented by then. The row or tile whose menu is open is marked `.has-open-popup`
meanwhile, as GTK's own menus mark theirs, so it stays highlighted while the pointer is in
the menu. The sidebar's playlist
and folder rows open theirs through popup() too (sidebar_view.py).

The Now Playing sheet and the full-screen player show the item playing over areas of their
own (the artwork, the titles, the lyrics) rather than in rows: attach_playing() gives such
an area the item's menu (its `source`'s context_item, the menu their More Options shows) on
a right click or a long press, at the pointer, but over a control or a selectable label,
which keep their own (a slider, a button, the unsynced lyrics' Copy). The long press claims
the touch, so a lyric line pressed long opens the menu and does not also seek; a click
still seeks. attach_playing_keys() opens it on Menu and Shift+F10 from anywhere in a widget,
beside the focus, as the player bar's keys do, unless the focus's own list has menus of its
own (Up Next's rows: their view's shortcut is reached first). Both hold `source` by a
GObject weak reference, so a sheet or a player dropped is freed with its controllers.
"""

from gettext import ngettext

from gi.repository import Gdk, Gio, GLib, Graphene, Gtk

from .. import shortcuts
from ..library import ItemRefs, Track
from . import dnd

# The containers whose children are rows or tiles.
LIST_TYPES = (Gtk.ListBase, Gtk.FlowBox, Gtk.ListBox)

# The keys that open the focused item's menu, as a Gtk.ShortcutTrigger string: the
# shortcuts table's alternatives, which the Keyboard Shortcuts dialog lists.
MENU_KEYS = '|'.join(shortcuts.CONTEXT_MENU.split())


def context_object(widget):
    return getattr(widget, 'context_item', None)


def _descendant(widget):
    """The first visible widget under `widget` (itself included) with a context_item, and
    that item: (widget, obj) or None."""
    obj = context_object(widget)
    if obj is not None:
        return widget, obj
    child = widget.get_first_child()
    while child is not None:
        if child.get_visible() and not isinstance(child, Gtk.Popover):
            found = _descendant(child)
            if found is not None:
                return found
        child = child.get_next_sibling()
    return None


def find(view, widget):
    """(widget, obj) for what `widget` (picked in `view`, or focused there) belongs to: it or
    its nearest ancestor with a context_item, or what the row or tile holding it holds. None
    when it is none of the view's items (the view's background, a page's hero)."""
    while widget is not None and widget is not view:
        obj = context_object(widget)
        if obj is not None:
            return widget, obj
        parent = widget.get_parent()
        if isinstance(parent, LIST_TYPES):  # a row or tile of a list: what it holds
            return _descendant(widget)
        widget = parent
    if widget is view:
        obj = context_object(view)
        if obj is not None:
            return view, obj
    return None


def focused(view, focus):
    """The Item or Track of view's row or tile that has the keyboard focus (`focus`, the
    window's focus widget), or None: the focus elsewhere, or on none of the view's items."""
    if focus is None or not (focus is view or focus.is_ancestor(view)):
        return None
    found = find(view, focus)
    if found is None and focus is not view:
        found = _descendant(focus)
    return found[1] if found is not None else None


def owner(widget):
    """The row or tile of a list that holds widget (widget itself when it is one): the
    child of a LIST_TYPES container; None when widget is in no list."""
    while widget is not None:
        if isinstance(widget.get_parent(), LIST_TYPES):
            return widget
        widget = widget.get_parent()
    return None


def popup(widget, obj, x=None, y=None, queued=None, owner_widget=None):
    """Show the menu for obj in a popover parented to widget, pointing at (x, y) in its
    coordinates, or at the whole widget; `queued` and the queue entry as the widget with the
    menu (`owner_widget`, else widget) says (`context_queued`, `context_queue_entry`) unless
    given. The popover, or None when obj has no menu."""
    actions = getattr(widget.get_root(), 'item_actions', None)
    source = owner_widget if owner_widget is not None else widget
    if queued is None:
        queued = bool(getattr(source, 'context_queued', False))
    entry = getattr(source, 'context_queue_entry', None)
    moves = getattr(source, 'context_queue_moves', None)
    menu = (actions.menu_for(obj, queued=queued, queue_entry=entry, queue_moves=moves)
            if actions is not None else None)
    extra = getattr(source, 'context_extra', None)
    if extra is not None and extra.get_n_items():
        if menu is None:
            menu = Gio.Menu()
        menu.append_section(None, extra)
    if menu is None:
        return None
    popover = Gtk.PopoverMenu.new_from_model(menu)
    popover.set_has_arrow(False)
    popover.set_parent(widget)
    if x is not None and y is not None:
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rectangle)
        popover.set_halign(Gtk.Align.START)  # the menu opens from the pointer
    marked = owner(widget)
    if marked is not None:
        marked.add_css_class('has-open-popup')
    view = marked.get_parent() if marked is not None else None
    home = (widget.get_root(), source, obj, view)
    popover.connect('closed', _on_closed, marked, home)
    popover.popup()
    return popover


def _on_closed(popover, marked, home):
    if marked is not None:
        marked.remove_css_class('has-open-popup')
    GLib.idle_add(_unparent, popover, home)


def _unparent(popover, home=None):
    if home is not None:
        give_focus_back(popover, *home)
    if popover.get_parent() is not None:
        popover.unparent()
    return GLib.SOURCE_REMOVE


def _same(obj, other):
    """Whether two context objects are the same item (a queue row makes a new Track each
    time it is asked)."""
    if obj is other:
        return True
    if obj is None or other is None or type(obj) is not type(other):
        return False
    key = getattr(obj, 'id', None)
    return key is not None and key == getattr(other, 'id', None)


def give_focus_back(popover, root, source, obj, view):
    """A closed menu's focus, when it is still in the menu (or nowhere), back where the menu
    was opened: the first widget from the popover's parent up that takes it, as GTK does,
    while `source` (the row or tile it was opened for) is still in the window showing
    `obj`; else its list `view` (its own focus item). Nothing when the focus has moved on
    (the chosen item's action took it elsewhere)."""
    if root is None:
        return
    focus = root.get_focus()
    if focus is not None and focus is not popover and not focus.is_ancestor(popover):
        return
    parent = popover.get_parent()
    if (parent is not None and parent.get_root() is root and source.get_mapped()
            and _same(context_object(source), obj)):
        while parent is not None:
            if parent.get_visible() and parent.grab_focus():
                return
            parent = parent.get_parent()
    if view is not None and view.get_root() is root and view.get_mapped():
        view.grab_focus()


def _popup_at(view, x, y):
    """The menu for what is at (x, y) in view: True when there was one."""
    found = find(view, view.pick(x, y, Gtk.PickFlags.DEFAULT))
    if found is None:
        return False
    widget, obj = found
    point = Graphene.Point()
    point.x, point.y = x, y
    ok, local = view.compute_point(widget, point)
    if not ok:
        return False
    return popup(widget, obj, local.x, local.y) is not None


def _on_pressed(gesture, _n_press, x, y):
    if _popup_at(gesture.get_widget(), x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)


def _on_long_pressed(gesture, x, y):
    if _popup_at(gesture.get_widget(), x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)


def popup_focused(view):
    """The menu for the row or tile of view with the keyboard focus: True when there was
    one (Menu, Shift+F10)."""
    focus = view.get_root().get_focus() if view.get_root() is not None else None
    if focus is None or not (focus is view or focus.is_ancestor(view)):
        return False
    found = find(view, focus)
    if found is None and (focus is not view or not isinstance(view, LIST_TYPES)):
        found = _descendant(focus)  # the focused row's item, or a single widget's (the bar)
    if found is None:
        return False
    widget, obj = found
    # A button inside the widget with the menu (the player bar's): the menu hangs from it,
    # and the focus goes back to it when the menu closes.
    anchor = focus if focus is not widget and focus.is_ancestor(widget) else widget
    return popup(anchor, obj, owner_widget=widget) is not None


def _on_menu_key(view, _arguments):
    return popup_focused(view)


# What keeps its own right click and long press over the item playing: the controls, and a
# selectable label (its Copy menu).
OWN_PRESS = (Gtk.Button, Gtk.MenuButton, Gtk.ScaleButton, Gtk.Range, Gtk.Switch,
             Gtk.CheckButton, Gtk.DropDown, Gtk.Editable)


def keeps_own_press(area, widget):
    """Whether `widget` (picked in `area`) is, or is inside, something under `area` that
    keeps its own right click and long press (OWN_PRESS, a selectable label)."""
    while widget is not None and widget is not area:
        if isinstance(widget, OWN_PRESS) or (isinstance(widget, Gtk.Label)
                                             and widget.get_selectable()):
            return True
        widget = widget.get_parent()
    return False


def _playing_item(source_ref):
    source = source_ref()
    return (source, getattr(source, 'context_item', None)) if source is not None else (None, None)


def _popup_playing(source, area, obj, x=None, y=None):
    """The item playing's menu (obj, a queued one: no Play) in a popover parented to
    `area`, the focus given back as from `source` (context_menu.give_focus_back); `source`
    told of it (its context_menu_opened(popover), when it has one). The popover, or None."""
    popover = popup(area, obj, x, y, queued=True, owner_widget=source)
    opened = getattr(source, 'context_menu_opened', None)
    if popover is not None and opened is not None:
        opened(popover)
    return popover


def attach_playing(area, source):
    """A right click or a long press over `area` opens the menu of the item `source`
    plays (its context_item; nothing while it is None) at the pointer, but over a control
    or a selectable label (keeps_own_press()). Both claim the press, before the area's own
    gestures (a lyric line's seek). `source` is held weakly."""
    source_ref = source.weak_ref()

    def pressed(gesture, x, y):
        area = gesture.get_widget()
        source, obj = _playing_item(source_ref)
        if obj is None or keeps_own_press(area, area.pick(x, y, Gtk.PickFlags.DEFAULT)):
            return
        if _popup_playing(source, area, obj, x, y) is not None:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY,
                             propagation_phase=Gtk.PropagationPhase.CAPTURE)
    click.connect('pressed', lambda gesture, _n_press, x, y: pressed(gesture, x, y))
    area.add_controller(click)
    press = Gtk.GestureLongPress(touch_only=True, propagation_phase=Gtk.PropagationPhase.CAPTURE)
    press.connect('pressed', pressed)
    area.add_controller(press)


def attach_playing_keys(widget, source):
    """Menu and Shift+F10 with the focus anywhere in `widget` open the menu of the item
    `source` plays, beside the focused widget, as popup_focused() does the bar's, unless
    something on the way has its own (Up Next's rows, a selectable label).
    `source` is held weakly."""
    source_ref = source.weak_ref()

    def activate(widget, _arguments):
        source, obj = _playing_item(source_ref)
        root = widget.get_root()
        focus = root.get_focus() if root is not None else None
        if obj is None or focus is None or not (focus is widget or focus.is_ancestor(widget)):
            return False
        return _popup_playing(source, focus, obj) is not None

    keys = Gtk.ShortcutController()
    keys.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(MENU_KEYS),
                                       Gtk.CallbackAction.new(activate)))
    widget.add_controller(keys)


def drag_refs(obj):
    """What a drag of obj carries: a library.ItemRefs of it (a track or a song or video by its
    own id, an album, playlist, folder or station Item), with a track's list as its
    origin; None for what cannot be dragged."""
    play = obj.play if isinstance(obj, Track) else {}
    origin = (play.get('kind'), play.get('id')) if play.get('kind') and play.get('id') else None
    return ItemRefs.for_objects([obj], origin)


def set_drag_objects(view, objects):
    """What a drag from view carries: objects(obj) for the item obj pressed, a list of
    Tracks in order (a selection's, widgets/selection_mode.py), or None for obj alone.
    `objects` is held by the view: pass one that does not hold the view's page
    (weak_method())."""
    view._drag_objects = objects


def drag_refs_of(objects):
    """What a drag of several tracks carries (a selection's): their library.ItemRefs, with
    the list of the first as the origin (so it is never taken for one song's reorder: that
    is a drag of one); None when none can be dragged."""
    play = objects[0].play if objects and isinstance(objects[0], Track) else {}
    origin = (play.get('kind'), play.get('id')) if play.get('kind') and play.get('id') else None
    return ItemRefs.for_objects(objects, origin)


def _drag_finder(view):
    """attach_source()'s find for view: what is under (x, y) and its widget as the icon (a
    selection's several, with their count as the icon instead). It holds the view by a
    GObject weak reference (a page that can be dropped owns it)."""
    view_ref = view.weak_ref()

    def found(x, y):
        view = view_ref()
        hit = find(view, view.pick(x, y, Gtk.PickFlags.DEFAULT)) if view is not None else None
        if hit is None:
            return None
        widget, obj = hit
        objects = getattr(view, '_drag_objects', None)
        several = objects(obj) if objects is not None else None
        if several and len(several) > 1:
            refs = drag_refs_of(several)
            return (refs, widget, songs_label(len(refs))) if refs is not None else None
        refs = drag_refs(obj)
        return (refs, widget) if refs is not None else None

    return found


def songs_label(count):
    """A drag of several songs' icon: "3 Songs"."""
    return ngettext('{count} Song', '{count} Songs', count).format(count=f'{count:n}')


def attach(view, drag=False):
    """Give view's items context menus (and, with drag, make them draggable: a track onto a
    sidebar playlist, a playlist or folder onto a sidebar folder, as widgets.dnd's
    library.ItemRefs). Once per view: attaching again does nothing."""
    if getattr(view, '_context_menu_attached', False):
        return
    view._context_menu_attached = True

    click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY,
                             propagation_phase=Gtk.PropagationPhase.CAPTURE)
    click.connect('pressed', _on_pressed)
    view.add_controller(click)

    press = Gtk.GestureLongPress(touch_only=True, propagation_phase=Gtk.PropagationPhase.CAPTURE)
    press.connect('pressed', _on_long_pressed)
    view.add_controller(press)

    keys = Gtk.ShortcutController()
    keys.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(MENU_KEYS),
                                       Gtk.CallbackAction.new(_on_menu_key)))
    view.add_controller(keys)

    if drag:
        dnd.attach_source(view, _drag_finder(view), Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
