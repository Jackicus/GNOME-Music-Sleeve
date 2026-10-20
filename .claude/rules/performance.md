---
paths:
  - "src/pages/**"
  - "src/widgets/**"
  - "src/library.py"
  - "src/main.py"
  - "src/window.py"
  - "scripts/bench.py"
  - "scripts/scroll_test.py"
  - "scripts/lyrics_test.py"
---

# Performance: lists, artwork, startup

Targets, on a 3,000-album, 40,000-song invented library: content painted within 250 ms of
a bare `Adw.ApplicationWindow`'s first frame (the app's own share of the start, about a
second from launch here: the bare window alone takes 0.8 s), page switches under 100 ms, no
dropped frames while scrolling Albums and Songs, anonymous memory under 250 MB after every
page has been browsed twice, and pages opened and closed (20 albums, 5 artists, 5 artist
pages, 5 See All, 2 Charts, 2 Replay and 2 of a search's See All a round, three rounds
after a warm-up round) leaving at most 5 MB behind.
bench.py checks all but scrolling. The numbers behind these rules are in docs/notes.md.

## Measure

- Before and after a change on the startup path, a page's first build or a list's bind:
  `scripts/headless.sh scripts/bench.py` (build/demo-big by default; medians of several runs)
  and, for lists, `APPLE_MUSIC_CACHE=build/demo-big scripts/headless.sh scripts/scroll_test.py
  --page albums` (or `--page songs --distance 40000`, with `--setting
  "song-columns=['genre','year']"` for its optional columns, `--page music-videos`, `--open
  playlist:l.pllong` for the long playlist, or `--sidebar`; a list that fits the window is
  reported so). The headless display's
  virtual monitor shows the window (a hidden one gets no frames); compare only headless runs.
  `python3 -X importtime` for imports. The lyrics view's stepping and sweep:
  `scripts/headless.sh scripts/lyrics_test.py` (frames, work a frame, CPU, the lyrics list's
  allocations while the syllable fixture plays). Put the numbers in the commit message.
- `Application.mark(name)` notes a startup moment (logged with `--debug`); the grid and Songs
  pages call `pages.mark_bound(self)` at their first bind.

## Recycled rows and tiles

