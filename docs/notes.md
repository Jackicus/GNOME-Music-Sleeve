# Lab notes

Findings and measurements that explain the code but are not rules. Each was true when it was
written down (September 2026: GTK 4.22, libadwaita 1.9, PyGObject 3.56, Python 3.14, Chrome
154, on the development machine); re-check one before building on it, and date what you add.

The measurements behind the list and model code live in the module docstrings, next to the
code they justify: `pages/songs.py` (GTK's sorters and filters over Python objects, row
rebuilding), `pages/grid.py` (expression sorters against a custom sorter), the library package
(`library/objects.py`: `raw_property`'s memory; `records.py`: `TrackRecord`'s; `songs.py`:
`SongOrder`'s keys; `diff.py`: `apply_diff`; `pacing.py`: `paused_gc`, `yield_to_frames`), and `widgets/artwork.py` (texture sizes, the cache budget). The
performance pass that produced most of them is written up in `docs/history/build-plan.md`, in
its "Performance pass" section.

## The development machine

- A bare `Adw.ApplicationWindow` paints its first frame about 760 ms after its process starts:
  loading the desktop's icon theme takes about 200 ms of GTK's start, and `present()` waits about
  330 ms for the compositor's first configure. Its RSS is about 158 MB, 105 MB of it
  file-backed (the NVIDIA driver maps about 50 MB). No change to the app removes this floor;
  the startup target is the app's own share over it (performance.md: content painted within
  250 ms of the bare window's first frame, `scripts/bench.py` pairing each run with a bare
  window's).
- Startup on build/demo-big, headless, 2026-10-20 (issue 476), `bench.py --runs 5`, the
  base (main) and the branch benched in turns three times each, medians: a bare window's
  first frame 805-842 ms, run by run 790-860 (the first start after a while is cold,
  1.7-1.9 s: bench.py now starts one untimed first). The bare window: its imports 120 ms,
  `Adw.Application` started at 400, mapped at 750 (`present()` waits about 350 ms for the
  compositor), painted 18 ms later. The app before:
  imports to 177 ms, GTK started 479, activate 515, window built 552, mapped 935, content
  painted 1083-1107 ms, the app's own share 259-298 ms. From the map to the first paint
  (150-170 ms), the Albums page restored at startup made 129 tiles for the 12 in view: the
  albums' splice took 33 ms (sorting 3,000 Items by title, 18 ms of it, through the title's
  Python getter; the tiles), and the frame's layout 50-62 ms and paint 15. Made for the rows
  that fit (`grid.first_tiles()`: 20 tiles at 1100x760) and the rest 16 a frame after the
  first paint, content was painted at 995-1047 ms, the app's own share 182-219 ms; the
  frame's layout 33-38 ms. What is left of the app's share: about 60 ms more imports than the
  bare window's, 35 ms from GTK's start to activate (the engine, player, sync and MPRIS
  objects), 40 ms building the window, about 40 ms more for the compositor to map the larger
  window, then 95 ms from the map to the paint (the albums' 30 ms splice, the window's first
  layout and paint). The first visits of Recently Added and All Playlists went from 86-90 ms
  to 26-31 ms, their tiles' growth showing as a 15 ms frame after; the Albums page shown again
  after the tour's first pages took 20 ms instead of 12. On the skill's library as it is now
  (`--videos 1000 --long-playlist 5000` too), two benches each: content 1062-1115 ms to
  1004-1064, the app's own share 253-268 ms to 172-220; Music Videos' first visit 88-91 ms to
  34-35.
- Timings vary by 100 ms or more between runs with the usual desktop load: `bench.py --runs 5`
  and medians.
- The monitor runs at 240 Hz, and an unfocused window may get 60 frames a second, so
  `scroll_test.py` reports the app's own work per frame. The compositor sends no frames to a
  window it does not show, so a hidden bench or scroll-test window stalls.
- A tiling extension resizes windows that are resizable when mapped; the scripts make theirs
  non-resizable (`scripts/harness.py`).
- No input can be synthesised on this Wayland desktop: live runs on the desktop are driven
  with `gapplication action`, `scripts/am.py` and D-Bus. Under `scripts/headless.sh`,
  `a11y_check.py` sends real keys through the headless mutter's RemoteDesktop
  (`scripts/remote_keys.py`); only its `--emulate-keys` fallback dispatches them through GTK's
  own controllers.

## The targets against v1.2.0, on a quiet machine (2026-11-12, issue 587)

Main after the 2026-11-11 session (c6c2fe1) against v1.2.0 built the same day from `git
archive v1.2.0` with main's `scripts/bench.py` copied in (its harness, scroll_test.py and
demo_library.py are v1.2.0's own, unchanged since), both on one build/demo-big made by
main's generator. GTK 4.24.1, libadwaita 1.10.0, GLib 2.90.1, PyGObject 3.58.1, Python
3.14.8, Meson 1.12.1, kernel 7.3.0-4-cachyos; headless at 1100x760, scale 1. Each series ran
alone, five runs, medians and the runs' range in brackets; the owner's music played in the
installed app throughout (its headless Chrome about a quarter of a core per process).

| | target | v1.2.0 | main |
|---|---|---|---|
| the series' machine: load, idle, available, swap | | bench 3.4 to 1.9, idle 94, 8.9-10.4 GB, 1.3-1.5 GB; scroll 1.0 to 3.4, idle 93-94, 8.2-9.7 GB, 1.3-1.9 GB | bench 1.6 to 2.0, idle 91-96, 9.4-10.3 GB, 1.3 GB; scroll 2.6 to 2.8, idle 88-94, 7.9-8.1 GB, 1.9-2.2 GB |
| a bare window's first frame | | 756 ms (732-848) | 740 (733-780) |
| content painted | | 955 ms (948-1042) | 945 (931-964) |
| the app's own share (bench.py's line; run by run) | 250 ms | 208 ms (107-286) | 198 (177-228) |
| longest first switch (Favourite Songs) | 100 ms | 71 ms (68-81) | 71 (69-77) |
| Songs built and painted; the longest frame after its switch | | 589 ms (580-628); 70 (69-76) | 581 (568-585); 58 (57-59) |
| first visits: Albums, Recently Added, All Playlists, Music Videos, a playlist | | 21, 29, 26, 33, 12 ms | 19, 28, 25, 32, 11 |
| pages' first paint: album, library artist, artist page, See All, Charts, Replay, search See All | | 32.2 (31.6-33.7), 15.3, 17.7, 16.9, 11.4, 11.9, 25.7 ms | 31.9 (31.8-32.3), 14.9, 17.8, 16.7, 11.4, 11.3, 24.7 |
| anonymous memory, every page browsed twice | 250 MB | 228 MB (226-229) | 227 (227-229) |
| pages step, anonymous, three rounds | 5 MB | +4.5 MB (3.6-5.7) | +3.3 (2.1-3.9) |
| malloc's bytes in use after each round | | +0.48, +0.92, +1.29 MB | +0.18, +0.33, +0.42 |
| Albums scrolled to the bottom: work a frame, mean / 90th / longest | no frame over 16.7 ms | 3.1 (2.8-3.3) / 3.9 / 9.0 ms, none over | 2.7 (2.6-2.9) / 3.5 / 7.7, none over |
| Songs, 40,000 px | no frame over 16.7 ms | 5.7 (5.3-6.6) / 7.6 / 12.4 ms, none over | 3.8 (3.7-4.1) / 4.9 / 8.3, none over |
| the 5,000-song playlist, 40,000 px | no frame over 16.7 ms | 3.3 (3.1-3.4) / 4.6 / 6.8 ms, none over | 3.2 (3.1-3.4) / 4.4 / 6.4, none over |

