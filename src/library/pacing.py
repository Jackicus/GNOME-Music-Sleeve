# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Long main-thread work that leaves room for frames: the frame budget, yield_to_frames(),
and the garbage collector paused around big loads (paused_gc)."""

import asyncio
import gc

from gi.repository import GLib


# How long wrapping the Songs store runs before it lets GTK paint a frame, in seconds.
FRAME_BUDGET = 0.008


class paused_gc:
    """A context in which the garbage collector does not run, and after which, when `freeze`
    (the default), every object alive is frozen: moved where collections never scan it
    (gc.freeze()). For a load() or a Songs build, which make hundreds of thousands of objects
    that live as long as the library: unfrozen, each full collection scanned them all again,
    about 50 ms on 3,000 albums and 40,000 songs (a dropped frame whenever one came round),
    and pausing also spares the parse the young collections its allocations would trigger.

    Freezing moves garbage too: a reference cycle not yet collected would never be. So a
    pause that is to freeze collects first (4 ms at startup, before the library is read;
    later, only what is not frozen yet is scanned), and, when something is frozen already
    (every freeze after the first load's), collects again before it freezes, for what the
    pause itself made garbage; the first load's end skips that, as a full collection of the
    new library would cost 50 ms before the first frame, and all it could catch is what the
    parse and the window's building left in cycles. The other price: an object alive at the
    freeze that later becomes garbage in a cycle is never collected. Hence no freeze for a
    reload(), which comes after every sync while pages come and go, and keeps its objects
    anyway. Nested uses pause once and resume, freezing if any of them asked to, at the
    outermost end; the collector is left as it was found (enabled or not).
    """

    _depth = 0
    _freeze = False
    _was_enabled = True

    def __init__(self, freeze=True):
        self.freeze = freeze

    def __enter__(self):
        cls = paused_gc
        if not cls._depth:
            cls._was_enabled = gc.isenabled()
            cls._freeze = False
            if self.freeze:
                gc.collect()
            gc.disable()
        cls._depth += 1
        cls._freeze = cls._freeze or self.freeze
        return self

    def __exit__(self, *_exception):
        cls = paused_gc
        cls._depth -= 1
        if not cls._depth:
            if cls._freeze:
                if gc.get_freeze_count():
                    gc.collect()
                gc.freeze()
            if cls._was_enabled:
                gc.enable()
        return False


async def yield_to_frames():
    """Pause so GTK can paint before the next batch.

    A bare `await asyncio.sleep(0)` is not enough on the GLib loop: asyncio's callbacks run at
    G_PRIORITY_DEFAULT, above the frame clock's redraw, so a task that only yields to itself
    starves painting until it ends. Running the next step at idle priority lets the frame in
    first. On a plain asyncio loop (tests) nothing paints and sleep(0) is all there is.
    """
    task = asyncio.current_task()
    set_priority = getattr(task, 'set_priority', None)  # gi.events.GLibTask
    if set_priority is None:
        await asyncio.sleep(0)
        return
    set_priority(GLib.PRIORITY_DEFAULT_IDLE)
    try:
        await asyncio.sleep(0)
    finally:
        set_priority(GLib.PRIORITY_DEFAULT)
