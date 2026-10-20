# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The window's own keys: which playback or Now Playing action a key press runs, given where
the focus is.

The playback keys (shortcuts.PLAYBACK: Space, Ctrl+Right, Ctrl+Left) are not application
accelerators: GTK 4 runs those in the window's capture phase, before the focus widget, so a
bare Space would fire while typing in the Songs filter and Ctrl+Left would skip a track
instead of a word. The window's capture-phase key controller asks playback_action() instead,
which leaves the keys to the widgets whose keys they are, and the window activates the
action it names. The decision takes plain values (the focus widget's class, not the widget),
so tests/test_keyboard.py checks it without a display. The keys that open Now Playing on
a tab (shortcuts.NOW_PLAYING_TABS: Ctrl+Shift+L, Ctrl+Shift+U, Unicode entry in a text
field) are the window's own for the same reason, and tab_action() decides them alike.

    name = playback_action(keyval, mods, type(focus), dialog_open, in_popover, enabled)
    name = tab_action(keyval, mods, type(focus), dialog_open, in_popover, enabled)
    step = move_step(keyval, mods, type(focus), dialog_open, in_popover)   # -1, 1 or None
    step = volume_step(keyval, mods, type(focus), dialog_open, in_popover)  # -1, 1 or None
    name = selection_key(keyval, mods, type(focus), dialog_open, in_popover, active, on_row)

move_step() is a playlist page's (pages/detail.py): Alt+Up or Alt+Down (shortcuts.MOVE_UP,
MOVE_DOWN) moves the focused song one place, on the same terms. volume_step() is the
window's: Ctrl+Up or Ctrl+Down (shortcuts.VOLUME_UP, VOLUME_DOWN) steps the volume, except
where those keys are the focused widget's own (VOLUME_OWNERS). selection_key() is a track
list's selection mode's (widgets/selection_mode.py), asked by the window before the playback
keys, so that in the mode Space on a song selects it rather than playing or pausing.

    target = search_target(page)   # 'filter' or 'search': where Ctrl+F goes

