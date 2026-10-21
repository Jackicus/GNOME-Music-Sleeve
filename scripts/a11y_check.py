#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Walk the keyboard checklist and list unnamed widgets, with no one at the keyboard.

    scripts/a11y_check.py [--size WxH] [--light] [--names] [--emulate-keys] [--step radio]

Runs the installed build (meson install -C build, or scripts/run.sh, first) on the demo
library, as screenshot.py --demo does (scripts/harness.py: memory settings, animations off,
no engine), and walks the
keyboard walkthrough in docs/accessibility.md key by key, printing PASS or FAIL for each step;
the exit status is 1 when a step fails. Use --size 360x640 for the narrow layout, and
--step radio to walk the Radio page's steps alone (to repeat them).

Under scripts/headless.sh the keys are real: scripts/remote_keys.py opens a session on the
headless mutter's org.gnome.Mutter.RemoteDesktop and injects them as a keyboard would, so the
window is active and nothing about the walkthrough is emulated — typing included. With
--emulate-keys, or where that interface is not on the session bus, each press is dispatched
through GTK's own handlers instead (press()): the capture-phase key and shortcut
controllers from the window down to the focus widget (the window's playback keys, the
application's accelerators, the mnemonics a dialog's shortcut manager runs on its labels),
then the shortcut controllers from the focus widget up to the window (the widgets' own keys:
Tab, the arrows, Enter, Escape, the context-menu keys) and a popover's own key handler; typing
is not emulated (the text is set), and the steps that need an active window are left out.
Step 8 of the walkthrough (a dialog over the window) runs with the window maximized, where a
dialog is inside it, and the window is made its --size again afterwards.

--names also starts a private accessibility bus (a dbus-daemon with at-spi's configuration on
an abstract socket, and at-spi2-registryd, stopped when the script exits, however it exits;
nothing on the desktop's own buses) and, on each page, lists the focusable controls that
have no accessible name, as libatspi reads them: what Orca would find, and what the GTK
inspector's Accessibility tab shows. Anything listed there is a gap (libadwaita's own
widgets included).
"""

import argparse
import asyncio
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import harness

parser = argparse.ArgumentParser()
parser.add_argument('--size', default='1100x760')
parser.add_argument('--light', action='store_true')
parser.add_argument('--names', action='store_true',
                    help='list focusable controls without an accessible name (libatspi)')
parser.add_argument('--emulate-keys', action='store_true',
                    help="dispatch each press through GTK's handlers instead of sending a real "
                         "key through the compositor's RemoteDesktop interface")
parser.add_argument('--step', choices=['radio'],
                    help='walk that step alone, from the window as it opens')
parser.add_argument('--dump', action='store_true', help=argparse.SUPPRESS)  # the lister
args = parser.parse_args()

# Where distributions put at-spi's registry daemon and its bus configuration.
REGISTRYD = ('/usr/libexec/at-spi2-registryd', '/usr/lib/at-spi2-registryd',
             '/usr/lib/at-spi2-core/at-spi2-registryd')
BUS_CONFIGS = ('/usr/share/defaults/at-spi2/accessibility.conf',
               '/etc/at-spi2/accessibility.conf')
REGISTRY_NAME = 'org.a11y.atspi.Registry'

# Roles whose focusable objects need a name of their own.
NAMED_ROLES = {'push button', 'toggle button', 'check box', 'slider', 'spin button',
               'combo box', 'menu item', 'list item', 'table row', 'text', 'entry', 'switch',
               'radio button', 'link', 'page tab', 'table cell', 'button', 'tree item'}


def list_unnamed():
    """--dump: print the app's showing, focusable, sensitive objects with a role in
    NAMED_ROLES and no name, one per line (role and path), from the bus in the environment."""
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    apps = [desktop.get_child_at_index(i) for i in range(desktop.get_child_count())]
    app = next((a for a in apps if a is not None and a.get_name() == 'a11y_check'), None)
    if app is None:
        sys.exit('a11y_check: the app is not on the accessibility bus')

    def walk(obj, path):
        states = obj.get_state_set()
        if path and not states.contains(Atspi.StateType.SHOWING):
            return
        role = obj.get_role_name()
        if (role in NAMED_ROLES and not obj.get_name()
                and states.contains(Atspi.StateType.FOCUSABLE)
                and states.contains(Atspi.StateType.SENSITIVE)):
            print(f'{role} in {" > ".join(path[-3:])}')
        label = f'{role} {obj.get_name()!r}' if obj.get_name() else role
        for i in range(obj.get_child_count()):
            child = obj.get_child_at_index(i)
            if child is not None:
                walk(child, path + [label])

    walk(app, [])


if args.dump:
    list_unnamed()
    sys.exit(0)



def stop(process):
    """End a daemon this script started: SIGTERM, then SIGKILL after 5 s."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def start_daemon(argv, **kwargs):
    """Start a daemon, stopped when this script exits (atexit: also after an exception or
    sys.exit())."""
    process = subprocess.Popen(argv, **kwargs)
    atexit.register(stop, process)
    return process


def wait_for_name(address, name, timeout=5.0):
    """Whether `name` gets an owner on the bus at address within timeout seconds."""
    from gi.repository import Gio, GLib

    connection = Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reply = connection.call_sync(
                'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'NameHasOwner', GLib.Variant('(s)', (name,)), GLib.VariantType('(b)'),
                Gio.DBusCallFlags.NONE, 1000, None)
            if reply.unpack()[0]:
                return True
            time.sleep(0.05)
        return False
    finally:
        connection.close_sync(None)


def start_accessibility_bus():
    """A private accessibility bus (dbus-daemon with at-spi's configuration listening on an
    abstract socket, and at-spi2-registryd on it), set as AT_SPI_BUS_ADDRESS, which GTK and
    libatspi take over the desktop's: nothing here touches the session."""
    registryd = next((path for path in REGISTRYD if os.access(path, os.X_OK)), None)
    if registryd is None:
        sys.exit('a11y_check: --names needs at-spi2-registryd (looked in '
                 + ', '.join(REGISTRYD) + ')')
    source = next((path for path in BUS_CONFIGS if os.path.exists(path)), None)
    if source is None:
        sys.exit("a11y_check: --names needs at-spi's accessibility.conf (looked in "
                 + ', '.join(BUS_CONFIGS) + ')')
    if shutil.which('dbus-daemon') is None:
        sys.exit('a11y_check: --names needs dbus-daemon')
    with open(source, encoding='utf-8') as file:
        text = file.read()
    listen = f'<listen>unix:abstract=apple-music-a11y-check-{os.getpid()}</listen>'
    config_text = re.sub(r'<listen>.*?</listen>', listen, text, count=1, flags=re.S)
    if config_text == text:
        sys.exit(f'a11y_check: no <listen> element to replace in {source}')
    with tempfile.TemporaryDirectory(prefix='a11y-check-') as config_dir:
        config = os.path.join(config_dir, 'accessibility.conf')
        with open(config, 'w', encoding='utf-8') as file:
            file.write(config_text)
        daemon = start_daemon(['dbus-daemon', '--config-file', config, '--nofork',
                               '--print-address'], stdout=subprocess.PIPE, text=True)
        address = daemon.stdout.readline().strip()  # printed once it listens
    if not address:
        sys.exit('a11y_check: the private dbus-daemon did not start')
    os.environ['AT_SPI_BUS_ADDRESS'] = address
    start_daemon([registryd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_for_name(address, REGISTRY_NAME):
        sys.exit('a11y_check: at-spi2-registryd did not come up on the private bus')


width, height = (int(n) for n in args.size.split('x'))
harness.require_install()  # before any daemon starts
if args.names:
    start_accessibility_bus()

# The program name is how the lister finds the app on the accessibility bus.
app = harness.make_app('A11yCheck', light=args.light, size=(width, height), name='a11y_check')

import remote_keys  # noqa: E402  (imports Gtk, so after make_app)
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402  (after make_app)

from applemusic import shortcuts  # noqa: E402  (the installed build's, after make_app)
from applemusic.widgets import context_menu  # noqa: E402  (likewise)

failures = []

# The compositor's keyboard, or None where the walkthrough falls back to press().
keyboard = None
if not args.emulate_keys:
    try:
        keyboard = remote_keys.open_keyboard()
        atexit.register(keyboard.close)
    except remote_keys.Unavailable as error:
        print(f'a11y_check: no real key presses ({error}); emulating them instead')
print('keys: real' if keyboard else 'keys: emulated (press())')


# -- key presses --------------------------------------------------------------------------

def _parse(accel):
    ok, key, mods = Gtk.accelerator_parse(accel)
    return (key, int(mods)) if ok else None


def _controllers(widget):
    model = widget.observe_controllers()
    return [model.get_item(i) for i in range(model.get_n_items())]


def descendants(widget):
    """The widgets under widget, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def _mnemonic_owner(manager, shortcut):
    """The widget under manager whose own (managed) shortcut controller holds shortcut: the
    label a mnemonic belongs to, which GTK activates. None when there is none."""
    for widget in (manager, *descendants(manager)):
        for controller in _controllers(widget):
            if (isinstance(controller, Gtk.ShortcutController)
                    and controller.get_scope() == Gtk.ShortcutScope.MANAGED
                    and shortcut in [controller.get_item(i)
                                     for i in range(controller.get_n_items())]):
                return widget
    return None


def _shortcut(controller, key, mods, phase):
    """Activate controller's shortcut for (key, mods) in phase, as GTK does: what ran, or
    None. A mnemonic (a label's underlined letter, which the shortcut manager above the
    label runs) matches its letter with the controller's mnemonic modifier (Alt) and runs on
    its label while that is mapped and sensitive. As in GTK, a key that matches one shortcut
    only runs it exclusively: a mnemonic then activates its widget (several with the same
    letter only take the focus in turn)."""
    if controller.get_propagation_phase() != phase:
        return None
    matches = []
    for i in range(controller.get_n_items()):
        shortcut = controller.get_item(i)
        trigger = shortcut.get_trigger()
        widget = controller.get_widget()
        if isinstance(trigger, Gtk.MnemonicTrigger):
            if (mods != int(controller.get_mnemonics_modifiers())
                    or Gdk.keyval_to_lower(key) != Gdk.keyval_to_lower(trigger.get_keyval())):
                continue
            widget = _mnemonic_owner(widget, shortcut)
            if widget is None or not (widget.get_mapped() and widget.is_sensitive()):
                continue
        elif trigger is None or (key, mods) not in [
                _parse(alt) for alt in trigger.to_string().split('|')]:
            continue
        matches.append((shortcut, widget))
    flags = Gtk.ShortcutActionFlags.EXCLUSIVE if len(matches) == 1 else Gtk.ShortcutActionFlags(0)
    for shortcut, widget in matches:
        if shortcut.get_action().activate(flags, widget, shortcut.get_arguments()):
            return shortcut.get_action().to_string()
    return None


def press(window, accel):
    """Dispatch a key press through GTK's handlers, as the module says. What handled it, or
    None."""
    key, mods = _parse(accel)
    chain = []
    widget = window.get_focus() or window
    while widget is not None:
        chain.append(widget)
        widget = widget.get_parent()
    state = Gdk.ModifierType(mods)
    for widget in reversed(chain):  # capture: from the window down
        for controller in _controllers(widget):
            phase = controller.get_propagation_phase()
            if (isinstance(controller, Gtk.EventControllerKey)
                    and phase == Gtk.PropagationPhase.CAPTURE
                    and controller.emit('key-pressed', key, 0, state)):
                return f'{widget.__gtype__.name} key controller'
            if isinstance(controller, Gtk.ShortcutController):
                done = _shortcut(controller, key, mods, Gtk.PropagationPhase.CAPTURE)
                if done:
                    return done
    for widget in chain:  # bubble: from the focus up
        for controller in _controllers(widget):
            phase = controller.get_propagation_phase()
            if (isinstance(controller, Gtk.EventControllerKey) and isinstance(widget, Gtk.Popover)
                    and phase == Gtk.PropagationPhase.BUBBLE
                    and controller.emit('key-pressed', key, 0, state)):
                return f'{widget.__gtype__.name} key controller'
            if isinstance(controller, Gtk.ShortcutController):
                done = _shortcut(controller, key, mods, Gtk.PropagationPhase.BUBBLE)
                if done:
                    return done
    return None


# -- the checklist -------------------------------------------------------------------------

def filter_text(page):
    """Text a page's filter shows some of its items for: its first item's title (a word
    of it, when that is long)."""
    model = filter_view(page).get_model()
    item = next((model.get_item(n) for n in range(model.get_n_items())
                 if getattr(model.get_item(n), 'search_key', None)), None)
    title = item.title if item is not None else ''
    return title.split()[0] if len(title) > 12 else title


def filter_view(page):
    """The list or grid a page's filter filters."""
    for name in ('grid_view', 'column_view', 'list_view'):
        view = getattr(page, name, None)
        if view is not None:
            return view
    return None


def shown_count(view):
    """The items (tracks, on a playlist's page) the list or grid shows."""
    model = view.get_model()
    return sum(1 for n in range(model.get_n_items())
               if getattr(model.get_item(n), 'search_key', None) is not None)


async def library_filter(window, page, name):
    """A library page's filter by keyboard: Ctrl+F, typing, Escape (docs/accessibility.md)."""
    view = filter_view(page)
    bar = page.filter_bar
    # From the filter's button in the header bar: a page shown again gives the focus back
    # where it was (the Artists page, on an artist's album), where Ctrl+2 leaves it.
    split_view = getattr(page, 'split_view', None)
    if split_view is not None and split_view.get_collapsed():
        split_view.set_show_content(False)  # the Artists list, not an artist's albums
        await asyncio.sleep(0.6)
    bar.button.grab_focus()
    await key(window, '<primary>2', 0.6)
    check(f'Ctrl+2 puts the focus in {name}', inside(window.get_focus(), view),
          describe(window.get_focus()))
    total = shown_count(view)
    text = filter_text(page)
    await key(window, '<primary>f', 0.6)
    check(f'Ctrl+F on {name} shows its filter bar with the cursor in its entry',
          bar.get_search_mode() and inside(window.get_focus(), bar.entry),
          describe(window.get_focus()))
    await type_into(bar.entry, text, 0.8)
    shown = shown_count(view)
    check(f'typing filters {name}', 0 < shown < total or (shown == total == 1),
          (text, shown, total))
    await key(window, 'Escape', 0.8)
    check(f'Escape closes it, all of {name} back, the focus in the list',
          not bar.get_search_mode() and bar.entry.get_text() == ''
          and shown_count(view) == total and inside(window.get_focus(), view),
          (bar.get_search_mode(), shown_count(view), describe(window.get_focus())))
    if keyboard is not None:
        # Typing on the list starts it (Gtk.SearchBar's key capture).
        keyboard.type_text(text[:1].lower())
        await asyncio.sleep(0.8)
        check(f'typing on {name} shows the filter with the letter in it',
              bar.get_search_mode() and bar.entry.get_text() == text[:1].lower()
              and inside(window.get_focus(), bar.entry),
              (bar.get_search_mode(), bar.entry.get_text(), describe(window.get_focus())))
        await key(window, 'Escape', 0.8)
    await filter_far_down(window, page, name)


def focused_object(window, view):
    """The Item or Track of the row or tile of view with the focus, while that widget is on
    screen (a recycled one scrolled out of view is not), else None."""
    from applemusic.widgets import context_menu

    focus = window.get_focus()
    if focus is None or focus is view or not inside(focus, view) or not focus.get_mapped():
        return None
    found = context_menu.find(view, focus)
    return found[1] if found is not None else None


def recycling_letter(view, avoid):
    """A letter that some of view's items match but not all, nor `avoid`: a filter of it
    recycles avoid's row or tile for another item."""
    from applemusic.library import filter_matches

    model = view.get_model()
    keys = [model.get_item(n).search_key for n in range(model.get_n_items())
            if getattr(model.get_item(n), 'search_key', None) is not None]
    partial = [letter for letter in 'aeiourstnlmdhcbgkpvwy'
               if 0 < sum(filter_matches(letter, key) for key in keys) < len(keys)]
    return next((letter for letter in partial if not filter_matches(letter, avoid.search_key)),
                partial[0] if partial else 'a')


async def filter_far_down(window, page, name):
    """Escape out of a filter with the focus far down the list (docs/accessibility.md): the
    focus on the last item (End), Ctrl+F, a letter that leaves that item out, Escape: the
    focus back on it, on screen, and Up moves on from it; then a filter that matches nothing,
    Escape, and the focus is on the item again, not on the bare list."""
    view = filter_view(page)
    bar = page.filter_bar
    if not inside(window.get_focus(), view):
        await key(window, '<primary>2', 0.6)
    await key(window, 'End', 0.6)
    model = view.get_model()
    items = [model.get_item(n) for n in range(model.get_n_items())
             if getattr(model.get_item(n), 'search_key', None) is not None]
    last = next(n for n in reversed(range(model.get_n_items())) if model.get_item(n) is items[-1])
    if focused_object(window, view) is not items[-1] and last < model.get_n_items() - 1:
        # A playlist's list ends with its suggestions, which End goes to (or, from a song,
        # not at all): the last song, as Up from them would reach it.
        from applemusic.widgets.util import focus_position

        focus_position(view, last)
        await asyncio.sleep(0.4)
    before = focused_object(window, view)
    check(f'the focus at the end of {name}', before is items[-1],
          before.title if before is not None else describe(window.get_focus()))
    if before is None:
        return
    letter = recycling_letter(view, before)
    await key(window, '<primary>f', 0.6)
    await type_into(bar.entry, letter, 0.8)
    total = shown_count(view)
    await key(window, 'Escape', 0.8)
    after = focused_object(window, view)
    check(f'Escape from a filter of {letter!r} on {name}: the focus back on the item it was '
          'on, on screen', after is before,
          (total, after.title if after is not None else describe(window.get_focus())))
    await key(window, 'Up', 0.4)
    moved = focused_object(window, view)
    check(f'Up moves on from it in {name}', moved is not None and moved is not before,
          moved.title if moved is not None else describe(window.get_focus()))
    if moved is None:
        return
    await key(window, '<primary>f', 0.6)
    await type_into(bar.entry, 'zzqx', 0.8)  # which no item has
    await key(window, 'Escape', 0.8)
    after = focused_object(window, view)
    check(f'Escape from a filter matching nothing on {name}: the focus on the item again, '
          'not the bare list', after is moved,
          after.title if after is not None else describe(window.get_focus()))


def first_playlist():
    """The library's first playlist of the user's: one with Rename…."""
    return next(node.item for node in app.library.playlist_tree().flat
                if node.kind == 'playlist' and node.item.editable)


def menu_labels(menu):
    """The labels of a Gio.MenuModel's items, its sections flattened (not its submenus')."""
    labels = []
    for position in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        if section is not None:
            labels.extend(menu_labels(section))
        else:
            labels.append(label.unpack() if label is not None else '')
    return labels


def menu_submenu(menu, label):
    """The submenu of a Gio.MenuModel labelled `label`, its sections searched, or None."""
    for position in range(menu.get_n_items()):
        found = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL)
        submenu = menu.get_item_link(position, Gio.MENU_LINK_SUBMENU)
        if submenu is not None and found is not None and found.unpack() == label:
            return submenu
        section = menu.get_item_link(position, Gio.MENU_LINK_SECTION)
        inside = menu_submenu(section, label) if section is not None else None
        if inside is not None:
            return inside
    return None


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' ({detail})' if detail and not ok else ''))
    if not ok:
        failures.append(name)


