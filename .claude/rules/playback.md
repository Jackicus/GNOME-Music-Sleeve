---
paths:
  - "src/player.py"
  - "src/mpris.py"
  - "src/lyrics.py"
  - "src/player_bar.py"
  - "src/player_bar.blp"
  - "src/widgets/transport.py"
  - "src/widgets/now_playing.*"
  - "src/widgets/lyrics.py"
  - "src/widgets/queue.py"
  - "tests/test_player.py"
  - "tests/test_mpris.py"
  - "tests/test_transport.py"
  - "tests/test_queue.py"
  - "tests/test_lyrics.py"
---

# Playback: the Player, MPRIS, the bar and Now Playing

- `Player` (player.py) has no GTK. Its properties change from the engine's `event` signal, from
  one `now_playing()`/`queue()` read when the engine comes up, from the lyrics fetched once
  per catalog song, and from the level a volume set is answered with (MusicKit posts no
  `playbackVolumeDidChange` while it holds no item). Nothing polls MusicKit (sign-in's wait is the one poll). The bar, the sheet
  and MPRIS follow `notify::*`. Every view reads the same cleaned state, because the Player
  does the cleaning once:
  - `resting` is the state with MusicKit's `seeking` transient seen through; `active` and
    `stopped` derive from it, so a seek never flips the play button or the background timer.
    While a play request is `pending` it also holds through the states that are not active
    (MusicKit pauses, seeks and stops the old queue as it loads the new one): the last active
    state since the request, or the one it began in, so the bar and MPRIS show no Play or
    Stopped blip. When the hold ends (the answer, a failure, the engine going) and MusicKit's
    own state differs, `notify::state` is emitted again for the views that read `resting`.
  - A null `nowPlayingItemDidChange` clears the track only after `TRACK_GRACE_MS` (800) with
    no new item (`track_grace_ms`, 0 in synchronous tests): MusicKit sends one between
    queues, right before the next item. Positions reported meanwhile are ignored.
  - After a new item, MusicKit reports the previous item's position (and duration) once more:
    for `TRACK_HOLD` seconds a position further than `SEEK_JUMP` past where the item can be is
    dropped (`_plausible`); the state is still taken. The item's times change with the track
    under one `freeze_notify`, so a `notify::track` handler reads 0 and Apple's length.
  - The position is stamped only when it changes (MusicKit reports whole seconds), and
    `estimated_position()` runs on a second at most. The lyrics view follows the estimate.
  - A state or track event that arrives while `refresh()` awaits its answer outranks the
    answer, which then sets only the modes and the volume; the engine's `bridgeReset` event
    resets the Player as the engine going down does, then reads `now_playing()` again.
- Its commands are thin coroutines over the engine; the UI runs them through
  `app.player_command(coro, on_error=None)`, which toasts an EngineError. `play()` starts a
  `down` engine when signed in (`ensure_engine()`, which also waits for one `starting`) and
  raises `not-signed-in` otherwise; see engine.md for the `starting` state. Play requests
  go out one at a time, the newest winning (a request superseded while it waits, for its
  turn or the engine's start, is dropped), and `pending` is True while one is with the
  engine (the play buttons show a spinner, and
  `resting` holds). `play(shuffle=None)` keeps the mode (a track row); a Play button passes
  False, a Shuffle button True.
  `previous()` restarts the item after `PREVIOUS_RESTART` seconds. A `mediaPlaybackError` is
  emitted as `error(sentence)`, the sentence `playback_error_text(code)` gives MusicKit's
  code; the app toasts it as it is.
- The queue store: `apply_queue()` makes `player.queue` MusicKit's snapshot with one splice of
  what differs (`_splice_queue`: the entries alike at the start and the end, compared by
  `NowPlaying.key`, kept as the same objects and renumbered), so a list over it keeps its
  rows; never replace the store whole (docs/notes.md has the cost). Up Next's edits
  (`remove_from_queue(index, id)`, `clear_up_next()`, `undo_clear()`) change the store at
  once, then the engine; MusicKit's event that follows then changes nothing, and a failure
  reads the queue again (`queue-changed`: only that, but an Undo that cannot be done says so
  in a toast; anything else is raised too). Events are
  applied as they come, never delayed to coalesce them. Edits name an entry after the one
  playing by index and id, only while `queue_editable` (the snapshot's `editable`: not a
  station's queue); while restored they change the session alone and drop its `source`.
  `apply_autoplay()` sets the `autoplay` setting on MusicKit as the engine comes up, after a
  `bridgeReset`, and when the setting changes (main.py); `autoplay` and `can_autoplay` are
  MusicKit's, and `NowPlaying.autoplay` marks an entry autoplay added. The streaming quality
  is the engine's, not the Player's: `Engine.preferred_bitrate` (the `streaming-quality`
  setting, `engine.quality_bitrate()`) set beside each start and after a `bridgeReset` when
  MusicKit has another, `set_bitrate()` when the setting changes (main.py), `Engine.bitrate`
  what MusicKit streams at. `undo_clear()` orders
  the store as the bridge orders MusicKit's queue (`undone_tail()`: autoplay's refill after
  a Clear dropped when Clear took autoplay entries, so one Autoplay batch). tests/test_player.py's
  QueueDiffTest, QueueEditTest and AutoplayTest.
- The last session (`src/session.py`'s `SessionKeeper`, `app.session`, not in demo mode):
  `<cache>/session.json`, written 2 s after a change and every 30 s while playing, at quit
  (the snapshot taken before the engine's stop empties the Player), never with nothing over
  a good file. It keeps the user's queue (`session.user_queue()`): what autoplay added after
  the item is left out, written or read, and MusicKit's autoplay adds again after it once it
  plays (restored by id, autoplay's songs would come back as songs the user queued, and
  autoplay would add more after them). At launch, after the library's load,
  `Player.restore()` shows it as the Player's own state with `restored` True: MusicKit
  holding nothing (its empty refresh() answer, null items, states, times, bridgeReset, the
  engine going down) changes nothing meanwhile (a bridgeReset still sets autoplay, and autoplayEnabledDidChange is taken);
  MusicKit holding an item or a queue of its own ends it. Seek, next, previous, stop,
  shuffle, repeat (and the volume with the engine down) are local and paused; Play and an Up
  Next row hand it to MusicKit as one play request (`restore_session()`: `source`, the
  album, playlist or station the queue still is, else its songs' ids; `shuffle=False`, the
  position as `start_time`); play_next/play_later queue it paused first (`paused`). The
  request is what the session shows as it goes out (`_restore_request`, after the engine's
  start, its own or the autostart's), so a step or an Up Next row taken while it waits is
  what plays; another restore_session() meanwhile sends nothing (a Play makes a paused one
  play) and returns
  once it is answered (`_restoring`), so play_next's item goes after it. The request takes
  the session (`_take_restored`, which makes a refresh() answer under way stale) and gives
  it back on a failure, unless MusicKit refused it (`api` with a code:
  dropped, `session-dropped` deletes the file, `error` toasts why). MusicKit refuses a whole
  queue by ids when one song cannot be found (`NOT_FOUND`): `_without_missing()` sends it
  once more without the songs MusicKit's message names and those `engine.songs_found()`
  (one read by id of the library's and the catalog's) does not answer, the item and its
  position kept; only the item itself gone (or none found missing, or a second refusal)
  drops it. A refresh() answer while
  a play request is pending sets only the modes. Discord publishes nothing while restored.
  tests/test_session.py and test_player.py's RestoreTest; `scripts/screenshot.py --demo
  --restored` shows it.
- A preview (a suggested song's 30-second clip, `Player.start_preview`) plays in the
  page's own audio element, not through MusicKit, which pauses for it: the state, track,
  times and queue stay MusicKit's, so the bar, the sheet and MPRIS show the queue paused,
  as it is, and Play there resumes it and stops the clip (the bridge stops a preview on
  `play()`, every `control()` and MusicKit playing). Only `player.preview` (the song's
  catalog id, from `previewDidChange`) says a clip plays; it is cleared with the rest when
  the engine goes down or the page is reloaded.
- A live radio station (`player.live`, the Track's `isLive`: told by its item, never by its
  times, its duration being the stream's window) allows only Stop: `can_seek`, `can_pause`,
  `can_go_next`, `can_go_previous`, `can_shuffle` and `can_repeat` are False (otherwise
  MusicKit's capabilities, taken from an item event, a state with an item loaded and
  `capabilitiesChanged`; Previous also while the item can be sought: it restarts it).
  seek(), next(), previous(), set_shuffle() and set_repeat() do nothing (MPRIS's Shuffle
  and LoopStatus too; `ModeControl`'s toggles are insensitive),
  toggle() and pause() stop it, and `_keep_station()` then shows the station as a session
  restored, stopped, so Play tunes in again. The bar, the sheet and the full screen show
  `SeekControl`'s LIVE badge (the scale's sibling in a `Gtk.Stack`, so the row keeps its
  height) and `play_button_look()`'s Stop, the play button described "Live Radio"
  (`PlayButton`: the badge is a label no focus reaches) and the item announced "Now
  playing live: …"; the Lyrics tab says lyrics are not available for live radio; app.next
  and app.previous follow `can_go_*`, and
  their keys stay the window's while an item plays (they do nothing rather than move the
  focus). MPRIS: no `mpris:length`, Position 0, no Seeked, Pause, PlayPause and Stop stop it;
  Discord: no timestamps; no lyrics are asked. tests/test_player.py's LiveTest and
  ModesTest, test_mpris's
  live sequence; `scripts/screenshot.py --demo --playing --live` shows it.
- `player.stopped` means no item, or `none`, `stopped`, `ended` or `completed` (paused is not).
  MusicKit passes through `ended` and `stopped` between items, so anything acting on "stopped"
  waits a moment (background playback waits 10 s before quitting).
- The bar and the sheet share their transport pieces (`widgets/transport.py`: `PlayButton`,
  `TrackTitles`, `SeekControl` over a GTK-free `SeekGuard`, `ModeControl`, `VolumeControl`
  over a `Coalescer`, `HeartControl`, `RemoteCover`): change them there, and test their
  decisions in tests/test_transport.py with stand-in buttons. The bar announces each new
  item through the window, once per item, and with nothing playing hides its seek slider
  and heart. Its Lyrics and Up Next toggles are `win.show-lyrics` and `win.show-queue`,
  `widgets.now_playing.TabActions` over the sheet's tab seam (`shown-tab`, `show_tab()`):
  stateful (pressed while the tab is in sight), enabled by `can_show_tab()`; the bar hides
  them below 640sp (`narrow`) and its whole right-hand box below 600sp (`compact`), where
  it is a phone's bar: `transport_box` moved after `item_box` (the item, then Play and
  Next), no Previous, and the seek row only for a live station's LIVE badge. The bar
  is a drop target (`Gtk.DropTarget` of `library.ItemRefs`, deciding from `dnd.current()`):
  what `actions.queue_targets()` can queue all of goes through `item_actions.queue_drop()`,
  Play Later, or Play Next when `dnd.shift_held()`; the sheet is no target (open, it covers
  every drag source). The sheet's layout follows three of its own properties, set by window.blp's
  breakpoints: `wide` (900sp and up: the item beside the tabs), `compact` (600sp and under:
  a smaller cover) and `short` (a window too low for the cover over the titles: a 96 px
  cover beside them). Only the last matching breakpoint applies, so each width band has a
  short variant repeating its setters; check every size with
  `scripts/screenshot.py --demo --now-playing lyrics|queue --size WxH` and the log for
  libadwaita's "exceeds … height" warning. Up Next is a `Gtk.SliceListModel` of the queue
  from the entry playing on, its size set again with each offset (`queue.slice_size()`,
  gtk-notes.md; tests/test_queue.py), in sections by `queue.QueueSections` (the entry
  playing; Playing Next; Autoplay from the first entry autoplay added: `section_bounds()`),
  a row being queue index `queue_index_at(position)` and showing its entry's cover, which
  `queue.EntryArt` finds once per artwork URL (on disk in a thread, else a thumbnail
  fetched, never in the demo), only for the rows bound and at most every `ART_DELAY_MS`,
  and again once the cache's generation moves (Clear Cache, sign-out): bind is a
  dictionary lookup. Remove from Up Next is in an entry's menu
  (`context_queue_entry`) and on Delete (the focus then on the row in its place); History
  (a toggle above the list, off when the tab is left) shows the entries before the one
  playing, most recent first, in a second list over a `queue.HistoryModel` brought up to
  date (one splice) only while it shows; Autoplay and Clear (an Undo toast,
  `app.undo-clear-up-next`) sit above the list. The sheet's background is the item's
  artwork as a tint (`widgets.backdrop.ArtworkBackdrop`, `tint`: the full-screen player's
  field drawn faintly over the sheet's colour, as deep as `artwork.tint_alpha()` lets its
  text read at AA in the scheme shown, none in high contrast), made only while the sheet is
  in sight; the sheet's dimmed labels are at 70% (style.css). The lyrics list is the user's while they scroll it
  (wheel, touchpad, touch: it shows no scrollbar) or have the focus on a line. Its top and
  bottom edges fade out through an alpha mask in `LyricsView.do_snapshot` (`edge_fades()`:
  as far as the text goes on past each edge; none in high contrast), never a gradient laid
  over the text in a background colour, which the full-screen backdrop would show. A lyrics
  row's side in a duet (its labels' alignment, its box's horizontal margins, its break's
  dots) is set only through `widgets.lyrics.set_side()`, at bind and when the list's width
  changes, from the line's `side` (`lyrics.side()`). An instrumental break
  (`lyrics.instrumental_breaks()`, Apple's 9 s rule) belongs to the line after it
  (`LyricLine.instrumental`), its dots in that line's row, never an item of its own (a list
  item that cannot take the focus stops GTK's arrow keys). What the synced view shows is
  `Lyrics.moment_at()` (the row current, in its break or not, and its step: the dots lit, or
  a word-timed line's pieces begun), and it steps on one GLib timeout armed for
  `Lyrics.next_change()`, never a per-frame tick: a new kind of step goes into those two. The
  one per-frame tick is a sweep's drawing: while a piece of a shown part of the current
  word-timed line is being sung (the tab shown, the music playing, animations on), the list's
  tick callback redraws that row's `LyricLabel`s (at most about 60 times a second) and
  nothing else, and stops itself in the gaps. The labels light the pieces sung
  (`lyrics.sung()`) through an alpha mask in their own snapshot (`piece_segments()`, by
  Pango's UTF-8 byte indices: `lyrics.byte_spans()`), never through Pango attributes, which
  would lay the row and the list out at every word. The lyrics hold rather than go back by
  less than `HOLD_BACK` (a pause's whole second).
- The full-screen player (`widgets/fullscreen_player.py`, shown by `fullscreen.FullscreenHost`,
  `win.fullscreen-player`, F11) shares the transport pieces too, and borrows the sheet's one
  LyricsView: `lend_lyrics()`/`return_lyrics()` move it between the sheet's `lyrics_slot`
  and the player's, the sheet covered meanwhile (`set_covered`), so `set_active` is called
  by whichever holds it and never by the other; a second LyricsView would follow the Player
  for good and paint twice. The player does nothing while hidden (no idle timeout, no fetch,
  no field: `_show_item()` catches up as it shows) and leaves only when the Player's item
  goes (after its grace), never from one song to the next; tests/test_fullscreen.py.
  Its layout is `fullscreen.layout_for()` (a pure function, applied as the view is
  allocated), its idle `fullscreen.should_hide()`; its background an ArtworkBackdrop
  (widgets/backdrop.py, the sheet's too) over `artwork.field_for()` (the last few covers'
  fields, shared with the sheet) and `scrim_alpha()`. Check it with `scripts/screenshot.py --demo
  --fullscreen-player [lyrics|localized|syllable|none] --size WxH` (and `--idle`).
- MPRIS: the app owns `org.mpris.MediaPlayer2.<app id>`; Chrome's own player is disabled by its
  launch flags. The object is registered with
  `Gio.DBusConnection.register_object_with_closures2` (the older call is deprecated since GLib
  2.84, the declared minimum); GLib answers Get, GetAll, Set and introspection from the node
  info, and each property has a getter of its own (`PLAYER_GETTERS`), so Get builds only what
  is asked. `bus_acquired` comes before `name_acquired`; `name_lost` with no connection means
  no bus at all, and the app runs on.
- PropertiesChanged is emitted by hand, `(sa{sv}as)`, with only the keys that differ from what
  was last sent. Position is never in it (the spec's annotation): clients read it, and
  `Player.estimated_position()` runs it on between events. Seeked follows the app's own seeks
  and any position jump from where a client would extrapolate it (while the published status
  is Playing, so a stall behind that status ends with a Seeked). `mpris:trackid` carries the
  queue index (`/track/<index>/<id>`): the same song twice in a row is two tracks. Stop
  pauses and seeks to 0, keeping the item (Stopped until the music plays again; CanPlay stays
  true, so the Shell keeps the player). SetPosition drops a stale trackid or a position outside
  the track; Seek clamps to 0 and goes to the next item past the end; PlayPause with nothing to
  play answers NotSupported. The artwork file is found through `remote.fetch_remote`, never a
  stat on the main loop; a new item's own properties (`ITEM_PROPERTIES`: Metadata and the
  Can*s) wait for it and go out together, for `ART_GRACE_MS` (200) at most (`art_grace_ms`,
  0: no wait), so a client sees one Metadata change per item. Metadata without `mpris:artUrl`
  followed by the same Metadata with it made GNOME Shell's card blink through its no-cover
  icon at every track change; the wait ends the moment the file is there, an item passed
  through by a second skip never reaches the bus, and a download slower than the grace
  publishes the item and follows with its artwork.
- GNOME Shell lists a player while `CanPlay` is true (so "Not Playing" shows nothing) and finds
  its icon through `<DesktopEntry>.desktop` in the Shell's data directories: a system install
  shows the icon, the dev build in build/install shows only the Identity.
- Tests drive the Player and Mpris with stand-in apps and engines (tests/test_player.py,
  tests/test_mpris.py), with no GTK. `patched_clocks()` (test_player.py) puts `time.monotonic`
  under the test's control for both; no `asyncio.sleep(> 0)` inside it. The `FakeEngine` has
  per-command gates (`engine.gate(name)`) to hold an answer back. test_mpris.py's
  `SEQUENCES` table replays the event sequences seen live through a Player and the service
  together (`play` and `answer` steps put a pending play request around them; each step lets
  the loop run, so a new item's artwork lands inside its grace and its properties go out
  once): add a sequence there when a new one is recorded. One test runs the service on a dbus-daemon of
  its own and talks to it through GDBus (never `Gio.TestDBus`, which is for a process of its
  own). Checks on the session bus are in the `live-engine-check` skill.
