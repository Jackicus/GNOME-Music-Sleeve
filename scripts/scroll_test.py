#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Scroll a page of the real window from top to bottom and report dropped frames, or type
into its filter and report what each key cost.

    scripts/scroll_test.py [--page KEY] [--speed PX_PER_S] [--distance PX] [--size WxH]
                           [--light] [--sidebar] [--open KIND:ID]
                           [--type TEXT [--key-interval MS]]

Runs the installed build (meson install -C build, or scripts/run.sh, first) on the
demo library, as screenshot.py --demo does (scripts/harness.py), with the desktop's
icon theme and animations: build/demo, or $APPLE_MUSIC_CACHE when set, which is how
a big library is measured:

    scripts/demo_library.py --cache build/demo-2000 --albums 2000
    APPLE_MUSIC_CACHE=build/demo-2000 scripts/scroll_test.py --page albums

Once the library has loaded and the page shows its list (the scrolled window of
its grid_view, column_view or list_view, once mapped: not a status page's), that
scrolled window is moved at a steady speed on every frame, to the bottom or for
--distance pixels (the Songs page of 30,000 songs is 1.5 million pixels long:
6 minutes at 4,000 px/s). A page without such a view scrolls its first mapped
scrolled window:

    APPLE_MUSIC_CACHE=build/demo-2500 scripts/scroll_test.py --page songs --distance 40000

A list laid out and shorter than the window (the same height for FITS_FRAMES frames
in a row) is reported as fitting, with nothing to scroll, and the run ends there:
Music Videos on a library of six. demo_library.py's --videos and --long-playlist make
the long ones (the big library CLAUDE.md names has both):

    APPLE_MUSIC_CACHE=build/demo-big scripts/headless.sh scripts/scroll_test.py \
        --page music-videos
    APPLE_MUSIC_CACHE=build/demo-big scripts/headless.sh scripts/scroll_test.py \
        --open playlist:l.pllong --distance 40000

--sidebar scrolls the sidebar instead of the page (a library with many
playlists makes it long: its rows are not recycled).

--type TEXT types TEXT into the page's filter bar (widgets/filter_bar.py) a key at a
time, --key-interval ms apart (250 by default: past the entry's 150 ms delay, so every
key refilters), then deletes it a key at a time, and reports how long each refilter held
the main loop (from the bar's `changed` to the end of its last handler: the filter, the
models' and the list's own work) and the frames meanwhile, which is how long typing
waits at worst:

    APPLE_MUSIC_CACHE=build/demo-big scripts/headless.sh scripts/scroll_test.py \
        --page songs --type "the night"

--open playlist:ID (or album:ID) pushes the library's item first, to scroll it or type
into its filter.

Two things are reported. The app's own work per frame, timed on the main thread
from the frame clock's before-paint to the end of its paint (tick callbacks and
the binds they cause, layout, snapshot and render): a frame whose work overran
the monitor's refresh interval, or 16.7 ms, would have been dropped at that
rate. And the gaps between the frames the compositor actually asked for, which
also depend on the compositor and on what else the machine is doing, so they
vary from run to run. Both count from the first frame that scrolled, not the
loading before it. A monitor that reports no refresh rate is taken as 60 Hz.
Also counts the artwork decoded on the way. Settings go to a memory backend.
"""

import argparse
import statistics
import time

import harness

parser = argparse.ArgumentParser()
parser.add_argument('--page', default='albums')
parser.add_argument('--speed', type=float, default=4000, help='pixels a second (default 4000)')
parser.add_argument('--distance', type=float, help='pixels to scroll (default: to the bottom)')
parser.add_argument('--size', default='1100x760')
parser.add_argument('--light', action='store_true')
parser.add_argument('--sidebar', action='store_true', help='scroll the sidebar, not the page')
parser.add_argument('--open', metavar='KIND:ID', help="the library's item pushed first")
parser.add_argument('--type', metavar='TEXT',
                    help="type TEXT into the page's filter, then delete it, a key at a time")
parser.add_argument('--key-interval', type=float, default=250,
                    help='milliseconds between keys (default 250)')
args = parser.parse_args()
width, height = (int(n) for n in args.size.split('x'))

# Animations on and the desktop's look, as the numbers were always measured.
app = harness.make_app('ScrollTest', light=args.light, animations=True, stock_look=False,
                       size=(width, height), name='scroll-test')

from gi.repository import GLib, GObject, Gtk  # noqa: E402  (after make_app)

from applemusic.widgets import artwork  # noqa: E402

# How many frames a laid-out list must keep the same height, shorter than the window, to be
# reported as fitting it (half a second at 60 Hz): one that is still being filled grows.
FITS_FRAMES = 30

decoded = 0
_load = artwork._load


def counting_load(path, size=None):
    global decoded
    decoded += 1  # in a worker thread; a lost increment would only undercount
    return _load(path, size)


artwork._load = counting_load


def on_activate(_app):
    app.settings.set_string('last-page', args.page)
    GLib.timeout_add(1000, start)


opened = [False]


def scrolled_window(widget):
    """The first mapped Gtk.ScrolledWindow under widget, depth first."""
    if isinstance(widget, Gtk.ScrolledWindow) and widget.get_mapped():
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = scrolled_window(child)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def list_scroller(page):
    """The Gtk.ScrolledWindow holding the page's list (its grid_view, column_view or
    list_view), mapped or not; else the first mapped scrolled window under it, or None."""
    for name in ('grid_view', 'column_view', 'list_view'):
        widget = getattr(page, name, None)
        while widget is not None and not isinstance(widget, Gtk.ScrolledWindow):
            widget = widget.get_parent()
        if widget is not None:
            return widget
    return scrolled_window(page)


waited = [0]  # polls since the library loaded, while the list is not shown


def start():
    if app.library.props.state == 'loading':
        GLib.timeout_add(100, start)
        return GLib.SOURCE_REMOVE
    window = app.get_active_window()
    if args.open and not opened[0]:
        opened[0] = True
        kind, item_id = args.open.split(':', 1)
        window.open_item(app.library.by_id(kind, item_id))
        GLib.timeout_add(1500, start)
        return GLib.SOURCE_REMOVE
    if not args.sidebar:
        window.split_view.set_show_content(True)  # a narrow window shows the page, not the sidebar
    page = window.sidebar if args.sidebar else window.navigation_view.get_visible_page()
    scrolled = list_scroller(page)
    if scrolled is not None and not scrolled.get_mapped():  # a status page shows meanwhile
        waited[0] += 1
        if waited[0] < 600:  # a minute
            GLib.timeout_add(100, start)
            return GLib.SOURCE_REMOVE
        scrolled = None
    if scrolled is None:
        print(f'scroll-test: no scrolled window shown on the {where()}', flush=True)
        app.quit()
        return GLib.SOURCE_REMOVE
    monitor = window.get_display().get_monitor_at_surface(window.get_surface())
    rate = monitor.get_refresh_rate() if monitor else 0  # millihertz; 0 when unknown
    interval = 1e9 / rate if rate else 1e6 / 60  # microseconds
    if args.type:
        type_into(window, page, interval)
        return GLib.SOURCE_REMOVE
    adjustment = scrolled.get_vadjustment()
    times = []
    work = []  # seconds of main-thread work per frame
    frame_clock = window.get_frame_clock()
    began = {}
    handlers = []

    def collect():
        """Time each frame's work from now on: the scrolling has begun."""
        handlers.extend([
            frame_clock.connect('before-paint',
                                lambda _clock: began.update(at=time.perf_counter())),
            frame_clock.connect('paint', lambda _clock: 'at' in began and work.append(
                time.perf_counter() - began.pop('at'))),
        ])

    fitted = []  # the frames in a row the laid-out list has fitted the window

    def tick(widget, clock):
        end = adjustment.get_upper() - adjustment.get_page_size()
        if end <= 0 and not times:
            if widget.get_height() <= 0 or adjustment.get_page_size() <= 0:
                fitted.clear()  # not laid out yet
                return GLib.SOURCE_CONTINUE
            fitted.append(adjustment.get_upper())
            if len(fitted) < FITS_FRAMES or len(set(fitted[-FITS_FRAMES:])) > 1:
                return GLib.SOURCE_CONTINUE  # laid out, but it may still be growing
            print(f'scroll-test: the {where()} fits the window at {window_size()}: '
                  'nothing to scroll', flush=True)
            GLib.timeout_add(200, app.quit)
            return GLib.SOURCE_REMOVE
        fitted.clear()
        if args.distance:
            end = min(end, args.distance)
        now = clock.get_frame_time()
        if not times:
            collect()
        times.append(now)
        adjustment.set_value(min(end, args.speed * (now - times[0]) / 1e6))
        if adjustment.get_value() < end:
            return GLib.SOURCE_CONTINUE
        for handler in handlers:
            frame_clock.disconnect(handler)
        report(times, work, interval, end)
        return GLib.SOURCE_REMOVE

    scrolled.add_tick_callback(tick)
    return GLib.SOURCE_REMOVE