def inside(widget, ancestor):
    return widget is not None and (widget is ancestor or widget.is_ancestor(ancestor))


def describe(widget):
    return widget.__gtype__.name if widget is not None else 'nothing'


def row_title(row):
    """The title of a page-mode sidebar row (an action row), or '' for anything else."""
    return getattr(row, 'get_title', lambda: '')() if row is not None else ''


async def key(window, accel, wait=0.25):
    """Press accel and wait. With a real keyboard the press goes to the focused window,
    whatever `window` is, and nothing can say what handled it (None); emulated, it is
    dispatched in window and what handled it comes back (press())."""
    if keyboard is None:
        handled = press(window, accel)
    else:
        keyboard.send(accel)
        handled = None
    await asyncio.sleep(wait)
    return handled


def by(handled, what):
    """Whether an emulated press ended in `what`. True with a real keyboard, which cannot see
    what handled a key: the step's own effect is what it checks there."""
    return keyboard is not None or (handled or '').endswith(what)


async def type_into(entry, text, wait=0.4):
    """Put text in the focused entry: typed key by key with a real keyboard, else set."""
    if keyboard is None:
        entry.set_text(text)
    else:
        keyboard.type_text(text)
    await asyncio.sleep(wait)


async def until(condition, timeout=2.0):
    """Wait, up to timeout seconds, for condition() to hold: True when it did. For what
    follows a press after a delay of the toolkit's (a button pressed by its key shows its
    pressed state for a moment before it clicks)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return condition()


async def shelves_shown(window, ready=None, frames=120, timeout=20.0):
    """Wait for the page shown, a page of shelves (its ShelfColumn, `_column`), to have the
    engine's answer (and `ready(page)`, when given), every one of its shelves bound (the
    first few at once, the rest one a frame) and each laid out, then for one frame more, or
    for `frames` of the window's frames at most (the step's checks then say what is
    missing); the page shown. In frames, not seconds: a loaded machine draws them slowly
    (the first ones compile shaders), and a key pressed between a shelf's binding and its
    first layout is the one this waits out."""
    ticks = [0]

    def tick(*_args):
        ticks[0] += 1
        return GLib.SOURCE_CONTINUE

    def settled():
        page = window.navigation_view.get_visible_page()
        column = getattr(page, '_column', None)
        widgets = column.widgets if column is not None else []
        return (column is not None and column.shelves and len(widgets) == len(column.shelves)
                and all(widget.get_width() > 0 for widget in widgets)
                and (ready is None or ready(page)))

    handle = window.add_tick_callback(tick)
    deadline = time.monotonic() + timeout
    try:
        while not settled() and ticks[0] < frames and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        seen = ticks[0]
        while ticks[0] <= seen and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        return window.navigation_view.get_visible_page()
    finally:
        window.remove_tick_callback(handle)


def dialog_shown(window, kind):
    """The dialog of kind shown over window, inside it or as a window of its own (an
    Adw.Dialog over a window that is neither maximized nor tiled), or None."""
    shown = window.get_visible_dialog()
    if isinstance(shown, kind):
        return shown
    for toplevel in Gtk.Window.list_toplevels():
        if toplevel is not window and toplevel.get_visible():
            found = next((widget for widget in descendants(toplevel)
                          if isinstance(widget, kind)), None)
            if found is not None:
                return found
    return None


def watch(name, calls):
    """Replace app.player's command `name` with one that records its argument in calls and
    does nothing (the demo has no engine). Returns the function that puts it back."""
    def command(argument):
        calls.append(argument)
        return asyncio.sleep(0)
    setattr(app.player, name, command)
    return lambda: delattr(app.player, name)


async def moving_songs(window):
    """Step 12: Alt+Down and Alt+Up on a playlist's focused song, announced, the focus
    staying on it; Move Up and Move Down in its menu."""
    playlist = first_playlist()
    window.select_page(f'playlist:{playlist.id}')
    await asyncio.sleep(0.8)
    page = window.navigation_view.get_visible_page()
    await key(window, '<primary>2', 0.6)
    for _step in range(6):  # Play, Shuffle, More Options, then the first song
        found = context_menu.find(page.list_view, window.get_focus())
        if found is not None and found[1] is page.item.groups[0].entries.get_item(0):
            break
        await key(window, 'Tab', 0.3)
    await key(window, 'Down', 0.3)
    found = context_menu.find(page.list_view, window.get_focus())
    song = found[1] if found is not None else None
    check('Tab and Down reach the second song', song is not None and song.index == 1,
          describe(window.get_focus()))
    if song is None:
        return
    said = []
    window.announce = lambda text, _priority: said.append(text)
    await key(window, '<alt>Down', 0.4)
    found = context_menu.find(page.list_view, window.get_focus())
    check('Alt+Down moves it one place down, the focus with it',
          song.index == 2 and found is not None and found[1] is song,
          (song.index, describe(window.get_focus())))
    check('and says where it went', said[-1:] == [
        f'“{song.title}” moved to position 3 of {len(page.item.track_ids())}'], said)
    await key(window, '<alt>Up', 0.4)
    found = context_menu.find(page.list_view, window.get_focus())
    check('Alt+Up moves it back up', song.index == 1 and found is not None and found[1] is song,
          (song.index, describe(window.get_focus())))
    del window.announce
    await key(window, 'Menu', 0.6)
    shown = [each for each in harness.popovers(page.list_view)
             if isinstance(each, Gtk.PopoverMenu)]
    labels = menu_labels(shown[0].get_menu_model()) if shown else []
    check('Menu on it lists Move Up and Move Down', '_Move Up' in labels
          and 'Move _Down' in labels, labels)
    await key(window, 'Escape', 0.4)
    check('Escape closes it', not any(each.get_visible() for each in shown))


async def catalog_playlist(window, artist):
    """One of the catalog's playlists, from the artist page's Artist Playlists: its curator's
    name a link (Shift+Tab from Play reaches it, Enter opens the curator's page), and its
    shelves after the tracks, Tab into them and Shift+Tab back to the last track."""
    print('-- catalog playlist')
    shelf = next((shelf for shelf in artist._shelves if shelf.key == 'playlists'), None)
    check("the artist's page has playlists", shelf is not None and shelf.items.get_n_items())
    if not shelf or not shelf.items.get_n_items():
        return
    window.open_item(shelf.items.get_item(0))
    await asyncio.sleep(1.0)
    page = window.navigation_view.get_visible_page()
    await until(lambda: page.artist_button.get_visible() and page._shelves_start is not None)
    check("the curator's name is a link", page.artist_button.get_visible()
          and not page.subtitle_label.get_visible())
    page.play_button.grab_focus()
    await key(window, '<shift>ISO_Left_Tab')
    check("Shift+Tab from Play: the curator's link", window.get_focus() is page.artist_button,
          describe(window.get_focus()))
    await key(window, 'Return', 1.0)
    curator = window.navigation_view.get_visible_page()
    check("Enter opens the curator's page", curator is not page
          and getattr(curator, 'item', None) is not None and curator.item.kind == 'category',
          type(curator).__name__)
    if curator is not page:
        window.navigation_view.pop()
        await asyncio.sleep(0.6)
    last = page._shelves_start - 1 if page._shelves_start is not None else None
    if last is not None:
        page.list_view.scroll_to(last, Gtk.ListScrollFlags.FOCUS, None)
        await asyncio.sleep(0.3)
        await key(window, 'Tab', 0.3)
        check('Tab from the last track: the first shelf',
              inside(window.get_focus(), page.shelves_box), describe(window.get_focus()))
        await key(window, '<shift>ISO_Left_Tab', 0.3)
        focus = window.get_focus()
        check('Shift+Tab: back to the last track', inside(focus, page.list_view)
              and not inside(focus, page.shelves_box)
              and focus.__gtype__.name == 'GtkListItemWidget'
              and focus.get_first_child().track_row.context_item
              is page._rows.get_item(last), describe(focus))
    window.navigation_view.pop()  # back to the artist, as the steps below expect
    await asyncio.sleep(0.6)


async def view_credits(window, detail):
    """Step 3's View Credits, from the focused track's menu: its dialog (the demo's invented
    answer) with each person a row Tab reaches, Escape closing it, the focus back on the
    track."""
    from applemusic.dialogs.credits import CreditsDialog

    print('-- View Credits')
    row = window.get_focus()
    await key(window, 'Menu', 0.6)
    shown = [each for each in harness.popovers(detail.list_view)
             if isinstance(each, Gtk.PopoverMenu) and each.get_visible()]
    labels = menu_labels(shown[0].get_menu_model()) if shown else []
    check('Menu on a track lists View Credits', 'Vi_ew Credits' in labels, labels)
    if keyboard is not None:
        await key(window, 'e', 1.0)  # its mnemonic
    else:
        for each in shown:
            each.popdown()
        track = detail.item.groups[0].entries.get_item(1)
        window.activate_action('win.item-view-credits', GLib.Variant('(ss)', ('song', track.id)))
    await until(lambda: dialog_shown(window, CreditsDialog) is not None
                and dialog_shown(window, CreditsDialog).status == 'credits')
    dialog = dialog_shown(window, CreditsDialog)
    check('E opens the credits', dialog is not None and dialog.status == 'credits',
          dialog.status if dialog is not None else None)
    if dialog is None:
        return
    toplevel = dialog.get_root()
    await key(toplevel, 'Tab', 0.3)
    await key(toplevel, 'Tab', 0.3)
    focus = toplevel.get_focus()
    check('Tab reaches a person in the credits', inside(focus, dialog.credits_page)
          and isinstance(focus, Adw.ActionRow) and bool(focus.get_title()), describe(focus))
    await key(toplevel, 'Escape', 0)
    await until(lambda: dialog_shown(window, CreditsDialog) is None)
    await until(window.is_active)
    check('Escape closes it, the focus back on the track',
          dialog_shown(window, CreditsDialog) is None and window.get_focus() is row,
          describe(window.get_focus()))


async def selecting_songs(window):
    """Step 16: a playlist's selection mode from the keyboard: Ctrl+A on a song selects them
    all (the mode on), Ctrl+Shift+A none, Space selects the focused song and Shift+Space up
    to the next, each count announced and said by the row; Escape leaves the mode, the focus
    staying on the song, and Space is the playback key's again."""
    page = window.navigation_view.get_visible_page()
    mode = getattr(page, 'selection_mode', None)
    check("the playlist's page has a selection mode", mode is not None)
    if mode is None:
        return
    found = context_menu.find(page.list_view, window.get_focus())
    song = found[1] if found is not None else None
    check('the focus is on a song', song is not None, describe(window.get_focus()))
    if song is None:
        return
    said = []
    window.announce = lambda text, _priority: said.append(text)
    count = len(page.item.track_ids())
    await key(window, '<primary>a', 0.4)
    check('Ctrl+A on a song selects every song, the mode on',
          mode.active and mode.selection.count == count, mode.selection.count)
    check('the bar of actions shows, Cancel in the header bar',
          mode.bar.get_revealed() and mode.cancel_button.get_visible())
    check('and the count is said', said[-1:] == [f'{count} Selected'], said)
    await key(window, '<primary><shift>a', 0.4)
    check('Ctrl+Shift+A selects none', mode.active and mode.selection.count == 0,
          mode.selection.count)
    await key(window, 'space', 0.4)
    check('Space selects the focused song', mode.selection.has(song)
          and mode.selection.count == 1, mode.selection.count)
    row = next((item for item in page._bound if item.get_item() is song), None)
    check('its row says so', row is not None
          and row.get_accessible_description().startswith('Selected'),
          row.get_accessible_description() if row is not None else None)
    await key(window, 'Down', 0.3)
    await key(window, '<shift>space', 0.4)
    check('Shift+Space selects from it to the next', mode.selection.count == 2,
          mode.selection.count)
    check('and says how many', said[-1:] == ['2 Selected'], said)
    await key(window, 'Escape', 0.4)
    focus = window.get_focus()
    check('Escape leaves the mode, the focus on the song',
          not mode.active and inside(focus, page.list_view), describe(focus))
    check('the bar goes', not mode.bar.get_revealed())
    del window.announce


async def playlist_actions(window):
    """Step 17: on a playlist of the user's, Delete on the focused song removes it (the item
    actions' Remove from Playlist, recorded: the demo writes nothing); Sort By in the header
    bar, named, opened with Space, an order chosen by its mnemonic (no song moves in it);
    the playlist's menu offers Add Songs… and Duplicate, whose dialog takes the focus in its
    search, Enter moving to the first song and picking it, Escape closing it with the focus
    back on the page."""
    from applemusic.dialogs.add_songs import AddSongsDialog

    page = window.navigation_view.get_visible_page()
    actions = window.item_actions
    found = context_menu.find(page.list_view, window.get_focus())
    song = found[1] if found is not None else None
    check('the focus is on a song of the playlist', song is not None,
          describe(window.get_focus()))
    if song is None:
        return
    removed = []
    actions.remove_entries = lambda playlist, tracks: removed.append((playlist, list(tracks)))
    await key(window, 'Delete', 0.4)
    del actions.remove_entries
    check('Delete removes the focused song', removed == [(page.item, [song])],
          [(playlist.id, [each.title for each in tracks]) for playlist, tracks in removed])

    print("-- a playlist's Sort By")
    button = page.sort_button
    check('Sort By is in the header bar, named', button.get_visible()
          and button.get_tooltip_text() == 'Sort By')
    button.grab_focus()
    await key(window, 'space', 0.6)
    shown = [each for each in harness.popovers(button) if isinstance(each, Gtk.PopoverMenu)
             and each.get_visible()]
    labels = menu_labels(shown[0].get_menu_model()) if shown else []
    check('Space opens it: the orders, then the directions', labels[:2] == [
        '_Playlist Order', '_Title'] and 'Desce_nding' in labels, labels)
    if keyboard is not None:
        await key(window, 't', 0.6)  # Title's mnemonic
    else:
        for each in shown:
            each.popdown()
        page.activate_action('tracks.sort', GLib.Variant('s', 'title'))
        await asyncio.sleep(0.3)
    check('T sorts by title, and no song moves while it does',
          page.order == ('title', False) and not page.can_reorder(), page.order)
    page.sort('playlist')
    check('Playlist Order moves songs again', page.can_reorder())

    print('-- Add Songs… and Duplicate')
    labels = menu_labels(actions.menu_for(page.item))
    check("the playlist's menu offers Add Songs… and Duplicate",
          'Add Son_gs…' in labels and 'Dupl_icate' in labels, labels)
    added = []
    actions.add_items_to_playlist = lambda playlist_id, objects: added.append(objects)
    window.activate_action('win.item-add-songs', GLib.Variant('(ss)', ('playlist',
                                                                       page.item.id)))
    await until(lambda: dialog_shown(window, AddSongsDialog) is not None
                and dialog_shown(window, AddSongsDialog).get_mapped())
    dialog = dialog_shown(window, AddSongsDialog)
    check('Add Songs… opens its dialog', dialog is not None)
    if dialog is None:
        del actions.add_items_to_playlist
        return
    toplevel = dialog.get_root()
    await until(lambda: inside(toplevel.get_focus(), dialog.search_entry))
    check('the focus is in its search', inside(toplevel.get_focus(), dialog.search_entry),
          describe(toplevel.get_focus()))
    # The library's songs, built for it when no page has asked for them yet; and the keys
    # the dialog's own window's once it is active (a dialog of its own window).
    await until(lambda: dialog.stack.get_visible_child_name() == 'library', 5)
    await until(toplevel.is_active)
    await key(toplevel, 'Return', 0.4)
    focus = toplevel.get_focus()
    check('Enter moves to the first song', inside(focus, dialog.library_view),
          describe(focus))
    await key(toplevel, 'Return', 0.4)
    check('Enter picks it: the header bar counts it, its row says so',
          dialog.picks.count == 1
          and dialog.window_title.get_subtitle() == '1 song selected'
          and any(item.get_accessible_description() == 'Selected'
                  for item in dialog._bound), dialog.picks.count)
    await key(toplevel, 'Escape', 0)
    await until(lambda: dialog_shown(window, AddSongsDialog) is None)
    await until(window.is_active)
    check('Escape closes it, nothing added, the focus back on the page',
          dialog_shown(window, AddSongsDialog) is None and added == []
          and inside(window.get_focus(), page), describe(window.get_focus()))
    del actions.add_items_to_playlist


async def playing_keys(window):
    """Step 13: Go to Current Song (Ctrl+L) from a page, Now Playing and the full-screen
    player, the focus on the song's row each time; the volume keys (Ctrl+Up, Ctrl+Down) on
    a list's row and a button, announced, and not on a sidebar row or the seek slider."""
    from applemusic.widgets import context_menu

    state = harness.invented_playing_state(app)
    items = state['queue']['items']
    at = min(6, len(items) - 1)  # a song down the album, so the list has to scroll to it
    state['track'], state['queue']['index'] = items[at], at
    app.player.apply(state)
    await asyncio.sleep(0.3)
    album = app.library.albums.get_item(0)
    before = window.navigation_view.get_visible_page()
    levels, said = [], []

    def set_volume(level):  # the demo has no engine: MusicKit's answer, at once
        levels.append(level)
        app.player._set_volume(level)
        return asyncio.sleep(0)

    app.player.set_volume = set_volume
    window.announce = lambda text, _priority: said.append(text)

    def on_song_row():
        page = window.navigation_view.get_visible_page()
        view = getattr(page, 'list_view', None)
        found = (context_menu.find(view, window.get_focus())
                 if view is not None and window.get_focus() is not None else None)
        return (getattr(page, 'item', None) is album and found is not None
                and found[1].id == items[at]['id'])

    await key(window, '<primary>1', 0.6)
    shown = window.shown
    await key(window, '<primary>Down', 0.4)
    check("Ctrl+Down on a sidebar row is the row's (the focus moves, nothing selected), not "
          'the volume', not levels and window.shown == shown, (levels, window.shown))
    await key(window, '<primary>l', 0.8)
    await until(on_song_row)
    check("Ctrl+L opens the album playing with the focus on the song's row", on_song_row(),
          describe(window.get_focus()))
    row = window.get_focus()
    await key(window, '<primary>Up', 0.3)
    check('Ctrl+Up on a row turns the volume up a step, announced',
          levels == [0.8] and said[-1:] == ['Volume 80%'] and window.get_focus() is row,
          (levels, said))
    await key(window, '<primary>Down', 0.3)
    await key(window, '<primary>KP_Down', 0.3)
    check('Ctrl+Down twice turns it down two', levels == [0.8, 0.7, 0.6]
          and said[-1:] == ['Volume 60%'], (levels, said))
    await key(window, '<primary><shift>n', 0.8)
    check('Ctrl+Shift+N opens Now Playing', window.bottom_sheet.get_open())
    await key(window, '<primary>l', 0.8)
    await until(lambda: not window.bottom_sheet.get_open() and on_song_row())
    check("Ctrl+L there closes it, the focus on the song's row",
          not window.bottom_sheet.get_open() and on_song_row(), describe(window.get_focus()))
    await key(window, 'F11', 0.8)
    check('F11 shows the full-screen player', window.fullscreen_host.shown)
    await key(window, '<primary>l', 0.8)
    await until(lambda: not window.fullscreen_host.shown and on_song_row())
    check("Ctrl+L there leaves it, the focus on the song's row",
          not window.fullscreen_host.shown and on_song_row(), describe(window.get_focus()))
    await key(window, '<primary>3')
    await key(window, '<primary>Up', 0.3)
    check('Ctrl+Up on the play button turns the volume up',
          levels[-1:] == [0.7] and window.get_focus() is window.player_bar.play_button, levels)
    window.player_bar.seek_scale.grab_focus()
    await key(window, '<primary>Up', 0.3)
    check("Ctrl+Up on the seek slider is the slider's", len(levels) == 4, levels)
    del app.player.set_volume
    del window.announce
    if window.navigation_view.get_visible_page() is not before:
        window.navigation_view.pop_to_page(before)
        await asyncio.sleep(0.6)
    app.player.apply(harness.invented_playing_state(app, lyrics=True))
    await asyncio.sleep(0.3)
    await key(window, '<primary>3')


async def radio_step(window):
    """Radio: its shelves, then Ctrl+2, Tab and the arrows into the live stations (also alone:
    --step radio)."""
    print('-- radio')
    window.select_page('radio')
    radio = await shelves_shown(window)  # the demo's invented answer, then its shelves
    shelves = radio._column.widgets
    live = shelves[0] if shelves else None
    check('Radio shows the live stations as large cards, then Recently Played',
          live is not None and live.props.hero and len(shelves) > 1
          and shelves[1].shelf.items is app.library.radio,
          [widget.shelf.key for widget in shelves])
    if live is not None:
        await key(window, '<primary>2', 0.6)
        check('Ctrl+2 puts the focus in the live stations', inside(window.get_focus(), live),
              describe(window.get_focus()))
        for _ in range(3):  # the shelf's paging arrows and See All, then its cards
            if inside(window.get_focus(), live.list_view):
                break
            await key(window, 'Tab')
        check('Tab reaches the first live station', inside(window.get_focus(), live.list_view),
              describe(window.get_focus()))
        requests = []
        play_request = window.play_request
        window.play_request = lambda play, start_with=None, shuffle=None, start_id=None: (
            requests.append(play))
        await key(window, 'Right')
        await key(window, 'Return')
        window.play_request = play_request
        second = live.shelf.items.get_item(1)
        check('Right, Enter plays the second live station', requests == [second.play],
              requests)


async def genres_step(window):
    """Genres (show-genres): its sidebar row, the grid of genres by keyboard, a genre's
    albums opened with Enter, Alt+Left back to the genre's tile."""
    print('-- Genres')
    item = window._sidebar.item_for('genres')
    check('Genres is not in the sidebar until chosen', not item.get_visible())
    app.settings.set_boolean('show-genres', True)
    await asyncio.sleep(0.4)
    check('Show Genres lists it', item.get_visible())
    row = window._sidebar.row(item.get_index())
    narrow = window.split_view.get_collapsed()  # a page-mode row has its title (an action row)
    check('Its row shows', row is not None and row.get_visible()
          and (not narrow or row_title(row) == 'Genres'), row_title(row))
    window.select_page('genres')
    window.split_view.set_show_content(True)
    await asyncio.sleep(1.0)
    genres = window.navigation_view.get_visible_page()
    check('Genres shows a grid of the genres', getattr(genres, 'grid_view', None) is not None
          and genres.stack.get_visible_child_name() == 'items',
          getattr(genres, 'get_title', lambda: genres)())
    genres.title_label.grab_focus()  # anywhere on the page: Ctrl+2 takes it into the grid
    window.split_view.set_show_content(True)
    await key(window, '<primary>2', 0.6)
    check('Ctrl+2 puts the focus on the first genre', inside(window.get_focus(),
                                                             genres.grid_view),
          describe(window.get_focus()))
    from applemusic.widgets.labels import accessible_label

    first = genres.grid_view.get_model().get_item(0)
    label = accessible_label(first) if first is not None else None
    check('A genre is read with its count ("Ambient, 3 albums")',
          label == f'{first.title}, {first.subtitle}' and first.subtitle.endswith(
              ('album', 'albums')), label)
    await key(window, 'Return', 1.0)
    pushed = window.navigation_view.get_visible_page()
    albums = pushed.grid_view.get_model() if hasattr(pushed, 'grid_view') else None
    shown = [albums.get_item(n) for n in range(albums.get_n_items())] if albums else []
    check("Enter opens the genre's albums", getattr(pushed, 'item', None) is first and shown
          and all(album.genre == first.title for album in shown),
          (pushed, [album.title for album in shown]))
    await key(window, '<alt>Left', 0.8)
    check('Alt+Left goes back to Genres, the focus on the genre',
          window.navigation_view.get_visible_page() is genres
          and inside(window.get_focus(), genres.grid_view), describe(window.get_focus()))
    app.settings.reset('show-genres')
    await asyncio.sleep(0.6)
    check('Hidden again, Home shows in its place', window.shown == 'home', window.shown)


async def song_columns_step(window):
    """The Songs table's Genre and Year columns, from its Sort and Filter menu by keyboard
    (the menu's mnemonics all its own); hidden, with their items, in a narrow window."""
    print("-- Songs' Genre and Year columns")
    window.select_page('songs')
    window.split_view.set_show_content(True)
    await asyncio.sleep(1.0)
    songs = window.navigation_view.get_visible_page()
    songs.sort_button.grab_focus()
    await key(window, 'Return', 0.6)
    popover = songs.sort_button.get_popover()
    check('Return opens Sort and Filter', popover is not None and popover.get_visible())
    labels = menu_labels(songs.sort_button.get_menu_model())
    letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label]
    check('Each of its items, the columns too, has a mnemonic of its own',
          len(letters) == len(labels) == len(set(letters)), labels)
    room = songs._column_actions['genre'].get_enabled()
    check('The column items show only where the table has room for them',
          room != window.split_view.get_collapsed(), room)
    if room:
        await key(window, 'c', 0.6)
        check('C, its mnemonic, shows the Genre column',
              songs.genre_column.get_visible()
              and app.settings.get_strv('song-columns') == ['genre'],
              app.settings.get_strv('song-columns'))
    else:
        await key(window, 'Escape', 0.4)
    app.settings.reset('song-columns')
    await asyncio.sleep(0.4)
    check('Off again, the column goes', not songs.genre_column.get_visible())


