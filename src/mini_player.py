# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The mini player: a small window of its own with the item playing, in place of the main
window. Its layout as a pure function, its panes, and its host, the app's way in and out of
it.

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

Lyrics and Up Next are a pane under its controls, one at a time (Panes): off until asked
for, the window growing by the pane's height (mini-player-pane-height) as one opens and
back as it closes, so mini-player-height stays the height without one; the pane open is
remembered (mini-player-pane) and opened again the next time. What a pane shows is not the
mini player's: the app has one LyricsView and one QueueView, the Now Playing sheet's, which
follow the Player for the app's life, and the sheet lends them (lend_lyrics(), lend_queue())
as it lends the lyrics to the full-screen player. The sheet's window being hidden, the host
covers the sheet as it enters (set_covered(): its views inactive) and uncovers it as it
leaves, a view lent given back first, so one place at a time makes a view active and no
view is ever in a window being destroyed.

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
# The extras (Favourite, Shuffle, Repeat, Volume), as the widgets measure with the app's
# stylesheet: the height a row of them takes under the transport, with its spacing (34 and
# 12); the height the short layout takes without it, margins and all (169); and the width
# from which the seven buttons fit in one row (336 and the side margins).
EXTRAS_ROW = 46
SHORT_HEIGHT = 170
INLINE_WIDTH = 372

Layout = namedtuple('Layout', 'short art_size extras')


def layout_for(width, height):
    """The mini player's Layout for content `width` x `height` px. `extras`, where
    Favourite, Shuffle, Repeat and Volume go: 'inline', around Previous, Play and Next, from
    INLINE_WIDTH; in a narrower window a 'row' of their own under the transport when the
    height has room for it under the short layout, else 'none' (hidden: a window both low
    and narrow keeps the transport). `art_size`, the cover's edge over the titles, as large
    as the width and the room over the controls leave (a multiple of 8, at most the cover
    file's); or, when that is less than MIN_ART, `short`: a SMALL_ART cover beside the
    titles. The controls outrank the cover: a row that fits is shown, over a smaller
    cover."""
    if width >= INLINE_WIDTH:
        extras = 'inline'
    elif height >= SHORT_HEIGHT + EXTRAS_ROW:
        extras = 'row'
    else:
        extras = 'none'
    room = height - TOP_MARGIN - BELOW_ART - (EXTRAS_ROW if extras == 'row' else 0)
    across = width - 2 * MARGIN
    size = int(min(room, across, MAX_ART)) // 8 * 8
    if size < MIN_ART:
        return Layout(True, SMALL_ART, extras)
    return Layout(False, size, extras)


# The panes: their names (the sheet's tabs'), and the least height one is given.
PANES = ('lyrics', 'queue')
PANE_MIN = 160


def split(height, base, pane_min=PANE_MIN):
    """(body, pane): how a window `height` px high with a pane open divides, `base` its
    height without one. The body keeps `base` and the pane has the rest, what the window
    grew by and whatever the user has dragged it by since; a window too low for that gives
    the pane `pane_min` and the body what is left. Also what is remembered of a window
    resized with a pane open: its height without the pane, and the pane's."""
    pane = height - base
    if pane < pane_min:
        pane = min(pane_min, max(height, 0))
        return max(height - pane, 0), pane
    return base, pane