Ctrl+F is an accelerator (win.search), which a library page with a filter takes for its
filter bar (widgets/filter_bar.py), and any other page leaves to the Search page.
"""

from gi.repository import Gdk, Gtk

from . import shortcuts


def parse_keys(table):
    """{(keyval, modifiers): action} for a table of action -> accelerator strings."""
    keys = {}
    for name, accels in table.items():
        for accel in accels:
            ok, keyval, mods = Gtk.accelerator_parse(accel)
            if ok:
                keys[(keyval, int(mods))] = name
    return keys


# The playback keys, by (keyval, modifiers) -> app action.
PLAYBACK_KEYS = parse_keys(shortcuts.PLAYBACK)

# The keys that open Now Playing on a tab, by (keyval, modifiers) -> window action.
TAB_KEYS = parse_keys(shortcuts.NOW_PLAYING_TABS)

# The keys that move a playlist's focused song, by (keyval, modifiers) -> the step (the
# keypad's arrows too).
MOVE_KEYS = parse_keys({-1: (shortcuts.MOVE_UP, '<alt>KP_Up'),
                        1: (shortcuts.MOVE_DOWN, '<alt>KP_Down')})

# The volume keys, by (keyval, modifiers) -> the step (the keypad's arrows too).
VOLUME_KEYS = parse_keys({-1: (shortcuts.VOLUME_DOWN, '<primary>KP_Down'),
                          1: (shortcuts.VOLUME_UP, '<primary>KP_Up')})

# A track list's selection mode's keys, by (keyval, modifiers) -> what they do (the keypad's
# Space too).
SELECTION_KEYS = parse_keys({
    'toggle': (shortcuts.SELECT_TOGGLE, 'KP_Space'),
    'extend': (shortcuts.SELECT_RANGE, '<shift>KP_Space'),
    'select-all': (shortcuts.SELECT_ALL,),
    'select-none': (shortcuts.SELECT_NONE,),
    'leave': (shortcuts.LEAVE_SELECTION,),
})

# The primary menu's key (F10), which the window handles itself when the button is hidden.
MAIN_MENU_KEY = Gtk.accelerator_parse(shortcuts.MAIN_MENU)[1:]

# Where a key is the focused widget's own, whatever it is: an entry or a text view.
TYPING = (Gtk.Editable, Gtk.TextView)
# Where Space is the widget's own key, as GTK and the HIG have it: Space presses a button
# (a toggle button, a menu button's, a drop-down's or a scale button's inner button and a
# toggle group's toggles are buttons too), flips a switch or a check box, and activates a
# boxed list's row. Space plays or pauses only on what does nothing with it: a tile, a list
# item, the seek slider, or no focus at all.
SPACE_OWNERS = (Gtk.Button, Gtk.Switch, Gtk.CheckButton, Gtk.ListBoxRow)
SPACE_KEYS = (Gdk.KEY_space, Gdk.KEY_KP_Space)
# Where Ctrl+Up and Ctrl+Down are the widget's own, beside TYPING (a text view's paragraph
# keys): a slider's (the seek slider's page step) and a boxed list's row's (the sidebar's,
# where they move the focus without selecting, so without showing the page). The grids and
# lists select nothing (Gtk.NoSelection), so there they only move the focus as Up and Down
# do, and the volume keys take them.
VOLUME_OWNERS = (Gtk.Range, Gtk.ListBoxRow)


def playback_action(keyval, mods, focus_type, dialog_open, in_popover, enabled):
    """The app action (without "app.") that a key press runs, or None when the key is not
    a playback key or belongs to something else: the focus widget (`focus_type`, its class,
    or type(None) with no focus) when it is typed into (TYPING), or for Space when it owns
    Space (SPACE_OWNERS); a dialog open over the window; a popover (a menu) the focus is
    in; the action itself when it is not enabled (`enabled(name)`: nothing plays)."""
    return _key_action(PLAYBACK_KEYS, keyval, mods, focus_type, dialog_open, in_popover,
                       enabled)


def tab_action(keyval, mods, focus_type, dialog_open, in_popover, enabled):
    """The window action (without "win.") that a key press runs to show a Now Playing tab
    (TAB_KEYS), or None, on playback_action()'s terms: not while typing, in a dialog or a
    popover, or with the action disabled."""
    return _key_action(TAB_KEYS, keyval, mods, focus_type, dialog_open, in_popover, enabled)


def _key_action(keys, keyval, mods, focus_type, dialog_open, in_popover, enabled):
    # A press with Shift held reports the capital (Ctrl+Shift+L is L); the tables hold
    # what Gtk.accelerator_parse makes of '<shift>l', the small letter.
    name = keys.get((Gdk.keyval_to_lower(keyval), int(mods)))
    if name is None:
        return None
    if dialog_open or in_popover:
        return None
    if issubclass(focus_type, TYPING):
        return None
    if keyval in SPACE_KEYS and issubclass(focus_type, SPACE_OWNERS):
        return None
    if not enabled(name):
        return None
    return name


def move_step(keyval, mods, focus_type, dialog_open, in_popover):
    """How far a key press moves a playlist's focused song: -1 (Alt+Up), 1 (Alt+Down), or
    None for any other key, and while it is typed into, a dialog is open or the focus is in
    a popover, as for the playback keys."""
    step = MOVE_KEYS.get((keyval, int(mods)))
    if step is None or dialog_open or in_popover or issubclass(focus_type, TYPING):
        return None
    return step


def volume_step(keyval, mods, focus_type, dialog_open, in_popover):
    """Which way a key press steps the volume: 1 (Ctrl+Up), -1 (Ctrl+Down), or None for any
    other key, and while the focus is typed into (TYPING) or owns the keys (VOLUME_OWNERS), a
    dialog is open or the focus is in a popover (the volume's own slider is in one)."""
    step = VOLUME_KEYS.get((keyval, int(mods)))
    if step is None or dialog_open or in_popover:
        return None
    if issubclass(focus_type, TYPING) or issubclass(focus_type, VOLUME_OWNERS):
        return None
    return step


def selection_key(keyval, mods, focus_type, dialog_open, in_popover, active, on_row):
    """What a key press does in a track list's selection mode (SELECTION_KEYS: 'toggle',
    'extend', 'select-all', 'select-none', 'leave'), or None for the key to go on as usual:
    `active`, the focused page's list is in its mode; `on_row`, the focus is on one of its
    songs. Space and Shift+Space only on a song in the mode (a focused button keeps Space,
    and outside the mode it plays or pauses); Ctrl+A in the mode, or on a song (it starts
    the mode); Ctrl+Shift+A and Escape in the mode only. Never while the focus is typed into
    (Ctrl+A selects the text, Escape closes the filter first), a dialog is open or the focus
    is in a popover."""
    name = SELECTION_KEYS.get((Gdk.keyval_to_lower(keyval), int(mods)))
    if name is None or dialog_open or in_popover or issubclass(focus_type, TYPING):
        return None
    if name in ('toggle', 'extend'):
        if not active or not on_row or issubclass(focus_type, SPACE_OWNERS):
            return None
    elif name == 'select-all':
        if not active and not on_row:
            return None
    elif not active:
        return None
    return name


def search_target(page):
    """Where Ctrl+F (win.search) puts the cursor from `page`, the page shown: 'filter', its
    own filter bar, when it has one with something to filter now (Songs, Albums, Artists,
    Music Videos, a playlist's songs: the page's focus_filter() shows it), else 'search',
    the Search page's entry (an album's page, Home, a page still loading)."""
    bar = getattr(page, 'filter_bar', None)
    if bar is not None and bar.available and hasattr(page, 'focus_filter'):
        return 'filter'
    return 'search'


def is_main_menu(keyval, mods):
    """Whether the key press is the primary menu's (F10, no modifiers)."""
    return (keyval, int(mods)) == MAIN_MENU_KEY