async def walkthrough(window):
    narrow = window.split_view.get_collapsed()
    print('-- sidebar')
    await key(window, '<primary>1', 0.6)
    check('Ctrl+1 puts the focus on the selected sidebar row',
          isinstance(window.get_focus(), Gtk.ListBoxRow) and inside(window.get_focus(),
                                                                     window.sidebar))
    if narrow:
        # The page mode's sidebar is a boxed list per section, and libadwaita passes the focus
        # from one section to the next on Down from its last row. That needs an active window:
        # GtkListBoxRow's focus handler reads the row's has-focus, which GTK sets only while
        # the toplevel has the keyboard. A real key press makes the window active; an emulated
        # one cannot, so there the script steps over the section's end itself.
        for _ in range(2):  # Home → New, Radio
            await key(window, 'Down', 0.15)
        check('Down moves to Radio', row_title(window.get_focus()) == 'Radio',
              row_title(window.get_focus()))
        await key(window, 'Up', 0.15)
        check('Up moves back to New', row_title(window.get_focus()) == 'New',
              row_title(window.get_focus()))
        await key(window, 'Down', 0.15)  # Radio again, the section's last row
        if keyboard is None:
            rows = window._sidebar.rows()
            next((row for row in rows if row_title(row) == 'Recently Added'),
                 rows[0]).grab_focus()
            await asyncio.sleep(0.15)
        else:
            await key(window, 'Down', 0.15)
            check("Down from a section's last row moves to the next section",
                  row_title(window.get_focus()) == 'Recently Added',
                  row_title(window.get_focus()))
        for _ in range(2):  # Recently Added → Artists, Albums
            await key(window, 'Down', 0.15)
        check('Down moves to Albums', row_title(window.get_focus()) == 'Albums',
              row_title(window.get_focus()))
    else:
        for _ in range(5):  # Home → New, Radio, Recently Added, Artists, Albums
            await key(window, 'Down', 0.15)
        check('Down selects Albums and shows it', window.shown == 'albums', window.shown)
        await key(window, 'Up', 0.15)
        check('Up selects Artists and shows it', window.shown == 'artists', window.shown)
        await key(window, 'Down', 0.15)
        check('Down selects Albums again', window.shown == 'albums', window.shown)
    await key(window, 'Return', 0.6)
    check('Enter shows Albums', window.shown == 'albums' and (
        not narrow or window.split_view.get_show_content()))
    print('-- grid')
    await key(window, '<primary>2', 0.6)
    grid = window.navigation_view.get_visible_page()
    check('Ctrl+2 puts the focus on a tile', inside(window.get_focus(), grid.grid_view),
          describe(window.get_focus()))
    await key(window, 'Right')
    await key(window, 'Down')
    await key(window, 'Return', 1.0)
    detail = window.navigation_view.get_visible_page()
    check('Right, Down, Enter opens an album', getattr(detail, 'item', None) is not None
          and detail.item.kind == 'album')
    check('the focus is on Play', inside(window.get_focus(), detail.play_button))
    print('-- album')
    await key(window, 'Tab')
    check('Tab: Shuffle', inside(window.get_focus(), detail.shuffle_button))
    await key(window, 'Tab')
    check('Tab: More Options', inside(window.get_focus(), detail.more_button))
    await key(window, 'Tab')
    check('Tab: the first track', inside(window.get_focus(), detail.list_view)
          and window.get_focus().__gtype__.name == 'GtkListItemWidget')
    await key(window, '<shift>ISO_Left_Tab')
    check('Shift+Tab: back to More Options', inside(window.get_focus(), detail.more_button),
          describe(window.get_focus()))
    await key(window, 'Tab')
    check('Tab: the first track again', inside(window.get_focus(), detail.list_view)
          and window.get_focus().__gtype__.name == 'GtkListItemWidget')
    requests = []
    play_request = window.play_request
    window.play_request = lambda play, start_with=None, shuffle=None, start_id=None: (
        requests.append((start_with, start_id)))
    await key(window, 'Down')
    await key(window, 'Return')
    window.play_request = play_request
    second = detail.item.groups[0].entries.get_item(1)
    check('Down, Enter plays the second track', requests == [(1, second.id)], requests)
    await view_credits(window, detail)
    # The footer and the catalog's shelves after the tracks (the demo's invented answer).
    await until(lambda: detail._shelves_start is not None)
    check("the catalog's shelves follow the tracks", detail._shelves_start is not None)
    if detail._shelves_start is not None:
        last = detail._shelves_start - 2  # the footer between them takes no focus
        detail.list_view.scroll_to(last, Gtk.ListScrollFlags.FOCUS, None)
        await asyncio.sleep(0.3)
        await key(window, 'Tab', 0.3)
        check('Tab from the last track: the first shelf',
              inside(window.get_focus(), detail.shelves_box), describe(window.get_focus()))
        await key(window, '<shift>ISO_Left_Tab', 0.3)
        focus = window.get_focus()
        check('Shift+Tab: back to the last track', inside(focus, detail.list_view)
              and not inside(focus, detail.shelves_box)
              and focus.__gtype__.name == 'GtkListItemWidget'
              and focus.get_first_child().track_row.context_item
              is detail._rows.get_item(last), describe(focus))
    print('-- catalog album')
    # One of the catalog's the library lacks (Other Versions' first): Add between Shuffle and
    # More Options.
    other = None
    for shelf in detail._catalog_shelves:
        other = next((shelf.items.get_item(position)
                      for position in range(shelf.items.get_n_items())
                      if shelf.items.get_item(position).kind == 'album'), None)
        if other is not None:
            break
    check('an album the library lacks is on a shelf', other is not None)
    if other is not None:
        window.open_item(other)
        await asyncio.sleep(1.0)
        catalog = window.navigation_view.get_visible_page()
        check('it has Add', catalog.add_button.get_visible()
              and not catalog.in_library_box.get_visible())
        catalog.play_button.grab_focus()
        await key(window, 'Tab')
        check('Tab: Shuffle', inside(window.get_focus(), catalog.shuffle_button))
        await key(window, 'Tab')
        check('Tab: Add', inside(window.get_focus(), catalog.add_button),
              describe(window.get_focus()))
        await key(window, 'Tab')
        check('Tab: More Options', inside(window.get_focus(), catalog.more_button))
        window.navigation_view.pop()  # back to the album, as the steps below expect
        await asyncio.sleep(0.6)
    print('-- artist')
    window.open_artist_page(app.library.artists.get_item(0))  # Go to Artist's page
    await asyncio.sleep(1.5)  # its page answered from the demo's invented one
    artist = window.navigation_view.get_visible_page()
    check('an artist opens with the focus on Play', inside(window.get_focus(), artist.play_button),
          describe(window.get_focus()))
    await key(window, 'Tab')
    check('Tab: the star', window.get_focus() is artist.favourite_button,
          describe(window.get_focus()))
    starred = artist.favourite_button.get_active()
    await key(window, 'space')  # the demo engine remembers it for the session
    await until(lambda: artist.favourite_button.get_active() != starred)
    check('Space stars the artist, or takes the star back',
          artist.favourite_button.get_active() != starred
          and window.get_focus() is artist.favourite_button)
    await key(window, 'space')
    await until(lambda: artist.favourite_button.get_active() == starred)
    check('Space again puts it back', artist.favourite_button.get_active() == starred)
    await key(window, 'Tab')
    check('Tab: More Options', inside(window.get_focus(), artist.more_button))
    await key(window, 'Tab')
    check('Tab: the latest release', window.get_focus() is artist.release_button,
          describe(window.get_focus()))
    for _ in range(4):  # the Top Songs arrows and See All, then the songs
        if inside(window.get_focus(), artist.top_songs.grid_view):
            break
        await key(window, 'Tab')
    check('Tab reaches the first top song', inside(window.get_focus(), artist.top_songs.grid_view)
          and window.get_focus().__gtype__.name == 'GtkListItemWidget',
          describe(window.get_focus()))
    requests = []
    window.play_request = lambda play, start_with=None, shuffle=None, start_id=None: (
        requests.append((play.get('kind'), start_with, start_id)))
    await key(window, 'Down')
    await key(window, 'Return')
    window.play_request = play_request
    song = artist.top_songs.shelf.items.get_item(1)
    check('Down, Enter plays the top songs from the second', requests == [('songs', 1, song.id)],
          requests)
    await catalog_playlist(window, artist)
    # The other look of the hero: the demo's first artist has a banner, its second none.
    banner = artist.banner.get_visible()
    window.navigation_view.pop()
    await asyncio.sleep(0.6)
    window.open_artist_page(app.library.by_id('artist', 'l.art002' if banner else 'l.art001'))
    await asyncio.sleep(1.5)
    other = window.navigation_view.get_visible_page()
    look = 'the portrait' if banner else 'a banner'
    check(f'an artist with {look} opens with the focus on Play',
          other.banner.get_visible() != banner
          and inside(window.get_focus(), other.play_button), describe(window.get_focus()))
    await key(window, 'Tab')
    check(f'Tab: the star, over {look}', window.get_focus() is other.favourite_button,
          describe(window.get_focus()))
    await key(window, 'Tab')
    check(f'Tab: More Options, over {look}', inside(window.get_focus(), other.more_button))
    window.navigation_view.pop()  # back to the album, as the steps below expect
    await asyncio.sleep(0.6)
    print('-- the idle player bar')
    check('with nothing playing there is no bar',
          not window.bottom_sheet.get_reveal_bottom_bar() and not window.player_bar.get_mapped())
    resting = window.get_focus()
    await key(window, '<primary>3')
    check('Ctrl+3 with nothing playing leaves the focus where it is',
          window.get_focus() is resting and not window.bottom_sheet.get_open(),
          describe(window.get_focus()))
    await key(window, 'F11', 0.6)
    check('F11 with nothing playing does nothing', not window.fullscreen_host.shown
          and window.get_focus() is resting, describe(window.get_focus()))
    await key(window, '<primary><shift>n', 0.8)
    check('Ctrl+Shift+N opens Now Playing all the same (Nothing Queued)',
          window.bottom_sheet.get_open())
    await key(window, 'Escape')
    await until(lambda: not window.bottom_sheet.get_open() and window.get_focus() is resting)
    check('Escape closes it, the focus back where it was',
          not window.bottom_sheet.get_open() and window.get_focus() is resting,
          describe(window.get_focus()))
    app.player.apply(harness.invented_playing_state(app, lyrics=True))
    await until(window.player_bar.get_mapped)
    check('an item playing reveals the bar',
          window.bottom_sheet.get_reveal_bottom_bar() and window.player_bar.get_mapped())
    print('-- player bar')
    await key(window, '<primary>3')
    check('Ctrl+3 puts the focus on the play button',
          window.get_focus() is window.player_bar.play_button)
    bar = window.player_bar
    if bar.props.compact:  # a phone's bar: the item, then Play and Next, no Previous
        await key(window, 'Tab')
        after = window.get_focus()
        await key(window, '<shift>Tab')
        check('the compact bar: Tab from Play goes to Next, Shift+Tab back; no Previous',
              after is bar.next_button and window.get_focus() is bar.play_button
              and not bar.previous_button.get_mapped(), (describe(after),
                                                         describe(window.get_focus())))
    else:
        await key(window, '<shift>Tab')
        before = window.get_focus()
        await key(window, 'Tab')
        check('Shift+Tab from Play goes to Previous, Tab back',
              before is bar.previous_button and window.get_focus() is bar.play_button,
              (describe(before), describe(window.get_focus())))
    # Watched at the actions: Space presses the focused button, whose own activation runs
    # its action (never the window's key handler); the window handles Ctrl+Right and Ctrl+Left.
    actions = []
    handlers = [(app.lookup_action(name), app.lookup_action(name).connect(
        'activate', lambda action, _parameter: actions.append(action.get_name())))
        for name in ('play-pause', 'next', 'previous')]
    handled = await key(window, 'space')
    await until(lambda: actions)  # the button clicks once its pressed state has shown
    check('Space presses the focused play button (play-pause)',
          actions == ['play-pause'] and by(handled, 'signal(activate)'), (actions, handled))
    await key(window, '<primary>Right')
    await key(window, '<primary>Left')
    for action, handler in handlers:
        action.disconnect(handler)
    check('Space, Ctrl+Right, Ctrl+Left: play-pause, next, previous',
          actions == ['play-pause', 'next', 'previous'], actions)
    await key(window, 'Menu', 0.6)
    popover = harness.popovers(window.player_bar)
    check("Menu on the bar opens the item playing's menu", bool(popover))
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back on the play button',
          not any(each.get_visible() for each in popover)
          and window.get_focus() is window.player_bar.play_button, describe(window.get_focus()))
    print('-- Go to Current Song, the volume keys')
    await playing_keys(window)
    print('-- a live station')
    said = []
    window.announce = lambda text, _priority: said.append(text)
    app.player.apply(harness.invented_live_state(app))
    await until(bar.live_label.get_mapped)
    del window.announce
    check('a live station: LIVE in place of the slider, Stop on the play button, the focus '
          'kept', bar.live_label.get_mapped() and not bar.seek_scale.get_mapped()
          and bar.play_button.get_tooltip_text() == 'Stop'
          and window.get_focus() is bar.play_button, describe(window.get_focus()))
    described = [Gtk.test_accessible_has_property(button, Gtk.AccessibleProperty.DESCRIPTION)
                 for button in (bar.play_button, window.now_playing.play_button)]
    check('a screen reader hears it is live: "Now playing live: …" announced, the play '
          'buttons (bar, sheet) described, Shuffle and Repeat off',
          len(said) == 1 and said[0].startswith('Now playing live: ') and all(described)
          and not bar.shuffle_button.get_sensitive()
          and not bar.repeat_button.get_sensitive(), (said, described))
    actions = []
    handlers = [(app.lookup_action(name), app.lookup_action(name).connect(
        'activate', lambda action, _parameter: actions.append(action.get_name())))
        for name in ('play-pause', 'next', 'previous')]
    stopped = []

    async def stop():  # the demo has no engine: its failure's toast would take Escape
        stopped.append(True)
    app.player.stop = stop
    await key(window, 'space')
    await until(lambda: actions and stopped)
    handled = [await key(window, '<primary>Right'), await key(window, '<primary>Left')]
    del app.player.stop
    for action, handler in handlers:
        action.disconnect(handler)
    check('Space on Stop stops it (play-pause); Ctrl+Right and Ctrl+Left do nothing, the '
          'focus kept', actions == ['play-pause'] and stopped == [True]
          and not app.lookup_action('next').get_enabled()
          and not app.lookup_action('previous').get_enabled()
          and all(by(each, 'key controller') for each in handled)
          and window.get_focus() is bar.play_button,
          (actions, stopped, handled, describe(window.get_focus())))
    # The demo's "not available" toasts of the playback keys above, queued one after the
    # other: one still up when a later step presses Escape would take it.
    window.toast_overlay.dismiss_all()
    app.player.apply(None)  # the music stops: the bar goes, with the focus on it
    await until(lambda: not window.player_bar.get_mapped())
    check('the item going hides the bar and moves the focus into the page',
          not window.bottom_sheet.get_reveal_bottom_bar()
          and inside(window.get_focus(), window.navigation_view), describe(window.get_focus()))
    app.player.apply(harness.invented_playing_state(app, lyrics=True))
    await until(window.player_bar.get_mapped)
    print('-- Now Playing')
    sheet = window.now_playing
    tabs = sheet.tab_stack.get_prev_sibling()  # the Lyrics / Up Next switcher
    await key(window, '<primary><shift>n', 0.8)
    check('Ctrl+Shift+N opens the sheet with the focus on its play button',
          window.bottom_sheet.get_open() and window.get_focus() is sheet.play_button)
    for _ in range(3):  # Next, Repeat, the tabs
        await key(window, 'Tab', 0.1)
    check('Tab reaches the Lyrics and Up Next tabs', inside(window.get_focus(), tabs),
          describe(window.get_focus()))
    await key(window, 'Right')
    await key(window, 'space')  # the toggle clicks once its pressed state has shown
    await until(lambda: sheet.tab_stack.get_visible_child_name() == 'queue')
    check('Right, Space: Up Next', sheet.tab_stack.get_visible_child_name() == 'queue')
    await key(window, 'Left')
    await key(window, 'Return')
    await until(lambda: sheet.tab_stack.get_visible_child_name() == 'lyrics')
    check('Left, Enter: Lyrics', sheet.tab_stack.get_visible_child_name() == 'lyrics')
    await key(window, 'Tab', 0.1)
    check('Tab reaches the lyrics', inside(window.get_focus(), sheet.lyrics_view.list_view),
          describe(window.get_focus()))
    seeks = []
    undo = watch('seek', seeks)
    await key(window, 'Down')
    await key(window, 'Return')
    undo()
    check('Down, Enter seeks to a line', len(seeks) == 1, seeks)
    await key(window, 'Tab', 0.1)
    check('Tab: the close button', window.get_focus() is sheet.close_button,
          describe(window.get_focus()))
    for _ in range(4):  # on through the header bar's buttons
        if window.get_focus() is sheet.more_button or inside(window.get_focus(),
                                                             sheet.more_button):
            break
        await key(window, 'Tab', 0.1)
    check('Tab reaches More Options', inside(window.get_focus(), sheet.more_button),
          describe(window.get_focus()))
    await key(window, 'Return', 0.6)
    popover = sheet.more_button.get_popover()
    check("Enter on it opens the item playing's menu", popover is not None
          and popover.get_visible())
    await key(window, 'Escape', 0.4)
    check('Escape closes the menu, not the sheet',
          window.bottom_sheet.get_open() and not popover.get_visible())
    sheet.close_button.grab_focus()
    await key(window, 'Return')
    await until(lambda: not window.bottom_sheet.get_open())
    check('Enter on the close button closes the sheet', not window.bottom_sheet.get_open())
    await key(window, '<primary><shift>n', 0.8)
    for _ in range(3):  # Next, Repeat, the tabs
        await key(window, 'Tab', 0.1)
    await key(window, 'Right')
    await key(window, 'space')
    await until(lambda: sheet.tab_stack.get_visible_child_name() == 'queue')
    queue_view = sheet.queue_view
    await key(window, 'Tab', 0.1)
    check('Tab reaches History', window.get_focus() is queue_view.history_button,
          describe(window.get_focus()))
    await key(window, 'Tab', 0.1)
    check('Tab: Autoplay', window.get_focus() is queue_view.autoplay_button,
          describe(window.get_focus()))
    await key(window, 'Tab', 0.1)
    check('Tab: Clear', window.get_focus() is queue_view.clear_button,
          describe(window.get_focus()))
    await up_next_clear(window, queue_view)
    await key(window, 'Menu', 0.6)
    popover = harness.popovers(sheet.queue_view)
    check("Menu opens the focused entry's menu", bool(popover))
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back in Up Next',
          not any(each.get_visible() for each in popover) and window.bottom_sheet.get_open()
          and inside(window.get_focus(), sheet.queue_view.list_view),
          describe(window.get_focus()))
    await up_next_remove(window, queue_view)
    await up_next_move(window, queue_view)
    jumps = []
    undo = watch('queue_jump', jumps)
    await key(window, 'Down')
    await key(window, 'Return')
    undo()
    check('Down, Enter plays the next entry', jumps == [1], jumps)
    await up_next_history(window, queue_view)
    await key(window, 'Escape', 0.8)
    check('Escape closes the sheet', not window.bottom_sheet.get_open())
    await now_playing_tabs(window)
    await fullscreen_player(window)
    await mini_player(window)
    print('-- back')
    await key(window, '<alt>Left', 0.8)
    check('Alt+Left goes back to Albums', window.navigation_view.get_visible_page() is grid)
    print('-- search')
    await key(window, '<primary>f', 0.6)
    check("Ctrl+F on Albums shows the page's own filter, not Search",
          window.shown == 'albums' and grid.filter_bar.get_search_mode()
          and inside(window.get_focus(), grid.filter_bar.entry), describe(window.get_focus()))
    await key(window, 'Escape', 0.6)
    window.select_page('home')  # a page with no filter
    await asyncio.sleep(0.8)
    await key(window, '<primary>2', 0.4)
    await key(window, '<primary>f', 0.8)
    search = window.navigation_view.get_visible_page()
    check('Ctrl+F elsewhere shows Search with the focus in its entry',
          window.shown == 'search' and inside(window.get_focus(), search.search_entry))
    await type_into(search.search_entry, 'tide')
    check('typing into the entry reaches it', search.search_entry.get_text() == 'tide',
          search.search_entry.get_text())
    await key(window, '<primary><shift>u', 0.4)
    check("Ctrl+Shift+U in the entry is the entry's (Unicode entry), not Up Next",
          window.lookup_action('show-queue').get_enabled() and not window.bottom_sheet.get_open()
          and inside(window.get_focus(), search.search_entry), describe(window.get_focus()))
    levels = []
    restore = watch('set_volume', levels)
    await key(window, '<primary>Up', 0.3)
    restore()
    # Not the volume; GTK's own (the window's move-focus) may take the focus up out of it.
    check('Ctrl+Up in the entry leaves the volume alone',
          app.player.track is not None and not levels,
          (levels, app.player.track, describe(window.get_focus())))
    search.search_entry.grab_focus()
    await asyncio.sleep(0.2)
    await key(window, 'Tab')
    check("Tab from the entry reaches Apple Music's filter",
          inside(window.get_focus(), search.kind_dropdown), describe(window.get_focus()))
    await key(window, 'space', 0.6)
    await key(window, 'Down')
    await key(window, 'Return', 1.0)
    check('Space, Down, Enter on the filter: one kind, its list shown',
          search.kind == 'artists' and search.stack.get_visible_child_name() == 'kind',
          (search.kind, search.stack.get_visible_child_name()))
    check('the focus back on the filter once a kind is chosen',
          inside(window.get_focus(), search.kind_dropdown), describe(window.get_focus()))
    search.set_kind('all')
    await asyncio.sleep(0.8)
    await key(window, 'Tab')
    await key(window, 'Right')
    await key(window, 'space', 0.8)
    check('Tab, Right, Space: Your Library', search.mode == 'library', search.mode)
    await key(window, '<shift>Tab')
    await key(window, 'Escape')
    check('Escape in the entry clears it', search.search_entry.get_text() == '')
    print("-- a search's See All")
    search.set_mode('music')
    search.search_entry.grab_focus()
    await type_into(search.search_entry, 'tide')
    await key(window, 'Return', 1.2)
    songs_shelf = next((widget for widget in search._column.widgets
                        if widget.shelf is not None and widget.shelf.key == 'songs'), None)
    check('Enter in the entry: the shelves, Songs offering See All',
          songs_shelf is not None and songs_shelf.see_all_button.get_visible())
    if songs_shelf is not None:
        songs_shelf.see_all_button.grab_focus()
        await key(window, 'space', 1.2)
        see_all = window.navigation_view.get_visible_page()
        check("Space on See All: the kind's page, the focus in its list",
              type(see_all).__name__ == 'SearchAllPage'
              and inside(window.get_focus(), see_all.results_list.list_view),
              (type(see_all).__name__, describe(window.get_focus())))
        await key(window, 'End', 1.2)
        check('End in the list: the next page loaded, the end shown',
              see_all.pager.state == 'done' and see_all.pager.items.get_n_items() > 20,
              (see_all.pager.state, see_all.pager.items.get_n_items()))
        await key(window, 'Escape', 0.8)
        check('Escape goes back to the results',
              window.navigation_view.get_visible_page() is search
              and search.stack.get_visible_child_name() == 'results',
              describe(window.navigation_view.get_visible_page()))
    search.search_entry.grab_focus()
    await key(window, 'Escape')
    print('-- search over a pushed page, the Songs filter')
    window.open_item(app.library.albums.get_item(0))  # a result opened from Search
    await asyncio.sleep(0.6)
    await key(window, '<primary>f', 0.8)
    check('Ctrl+F over a page pushed on Search pops it and focuses the visible entry',
          window.navigation_view.get_visible_page() is search
          and inside(window.get_focus(), search.search_entry), describe(window.get_focus()))
    print('-- the Songs filter')
    window.select_page('songs')
    await asyncio.sleep(0.8)
    songs = window.navigation_view.get_visible_page()
    await key(window, '<primary>2', 0.6)
    check('Ctrl+2 puts the focus in the Songs table',
          inside(window.get_focus(), songs.column_view), describe(window.get_focus()))
    if keyboard is not None:
        # Typing on the page shows the filter bar (Gtk.SearchBar's key capture forwards the
        # key's event, which an emulated press has none of).
        keyboard.type_text('a')
        await asyncio.sleep(0.6)
        check('typing on the page shows the filter bar with the letter in its entry',
              songs.filter_bar.get_search_mode() and songs.filter_bar.entry.get_text() == 'a'
              and inside(window.get_focus(), songs.filter_bar.entry),
              (songs.filter_bar.get_search_mode(), songs.filter_bar.entry.get_text(),
               describe(window.get_focus())))
        await key(window, 'Escape', 0.6)
        check('Escape closes it, clears the filter and puts the focus back in the table',
              not songs.filter_bar.get_search_mode() and songs.filter_bar.entry.get_text() == ''
              and inside(window.get_focus(), songs.column_view),
              (songs.filter_bar.get_search_mode(), songs.filter_bar.entry.get_text(),
               describe(window.get_focus())))
    await key(window, '<primary>f', 0.6)
    check("Ctrl+F on Songs shows the page's filter bar with the cursor in its entry",
          songs.filter_bar.get_search_mode() and inside(window.get_focus(), songs.filter_bar.entry),
          describe(window.get_focus()))
    await key(window, 'Escape', 0.6)
    check('Escape closes the filter bar, the focus back in the table',
          not songs.filter_bar.get_search_mode()
          and inside(window.get_focus(), songs.column_view), describe(window.get_focus()))
    requests = []
    window.play_request = lambda play, start_with=None, shuffle=None, start_id=None: (
        requests.append((play.get('kind'), len(play.get('id', '').split(',')), shuffle)))
    await key(window, '<shift>Tab')
    check('Shift+Tab from the table: Shuffle', window.get_focus() is songs.shuffle_button,
          describe(window.get_focus()))
    await key(window, 'space')
    await key(window, '<shift>Tab')
    check('Shift+Tab: Play', window.get_focus() is songs.play_button,
          describe(window.get_focus()))
    await key(window, 'Return')
    window.play_request = play_request
    from applemusic.discography import PLAY_LIMIT
    shown = min(len(songs._matches), PLAY_LIMIT)
    check('Space on Shuffle, Enter on Play: the songs shown, shuffled, then in order',
          requests == [('songs', shown, True), ('songs', shown, False)], requests)
    print('-- Artists')
    window.select_page('artists')
    window.split_view.set_show_content(True)
    await asyncio.sleep(0.6)
    artists = window.navigation_view.get_visible_page()
    collapsed = artists.split_view.get_collapsed()
    await key(window, '<primary>2', 0.6)
    check("Ctrl+2 puts the focus on the list's selected artist",
          inside(window.get_focus(), artists.list_view), describe(window.get_focus()))
    selection = artists.list_view.get_model()
    await key(window, 'Down', 0.4)
    second = selection.get_item(1)
    if collapsed:
        check('Down moves to the next artist', selection.get_selected() == 1
              and not artists.split_view.get_show_content(), selection.get_selected())
    else:
        check('Down selects the next artist, whose albums show beside the list',
              artists.detail.artist is second, artists.detail.artist)
    await key(window, 'Return', 0.8)
    detail = artists.detail
    check("Enter shows the artist's albums, the focus on Play",
          detail.artist is second and detail.get_mapped()
          and inside(window.get_focus(), detail.play_button), describe(window.get_focus()))
    await key(window, 'Tab')
    check('Tab: Shuffle', inside(window.get_focus(), detail.shuffle_button))
    await key(window, 'Tab')
    check('Tab: More Options', inside(window.get_focus(), detail.more_button))
    await key(window, 'Tab')
    check('Tab: the first album', inside(window.get_focus(), detail.grid_view),
          describe(window.get_focus()))
    await key(window, 'Return', 1.0)
    pushed = window.navigation_view.get_visible_page()
    check('Enter opens the album', getattr(pushed, 'item', None) is not None
          and pushed.item.kind == 'album' and pushed.item is detail.shown_albums()[0],
          (pushed, [album.title for album in detail.shown_albums()],
           getattr(getattr(pushed, 'item', None), 'title', None)))
    await key(window, '<alt>Left', 0.8)
    check('Alt+Left goes back to the artist, the focus on the album',
          window.navigation_view.get_visible_page() is artists
          and inside(window.get_focus(), detail.grid_view), describe(window.get_focus()))
    if collapsed:
        await key(window, '<alt>Left', 0.8)
        check('Alt+Left goes back to the list, the focus on the artist',
              not artists.split_view.get_show_content()
              and inside(window.get_focus(), artists.list_view), describe(window.get_focus()))
    print('-- menus')
    await key(window, 'F10', 0.6)
    menu = window.primary_menu_button.get_popover()
    check('F10 opens the main menu', menu is not None and menu.get_visible())
    first = menu_labels(window.primary_menu_button.get_menu_model())[:2]
    check('It starts with New Playlist… and New Folder…',
          first == ['Ne_w Playlist…', 'New _Folder…'], first)
    await key(window, 'Escape', 0.4)
    check('Escape closes it', not menu.get_visible())
    window.select_page('albums')
    await asyncio.sleep(0.4)
    grid = window.navigation_view.get_visible_page()
    grid.sort_button.grab_focus()  # the header bar's Sort By
    await key(window, '<primary>2', 0.6)
    check("Ctrl+2 from the page's header bar moves into the grid",
          inside(window.get_focus(), grid.grid_view), describe(window.get_focus()))
    await key(window, 'Menu', 0.6)
    popover = harness.popovers(grid)
    check("Menu opens the focused tile's context menu", bool(popover))
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back on the tile',
          not any(each.get_visible() for each in popover)
          and inside(window.get_focus(), grid.grid_view), describe(window.get_focus()))
    actions = []
    handler = app.lookup_action('play-pause').connect(
        'activate', lambda action, _parameter: actions.append(action.get_name()))
    handled = await key(window, 'space')
    await until(lambda: actions)
    app.lookup_action('play-pause').disconnect(handler)
    check('Space on a tile plays or pauses',
          actions == ['play-pause'] and by(handled, 'key controller'),
          (actions, handled, describe(window.get_focus())))
    print('-- favourites only')
    grid.sort_button.grab_focus()  # Sort and Filter
    await key(window, 'Return', 0.6)
    popover = grid.sort_button.get_popover()
    check('Return opens Sort and Filter', popover is not None and popover.get_visible())
    labels = menu_labels(grid.sort_button.get_menu_model())
    letters = [label[label.index('_') + 1].lower() for label in labels if '_' in label]
    check('Each of its items has a mnemonic of its own',
          len(letters) == len(labels) == len(set(letters)), labels)

    def focused_text():
        focus = window.get_focus()
        focus = focus if popover is not None and inside(focus, popover) else None
        labels = [widget.get_label() for widget in descendants(focus)
                  if isinstance(widget, Gtk.Label)] if focus is not None else []
        return labels[0].replace('_', '') if labels else ''

    for _press in range(12):
        if focused_text() == 'Favourites Only':
            break
        await key(window, 'Down', 0.15)
    check('Down reaches Favourites Only', focused_text() == 'Favourites Only', focused_text())
    await key(window, 'Escape', 0.4)
    grid.sort_button.grab_focus()
    await key(window, 'Return', 0.6)
    await key(window, 'f', 0.6)
    shown = grid.grid_view.get_model()
    shown = [shown.get_item(n) for n in range(shown.get_n_items())]
    check('F, its mnemonic, shows the favourite albums alone',
          grid._favourites_action.get_state().get_boolean() and shown
          and all(item.favourite for item in shown), len(shown))
    grid.activate_action('page.favourites-only', None)  # every album again
    app.settings.reset('favourites-only')
    await genres_step(window)
    await song_columns_step(window)
    print("-- the library pages' filters (Ctrl+F)")
    for key_name, name in (('albums', 'Albums'), ('music-videos', 'Music Videos'),
                           ('artists', 'Artists'), ('songs', 'Songs'),
                           ('favourite-songs', 'Favourite Songs')):
        window.select_page(key_name)
        window.split_view.set_show_content(True)
        await asyncio.sleep(0.8)
        await library_filter(window, window.navigation_view.get_visible_page(), name)
    print("-- a playlist's filter, Escape before Back")
    window.select_page('albums')
    await asyncio.sleep(0.4)
    albums = window.navigation_view.get_visible_page()
    window.open_item(first_playlist())
    await asyncio.sleep(1.0)
    playlist = window.navigation_view.get_visible_page()
    await library_filter(window, playlist, 'a playlist')
    await key(window, '<primary>f', 0.6)
    await type_into(playlist.filter_bar.entry, filter_text(playlist), 0.6)
    await key(window, '<primary>2', 0.6)
    check("Ctrl+2 from the playlist's filter moves into its songs",
          inside(window.get_focus(), playlist.list_view), describe(window.get_focus()))
    await key(window, 'Escape', 0.6)
    check('Escape on the songs closes the filter first, the page still shown',
          not playlist.filter_bar.get_search_mode()
          and window.navigation_view.get_visible_page() is playlist,
          (playlist.filter_bar.get_search_mode(), window.navigation_view.get_visible_page()))
    await key(window, 'Escape', 0.8)
    check('Escape again goes back', window.navigation_view.get_visible_page() is albums,
          window.navigation_view.get_visible_page())
    await radio_step(window)
    print('-- new')
    from applemusic.widgets.banner_tile import BannerTile
    from applemusic.widgets.explore import LinkChild

    window.select_page('new')
    new = await shelves_shown(window)  # the demo's invented answer, then its shelves
    shelves = new._column.widgets
    featured = shelves[0] if shelves else None
    check('New opens with its banners as wide cards',
          featured is not None and featured.props.banners, [w.shelf.key for w in shelves])
    if featured is not None:
        await key(window, '<primary>2', 0.6)
        for _ in range(3):  # the shelf's paging arrows and See All, then its cards
            if inside(window.get_focus(), featured.list_view):
                break
            await key(window, 'Tab')
        focus = window.get_focus()
        card = focus.get_first_child() if focus is not None else None
        check('Tab reaches the first banner', isinstance(card, BannerTile),
              describe(focus))
    links = [child for child in descendants(new) if isinstance(child, LinkChild)]
    room = next((child for child in links if child.item.kind == 'room'), None)
    check('More to Explore ends New with its links, a room among them', room is not None,
          [child.item.title for child in links])
    if room is not None:
        room.grab_focus()
        await key(window, 'Return', 1.0)
        page = window.navigation_view.get_visible_page()
        check('Enter on a link opens its room as a grid',
              getattr(page, 'item', None) is room.item
              and page.stack.get_visible_child_name() == 'items',
              page.get_title())
        await key(window, '<primary>2', 0.6)
        check("Ctrl+2 puts the focus in the room's grid",
              inside(window.get_focus(), page.grid_view), describe(window.get_focus()))
        await key(window, 'Escape', 0.6)
        check('Escape goes back to New', window.navigation_view.get_visible_page() is new,
              window.navigation_view.get_visible_page())
    print('-- charts')
    from applemusic.pages.charts import charts_item
    from applemusic.widgets.song_shelf import SongShelf

    window.open_item(charts_item())  # as New's and Search's Top Charts tile opens it
    charts = await shelves_shown(window)  # the demo's invented answer, then its shelves
    shelves = charts._column.widgets
    songs = shelves[0] if shelves else None
    check('Charts shows Top Songs as a numbered grid of songs, then numbered tiles',
          isinstance(songs, SongShelf) and songs.shelf.ranked and len(shelves) == 6
          and shelves[1].shelf.ranked, [widget.shelf.key for widget in shelves])
    if isinstance(songs, SongShelf):
        await key(window, '<primary>2', 0.6)
        check('Ctrl+2 puts the focus in Top Songs', inside(window.get_focus(), songs),
              describe(window.get_focus()))
        for _ in range(3):  # the shelf's paging arrows and See All, then its songs
            if inside(window.get_focus(), songs.grid_view):
                break
            await key(window, 'Tab')
        check('Tab reaches the first song', inside(window.get_focus(), songs.grid_view),
              describe(window.get_focus()))
        requests = []
        play_request = window.play_request
        window.play_request = lambda play, start_with=None, shuffle=None, start_id=None: (
            requests.append((play, start_with)))
        await key(window, 'Return')
        window.play_request = play_request
        check('Enter plays the chart from its first song',
              requests == [(songs.queue(), 0)], requests)
    menu = charts.genre_menu
    drop_down = menu.drop_down
    check('The header bar has the genre menu, named, on All Genres',
          drop_down.get_visible() and drop_down.get_tooltip_text() == 'Genre'
          and drop_down.get_selected_item() is not None
          and drop_down.get_selected_item().get_string() == 'All Genres',
          drop_down.get_selected_item() and drop_down.get_selected_item().get_string())
    if drop_down.get_visible():
        drop_down.grab_focus()
        await key(window, 'Return', 0.6)  # opens the menu
        popover = next((widget for widget in descendants(drop_down)
                        if isinstance(widget, Gtk.Popover)), None)
        check('Enter opens the genre menu', popover is not None and popover.get_visible(),
              describe(window.get_focus()))
        await key(window, 'Down')
        await key(window, 'Return', 1.0)  # the first genre: the page starts over on it
        wanted = menu._choices[1].id if len(menu._choices) > 1 else None
        shelves = charts._column.widgets
        check('Down, Enter chooses the first genre: its charts, the focus on the menu',
              menu.genre == wanted and wanted
              and [widget.shelf.key for widget in shelves if widget.get_visible()]
              == ['charts-songs', 'charts-albums']
              and inside(window.get_focus(), drop_down),
              (menu.genre, [widget.shelf.key for widget in shelves], describe(
                  window.get_focus())))
    await key(window, 'Escape', 0.6)
    check('Escape goes back to the page it was opened from',
          window.navigation_view.get_visible_page() is not charts,
          window.navigation_view.get_visible_page())
    print('-- home')
    window.select_page('home')
    home = await shelves_shown(  # the demo's invented Recently Played among the shelves
        window, lambda page: page._recent.shelf in page._column.shelves)
    keys = [widget.shelf.key for widget in home._column.widgets if widget.get_visible()]
    check('Home shows Recently Played after its first shelf',
          keys[1:2] == ['recently-played'], keys)
    recent = home._column.widget_for(home._recent.shelf)
    await key(window, '<primary>2', 0.6)
    for _ in range(8):  # the first shelf's arrows, See All and cards, then Recently Played's
        if recent is None or inside(window.get_focus(), recent.list_view):
            break
        await key(window, 'Tab')
    check('Tab reaches Recently Played', recent is not None
          and inside(window.get_focus(), recent.list_view), describe(window.get_focus()))
    focus = window.get_focus()
    refreshed = []
    refresh = home.refresh
    home.refresh = lambda: (refreshed.append(True), refresh())
    await key(window, 'F5', 0.6)
    check('F5 refreshes Home, the focus staying on its tile',
          refreshed == [True] and window.get_focus() is focus, describe(window.get_focus()))
    check('Refresh is named', home.refresh_button.get_tooltip_text() == 'Refresh')
    home.refresh_button.grab_focus()
    await key(window, 'space', 0.6)
    check('Space on Refresh refreshes, the focus staying on it',
          refreshed == [True, True] and window.get_focus() is home.refresh_button,
          describe(window.get_focus()))
    home.refresh = refresh
    print('-- replay')
    from applemusic.widgets.explore import LinkChild

    link = next((child for child in descendants(home.explore_box)
                 if isinstance(child, LinkChild)), None)
    check("Home ends with More for You's link to Replay",
          link is not None and link.item.kind == 'replay', link and link.item.title)
    if link is not None:
        link.grab_focus()
        await key(window, 'Return', 1.0)
        replay = await shelves_shown(window)  # the demo's invented answer, then its shelves
        shelves = replay._column.widgets
        songs = shelves[0] if shelves else None
        check('Enter opens Replay: Top Songs a numbered grid of songs, then numbered tiles',
              getattr(replay, 'item', None) is link.item and isinstance(songs, SongShelf)
              and songs.shelf.ranked and len(shelves) == 4 and shelves[1].shelf.ranked,
              [widget.shelf.key for widget in shelves])
        if isinstance(songs, SongShelf):
            await key(window, '<primary>2', 0.6)
            for _ in range(3):  # the shelf's paging arrows and See All, then its songs
                if inside(window.get_focus(), songs.grid_view):
                    break
                await key(window, 'Tab')
            check('Ctrl+2 and Tab reach the first song',
                  inside(window.get_focus(), songs.grid_view), describe(window.get_focus()))
        drop_down = replay.year_menu.drop_down
        check('The header bar has the year menu, named, on the latest year',
              drop_down.get_visible() and drop_down.get_tooltip_text() == 'Year'
              and drop_down.get_selected() == 0, drop_down.get_selected())
        if drop_down.get_visible():
            drop_down.grab_focus()
            await key(window, 'Return', 0.6)  # opens the menu
            await key(window, 'Down')
            await key(window, 'Return', 1.0)  # the year before: the page starts over on it
            wanted = replay.year_menu._choices[1].id
            check('Down, Enter chooses the year before: its Replay, the focus on the menu',
                  replay.year_menu.year == wanted
                  and replay.title_label.get_label() == f'Replay {wanted}'
                  and inside(window.get_focus(), drop_down),
                  (replay.year_menu.year, replay.title_label.get_label(),
                   describe(window.get_focus())))
        await key(window, 'Escape', 0.6)
        check('Escape goes back to Home', window.navigation_view.get_visible_page() is home,
              window.navigation_view.get_visible_page())
    print('-- folders')
    tree = app.library.playlist_tree()
    folder = next(node for node in tree.flat if node.kind == 'folder' and node.children)
    child = folder.children[0]
    sidebar = window._sidebar
    window.select_page(f'folder:{folder.id}')
    await asyncio.sleep(0.6)
    await key(window, '<primary>1', 0.6)
    folder_row = sidebar.row(sidebar.item_for(f'folder:{folder.id}').get_index())
    check("Ctrl+1 puts the focus on the folder's row", window.get_focus() == folder_row,
          (describe(window.get_focus()), row_title(window.get_focus()),
           window.sidebar.get_selected(), len(sidebar.rows())))
    child_item = sidebar.item_for(f'{child.kind}:{child.id}')
    await key(window, 'Right', 0.4)
    check('Right opens the folder without changing the page',
          child_item.get_visible() and window.shown == f'folder:{folder.id}',
          (child_item.get_visible(), window.shown))
    await key(window, 'Down', 0.4)
    check("Down moves to the folder's first entry",
          window.get_focus() == sidebar.row(child_item.get_index()), describe(window.get_focus()))
    await key(window, 'Left', 0.4)
    check('Left moves back to the folder', window.get_focus() == folder_row,
          describe(window.get_focus()))
    await key(window, 'Left', 0.4)
    check('Left closes the folder', not child_item.get_visible())
    await key(window, 'Menu', 0.6)
    shown = [each for each in harness.popovers(folder_row) if isinstance(each, Gtk.PopoverMenu)]
    labels = menu_labels(shown[0].get_menu_model())[:2] if shown else []
    check("Menu on the folder's row opens its menu from the row (New Playlist…, New Folder…)",
          labels == ['Ne_w Playlist…', 'New _Folder…'], (labels, describe(window.get_focus())))
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back on the row',
          not any(each.get_visible() for each in shown) and window.get_focus() == folder_row,
          describe(window.get_focus()))
    await key(window, '<shift>F10', 0.6)
    shown = [each for each in harness.popovers(folder_row) if isinstance(each, Gtk.PopoverMenu)]
    check('Shift+F10 opens it too', bool(shown) and shown[0].get_visible())
    await key(window, 'Escape', 0.4)
    print('-- Move to Folder, New Folder')
    window.select_page('all-playlists')
    await asyncio.sleep(0.6)
    grid = window.navigation_view.get_visible_page()
    await key(window, '<primary>2', 0.6)  # the page shown, in the narrow layout too
    new_folder = [button for button in descendants(grid.header_bar)
                  if isinstance(button, Gtk.Button) and button.get_mapped()
                  and button.get_action_name() == 'win.item-new-folder']
    check('All Playlists has a New Folder button named "New Folder"',
          [button.get_tooltip_text() for button in new_folder] == ['New Folder'],
          ([button.get_tooltip_text() for button in new_folder], describe(window.get_focus())))
    found = None
    folder_movable = False
    for _step in range(8):  # past Favourite Songs and the folders, to a playlist
        found = context_menu.find(grid.grid_view, window.get_focus())
        movable = found is not None and window.item_actions.move_targets(found[1]) is not None
        if movable and found[1].kind == 'folder':
            folder_movable = True
        if movable and found[1].kind == 'playlist':
            break
        await key(window, 'Right', 0.3)
    check('Arrows pass folder tiles that can be moved, too', folder_movable)
    check('Arrows reach a playlist tile that can be moved',
          found is not None and found[1].kind == 'playlist', describe(window.get_focus()))
    await key(window, 'Menu', 0.6)
    shown = [each for each in harness.popovers(grid) if isinstance(each, Gtk.PopoverMenu)]
    moves = menu_submenu(shown[0].get_menu_model(), 'Mov_e to Folder') if shown else None
    labels = menu_labels(moves) if moves is not None else []
    check("Menu on it opens its menu, with Move to Folder's named folders and New Folder…",
          bool(labels) and all(labels) and labels[-1] == 'New _Folder…', labels)
    await key(window, 'Escape', 0.4)
    check('Escape closes it', not any(each.get_visible() for each in shown))
    print("-- a playlist's songs moved")
    await moving_songs(window)
    print("-- a playlist's songs selected")
    await selecting_songs(window)
    print("-- a playlist's song removed")
    await playlist_actions(window)
    print('-- Preferences')
    await key(window, '<primary>comma', 1.0)
    dialog = app._preferences
    check('Ctrl+, opens Preferences', dialog is not None)
    if dialog is not None:
        toplevel = dialog.get_root()
        if keyboard is not None:
            # Tab from a row stays on it in a window without the keyboard (GtkListBoxRow's
            # focus handler reads has-focus): only a real press makes a window active.
            visited = []
            for _ in range(4):
                await key(toplevel, 'Tab', 0.2)
                visited.append(toplevel.get_focus())
            check('Tab moves from row to row inside it',
                  len({id(widget) for widget in visited}) == len(visited)
                  and all(inside(widget, dialog) for widget in visited),
                  [describe(widget) for widget in visited])
        buttons = [widget for widget in descendants(dialog)
                   if isinstance(widget, Adw.ButtonRow)
                   or (isinstance(widget, Gtk.Button) and widget.get_label())]
        check('every labelled button in it has a mnemonic',
              buttons and all(button.get_use_underline() for button in buttons),
              [describe(button) for button in buttons if not button.get_use_underline()])
        # Clear refuses in the demo, here without the toast, which would take the next
        # Escape (a toast overlay's Escape dismisses its toast).
        clicks = []
        handler = dialog.clear_button.connect('clicked', lambda _button: clicks.append(True))
        app.refuse_in_demo = lambda: True
        handled = await key(toplevel, '<alt>l', 0)
        await until(lambda: clicks)  # the button clicks once its pressed state has shown
        del app.refuse_in_demo
        dialog.clear_button.disconnect(handler)
        check('Alt+L presses Clear', clicks == [True], (handled, clicks))
        await key(toplevel, 'Escape', 0.8)
        check('Escape closes it', app._preferences is None)
    print('-- Keyboard Shortcuts')
    await key(window, '<primary>question', 1.0)
    shown = dialog_shown(window, Adw.ShortcutsDialog)
    check('Ctrl+? opens Keyboard Shortcuts', shown is not None)
    if shown is not None:
        titles = {row.get_title() for row in descendants(shown)
                  if isinstance(row, Gtk.ListBoxRow) and hasattr(row, 'get_title')}
        wanted = {title for _section, items in shortcuts.sections() for title, _key in items}
        check('it lists every shortcut', titles == wanted, sorted(titles ^ wanted))
        await key(shown.get_root(), 'Escape', 0)
        await until(lambda: dialog_shown(window, Adw.ShortcutsDialog) is None)
        check('Escape closes it', dialog_shown(window, Adw.ShortcutsDialog) is None)
    print("-- a playlist's name dialog")
    from applemusic.dialogs.playlist import NameDialog

    playlist = first_playlist()
    target = GLib.Variant('(ss)', ('playlist', playlist.id))
    window.activate_action('win.item-rename', target)
    await asyncio.sleep(0.8)
    shown = dialog_shown(window, NameDialog)
    check('Rename… opens the name dialog', shown is not None)
    if shown is not None:
        toplevel = shown.get_root()
        check('the name has the focus', inside(toplevel.get_focus(), shown.name_row),
              describe(toplevel.get_focus()))
        # Rename refuses in the demo: recorded here, without the toast (which would take
        # the next Escape).
        refused = []
        app.refuse_in_demo = lambda: refused.append(True) or True
        await type_into(toplevel.get_focus(), 'Invented Name')
        await key(toplevel, 'Return', 0)
        await until(lambda: refused)
        del app.refuse_in_demo
        check('Enter in it renames', refused == [True], refused)
        await until(lambda: dialog_shown(window, NameDialog) is None)
        check('and closes it', dialog_shown(window, NameDialog) is None)
        window.activate_action('win.item-rename', target)
        await asyncio.sleep(0.8)
        shown = dialog_shown(window, NameDialog)
        if shown is not None:
            await key(shown.get_root(), 'Escape', 0)
        await until(lambda: dialog_shown(window, NameDialog) is None)
        check('Escape closes it, nothing renamed',
              dialog_shown(window, NameDialog) is None and playlist.title != 'Invented Name')
    await until(window.is_active)  # the keyboard back on the window, the dialog gone
    await key(window, '<primary>n', 0.8)
    await until(lambda: dialog_shown(window, NameDialog) is not None)
    shown = dialog_shown(window, NameDialog)
    check('Ctrl+N opens New Playlist, the name with the focus',
          shown is not None and shown.get_heading() == 'New Playlist'
          and inside(shown.get_root().get_focus(), shown.name_row),
          describe(shown.get_root().get_focus()) if shown is not None else None)
    if shown is not None:
        await key(shown.get_root(), 'Escape', 0)
    await until(lambda: dialog_shown(window, NameDialog) is None)
    check('Escape closes it', dialog_shown(window, NameDialog) is None)
    print('-- the confirmation before Remove from Library')
    album = app.library.albums.get_item(0)
    window.activate_action('win.item-remove-from-library',
                           GLib.Variant('(ss)', ('album', album.id)))
    await asyncio.sleep(0.8)
    shown = dialog_shown(window, Adw.AlertDialog)
    check('Remove from Library… asks first', shown is not None)
    if shown is not None:
        check('Cancel is the default, Remove destructive',
              shown.get_default_response() == 'cancel'
              and shown.get_response_appearance('confirm')
              == Adw.ResponseAppearance.DESTRUCTIVE)
        await key(shown.get_root(), 'Escape', 0)
        await until(lambda: dialog_shown(window, Adw.AlertDialog) is None)
        check('Escape closes it, nothing removed',
              dialog_shown(window, Adw.AlertDialog) is None
              and app.library.by_id('album', album.id) is album)
    print('-- a dialog over the window')
    # A dialog is inside the window only when the window is maximized or tiled (else it is
    # a window of its own, which the window's keys never reach).
    window.set_resizable(True)
    window.maximize()
    await until(window.is_maximized)
    await key(window, '<primary>comma', 1.0)
    dialog = app._preferences
    check('Preferences opens inside the maximized window',
          dialog is not None and window.get_visible_dialog() is dialog)
    if dialog is not None:
        on = [name for name in ('back', 'search', 'focus-sidebar', 'focus-content',
                                'focus-player', 'show-lyrics', 'show-queue', 'new-playlist',
                                'go-to-current-song')
              if window.lookup_action(name).get_enabled()]
        check("the window's keyed actions are off", not on, on)
        before = (window.shown, window.navigation_view.get_visible_page())
        actions = []
        handler = app.lookup_action('play-pause').connect(
            'activate', lambda action, _parameter: actions.append(action.get_name()))
        levels = []
        restore = watch('set_volume', levels)
        for accel in ('<alt>Left', '<primary>f', '<primary>1', '<primary>2', '<primary>3',
                      '<primary><shift>n', '<primary><shift>l', '<primary><shift>u', 'space',
                      '<primary>n', '<primary>l', '<primary>Up'):
            await key(window, accel, 0.3)
        restore()
        app.lookup_action('play-pause').disconnect(handler)
        after = (window.shown, window.navigation_view.get_visible_page())
        check('Alt+Left, Ctrl+F, Ctrl+1 to 3, Ctrl+Shift+N, L and U, Space, Ctrl+N, Ctrl+L '
              'and Ctrl+Up leave the page alone',
              after == before and not window.bottom_sheet.get_open() and not actions
              and not levels and window.get_visible_dialog() is dialog
              and inside(window.get_focus(), dialog),
              (after[0], window.bottom_sheet.get_open(), actions, levels,
               describe(window.get_focus())))
        await key(window, 'Escape', 0)
        await until(lambda: app._preferences is None)
        check('Escape closes it', app._preferences is None)
    window.unmaximize()
    await until(lambda: not window.is_maximized()
                and (window.get_width(), window.get_height()) == (width, height))
    window.set_resizable(False)