class Panes:
    """The mini player's pane: which shows (`shown`: '', 'lyrics' or 'queue'), the lending
    and the window's size. No GTK: `window` has get_default_size(), set_default_size(),
    fixed_size() (maximized, tiled or full screen: it cannot grow), show_pane(name, widget,
    base) and hide_pane(); `sheet` (the Now Playing sheet, or None: nothing to show) lends
    the views; `settings` holds mini-player-pane and mini-player-pane-height. `base` is the
    window's height without a pane.

    Opening one: the view lent (inactive: the sheet is covered), put in the window, the
    window grown, then the view made active. Closing, or swapping for the other: inactive
    first, out of the window, back in the sheet; then the window shrunk, or the other taken
    with no resize. A window that cannot grow keeps its size, and the pane has what split()
    gives it."""

    def __init__(self, window, sheet, settings, base):
        self._window = window
        self._sheet = sheet
        self._settings = settings
        self.base = base
        self.shown = ''
        self._widget = None
        self.grown = False     # whether the window's size counts the pane

    def toggle(self, name):
        """The pane `name`, or closed when it shows already."""
        if self.shown == name:
            self.close()
        else:
            self.show(name)

    def show(self, name, grown=False):
        """Show the pane `name` (in place of the other, when that shows). `grown`: the
        window was made at its size with the pane already. False when there is nothing to
        lend."""
        if name == self.shown:
            return True
        if name not in PANES or self._sheet is None:
            return False
        swapping = bool(self.shown)
        if swapping:
            self._give_back()
        widget = (self._sheet.lend_lyrics() if name == 'lyrics'
                  else self._sheet.lend_queue())
        if widget is None:
            if swapping:
                self._closed()
            return False
        self._widget = widget
        self.shown = name
        if grown:
            self.grown = True
        elif not swapping:
            self._grow()
        self._window.show_pane(name, widget, self.base)
        widget.set_active(True)
        self._settings.set_string('mini-player-pane', name)
        return True

    def close(self):
        """Close the pane: its view given back, its height kept, the window shrunk."""
        if not self.shown:
            return
        self._give_back()
        self._closed()
        self._settings.set_string('mini-player-pane', '')

    def give_back(self):
        """The mini player goes: the view back in the sheet, the pane's height kept, the
        pane still the one remembered. (width, height) of the window without the pane, or
        None when no pane showed."""
        if not self.shown:
            return None
        self._give_back()
        size = self._keep_sizes()
        self.shown = ''
        self._window.hide_pane()
        return size

    def _grow(self):
        width, height = self._window.get_default_size()
        pane = max(self._settings.get_int('mini-player-pane-height'), PANE_MIN)
        if self._window.fixed_size() or width <= 0 or height <= 0:
            self.grown = False
            return
        self.base = height     # as the user last left it, without a pane
        self.grown = True
        self._window.set_default_size(width, height + pane)

    def _give_back(self):
        widget, self._widget = self._widget, None
        if widget is None:
            return
        widget.set_active(False)
        self._window.hide_pane()
        if self.shown == 'lyrics':
            self._sheet.return_lyrics(widget)
        else:
            self._sheet.return_queue(widget)

    def _keep_sizes(self):
        """The window's size read as the pane goes: (width, its height without the pane),
        the pane's height written. A window that never grew for the pane (maximized or
        tiled as it opened) says nothing about either height."""
        width, height = self._window.get_default_size()
        if not self.grown or width <= 0 or height <= 0:
            return width, self.base
        self.base, pane = split(height, self.base)
        self._settings.set_int('mini-player-pane-height', pane)
        return width, self.base

    def _closed(self):
        width, base = self._keep_sizes()
        self.shown = ''
        self._window.hide_pane()
        if self.grown:
            self.grown = False
            self._window.set_default_size(width, base)


def _make_window(app):
    from .widgets.mini_player import MiniPlayer

    window = MiniPlayer(application=app)
    window.set_player(app.player, app)
    return window


class MiniPlayerHost:
    """See the module. `app` has `settings` and `main_window()` (the main window, hidden or
    not, whose `now_playing` is the sheet that lends the panes their views);
    `make_window(app)` makes the window (widgets/mini_player.MiniPlayer, following the
    app's Player), which has `can_show(pane)`, `set_lender(sheet, main, base)` (its `panes`
    made, a Panes) and `release()` (its pieces detached, then destroyed)."""

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

    def _sheet(self, main):
        return getattr(main, 'now_playing', None)

    def enter(self):
        """Show the mini player at its size, with the pane it last had when there is
        something to show in it, and hide the main window, its sheet covered; the one shown
        already is presented."""
        if self.window is not None:
            self.window.present()
            return
        settings = self._app.settings
        window = self._make_window(self._app)
        main = self._app.main_window()
        sheet = self._sheet(main)
        width = settings.get_int('mini-player-width')
        base = settings.get_int('mini-player-height')
        pane = settings.get_string('mini-player-pane')
        if pane not in PANES or sheet is None or not window.can_show(pane):
            pane = ''
        # With a pane to open, the window is made at its grown size: no second resize.
        grown = base + max(settings.get_int('mini-player-pane-height'), PANE_MIN)
        window.set_default_size(width, grown if pane else base)
        self.window = window
        window.present()
        if main is not None:
            main.put_away()    # out of the full-screen player first: the lyrics are back
        if sheet is not None:
            sheet.set_covered(True)
        window.set_lender(sheet, main, base)
        if pane and not window.panes.show(pane, grown=True):
            window.set_default_size(width, base)

    def leave(self):
        """The main window presented again, the mini player closed (its size kept): a view
        lent to a pane given back first, then the sheet uncovered."""
        window = self._take()
        if window is None:
            return
        main = self._app.main_window()
        sheet = self._sheet(main)
        if sheet is not None:
            sheet.set_covered(False)
        if main is not None:
            main.present()
        window.release()

    def quit(self):
        """The app quits: the mini player closed (its size kept, a view lent given back),
        the main window left hidden."""
        window = self._take()
        if window is not None:
            window.release()

    def _take(self):
        window, self.window = self.window, None
        if window is not None:
            panes = getattr(window, 'panes', None)
            size = panes.give_back() if panes is not None else None
            width, height = size if size is not None else window.get_default_size()
            if width > 0 and height > 0:
                self._app.settings.set_int('mini-player-width', width)
                self._app.settings.set_int('mini-player-height', height)
        return window
