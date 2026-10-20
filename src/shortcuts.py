# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The keyboard shortcuts in one table: the accelerators the app sets, the playback keys the
window handles itself, and the Keyboard Shortcuts dialog, which lists them all.

main.py sets ACCELS with Gtk.Application.set_accels_for_action and builds the dialog from
sections(); keyboard.py parses PLAYBACK into its PLAYBACK_KEYS, NOW_PLAYING_TABS into its
TAB_KEYS and MAIN_MENU into the window's F10, widgets/context_menu.py binds CONTEXT_MENU,
and sidebar_view.py binds FOLDER_OPEN and FOLDER_CLOSE on the sidebar (keys for the focused
row, only with the focus in the sidebar), as widgets/queue.py binds QUEUE_REMOVE on Up Next's
list; a playlist's page runs MOVE_UP and MOVE_DOWN on its focused song (keyboard.move_step():
Alt+Up and Alt+Down, as GNOME Text Editor moves a line), and keyboard.py parses VOLUME_UP and
VOLUME_DOWN into its VOLUME_KEYS, the window's too. tests/test_shortcuts.py checks that the
dialog lists every one of them. Keys that are none of these are listed as they are: Escape
(the dialogs', the Now Playing sheet's, the full-screen player's), under General with the
other keys that act on windows.

F11 and F5 are the accelerators without a modifier: function keys, which no GTK widget takes
for its own, set as accelerators by GNOME's own apps: F11 the HIG's Fullscreen key (the
window's action is disabled while nothing plays), F5 Refresh, the page's own (Home, New, Made
for You, Radio, Charts, a category: the action is disabled on a page without one). Ctrl+R,
which GNOME's apps also give Refresh, is Refresh Library here (app.sync), the sync of
everything.

The playback keys are not accelerators: GTK 4 runs application accelerators in the window's
capture phase, before the focus widget, so a bare Space would fire while typing in an entry
and Ctrl+Left would skip a track instead of a word (see keyboard.playback_action). Nor are
the volume keys (Ctrl+Up, Ctrl+Down: a text view's paragraph keys, a slider's page step, a
boxed list's or the sidebar's way to move the focus without selecting; keyboard.volume_step).
The accelerators keep off the HIG's standard ones the app has no use for, and Ctrl+N is the
HIG's "New" here: New Playlist. Ctrl+L is Go to Current Song, as on Apple's players (no
text field of GTK's has a Ctrl+L).
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
    'win.new-playlist': ('<primary>n',),
    'win.go-to-current-song': ('<primary>l',),
    'window.close': ('<primary>w',),
    'win.back': ('<alt>Left',),
    'win.search': ('<primary>f',),
    'win.refresh': ('F5',),
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
# On a focused Up Next row (widgets/queue.py binds it on the list): Remove from Up Next.
QUEUE_REMOVE = 'Delete'
# On a focused song of a playlist of the user's: move it up or down one place.
MOVE_UP = '<alt>Up'
MOVE_DOWN = '<alt>Down'
# Anywhere in the window while something plays (keyboard.volume_step): the volume up or down
# a step (widgets/transport.VOLUME_STEP), announced.
VOLUME_UP = '<primary>Up'
VOLUME_DOWN = '<primary>Down'


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
            (_('Go to Current Song'), 'win.go-to-current-song'),
            (_('Refresh the Page'), 'win.refresh'),
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
            (_('Volume Up'), VOLUME_UP),
            (_('Volume Down'), VOLUME_DOWN),
            (_('Show or Hide Now Playing'), 'app.now-playing'),
            (_('Show or Hide Lyrics'), 'show-lyrics'),
            (_('Show or Hide Up Next'), 'show-queue'),
            (_('Remove from Up Next'), QUEUE_REMOVE),
            (_('Fullscreen Player'), 'win.fullscreen-player'),
        ]),
        (_('Playlists'), [
            (_('New Playlist'), 'win.new-playlist'),
            (_('Move Song Up'), MOVE_UP),
            (_('Move Song Down'), MOVE_DOWN),
        ]),
    ]
