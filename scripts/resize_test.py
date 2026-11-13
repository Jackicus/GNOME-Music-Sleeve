#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Resize the real window from wide to narrow and back, a frame at a time, as dragging its
edge does, and report the frames: how long each one's work took, which were over the
budget, at which widths, and the Python time in them.

    scripts/headless.sh scripts/resize_test.py [--page KEY | --open KIND:ID | --now-playing]
                        [--wide PX] [--narrow PX] [--height PX] [--speed PX_PER_S]
                        [--rounds N] [--no-profile] [--top N] [--light] [--setting KEY=VALUE]…

Runs the installed build (meson install -C build first) on the demo library through
scripts/harness.py, as scroll_test.py does (animations on, the desktop's look), with
$APPLE_MUSIC_CACHE for a big one:

    APPLE_MUSIC_CACHE=$PWD/build/demo-big scripts/headless.sh scripts/resize_test.py --page albums
    APPLE_MUSIC_CACHE=$PWD/build/demo-big scripts/headless.sh scripts/resize_test.py \
        --open artist:most

The harness makes its windows non-resizable; this one is made resizable again. Under the
headless mutter a mapped, floating toplevel takes a new size from set_default_size(): GTK
lays it out at that size in the frame that asks and commits a surface that big, which
mutter keeps. So a tick callback on the window sets the width each frame, moving at --speed
px/s from --wide down to --narrow and back, --rounds times, at --height; a frame that runs
long is followed by a bigger step, as the edge under a pointer moves on meanwhile. The
compositor's own way, configure events (mutter's keyboard resize, Alt+F8, driven through
remote_keys.py), costs the same frames (docs/notes.md). Collapsed, the window's split view
shows the page, its sidebar closed. The sweep waits for the page to settle
first (SETTLED_FRAMES quiet frames: Songs prepares its order over frames).

--page KEY shows a sidebar destination (albums by default), --open KIND:ID pushes an item
of the library's (album, artist, playlist, video; ID an id, `first`, the section's first,
or for an artist `most`, the library's artist with the most albums), and --now-playing
opens the Now Playing sheet on an invented item with lyrics (harness.invented_playing_state)
over the page.

