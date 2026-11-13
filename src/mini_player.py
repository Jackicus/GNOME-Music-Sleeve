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
written as it leaves; it is never smaller than MIN_WIDTH by MIN_HEIGHT, the size its seven
buttons and its short layout take.

Lyrics and Up Next are a pane under its controls, one at a time (Panes): off until asked
for, and opened inside the window. The controls and the pane are the two halves of a
divider the user drags (the window's Gtk.Paned): the pane takes its height
(mini-player-pane-height) from the bottom of the window and the controls lay themselves out
in what is left, down to the short layout (SHORT_HEIGHT), so a window with the room is not
resized. One too low for the short layout and a pane worth reading (PANE_OPEN) grows by
what is missing (grow_for_pane()) and shrinks by the same as the pane closes: a window
cannot say where it is on the screen, and one that grows may leave it. mini-player-height
stays the height the user gave the window, without what it grew by; the pane open is
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

# The layout's measures, in px of the controls: the content under the header bar, over the
# pane when one shows.
MARGIN = 18            # the sides and the bottom
TOP_MARGIN = 6         # under the header bar
# The height the titles, the seek row and the buttons take under the cover, with their
# spacing and the bottom margin, as the widgets measure with the app's stylesheet.
BELOW_ART = 170
MIN_ART = 128          # smaller than this over the titles: the short layout
MAX_ART = 640          # the cover file's size (backend config.COVER_SIZE)
# The short layout's cover, beside the titles: SMALL_ART where the controls have no more
# than their least height, larger with the room over that, up to SIDE_ART and a third of
# the width.
SMALL_ART = 56
SIDE_ART = 120
# The height the short layout takes, margins and all: the least the controls are given.
SHORT_HEIGHT = 170
# The mini player's smallest size, its content's (the view measures it as its least). The
# width is the row of seven buttons (Favourite, Shuffle, Previous, Play, Next, Repeat,
# Volume: 324 px as they measure) and the side margins, so the row is whole at every
# size; the height the header bar and the short layout.
MIN_WIDTH = 360
MIN_HEIGHT = 220

Layout = namedtuple('Layout', 'short art_size')


def layout_for(width, height):
    """The Layout of the mini player's controls in `width` x `height` px. `art_size`, the
    cover's edge over the titles, as large as the width and the room over the controls
    leave (a multiple of 4, at most the cover file's); or, when that is less than MIN_ART,
    `short`: the cover beside the titles, SMALL_ART and what the height has over
    SHORT_HEIGHT, up to SIDE_ART. The buttons are one row in both."""
    room = height - TOP_MARGIN - BELOW_ART
    across = width - 2 * MARGIN
    size = int(min(room, across, MAX_ART)) // 4 * 4
    if size >= MIN_ART:
        return Layout(False, size)
    side = int(min(SMALL_ART + height - SHORT_HEIGHT, SIDE_ART, across / 3)) // 4 * 4
    return Layout(True, max(side, SMALL_ART))


# The panes: their names (the sheet's tabs'); the least height the divider leaves one; and
# the least one is opened with, which a window too low for it grows to give. A pane's
# height counts the divider over it.
PANES = ('lyrics', 'queue')
PANE_MIN = 140
PANE_OPEN = 220


def grow_for_pane(height, header):
    """By how many px a window `height` px high, its header bar `header`, has to grow to
    open a pane: what its short layout and a pane of PANE_OPEN lack, 0 when they fit."""
    return max(header + SHORT_HEIGHT + PANE_OPEN - height, 0)


def divide(height, pane):
    """(controls, pane): how `height` px under the header bar divide for a pane wished
    `pane` px high. The pane has its wish, no less than PANE_MIN, as far as the controls
    keep SHORT_HEIGHT; the controls the rest."""
    pane = max(pane, PANE_MIN)
    controls = max(height - pane, SHORT_HEIGHT)
    return controls, max(height - controls, 0)


class Panes:
    """The mini player's pane: which shows (`shown`: '', 'lyrics' or 'queue'), the lending
    and the window's size. No GTK: `window` has get_default_size(), set_default_size(),
    fixed_size() (maximized, tiled or full screen: it cannot grow), header_height(),
    show_pane(name, widget, height) (the pane in the window, `height` px wished for it),
    hide_pane() and pane_height() (the height the pane was left, when the user changed it:
    the divider dragged, the window resized; else None); `sheet` (the Now Playing sheet, or
    None: nothing to show) lends the views; `settings` holds mini-player-pane and
    mini-player-pane-height.

    Opening one: the view lent (inactive: the sheet is covered), the window grown if it
    lacks the room (`grown`, the px it grew by), the view put in it, then made active.
    Closing, or swapping for the other: inactive first, out of the window, back in the
    sheet; then the window shrunk by what it grew, or the other taken with no resize and
    the divider where it was. A window that cannot grow keeps its size, and the pane has
    what divide() gives it."""

    def __init__(self, window, sheet, settings):
        self._window = window
        self._sheet = sheet
        self._settings = settings
        self.shown = ''
        self._widget = None
        self.grown = 0         # the px the window grew by for the pane

    def toggle(self, name):
        """The pane `name`, or closed when it shows already."""
        if self.shown == name:
            self.close()
        else:
            self.show(name)

    def show(self, name, grown=None):
        """Show the pane `name` (in place of the other, when that shows). `grown`: the
        window was made `grown` px taller for the pane already. False when there is
        nothing to lend."""
        if name == self.shown:
            return True
        if name not in PANES or self._sheet is None:
            return False
        swapping = bool(self.shown)
        if swapping:
            self._keep_height()
            self._give_back()
        widget = (self._sheet.lend_lyrics() if name == 'lyrics'
                  else self._sheet.lend_queue())
        if widget is None:
            if swapping:
                self._closed()
            return False
        self._widget = widget
        self.shown = name
        if not swapping:
            self.grown = self._grow() if grown is None else grown
        self._window.show_pane(name, widget,
                               self._settings.get_int('mini-player-pane-height'))
        widget.set_active(True)
        self._settings.set_string('mini-player-pane', name)
        return True

    def close(self):
        """Close the pane: its view given back, its height kept, the window shrunk by what
        it grew."""
        if not self.shown:
            return
        self._keep_height()
        self._give_back()
        self._closed()
        self._settings.set_string('mini-player-pane', '')

    def give_back(self):
        """The mini player goes: the view back in the sheet, the pane's height kept, the
        pane still the one remembered. (width, height) of the window without what it grew
        by for the pane, or None when no pane showed."""
        if not self.shown:
            return None
        self._keep_height()
        self._give_back()
        self.shown = ''
        self._window.hide_pane()
        width, height = self._window.get_default_size()
        grown, self.grown = self.grown, 0
        return width, self._without(height, grown)

    def _grow(self):
        width, height = self._window.get_default_size()
        if self._window.fixed_size() or width <= 0 or height <= 0:
            return 0
        grown = grow_for_pane(height, self._window.header_height())
        if grown:
            self._window.set_default_size(width, height + grown)
        return grown

    @staticmethod
    def _without(height, grown):
        return max(height - grown, MIN_HEIGHT) if grown and height > 0 else height

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

    def _keep_height(self):
        """The pane's height written, when the user left it another than it opened with."""
        height = self._window.pane_height()
        if height:
            self._settings.set_int('mini-player-pane-height', max(height, PANE_MIN))

    def _closed(self):
        self.shown = ''
        self._window.hide_pane()
        grown, self.grown = self.grown, 0
        if grown:
            width, height = self._window.get_default_size()
            if width > 0 and height > 0:
                self._window.set_default_size(width, self._without(height, grown))


def _make_window(app):
    from .widgets.mini_player import MiniPlayer

    window = MiniPlayer(application=app)
    window.set_player(app.player, app)
    return window


class MiniPlayerHost:
    """See the module. `app` has `settings` and `main_window()` (the main window, hidden or
    not, whose `now_playing` is the sheet that lends the panes their views);
    `make_window(app)` makes the window (widgets/mini_player.MiniPlayer, following the
    app's Player), which has `can_show(pane)`, `header_height()`, `set_lender(sheet, main)`
    (its `panes` made, a Panes) and `release()` (its pieces detached, then destroyed)."""

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
        width = max(settings.get_int('mini-player-width'), MIN_WIDTH)
        height = max(settings.get_int('mini-player-height'), MIN_HEIGHT)
        pane = settings.get_string('mini-player-pane')
        if pane not in PANES or sheet is None or not window.can_show(pane):
            pane = ''
        # With a pane to open, the window is made with the room for it: no second resize.
        grown = grow_for_pane(height, window.header_height()) if pane else 0
        window.set_default_size(width, height + grown)
        self.window = window
        window.present()
        if main is not None:
            main.put_away()    # out of the full-screen player first: the lyrics are back
        if sheet is not None:
            sheet.set_covered(True)
        window.set_lender(sheet, main)
        if pane and not window.panes.show(pane, grown=grown) and grown:
            window.set_default_size(width, height)

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
