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
  playlist's menus: the folders it can go into in one list, a nested one named after both,
  as "No folder is a submenu" below has it, ending in New Folder…, a folder holding it) are the keyboard's and the narrow layout's way; dragging a playlist's sidebar
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
- **A playlist's songs reordered, at once and safely** (2026-10-20). On a playlist of the
  user's (`Item.editable`: not Favourite Songs, nor one of Apple's) a song moves by dragging
  it within the list (an insertion line, the list scrolling near its edges), by Move Up and
  Move Down in its menu, and by Alt+Up and Alt+Down on the focused song (GNOME Text Editor's
  keys for moving a line; not accelerators, `keyboard.move_step()`); the move is announced.
  The whole row drags, as it already did onto a sidebar playlist, with no drag handle: a
  handle would put a widget in every recycled row, and a click still plays (the drag starts
  past GTK's threshold and cancels the click). Apple's API has one way to reorder, the web
  player's: `PUT …/tracks` with the whole list. So the write reads Apple's list first and
  sends back every entry it read, by its own id and type (the read includes the songs Apple
  cannot play, which a PUT of what is shown would delete), and refuses, writing nothing, when
  that list is not the one the move was made on (`conflict`: changed on another device):
  merging a move into a list the user never saw could put songs anywhere. Library playlists
  carry no `trackCount` and the ids already say whether the list changed, so neither a count
  nor `lastModifiedDate` is compared (a rename moves the date too). The move shows at once
  (`Library.reorder()`: the same rows, one splice, the order held through syncs until
  library.json shows it, as folder moves are); one write per drop, and Move Up and Move Down a
  second after the last press, so a burst is one write; one write at a time per playlist;
  any other write to it goes after the order (`PlaylistOrder.flush()`). A refusal puts back
  Apple's order; the toast has Undo. Once Apple's read shows the new order, a playlists pass
  reads that playlist's tracks into library.json, unstamped so the next full pass reads them
  again (the listing's date can come before the tracks show the change); Add and Remove from
  Playlist do the same, so all three survive a restart. Up Next is not touched, as in Apple's
  apps. In the demo a move shows and nothing is written.
- **Drops that queue and make playlists** (2026-10-20). As on Apple's Mac app, songs, music
  videos, albums and playlists dropped on the player bar join Up Next: at its end (Play
  Later, which is what the Mac app's drop does), or after the item playing with Shift held
  (Play Next), each by the target its menu's Play Later queues (`actions.queue_targets()`: a
  song by its catalog id, an album or a playlist by its play target); a drag holding anything that cannot be queued
  (a folder) is refused whole, not queued in part. The bar is the one place: the Now Playing
  sheet covers the window while open, so no drag source is in sight of its Up Next tab, and
  the bar shows only while something plays. Songs, music videos and albums (their songs)
  dropped on All Playlists make a new playlist of them, through New Playlist's dialog with the first one's title
  filled in (a name made up without asking would need a rename), and its page is shown once
  Apple lists it; playlists dropped there still move to the top level (switched off, above).
  A drag carries its objects as well as their Refs (`ItemRefs.objects`), since a Ref names a
  song by the id a playlist takes, not the catalog id MusicKit queues it by.
- **Add to Playlist for albums and playlists** (2026-10-20). As on every Apple client, an
  album's or a playlist's menu has Add to Playlist (the same submenu as a song's, a
  playlist not offered to itself, New Playlist… named after it), and its tile drags onto a
  sidebar playlist; every grid and shelf of tiles is a drag source now, the drag on the
  view, not the tile, so binding costs nothing more. What is added is its tracks, in order:
  the library's (by their own `i.` ids) when it has them, else the engine's `item()` read
  (catalog ids), which follows Apple's pages. One POST of the list
  (`Engine.add_tracks_to_playlist`), in runs of `api.PLAYLIST_BATCH` (100) since no limit
  is documented or checked, one after the other so the order holds; a failure partway
  leaves what went in, is reported, and the playlist is read again. One toast counts them.
  A second click while the same add runs is ignored. A playlist's sidebar row dropped on
  another playlist's adds its songs too (its drag offers MOVE alone, which the row
  answers); on a folder it still moves. Albums dropped on All Playlists make a new playlist
  of their songs; playlists dropped there still move.
- **No folder is a submenu** (2026-10-20, #423). A `Gtk.PopoverMenu` keeps each submenu as
  a page of one `GtkStack` named by its label, and a submenu's item opens the page of that
  name (GTK 4.20 to 4.22 alike, with no attribute to name it otherwise): two submenus of one
  label share a page. A playlist's menu had a folder as a submenu in both Add to Playlist
  and Move to Folder, so Add to Playlist › a folder could open Move to Folder's page and
  move the playlist instead of adding its songs; two folders of one name (two Untitled
  Folders) or one named `main` (the menu's own page) did the same. A label made unique
  out of sight (markup, an invisible character) was refused: what the user reads and what
  a screen reader says must be the name. So the two submenus with fixed labels are the
  only ones, and inside them nothing is nested: Add to Playlist lists the top level's
  playlists, then each folder's in a section headed by its name (a folder inside another
  after that one's own playlists, headed "Evenings › Late Night"); Move to Folder is one
  list of the folders it can go into, a folder inside another named so. This is also
  what the GNOME HIG asks of menus (submenus sparingly, never nested deeper than one
  level), and the headed sections are GTK's own (a section's label). Nested popovers
  (`GTK_POPOVER_MENU_NESTED`, which has no stack) would keep the folders as submenus, but
  cascade sideways, which no GNOME app's menus do and which does not fit 360 px.
  tests/test_context_menu.py opens every submenu of a playlist's menu and checks that it
  shows its own items.
- **A sidebar row's menu is its page's** (2026-10-20). A playlist's, a folder's, Favourite
  Songs' and All Playlists' rows open the item actions' menu for their Item
  (`actions.build_menu`, through `menu_for`), the one their page's More Options and their
  tile show, so the two never drift apart (the sidebar's had been a shorter list of its
  own). The controller opens it from the row as a tile's opens (`widgets/context_menu.py`'s
  `popup()`): at the pointer for a right click or a long press, under the row for Menu or
  Shift+F10. AdwSidebar's own context menu is not used: a section's `menu-model` leaves Menu
  and Shift+F10 dead (its `menu.popup` is enabled only by a model on the whole sidebar), and
  in the sidebar mode they would open the selected row's menu rather than the focused one's
  (#349). The narrower font and the menu over the top of the sidebar in the audit's
  screenshot were the harness's: the row was scrolled out of view.
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
  slider or nothing. Now Playing is Ctrl+Shift+N, leaving Ctrl+N to the HIG's "New", which
  is New Playlist (as on Apple's players). Bare keys and editing chords are never
  application accelerators (`src/keyboard.py` decides them).
- **Apple's playback keys, GNOME's terms** (2026-10-20). Go to Current Song is Ctrl+L, as on
  Apple's players: the album or playlist of the library's the queue came from, else the
  song's album, the focus on the song's row, from Now Playing and the full-screen player too
  (they close). A playlist's filter that hides the song is cleared for it (#443), one that
  shows it is kept: the key asks for the song, so the page shows it. The volume is Ctrl+Up and Ctrl+Down, a tenth a press, announced, and the
  window's own key (`keyboard.volume_step()`): they are editing chords, a text view's
  paragraph keys, a slider's page step and, on the sidebar's rows, the move of the focus
  without selecting, all left to those. The grids and lists select nothing, so there the
  keys move the focus only as Up and Down do, and they take the volume.
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
- **Suggest Less in the menus, not on the heart** (2026-10-20, #341). An item has one rating
  at Apple: 1 a favourite, -1 Suggest Less. A menu shows Favourite or Remove from Favourites,
  and Suggest Less or Undo Suggest Less, but no Suggest Less beside a favourite, as the web
  player has it; Favourite on an item rated Suggest Less replaces it. The heart of the player
  bar, Now Playing and the full-screen player stays two states (a Suggest Less shows it
  empty): a third state there would be a control nobody could read at a glance. A menu asks
  the engine for the rating as it opens, the one read it made for the favourite already.
- **An artist's favourite is a star, not a rating** (2026-10-20, #357). Apple's players star
  an artist on their page, and the web player writes it to `/v1/me/favorites`, not to the
  ratings (an artist's ratings path is always a 404), so the app does the same: a star toggle
  (Adwaita's `starred-symbolic`) beside Play, and Favourite / Remove from Favourites in an
  artist's menus, but no Suggest Less, whose write for an artist is unverified. The state is
  the artist page's own read (`extend=inFavorites`), so the page's first build asks nothing
  more; a menu reads it alone as it opens, past MusicKit's cache. A press shows the new state
  at once and puts it back, with the error's toast, when Apple refuses. The library holds no
  artists' favourites (library.json's are songs, albums, playlists and videos), so a library
  artist's tile shows no heart; a library artist the app has not matched to Apple Music has
  no star until their page has found them.
- **Favourites and dates come with the listings** (2026-10-20, #347). The sync asks the
  library listings it already reads for `inFavorites` (`extend=inFavorites`, the songs'
  included albums by `extend[library-albums]=`), which costs no request, rather than reading
  ratings or the catalog's `personalRating` for the whole library (135 to 400 requests more
  for 40,000 songs). Checked live: a song rated 1, as the app favourites it, is
  `inFavorites: true`. A listing that refuses the extension is read again without it, and the
  songs' favourites are then Favourite Songs' songs. library.json keeps them as one list of
  ids per section, not a flag per entry: a song is many Tracks (its album, each playlist,
  Songs), which are immutable records, and a heart changed in the app changes one set
  (`Library.set_favourite`, from the Engine's `rated`). The file is not rewritten for it:
  the next sync reads Apple's state, so a heart changed here and then the app restarted
  before a sync shows the file's state until a sync or a menu's rating read corrects it
  (accepted: rewriting a 50 MB library.json per click is not). Recently Added is the
  library's albums and playlists (and the music videos Apple dates) by `dateAdded`, to the
  second (albums carry a time, checked live, despite the documentation's date), ties in
  Apple's recently-added order; a loose song's stand-in album, which has no date, last.
  The heart in a row or tile is a dimmed mark, as the explicit badge is, that comes and
  goes without a layout: an image shown by its opacity in a row, a CSS background in room a
  tile's subtitle line always keeps (an image more a tile cost 12 ms a grid's first build); Favourites Only is a check item in the
  sort menu (Sort and Filter, as Nautilus puts Show Hidden Files beside its sort orders).
  The format bump (library.json version 3) makes an older file resync as soon as the engine
  is up; only a full pass writes the current version, a short pass (quick, playlists,
  shelves) the version of the file it kept the rest from (2026-10-20, #437), since one that
  stamped the current version on a file it had not rebuilt put the upgrade's full sync off
  until the interval. 1.0.0's short passes did that, so 1.0.1 writes version 4, the same
  shape, and every 3 is synced once more: one full sync on the upgrade, rather than guessing
  from a file's contents whether its hearts and dates were ever read.
- **A filter on the library's lists** (2026-10-20). Albums, Artists, Music Videos, Songs
  and a playlist's songs (Favourite Songs' too) have one filter bar (`widgets/filter_bar.py`),
  as GNOME's apps put one over a list: the header's search button, Ctrl+F, or typing on the
  page shows it; Escape (in it, or on the page) closes and clears it, before a pushed page's
  Escape goes back. Ctrl+F takes a library page's filter when the page has something to
  filter (`keyboard.search_target()`) and goes to Search from anywhere else, as Nautilus
  and Contacts give Ctrl+F to the view shown. Every filter matches as the Songs filter and
  Your Library search do: the whole text, case and accents ignored, in one of the title, the
  artist and the album (an Item's title and subtitle), not words spread over them, so a
  search's See All opens Songs on the same songs. It narrows Favourites Only (both apply).
  While a playlist is filtered its songs cannot be moved (no drag, no Alt+Up, no Move Up in
  their menus): the order shown is not the playlist's. Recently Added, All Playlists and a
  folder have none (few items, in an order of their own), nor an album's tracks.
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
  context menu, a drag (to a sidebar playlist, or within the user's playlist to reorder it)
  and a row's artist and album links (`src/widgets/track_links.py`) claim their presses
  before the row sees them, so they are unchanged. The Songs table keeps no selection any more (a `Gtk.NoSelection`, as the lists
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
  cells that grow with the page, where the grids' tiles were centred in theirs and drifted
  (28 px wide, 13 at 360); under 400sp the margins shrink to the 14 px that still fit two
  tiles, the grid never centred (a centred scrollable has GTK measure its width for its
  height, which warns) (#243).
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
  the stream's window, not a length to show. It is told by its item (`isLive`), never by
  its times. Every Pause there is (the bar's button, Space, MPRIS's Pause and PlayPause)
  stops it, though MPRIS says `CanPause` false: a Shell card or a media key that cannot
  pause should still end the music. Stopped, MusicKit holds nothing; the app keeps the
  station shown, stopped, as a session restored (`Player._keep_station`), so Play tunes in
  again, as Apple's players do. Ctrl+Right and Ctrl+Left stay the window's while it plays
  and do nothing, rather than move the focus. MPRIS publishes no `mpris:length`, Position 0
  and no Seeked; Discord no timestamps. Autoplay is the page's own switch, not the
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
- **Up Next's edits: at once, MusicKit's queue the truth; Autoplay on** (2026-10-20, #332).
  Remove from Up Next, Clear and Clear's Undo change the Player's queue at once and then
  MusicKit's (`queue.spliceQueueItems`, `clearAfterCurrent`, the cleared entries spliced
  back), each naming its entry by index and id, as the web player checks, so a queue that
  changed meanwhile is never edited in the wrong place; MusicKit's `queueItemsDidChange`
  that follows then finds the queue as it is, and a refusal shows MusicKit's queue again.
  The Player applies every queue event as the fewest splices of its store, so the rows
  stay (on a 500-entry queue one removal went from rebuilding 205 rows, 186 ms, to one, 10
  ms: docs/notes.md), and events are not coalesced in time: turning Autoplay off removes
  its entries one event each, each a one-row splice. Clear has an Undo toast rather than a
  confirmation (the HIG's way), Remove neither (the row goes, and a screen reader is told).
  No per-row remove button: the menu, Delete and a long press reach it with a mouse, the
  keyboard and a finger, and a button on every row is a widget per row to bind. Autoplay is
  on unless turned off (the `autoplay` setting, `true`: Apple's apps start with it on), set
  on MusicKit at every engine start and after the page reloads; the entries it adds are
  listed under an Autoplay heading. While a session is restored (#342), the edits change it
  alone, and it is queued as its songs from then on.
- **Autoplay for every queue; Clear's Undo leaves one Autoplay batch** (2026-10-20, #471,
  #473). MusicKit makes an autoplay station for each new queue itself, but a queue set
  with `startWith` asks the old station for songs first and, when that answer lands after
  the station has gone, MusicKit's controller is left "loading" for good: no autoplay for
  any later queue until the page reloads (src/backend/README.md, "Autoplay across
  queues"). The bridge's `play()` stops MusicKit's autoplay before `setQueue` and clears a
  load left stuck, rather than stopping passing `startWith` (a track row and a restored
  session need it) or reloading the page. Clear's Undo puts the queue back as it was: the
  ten entries autoplay added after the Clear go when Clear took autoplay entries of its
  own (the user's songs and their autoplay come back as one batch), and stay after the
  user's songs when it took none (they are then the queue's autoplay); songs queued
  between Clear and Undo go before autoplay's, where Play Later puts them.
- **Up Next with covers and History; Now Playing tinted by the artwork** (2026-10-20,
  #353). As Apple's queues do, each Up Next row shows its entry's cover in place of a
  number (the entry playing has the track rows' play symbol over its cover), under a
  Playing Next heading for what follows the entry playing. A row's cover comes from one
  lookup per artwork URL (`queue.EntryArt`): the file on disk (the thumbnail it fetched
  before, the library's own thumbnail of that artwork, the cover the bar fetched), else the
  thumbnail fetched, a few at a time, only for the rows still bound a moment after they
  were (a fast scroll through a long queue asks for nothing it passed), and never in the
  demo; bind only reads what is known. History is a toggle above the list that shows, in
  place of Up Next, the queue's entries before the one playing (MusicKit's queue keeps
  them), the most recent first, which play again on Enter or a double click, as Apple's
  History button does on macOS; not a section above Up Next, which would put the past
  between the tab and what plays next, scroll the entry playing away from the top, and make
  the Up Next list's sections (#332) move with every song. Remove from History is not
  offered: MusicKit's played entries are not the account's history. The toggle goes off
  when the tab is left, so Up Next is what the tab opens on. Now Playing's background is
  the full-screen player's backdrop drawn faintly (one widget, `widgets/backdrop.py`, and
  one field per cover, made in a thread and shared), as Apple's apps colour their player
  from the artwork: the field over the sheet's own colour at the most opacity, up to 50%,
  at which the sheet's text still reads at WCAG AA on every part of it in the colour scheme
  shown (`artwork.tint_alpha()`; its dimmed labels at 70%, as the full-screen player's, so
  that a light scheme leaves room for any tint at all), the plain background when none
  will do and in high contrast; a new song's tint crossfades in, at once with animations
  off. The sheet makes it only while it is in sight.
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
  through it paused, without the engine; the request plays what the bar shows when it goes
  out, so a step or an Up Next row taken while the engine starts for it (or the autostart at
  launch is still under way, #472) is what plays, and a second Play meanwhile sends
  nothing (the session stays shown, and kept, if the start fails). Shuffle comes back off, the queue in its order (the same Up Next), since turning
  MusicKit's shuffle on reshuffles what follows; repeat comes back. Play Next or Later on it
  first queues it paused (the start waits for the first play in the bridge). No Preferences switch: Apple's apps, GNOME Music and the HIG's "fewer
  preferences" agree, and a paused bar gets in the way of nothing. Signing out and Clear
  Cache forget it; MusicKit refusing it drops it. Discord shows nothing until it plays.
  Since 2026-10-20 (#464, #465), two answers from the live check: MusicKit refuses a whole
  queue by ids when one song cannot be resolved (`NOT_FOUND`, a song since removed from the
  library), so that refusal is tried once more without the songs MusicKit names and those a
  read by id does not find, and only the item itself gone drops the session; and the
  session keeps the user's queue only, without what autoplay added after the item, since
  autoplay's songs restored by id came back as songs the user queued, with ten more of
  autoplay's after them. MusicKit's autoplay (when on) adds its own again after the queue
  once it plays.

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
  Start), and `scripts/headless.sh` hands Chrome the desktop's session bus
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
- **Filters after the sort, their changes recycled** (2026-10-20). A grid and the Artists
  list filter their sorted items (a `Gtk.FilterListModel` over the `Gtk.SortListModel`), so a
  filter's change never sorts again, and show a filter's change through `ShownModel`, which
  inserts the new items before removing the old with a scroll to the top between, so the
  view rebinds its rows rather than building them (the Songs table's `_show()` did this
  already). A key on 3,000 albums went from 48 to 21 ms (docs/notes.md).
- **The model's own words** (2026-09-28). What the app calls things (an untitled album,
  Home's own shelves, a count caption such as "12 songs, 43 min") is made and translated in
  `library.py` from the data, not read from English text the backend wrote into
  library.json, which gettext cannot reach. The captions are made once per Item, never in a
  list's bind.
- **Demo mode** (2026-09-27). `--demo` runs the app on a generated, invented library, so UI
  work, tests and screenshots never need Chrome or a real account. Its writes are refused
  with a toast, but for a playlist's new order, which shows (and is not kept), so the
  keyboard walkthrough and the screenshots can move songs, and an artist's favourite, which
  the session remembers, so the artist page's star works.
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
- **An artist's page opens with Apple's banner** (2026-10-20). Where Apple has a wide
  picture of the artist (its web player's rule: the editorial background, else the
  portrait cut with the `vf` crop Apple recommends; about half of the artists tried), the
  page's hero is that picture, edge to edge under the header bar, with the name, genre,
  Play and More Options in white at its foot, as Apple Music shows it; else the round
  portrait beside the name, as before (#355). The picture is cut at 3:1 and the header is
  its width over three, between 240 and 440 px: a phone shows the middle of it, a
  maximized window keeps the top songs in view. White text over a picture needs no colour
  scheme of its own: a black scrim, deepest at the foot, carries it in both (deeper still
  with high contrast). The banner is fetched at the width shown, in steps, never at Apple's
  full 4320 px, and its place is held in Apple's colour for it until it fades in, so
  nothing moves when it comes; the switch from the portrait to the banner comes with the
  catalog's answer (from the day's copy, at once, after the first visit), with the rest of
  the page. The latest release sits beside Top Songs down to 700sp (a release card and one
  column of songs), not 900sp, so it is not alone at a common window width.
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
- **Radio is Apple's radio page, with Recently Played as one shelf** (2026-10-20, #336).
  The page is the editorial grouping behind music.apple.com's own Radio page
  (`groupings?name=radio`, asked as New's is, with the stations' programmes and shows),
  shaped by New's own grouping parser (`normalize._grouping_shelves`) and kept a day, as
  New is: the live stations first, as large cards, then Apple's shelves in Apple's order.
  The stations the user played (`library.radio`, which the sync keeps) are one shelf,
  Recently Played, after the live stations, bound to the library's store itself so a sync
  reaches it, and shown alone while Apple cannot be asked and nothing is kept (with the
  status page's button still behind Refresh), so the page is never empty for a library that
  has stations. A live station's subtitle is the programme on air when the page is shown,
  worked out from the answer's `events` then rather than when it was fetched, and an answer
  whose programmes have all run out for a station is not fresh, whatever its age
  (`expires`). A radio show is an Apple curator: its tile opens its page (the category
  page, which a curator's grouping already makes), never Play. The hero row's stations
  that the live row shows are left out of it; Apple's links (More to Explore, the genres)
  wait for #370. The page is a `ShelvesPage` with an `arrange` of its own rather than a
  class of its own: PyGObject refuses a subclass of a `Gtk.Template` class.
- **Charts is a pushed page, reached from New and Search** (2026-10-20, #344). Apple Music
  has no Charts destination of its own, so neither does the app: a Top Charts tile ends
  New (under More to Explore, where Apple's New page ends with its links, #370's to fill)
  and leads Search's browse categories, as Apple's Browse lists its chart rooms, and both
  push one page (`pages/charts.py`, `window.open_item` for kind `charts`). The page is a
  `ShelvesPage` over `GET /v1/catalog/<sf>/charts` (every kind at once, most played,
  `with=dailyGlobalTopCharts,cityCharts` for the Daily Top 100 and City Charts playlists;
  asked again without `with` if Apple refuses it), kept a day as the other editorial pages
  are, in a fixed order (Top Songs, Top Albums, Top Playlists, Daily Top 100, City Charts,
  Top Music Videos) whatever order the answer has. A ranking's place is its point, so the
  rankings are numbered: Top Songs as the artist page's grid of songs (one queue from the
  song activated, as music.apple.com plays a chart) with its number before each, the rest
  as tiles with the number over the cover's corner (`widgets.shelf.RankedTile`, not a
  change to every tile); the Daily Top 100 and City Charts are a playlist a place, not a
  ranking, so plain tiles. `ShelfColumn` picks the widget by the shelf's `form` (songs or
  tiles), so the songs need no page of their own. No genre filter yet (#404): the request
  takes `genre=`, the page has nowhere to choose one.
- **Home's Recently Played is asked as Home is shown; Refresh is F5** (2026-10-20, #346).
  Home's other shelves are the library's, which the sync writes every few hours; Recently
  Played follows what was just played, so it is not one of them: it is
  `Engine.recently_played()` (Apple's documented `/v1/me/recent/played`, ten a read, up to
  thirty), a kept answer like New's, which Home shows at once, then asks Apple for past
  the cache once it is a minute old, each time the page is shown (`home.Throttle`: no
  more often, and not for a minute after Apple failed; the engine down or signed out is
  waited out by watching it). Nothing of it is ever toasted: the shelf stays as it was.
  It goes after the first shelf, where music.apple.com puts it under Top Picks, and a
  recommendation of Apple's that only repeats it is left out meanwhile. An answer comes
  into one shelf the page keeps (`home.RecentlyPlayed`: the fewest splices, an item still
  played keeping its object, the library's own Item where it has one), so its widget and
  tiles stay; an answer that would move the page under the user (the shelf coming or
  going above where they scrolled) or take the focus (it is in the shelf) waits until the
  page is next shown, rather than adjusting the scroll behind their back. Refresh, in the
  header bar as on New, asks for Recently Played past the throttle and has the sync read
  the shelves again in a pass of their own (`sync_library(shelves=True)`: the
  recommendations, Heavy Rotation and Recently Added, everything else kept from the last
  file), not a full sync, which reads every song. Its key is F5, which GNOME's apps give
  Refresh, as a window action that refreshes whichever page shown has a Refresh (Home,
  New, Made for You, Radio, Charts, a category); Ctrl+R, their other Refresh key, stays
  Refresh Library. A recommendation's `reason` is its shelf's subtitle, a dimmed line under the
  title, when it does not just say the title again.
- **A playlist's header, and Add / In Library** (2026-10-20). A playlist's hero says what
  Apple Music's does: its curator under the title (the account's name for one of the
  user's, which carry none), then "Updated" and the day it last changed (today, yesterday,
  a weekday within the week, else the date: Apple's `lastModifiedDate`, the `modified` the
  sync writes from every listing, apart from the stamp its tracks were read under,
  `tracksModified`, so an edit made in the app does not take it away, #436), then its
  songs and time; the genre and the year that were there (the year
  was the modified date's) are gone. An album's caption is unchanged. An album or playlist
  of the catalog's has **Add** beside Play and Shuffle (an album opened from a shelf, which
  is subtitled with its year, is by its `artistName`: `release.album_artist()`), which becomes **In Library**, a
  state with no action (the menu has the rest), once the library holds it; the library's
  own pages show neither, being the library's (#351). Whether the library holds it is
  answered from what is loaded (`Library.holds()`), never with a request on the page's
  first build: by catalog id (an Apple playlist added names its catalog playlist as its
  play parameters' `globalId`), else, for an album, which a library album carries no
  catalog id for, by title and artist, confirmed by a song when the page has them. Apple
  lists an addition seconds to a minute after taking it, later than the quick sync that
  follows, so a successful add is noted in the library (`note_added()`) until a reload
  lists it: In Library does not flip back meanwhile. Its menu, wherever it shows, asks the
  same `holds()`: one held has no Add to Library, and its Remove from Library takes out
  the library's album or playlist it was found as (#446). Add and More Options keep together,
  on the buttons' line or, where it has no room (a phone, a narrow window beside the
  cover), on one of their own under Play and Shuffle (an `AdwWrapBox`), rather than
  ellipsizing the buttons or moving the cover's breakpoint.
- **A curator is a page, never a station** (2026-10-20, #359, #360). Apple's curators (a
  genre's page, a radio show) have no `playParams`, so Play and Favourite on one could only
  fail. Every curator, wherever Apple puts one (a shelf, the search landing, an artist's
  Radio Shows), is a category tile that opens its page, and its menu is Open in Browser and
  Copy Link alone; the normaliser never makes one a station. The page is the category page,
  asked as music.apple.com asks it (the grouping's shelves with their contents, then the
  curator's playlists), so a show's page lists its episodes, which play as stations. A show
  offers no Go to Artist: Apple names its host (`showHostName`), not the host's artist. The
  show's banner waits (#401): the category page has no hero.
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

- **A search's kind pages on as it is scrolled** (2026-10-20, #345). Apple's search answers
  at most 25 of a kind a request, with a `next` offset. The shelves of every kind ask for 20
  each (and Top Results); a kind of its own (the filter, a shelf's See All) is a list of
  rows, not a grid of tiles, as Apple Music's own search lists them, fed by a
  `search_pager.SearchPager` that asks for the next 25 when less than a screen is left below
  the view, and ends with what it found ("35 songs"), or Try Again when a page fails. A list
  of rows takes a footer, which a `Gtk.GridView` cannot (it has no sections). The filter is a
  `Gtk.DropDown` beside the entry, not a toggle group: nine kinds do not fit in 360 px, and
  the drop-down is reached by one Tab from the entry. Radio shows and curators are asked for
  with every search and shown as category tiles, as everywhere else (their page is the
  category page); a third party's curator, whose page the app cannot read, opens
  music.apple.com's. The demo answers a search from an invented catalog
  (`demo-search.json`), so the filter and See All show in its screenshots.

- **View Credits is a dialog of boxed lists, and its names lead nowhere** (2026-10-20, #364).
  A song's credits are a short read-only list beside what is playing, not a place to
  browse, so they open in an `AdwDialog` (a bottom sheet in a narrow window) over the page,
  not a pushed page that would take the user from where they were: one boxed list per kind
  of credit, as Apple orders and titles them, each person's roles under their name, as the
  HIG lays out a list of properties. A credited person is not linked to an artist page:
  Apple's credit has an id of its own, not an artist's catalog id, and finding the artist
  would take a search a name could answer wrongly. Only a song with a catalog id offers
  View Credits (an upload has no credits at Apple). The answer is kept for a day, as the
  other catalog answers are, and the demo answers from invented credits.

## Open

- Nothing. The questions that were open here are settled above; what is left is in
  `TODO.md` and the open issues.