Nothing regressed: every median of main is within v1.2.0's range or better. Two are better
by more than the noise. The pages step, by #585's two leak fixes (Memory, below: malloc's
bytes in use a third of v1.2.0's, as #585 measured under load). And Songs: v1.2.0 on GTK
4.24 prints about 97,000 "Trying to measure GtkColumnViewCellWidget … for width of 0"
warnings a Songs scroll, which main's constant-size SongTitle (b1d6bbc, #565) stopped; its
Python layout manager costs less than the warnings did. The earlier figures, for
reference: startup's own share 172-220 ms (2026-10-20, issue 476); Favourite Songs' first
switch 77-91 ms and 226-229 MB after browsing (2026-10-21, issue 527); Albums' scroll 2.3 /
3.5 / 9.6 ms (docs/history/build-plan.md), Songs' 4.6 ms (longest 12.6) and the long
playlist's 4.3-4.5 (issues 527 and 363); the pages step +2.8 MB under load (issue 541).
Swap grew from 1.3 to 2.2 GB over the four series from something else on the desktop; the
memory readings agree with each other across it.

How these were taken, from a tree's root (the main checkout's or the scratch copy of
v1.2.0's), the build installed into its own build/install:

```
scripts/demo_library.py --cache build/demo-big --albums 3000 --playlists 300 --tracks 40000 \
    --videos 1000 --long-playlist 5000                 # once, by the newest tree's generator
meson setup build --prefix="$PWD/build/install" -Dprofile=development; meson install -C build
uptime; vmstat 5 3; top -b -n 2 -d 3 | head -20       # quiet: idle 93 % or more, nothing
                                                      # else over half a core
scripts/headless.sh scripts/bench.py --runs 5 --cache "$PWD/build/demo-big"
for list in "--page albums" "--page songs --distance 40000" \
            "--open playlist:l.pllong --distance 40000"; do
    for run in 1 2 3 4 5; do
        APPLE_MUSIC_CACHE="$PWD/build/demo-big" scripts/headless.sh scripts/scroll_test.py $list
    done
done
```

`bench.py` prints each run's startup, longest switch and pages step and the medians of the
rest; to keep every run's figures (the ranges above), the same runs went through a wrapper
that records each child's `bench-result:` line (kept, with the raw runs and the summary
scripts, in the main checkout's git-ignored build/perf-pass/).

## Resizing the window, against v1.2.0 and Nautilus (2026-11-12, issue 590)

`scripts/resize_test.py` with its defaults: the width 1400 px down to 360 and back three
times at 1000 px/s, 760 px high, a frame at a time (`set_default_size()` from a tick),
then a fourth round under cProfile for the Python time. v1.2.0 from `git archive v1.2.0`
with main's resize_test.py copied in, main at b017fee, main after the fixes below (#594,
#595 and the grids' columns, on 90f7cbd), one build/demo-big; the same
machine, toolkit and headless display as the section above. Each series ran alone, five
runs a page, medians and the runs' range; the owner's music played throughout. Work is a
frame's main-thread work (before-paint to the end of paint); "over" counts frames over
16.7 ms.

| page | target | v1.2.0: mean / 90th / longest work, over | main before: the same; Python a frame | main after: the same; Python a frame |
|---|---|---|---|---|
| the series' machine: load, idle, available, swap | | 2.1-2.2, idle 95-96, 9.8 GB, 3.6-3.7 GB | 2.1-2.4, idle 96, 9.5-9.6 GB, 3.5-3.6 GB | 1.8-2.2, idle 96-98, 9.5-10.0 GB, 2.8-2.9 GB (Now Playing run again: Discord took 1.5 cores at the end of the series) |
| Albums | longest 50 ms, 4 % | 9.0 / 14.1 / 137 ms (136-155), 9.5 % | 9.2 / 14.6 / 138 (136-142), 9.9 %; 1.9 ms | 8.6 / 11.7 / 135 (133-138), 9.1 %; 1.6 |
| a library artist (`--open artist:most`) | | 6.5 / 7.7 / 102 (101-108), 5.2 % | 6.8 / 8.0 / 108 (103-111), 5.2 %; 0.8 | 6.3 / 7.5 / 102 (101-112), 5.2 %; 0.7 |
| Songs | | 15.7 / 27.4 / 224 (221-224), 12.4 % | 14.1 / 23.0 / 234 (226-235), 11.6 %; 13.2 | 13.0 / 21.8 / 217 (217-220), 10.3 %; 4.2 |
| Home | | 7.0 / 8.1 / 104 (98-107), 5.2 % | 7.2 / 8.5 / 105 (104-106), 5.2 %; 0.9 | 6.9 / 7.9 / 103 (99-106), 5.2 %; 0.7 |
| an album (`--open album:first`) | | 7.7 / 9.0 / 125 (123-126), 6.3 % | 8.0 / 9.0 / 126 (120-127), 6.3 %; 1.3 | 7.5 / 8.6 / 122 (117-127), 6.3 %; 1.0 |
| a playlist (`--open playlist:first`) | | 8.8 / 10.8 / 137 (133-143), 7.1 % | 8.6 / 11.1 / 134 (132-141), 7.1 %; 1.5 | 8.1 / 9.9 / 132 (130-134), 6.3 %; 1.2 |
| Albums, Now Playing open | | 11.2 / 21.9 / 159 (143-166), 11.1 % | 10.7 / 20.9 / 157 (143-166), 10.0 %; 2.6 | 9.8 / 14.9 / 136 (133-138), 8.8 %; 2.0 |
| Albums dragged 1400 to 700 and back only (`--narrow 700`) | | | 6.3 / 9.9 / 27 (26-28), 7.7 %; 1.4 | 5.3 / 8.2 / 19 (18-20), 2.4 %; 0.3 |

Main before the fixes was v1.2.0 within the noise: the stutter the owner saw on 1.2.0 was
all still there. Every page's longest frame is the one where the window's 640sp breakpoint
collapses or expands the split view (625-655 px), and the frame after it is the next longest
(50-60 ms, Songs 95); the rest of the frames over budget are a grid's column count rising
(20-29 ms) and, on Songs, its own breakpoint (33-44 ms, and 75 ms when the sweep lands past
it just after the expand). The causes,
each measured with the scripts kept in build/perf-pass/resize/ (one width change at a time,
25 frames apart, the frame that lays it out timed and profiled):

- The split view collapsing or expanding: 115-140 ms on a page with a grid or list,
  200-230 ms on Songs. `Adw.NavigationSplitView` moves the content page into its own
  navigation view and back, and a `Gtk.GridView`, `ListView` or `ColumnView` that is moved
  drops every row and builds them all again (GTK below). The grid's 65-97 tiles cost about
  25 ms of Python (`Tile.__init__`, its template) and as much again in GTK; Songs' 205 rows
  about 100 ms of Python (SongTitle, the cells' setup, the artist line). The same
  breakpoint's `sidebar.mode: page` has `Adw.Sidebar` build all its rows again for the new
  mode: alone, at a fixed width, 61-113 ms with build/demo-big's 300 playlists, plus
  `SidebarController.update_rows()` (about 8 ms, and before #594 again from an idle,
  which lengthened the gap after the crossing by 12 ms on Albums). On build/demo
  the whole crossing takes 32-34 ms; with the grid's model taken away 84-92 ms.
- Songs re-sorts each time: the move unrealizes and realizes the page, and `do_realize`
  calls `_on_songs_changed()`, which makes a new `SongOrder` and prepares its keys over
  frames (about 0.6 s of Python a collapse and expand, 13 ms a frame on average over the
  sweep), then splices the same order in. Fixed in #595 (it sorts again only when the store
  changed while it was unrealized): 4.2 ms of Python a frame. It ran between frames, so the
  frames themselves moved little.
- A grid's columns: widening past a column, the grid page raises `max-columns` at once and
  the grid builds a column of about 30 tiles in that frame, 20-29 ms (about 9 ms of it
  `Tile.__init__`); narrowing lowered it from an idle, which dropped them, so every
  widening built them again. Now lowered only once the width has settled
  (`grid.FewerColumns`, 400 ms) or as the page is unrealized: a drag that stays above the
  collapse (1400 to 700 px) has 2.4 % of its frames over budget, and none over 20 ms, where
  it had 7.7 %. The default sweep crosses the collapse each round, which lowers the columns
  first (keeping them through it made that frame 40-60 ms longer, the grid building more
  tiles again), so there each widening still builds them.
