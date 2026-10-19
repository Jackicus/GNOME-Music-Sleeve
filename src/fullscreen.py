# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The full-screen player's host: the window's way in and out of it, and its layout and idle
decisions as pure functions.

    host = FullscreenHost(window, stack, sheet, player, app)
    host.enter()        the item playing, full screen (win.fullscreen-player, F11)
    host.leave(restore_focus=True)
    host.shown          whether the player is shown; host.view: the view, once built

The view (widgets/fullscreen_player.py) is built on the first enter and kept for the
window's life: its module is imported then, never at startup. It is the window's stack's
second page, beside the bottom sheet (window.blp), so while it shows the rest of the window
is unmapped: the pages let go of what they follow, nothing behind it paints, and Tab stays
inside it. The window is fullscreened as it enters, unless it already was (a window
manager's shortcut), and put back as it leaves; GTK keeps the window's default size and
maximized state through it, so the state the window saves while full screen is the normal
one.

There is one LyricsView, the Now Playing sheet's. Entering covers the sheet (its Lyrics and
Up Next views go inactive), moves the view out of the sheet's Lyrics tab into the full-screen
view and makes it active there; leaving does the reverse, the sheet then making it active
again only if it is open on its Lyrics tab (which centres the current line again). So only one
place ever paints the lyrics, steps them or sweeps a word.

The player leaves on its own when nothing plays any more: the Player's item goes (the queue
ended or was cleared, a stop, a sign-out, the engine gone; only after the Player's grace
between queues, so one song giving way to the next never leaves it), or the window manager
takes the window out of full screen. A pause keeps it. The window's own keys that go to its
pages leave it first (Window._close_sheet).
"""

import logging
from collections import namedtuple

from gi.repository import GLib

log = logging.getLogger(__name__)

# The layout's measures, in px of the view.
PORTRAIT_WIDTH = 720        # narrower than this: one column
PORTRAIT_RATIO = 4 / 5      # or taller than this for its width
MARGIN = 48                 # around the content, the wide layout's
MARGIN_NARROW = 16          # the one-column layout's, at 400 px and less
MARGIN_PORTRAIT = 24
TOP_MARGIN = 56             # under the header bar, which the content extends under
SMALL_ART = 96              # the one-column layout with lyrics: the cover beside the titles
MAX_ART = 640               # the cover file's size (backend config.COVER_SIZE)
MIN_ART = 120
# The height the titles and the controls take under the cover, and the share of the width
# the cover may take beside the lyrics or alone.
BELOW_ART = 230
ART_SHARE = 0.42
ART_SHARE_ALONE = 0.6
# Seconds without the pointer moving or a key before the controls and the cursor hide.
IDLE_SECONDS = 3

Layout = namedtuple('Layout', 'portrait lyrics art_size margin')


def layout_for(width, height, lyrics):
    """The view's Layout at `width` x `height` px, with the lyrics column (`lyrics`) or not:
    `portrait` one column (narrow, or tall for its width) rather than the artwork beside the
    lyrics; `art_size` the cover's edge, as large as the room under it leaves (at most the
    cover file's 640 px), and SMALL_ART beside the titles in one column with lyrics;
    `margin` the content's side margins."""
    portrait = width < PORTRAIT_WIDTH or width < height * PORTRAIT_RATIO
    if portrait:
        margin = MARGIN_NARROW if width <= 400 else MARGIN_PORTRAIT
    else:
        margin = MARGIN
    if portrait and lyrics:
        return Layout(True, True, SMALL_ART, margin)
    room = height - TOP_MARGIN - MARGIN - BELOW_ART
    across = width - 2 * margin
    if not portrait:
        across *= ART_SHARE if lyrics else ART_SHARE_ALONE
    size = int(min(room, across, MAX_ART)) // 8 * 8
    return Layout(portrait, lyrics, max(MIN_ART, size), margin)


def should_hide(playing, popover_open, pointer_on_controls, keyboard_on_controls, idle_for):
    """Whether the controls and the cursor hide now: after IDLE_SECONDS with no motion or
    key (`idle_for`, seconds), while the music plays, with no popover open (a menu, the
    volume), the pointer off the controls and the header bar, and the keyboard's focus not
    shown on one of them."""
    return (playing and not popover_open and not pointer_on_controls
            and not keyboard_on_controls and idle_for >= IDLE_SECONDS)


class FullscreenHost:
    """The window's full-screen player. See the module."""

    def __init__(self, window, stack, sheet, player, app):
        self._window = window
        self._app = app
        self._stack = stack
        self._sheet = sheet
        self._player = player
        self.view = None
        self.shown = False
        self._was_fullscreen = False    # the window was full screen before the player
        self._focus_before = None       # a weak reference to the focus as it entered
        self._listeners = []
        self._track_handler = player.connect('notify::track', lambda *_: self._on_track())
        window.connect('notify::fullscreened', lambda *_: self._on_fullscreened())

    def release(self):
        """Stop following the Player, which outlives the window (the window quitting)."""
        if self._track_handler:
            self._player.disconnect(self._track_handler)
            self._track_handler = 0

    def connect_changed(self, callback):
        """Call `callback()` after the player is entered or left (the window's actions)."""
        self._listeners.append(callback)

    def _changed(self):
        for callback in self._listeners:
            callback()

    def toggle(self):
        if self.shown:
            self.leave()
        else:
            self.enter()

    def _ensure_view(self):
        if self.view is None:
            from .widgets.fullscreen_player import FullscreenPlayer

            self.view = FullscreenPlayer()
            self.view.set_player(self._player, self._app)
            self._stack.add_named(self.view, 'fullscreen')
            log.debug('fullscreen: the view built')
        return self.view

    def enter(self):
        """Show the item playing full screen (nothing without an item)."""
        if self.shown or self._player.track is None:
            return
        view = self._ensure_view()
        focus = self._window.get_focus()
        self._focus_before = focus.weak_ref() if focus is not None else None
        self._was_fullscreen = self._window.is_fullscreen()
        self.shown = True
        self._sheet.set_covered(True)
        view.take_lyrics(self._sheet.lend_lyrics())
        self._stack.set_visible_child(view)
        view.set_shown(True)
        if not self._was_fullscreen:
            self._window.fullscreen()
        GLib.idle_add(self._focus_view)
        self._changed()

    def _focus_view(self):
        if self.shown:
            self.view.focus_controls()
        return GLib.SOURCE_REMOVE

    def leave(self, restore_focus=True):
        """Back to the window as it was: its size or maximized state, the sheet open or
        closed, and (`restore_focus`) the focus where it was, when that is still there."""
        if not self.shown:
            return
        self.shown = False
        view = self.view
        view.set_shown(False)
        lyrics = view.give_lyrics()
        self._stack.set_visible_child_name('main')
        self._sheet.return_lyrics(lyrics)
        self._sheet.set_covered(False)
        if not self._was_fullscreen and self._window.is_fullscreen():
            self._window.unfullscreen()
        focus_before, self._focus_before = self._focus_before, None
        if restore_focus:
            GLib.idle_add(self._restore_focus, focus_before)
        self._changed()

    def _restore_focus(self, focus_before):
        widget = focus_before() if focus_before is not None else None
        if not self.shown and widget is not None and widget.get_mapped():
            widget.grab_focus()
        return GLib.SOURCE_REMOVE

    def _on_track(self):
        if self.shown and self._player.track is None:
            log.debug('fullscreen: nothing plays any more: leaving')
            self.leave()
        self._changed()

    def _on_fullscreened(self):
        """The window manager took the window out of full screen: the player leaves too."""
        if self.shown and not self._window.is_fullscreen():
            self.leave()