def shown_count(page):
    """The items the page's list shows now."""
    for name in ('grid_view', 'column_view', 'list_view'):
        view = getattr(page, name, None)
        if view is not None and view.get_model() is not None:
            return view.get_model().get_n_items()
    return 0


def type_into(window, page, interval):
    """--type: the text typed into the page's filter and deleted, a key at a time; each
    refilter timed from the bar's `changed` to the end of its handlers, and the frames."""
    from applemusic.widgets.filter_bar import FilterBar

    bar = getattr(page, 'filter_bar', None)
    if bar is None or not page.focus_filter():
        print(f'scroll-test: no filter to type into on the {where()}', flush=True)
        app.quit()
        return
    texts = [args.type[:n] for n in range(1, len(args.type) + 1)]
    texts += texts[-2::-1] + ['']
    before = shown_count(page)
    began = {}
    refilters = []  # (text, seconds, items shown after)

    def hook(*_args):
        began['at'] = time.perf_counter()
        return True

    GObject.add_emission_hook(FilterBar, 'changed', hook)
    bar.connect_after('changed', lambda bar: refilters.append(
        (bar.entry.get_text(), time.perf_counter() - began.pop('at', time.perf_counter()),
         shown_count(page))))
    work = []
    frame_began = {}
    frame_clock = window.get_frame_clock()
    handlers = [
        frame_clock.connect('before-paint',
                            lambda _clock: frame_began.update(at=time.perf_counter())),
        frame_clock.connect('paint', lambda _clock: 'at' in frame_began and work.append(
            time.perf_counter() - frame_began.pop('at'))),
    ]

    def key():
        # A key's insertion or deletion, as typing makes it: set_text() would empty the
        # entry first, which refilters at once.
        if texts:
            text, typed = texts.pop(0), bar.entry.get_text()
            if len(text) > len(typed):
                bar.entry.insert_text(text[-1], len(typed))
            else:
                bar.entry.delete_text(len(text), -1)
            return GLib.SOURCE_CONTINUE
        for handler in handlers:
            frame_clock.disconnect(handler)
        report_typing(before, refilters, sorted(work or [0]), interval)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(int(args.key_interval), key)