# -- names ---------------------------------------------------------------------------------

def focused_entry(queue_view):
    """The queue entry of the Up Next row with the focus, or None."""
    from applemusic.widgets import context_menu

    focus = queue_view.get_root().get_focus()
    found = context_menu.find(queue_view.list_view, focus) if focus is not None else None
    return found[0].entry if found is not None else None


async def up_next_remove(window, queue_view):
    """Up Next's Remove: the menu of an entry after the one playing offers it, and Delete
    takes the focused entry out (the Player's command stood in for: the demo has no engine,
    so the stand-in takes it out of the queue as the Player would), the focus moving to the
    entry that took its place; the entry playing stays. After the Delete, that entry's menu
    closed with Escape gives it the focus back. Leaves the focus on the first row."""
    player = app.player
    await key(window, 'Down')
    await key(window, 'Menu', 0.6)
    shown = harness.popovers(queue_view)
    labels = menu_labels(shown[0].get_menu_model()) if shown else []
    check("the next entry's menu offers Remove from Up Next",
          'Remove from Up Ne_xt' in labels, labels)
    await key(window, 'Escape', 0.4)
    removed = []

    async def remove(index, entry_id):
        removed.append((index, entry_id))
        player.queue.remove(index)
        player._renumber(index)
        return True
    player.remove_from_queue = remove
    before = focused_entry(queue_view)
    following = player.queue.get_item(2).id if player.queue.get_n_items() > 2 else None
    await key(window, 'Delete', 0.6)
    after = focused_entry(queue_view)
    check('Delete removes the focused entry',
          before is not None and removed == [(1, before.id)], removed)
    check('the focus goes to the entry that took its place',
          after is not None and after.id == following,
          after.title if after is not None else describe(window.get_focus()))
    await key(window, 'Up')
    await key(window, 'Delete', 0.4)
    check('Delete on the entry playing removes nothing', len(removed) == 1, removed)
    await key(window, 'Down')
    entry = focused_entry(queue_view)
    await key(window, 'Menu', 0.6)
    shown = harness.popovers(queue_view)
    check("after a Delete, Menu opens the next entry's menu", bool(shown))
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back on the entry',
          not any(each.get_visible() for each in shown) and entry is not None
          and focused_entry(queue_view) is entry, describe(window.get_focus()))
    await key(window, 'Up')
    del player.remove_from_queue


