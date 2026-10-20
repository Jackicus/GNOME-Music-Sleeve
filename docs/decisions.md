# Decisions

The design decisions this app rests on, with the reasons and what was given up. When one
changes, change it here, with the date. The plan they came from is in
`docs/history/build-plan.md`.

## Product

- **Distribution: native first** (2026-09-27). Releases are `meson install` and an AUR package
  (`build-aux/aur/PKGBUILD`). The Flatpak manifest is for development only: from the sandbox,
  the app runs the host's Chrome through `flatpak-spawn --host`. Flathub is out of scope: it
  would refuse an app that depends on the host's Chrome. (It was also out of scope while the
  app carried Apple's name; that half no longer applies, but the Chrome dependency still does.)
- **A profile of its own** (2026-09-27). The app's Chrome uses its own profile
  (`$XDG_DATA_HOME/apple-music/chrome`, the development build `chrome-devel`), so it never
  fights another Chrome, such as the GNOME Shell extension's, over a profile lock. The cost is
  one sign-in per profile, and two Chromes when both run.
- **The development build's own paths** (2026-09-28). The .Devel build has its own cache
  (`$XDG_CACHE_HOME/apple-music-devel`) beside its own Chrome profile, chosen in
  `backend/config.py` from the build profile, so a development sync, Clear Cache or Sign Out
  never rewrites or deletes the release build's library. The settings are shared but for the
  account's: `signed-in`, `account-name`, `last-sync`, `last-page` and `expanded-folders` have
  `-devel` twins for the .Devel build (`Application.account_key()`), whose profile holds a
  sign-in of its own; a development build starts signed out, with an empty library.
- **The player at the bottom** (2026-09-27). A full-width bar at the bottom of the window, as
  in GNOME Music, with Now Playing as an `AdwBottomSheet` that slides up over the content and
  holds Lyrics and Up Next. The web player puts its player at the top; the bottom keeps the
  header bar for titles and back buttons, which is what GNOME users expect. Shown only while
  something plays (2026-10-01), as GNOME Music's is: with nothing playing the window ends at
  the content rather than carrying a dead "Not Playing" bar, and the bar slides in with the
  first item (`src/window.py` reveals it from the Player's track, after the Player's grace
  between queues, so a change of queue shows no blink). Ctrl+Shift+N still opens Now
  Playing; Ctrl+3 with no bar leaves the focus and says "Not Playing" to a screen reader.
- **Playlist folders in the sidebar** (2026-09-27, indented 2026-10-19). Folders are sidebar
  items with a folder icon and a disclosure arrow; activating one shows or hides its playlists
  and opens the folder's page (in the narrow layout's page mode it only opens the page). A
  folder's contents follow it, indented 28px a level as GNOME Builder's project tree indents
  (a nested item's icon under its folder's title), up to three levels; deeper items keep the
  third level's indent. `AdwSidebar` has no indentation of its own, so the controller gives
  each nested row a `depth-1` to `depth-3` class as it names the rows (and only when the rows
  match the items one to one; else the sidebar stays flat), and `src/style.css` moves the
  row's content in, mirrored for right-to-left, the selection still the row's full width. The
  page mode's boxed lists are indented too: there a folder has no arrow and its contents
  would otherwise look like top-level playlists. The subtitle that used to name a nested
  item's folder is gone (one height for every row, as in Builder); the tooltip keeps the
  whole name, and screen readers hear each row's level.
- **Folders made and playlists moved, at once** (2026-10-20). New Folder… (the main menu, a
  folder's and All Playlists' menus, a folder button beside each **+**) and Move to Folder (a
  playlist's menus, as Add to Playlist nests the folders, ending in New Folder…, a folder
  holding it) are the keyboard's and the narrow layout's way; dragging a playlist's sidebar
  row or tile onto a sidebar folder is the pointer's. A move is shown before Apple answers:
  `Library.hold()` remakes the tree from library.json's folders plus the changes held, so the
  sidebar splices only what moved, keeps its open folders and selection, and gives the moved
  row its focus back; Apple's refusal releases the change (the playlist is back where the file
  has it) and is reported; the toast offers Undo, a move back. Apple lists a change seconds
  later, so the change stays held through any sync until library.json shows it, or for
  `PENDING_HOLD` (two minutes), after which Apple's listing wins. A new folder is shown once
  Apple answers with its id (no id, nothing to show), its page selected as a new playlist's is.
  The sidebar highlights the folder a drop goes into and draws no insertion line, since Apple
  orders each folder by title: where in it a drop lands means nothing. Moving to the top level
  and a folder into another are written and tested but switched off (`api.MOVE_TO_TOP_LEVEL`,
  `api.MOVE_FOLDERS`) until Apple has been seen to take them: the app offers no move Apple may
  refuse, and the user guide's Known limitations says so. Drags are the app's own: one type,
  `library.ItemRefs`, and drop targets decide from the drag in progress
  (`widgets.dnd.current()`), so drags from other applications are not taken.