- A `Gtk.GridView`, `ListView` or `ColumnView` binds each item many times while it scrolls, so
  bind must be cheap: text in `Gtk.Inscription` (a wrapping `Gtk.Label` is measured again at
  every rebind; SongTitle's, QueueRow's and TrackLink's single-line labels are deliberate), no
  `_()` in bind (look strings up once; the model's `count-label` is made once), no costly
  children in widgets made by the hundred (a tile makes an `Adw.Avatar` only for an artist,
  its play symbol only for a music video; its tooltip is worked out on `query-tooltip`),
  and fixed column widths (`fixed-width` plus `expand`) in tables.
- Nothing in a recycled row may change size when its artwork arrives or goes: a `Gtk.Picture`
  whose paintable changes intrinsic size relayouts the whole list, and so does a child shown or
  hidden. Show `artwork.empty(size)` for no texture and fade the placeholder icon instead.
- Artwork goes through `widgets.artwork.get_default()`: `get(path, size)` answers from the
  cache, `request(path, callback, size)` decodes in a thread, `cancel(token)` when the widget is
  recycled or unmapped. `size` is the edge drawn in device pixels. A widget never calls it
  itself: it owns an `artwork.ArtworkSlot` (`set_paths()` in bind, `map()`/`unmap()` from its
  `do_map`/`do_unmap`, `follow_scale(self)`; `attach()` only for a widget class that is not
  ours: signal handlers cost 0.6 KB a widget), which asks in an idle after the frame, lets go on
  unmap, falls through its paths, shows another size of one meanwhile, and always hands the
  widget a texture or `empty()`. Tile, Cover (and so SongTitle, TrackRow, HeroTile, QueueRow),
  CategoryTile, the artist portrait and the artist banner use one; a new artwork widget
  does too. A thumbnail is as big as a tile draws it at 2x by its shorter edge: a video's
  (a music video's, a More To See link's) is asked and scaled in its 16:9 box,
  `normalize.thumb_box()`, and named apart (`thumb_name()`), not in the square one.
- A model change that removes the items a `Gtk.ListView` or `ColumnView` shows destroys those
  rows and builds new ones. To replace a list's contents, insert the new items first,
  `scroll_to(0)`, then remove the old ones (`SongsPage._show()`): the rows are only rebound.
  A sync's change to what a list shows goes through `library.apply_diff` instead (the fewest
  splices), so the list keeps its scroll position. A filter's change over GTK's models goes
  through `widgets.filter_bar.ShownModel`, the list's own model, under `replacing(scroll)`:
  it shows the change the same way (the grids, Artists, a playlist's songs).
- That recycles only the rows the insertion pushes past those the view keeps
  (`widgets.util.rows_kept()`). A list of a few items growing back to many (a Backspace)
  goes through `widgets.util.GrowBack` instead (ShownModel, given its view, and the Songs
  table): the items shown keep their rows (a change that removes an item and puts it back
  keeps its row), the new ones go in a few a frame from the top, and the old ones that will
  be past the rows kept go at once (a row a change above moves is laid out again). A list or
  shelf given many items at once grows the same way: a shelf's row gets `FIRST_TILES` (a
  chart's songs `FIRST_SONGS`) and more a frame after the one that draws them
  (`PagedRow.give_items()`), as Artists' first build does.
- A `Gtk.GridView` keeps about 30 rows of `max-columns` tiles alive however few it shows: set
  `max-columns` to what fits (`grid.columns_for()`; `COLUMN_WIDTH` and `VIDEO_COLUMN_WIDTH`
  are a tile, `tile.ART_SIZE` or a video grid's `tile.GRID_VIDEO_SIZE`, plus Adwaita's
  padding, so change them together). It makes them all in the frame its model fills in, so a
  grid page shows the rows that fit at first (`grid.first_tiles()`, from the window's
  `content_height()`) and lets the rest in `GROW_TILES` a frame after its first paint
  (`GridPage._grow`); a filter (whose rows are recycled: `ShownModel.replacing()`) and a
  focus by position call `_show_all()` first.

## Sorting and filtering

- Sort with `Gtk.StringSorter`/`Gtk.NumericSorter` (in a `Gtk.MultiSorter`) over
  `Gtk.PropertyExpression`s of the model's properties: they read each item once and sort in C.
- A `Gtk.ColumnViewSorter` compares pairs and evaluates both items' expressions at every
  comparison, which is seconds on 30,000 songs. For Songs, read the primary column from the view
  sorter's `changed`, then sort and filter in Python and splice: `library.SongOrder` computes
  each column's keys once, in frame-sized steps (`await prepare(column)`), and `tracks()` then
  only sorts (library.md).
- Filter after sorting (`Gtk.FilterListModel` over the `Gtk.SortListModel`): a filter's
  change then only removes and puts back, and never sorts again. The Songs table tests only
  the last matches when the text grows (`songs.narrows()`) and keeps the matches of the texts
  it filtered by lately (`KEPT_SEARCHES`: a Backspace tests nothing); GTK's pages set their
  text through `filter_bar.SearchText`, which leaves the models alone when a shorter text is
  known to match no more than the longer did. Measure a filter with `scroll_test.py --type
  TEXT` (docs/notes.md).

## Startup and the main loop

- Everything in `do_startup`, `do_activate` and a restored page's construction is on the
  startup path: keep it small. Import modules at the top of main.py's import chain (before the
  library's parse starts) or lazily; page modules only in their factories.
- A page that builds many widgets builds what shows first and the rest a frame apart
  (`ShelfColumn`'s `FIRST_SHELVES`, then one shelf per `await widgets.util.next_frame(widget)`).
  Chunked main-thread work yields with `await yield_to_frames()`.
- Garbage collection around big loads: see `library.md` (`paused_gc`).