async def up_next_move(window, queue_view):
    """Up Next's moves: the next entry's menu offers Move Down (not Move Up: it is the first
    after the one playing), Alt+Down moves it one place with the focus on it and says where
    it went, Alt+Up moves it back, Alt+Up again moves nothing, nor does Alt+Down on the entry
    playing (the Player's own move_in_queue(), MusicKit's answer stood in for: the demo has
    no engine). Starts and leaves the focus on the first row."""
    player, engine = app.player, app.engine
    await key(window, 'Down')
    await key(window, 'Menu', 0.6)
    shown = harness.popovers(queue_view)
    labels = menu_labels(shown[0].get_menu_model()) if shown else []
    check("the next entry's menu offers Move Down, not Move Up",
          'Move _Down' in labels and '_Move Up' not in labels, labels)
    await key(window, 'Escape', 0.4)
    moves = []

    async def queue_move(index, to_index, entry_id, edit=None):
        moves.append((index, to_index))
    engine.queue_move = queue_move
    said = []
    window.announce = lambda text, _priority: said.append(text)
    entry = focused_entry(queue_view)
    count = player.queue.get_n_items() - player.queue_index - 1
    await key(window, '<alt>Down', 0.3)
    await until(lambda: entry is not None and entry.index == player.queue_index + 2
                and focused_entry(queue_view) is entry and bool(said))
    check('Alt+Down moves the focused entry one place down, the focus with it',
          entry is not None and entry.index == player.queue_index + 2
          and focused_entry(queue_view) is entry,
          (moves, describe(window.get_focus())))
    title = entry.title if entry is not None else ''
    check('and says where it went',
          said[-1:] == [f'“{title}” moved to position 2 of {count} in Up Next'], said)
    await key(window, '<alt>Up', 0.3)
    await until(lambda: entry is not None and entry.index == player.queue_index + 1
                and focused_entry(queue_view) is entry)
    check('Alt+Up moves it back up', entry is not None and entry.index == player.queue_index + 1
          and focused_entry(queue_view) is entry, (moves, describe(window.get_focus())))
    await key(window, '<alt>Up', 0.4)
    check('Alt+Up on the first entry after the one playing moves nothing', len(moves) == 2,
          moves)
    await key(window, 'Up')
    await key(window, '<alt>Down', 0.4)
    check('Alt+Down on the entry playing moves nothing', len(moves) == 2, moves)
    del window.announce
    del engine.queue_move