def report_typing(before, refilters, work, interval):
    budget = interval / 1e6
    times = sorted(seconds for _text, seconds, _shown in refilters) or [0]
    print(f"scroll-test: typed {args.type!r} into the {where()}'s filter and deleted it, "
          f'{args.key_interval:.0f} ms a key, at {window_size()}; {before:n} items shown '
          f'before', flush=True)
    for text, seconds, shown in refilters:
        print(f'  {text!r:24} {1000 * seconds:6.1f} ms, {shown:n} shown', flush=True)
    print(f'  refilters: {len(refilters)}, median {1000 * statistics.median(times):.1f} ms, '
          f'longest {1000 * times[-1]:.1f} ms', flush=True)
    print(f'  work per frame: mean {1000 * statistics.mean(work):.1f} ms, '
          f'longest {1000 * work[-1]:.1f} ms; over {1000 * budget:.1f} ms: '
          f'{sum(w > budget for w in work)} of {len(work)}', flush=True)
    GLib.timeout_add(200, app.quit)


def where():
    if args.sidebar:
        return 'sidebar'
    return f'{args.open} page' if args.open else f'{args.page} page'


def window_size():
    window = app.get_active_window()
    return f'{window.get_width()}x{window.get_height()}'


def report(times, work, interval, distance):
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)] or [0]
    work = sorted(work or [0])
    budget = interval / 1e6
    print(f'scroll-test: {where()} at {window_size()}: {distance:.0f} px in '
          f'{(times[-1] - times[0]) / 1e6:.1f} s at {args.speed:.0f} px/s; '
          f'{decoded} covers decoded', flush=True)
    over = [(budget, f'{1 / budget:.0f} Hz')]
    if round(1 / budget) != 60:
        over.append((1 / 60, '60 Hz'))
    print(f'  work per frame: mean {1000 * statistics.mean(work):.1f} ms, '
          f'90th percentile {1000 * work[int(len(work) * 0.9)]:.1f} ms, '
          f'longest {1000 * work[-1]:.1f} ms; '
          + '; '.join(f'over {1000 * limit:.1f} ms ({rate}): '
                      f'{sum(w > limit for w in work)} of {len(work)}' for limit, rate in over),
          flush=True)
    rate = len(gaps) / ((times[-1] - times[0]) / 1e6)
    print(f'  frames drawn: {len(gaps)}, {rate:.0f} a second; '
          f'longest gap {max(gaps) / 1000:.1f} ms; gaps over 16.7 ms: '
          f'{sum(gap > 16700 for gap in gaps)}, over 33.3 ms: {sum(gap > 33300 for gap in gaps)}',
          flush=True)
    GLib.timeout_add(200, app.quit)


app.connect('activate', on_activate)
GLib.timeout_add_seconds(300, app.quit)  # whatever happens
harness.run_app(app)
