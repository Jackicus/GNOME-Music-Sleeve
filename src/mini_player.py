# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The mini player: a small window of its own with the item playing, in place of the main
window. Its layout as a pure function, and its host, the app's way in and out of it.

    host = MiniPlayerHost(app)    app.mini_player
    host.toggle()                 app.mini-player (the main menu's Mini Player, the player
                                  bar's menu, Ctrl+Shift+M; Return to Main Window there)
    host.enter()                  the mini player shown, the main window hidden
    host.leave()                  the main window back, the mini player gone
    host.quit()                   the mini player gone, the main window left as it is
    host.shown, host.window       whether it shows; the window (widgets/mini_player.py)

One instance at a time: entering while it shows presents it. The window is built as it
enters (its module imported then, never at startup) and destroyed as it leaves, its pieces
letting go of the Player first, so nothing follows the Player for it while it is closed. The
main window hides as it shows (Window.put_away(): out of the full-screen player, its dialogs
closed, its state saved) and is presented again as it leaves, as it was. Closing the mini
player is leaving it: the main window comes back (the issue's choice, docs/decisions.md),
whatever background playback says, since a close there only puts the music back in its
window. The mini player's size is the mini-player-width and mini-player-height settings,
written as it leaves.

GNOME on Wayland offers an app no way to keep a window above the others, so it is an
ordinary window: it does not promise to stay on top.
"""

from collections import namedtuple

# The layout's measures, in px of the content under the header bar.
MARGIN = 18            # the sides and the bottom
TOP_MARGIN = 6         # under the header bar
# The height the titles, the seek row and the transport take under the cover, with their
# spacing and the bottom margin.
BELOW_ART = 170
MIN_ART = 128          # smaller than this over the titles: the short layout
MAX_ART = 640          # the cover file's size (backend config.COVER_SIZE)
SMALL_ART = 56         # the short layout's cover, beside the titles

Layout = namedtuple('Layout', 'short art_size')


def layout_for(width, height):
    """The mini player's Layout for content `width` x `height` px: `art_size`, the cover's
    edge over the titles, as large as the width and the room over the controls leave (a
    multiple of 8, at most the cover file's); or, when that is less than MIN_ART, `short`:
    a SMALL_ART cover beside the titles."""
    room = height - TOP_MARGIN - BELOW_ART
    across = width - 2 * MARGIN
    size = int(min(room, across, MAX_ART)) // 8 * 8
    if size < MIN_ART:
        return Layout(True, SMALL_ART)
    return Layout(False, size)


def _make_window(app):
    from .widgets.mini_player import MiniPlayer

    window = MiniPlayer(application=app)
    window.set_player(app.player, app)
    return window


class MiniPlayerHost:
    """See the module. `app` has `settings` and `main_window()` (the main window, hidden or
    not); `make_window(app)` makes the window (widgets/mini_player.MiniPlayer, following the
    app's Player), which has `release()` (its pieces detached, then destroyed)."""

    def __init__(self, app, make_window=None):
        self._app = app
        self._make_window = make_window or _make_window
        self.window = None

    @property
    def shown(self):
        return self.window is not None

    def toggle(self):
        """The mini player, or back from it."""
        if self.shown:
            self.leave()
        else:
            self.enter()

    def enter(self):
        """Show the mini player at its size and hide the main window; the one shown
        already is presented."""
        if self.window is not None:
            self.window.present()
            return
        settings = self._app.settings
        window = self._make_window(self._app)
        window.set_default_size(settings.get_int('mini-player-width'),
                                settings.get_int('mini-player-height'))
        self.window = window
        window.present()
        main = self._app.main_window()
        if main is not None:
            main.put_away()

    def leave(self):
        """The main window presented again, the mini player closed (its size kept)."""
        window = self._take()
        if window is None:
            return
        main = self._app.main_window()
        if main is not None:
            main.present()
        window.release()

    def quit(self):
        """The app quits: the mini player closed (its size kept), the main window left
        hidden."""
        window = self._take()
        if window is not None:
            window.release()

    def _take(self):
        window, self.window = self.window, None
        if window is not None:
            width, height = window.get_default_size()
            if width > 0 and height > 0:
                self._app.settings.set_int('mini-player-width', width)
                self._app.settings.set_int('mini-player-height', height)
        return window
