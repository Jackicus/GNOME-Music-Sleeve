# Lab notes

Findings and measurements that explain the code but are not rules. Each was true when it was
written down (September 2026: GTK 4.22, libadwaita 1.9, PyGObject 3.56, Python 3.14, Chrome
154, on the development machine); re-check one before building on it, and date what you add.

The measurements behind the list and model code live in the module docstrings, next to the
code they justify: `pages/songs.py` (GTK's sorters and filters over Python objects, row
rebuilding), `pages/grid.py` (expression sorters against a custom sorter), `library.py`
(`raw_property`'s and `TrackRecord`'s memory, `SongOrder`'s keys, `apply_diff`, `paused_gc`,
`yield_to_frames`), and `widgets/artwork.py` (texture sizes, the cache budget). The
performance pass that produced most of them is written up in `docs/history/build-plan.md`, in
its "Performance pass" section.

## The development machine

- A bare `Adw.ApplicationWindow` paints its first frame about 760 ms after its process starts:
  loading the desktop's icon theme takes about 200 ms of GTK's start, and `present()` waits about
  330 ms for the compositor's first configure. Its RSS is about 158 MB, 105 MB of it
  file-backed (the NVIDIA driver maps about 50 MB). No change to the app removes this floor;
  the startup target of content within a second is measured against it.
- Timings vary by 100 ms or more between runs with the usual desktop load: `bench.py --runs 5`
  and medians.
- The monitor runs at 240 Hz, and an unfocused window may get 60 frames a second, so
  `scroll_test.py` reports the app's own work per frame. The compositor sends no frames to a
  window it does not show, so a hidden bench or scroll-test window stalls.
- A tiling extension resizes windows that are resizable when mapped; the scripts make theirs
  non-resizable (`scripts/harness.py`).
- No input can be synthesised on this Wayland desktop: live runs are driven with
  `gapplication action`, `scripts/am.py` and D-Bus, and `a11y_check.py` dispatches keys through
  GTK's own controllers.

## GTK and libadwaita, measured

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

## Memory

The target (`.claude/rules/performance.md`, checked by `scripts/bench.py`): anonymous memory
under 250 MB after every page has been browsed twice on the 3,000-album, 40,000-song library,
and pages opened and closed leaving at most 5 MB behind. RSS is not the target: it adds what
the libraries and the GL driver map, which the app cannot shrink (a bare `Adw.ApplicationWindow`
is 158 MB on the desktop, 105 of it file-backed; 192 MB headless, 64 of it anonymous).

- Measured headless, 2026-09-29: anonymous memory 212-215 MB after every page browsed twice
  (RSS about 367 MB); the pages step (20 albums, 5 artists, 5 See All opened and popped)
  leaves -1 to +1 MB after a warm-up round, and frees every page. Its first round grows RSS by
  about 6 MB once: the artwork's texture cache filling to its budget.
- What brought it there (2026-09-28/29): each track of library.json kept as a tuple
  (`TrackRecord`), the parsed library 47.5 MB to 32.4; the Songs orders keeping ranks in
  arrays instead of collation keys, 22.3 MB to 3.1; a reload keeping one copy of each
  unchanged dict, not two, 30 MB less after a sync; the texture cache sized by the scale factor
  (8 MB at 1x, not 32), anonymous memory after scrolling all of Albums 156 MB to 137; pages,
  shelves and dialogs freed once dropped (weak connections).
- Not done, about 21 MB more: a lazy Songs model, a `Gio.ListModel` over the track records
  that wraps a `Track` only for the rows GTK asks for, instead of 40,000 Tracks and three
  stores. It changes the type of `library.songs` and moves Search's library song filter into
  Python; with it, the per-Track `search_key` could go too.

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