async def up_next_clear(window, queue_view):
    """Space on Clear (the focus on it): the Player's own clear_up_next() takes everything
    after the entry playing out of the queue (only MusicKit's answer stood in for: the demo
    has no engine), Clear goes insensitive, and the focus, which GTK would drop to the window,
    goes to the entry playing; Undo (the toast's action) puts the entries back."""
    player, engine = app.player, app.engine
    count = player.queue.get_n_items()
    calls = []

    async def queue_clear():
        calls.append('clear')
        return count - player.queue_index - 1

    async def queue_undo_clear():
        calls.append('undo')
        return count - player.queue_index - 1
    engine.queue_clear, engine.queue_undo_clear = queue_clear, queue_undo_clear
    playing = player.queue.get_item(player.queue_index)
    await key(window, 'space', 0.2)
    await until(lambda: calls and player.queue.get_n_items() == player.queue_index + 1)
    await asyncio.sleep(0.4)
    focus = window.get_focus()
    check('Space on Clear clears Up Next, and Clear goes insensitive',
          calls == ['clear'] and player.queue.get_n_items() == player.queue_index + 1
          and not queue_view.clear_button.get_sensitive(),
          (calls, player.queue.get_n_items()))
    check('the focus goes to the entry playing, on screen',
          focused_entry(queue_view) is playing and focus.get_mapped(), describe(focus))
    app.activate_action('undo-clear-up-next', None)
    await until(lambda: player.queue.get_n_items() == count)
    window.toast_overlay.dismiss_all()  # its Escape would close the toast, not a menu
    del engine.queue_clear, engine.queue_undo_clear
    check("the toast's Undo puts the entries back, the focus where it was",
          calls == ['clear', 'undo'] and player.queue.get_n_items() == count
          and queue_view.clear_button.get_sensitive()
          and focused_entry(queue_view) is playing, (calls, player.queue.get_n_items()))