Reported, from the first resized frame: each frame's work on the main thread, from the
frame clock's before-paint to the end of its paint (the tick, the layout at the new width,
snapshot and render: what scroll_test.py times), its layout phase apart, the frames over the
monitor's refresh interval (16.7 ms at 60 Hz), the longest frames with the width they laid
out, and each frame over it with what changed in it (changes(): a breakpoint of the window's
or of a page's Adw.BreakpointBin that applied or stopped, a grid's max-columns); the gaps
between frames, which also hold the work done between them (an idle's). Then, unless
--no-profile, one more round under cProfile: the Python time a frame (python_time(); a GTK
call made from Python counts in its caller, and cProfile's own cost is in it too) and the
--top functions by their own time. The last line, `resize-result: {json}`, has the figures
for a summary over runs.
"""

import argparse
import json
import statistics
import time

# The milliseconds of a frame's work over which a frame is reported as over budget, when
# the monitor reports no refresh rate: 60 Hz.
DEFAULT_INTERVAL_US = 1e6 / 60
# The page has settled before the sweep when this many frames in a row each took less than
# SETTLED_WORK seconds of work and came within SETTLED_GAP of the one before; it is not
# waited for longer than SETTLE_LIMIT seconds.
SETTLED_FRAMES = 60
SETTLED_WORK = 0.004
SETTLED_GAP = 0.025
SETTLE_LIMIT = 30


def sweep_width(elapsed, wide, narrow, speed, rounds):
    """The window's width `elapsed` seconds into the sweep: from `wide` down to `narrow` and
    back at `speed` px/s, `rounds` times; None once it is over."""
    span = wide - narrow
    if span <= 0 or speed <= 0:
        return None
    travelled = elapsed * speed
    if travelled >= 2 * span * rounds:
        return None
    within = travelled % (2 * span)
    return round(wide - within if within <= span else narrow + within - span)


def percentile(sorted_values, share):
    """The value `share` (0 to 1) of the way through `sorted_values` (nearest rank), 0 for
    none."""
    if not sorted_values:
        return 0
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * share))]


def summarize(frames, budget):
    """The figures of a sweep's frames, each (work, layout, width, changes) in seconds and px,
    against `budget` seconds: counts, the mean, 90th percentile and longest work, the mean
    layout, the share over budget, in milliseconds and per cent."""
    work = sorted(frame[0] for frame in frames)
    layout = [frame[1] for frame in frames]
    over = sum(value > budget for value in work)
    return {
        'frames': len(work),
        'mean': 1000 * statistics.mean(work) if work else 0,
        'p90': 1000 * percentile(work, 0.9),
        'longest': 1000 * (work[-1] if work else 0),
        'layout': 1000 * statistics.mean(layout) if layout else 0,
        'over': over,
        'over_share': 100 * over / len(work) if work else 0,
    }


def longest_frames(frames, count):
    """The `count` longest frames, (milliseconds, width, layout milliseconds), longest
    first."""
    ranked = sorted(frames, key=lambda frame: frame[0], reverse=True)[:count]
    return [(1000 * frame[0], frame[2], 1000 * frame[1]) for frame in ranked]


def changes(before, after):
    """What changed between two layout states (each {name: value}: a breakpoint's condition
    or '' for none, a grid's columns), as short strings: 'window: max-width: 640sp' for a
    breakpoint that applies now, 'window: -max-width: 640sp' for one that no longer does,
    'AppleMusicGridPage columns 4>3'."""
    found = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if isinstance(new, int) or isinstance(old, int):
            found.append(f'{name} columns {old}>{new}')
        elif new:
            found.append(f'{name}: {new}')
        else:
            found.append(f'{name}: -{old}')
    return found


def python_time(stats, own_file=__file__):
    """From a pstats.Stats: the seconds in Python code (each function's own time, and the
    built-ins it calls) and the functions ranked by it, each (seconds, calls,
    'file:line(name)'). A GTK call made from Python through gi is not a built-in to
    cProfile: its time, a layout or tiles built included, is its Python caller's. This
    script's own functions are left out."""
    ranked = []
    for (path, line, name), (_primitive, calls, own, _cumulative, _callers) in \
            stats.stats.items():
        if path == own_file:
            continue
        where = name if path == '~' else f'{path.rsplit("/", 1)[-1]}:{line}({name})'
        ranked.append((own, calls, where))
    ranked.sort(reverse=True)
    return sum(own for own, _calls, _where in ranked), ranked


def main():
    parser = argparse.ArgumentParser()
    where = parser.add_mutually_exclusive_group()
    where.add_argument('--page', default='albums')
    where.add_argument('--open', metavar='KIND:ID', help="the library's item pushed first")
    parser.add_argument('--now-playing', action='store_true',
                        help='the Now Playing sheet open over the page')
    parser.add_argument('--wide', type=int, default=1400, help='px (default 1400)')
    parser.add_argument('--narrow', type=int, default=360, help='px (default 360)')
    parser.add_argument('--height', type=int, default=760, help='px (default 760)')
    parser.add_argument('--speed', type=float, default=1000,
                        help='pixels a second the edge moves (default 1000)')
    parser.add_argument('--rounds', type=int, default=3,
                        help='sweeps down and back that are timed (default 3)')
    parser.add_argument('--no-profile', action='store_true',
                        help='no last round under cProfile')
    parser.add_argument('--top', type=int, default=12,
                        help='functions listed from the profiled round (default 12)')
    parser.add_argument('--light', action='store_true')
    parser.add_argument('--setting', metavar='KEY=VALUE', action='append', default=[],
                        help="a setting (GVariant text), as scroll_test.py's")
    args = parser.parse_args()
    if args.narrow >= args.wide:
        parser.error('--narrow must be less than --wide')

    import harness

    app = harness.make_app('ResizeTest', light=args.light, animations=True, stock_look=False,
                           size=(args.wide, args.height), name='resize-test')
    from gi.repository import GLib, Gtk  # noqa: F401  (after make_app)

    # The harness fixes each window's size; this one is dragged.
    app.connect_after('window-added', lambda _app, window: window.set_resizable(True))
    run = Run(app, args)
    app.connect('activate', run.on_activate)
    GLib.timeout_add_seconds(300, app.quit)  # whatever happens
    harness.run_app(app)


class Run:
    """One run: the page shown, the timed rounds, the profiled round, the report."""

    def __init__(self, app, args):
        self.app = app
        self.args = args
        self.opened = False
        self.frames = []  # (work, layout, width) of the timed rounds
        self.profiled = []  # the same, of the profiled round
        self.times = []  # the frame times (µs) of the timed rounds

    def on_activate(self, _app):
        from gi.repository import GLib

        if not self.args.open:
            self.app.settings.set_string('last-page', self.args.page)
        for setting in self.args.setting:
            key, _sep, text = setting.partition('=')
            kind = self.app.settings.get_value(key).get_type_string()
            self.app.settings.set_value(key, GLib.Variant.parse(GLib.VariantType(kind), text))
        GLib.timeout_add(1000, self.start)

    def where(self):
        shown = f'{self.args.open} page' if self.args.open else f'{self.args.page} page'
        return shown + (', Now Playing open' if self.args.now_playing else '')

    def item(self, spec):
        kind, item_id = spec.split(':', 1)
        library = self.app.library
        stores = {'album': library.albums, 'artist': library.artists,
                  'playlist': library.playlists, 'video': library.videos}
        store = stores.get(kind)
        if item_id == 'first' and store is not None and store.get_n_items():
            return store.get_item(0)
        if item_id == 'most' and kind == 'artist':
            artists = [store.get_item(i) for i in range(store.get_n_items())]
            return max(artists, key=lambda artist: len(artist.raw.get('groups') or []),
                       default=None)
        return library.by_id(kind, item_id)

    def start(self):
        from gi.repository import GLib

        import harness

        if self.app.library.props.state == 'loading':
            GLib.timeout_add(100, self.start)
            return GLib.SOURCE_REMOVE
        window = self.app.get_active_window()
        if self.args.open and not self.opened:
            self.opened = True
            item = self.item(self.args.open)
            if item is None:
                print(f'resize-test: no {self.args.open} in the library', flush=True)
                self.app.quit()
                return GLib.SOURCE_REMOVE
            window.open_item(item)
            GLib.timeout_add(1500, self.start)
            return GLib.SOURCE_REMOVE
        if self.args.now_playing and not window.bottom_sheet.get_open():
            self.app.player.apply(harness.invented_playing_state(self.app, lyrics=True))
            window.now_playing.tab_stack.set_visible_child_name('lyrics')
            window.bottom_sheet.set_open(True)
            GLib.timeout_add(1500, self.start)
            return GLib.SOURCE_REMOVE
        monitor = window.get_display().get_monitor_at_surface(window.get_surface())
        rate = monitor.get_refresh_rate() if monitor else 0  # millihertz; 0 when unknown
        self.budget = (1e9 / rate if rate else DEFAULT_INTERVAL_US) / 1e6  # seconds
        self.settle(window, lambda: self.sweep(window, self.args.rounds, self.frames,
                                               self.times, self.timed_done))
        return GLib.SOURCE_REMOVE

    def settle(self, window, then):
        """then() once the page has settled: SETTLED_FRAMES frames in a row each with little
        work and on time (a page still sorting or filling in, as Songs prepares its order
        over frames, is not), or after SETTLE_LIMIT seconds, said so."""
        from gi.repository import GLib

        clock = window.get_frame_clock()
        began, quiet, start = {}, [0], time.perf_counter()
        last = [None]

        # Every frame has a before-paint and an after-paint, painted or not (a frame with
        # nothing to draw has no paint phase).
        def before_paint(_clock):
            now = time.perf_counter()
            began['gap'] = now - last[0] if last[0] is not None else 0
            began['at'] = last[0] = now

        def after_paint(_clock):
            if 'at' not in began:
                return
            calm = (time.perf_counter() - began.pop('at') < SETTLED_WORK
                    and began.pop('gap') < SETTLED_GAP)
            quiet[0] = quiet[0] + 1 if calm else 0

        handlers = [clock.connect('before-paint', before_paint),
                    clock.connect('after-paint', after_paint)]

        def tick(_widget, _clock):
            waited = time.perf_counter() - start
            if quiet[0] < SETTLED_FRAMES and waited < SETTLE_LIMIT:
                return GLib.SOURCE_CONTINUE
            for handler in handlers:
                clock.disconnect(handler)
            if quiet[0] < SETTLED_FRAMES:
                print(f'resize-test: not settled after {SETTLE_LIMIT} s; resizing anyway',
                      flush=True)
            then()
            return GLib.SOURCE_REMOVE

        window.add_tick_callback(tick)

    def watched(self, window):
        """The window and every Adw.BreakpointBin and Gtk.GridView under it, each with its
        name in changes(): the window, a bin or grid by the page (or widget) holding it."""
        from gi.repository import Adw, Gtk

        found = [('window', window)]
        named = {}

        def owner(widget):
            parent = widget.get_parent()
            while parent is not None and not isinstance(parent, Adw.NavigationPage):
                parent = parent.get_parent()
            return type(parent if parent is not None else widget).__gtype__.name

        def walk(widget):
            if isinstance(widget, (Adw.BreakpointBin, Gtk.GridView)):
                name = owner(widget)
                named[name] = named.get(name, 0) + 1
                found.append((name if named[name] == 1 else f'{name}#{named[name]}', widget))
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(window)
        return found

    @staticmethod
    def layout_state(watched):
        """{name: value} of the watched widgets: a breakpoint's condition ('' for none), a
        grid's max-columns."""
        from gi.repository import Gtk

        state = {}
        for name, widget in watched:
            if isinstance(widget, Gtk.GridView):
                state[name] = widget.get_max_columns()
            else:
                current = widget.get_current_breakpoint()
                state[name] = current.get_condition().to_string() if current else ''
        return state

    def sweep(self, window, rounds, frames, times, done):
        """Resize `window` a frame at a time over `rounds` sweeps, each frame's (work,
        layout, width, changes) appended to `frames` and its frame time to `times`; then
        done()."""
        from gi.repository import GLib

        args = self.args
        clock = window.get_frame_clock()
        began = {}
        watched = self.watched(window)
        last = [self.layout_state(watched)]

        def before_paint(_clock):
            began['frame'] = time.perf_counter()

        def update(_clock):
            began['layout'] = time.perf_counter()  # after the tick callbacks

        def layout(_clock):
            if 'layout' in began:
                began['laid'] = time.perf_counter() - began.pop('layout')

        def paint(_clock):
            if 'frame' in began and times:
                work = time.perf_counter() - began.pop('frame')
                state = self.layout_state(watched)  # after the frame's timing: not in it
                frames.append((work, began.pop('laid', 0.0), window.get_width(),
                               changes(last[0], state)))
                last[0] = state

        handlers = [clock.connect('before-paint', before_paint),
                    clock.connect('update', update), clock.connect('layout', layout),
                    clock.connect('paint', paint)]

        def tick(_widget, frame_clock):
            now = frame_clock.get_frame_time()
            first = times[0] if times else now
            width = sweep_width((now - first) / 1e6, args.wide, args.narrow, args.speed,
                                rounds)
            if width is None:
                for handler in handlers:
                    clock.disconnect(handler)
                GLib.timeout_add(300, done, window)
                return GLib.SOURCE_REMOVE
            times.append(now)
            window.set_default_size(width, args.height)
            return GLib.SOURCE_CONTINUE

        window.set_default_size(args.wide, args.height)
        GLib.timeout_add(500, lambda: window.add_tick_callback(tick) and GLib.SOURCE_REMOVE)

    def timed_done(self, window):
        from gi.repository import GLib

        if self.args.no_profile:
            self.report(None)
            return GLib.SOURCE_REMOVE
        import cProfile

        self.profiler = cProfile.Profile()
        profiled_times = []

        def done(_window):
            self.profiler.disable()
            self.report(profiled_times)
            return GLib.SOURCE_REMOVE

        self.profiler.enable()
        self.sweep(window, 1, self.profiled, profiled_times, done)
        return GLib.SOURCE_REMOVE

    def report(self, profiled_times):
        from gi.repository import GLib

        args = self.args
        budget = self.budget
        figures = summarize(self.frames, budget)
        gaps = [b - a for a, b in zip(self.times, self.times[1:], strict=False)] or [0]
        widths = len({frame[2] for frame in self.frames})
        print(f'resize-test: the {self.where()}, {args.wide} to {args.narrow} px and back '
              f'{args.rounds} times at {args.speed:.0f} px/s, {args.height} px high; '
              f'{widths} widths laid out', flush=True)
        print(f"  work per frame: mean {figures['mean']:.1f} ms, 90th percentile "
              f"{figures['p90']:.1f} ms, longest {figures['longest']:.1f} ms; layout phase "
              f"mean {figures['layout']:.1f} ms; over {1000 * budget:.1f} ms: "
              f"{figures['over']} of {figures['frames']} ({figures['over_share']:.1f} %)",
              flush=True)
        print(f'  frames drawn: {len(gaps)}; longest gap {max(gaps) / 1000:.1f} ms; gaps over '
              f'16.7 ms: {sum(gap > 16700 for gap in gaps)}, over 33.3 ms: '
              f'{sum(gap > 33300 for gap in gaps)}', flush=True)
        print('  longest frames: ' + ', '.join(
            f'{work:.1f} ms at {width} px (layout {layout:.1f})'
            for work, width, layout in longest_frames(self.frames, 5)), flush=True)
        print('  over budget (px, ms, what changed in the frame):' + (''.join(
            f'\n    {width} px {1000 * work:.0f} ms' + (f' [{"; ".join(changed)}]'
                                                       if changed else '')
            for work, _layout, width, changed in self.frames if work > budget) or ' none'),
            flush=True)
        result = dict(figures, where=self.where(), gap=max(gaps) / 1000,
                      gaps_over=sum(gap > 16700 for gap in gaps))
        if profiled_times is not None:
            import pstats

            seconds, ranked = python_time(pstats.Stats(self.profiler))
            count = max(1, len(self.profiled))
            profiled = summarize(self.profiled, budget)
            print(f'  profiled round: {len(self.profiled)} frames, work mean '
                  f"{profiled['mean']:.1f} ms, longest {profiled['longest']:.1f} ms; Python "
                  f'{1000 * seconds / count:.2f} ms a frame', flush=True)
            for own, calls, name in ranked[:args.top]:
                print(f'    {1000 * own / count:7.3f} ms {calls / count:7.1f}x  {name}',
                      flush=True)
            result['python'] = 1000 * seconds / count
        print('resize-result: ' + json.dumps(result), flush=True)
        GLib.timeout_add(200, self.app.quit)


if __name__ == '__main__':
    main()