- **Sidebar sections: titles and dividers** (2026-10-19). Library and Playlists keep their
  titles (Playlists especially, which the library's folders and playlists fill), and a thin
  divider above each, as Files separates its sidebar's groups. libadwaita draws that divider
  only above an untitled section, so `src/style.css` draws it on a titled section's header
  (`.navigation-sidebar > .header:not(.first)`, a background line), in the separator's colour,
  inset and spacing; no Python touches AdwSidebar's widgets, and nothing in the rule depends
  on what libadwaita puts inside the header (1.9 and 1.10 differ there). The first section
  (Search, Home, New, Radio) stays untitled with no divider; the narrow layout's page mode,
  whose sections are boxed lists, has none.
- **Playlists in Apple Music's order** (2026-10-03). Apple's API lists a folder's contents in
  an order of its own; its web player sorts them, and so does the app, everywhere playlists
  are listed (the sidebar, a folder's page, All Playlists, Add to Playlist): Favourite Songs,
  then folders, then playlists, each by title as `localeCompare` sorts lower-cased text, so
  "10." comes before "2." there and here. No natural number order, which would differ from
  Apple's. All Playlists offers no other order.
- **Keys as GNOME has them** (2026-09-28). Space presses a focused button, switch, check box or
  list row, as everywhere in GTK; it plays or pauses only on a tile, a list item, the seek
  slider or nothing. Now Playing is Ctrl+Shift+N, leaving Ctrl+N to the HIG's "New". Bare keys
  and editing chords are never application accelerators (`src/keyboard.py` decides them).
- **Lyrics and Up Next in the bar** (2026-10-20). Two toggle buttons at the bar's right, as
  Apple's players have them, open Now Playing on that tab and close it when it shows that
  tab; pressed while their tab is in sight, Lyrics off for a song without lyrics. Their keys
  are Ctrl+Shift+L and Ctrl+Shift+U (L for Lyrics, U for Up Next), the window's own
  (`shortcuts.NOW_PLAYING_TABS`), not accelerators: Ctrl+Shift+U is GTK's Unicode entry in a
  text field, which an accelerator would take from the Search entry. Below 640sp the bar
  drops them first (the title keeps its room), and below 600sp the whole right-hand box;
  the sheet the bar opens has the tabs.
- **Music videos play as audio** (2026-09-28). The engine is headless, so a video tile plays
  the video's sound, as the context menu's Play does, rather than refusing or opening a
  browser. Easy to change to a toast with Open in Browser.
- **MPRIS Stop pauses** (2026-09-28). Stop pauses and seeks to the start, keeping the item, as
  the spec allows; the Shell then keeps showing the player, where ending the session would
  drop it.
- **Favourite is a heart** (2026-09-28), everywhere: the sidebar's Favourite Songs and its
  page as well as the player bar and Now Playing, with the bundled heart icons.
- **A refresh on a schedule** (2026-09-28). The library is synced when the last sync is older
  than the chosen interval, or when library.json is missing, unreadable or of an older
  version, checked by a timer, when the engine comes up and when the library has been read;
  only with the engine up and signed in, so a timer never starts Chrome.
- **Sign-out revokes the session** (2026-09-28). Signing out calls MusicKit's `unauthorize()`
  before anything is deleted, so the token stops working at Apple's end too; when the engine
  is down, it starts Chrome headless for up to 20 seconds to do so, then wipes whatever
  happens. The alternative, skipping the revocation when the engine is down, is quicker but
  leaves the token valid until Apple expires it. Every job that writes the cache is stopped
  first (the cache's generation), so nothing is written after the wipe.
- **Discord presence, off by default** (2026-09-30). A switch in Preferences sends the playing
  track to the Discord desktop app as rich presence, over its local IPC socket, with no
  library: the protocol is a handshake and one command, and a dependency would be the app's
  only one outside GNOME's stack. Off until the user turns it on, since it publishes what they
  listen to. The application id is the project's own Discord application, public by nature
  (rich presence needs no token). The activity names itself "Apple Music", so the card reads
  "Listening to Apple Music" as it reads "Listening to Spotify": it names the service being
  listened to, not this app, which keeps to the rule on Apple's marks. The artist is the
  status line under the user's name, and the album is the cover's caption, which Discord
  prints as the card's third line. The cover is Apple's own public URL, which Discord fetches;
  nothing is uploaded anywhere.
- **A click plays a song** (2026-10-01). A track in an album's or a playlist's list, the Songs
  table and Search's songs plays on a single click (`single-click-activate`), as GNOME Music
  plays one: the first click of a double click selected nothing anyone used, and a row that
  wants a second click is a file manager's. Enter plays the focused row as before; the
  context menu, a drag to a sidebar playlist and a row's artist and album links
  (`src/widgets/track_links.py`) claim their presses before the row sees them, so they are
  unchanged. The Songs table keeps no selection any more (a `Gtk.NoSelection`, as the lists
  have): GTK selects the hovered row of a single-click list, which would have followed the
  pointer around. The track playing is marked in every row that shows it, as Up Next marks
  its entry (#241).
- **One look for loading, status pages, links and grids** (2026-10-01). A page that waits
  shows a bare 32 px `AdwSpinner`, the album and artist pages' sections under their hero too,
  in place of three looks (that spinner, a hand-made "Loading…", a status page with a spinner
  paintable). A state with words is an `AdwStatusPage`, or a box shaped as a compact one
  where a list row cannot hold one (the album page's), with one `pill suggested-action`
  button and plain `pill` ones beside it. A link in text (an album's artist, a row's artist
  and album) is the text's own colour, underlined under the pointer, never a `link` button's
  blue. A grid's first column sits on the page's 24 px margin, the tiles at the start of
  cells that grow with the page, as Radio's flow box has them, where the grids' tiles were
  centred in theirs and drifted (28 px wide, 13 at 360); under 400sp the margins shrink to
  the 14 px that still fit two tiles, Radio's the same, the grid never centred (a centred
  scrollable has GTK measure its width for its height, which warns) (#243).
- **A tile's title and subtitle keep to one line each; music videos are 16:9** (2026-10-20),
  as Apple Music's grids have them. A title or subtitle too long for its tile ends in an
  ellipsis, so every tile in a row is as tall as the next and the subtitles line up; the
  whole of both is in the tooltip (only when a line is cut short, worked out as the pointer
  rests, so binding a tile costs nothing for it) and in the tile's accessible name. Two
  lines of title, as before, showed more of a long one, but a row's subtitles then sat at
  two heights. A music video's tile is a 284×160 frame, as tall as a cover, so a shelf that
  mixes videos with albums keeps one height and its titles one line. A grid of them (Music
  Videos, a videos shelf's See All) has smaller 240×135 frames, so three columns fit beside
  the sidebar at the default window width (two of 284 left about 100 px empty after each),
  two at middle widths and one in a 360 px window. Its
  play symbol shows under the pointer and with the keyboard focus, not always, as on Apple
  Music's tiles (#354).
- **Show Translations and Show Pronunciations stay independent** (2026-10-19), as Apple's
  web player has them: two separate menu items, and with both on a line shows its
  pronunciation, then its translation. Checked against Apple's lyrics component (#309).
- **Background vocals on a line of their own, parentheses kept** (2026-10-19). A line's
  background vocals (echoes, ad-libs) show under its main vocals and their pronunciation
  and translation, smaller and fainter, with their own pronunciation and translation under
  them, smaller still: Apple's own lyrics component stacks them so, and the unsynced text
  does the same. The text is Apple's as it is, parentheses and all: Apple's view shows them
  too (it strips them only to compare the background with its translation), they mark the
  line as an echo where size and shade alone are faint (a dimmed line, a screen reader's
  reading of the row), and the background's pronunciation and translation carry their own,
  which would read oddly under a background without. Folding the background into its line
  as one string, as before, lost the difference between the singer and the echo (#306).
- **A duet's singers on their own sides, a group's lines in the middle** (2026-10-19). As
  Apple's lyrics component does, a song is a duet when some line's singer is not `v1`; the
  lead's lines (v1) keep to the start of the view and the second singer's (v2) to the end,
  every part of a line (pronunciation, translation, background vocals) aligned with it, and
  each line narrowed so the two read as two columns: Apple's 60% of the width, but never
  under 280 px (at 360 px the share alone left lines of a word or two), by a margin on the
  box's other side, so the hover and focus highlight sits on the line's side too. Apple
  puts every singer but v1 on the second side, groups and everyone included; here the lines
  of anyone but v1 and v2 (v3, v4, v1000: Apple's ids for both singers together, a choir,
  everyone, seen as v3 and v4 in real duets) are centred in the middle, because on the
  second side a chorus everyone sings read as the second singer's, which it is not. The
  answer keeps the singers' ids but not their kind (person or group), so a trio's third
  singer is centred too, which still says "neither of the two". Right to left, the sides are
  mirrored (GTK flips the labels' alignment and the margins). The unsynced text stays as it
  is, and the singers are not named to a screen reader, as Apple names none (#307).
- **Instrumental breaks by Apple's rules, their dots in the next line's row** (2026-10-19).
  Apple's lyrics component shows three dots before the first verse when the first line
  starts after 9 s (from 0 to a millisecond before it) and between two verses (TTML `<div>`s;
  here a line marked `stanza`) when the next verse starts more than 9 s after the previous
  line's end (from a millisecond after that end), and never between the lines of one verse:
  `lyrics.instrumental_breaks()` follows it, from the latest end of the lines before (a duet's
  lines overlap), and none after a line without an end. The dots are not a row of their own,
  as Apple's are, but open (a `Gtk.Revealer`) over the line after the break, in that line's
  row: GTK 4.22's list stops its arrow keys at an item that cannot take the focus, so a break
  item would either trap the keyboard or be an invisible stop on it, and every reader of the
  lines (the text, the menu, a click's seek) would have to skip it. During a break that row
  is current, its line still dimmed; the dots light one at a time, the first as the break
  begins and the next at each third, on the same single timeout that moves the highlight to
  the next line (`Lyrics.next_change()`), with a CSS fade and a gentle breathing of the group
  (a pulse of its opacity, which only redraws it, where a scale would lay the list out
  again at every frame); with animations off GTK runs neither, and the revealer opens at
  once, so the dots only step. In a duet they sit on the side of the line that follows, where the eye goes next.
  The intro's dots are the first row, so at the start of a song the list is at its top (#305).
- **Words light as they are sung: drawn through a mask, swept with animations on**
  (2026-10-19). A word-timed line's pieces (Apple's spans: words and syllables) light on the
  current row only: the unsung text at the dimmed lines' opacity, so the line fills in from
  how the other lines look, the sung text at full, the main vocals, the background vocals
  and the pronunciation each by their own times, the translation whole (it is not timed).
  Drawn by the label itself (`LyricLabel.do_snapshot`: an alpha mask over its own drawing),
  not by a `Pango.AttrList` of foreground alphas: setting attributes clears the label's
  layout and queues a resize, so every word laid the row out again and reallocated the
  list (about 0.85 extra list allocations a word, measured), and it cannot fill a word in
  part. With animations on, the piece being sung fills in across its width over its
  duration with a soft edge, as Apple's gradient sweeps each syllable; that costs a redraw
  of one or two labels a frame while a piece is sung, capped at about 60 a second on any
  monitor (about 5 % of a core more at 60 Hz, docs/notes.md), and nothing while the tab is
  hidden, the music paused or between lines. With animations off (`gtk-enable-animations`,
  as reduced motion) each piece lights whole as it begins, on the existing timeout. The
  position is the Player's estimate, whole seconds refined, about 130 ms behind on average:
  not offset here, the same lag the line highlighting has (#304).
- **A full-screen player, not a full-screen lyrics view** (2026-10-19). Full screen shows
  the song playing as Apple Music's full-screen player does (#308): the artwork large, the
  title and the artist, the seek bar and the transport, and the lyrics beside them, larger,
  or the artwork centred alone for a song without; one column (a small cover beside the
  titles, the lyrics, the controls at the bottom) when the window is narrow or portrait,
  down to 360 px. It is a view of its own (`widgets/fullscreen_player.py`), the second page
  of a `Gtk.Stack` whose first is the bottom sheet, built on first use and kept: not the Now
  Playing sheet laid out anew, since an `AdwBottomSheet` never covers the whole window (its
  top gap, its handle, the content dimmed behind it). While it shows, the rest of the window
  is unmapped, so the pages let go of what they follow and Tab cannot leave it. There is one
  lyrics view: it moves from the sheet's Lyrics tab into the player and back
  (`fullscreen.FullscreenHost`), active in one place at a time, so one place paints, steps
  and sweeps the lyrics; back in the sheet it centres the current line again. It is entered
  from Fullscreen in Now Playing (beside the translation button) or F11, the HIG's
  Fullscreen key and the one accelerator without a modifier (a function key no widget
  takes), off while nothing plays (still listed among the shortcuts); Escape (once a menu
  or a toast has had it), F11 and Leave Fullscreen leave. The window is fullscreened and
  put back as it was: GTK keeps its size and maximized state through it, so quitting while
  full screen saves the normal state, and a window that was full screen before (a window
  manager's shortcut) stays so; the window manager taking it out of full screen leaves the
  player. It leaves on its own only when nothing plays any more (the Player's item gone,
  after its grace between queues): one song giving way to the next, an album or a playlist
  playing through, keeps it, and so does a pause. The window's keys that go to its pages
  (Ctrl+F, Ctrl+1, Ctrl+2, Ctrl+Shift+N, Go to Album) leave it first. Dark whatever the
  colour scheme, as GNOME's full-screen media views (Videos, Loupe) are: libadwaita's
  `osd` style (white text, controls for an on-screen display, the play button white) over
  a field made from the artwork's own pixels (shrunk to 32 px and blurred in a thread,
  stretched over the view) rather than Apple's background colour, which needs no bridge
  change and works for any artwork, under a black scrim just deep enough for its text to
  read at WCAG AA on the field's lightest pixel (`artwork.scrim_alpha()`: 4.5:1 for the
  small text at 70%, 3:1 for the dimmed lyric lines, large text), drawn by a widget of its
  own so the lyrics' redraws never draw it again. After three seconds without pointer
  motion or a key, while the music plays and nothing is in use (a menu open, the pointer or
  the keyboard focus on the controls), the header bar slides away, the seek bar and the
  transport fade (their room and focus kept) and the pointer hides, as in GNOME Videos;
  with animations off they go at once. Nothing runs or is fetched while it is not shown.
  MPRIS's `Fullscreen` stays false: no client uses it (#313).
- **The lyrics' edges fade, with no scrollbar** (2026-10-20). As Apple's lyrics do, the
  lines fade out at the top and the bottom of their area, in the sheet and the full-screen
  player, and no scrollbar shows (`EXTERNAL`: the wheel, the touchpad, a finger and the
  arrow keys still scroll them; a screen reader reads the lines as before). The fade is an
  alpha mask the view draws its page through, not a gradient of the background colour laid
  over the text: the full-screen player's background is the artwork's own colours, which no
  one colour matches, and a mask fades the text, not what is behind it. Each edge fades only
  as far as the text goes on past it, up to its 64 px band (a fifth of a short view), so the
  first line is whole at the top of the lyrics and the last at their end, as without a fade.
  In high contrast the edges stay hard, with libadwaita's line at a scrolled edge, as its
  own scrolled views turn their soft shadows into a line there; elsewhere that line is not
  drawn, the fade saying the same. The mask is drawn again with every frame the view draws,
  a word's sweep included: within the runs' spread (docs/notes.md) (#356).
- **Not possible through the web player** (2026-10-20, #358). The music plays in Apple's web
  player, through MusicKit JS, so what MusicKit JS and music.apple.com cannot do is out of
  reach, and a later audit need not suggest it again. Sound: MusicKit JS streams AAC at 64 or
  256 kbps (`PlaybackBitrate` STANDARD and HIGH; the app leaves MusicKit's own choice, which the
  bridge's `status()` reports as `bitrate`), never Lossless, Hi-Res Lossless or Dolby Atmos
  (Spatial Audio), so album pages show no audio badges (Lossless, Atmos, Hi-Res) on purpose:
  they would promise sound the app does not play. Processing: MusicKit JS has no equaliser,
  crossfade, AutoMix or Sound Check; an equaliser belongs to the system (EasyEffects on Chrome's
  PipeWire stream), not to the app. Offline: no downloads, as the web player has none. Features
  with no web API: Apple Music Sing, lyrics share cards, social profiles and friends,
  collaborative playlists, making smart playlists and a playlist's artwork upload. The user
  guide's Known limitations says so in a user's words.
- **What MusicKit's queue and live radio allow** (2026-10-20, #332, #343, checked live;
  `src/backend/README.md` has the calls). MusicKit says what it allows now in
  `mk.capabilities`, and the app follows it rather than work around it. A station's queue
  cannot be edited (`canEditPlaybackQueue` false, seen on a song-seeded station; follow the
  capability for the other kinds): no Remove, Clear or reorder in Up Next while one plays. A live station cannot be
  paused, sought or skipped: MusicKit ignores the seek and the pause and only `stop()` ends
  it, so its controls are Stop and LIVE, not Pause and a slider; its reported duration is
  the stream's window, not a length to show. Autoplay is the page's own switch, not the
  account's: the web player keeps it in its page's local storage for the account's token, so
  an Autoplay toggle in the app is the app's setting and does not follow the account to
  Apple's other players.
- **Create Station plays at once, by an id it builds** (2026-10-20, #339, checked live). As
  in Apple's players, Create Station is in the menus of songs and artists (the item playing's
  too) and replaces the queue with the station at once, with no toast: the bar says what
  plays. The station's id is `ra.<catalog id>`, which the web player builds rather than
  reads, so the app asks Apple nothing first; the item is offered only where that catalog id
  is known (a library song's `catalogId`, a library artist's when the library has one), so it
  never names a station that is not there. What it plays is a station like any other: a
  song-seeded one's queue cannot be edited (the entry above).
- **The last session, shown paused, handed over at Play** (2026-10-20, #342). As Apple's own
  apps do, the app opens with the last item in the bar, paused where it stopped, and its
  queue. It is kept in the cache (`session.json`: library ids and titles, so not the
  settings; written 2 s after a change and every 30 s while playing, at quit, never over a
  good file with nothing), and restored as the Player's own state (`restored`), not
  MusicKit's: Chrome is not started early, and nothing is asked of Apple for a session the
  user may never resume. MusicKit gets it at the first Play (or an Up Next row) as one play
  request (the album or playlist it came from while the queue still is that, else its songs
  by id; the position as `setQueue`'s `startTime`, with one seek after the play when MusicKit
  began further back), which is the path the app trusts most: loading the queue paused at
  launch would seek an item MusicKit had not loaded, without its Widevine licence, and would
  run only for those whose engine starts on launch. Until then seek, previous and next move
  through it paused, without the engine. Shuffle comes back off, the queue in its order (the
  same Up Next), since turning MusicKit's shuffle on reshuffles what follows; repeat comes
  back. Play Next or Later on it first queues it paused (the start waits for the first play
  in the bridge). No Preferences switch: Apple's apps, GNOME Music and the HIG's "fewer
  preferences" agree, and a paused bar gets in the way of nothing. Signing out and Clear
  Cache forget it; MusicKit refusing it drops it. Discord shows nothing until it plays.

## Engine

- **The overview searches the library, through the bus** (2026-10-01). The app exports
  `org.gnome.Shell.SearchProvider2` (`src/search_provider.py`), with a D-Bus service file
  whose `Exec` has `--gapplication-service`, as GNOME's own apps do.
  The Shell starts the app for a search when it is not running; that start runs
  `do_startup` alone, and the engine's autostart lives in `do_activate`, so no window shows
  and no Chrome runs until a result is chosen, and the app quits half a minute after its
  last call. The provider answers from the library in memory only: never the engine, never
  the Songs store built for it (a second on a big library; songs show once a page has
  built it). The desktop file stays `DBusActivatable=false`, unlike GNOME's own apps: the
  search does not need it, and a bus launch has no fallback to `Exec` (GLib drops the
  error), so an install whose service directory the session bus cannot see would leave the
  app's icon doing nothing.
- **Chrome as the engine** (2026-09-27). See "Why there is a browser inside" in
  `docs/architecture.md`. The real Chrome, because Chromium ships without Widevine.
- **Any Chromium-based browser with Widevine** (2026-10-20, #326). Nothing in the engine is
  Chrome's alone (the pipe, the flags, the profile's lock and Local State are Chromium's), so
  the browser is checked by what it can do rather than its name: once the engine is up, the
  page is asked for Widevine (`navigator.requestMediaKeySystemAccess`), and a browser that
  refuses it is kept running (the library, browsing and previews need none) but plays no
  song (`no-widevine`), with a toast saying so. Google Chrome is still the one tried first
  and the one tested; Edge, Brave, Vivaldi and Chromium follow it, and a snap is skipped (it
  cannot use a profile under a hidden directory). Not Firefox: it no longer speaks CDP, and
  WebDriver BiDi listens on a port, which the pipe was chosen to avoid.
- **The app owns MPRIS** (2026-09-27). The app publishes `org.mpris.MediaPlayer2.<app id>`
  from its Player, and Chrome runs with `--disable-features=HardwareMediaKeyHandling` so its
  own player never appears. A module of D-Bus code and every command relayed, in return
  for the Shell showing this app's name and icon, Raise focusing this window, the media keys
  reaching it, and a service that survives engine restarts.
- **DevTools over a pipe, no port** (2026-09-28). Chrome speaks CDP on its file descriptors 3
  and 4 (`--remote-debugging-pipe`), not on `--remote-debugging-port`. A DevTools port on
  127.0.0.1 answers every local user and every process that can open a socket, sandboxed apps
  with network access included, and whoever reaches it has full control of a browser signed in
  to the user's Apple Account: its session, its library, playback. A pipe reaches only the
  process that spawned Chrome. What it cost: a Chrome from an earlier run can no longer be
  reclaimed (so Chrome is tied to the app's life, below), the port preference went, and
  `scripts/am.py` runs a Chrome of its own unless the app opted in to a port. That opt-in is
  `APPLE_MUSIC_DEBUG_PORT`, for developers only: it opens a port on 127.0.0.1 beside the pipe,
  the log warns at every start, and nothing sets it by default, since while it is set the
  signed-in session is open to local users again.
- **Chrome lives and dies with the app** (2026-09-28). Chrome is spawned through
  `setpriv --pdeathsig TERM`, so the kernel ends it however the app ends (a crash, a SIGKILL, a
  lost display), not only on a clean quit; `flatpak-spawn --watch-bus` does the same in the
  sandbox.
  Which Chrome holds the profile is read from Chrome's own `SingletonLock`, checked against
  `/proc`, and a start ends such a Chrome before spawning its own. No state file records the
  engine's pid any more: the old one could sit at a predictable path in /tmp, and its check
  matched the profile as a substring. Without util-linux's `setpriv`, a crash can leave Chrome
  running until the next start.
- **No Chrome without its keyring** (2026-09-29). Chrome keeps the key that encrypts its
  profile's cookies in the desktop's keyring, and a Chrome that cannot reach it deletes those
  cookies, the Apple Music sign-in among them, for good. So the engine refuses to start Chrome
  on a profile whose `Local State` records the keyring's key when no `org.freedesktop.secrets`
  answers, or comes up when asked, on the bus Chrome will use (`no-keyring`, a toast with
  Retry), and `scripts/headless.sh` hands Chrome the desktop's session bus
  (`APPLE_MUSIC_HOST_SESSION_BUS`) while the app stays on its private one. A refused start is
  a toast and a retry; a lost sign-in is a trip to Apple's sign-in page and a full sync. A
  profile that never reached the keyring starts as before, since there is nothing to lose.
- **State from events, not polling** (2026-09-27). What is playing comes from MusicKit's events,
  forwarded through a CDP binding (`Runtime.addBinding`), plus one read when the engine comes
  up. The only polling is while waiting for sign-in, and briefly after it for the account's
  name.
- **The backend is a fork** (2026-09-28). `src/backend/` began as a copy of the extension's
  backend, and this app has since rewritten large parts of it. It is maintained here, for this
  app, in the app's own style (its provenance is at the end of `src/backend/README.md`).

## Code

- **asyncio on the GLib main loop** (2026-09-27), through PyGObject's `GLibEventLoopPolicy`.
  CDP is requests and events, which coroutines model directly: no locks, no hops between
  threads, and UI code awaits the engine in place. Blocking work goes to `asyncio.to_thread`;
  Chrome is spawned with `Gio.Subprocess`. Python 3.14 deprecates the policy call PyGObject
  still needs; if PyGObject changes its entry point, only `main.use_glib_event_loop()` changes.
- **One navigation view** (2026-09-27). The content pane is one `AdwNavigationView`. A sidebar
  item replaces its stack with the destination's root page, made on first visit and kept (a
  playlist's or folder's page only while it is among the last few shown); tiles push detail
  pages; root pages show a large in-content title and show the header bar's only while that
  one is out of view.
- **The cache as the library** (2026-09-27). `$XDG_CACHE_HOME/apple-music/library.json` is the
  one library snapshot, parsed off the main thread from the start of the process and wrapped
  into GObjects a section at a time. Thumbnails (320 px) are fetched for every item at sync;
  covers (640 px) on demand. Decoded textures live in an LRU at the size they are drawn: 8 MB at
  a scale factor of 1, the same tiles' 32 MB at 2 (2026-09-29).
- **Remove from Library: gone at once, back on a refusal** (2026-10-20). Removing a song,
  album, music video or one of Apple's playlists takes it out of the models before Apple has
  answered (`Library.hide`, a reload of library.json that leaves it out, with its album or
  artist when nothing of theirs is left and its entries in every playlist, as Apple takes
  them), after an `AdwAlertDialog` that says it goes from the playlists too; a refusal shows
  it again from the file and reports why. Apple's listings drop it 2 to 7 s after its 204,
  so the sync that follows (a quick pass that also reads the videos and the playlists that
  held it) waits until Apple's own read of the item is a 404, and every load leaves it out
  until one no longer meets it: a timed sync in between cannot bring it back. The user's
  own playlists keep Delete Playlist…, which says what it does to them; Apple's, which
  cannot be deleted, are removed (the same request, `DELETE /v1/me/library/playlists/<id>`).
- **Songs sorted in Python** (2026-09-27). Past a few thousand rows that the user re-sorts and
  filters, GTK's sorters read each Python item's properties from C too slowly, and a column
  view's own sorter compares pairs. The Songs page sorts and filters in Python and splices the
  result; every other list sorts with GTK's expression sorters.
- **The model's own words** (2026-09-28). What the app calls things (an untitled album,
  Home's own shelves, a count caption such as "12 songs, 43 min") is made and translated in
  `library.py` from the data, not read from English text the backend wrote into
  library.json, which gettext cannot reach. The captions are made once per Item, never in a
  list's bind.
- **Demo mode** (2026-09-27). `--demo` runs the app on a generated, invented library, so UI
  work, tests and screenshots never need Chrome or a real account.
- **Tests** (2026-09-28). Stdlib `unittest`, nothing to install. Logic lives in classes and
  functions without widgets, tested with stand-ins. Widget tests are allowed through
  `tests/gtk.py`, skipped without a display; CI runs them under Xvfb. The rest of the UI is
  checked with screenshots of the demo library. (First decided as screenshots only, no widget
  tests; changed because the logic that broke lived in widget classes.)
- **Weak connections in droppable widgets** (2026-09-28). A page, shelf, dialog or row that can
  be dropped connects its children's signals through `widgets.util.connect_weak()` and has no
  Blueprint handlers, because a connection to its own bound method forms a cycle through C that
  kept every popped page alive. `tests/test_page_lifetime.py` holds the line.
- **Errors as sentences** (2026-09-28). Everything that fails in the engine is an
  `EngineError` with a code; the user sees one plain-text toast per failure, whose sentence
  and button (`src/errors.py`) follow the code, and the detail goes to the log. A play MusicKit
  refused is worded from MusicKit's own code; sign-in and a failed sync have sentences of their
  own. A page that shows a state for the failure (Sign In, Start Engine, Try Again) does not
  toast it too.
- **The memory target** (2026-09-29). Anonymous memory, not RSS, which adds what the libraries
  and the GL driver map: under 250 MB after every page is browsed twice on the big invented
  library, and pages opened and closed leave at most 5 MB behind (`docs/notes.md`).
- **Comments describe the code** (2026-09-28), as it is and why: no phase numbers, review IDs,
  plans or history, which belong in commit messages.
- **A name of the app's own** (2026-09-30). The app is **Music Sleeve**, app ID
  `io.github.jackicus.MusicSleeve`. "Apple Music" as the display name was Apple's trademark
  used as a product name, which their guidelines for third parties do not allow. The service
  is still named where it has to be — the metainfo summary and description, the desktop file's
  `Keywords=` (so the app is still found by searching for "apple music"), and strings like
  "Sign in to Apple Music" — always less prominent than the app's own name. The full rule is in
  `.claude/rules/packaging.md` (#145).
- **An icon of the app's own** (2026-09-30). A record coming out of its sleeve, in GNOME's
  palette: the old icon was a red rounded square with a white double note, near enough to Apple
  Music's own logo to confuse users and to invite a complaint. Apple's guidelines for third
  parties allow no use of their logos or icons at all, and Flathub requires an icon distinct
  enough to carry the project's own identity. The symbolic icon is the record alone: at 16 px
  the sleeve behind it only muddies the silhouette. The development build's icon is the same
  artwork under a band of stripes, and the metainfo's brand colours follow it.
- **The accent is the user's** (2026-09-30). The app sets no accent of its own: libadwaita
  hands it whichever of GNOME's accent colours the user chose in Settings, and everything
  tinted (the Play button, the seek slider, the filled heart, links) follows. It had been
  pinned first to Apple Music's red, then to the new icon's purple; both were wrong for the
  same reason, that a GNOME app wears the user's colour, not its own. The metainfo's
  `<branding>` stays purple and keeps following the icon: that marks the app in a software
  centre, where it sits among other apps, and is not the user's choice to make (#195).

- **An item reaches MPRIS once** (2026-09-30). A new item's Metadata and Can*s wait for its
  artwork file, at most 200 ms (`ART_GRACE_MS`), rather than go out at once and again with
  `mpris:artUrl`: two changes made GNOME Shell's card blink through its no-cover icon at every
  track change (#182). The wait ends the moment the file is there, which is at once for the
  next song of one album (the same URL, nothing fetched) and a moment for a file on disk; a
  slower download publishes the item first and its artwork after, since a card that is right
  late is worse than one that fills in twice.
- **The keyboard walkthrough presses real keys** (2026-09-30). `scripts/a11y_check.py` sends
  them through the headless mutter's `org.gnome.Mutter.RemoteDesktop` interface, which
  `scripts/headless.sh` already puts on a private session bus, rather than dispatching each
  press through GTK's controllers: the window is then active, so the walkthrough covers what
  only an active window does — Tab from row to row and Down from one boxed sidebar section to
  the next — and typing is typed. The emulation stays behind `--emulate-keys`, and as the
  fallback on a session that has no such interface (a desktop one keeps it behind the
  remote-desktop portal, which asks the user first). It stays a tool to run here rather than a
  CI job: the container installs no mutter, and nothing in `check.sh` may need one (#169).
- **Artist pages are Apple's views** (2026-10-01). An artist's page is one catalog read with
  every view music.apple.com's views-based page asks for (`api.ARTIST_VIEWS`), kept for a day,
  laid out in the order and under the titles Apple gives: the release beside Top Songs (a grid
  three rows high), Essential Albums as large cards, the shelves, About (biography, From,
  Born or Formed, Genre) before Similar Artists. It replaces fetching every album with its
  tracks, which took one read an album. A library artist is the sync's own invention (no
  catalog id), so its catalog artist is found through one of its songs (the library album's,
  since the artist's copy of the tracks is dropped at load). The library's albums of the
  artist's show first, as In Your Library, beside the catalog's shelves: a library album
  carries no catalog id to tell it from the catalog's, so an album may be on both, which is
  the price of keeping what is in the library on the page (#236); Go to Artist opens the
  catalog artist's page while the engine is up. Videos about the artist open on music.apple.com: the engine is
  headless and has no picture to show. The demo engine answers with the artist pages the
  demo library invents (marked `demo`), and with none of Apple's (#226).
- **An album ends with its release and the catalog's shelves** (2026-10-20). Under the last
  disc, as every Apple Music client ends an album: the release date in full, "N songs, M
  minutes" and the ℗ line (else the label), then Other Versions, Music Videos, More By,
  Featured On and You Might Also Like (#335). The shelves are the album's documented views
  (`api.ALBUM_VIEWS`), asked with the album in one read; More By is no view of the album's,
  so it is a page of its first artist's `full-albums`, less the album, a second read whose
  failure only leaves More By out. Both are one answer kept for a day under the id the page
  asks by (`albums/`), as an artist's page is. A library album has no catalog id of its own,
  so the engine finds its catalog album through one of its songs, the way a library artist
  is found; the footer then takes the catalog album's date and ℗ line. The answer is asked
  after the tracks' first paint and appended as the list's last sections, so the page's
  first build never waits for it; without it (offline, the engine down, signed out, a 404)
  the page shows the songs and their count, and nothing is toasted: the shelves are extras,
  not the page. They live inside the track list, in rows of its own (a `Gtk.ListView`
  recycles only as its scrolled window's child), each shelf a horizontal list as the artist
  page's are. The demo library invents an answer for each hand-written album.
- **An artist of the library is shown as the library holds them** (2026-10-03). Apple Music
  has two pages of an artist: the catalog's, and its library's (Library › Artists: a list
  of artists beside the one chosen, their albums in the library under the name, Play and
  Shuffle). Both are here. The rule: **a click on an artist the library has** (the Artists
  list, a library artist's tile, a row's artist link, an album page's artist link) shows
  what the library holds of them, `pages/library_artist.py` (the Artists page's pane, or a
  page of its own pushed by `window.open_item`); **Go to Artist** (the menus) and the
  library page's name link open Apple Music's page of the artist (`window.open_artist_page`),
  as before; a link to an artist the library lacks goes where Go to Artist goes. A link
  is "the library has them" by name (`related.library_artist`), whatever page it is on: one
  rule for every link, and the library page's name leads on to the catalog in one click.
  The artist page's In Your Library always offers See All, which opens the library page.
  An artist's library page shows albums only, as Apple's does: a song added without its
  album sits under the sync's stand-in album and shows as that album's tile, so nothing the
  library holds of the artist's own is left out; songs of theirs on someone else's album (a
  compilation, a feature) are that album's artist's, the library's artists being its albums'
  artists (#268).

## Open

- Nothing. The questions that were open here are settled above; what is left is in
  `TODO.md` and the open issues.