async def up_next_history(window, queue_view):
    """History: a queue with entries played before the one playing (the invented one's
    history); Shift+Tab from Up Next back to the History toggle, Space shows them, the most
    recent first, Tab reaches them, their menu has no Remove from Up Next, Enter plays one
    again, and Space on the toggle goes back to Up Next. Leaves the focus in Up Next."""
    app.player.apply(harness.invented_playing_state(app, lyrics=True, history=True))
    current = app.player.queue_index
    await until(lambda: inside(window.get_focus(), queue_view.list_view))
    for _ in range(3):  # Clear, Autoplay, History
        await key(window, '<shift>Tab', 0.1)
    check('Shift+Tab from Up Next reaches History',
          window.get_focus() is queue_view.history_button, describe(window.get_focus()))
    await key(window, 'space', 0.4)
    await until(lambda: queue_view.lists.get_visible_child_name() == 'history')
    shown = queue_view.history_model
    check('Space on it shows History, the most recent first, without Autoplay and Clear',
          queue_view.history_shown and queue_view.lists.get_visible_child_name() == 'history'
          and shown.get_n_items() == current
          and shown.get_item(0) is app.player.queue.get_item(current - 1)
          and not queue_view.clear_button.get_visible(), shown.get_n_items())
    await key(window, 'Tab', 0.2)
    check('Tab reaches History', inside(window.get_focus(), queue_view.history_view),
          describe(window.get_focus()))
    await key(window, 'Menu', 0.6)
    popover = harness.popovers(queue_view)
    labels = menu_labels(popover[0].get_menu_model()) if popover else []
    check("Menu opens the entry's menu, without Remove from Up Next",
          bool(popover) and 'Remove from Up Ne_xt' not in labels, labels)
    await key(window, 'Escape', 0.4)
    check('Escape closes it, the focus back in History',
          inside(window.get_focus(), queue_view.history_view), describe(window.get_focus()))
    jumps = []
    undo = watch('queue_jump', jumps)
    await key(window, 'Down')
    await key(window, 'Return')
    undo()
    check('Down, Enter plays the entry played before the last one again',
          jumps == [current - 2], jumps)
    await key(window, '<shift>Tab', 0.1)
    check('Shift+Tab: the History toggle', window.get_focus() is queue_view.history_button,
          describe(window.get_focus()))
    await key(window, 'space', 0.4)
    await until(lambda: queue_view.lists.get_visible_child_name() == 'up-next')
    check('Space on it goes back to Up Next',
          not queue_view.history_shown and queue_view.clear_button.get_visible()
          and queue_view.lists.get_visible_child_name() == 'up-next')
    queue_view.list_view.grab_focus()