- Songs' narrow breakpoint (560sp of the page, a window about 770 px wide with the sidebar):
  showing the album and artist columns again makes their 410 cells anew (GTK below), 33-44
  ms (55-76 ms when it follows the expand), 17-18 ms of it `TrackLinks.__init__`. Left as
  it is: a cheaper label would take about 8 ms off a frame that would still be over
  budget.
- Between those, a resized frame costs 3-4 ms below about 890 px and 7-9 ms above (four
  columns of tiles, or Songs' seven columns): GTK's layout and render, inside the budget.

Nautilus 51.1, for the target: a separate instance on the same headless display, its own
session bus activating nothing (so no indexer, and nothing reaches the desktop's bus or the
owner's Nautilus), a scratch home and settings in memory, showing a folder of 3,000 invented
empty files in its default grid. A program that is not ours cannot be resized from inside,
so it was resized the compositor's way, mutter's keyboard resize (`begin-resize` through
`remote_keys.py`, 10 px a key every 10 ms: the same range and speed, three rounds), and its
frames read from its `GDK_DEBUG=frames` lines, whose times are when each frame ended. The
two ways agree: Music Sleeve's Albums resized by the keyboard, with both its own timing and
those lines, gave 138 and 118 ms at the split view (the lines' gaps 140 and 129 ms).
Nautilus, five runs (load 1.5-1.7, idle 95-96, swap 3.7 GB): about 350 frames a sweep, 12-17
of the gaps between them over 16.7 ms (3.4-4.9 %), 12 of those of two frames or more, three
or four frames (50-67 ms) as the window crosses its breakpoints, and no frame's work over 20
ms. Its first run of the day had one 217 ms gap at its first crossing, as caches filled.

The target (`.claude/rules/performance.md`) is Nautilus's: no frame's work over 50 ms, and
no more than 4 % of a sweep's frames over 16.7 ms. After the fixes no page meets it in the
default sweep: every page's longest frame (102-217 ms) and most of its frames over budget
are the split view's collapse and the frame after it, which only a change of design
removes (#593: `Adw.OverlaySplitView`, or keeping the sidebar's mode). A drag that stays
above 640 px meets it on Albums (longest 19 ms, 2.4 % over) and the library artist (none
over).

The other targets after the fixes, against the table above (#591's main): bench.py's five
runs unmoved (the app's own share 197 ms (182-226) against 198, the longest first switch
67 ms against 71, browsed anonymous memory 228 MB against 227, the pages step +3.4 MB
against +3.3); scroll_test.py on Albums five runs, 2.7 / 3.4 / 5.5 ms, none over (2.7 /
3.5 / 7.7), and Songs two runs, 3.6-3.8 / 4.6-5.0 / 8.3-12.7 ms, none over (3.8 / 4.9 /
8.3); the rest of that series was stopped as the session ended.

## GTK and libadwaita, measured

- `Adw.NavigationSplitView` collapsing or expanding moves its content, and a list view that
  is moved tears down and builds again every row it keeps (GTK 4.24.1, libadwaita 1.10.0,
  2026-11-12): a bare window with a `Gtk.GridView` of 3,000 items (simple tiles, the default
  12 columns) in the content tore down and set up all 385 tiles at each crossing, 87-102 ms a
  frame; the same window with `Adw.OverlaySplitView`, which keeps the content in place, and
  without a split view, 3-4 ms. A `Gtk.ColumnView` column shown again (`visible`) makes its
  cells anew, one per row kept. `Adw.Sidebar` builds all its rows again when its mode
  changes (300 playlists: 61-113 ms).
- AdwSidebar at about 150 playlist rows (162 playlists and 7 folders in one test library):
  splicing them in took about 24 ms, then one 15-17 ms frame; scrolling the list at 2,000-4,000
  px/s cost about 0.5 ms of work a frame. A reload with the same shapes keeps the items and costs
  about 5 ms. Its rows are real widgets, not recycled: a few thousand playlists would need a
  lighter path.
- A `Gtk.GridView` of 2,000 items bound about 52,000 times scrolling top to bottom; a wrapping
  `Gtk.Label` in each tile cost about 7 ms a frame at 4,000 px/s against about 1 ms for a
  `Gtk.Inscription`. An `Adw.Avatar` is about 18 KB and a third of a tile's construction time.
- A full garbage collection over a loaded 3,000-album, 40,000-song library took about 50 ms,
  hence `paused_gc`. A chunked load that yielded with `asyncio.sleep(0)` painted no frames; with
  `yield_to_frames()` it painted as it went.
- Nested scrolling needs no code: a scrolled window handles a scroll event only along an axis it
  can scroll, so a vertical wheel over a shelf (`vscrollbar-policy: never`) scrolls the page and
  a horizontal one the shelf. A diagonal touchpad swipe stays with the shelf; libinput locks a
  two-finger scroll to one axis, and once the page has started a touchpad scroll it keeps the
  gesture even over a shelf. In a test, emit `scroll` on the bubble-phase
  `Gtk.EventControllerScroll` (the capture-phase one only continues a scroll in progress).
- `Adw.BottomSheet` clamps its sheet to the window less a top margin of about 30 px, and
  Escape is a local `Gtk.ShortcutController` on the sheet's inner widget, which the open sheet's
  focus satisfies.
- `Gio.Settings.bind_with_mapping` exists in PyGObject 3.56, but its get-mapping closure got
  the GValue as a plain int it could not set, and GLib aborted on the rejected default; the
  refresh-interval row in Preferences is bound by hand instead.
- A sidebar row's context menu opens from a script through
  `SidebarController.popup_menu(key)`, as Menu on the focused row opens it. A
  `Gtk.PopoverMenu` submenu is named by its label, mnemonic underscore and all:
  `visible-submenu` 'Add to Pla_ylist' opens it (screenshot.py's `--submenu`).
- A stand-in texture of another size (`ArtworkSlot` showing `get_any()` while the size wanted
  decodes) changes the picture's size twice, and each time lays the list out again. The worst
  case, Songs scrolled at 2,000 px/s with every row's thumbnail cached only at the tiles'
  160 px (headless, 40,000 songs, 2026-09-29): 3.1-3.5 ms of work a frame against 2.9 ms
  without stand-ins, the longest frame the same (5.2-5.6 ms). Kept: the rows show the cover at
  once instead of the placeholder.
- The Songs table's artist and album link columns (`TrackLink`, issue 262), which made a
  20,000 px/s fling 4.8 ms of work a frame against 4.0 ms before them (headless, 40,000 songs,
  for 0.11.0). Per cell, bound, measured, allocated and snapshotted in a realized window
  (process time, 2026-10-08): a `TrackLink` 17-20 µs, a plain one-line `Gtk.Label` 15-17.5 µs,
  a `Gtk.Inscription` 15-17 µs. An Inscription saves nothing over a label that keeps its single
  line, and it could not keep the link to the text's width. The link's own work (`show()`:
  the text and `related.has_artist`/`has_album`) is about 2 µs a cell, about 0.13 ms a frame at
  that speed (33 rows bound a frame); the rest of the difference is two more columns of text
  laid out and drawn, which showing them costs. No frame went over 16.7 ms, so nothing was
  changed.
- Word-by-word lyrics (issue 304), headless, 2026-10-19: `scripts/lyrics_test.py`, the
  syllable fixture from 12 s for 36 s (nine lines, 73 pieces), 60 Hz virtual monitor,
  Vulkan renderer, 1100x760, whole-second positions fed about four times a second.

  | | frames | work a frame (mean, longest) | CPU (one core) | list allocations |
  |---|---|---|---|---|
  | before: the line lit whole | 645 | 0.78-0.80 ms, 3.9 ms | 1.9-2.0 % | 81 |
  | before, animations off | 51 | 0.86 ms, 2.3 ms | 0.4 % | 12 |
  | after: the pieces swept | 1865-1890 | 1.08-1.13 ms, 4.5 ms | 6.9-7.3 % | 81 |
  | after, animations off (whole pieces) | 110 | 1.06 ms, 3.2 ms | 0.8 % | 12 |
  | after, swept, pronunciations on | 1891 | 1.02 ms, 3.9 ms | 6.4 % | 93 |

  The list's allocations are the centring's only: no word lays anything out. The sweep's
  Python is about 0.08 ms a frame (the tick and its `_follow`), a masked label's snapshot
  about 0.1 ms; the rest is GTK's frame and the render. A line-timed song plays as before
  (no tick). Prototypes measured the same way before choosing: lighting by a
  `Pango.AttrList` of foreground alphas (`set_attributes()` at each word) cost about the same
  per step (about 1 ms frames) but reallocated the list about 0.85 times a word (164
  allocations against 103 for the mask, same glides), and could not fill a piece in part;
  capping the sweep at 30 redraws a second saved only 1.5 % of a core (5.5 %), so it redraws
  at the frame rate up to about 60 a second. The Player's estimate was 0 to 265 ms behind the
  true position (mean about 130 ms): MusicKit's whole seconds are stamped when first seen.
  It never runs back in steady play (it holds at most a report's lateness at a second's
  change), but falls back to the last whole second on a pause, hence the view's hold.
  `Pango.LayoutLine.get_x_ranges()` is unusable from PyGObject 3.56: its array's length
  annotation counts pairs, so it returns half the values (one number for one range);
  `Layout.index_to_line_x()` and the line's extents give the same edges. bench.py (5 runs,
  medians) and scroll_test.py before and after: content 924 / 927 ms, longest switch 65 / 67
  ms, anonymous memory after browsing 196 / 195 MB, pages +1.4 / +1.1 MB; Albums 4.0 / 4.1 ms
  a frame (longest 7.4 / 7.2), Songs 2.9 / 3.0-3.2 ms (longest 5.3 / 7.0-8.7), no frame over
  16.7 ms: the same, within the runs' spread (the lyrics view is not on those paths).
- The lyrics' faded edges (issue 356), headless, 2026-10-20: `scripts/lyrics_test.py` as
  above (the syllable fixture from 12 s for 36 s, 1100x760), three runs each, in the sheet
  and with `--fullscreen-player`, before and after the view drew its page through the
  edges' alpha mask (a mask node over the whole view, made again at each frame the view
  draws, the sweep's included). The machine was shared, so the runs spread widely.

  | | work a frame (mean) | CPU (one core) | list allocations |
  |---|---|---|---|
  | sheet, before | 1.17-1.52 ms (median 1.43) | 7.7-9.6 % | 81 |
  | sheet, after | 1.57-1.79 ms (median 1.58) | 9.4-9.6 % | 81-99 |
  | full screen, before | 1.29-1.82 ms (median 1.35) | 8.6-11.7 % | 81-99 |
  | full screen, after | 1.52-1.72 ms (median 1.54) | 9.0-10.8 % | 81-105 |

  About 0.15-0.2 ms a frame more, the CPU within the runs' spread; one frame in a run went
  over 16.7 ms before and after alike (the shared machine). The allocations are the
  centring's glides and vary from run to run either way. Masking only the two 64 px bands
  (the middle drawn plainly under a clip) would render less offscreen, but two clips that
  meet off the pixel grid at a fractional scale leave a faint seam, and the whole-view
  mask costs too little to need it.
- Hidden root pages keep their list and grid widgets (the window keeps each fixed
  destination's root page once visited, and the last eight playlist and folder pages).
  Letting the six hidden views' item widgets go while they are hidden, and rebuilding them on a
  revisit, would free about 6.3 MB on the 3,000-album, 40,000-song library (headless,
  2026-09-29): under the 10 MB it had to save to be worth a rebuild on every revisit, so it is
  not done.
- A focused entry destroyed with its page and GTK's Wayland text input (2026-10-01, GTK
  4.22.5, mutter 50.4, headless). The first `Gtk.Text` to take the focus in a process binds
  the `zwp_text_input_v3` object, and the compositor answers at once with `enter`. If that
  entry is destroyed before the main loop has dispatched the answer, GTK still holds the dead
  context and the `enter` crashes the process in `gtk_widget_get_display`
  (`text_input_enter` → `enable`), which is what a page test's synchronous teardown did
  (tests/page_harness.py): focus the entry, tear the page down, pump. Moving the focus off
  first (`set_focus(None)`) alone does not help; one main-loop turn before the teardown does,
  and a later focus (the text input bound already) torn down the same way is harmless. With
  the turn, every teardown was clean: the Search page's entry and the Songs filter focused
  and typed into, the page dropped and freed, then the keyboard moved to another window and
  back (the compositor's `leave` and `enter`), with the protocol log showing `enable` at the
  focus, `disable` at the teardown and nothing dangling. The app never destroys a page in
  the same loop iteration as a first focus: sign-out's `forget_account_pages()` (account.py)
  comes after the engine's stop, the wipe and the library's reload; eviction past
  `ROOT_LIMIT` and a sync's stale playlists drop only pages not shown; and a drop moves the
  focus into the new root page by itself (libadwaita's replace). Driven on the demo library
  over scripts/harness.py with real keys (scripts/remote_keys.py), with and without
  animations, the window active and not: no crash in any of 20-odd rounds, so nothing was
  changed in the window (issue 254).
- Up Next over a 500-entry invented queue (420x760, the headless display, medians of five;
  the time to apply a queue event, then two frames drawn; the list keeps about 205 rows):
  when the Player replaced the whole store at every difference, one entry removed cost 186
  ms and made and bound 205 rows, ten removed one event each (Autoplay turned off) 1.8 s
  and 2,050 rows, a move as two splices 350 ms, one entry appended 179 ms; with the store
  spliced only where it differs (#332) those are 10 ms and one row, 98 ms and ten rows, 19
  ms and two rows, 5 ms and none. A whole new queue is the same either way (183 ms, 205
  rows), as is the next entry playing (4 to 7 ms, one row).
- Up Next's moves (#361), on a 500-entry invented queue with covers, 420x800, the headless
  display, the move made locally (the Player's store and Up Next's handlers), medians of
  nine, a frame alone 16 ms: the entry taken out and the same object put back (two
  splices of one), 2 <-> 3 in view 9 ms for the splices and handlers and 43 ms to the next
  frame (one row made and bound: the moved one), 1 <-> 499 10 and 25 ms, 200 <-> 201 out
  of view 8 and 18 ms. One splice of the whole span between the two places with the same
  objects in their new order (at most one row made and bound too) cost 26 and 42 ms, 91 and
  131 ms, 22 and 31 ms: the far moves several times slower, so the Player removes and
  inserts.
- Up Next with covers and History (#353), on the same 500-entry invented queue (each album's
  entries their own artwork, on disk: the demo fetches nothing), 420x760, the headless
  display, before (origin/main) and after run in turns, medians of five each: a whole new
  queue 240 -> 255 ms (205 rows made and bound either way, a row now a cover too: 1 ms to
  make), the next entry playing 14 -> 15 ms (one row); a scroll from the top to the bottom
  at 4,000 px/s, work a frame mean 2.5 -> 4.0 ms, 90th percentile 3.7 -> 5.3 ms, 36 covers
  decoded on the way (EntryArt asked once per artwork URL). The list makes three or four
  rows more than it starts with on the way down (the same before), and with covers the two
  frames that make the first of them took 28 to 33 ms (none over 16.7 ms before): with any
  extra child in the row (a plain box in place of the cover) they took about 20 ms, and
  with none under 17, so it is the rows' size, not the artwork (no decode, no request, a
  plain picture: the same). Showing History on 499 entries played: 194 ms (205 rows made),
  another entry playing while it shows 11 ms (one row added on top); scrolling it, nothing
  over 16.7 ms. The sheet's tint under the lyrics (lyrics_test.py, the syllable fixture,
  20 s, two runs each in turns): work a frame 1.66 -> 1.97 ms, CPU 10.2 -> 11.5% of a core,
  nothing over 16.7 ms either way: the backdrop is drawn again with every frame the sweep
  draws, as a 32 px texture stretched over the sheet. `artwork.tint_alpha()` on a field's
  258 samples takes 3 to 14 ms, in the thread that makes the field.
- Sections from two `Gtk.SliceListModel`s of one store in a `Gtk.FlattenListModel` (Up
  Next's first try): moving their common bound takes items out of one part and puts them
  into the other, so their rows are built again, and the list's focus item went to the
  last row when a queue first filled the first part. A small Python `Gtk.SectionModel` over
  one slice (`widgets.queue.QueueSections`) gives the sections with no change to the rows.

- The library pages' filters typed into (2026-10-20, headless, `scripts/scroll_test.py
  --type midnight`: a key every 250 ms, past the entry's 150 ms delay, so every key
  refilters; the time each refilter holds the main loop, the filter, the models and the
  list's own work). A `Gtk.GridView` or `Gtk.ListView` destroys the rows of the items a
  change removes and builds rows for the ones it adds, about half a millisecond a tile:
  typing "m" on 3,000 albums built 65 tiles (48 ms), "mi" 117 (55 ms). With the filter
  after the sort (a filter's change no longer places what it puts back) and the change shown
  as the new items before the old, a scroll to the top, the old removed (`ShownModel`, as
  `SongsPage._show()` does), "m" took 21 ms and "mi" 12 ms, rebinding 2 tiles; on 868
  artists "m" 52 → 18 ms; on a 5,000-song playlist (invented, built from build/demo-big)
  "m" 72 → 29 ms, "mi" 146 → 19 ms. The Songs table (40,000 songs) tests only the last
  matches when the text grows (`songs.narrows()`): "mi" 52 → 40 ms, "mid" 54 → 29 ms; its
  first key stays 64 ms (26,801 rows spliced). What is left is a list growing back from a
  few items to many (Backspace from "mid", 5 to 291 albums: 65 ms; 70 to 802 playlist
  songs, 69 to 5,817 of Songs: 134 ms):
  a grid or list keeps rows for about 30 rows of tiles or 200 items, and those had gone
  with the items, so they are built again; it happens once, after the typing has paused.
  No frame of the typing itself went over 20 ms on the grids and Artists.
- Lists growing back, and a filter's Backspace that brings nothing back (#418, 2026-10-20,
  headless, build/demo-big and the 5,000-song playlist, `scroll_test.py --type midnight`,
  three runs of origin/main and the change in turns). GTK keeps the row of an item one
  change removes and adds back, and lays out again every row a change above it moves (six
  label rows inserted above 65 cost a frame 8.8 ms, at the end 3.1 ms). So a list of a few
  items that a Backspace brings many back to is grown in place (`widgets.util.GrowBack`):
  its old items keep their rows, those that will be past the rows the view keeps go at
  once, and the new ones come a few a frame from the top. Backspace "mid" → "mi": Albums
  66-69 → 13-14 ms, Songs 157-158 → 17-24 ms, the playlist 130-131 → 17-19 ms; Artists
  "mi" → "m" 50-54 → 6.7-6.8 ms. The steps a frame are what keeps those frames near 10 ms
  (tiles 12, Songs rows 6, a playlist's 5: twelve Songs rows made frames of 15-20 ms). A
  Backspace that leaves the same matches ("midnight" back to "mid") now filters nothing:
  Albums 7.5-8.8 → 0.3 ms, Songs 22-25 → 0.2-0.3 ms, the playlist 9-11 → 0.3-0.4 ms,
  Artists 2.0-2.7 → 0.3 ms (`filter_bar.SearchText`, the Songs table's kept matches). The
  first key ("m": Songs 60-72 ms, 26,801 rows) and the narrowing ones are as they were.
- The Charts page's first frames (#475, 2026-10-20, headless, build/demo-big at 1100x760,
  the audit's scratch script over `scripts/harness.py`: the main loop's longest stall, a
  4 ms timeout's lateness, and the longest frame, three runs, the second round warm). The
  Top Songs grid made a row for every song up to 90 (30 columns of three) in one frame,
  about a millisecond each with its layout, on top of the first shelves' 24 and 12 tiles.
  With the songs given 9 then 6 a frame and a shelf's row 10 tiles then 6 a frame
  (`PagedRow.give_items()`, both after the frame that draws the first): 50 songs, stall
  50-57 → 14-23 ms, frame 23-35 → 14-23 ms; 100 songs, stall 82-90 → 15-22 ms, frame
  34-49 → 14-23 ms; warm, no frame over 16.7 ms. A cold first visit still has one 22-31 ms
  frame: GTK's first render of the page's kind.
- Up Next's first rows made while a long queue scrolls (#411, 2026-10-20, headless,
  build/demo-big, 500 invented entries, 420x760, 4,000 px/s): not reproduced. The list has
  207 children from the start and makes one more on the way down; the frames that make it
  took 3.1-7.8 ms over 22 runs (also at 360x640, 1100x760, a 20,000 px/s fling, and the
  scroll at once after the queue's paint). Runs that had frames over 16.7 ms had them all
  along the scroll, with as many late compositor frames: other load on the machine.
- The selection mode's key (#574, 2026-11-13, under load: load average 3.3 to 3.7, vmstat
  88-96 % idle; medians of 15 runs; build/demo-big's 40,000 songs as SongEntries): keyed by
  the song's id (`library.selection_key()`, the id read straight from the TrackRecord),
  `Selection.keep()` takes 8.2 ms with one song or 1,000 selected and 11.5 ms with all
  40,000, `ordered()` 7.1, 7.6 and 8.4 ms; keyed by `id(raw)`, as before, 4.7, 4.6 and
  10.0 ms, and 3.1, 3.5 and 5.4 ms. The id through `TrackRecord.get()` cost 10.3 and
  14.2 ms for keep(). Within a frame, so the selection is keyed by id; the mode is not left
  on a reload. On the 5,000-song playlist, `Places` works out its repeats in 5.6 ms, once
  per change of the list (the first key asked after one), and keep() and ordered() of all
  5,000 take 1.9 and 1.6 ms.
- A selection's batch actions over build/demo-big's 40,000 songs (#578, 2026-11-13, under
  load: load average 3.8 to 5.5, 82-96 % idle; medians of 3 to 5 runs, each in a fresh
  Library, the first wrap being the cost): their Tracks (`song_tracks()`, every album's
  groups wrapped) 246-248 ms (300 of them: 2 ms); the queue targets and commands 71 ms (400
  commands of QUEUE_BATCH); `describe()` of each 27 ms; `playlist_track()` of each
  (`tracks_of()`) 99 ms; a drag's ItemRefs 105-123 ms and links 199-204 ms. After: Play Next
  and Play Later make 300 Tracks; `make_song_tracks()` takes 249 ms in all in 31 steps, the
  longest 8.1 ms between two frames, and `tracks_of()`'s longest step is 8.1 ms (10.0 at
  most).

## Memory

The target (`.claude/rules/performance.md`, checked by `scripts/bench.py`): anonymous memory
under 250 MB after every page has been browsed twice on the 3,000-album, 40,000-song library,
and pages opened and closed leaving at most 5 MB of it behind (malloc's bytes in use, beside
it, tell a leak from fragmentation: below). RSS is not the target: it adds what
the libraries and the GL driver map, which the app cannot shrink (a bare `Adw.ApplicationWindow`
is 158 MB on the desktop, 105 of it file-backed; 192 MB headless, 64 of it anonymous).

- Measured headless, 2026-09-29: anonymous memory 212-215 MB after every page browsed twice
  (RSS about 367 MB); the pages step (20 albums, 5 artists, 5 See All opened and popped;
  measured before bench.py also opened 5 of Apple Music's artist pages)
  leaves -1 to +1 MB after a warm-up round, and frees every page. Its first round grows RSS by
  about 6 MB once: the artwork's texture cache filling to its budget.
- What brought it there (2026-09-28/29): each track of library.json kept as a tuple
  (`TrackRecord`), the parsed library 47.5 MB to 32.4; the Songs orders keeping ranks in
  arrays instead of collation keys, 22.3 MB to 3.1; a reload keeping one copy of each
  unchanged dict, not two, 30 MB less after a sync; the texture cache sized by the scale factor
  (8 MB at 1x, not 32), anonymous memory after scrolling all of Albums 156 MB to 137; pages,
  shelves and dialogs freed once dropped (weak connections).
- Measured headless, 2026-10-20 (issue 478, the skill's library with `--playlists 300`):
  233-235 MB after every page browsed twice, before and after the startup change above, 15 MB
  under the target; 0.13.0 had 213-215. With the 1,000 music videos the skill's library has
  since (`--videos 1000 --long-playlist 5000`), 243-247 MB: 3-7 MB under it. A tile (tile.blp, not bound to artwork) costs 42-47 KB:
  a grid page's 129 tiles about 5.5 MB, which Recently Added has made since it shows the whole
  library rather than Apple's hundred (0.13.0 made 8). The bench charged each page's first
  visit with the RSS added from its paint to the next page's: Radio's work after its paint
  (about 10 MB) was counted as Recently Added's, which is why it read 15 MB; measured once a
  page's frames are over, Recently Added's first visit adds 6.6-7.5 MB, All Playlists' 5.6-6.6.
  The rest is the library's (anonymous memory at library ready, 132-137 MB, was about 6 MB
  over 0.13.0's in the issue's measurement: the favourites and dates the model holds since
  library.json version 3). Explained, not reduced: the headroom is small, and the lazy Songs
  model below is the largest saving known.
- The lazy Songs model: done (issue 527), below.
- Video thumbnails by their shorter edge (2026-10-20, issue 383): a video's thumbnail asked
  in a 569x320 box rather than 320x320 is 569x320 where it was 320x180. On the skill's
  library (`--videos 1000`), the demo's 1,000 video thumbnails went from 7.2 KB to 16.1 KB
  each (thumb/ 74.7 MB to 84.0 MB; Apple's JPEGs differ in size, not in shape). Headless at
  1x, three benches each: anonymous memory after every page browsed twice 225-230 MB before,
  226-241 after (medians 228 and 229), since a 1x tile decodes either file to 284x160;
  Music Videos scrolled at 4,000 px/s, 2.5 ms of work a frame before and 2.0 after (longest
  23.5 and 9.1 ms), no slower to decode. At 2x a video tile's texture is 569x320 (728 KB)
  where it was 320x180 (230 KB), within the cache's 32 MB budget at that scale.
- Genres and the tracks' genre and year (2026-10-20, issue 363; library.json version 5).
  build/demo-big's library.json went from 58 to 64 MB (each track's `genre` and `year`).
  Kept in the TrackRecord's two more slots, the genre's strings and the years' ints shared
  across tracks (`SHARED_KEYS`: a year past 256 decoded is an int object of its own, 1.8 MB
  over 57,000 tracks), they cost about 1 MB: anonymous memory at library ready 137 MB before,
  138 after; after every page browsed twice 249 before (runs 249-251), 250 after with Genres
  off, 253 with Genres on and browsed (a grid page more, its covers decoded). Startup's own
  share 231 ms before, 217-246 after (a noisier machine that day: the bare window 797 ms
  before, 810-891 after). Genres' first visit 33-36 ms (19 tiles made); `Library.genres()`
  over 3,000 albums is one walk of their dicts, not on the startup path. Songs scrolled
  40,000 px at 4,000 px/s: 4.4 ms of work a frame before (longest 9.0), 4.6 after with the
  columns off (8.1), 5.2 with Genre and Year shown (13.0), no frame over 16.7 ms. The long
  playlist's table: 4.3 ms a frame with the columns off, 4.5 with them on. A TrackRow makes
  its genre and year inscriptions only the first time it shows them: made in every row,
  Favourite Songs' first visit took 121 ms against 98, made lazily 101-110 (it was 98-144
  before, the one switch near the 100 ms target).

### The lazy Songs store and the slowest switch (2026-10-21, issue 527)

Headless on build/demo-big (the skill's library) at 1100x760 with Genres on, benches of
three runs alternating with origin/main (5052bea), two rounds each: anonymous memory after
every page browsed twice 250-253 MB before (median 252), 226-229 after (median 228);
the longest first switch, Favourite Songs', 105-111 ms before, 77-91 after. What each part
saved, measured page by page with `gc.collect()` and `malloc_trim(0)` after each visit:

- **The Songs store held 40,000 Tracks**: 22.6 MB, about 560 bytes a song (the GObject, its
  Python wrapper and the wrapper's dict, its place in its Group's store and the Songs
  store's), and building it wrapped every album's groups. It is a `SongModel` of
  `SongEntry` objects now (a slotted object of the TrackRecord, where its Track is and its
  search key: about 80 bytes), made from the albums' raw groups; a Track is made when a
  view asks for an item, the album's own (its groups wrapped then). The Songs page sorts
  and filters the entries, its rows a SongModel of them; Search's Your Library and Add
  Songs… match them in Python (`songs_matching()`), the search provider ranks them, and
  each wraps only what it shows. The Songs page's first visit added 56.8 MB before, 37
  after, 199 of the 3,000 albums wrapped for its 205 rows; the songs are built and painted
  in 670 ms where they took 1,020-1,070.
- **A row's parts most rows never show**: the selection mode's check box, the play icon
  over the thumbnail, the explicit badge, the artist's line under the title, about 3 KB a
  widget, made in every TrackRow and SongTitle and kept by the 200 rows a list view keeps.
  Made the first time a row shows one: the Songs table's rows 19.4 MB to 15.4 (24 widgets a
  row to 18), a playlist row's first setup about a third quicker.
- **Favourite Songs' first build bound every row twice**: its rows were made and bound as
  the list's, then the table's breakpoint applied at the first layout and bound them all
  again as the table's (making each list row's artist line on the way). The page assumes the
  table from the content pane's width before its first layout (`detail.expects_table()`)
  and checks the breakpoint at its first paint. Its first switch 103-110 ms to 77-89
  (cProfile: the rows' setup 35 ms to 23, the table's rebind 7 ms gone); an album opens in
  37-38 ms where it took 41.
- Not reduced, and in both builds: about one bench run in six reads 14-18 MB more after
  browsing (origin/main 270 once, this 243-246), with the same pages, rows, wrapped albums
  and garbage collector counts alive and nothing more after `gc.collect()`: memory the
  process holds, not objects. The medians above leave those runs in.
- Songs scrolled 40,000 px at 4,000 px/s: 5.2 ms of work a frame before (longest 9.0), 4.6
  after (12.6), none over 16.7. Typing "the night" into its filter: a refilter's median 32 ms
  before, 23 after, the longest 78 and 48. The pages step (three measured rounds): +3.1 and
  +4.1 MB before, +3.8 and +7.3 after (the second in a run of the 14 MB above).

### What a page visit leaves behind (2026-10-20)

Pages opened and popped over and over, headless on build/demo-big at 1100x760, half a second
each, anonymous memory read after `gc.collect()` and `malloc_trim(0)` after each round, with
glibc's `mallinfo2()` beside it (bytes malloc hands out, and what its arenas hold), and live
GObjects counted by type (an `LD_PRELOAD` shim over `g_object_new*` with a weak reference on
each: GLib's own instance counts need a debug build). Before, on 1.0.1: 145 artist pages +16.6
MB, 78 Charts +8.8 MB, 116 of a search's See All +13.6 MB, every page freed, and malloc's
bytes in use flat (+0.8 MB for the artist pages, nothing for the others) while its arenas grew
by as much as the process did.

- **Most of it was the malloc arenas of the decoding threads.** asyncio's default pool has as
  many threads as the CPUs and four more (20 here), glibc gives each thread that allocates an
  arena of its own (16 of them by the end, holding 30 MB free), and a texture's pixels,
  allocated in a decoding thread and freed on the main thread, go back to that thread's arena,
  where free pages stay scattered among live ones that `malloc_trim` cannot hand back. With
  `MALLOC_ARENA_MAX=1` the same 145 artist pages added 2.0 MB. The decodes now run in a pool
  of their own, `artwork.DECODE_WORKERS` (4) threads: 195 artist pages +6.7 MB, +2.4 MB of it
  after the first 25; 118 Charts +1.6 MB, 156 See All +0.4 MB, after a first round each.
  Capping asyncio's default pool as well (4 threads) changed nothing more; a fixed
  `M_MMAP_THRESHOLD` of 128 KB (`mallopt`, so each texture's pixels are mapped and unmapped
  on their own) lowered the level by 5 to 9 MB but not the slope, so the process's allocator
  is left alone.
- **`Adw.TimedAnimation.new()` leaked each animation and its target** (its new reference is
  annotated `(transfer none)`, so PyGObject takes another): the artist banner's fade, one an
  artist page with a banner, and a shelf's paging glide, one a click. Both are made with the
  constructor now, as the lyrics and the backdrop were (`.claude/rules/gtk-notes.md`).
- **Every `Adw.Breakpoint` stays behind**, 3 an artist page or album page: libadwaita 1.9.0 to
  1.10.0's `Adw.BreakpointBin` takes them but never lets go (a `GPtrArray` without a free
  function since its port to one, b4b4226c), reproduced in C; fixed upstream on main
  (f2e30ed1, 2026-10-20). About 1 KB each, the 1.4 MB that 490 artist pages left in malloc's
  use. Nothing to do here: unreffing them ourselves would free them twice once the fix ships.
- What is left on the artist page, about 14 KB a visit, is that and the arenas' fragmentation;
  Charts and See All level off within a few dozen visits. `scripts/bench.py` opens Charts and
  a search's See All too, three measured rounds after its warm-up (`--rounds`): before, +6.9
  MB of anonymous memory over the three (+4.1, +4.6, +6.9 after each), over the 5 MB target;
  after, +1.6 (+0.3, +0.9, +1.6), every page freed, and startup, the switches, the pages'
  first paints and Albums' scrolling as they were.

### The pages step: two leaks and the fragmentation (2026-11-11, issue 541)

The pages step had read +4 to +7 MB since it opened Charts, Replay and a search's See All
(issue 527's notes: +3.8 and +7.3), against its 5 MB target, every page freed. Measured
headless on build/demo-big at 1100x760 (GTK 4.24.1, libadwaita 1.10.0, PyGObject 3.58.1),
with malloc's bytes in use (`mallinfo2()`: what malloc has handed out and not had back)
beside the anonymous RSS after `gc.collect()` and `malloc_trim(0)`, live Python objects by
type (and by the function and the method a `connect_weak()` closure holds), and live
GObjects by type (an `LD_PRELOAD` shim over `g_object_new*`, as above; none of it is
committed). Six other builds and test runs shared the machine (load average 3 to 12): the
memory readings do not depend on it the way timings do, and the before and after benches
ran under the same load. Before, eight measured rounds of the step: malloc's bytes in use
grew 0.37-0.47 MB every round, without levelling off, so not warm-up: a leak, which each
kind of page run alone placed: an album page about 15 KB a visit, a library artist page,
Apple's artist page and See All 4-6 KB, Charts, Replay and a search's See All nothing.

- **GTK's menu tracker keeps a popover's sections.** Live GMenus grew 3 an album page, 2 a
  library artist page or See All: their Sort By menus' sections. `gtk_menu_tracker_add_items()`
  takes a reference to each section link (`g_menu_model_get_item_link()`, transfer full)
  and drops it only in its branch for sections it merges; a `Gtk.PopoverMenu` merges none,
  so every section given to a popover stays, with its items. Reproduced in C on 4.24.1 (a
  `gtk_popover_menu_new_from_model()` freed, its model freed, the section alive); the same
  code is in 4.20.0 and on GTK's main. The pages' Sort By sections are made once now
  (`widgets.util.shared_section()`): album pages alone, 0.3 MB a round to none that six
  rounds could tell from their noise (about 0.3 MB either way). A menu made as it
  opens (an item's More Options, a context menu, Add to Playlist) still leaves its sections
  behind each time it opens, a few KB.
- **Handlers on libadwaita's leaked breakpoints.** The album page connected six handlers to
  its three `Adw.Breakpoint`s' `apply` and `unapply` (the table, the selection bar's narrow
  layout); the breakpoints are never freed (above), so neither were the closures: 120 a
  round, 1,200 Python objects. It follows its `Adw.BreakpointBin`'s
  `notify::current-breakpoint` instead, whose handler goes with the bin.
- **What is left in use**, 0.11-0.14 MB a round, fits libadwaita's breakpoints themselves
  (inferred, not traced: the shim did not count them): 90 a round (3 an album
  page and an artist page, 2 a library artist page, 1 a See All) at about 1 KB each, as
  measured above. A real leak, upstream's, fixed on its main.
- **The rest is fragmentation.** The anonymous RSS grows more than malloc's bytes in use, most
  of it in the first measured round, while malloc's free space grows with it: the warm-up
  round leaves the heaps at 30 MB free, the first measured round adds 4, and they level off
  by the third (one instrumented run after the fixes, eight rounds: free 30.8 after the
  warm-up, then 35.1, 35.1, 35.3, 35.5, 35.1, 35.7, 36.0, 36.2 MB). Apple's artist pages,
  run alone, make most of it (anonymous +1.1 to +4.7 MB over six rounds, bytes in use
  flat), as issue 477 found.

`scripts/bench.py` checks the target on the anonymous RSS (it compared the RSS, which adds
the files mapped on the way), prints each run's value, and reports malloc's bytes in use
after each round. Five runs each, one bench after the other under the same load, the same
bench.py:

| | before (b1d6bbc) | after |
|---|---|---|
| anonymous, three rounds (median) | +4.8 MB (+2.3, +2.7, +4.8) | +2.8 MB (+1.6, +1.7, +2.8) |
| each run | +4.8, +4.9, +3.0, +1.9, +4.9 | +3.0, +2.8, +2.1, +2.5, +4.1 |
| RSS (median) | +5.6 MB | +3.7 MB |
| malloc's bytes in use after each round | +0.43, +0.82, +1.29 MB | +0.14, +0.33, +0.42 MB |

Eight rounds after: anonymous +1.9, +2.9, +3.8, +3.9, +4.2, +4.8, +4.5, +5.4 (two runs), bytes
in use +0.17 to +0.91 (0.11 a round). The 5 MB is for three rounds; more rounds pass it by
libadwaita's breakpoints and the fragmentation still settling.

## Chrome and the page

- A headless start takes about 10 s until the bridge answers: Chrome about 4 s, the page the
  rest.
- `Gio.InputStream.read_line_async` returns an empty line at the end of the stream, which cannot
  be told from a blank line; the stderr relay reads bytes instead.
- Apple's page is Svelte with hashed class names. Signed out, the sidebar footer holds
  `div.auth-content > button.signin`. Signed in, the account menu names the user in
  `.account-menu .user__name` (seen live on 2026-09-28), which `account_name()` reads first,
  once the page has drawn the menu, some seconds after authorization.
- The web player's own addresses (read from its router, 2026-09-28): a library playlist is
  `https://music.apple.com/library/playlist/<p. id>`, a library album
  `https://music.apple.com/library/albums/<l. id>` (only the owner can open either; a library
  album's catalog page comes from `/v1/me/library/albums/<id>/catalog`); a catalog song
  `https://music.apple.com/<storefront>/song/<id>` redirects to its canonical address.
- Ratings (2026-09-28): `GET /v1/me/ratings/<type>s/<id>` answers 404 for an unrated item, the
  `?ids=` form `{data: []}`; a loved item is `{type: 'ratings', attributes: {value: 1}}`. The
  library's artist ids (`l.art_…`) and loose songs' stand-in albums (`l.alb_…`) are made up by
  the sync, so Apple answers nothing for them: no rating, link or queue entry.
- The DevTools pipe (2026-09-28): asyncio's pipe transports (`connect_read_pipe`,
  `connect_write_pipe`) work on gi.events' loop. Chrome gets its ends through
  `Gio.SubprocessLauncher.take_fd()`, and `launcher.close()` after the spawn is what closes this
  process's copies: without it, Chrome's exit never read as the end of the pipe. That closing
  the pipe also makes Chrome quit, as Puppeteer relies on, is not confirmed on Chrome 154; the
  engine sends `Browser.close` and signals anyway.
- A cancelled `Gio.Subprocess.wait_async()` raised `GLib.Error` (cancelled), not
  `CancelledError`, hence `engine._process_exit()`.
- Chrome rewrites its `/proc/<pid>/cmdline` into one space-joined string, its helpers too (with
  `--type=`), so splitting it on NULs never finds `--user-data-dir=<profile>` as an argument,
  and a prefix match takes `…/chrome-devel` for `…/chrome`. `<profile>/SingletonLock` is a
  symlink to `<hostname>-<pid>` of the browser process holding the profile.
- `setpriv --pdeathsig TERM --` execs Chrome, so the pid and command line the engine sees are
  Chrome's. The parent-death signal follows the thread that spawned it, which is the main
  thread; a grandchild spawned this way exited within a second of its parent's SIGKILL.
- Chrome's own MPRIS player would be `org.mpris.MediaPlayer2.chromium.instance<pid>`; with
  `--disable-features=HardwareMediaKeyHandling`, `busctl --user list | grep -i mpris` shows the
  app's name and nothing for the engine's pid. `MediaSessionService` did not need disabling.
- Chrome without its keyring drops the encrypted cookies (2026-09-29). Chrome 154 encrypts its
  cookies with a key kept in the Secret Service (`org.freedesktop.secrets` on its session bus,
  through the desktop portal's secret provider, which `Local State` records as
  `os_crypt.portal.prev_init_success`). Started inside `scripts/headless.sh`'s private D-Bus
  session, it found the name activatable (the system's gnome-keyring service file) but the
  activation timed out after dbus-daemon's 25 s, so Chrome sat on `about:blank` that long, ran
  on a fallback key, and deleted the cookies it could not decrypt: the .Devel profile came up
  signed out and stayed so with the keyring back (one `geo` cookie left, `prev_init_success`
  flipped to false, `Failed to log in to GCM … wrong_secret` in its log). Hence
  `APPLE_MUSIC_HOST_SESSION_BUS` and the engine's refusal (`no-keyring`) before a start on
  such a profile. On this machine a private `dbus-daemon --session` lists 65 activatable names,
  `org.freedesktop.secrets` among them, and `StartServiceByName` for it hangs: an activatable
  name is no sign of a working keyring, so the check asks for the activation and waits 5 s.
  dbus-daemon does not end a child it activated when the activation fails or the daemon exits.
- Apple's syllable-lyrics TTML, read on 18 catalog songs (2026-10-19, structure only:
  English, Japanese, Korean and Spanish, duets among them). 16 had `itunes:timing="Word"`
  on the root, 2 `"Line"` (plain text in each `<p>`, no spans; a background vocal there is
  only parenthesised text). In a word-timed `<p>` every piece is a `<span begin end>`:
  English words are parted by a whitespace text node, syllables are adjacent spans (a
  stretched "oh-oh" keeps its hyphens in the spans); Japanese has no spaces at all, a span
  a character or two. Background vocals are a `<span ttm:role="x-bg">` holding timed spans,
  the parentheses inside the first and the last; in every case it came last in the `<p>`,
  after a space, so the main and the background vocals joined by a space read exactly as
  the whole `<p>` did. Its times may overlap the main vocals', and the `<p>`'s `end` is
  the later of the two. The
  transliteration's `<text>` (Japanese, Korean) is timed span for span with the line (the
  same begin and end, its own spaces, sometimes inside a span or two between spans), its
  x-bg timed too; the translation's `<text>` is plain, its x-bg an untimed span with the
  parentheses inside, and it may leave out a background the line has. Every `<p>` names
  its singer (`ttm:agent`), some `<div>`s too; the head declares them, `type="person"`,
  `"group"` (`v3`, `v4`: not always `v1000`) or `"other"` (`v2000`, a few lines of one
  song). No word ran outside its line's times or before the previous one. The bridge's
  answer is about 5 times the size it was without the words (14 to 41 KB a song, against
  3 to 9), so 2,000 kept lyrics may take 60 MB.

## The sync

- What Apple's library API offers a sync that wants only the changes (2026-09-30, from the
  documented endpoints and the answers the fixtures mirror): nothing general. The library
  listings (`/v1/me/library/songs`, `albums`, `playlists`, `music-videos`) take `limit`,
  `offset`, `include`, `extend` and `fields`; no `filter` by date, no `sort`, no changes
  feed or cursor. `meta.total` counts the listing, which an addition plus a removal, or an
  edit, leaves as it was, so it cannot stand for "unchanged". A conditional read (`ETag`,
  `If-None-Match`) is out of reach whatever Apple sends: the bridge's `api()` is MusicKit's
  `music()`, which hands back the parsed body alone, and the app never sees a header.
  `/v1/me/library/recently-added` covers additions only. What a listing does carry, per
  library playlist, is `lastModifiedDate` (and, as seen on the real answers, `trackCount`):
  enough to keep a playlist's tracks while both hold, which is what the sync does.
- The requests of a full pass against an invented library shaped like the one in #193 (793
  songs, 34 playlists holding 1,053 tracks, 5 folders), counted through the tests' fake
  engine with 0.3 s a request (scratch script, not in the repo): 59 requests, 36 of them the
  playlists' tracks, whatever changed, before; after, a refresh with nothing changed makes
  23 (no tracks read) and one with one playlist changed 24, the first sync still 59 and a
  listing without dates still 59. With the fake's latency: 8.5 s to 5.8 s and 6.1 s (the
  fake reads the songs' pages and the tracks a few at a time, as the engine does).
  Measured live on the maintainer's library (#192, #194) a full pass was 33 s and a quick
  pass (no tracks, folders, videos or stations) 18.5 s, so the tracks are at most 14.5 s of
  the 33: the songs listing, which nothing above can narrow, is the rest. The log's
  `sync done in N s (engine …, songs …, playlists …)` line now gives each phase's seconds
  (`phase_text()`), for the next live measurement.
- Live, on the maintainer's library (2026-10-02, the .Devel build headless): the first full
  pass with the stamps took 21 s (songs 6.7, playlists 6.6, shelves 4.4); the next, with
  nothing changed, 8 s, all 34 playlists kept (playlists 0.5 s). On a throwaway playlist of
  three songs, each edit moved its `lastModifiedDate` (to the second) within 5 s: a reorder
  (a `PUT` of its tracks in a new order), a removal (`DELETE` of one track) and an addition
  (`POST`); after the reorder the next full pass read that playlist alone and kept the new
  order. The edits went through Apple's library API, as music.apple.com's own do; an edit
  on a phone reaches the same cloud library, but was not tried. A single playlist's answer
  carried no `trackCount`, so the date alone did the work.
- Favourites and dates (#347, 2026-10-20). Live (read only): `extend=inFavorites` on the
  songs listing took no longer (1.33 s plain, 1.21 s extended, 100 songs) and every
  included album carried `inFavorites` and `dateAdded` (a full timestamp, 50 of 50); songs
  carry no `dateAdded`; a song rated 1 reads `inFavorites: true` (src/backend/README.md).
  Offline, on an invented 40,000-song answer (scratch script, not in the repo): grouping
  the songs took 270 to 300 ms either way, reading the favourites (`favourite_ids()`, the
  songs' and their included albums') 52 to 62 ms more, in the sync's thread; the albums'
  JSON grew 0.1 MB (12.0 to 12.1). A tile's heart as an image (a box and an image more a
  tile) cost 129 tiles 7 ms to make and 5 ms to lay out, so a grid's first visit 12 ms
  (All Playlists 88 to 101 ms); as a CSS background of the subtitle line it costs
  nothing measurable (`scripts/bench.py`, headless). Recently Added, the whole library
  now rather than Apple's hundred, opens in 89 ms (129 tiles, as Albums), 17 before.

## MPRIS and GNOME Shell

- GNOME Shell's media section lists a player only while its `CanPlay` is true, and looks the app
  up as `<DesktopEntry>.desktop` in the Shell's own data directories: the development build in
  build/install shows its Identity but no icon; a system install shows the icon.
- `gdbus` spells an object path argument `"objectpath '/…'"`.
