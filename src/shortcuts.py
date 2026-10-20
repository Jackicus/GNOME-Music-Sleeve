# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The keyboard shortcuts in one table: the accelerators the app sets, the playback keys the
window handles itself, and the Keyboard Shortcuts dialog, which lists them all.

main.py sets ACCELS with Gtk.Application.set_accels_for_action and builds the dialog from
sections(); keyboard.py parses PLAYBACK into its PLAYBACK_KEYS, NOW_PLAYING_TABS into its
TAB_KEYS and MAIN_MENU into the window's F10, widgets/context_menu.py binds CONTEXT_MENU,
and sidebar_view.py binds FOLDER_OPEN and FOLDER_CLOSE on the sidebar (keys for the focused
row, only with the focus in the sidebar). tests/test_shortcuts.py checks that the dialog
lists every one of them. Keys that are none of
these are listed as they are: Escape (the dialogs', the Now Playing sheet's, the full-screen
player's), under General with the other keys that act on windows.

F11 is the one accelerator without a modifier: a function key, which no GTK widget takes for
its own, the HIG's Fullscreen key, set as an accelerator by GNOME's own apps; the window's
action does nothing while nothing plays (it is disabled).

The playback keys are not accelerators: GTK 4 runs application accelerators in the window's
capture phase, before the focus widget, so a bare Space would fire while typing in an entry
and Ctrl+Left would skip a track instead of a word (see keyboard.playback_action). The
accelerators keep off the HIG's standard ones the app has no use for (Ctrl+N is "New").
Nor are the keys that open Now Playing on its Lyrics or Up Next tab (NOW_PLAYING_TABS):
Ctrl+Shift+U is GTK's Unicode entry in a text field, so the window's key controller runs
them only while the focus is not typed into (keyboard.tab_action), and Ctrl+Shift+L goes
with it.
"""

from gettext import gettext as _

# Action -> its accelerators (Gtk.Application.set_accels_for_action).
ACCELS = {
    'app.quit': ('<primary>q',),
    'app.shortcuts': ('<primary>question',),
    'app.preferences': ('<primary>comma',),
    'app.sync': ('<primary>r',),
    'app.now-playing': ('<primary><shift>n',),
    'window.close': ('<primary>w',),
    'win.back': ('<alt>Left',),
    'win.search': ('<primary>f',),
    'win.focus-sidebar': ('<primary>1',),
    'win.focus-content': ('<primary>2',),
    'win.focus-player': ('<primary>3',),
    'win.fullscreen-player': ('F11',),
}

# App action (without "app.") -> the keys the window's own key controller maps to it.
PLAYBACK = {
    'play-pause': ('space', 'KP_Space'),
    'next': ('<primary>Right',),
    'previous': ('<primary>Left',),
}

# Window action (without "win.") -> the keys the window's key controller maps to it: the
# Now Playing sheet on its Lyrics or Up Next tab, or closed when it shows that tab already
# (widgets/now_playing.py's TabActions; the player bar's Lyrics and Up Next buttons).
NOW_PLAYING_TABS = {
    'show-lyrics': ('<primary><shift>l',),
    'show-queue': ('<primary><shift>u',),
}

MAIN_MENU = 'F10'
CONTEXT_MENU = 'Menu <shift>F10'
CLOSE = 'Escape'
# On a focused sidebar row: open or close a folder (Left on an entry inside one moves to it).
FOLDER_OPEN = 'Right'
FOLDER_CLOSE = 'Left'


def accelerator(key):
    """What the dialog shows for `key`: an action's accelerators (ACCELS), a playback action's
    first key (PLAYBACK), a Now Playing tab's (NOW_PLAYING_TABS), or `key` itself, an
    accelerator string (alternatives separated by spaces, as Adw.ShortcutLabel takes them)."""
    if key in ACCELS:
        return ' '.join(ACCELS[key])
    if key in PLAYBACK:
        return PLAYBACK[key][0]
    if key in NOW_PLAYING_TABS:
        return NOW_PLAYING_TABS[key][0]
    return key


def sections():
    """The dialog's sections, translated on call: [(title, [(title, key)])], each key as
    accelerator() takes it."""
    return [
        (_('General'), [
            (_('Show Main Menu'), MAIN_MENU),
            (_('Preferences'), 'app.preferences'),
            (_('Refresh Library'), 'app.sync'),
            (_('Keyboard Shortcuts'), 'app.shortcuts'),
            (_('Close Dialog, Now Playing or Fullscreen'), CLOSE),
            (_('Close Window'), 'window.close'),
            (_('Quit'), 'app.quit'),
        ]),
        (_('Navigation'), [
            (_('Search or Filter'), 'win.search'),
            (_('Go Back'), 'win.back'),
            (_('Focus the Sidebar'), 'win.focus-sidebar'),
            (_('Focus the Page'), 'win.focus-content'),
            (_('Focus the Player Bar'), 'win.focus-player'),
            (_('Show Context Menu'), CONTEXT_MENU),
            (_('Open Sidebar Folder'), FOLDER_OPEN),
            (_('Close Sidebar Folder'), FOLDER_CLOSE),
        ]),
        (_('Playback'), [
            (_('Play or Pause'), 'play-pause'),
            (_('Next'), 'next'),
            (_('Previous'), 'previous'),
            (_('Show or Hide Now Playing'), 'app.now-playing'),
            (_('Show or Hide Lyrics'), 'show-lyrics'),
            (_('Show or Hide Up Next'), 'show-queue'),
            (_('Fullscreen Player'), 'win.fullscreen-player'),
        ]),
    ]