async def now_playing_tabs(window):
    """Lyrics and Up Next: Ctrl+Shift+U and Ctrl+Shift+L open Now Playing on that tab, switch
    it while it is open and close it on the tab it shows, the bar's toggles pressed for the
    tab in sight; the bar's Up Next button (where the bar has room for it) opens it too, and
    the focus comes back to it; from the full-screen player, back to the sheet on the tab."""
    print('-- Lyrics and Up Next')
    sheet = window.now_playing
    bar = window.player_bar
    await key(window, '<primary><shift>u', 0.8)
    await until(lambda: window.bottom_sheet.get_open())
    check("Ctrl+Shift+U opens Now Playing on Up Next, the bar's Up Next pressed",
          window.bottom_sheet.get_open() and sheet.shown_tab == 'queue'
          and bar.queue_button.get_active() and not bar.lyrics_button.get_active(),
          sheet.shown_tab)
    await key(window, '<primary><shift>l', 0.4)
    check('Ctrl+Shift+L switches it to Lyrics',
          window.bottom_sheet.get_open() and sheet.shown_tab == 'lyrics'
          and bar.lyrics_button.get_active() and not bar.queue_button.get_active(),
          sheet.shown_tab)
    await key(window, '<primary><shift>l', 0.8)
    await until(lambda: not window.bottom_sheet.get_open())
    check('Ctrl+Shift+L on Lyrics closes it, neither toggle pressed',
          not window.bottom_sheet.get_open() and not bar.lyrics_button.get_active()
          and window.get_focus() is not None and window.get_focus().get_mapped(),
          describe(window.get_focus()))
    if bar.queue_button.get_mapped():
        bar.queue_button.grab_focus()
        await key(window, 'space', 0.8)
        await until(lambda: window.bottom_sheet.get_open())
        check("Space on the bar's Up Next opens Now Playing on Up Next",
              window.bottom_sheet.get_open() and sheet.shown_tab == 'queue', sheet.shown_tab)
        await key(window, 'Escape', 0.8)
        await until(lambda: not window.bottom_sheet.get_open()
                    and window.get_focus() is bar.queue_button)
        check('Escape closes it, the focus back on Up Next',
              not window.bottom_sheet.get_open() and window.get_focus() is bar.queue_button,
              describe(window.get_focus()))
    else:
        check('the narrow bar leaves Lyrics and Up Next to the sheet (the title keeps the room)',
              not bar.lyrics_button.get_mapped() and bar.props.narrow)
    host = window.fullscreen_host
    await key(window, 'F11', 0.8)
    await until(lambda: host.shown)
    await key(window, '<primary><shift>u', 0.8)
    await until(lambda: not host.shown and window.bottom_sheet.get_open())
    check('Ctrl+Shift+U in the full-screen player: back to Now Playing, on Up Next',
          not host.shown and window.bottom_sheet.get_open() and sheet.shown_tab == 'queue',
          (host.shown, sheet.shown_tab))
    await key(window, 'Escape', 0.8)
    await until(lambda: not window.bottom_sheet.get_open())
    sheet.show_tab('lyrics')  # as the steps after these found it


async def fullscreen_player(window):
    """The full-screen player: F11 in, the focus on its play button, Tab through it and
    never out of it, Space and Enter on a line, Escape out, the window and the focus as they
    were; then in from Now Playing's Fullscreen and out with F11, back on that button."""
    print('-- full-screen player')
    host = window.fullscreen_host
    sheet = window.now_playing
    resting = window.get_focus()
    size, maximized = window.get_default_size(), window.is_maximized()
    await key(window, 'F11', 0.8)
    await until(lambda: host.shown and window.get_focus() is host.view.play_button)
    check('F11 shows the full-screen player, the focus on its play button',
          host.shown and window.is_fullscreen() and window.get_focus() is host.view.play_button,
          describe(window.get_focus()))
    stayed, lines = True, False
    for _ in range(16):
        await key(window, 'Tab', 0.05)
        stayed = stayed and inside(window.get_focus(), host.view)
        lines = lines or inside(window.get_focus(), sheet.lyrics_view.list_view)
        if lines:
            break
    check('Tab goes through its controls to the lyrics, never out of it',
          stayed and lines and window.get_focus().get_mapped(), describe(window.get_focus()))
    actions = []
    action = app.lookup_action('play-pause')
    handler = action.connect('activate', lambda *_: actions.append('play-pause'))
    await key(window, 'space')
    action.disconnect(handler)
    host.view.toast_overlay.dismiss_all()  # the demo's "not available", which Escape closes
    seeks = []
    undo = watch('seek', seeks)
    await key(window, 'Down')
    await key(window, 'Return')
    undo()
    check('Space on a line plays or pauses, Enter seeks to it',
          actions == ['play-pause'] and len(seeks) == 1, (actions, seeks))
    await key(window, 'Escape', 0.8)
    await until(lambda: not host.shown and window.get_focus() is resting)
    check('Escape leaves it: the window and the focus as they were',
          not host.shown and not window.is_fullscreen()
          and window.get_default_size() == size and window.is_maximized() == maximized
          and window.get_focus() is resting, describe(window.get_focus()))
    await key(window, '<primary><shift>n', 0.8)
    sheet.fullscreen_button.grab_focus()
    await key(window, 'Return', 0.8)
    await until(lambda: host.shown)
    check("Now Playing's Fullscreen shows it", host.shown)
    await key(window, 'F11', 0.8)
    await until(lambda: not host.shown and window.get_focus() is sheet.fullscreen_button)
    check('F11 leaves it, back in Now Playing on Fullscreen',
          not host.shown and window.bottom_sheet.get_open()
          and window.get_focus() is sheet.fullscreen_button, describe(window.get_focus()))
    await key(window, 'Escape', 0.8)
    await until(lambda: not window.bottom_sheet.get_open())


async def mini_player(window):
    """The mini player: Ctrl+Shift+M in, the window hidden, the focus on its Play; Tab
    through its controls and never out of it; Space plays or pauses, Ctrl+Right skips; Ctrl+Shift+M
    back to the window, the focus as it was; in again, and Ctrl+W (its close) back too."""
    print('-- mini player')
    host = app.mini_player
    resting = window.get_focus()
    await key(window, '<primary><shift>m', 0.8)
    await until(lambda: host.shown and host.window.get_focus() is host.window.view.play_button)
    mini = host.window
    view = mini.view if mini is not None else None
    check('Ctrl+Shift+M shows the mini player in place of the window, the focus on Play',
          mini is not None and mini.get_mapped() and not window.get_visible()
          and mini.get_focus() is view.play_button,
          describe(mini.get_focus() if mini is not None else None))
    if mini is None:
        return
    if keyboard is not None:
        await until(mini.is_active, 3.0)
    seen, stayed = set(), True
    for _ in range(6):
        await key(mini, 'Tab', 0.05)
        focus = mini.get_focus()
        stayed = stayed and inside(focus, view)
        seen.add(focus)
    check('Tab goes through Return to Main Window, the slider and the transport, never out',
          stayed and {view.main_window_button, view.seek_scale, view.previous_button,
                      view.play_button, view.next_button} <= seen,
          sorted(describe(widget) for widget in seen))
    view.play_button.grab_focus()
    actions = []
    handlers = [(app.lookup_action(name), app.lookup_action(name).connect(
        'activate', lambda _action, _parameter, name=name: actions.append(name)))
        for name in ('play-pause', 'next')]
    await key(mini, 'space')
    view.seek_scale.grab_focus()
    await key(mini, 'space')
    await key(mini, '<primary>Right')
    for action, handler in handlers:
        action.disconnect(handler)
    view.toast_overlay.dismiss_all()  # the demo's "not available"
    expected = ['play-pause', 'play-pause'] + (
        ['next'] if app.lookup_action('next').get_enabled() else [])
    check('Space on Play and on the slider plays or pauses, Ctrl+Right skips',
          actions == expected, actions)
    await key(mini, '<primary><shift>m', 0.8)
    await until(lambda: not host.shown and window.get_visible())
    check('Ctrl+Shift+M there: back to the window, the focus as it was',
          not host.shown and window.get_mapped() and window.get_focus() is resting,
          describe(window.get_focus()))
    await key(window, '<primary><shift>m', 0.8)
    await until(lambda: host.shown and host.window.get_focus() is not None)
    if keyboard is not None and host.window is not None:
        await until(host.window.is_active, 3.0)
    await key(host.window or window, '<primary>w', 0.8)
    await until(lambda: not host.shown and window.get_visible())
    check('Ctrl+W closes it: back to the window', not host.shown and window.get_mapped())
    if keyboard is not None:
        await until(window.is_active, 3.0)


async def unnamed(label):
    process = Gio.Subprocess.new([sys.executable, os.path.abspath(__file__), '--dump'],
                                 Gio.SubprocessFlags.STDOUT_PIPE
                                 | Gio.SubprocessFlags.STDERR_SILENCE)
    _ok, out, _err = await process.communicate_utf8_async(None, None)
    lines = [line for line in (out or '').splitlines() if line]
    print(f'{label}: {len(lines)} unnamed' + ''.join(f'\n    {line}' for line in lines))
    return len(lines)


async def names(window):
    print('-- accessible names (focusable controls without one)')
    total = 0
    app.settings.set_boolean('show-genres', True)  # Genres listed, as Preferences offers
    app.settings.set_strv('song-columns', ['genre', 'year'])  # and the optional columns
    for page in ('home', 'new', 'albums', 'artists', 'songs', 'genres', 'radio',
                 'all-playlists', 'favourite-songs'):
        window.select_page(page)
        window.split_view.set_show_content(True)
        await asyncio.sleep(1.0)
        total += await unnamed(page)
    app.settings.reset('show-genres')
    app.settings.reset('song-columns')
    for kind, store in (('album', app.library.albums), ('playlist', app.library.playlists),
                        ('artist', app.library.artists)):
        window.open_item(store.get_item(0))  # an artist: the library's page of them
        await asyncio.sleep(1.0)
        total += await unnamed(kind)
    window.select_page('songs')
    await asyncio.sleep(1.0)
    mode = window.navigation_view.get_visible_page().selection_mode
    mode.key('select-all')  # the header bar's count and Cancel, and the bar's actions
    await asyncio.sleep(0.6)
    total += await unnamed('songs, selecting')
    mode.leave()
    window.open_artist_page(app.library.artists.get_item(0))
    await asyncio.sleep(1.5)
    total += await unnamed("artist's page")
    from applemusic.explore import link_item

    for kind, item_id in (('room', 'demo.room01'), ('grouping', 'demo.grouping01')):
        window.open_item(link_item({'title': f'Invented {kind}', 'kind': kind, 'id': item_id}))
        await asyncio.sleep(1.0)
        total += await unnamed(f"a More to Explore link's {kind}")
    from applemusic.pages.charts import charts_item

    window.open_item(charts_item())
    await asyncio.sleep(1.0)
    total += await unnamed('Charts')
    drop_down = window.navigation_view.get_visible_page().genre_menu.drop_down
    drop_down.emit('activate')  # the genre menu open: its genres, each named
    await asyncio.sleep(1.0)
    total += await unnamed("Charts' genre menu, open")
    for widget in descendants(drop_down):
        if isinstance(widget, Gtk.Popover):
            widget.popdown()
    await asyncio.sleep(0.5)
    from applemusic.pages.replay import replay_item

    window.open_item(replay_item())
    await asyncio.sleep(1.0)
    total += await unnamed('Replay')
    drop_down = window.navigation_view.get_visible_page().year_menu.drop_down
    drop_down.emit('activate')  # the year menu open: its years, each named
    await asyncio.sleep(1.0)
    total += await unnamed("Replay's year menu, open")
    for widget in descendants(drop_down):
        if isinstance(widget, Gtk.Popover):
            widget.popdown()
    await asyncio.sleep(0.5)
    window.select_page('search')
    await asyncio.sleep(0.5)
    search = window.navigation_view.get_visible_page()
    search.set_mode('library')
    search.search_entry.set_text('the')
    await asyncio.sleep(1.5)
    total += await unnamed('search')
    search.set_mode('music')
    search.set_kind('songs')
    search.search_entry.set_text('tide')
    search.search_entry.emit('activate')
    await asyncio.sleep(1.5)
    total += await unnamed("search's list of one kind")
    search.kind_dropdown.emit('activate')  # Show Results Of open: its kinds, each named
    await asyncio.sleep(1.0)
    total += await unnamed("search's Show Results Of, open")
    for widget in descendants(search.kind_dropdown):
        if isinstance(widget, Gtk.Popover):
            widget.popdown()
    await asyncio.sleep(0.5)
    search.set_kind('all')
    await asyncio.sleep(1.5)
    window.open_shelf(next(shelf for shelf in search._column.shelves if shelf.key == 'songs'))
    await asyncio.sleep(1.5)
    total += await unnamed("search's See All")
    window.navigation_view.pop()
    await asyncio.sleep(0.5)
    app.player.apply(harness.invented_playing_state(app))
    window.bottom_sheet.set_open(True)
    await asyncio.sleep(1.0)
    total += await unnamed('Now Playing')
    window.bottom_sheet.set_open(False)
    window.activate_action('win.fullscreen-player', None)
    await asyncio.sleep(1.0)
    total += await unnamed('Fullscreen Player')
    window.activate_action('win.fullscreen-player', None)
    await asyncio.sleep(0.5)
    app.activate_action('mini-player', None)
    await asyncio.sleep(1.0)
    total += await unnamed('Mini Player')
    app.activate_action('mini-player', None)
    await asyncio.sleep(0.8)
    dialog = app.show_preferences()
    await asyncio.sleep(1.0)
    total += await unnamed('Preferences')
    dialog.set_visible_page_name('engine')
    await asyncio.sleep(0.5)
    total += await unnamed('Preferences, Engine')
    dialog.close()
    await asyncio.sleep(0.5)
    app.activate_action('shortcuts')
    await asyncio.sleep(1.0)
    total += await unnamed('Keyboard Shortcuts')
    shortcuts_shown = dialog_shown(window, Adw.ShortcutsDialog)
    if shortcuts_shown is not None:
        shortcuts_shown.force_close()
        await asyncio.sleep(0.5)
    window.activate_action('win.item-rename',
                           GLib.Variant('(ss)', ('playlist', first_playlist().id)))
    await asyncio.sleep(1.0)
    total += await unnamed('Rename Playlist')
    from applemusic.dialogs.playlist import NameDialog

    renamed = dialog_shown(window, NameDialog)
    if renamed is not None:
        renamed.force_close()
        await asyncio.sleep(0.5)
    from applemusic.dialogs.add_songs import AddSongsDialog

    window.activate_action('win.item-add-songs',
                           GLib.Variant('(ss)', ('playlist', first_playlist().id)))
    await asyncio.sleep(1.5)
    adding = dialog_shown(window, AddSongsDialog)
    if adding is not None:
        adding.library_view.emit('activate', 0)  # a song picked: its row and the count
        await asyncio.sleep(0.5)
        total += await unnamed('Add Songs')
        adding.scope_toggle.set_active_name('catalog')
        adding.search_entry.set_text('tide')
        await asyncio.sleep(1.5)
        total += await unnamed("Add Songs, Apple Music's")
        adding.force_close()
        await asyncio.sleep(0.5)
    else:
        check('Add Songs… opens its dialog', False)
    album = app.library.albums.get_item(0)
    song = album.groups[0].entries.get_item(0)
    window.item_actions.menu_for(song)  # the menu names the song its action finds
    window.activate_action('win.item-view-credits', GLib.Variant('(ss)', ('song', song.id)))
    await asyncio.sleep(1.0)
    total += await unnamed('View Credits')
    print(f'{total} unnamed in all')


# -- running -------------------------------------------------------------------------------

async def run():
    try:
        while app.library.props.state != 'ready':
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.0)
        window = app.get_active_window()
        if keyboard is not None:
            # A real press goes wherever the compositor points the keyboard, and it points it
            # at the window only once there is something to deliver: Shift on its own, then
            # the window is active and no step's first key is lost.
            keyboard.nudge()
            check('the window takes the keyboard', await until(window.is_active, 5.0))
        if args.step == 'radio':
            await radio_step(window)
        else:
            await walkthrough(window)
        if args.names and not args.step:
            await names(window)
    except Exception as error:  # a step that raised is a failure too
        import traceback
        traceback.print_exc()
        failures.append(repr(error))
    finally:
        app.quit()


def on_activate(_app):
    app.settings.set_string('last-page', 'home')
    app.settings.set_strv('expanded-folders', [])
    app.spawn(run())


app.connect('activate', on_activate)
harness.run_app(app)
print(f'{len(failures)} failed' if failures else 'all passed')
sys.exit(1 if failures else 0)
