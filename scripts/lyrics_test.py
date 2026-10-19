#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Play an invented lyrics fixture through the Now Playing sheet's Lyrics tab and report what
it cost: the frames, the work in each, the CPU, the lyrics list's allocations.

    scripts/lyrics_test.py [--fixture NAME] [--start SECONDS] [--seconds N] [--size WxH]
                           [--no-animations] [--pronunciations] [--event-period SECONDS]
                           [--rtl] [--fullscreen-player] [--shot PNG]

Runs the installed build (meson install -C build, or scripts/run.sh, first) on the demo
library (scripts/harness.py), with animations on unless --no-animations (the word-timed
lyrics then light whole pieces rather than sweeping them), dark, the stock look, under
scripts/headless.sh like every GUI script:

    scripts/headless.sh scripts/lyrics_test.py
    scripts/headless.sh scripts/lyrics_test.py --fixture lyrics --start 0

The demo's first track plays from --start seconds (12: just before the syllable fixture's
first line) with the lyrics of --fixture (harness.LYRICS_FIXTURES: `syllable`, the default,
is word-timed), the sheet open on Lyrics. The Player hears what the engine would send:
`playbackTimeDidChange` with the position in whole seconds, every --event-period seconds
(0.25, as MusicKit does) plus a little jitter, from a random phase, so the Player's
estimate lags as it does live. After --seconds (36: nine lines of the syllable fixture,
English and Japanese, a duet's sides and background vocals) it reports, from the first
moment it played:

- the frames painted, the main thread's work in each (from the frame clock's before-paint
  to the end of its paint: tick callbacks, layout, snapshot and render), the layout phase
  alone, and the longest gap between frames;
- the process's CPU time against the wall clock's (one core is 100 %);
- the lyrics Gtk.ListView's size_allocate calls (counted through a subclass the view is
  given in place of Gtk.ListView): the centring's scrolls cause some, and a highlight
  that relaid the list out would cause many more;
- the Python time in the view's stepping (_follow, _paint and the sweep's tick, when the
  view has one), and how many times each ran;
- how far the Player's estimate was from the true position, sampled at each frame.

--fullscreen-player plays it in the full-screen player instead of the sheet, its larger
lines over the backdrop (the window kept at --size, as screenshot.py's is).
--shot saves the window as it is at the end (a sweep caught mid-piece, which screenshot.py,
with animations off, cannot show); --rtl lays it out right to left. Compare only headless
runs. Settings go to a memory backend.
"""

import argparse
import random
import statistics
import time

import harness

parser = argparse.ArgumentParser()
parser.add_argument('--fixture', default='syllable', choices=sorted(harness.LYRICS_FIXTURES))
parser.add_argument('--start', type=float, default=12.0, help='seconds in (default 12)')
parser.add_argument('--seconds', type=float, default=36.0, help='how long (default 36)')
parser.add_argument('--size', default='1100x760')
parser.add_argument('--no-animations', action='store_true')
parser.add_argument('--pronunciations', action='store_true',
                    help='with lyrics-pronunciations on')
parser.add_argument('--event-period', type=float, default=0.25,
                    help='seconds between position events (default 0.25)')
parser.add_argument('--rtl', action='store_true', help='lay the window out right to left')
parser.add_argument('--fullscreen-player', action='store_true',
                    help='in the full-screen player rather than the sheet')
parser.add_argument('--shot', metavar='PNG', help='save the window at the end')
args = parser.parse_args()
width, height = (int(n) for n in args.size.split('x'))

app = harness.make_app('LyricsTest', animations=not args.no_animations,
                       size=(width, height), name='lyrics-test')

from gi.repository import GLib, Gtk  # noqa: E402  (after make_app)

from applemusic.widgets import lyrics as lyrics_view  # noqa: E402

allocations = [0]
timed = {}      # method name -> [calls, seconds]


class CountingListView(Gtk.ListView):
    def do_size_allocate(self, width, height, baseline):
        allocations[0] += 1
        Gtk.ListView.do_size_allocate(self, width, height, baseline)


class GtkWithCountingList:
    """widgets/lyrics.py's Gtk, but for the ListView it makes."""

    ListView = CountingListView

    def __getattr__(self, name):
        return getattr(Gtk, name)


lyrics_view.Gtk = GtkWithCountingList()


def timing(name):
    method = getattr(lyrics_view.LyricsView, name, None)
    if method is None:
        return
    record = timed.setdefault(name, [0, 0.0])

    def wrapper(*method_args, **kwargs):
        began = time.perf_counter()
        try:
            return method(*method_args, **kwargs)
        finally:
            record[0] += 1
            record[1] += time.perf_counter() - began

    setattr(lyrics_view.LyricsView, name, wrapper)


for name in ('_follow', '_paint', '_on_sweep_tick'):
    timing(name)


def on_activate(_app):
    GLib.timeout_add(500, begin)


if args.rtl:
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)


def begin():
    if app.library.props.state == 'loading':
        GLib.timeout_add(100, begin)
        return GLib.SOURCE_REMOVE
    window = app.get_active_window()
    app.settings.set_boolean('lyrics-pronunciations', args.pronunciations)
    app.player.apply(harness.invented_playing_state(app, lyrics=True, fixture=args.fixture,
                                                    position=args.start))
    window.now_playing.tab_stack.set_visible_child_name('lyrics')
    if args.fullscreen_player:
        window.activate_action('win.fullscreen-player', None)
    else:
        window.bottom_sheet.set_open(True)
    GLib.timeout_add(1500, run, window)  # the sheet (or the player) shown and laid out
    return GLib.SOURCE_REMOVE


def run(window):
    player = app.player
    began_at = time.monotonic()
    duration = player.duration
    rng = random.Random(304)

    def truth():
        return args.start + time.monotonic() - began_at

    # From here the position runs on from args.start, as the true clock does.
    player.position_updated_at = began_at
    allocations[0] = 0
    for record in timed.values():
        record[:] = [0, 0.0]
    clock = window.get_frame_clock()
    work, layouts, frames, errors, began = [], [], [], [], {}
    feeder = [0]

    def feed():
        player._on_event(None, 'playbackTimeDidChange',
                         {'position': float(int(truth())), 'duration': duration})
        feeder[0] = GLib.timeout_add(int(args.event_period * 1000 + rng.uniform(0, 40)), feed)
        return GLib.SOURCE_REMOVE

    def before_paint(_clock):
        began['frame'] = time.perf_counter()

    def update(_clock):
        began['layout'] = time.perf_counter()  # after the tick callbacks

    def layout(_clock):
        if 'layout' in began:
            layouts.append(time.perf_counter() - began.pop('layout'))

    def paint(_clock):
        if 'frame' in began:
            work.append(time.perf_counter() - began.pop('frame'))
            frames.append(clock.get_frame_time())
            errors.append(player.estimated_position() - truth())

    handlers = [clock.connect('before-paint', before_paint), clock.connect('update', update),
                clock.connect('layout', layout), clock.connect('paint', paint)]
    feeder[0] = GLib.timeout_add(int(rng.uniform(0, args.event_period * 1000)), feed)
    cpu_began = time.process_time()
    wall_began = time.perf_counter()

    def finish():
        cpu = time.process_time() - cpu_began
        wall = time.perf_counter() - wall_began
        GLib.source_remove(feeder[0])
        for handler in handlers:
            clock.disconnect(handler)
        report(wall, cpu, sorted(work) or [0], sorted(layouts) or [0], frames,
               sorted(errors) or [0])
        if args.shot:
            snapshot = Gtk.Snapshot()
            Gtk.WidgetPaintable(widget=window).snapshot(snapshot, window.get_width(),
                                                        window.get_height())
            window.get_renderer().render_texture(snapshot.to_node(), None).save_to_png(
                args.shot)
            print(args.shot, flush=True)
        GLib.timeout_add(200, app.quit)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(int(args.seconds * 1000), finish)
    return GLib.SOURCE_REMOVE


def report(wall, cpu, work, layouts, frames, errors):
    gaps = [b - a for a, b in zip(frames, frames[1:], strict=False)] or [0]
    options = ' '.join(option for option, on in (('no animations', args.no_animations),
                                                 ('pronunciations', args.pronunciations))
                       if on)
    print(f'lyrics-test: {args.fixture} from {args.start:g} s for {wall:.1f} s at '
          f'{args.size}{", " + options if options else ""}', flush=True)
    print(f'  frames {len(work)}, {len(work) / wall:.1f} a second; work per frame: mean '
          f'{1000 * statistics.mean(work):.2f} ms, 90th percentile '
          f'{1000 * work[int(len(work) * 0.9)]:.2f} ms, longest {1000 * work[-1]:.2f} ms, '
          f'over 16.7 ms: {sum(w > 1 / 60 for w in work)}; layout phase mean '
          f'{1000 * statistics.mean(layouts):.3f} ms; longest gap {max(gaps) / 1000:.0f} ms',
          flush=True)
    print(f'  CPU {cpu:.2f} s in {wall:.1f} s ({100 * cpu / wall:.1f} % of a core); '
          f'lyrics list allocated {allocations[0]} times', flush=True)
    print('  Python: ' + ', '.join(f'{name} {calls}x {1000 * seconds:.1f} ms'
                                   for name, (calls, seconds) in timed.items()), flush=True)
    print(f'  estimate - true position: mean {1000 * statistics.mean(errors):.0f} ms, '
          f'from {1000 * errors[0]:.0f} to {1000 * errors[-1]:.0f} ms', flush=True)


app.connect('activate', on_activate)
GLib.timeout_add_seconds(int(args.seconds) + 60, app.quit)  # whatever happens
harness.run_app(app)
