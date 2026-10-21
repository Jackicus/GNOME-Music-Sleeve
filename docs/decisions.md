# Decisions

The design decisions this app rests on, with the reasons and what was given up. When one
changes, change it here, with the date. The plan they came from is in
`docs/history/build-plan.md`.

## Product

- **Distribution: native first** (2026-09-27). Releases are `meson install` and an AUR package
  (`build-aux/aur/PKGBUILD`); until the AUR takes it, the package that PKGBUILD builds is
  attached to each GitHub release (2026-10-21, #547). The Flatpak manifest is for development
  only: from the sandbox, the app runs the host's Chrome through `flatpak-spawn --host`.
  Flathub is out of scope: it would refuse an app that depends on the host's Chrome. (It was
  also out of scope while the app carried Apple's name; that half no longer applies, but the
  Chrome dependency still does.)
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
  as "Add to Playlist's folders are submenus" below has it, ending in New Folder…, a folder holding it) are the keyboard's and the narrow layout's way; dragging a playlist's sidebar
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
  (Top Level, a drop on All Playlists) and a folder into another or out to the top level were
  switched on once Apple had been seen to take them (2026-10-21; `api.MOVE_TO_TOP_LEVEL`,
  `api.MOVE_FOLDERS` stay as the switches, so the app never offers a move Apple may refuse).
  Apple lists a folder in its new folder only about a minute after a move or a New Folder…
  inside a folder, having stopped listing a moved one where it was within seconds: the sync
  that follows waits for it (`actions.FOLDER_SETTLE_DELAYS`), and a held folder move keeps the
  folder's entries (`TreeChange.entries`), so a sync in between, finding it nowhere, does not
  take it and its playlists out of the sidebar. Drags are the app's own: one type,
  `library.ItemRefs`, and drop targets decide from the drag in progress
  (`widgets.dnd.current()`), so drags from other applications are not taken.
- **Drags carry links outward** (2026-10-20). Every drag source also offers its objects'
  music.apple.com pages (`actions.drag_links()`: what Copy Link copies, one a line, and a
  library album's catalog page by its catalog id, since a drag cannot wait for the engine)
  as `text/uri-list` and `text/plain`, after the ItemRefs in one `Gdk.ContentProvider`
  union (`dnd.provider()`), so a drop on a browser, an editor or a chat gives the link, as
  Apple's own clients do. The app's targets ask for the ItemRefs type alone and are
  unchanged; a text field of the app's (Search's entry) takes the link as any other text
  drop. A drag of nothing anyone else can open (an upload, a playlist of the user's, a
  folder) offers the ItemRefs alone, never the owner's library route.
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
  sheet covers the window while open, so no drag source is in sight of its Up Next tab (its
  own rows' drags are moves within it, #361), and the bar shows only while something plays. Songs, music videos and albums (their songs)
  dropped on All Playlists make a new playlist of them, through New Playlist's dialog with the first one's title
  filled in (a name made up without asking would need a rename), and its page is shown once
  Apple lists it; playlists and folders dropped there move to the top level (above).
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
- **Add to Playlist's folders are submenus, while each has a page of its own**
  (2026-10-21, #554; first #423). Add to Playlist lists the top level's playlists, then
  each folder as a submenu of its name holding its own playlists and then its folders, as
  deep as the sidebar nests them, New Playlist… last at the top; a folder with no playlist
  that can take the songs, at any depth, is left out, and a playlist is never offered its
  own songs. One long list with each folder a headed section (#423) ran off the screen
  with many playlists. A `Gtk.PopoverMenu` keeps each submenu as a page of one `GtkStack`
  named by its label, and a submenu's item opens the page of that name (GTK 4.20 to 4.22
  alike, with no attribute to name it otherwise): two submenus of one label share a page,
  so Add to Playlist › a folder could open Move to Folder's page and move the playlist
  instead of adding its songs, and two Untitled Folders, or a folder named `main` (the
  menu's own page), would open each other's. So the folders are submenus only when every
  submenu label of the whole menu is distinct and none is `main` (`actions.pages_distinct`
  over the folders' labels, Add to Playlist's, Move to Folder's); otherwise Add to
  Playlist falls back to the headed sections (a folder inside another after that one's own
  playlists, headed "Evenings › Late Night"), the selection mode's too. A label made
  unique out of sight (markup, an invisible character) is still refused: what the user
  reads and what a screen reader says must be the name. A folder's label has its
  underscores doubled (no mnemonic), so it can match a fixed label only where a
  translation gives that one no mnemonic. The HIG asks for submenus sparingly; a sliding
  popover shows one level at a time with a header back, so the depth never cascades and
  fits 360 px (nested popovers, `GTK_POPOVER_MENU_NESTED`, would cascade sideways, which
  no GNOME app's menus do). **Move to Folder stays one list** of the folders it can go
  into, a folder inside another named "Evenings › Late Night": a folder there is a place
  to move to, not a list to look into, so a submenu would need a Move Here inside each,
  every target one step further away; a library's folders are few beside its playlists;
  and only Add to Playlist's submenus can then collide. tests/test_context_menu.py opens
  every submenu of a playlist's menu in a real `Gtk.PopoverMenu` (folders three deep, and
  two of one name) and checks that each opens its own page showing its own items.
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
- **A phone's bar below 600sp** (2026-10-20, #369). The compact bar is laid out as Apple
  Music's mini player is on a phone: the artwork and the titles first,
  then Play (Stop for live radio) and Next at the end, with no Previous and no seek slider
  (a live station keeps its LIVE badge under the title). At 360 px three transport buttons
  before the artwork and a slider squeezed under the title left a dozen letters of it; the
  Now Playing sheet the bar opens has Previous, the slider and everything else. The wide
  bar is unchanged. The transport box is moved, not duplicated, so the buttons keep their
  focus, actions and names; right to left the row mirrors as GTK lays it out, and Tab
  follows GTK's order for a horizontal box (gtk-notes.md).
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
- **Play and Shuffle on Songs, at most 300 songs a queue** (2026-10-20, #376). Apple Music's
  Songs view has Play and Shuffle at the top; here they sit beside the title, as an album's
  under its own, and go under it below the table's 560sp breakpoint (a 360 px window). They
  play what the table shows, its sort, filter and Favourites Only applied, never more than
  that. The queue is one `songs` play request of library ids: MusicKit's `setQueue` looks
  each id up before anything plays, so it is capped at `discography.PLAY_LIMIT` (300 songs,
  about a day: the cap the library artist page's Play already used), not the 40,000 a big
  library holds, whose request would be a megabyte of ids and a long wait. Play queues the
  first 300 in the table's order; Shuffle draws 300 at random from all of them (so a shuffle
  reaches the whole library, not its first letters) and turns MusicKit's shuffle on, as an
  album's Shuffle does. Only the songs queued are read (a Track's id is a GObject property).
  Ctrl+2 still goes to the table, not to Play (`SongsPage.focus_content()`).
- **Your Library search in Apple's order** (2026-10-20, #376). Apple Music's library search
  leads with its best matches and the songs; Your Library shows Top Results (at most four
  of the artists, albums and playlists whose title is the text, begins with it, or has each
  of its words begin one of the title's: the search provider's `rank()` at 2 or better,
  `search.top_results()`), then Songs, Artists, Albums and Playlists. Top Results are hero
  cards, as Apple Music mode's; a song is no card, so the songs list right under them is
  where a song that matches best shows. The titles they are found in are read once per
  change to a store (`search.titles()`) and searched in Python: about 5 ms for a one-letter
  text over 3,000 albums, 868 artists and 301 playlists, under a millisecond for a word.
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
- **A notification when the song changes, off by default** (2026-10-20, #367). As Music on
  macOS offers, a switch in Preferences › General shows the new song (its title, its artist
  as the body, its cover as the icon) in a notification. Off until turned on: GNOME's
  notifications are for what the user would otherwise miss, and most users of a music player
  do not want one per song. Only while the app is out of sight (no window of it shown and
  focused): a song the window shows already needs no notification. Only a change from one
  song to another, after it has played a second: not the first song after launch or after
  playback ended (the user started it), not the session restored or its Play, not a skip
  within the second (the one that stays is announced), not a live station's programme. One
  id (`song-changed`), so each replaces the last and the tray keeps one, withdrawn when
  playback ends, when the setting goes off and at quit; another than the toasts' background
  notification, which it never replaces. The cover is a `Gio.BytesIcon` of the remote-art
  cache's file, read in a thread: the notification portal takes bytes where a file would need
  sharing. Its click runs `app.show-window`.
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
- **Several songs are selected in a selection mode; a click still plays** (2026-10-20,
  #362). Apple's players select with Ctrl- and Shift-clicks and act on the selection; here a
  plain click plays a song (above), so selecting is a mode of its own, as GNOME Music and
  Files have one: the Songs table, an album's and a playlist's songs (Favourite Songs' too),
  not Search's songs, a shelf's or Up Next. It is entered by the header bar's Select, by a
  Ctrl+click or Shift+click on a song (as Files' Ctrl+click selects: the modifiers are read
  as the row is activated, so a drag, Shift's Play Next on the player bar too, stays a
  drag), or by Ctrl+A on a song; in it a click, Enter or Space toggles a song and Shift
  extends from the last one toggled, Ctrl+A and Ctrl+Shift+A select all and none, and
  Cancel, Escape or any batch action leaves it, as does leaving the page. Outside it nothing
  changed: a plain click and Enter play, Space plays or pauses. The lists stay
  `Gtk.NoSelection` (nothing follows the pointer); the selection is a set of the Track
  objects (`src/selection.py`), which a reload keeps and a filter's new rows do not lose,
  where a `Gtk.MultiSelection`'s positions go at every key, and a filter narrows it to what
  it still shows, so an action never reaches a song out of sight. Rows show a check box and
  say "Selected"; the header bar shows the count (a menu of Select All and Select None) and
  Cancel in place of Select, Sort and Filter, which leave it the room at 360 px; a bar under
  the list holds Play Next and Play Later (one queue command for each run of songs, MusicKit's
  `songs` list; one song at a time if it refuses one), Add to Playlist (#340's batched add,
  or a New Playlist… of them), Remove from Playlist (one write of the entries kept, with Undo
  on its toast, as Up Next's Clear has, rather than a dialog) and Remove from Library… (one
  confirmation, a removal each, one sync after). A drag of a selected song carries the whole
  selection, its icon its count. While selecting, a playlist's songs do not move. Batch
  Favourite is left out: one rating write per song, and ambiguous over a mixed selection.
  Favourite Songs is not ambiguous, every song there a favourite: its bar has Remove from
  Favourites in place of Remove from Playlist (#491), one unlove a song (Apple has no batch
  rating write; four under way at once, the rest not tried after a failure), shown at once
  (the hearts and the playlist's rows, put back for a song whose write did not go), one
  toast with Undo, which loves them again.
- **Delete removes a playlist's song; Sort By is the view's; Add Songs… is a dialog**
  (2026-10-20, #372, #374). Delete on the focused song of a playlist of the user's is Remove
  from Playlist, as Files' Delete acts on what is focused and Up Next's Delete takes out its
  entry: a key of the page's own controller (`keyboard.remove_key()`), never an accelerator,
  since the filter's entry needs Delete. It goes through the selection's one write with Undo
  on its toast (`ItemActions.remove_entries()`, naming the one song), not the menu's single
  removal, which has no Undo, so a slip of the key is one click from being put back;
  in the selection mode it takes out the songs selected, as the bar's Remove from Playlist
  does, rather than only the focused one. One removal at a time a page: a second, made
  before Apple's answer, would be made on a list Apple has changed already and refused.
  Sort By (Playlist Order, Title, Artist, Album, Time, either way) orders only what the page
  shows, through a `Gtk.SortListModel` before the filter, as the grids sort: Apple's API has
  no sort of a playlist, and writing one would be a reorder of the whole list. So Play,
  Duplicate and a reorder keep the playlist's order, and while another order shows nothing
  moves (`can_reorder()`). It lasts as long as the page, not in the settings: a playlist
  opened again shows its own order, which is the one its songs are moved in, and the
  settings hold no playlist's id for it. Duplicate copies any playlist of the library
  (Favourite Songs and Apple's too, into one of the user's), named "<name> Copy" as Files
  names a copy, in the original's folder, with its description; a catalog playlist has Add
  to Library and Add to Playlist's New Playlist… instead. Add Songs… is a dialog rather than
  a mode of the Search page: it picks from the library's songs (all of them, narrowed as
  typed) and Apple Music's (a search of songs, paged as the Search page's list is), keeps
  the picks across both and every search, and adds them in their order with one write
  (`add_items_to_playlist()`, one POST up to `api.PLAYLIST_BATCH`), so a dozen songs are
  one toast and one refresh, not a dozen. It does not mark songs the playlist holds: a
  playlist may hold a song twice, as Apple's does.
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
- **Videos about an artist are 16:9 too; a video's thumbnail is kept by its shorter edge**
  (2026-10-20). An artist's More To See (interviews, films: `link` Items marked `video`)
  shows the music videos' frame, without the play symbol, since they open on
  music.apple.com rather than play here (`tile.FRAME`), and so does its See All. A video's
  thumbnail is asked in a 569x320 box (`normalize.thumb_box()`), not 320x320: Apple's `bb`
  fits a 16:9 image to the box, so the square one gave 320x180, which a 160 px frame at a
  scale of 2 drew 1.8 times enlarged. Its file has a name of its own (`<sha1>-wide.jpg`), so
  the next sync fetches it in place of the square-boxed one rather than keeping that. At a
  scale of 1 a tile decodes it to the same 284x160 texture as before; at 2x to 569x320,
  three times the square box's. Letting a video tile fall through to its cover instead
  (640x360) was the other way: the library's covers are fetched only by the pages that show
  them, so every video grid would have fetched its covers as it scrolled (#383).
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
- **A mini player in the main window's place** (2026-10-20, #366). As Apple's MiniPlayer on
  macOS and Windows, a small window of its own (`widgets/mini_player.py`, about 320 by 500
  px, down to 280 by 240) shows the song playing: the artwork, the title and the artist,
  the seek row (LIVE for a live station) and Previous, Play and Next, over the artwork's
  tint as Now Playing has it; Return to Main Window in its header bar. It takes the main
  window's place rather than sitting beside it: the main window hides as it shows and
  comes back, as it was, as it goes (`mini_player.MiniPlayerHost`), so the app has one
  window in sight and the mini player is not a second view of the same pages to keep
  apart. It is entered from the main menu, the player bar's menu and Ctrl+Shift+M (Apple's
  key for it on Windows), which also leaves it; closing it is leaving it, whatever background playback
  says, since a close there only puts the music back in its window (Ctrl+Q quits from it).
  One at a time: asked again, the one shown is presented. It is built as it shows and
  destroyed as it goes, its transport pieces letting go of the Player
  (`transport.Follower.detach()`), so a closed mini player follows nothing. Its size is
  remembered (`mini-player-width`, `mini-player-height`); its layout follows it
  (`mini_player.layout_for()`: the cover as large as the window allows, or small beside the
  titles in a low window). No lyrics, no Up Next, no heart or volume: what the issue asks
  for, and nothing in it redraws while a song plays but the seek row. It does not stay on
  top: GNOME on Wayland gives an app no way to ask (the window menu's Always on Top is the
  user's), so it promises nothing of the kind. Toasts go to it while it shows, as the
  window the user sees (`Application.toast()` through `get_active_window()`), and a search
  result from the Shell brings the main window back for its page
  (`Application.show_main_window()`).
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
- **Shelves show no scrollbar; their arrows page them** (2026-10-21, #555). A shelf's row
  (a `Shelf`'s, a `SongShelf`'s) is `hscrollbar-policy: external`, as the lyrics are: the
  overlay scrollbar under each row caught the pointer as a mouse wheel scrolled the page
  past it. The row still scrolls sideways with a touchpad, a tilting wheel, Shift and the
  wheel, a finger, and as the focus moves along it; a vertical wheel still goes on to the
  page. The previous and next arrows beside the title, which follow the row's adjustment,
  are what shows that a row scrolls, so they show whenever it overflows, at any width: the
  400sp floor that kept them out of a narrow window (for the title's room, a phone being
  scrolled by touch) went, since a narrow desktop window with a mouse had no other way along
  the row. A title the arrows and See All leave too little room goes onto a second line
  rather than being cut short.
- **Not possible through the web player** (2026-10-20, #358). The music plays in Apple's web
  player, through MusicKit JS, so what MusicKit JS and music.apple.com cannot do is out of
  reach, and a later audit need not suggest it again. Sound: MusicKit JS streams AAC at 64 or
  256 kbps (`PlaybackBitrate` STANDARD and HIGH: the `streaming-quality` setting, Preferences ›
  Engine › Streaming Quality, sets `mk.bitrate` at every start and page load, and the row shows
  the bitrate the bridge reports, #368), never Lossless, Hi-Res Lossless or Dolby Atmos
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
- **Up Next's order: moves within a section, edits numbered and replayed** (2026-10-20,
  #361). An entry after the one playing moves by a drag (the whole row, as a playlist's
  songs move: no drag handle, which would be one more widget per row to bind; a mouse's
  drag, since a touchscreen's scrolls), Move Up and Move Down in its menu, and Alt+Up and
  Alt+Down, as a playlist's songs do (#333). It moves within its own section only: what the
  user queued among Playing Next, autoplay's among Autoplay. MusicKit's splice gives the
  queue item back with its `isAutoplay`, so an autoplay entry moved into Playing Next would
  still be autoplay's and start the Autoplay heading there, and a song of the user's dropped
  among autoplay's would be taken for autoplay's; making one the other is not known to stick
  (not checked live). The bridge moves it with two `spliceQueueItems`, as checked live,
  and posts only the queue moved, never the one an entry short between them; the Player
  takes the entry out and puts the same object back (a splice of the whole span between the
  places made a 500-place move take 131 ms to the next frame against 25 ms: docs/notes.md),
  and the focus goes with the entry.
  Removes and moves are numbered, and every queue snapshot names the last it holds: a
  burst (Alt+Down held, Delete pressed quickly) leaves the Player's queue ahead of
  MusicKit's, and an event for the first edit would otherwise take the list back a step,
  with new rows and the focus lost. The Player replays the edits not yet held onto each
  snapshot before comparing it, so events are still applied as they come, never delayed;
  Clear and its Undo are not replayed (nothing is moved while a Clear is out). No toast for
  a move (the row moves); a screen reader is told where it went. A move made while Shuffle
  is on is lost when Shuffle is turned off: MusicKit puts back its own unshuffled order, the
  moved entry with it, and Up Next follows MusicKit's queue (checked live on 2026-10-20). The
  app does not replay the moves over the new order: they were made in an order that is gone.
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
  read by id does not find, and only the item itself gone drops the session (since #508
  every list of songs by id is retried so: see below); and the
  session keeps the user's queue only, without what autoplay added after the item, since
  autoplay's songs restored by id came back as songs the user queued, with ten more of
  autoplay's after them. MusicKit's autoplay (when on) adds its own again after the queue
  once it plays.
  Since #379 the engine lost mid-song (Chrome crashed or killed, the page crashed, closed or
  silent: the engine's `lost`, which no stop the app asks for emits) falls back to the same
  state rather than an empty bar: `Player.engine_lost()`, called by the app with its
  Restart toast, keeps the item paused where it was, the user's queue, its source (none
  under a play request, or once the queue was edited away from it), repeat and shuffle as
  they were (a pause changes no mode; Play turns MusicKit's shuffle on after the queue), a
  live station stopped without a position, and Play starts the engine and resumes it
  through the restore path, its retries and waits included. Up Next's edits still out to
  MusicKit (and a Clear's Undo) end with the page that would have answered them. A stop
  the app asks for (quit, sign-in's restarts, sign-out, the engine's Stop in Preferences)
  has no `lost`, and resets the bar as before: the user ended it. A page that reloads (the
  bridge's `bridgeReset`) still resets: the engine is not lost then.
- **Genres, and Genre and Year columns** (#363). Apple Music on macOS offers both: a
  Genres view in its sidebar once chosen, and columns to choose in its song lists. Genres
  here is a sidebar destination listed while `show-genres` is on (Preferences › Library ›
  Show Genres, off by default: the sidebar has no editor of its own, and most people browse
  by album and artist), a grid of the library's genres, each tiled with its first album's
  cover and counted in albums, opening its albums as the Albums page shows them. A genre is
  an album's (its first `genreNames`, which the sync has always kept), not its songs': the
  page lists albums, and an album of mixed genres would otherwise be in several. The index
  is made from the Albums store when the page first asks (`Library.genres()`, a few
  milliseconds for 3,000 albums, on no startup path) and kept up to date by every load; a
  genre's page is a C filter over the Albums store, which follows every sync as the store
  does (an album whose genre changed is spliced over itself: `genre` is a SORT_KEY). The
  columns are the songs' own genre and year (each song's first `genreNames` and
  `releaseDate`, library.json version 5, so an older file is synced again at once): a
  playlist's songs come from many albums. One setting (`song-columns`) holds them for the
  Songs table and every playlist's table, chosen from either one's sort menu as check items
  (Apple's are in its View Options; here the menu that already holds the table's other
  choices), and they show only where the table has room (Songs from 760sp, a playlist's
  table from its 720sp breakpoint), their items hidden with them. Composers and
  Compilations, also in Apple's list, are left out: the API gives no composer to library
  songs and no compilation flag to library albums.
- **A list of songs MusicKit cannot all find plays without the missing ones** (#508). Every
  play of song ids (Songs' Play and Shuffle, a library artist's Play, a shelf of songs, a
  selection's Play Next and Play Later, the session restored) goes through the Player's
  `play()`, `play_next()` or `play_later()`, and MusicKit refuses such a list whole when one
  song in it is gone (`NOT_FOUND`). So the Player, not each page, sends it once more without
  the songs MusicKit names and those a read by id does not find, in order, from the song
  asked for or the next one found, with one toast that counts them ("2 songs could not be
  played"): a song gone from a 300-song Shuffle should cost that song, not the play. Once:
  a second refusal is shown as it is, never a loop of reads and plays. The session restored
  keeps its rule that its item gone drops it (it is not shown at another song).

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
- **An icon of the app's own** (2026-09-30, redrawn 2026-10-21, #552). A dot-matrix display
  whose lit dots draw a double note: a dark panel, unlit dots dim, lit ones yellow to orange, a
  14 by 14 grid without its four corner dots so it sits inside the panel's rounded corners;
  flat, with no darker side under it. The first icon of all was a red rounded square with a
  white double note, near enough to Apple Music's own logo to confuse users and to invite a
  complaint; Apple's guidelines for third parties allow no use of their logos or icons at all,
  and Flathub requires an icon distinct enough to carry the project's own identity. So the note
  came back only as an LED pattern on a dark panel, nothing like a white note on red (the record
  and sleeve drawn in between is in git). The symbolic icon is the note alone as a pixel
  silhouette on 2 px cells: at 16 px the panel and its dots only blur. The development build's
  icon is the same under a band of stripes across the bottom rows, which the note leaves unlit,
  and the metainfo's brand colours follow the icon.
- **The accent is the user's** (2026-09-30). The app sets no accent of its own: libadwaita
  hands it whichever of GNOME's accent colours the user chose in Settings, and everything
  tinted (the Play button, the seek slider, the filled heart, links) follows. It had been
  pinned first to Apple Music's red, then to an older icon's purple; both were wrong for the
  same reason, that a GNOME app wears the user's colour, not its own. The metainfo's
  `<branding>` keeps following the icon (its orange): that marks the app in a software
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
- **A catalog playlist ends with the catalog's shelves, its curator a link** (2026-10-20,
  #371). As an album's page does: Featured Artists, More By the curator and You Might Also
  Like, from one read of the playlist with its curator and views (`Engine.playlist_page`)
  and, for an Apple curator's, a page of the curator's playlists (Apple's More By view is
  always empty and has no /view/ read: checked live on 20 playlists, #532), kept a day
  (`playlists/`), asked after the tracks' first paint and appended to the list,
  only for a playlist of the catalog's (Apple's or a curator's, in the library or not:
  `release.playlist_target()`); a playlist of the user's has Suggested Songs there instead.
  The curator's name under the title stays plain text until that answer names the curator,
  then is the same flat link an album's artist is: an Apple curator's page is the category
  page the app already has; a third party's (`curators`) and a shared playlist's listener's
  (`social-profiles`, their profile) have no page the app can read, so they open on
  music.apple.com, as a third-party curator found by Search does. No answer leaves
  the plain name and the songs, and nothing is toasted.
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
  that the live row shows are left out of it, and so are Apple's links (More to Explore,
  the genres) and its banners' art, which New shows (#370). The page is a `ShelvesPage`
  with an `arrange` of its own rather than a class of its own: PyGObject refuses a
  subclass of a `Gtk.Template` class.
- **Charts is a pushed page, reached from New and Search** (2026-10-20, #344). Apple Music
  has no Charts destination of its own, so neither does the app: Top Charts ends New
  (under More to Explore, unless Apple's own links reach the charts) and leads Search's
  browse categories, as Apple's Browse lists its chart rooms, and both
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
  tiles), so the songs need no page of their own.
- **Charts' genre menu: in the header bar, not remembered** (2026-10-20, #404). A
  `Gtk.DropDown` (All Genres, then the catalog's genres, `Engine.genres()`) packed at the
  end of the Charts page's header bar, beside Refresh, so it stays in reach however far
  the page is scrolled, as a view's filter does; libadwaita leaves a drop-down raised there.
  A genre's charts are its rankings alone (`genre=<id>`, no `with`): the Daily Top 100 and
  City Charts are every genre's. Choosing one starts the page over (`ShelvesPage.start_over`:
  the spinner, then that genre's shelves or the status page), never the old genre's shelves
  under a new name. The choice is the page's: Top Charts opens on all genres, as
  music.apple.com's charts do, and a `viewTop?genreId=` link on its genre (titled Top
  Charts, the genre's name, or the link's own words until the genres are read, in the
  menu), but for Music's (34, `api.ROOT_GENRE`, the genre every other belongs to, which
  New's own "Charts" link names): its charts are every genre's, so it opens All Genres
  (#530); a setting would have a Top Charts tile open on a genre chosen days before. Each
  genre's answer is kept a day beside every genre's (`charts/<id>.json`), the genres too
  (`genres.json`). The page is still a `ShelvesPage`: the menu is a small class it holds
  (`pages.charts.GenreMenu`), its pure parts src/charts.py's.
- **New's banners, and More to Explore as links to in-app pages** (2026-10-20, #370). New
  opens as Apple's does: the hero row's items as wide banner cards (Apple's `designBadge`
  over the title and the content's tagline, over the 320's own editorial artwork or the
  317's content's, cut at its source's shape and fetched for the widest card), a shelf
  `form` of their own (`banners`) so the shelves after it keep their tiles; an item
  without a banner shows its cover whole on its colour, and a hero row without any banner
  stays hero cards. Apple's rows of links (391, More to Explore; 322, the genres) end the
  page as cards of a label and a chevron, not tiles: Apple gives them no artwork. Each
  opens what the web player would, in the app: a room as a grid of its contents (a
  `GridPage` that fetches, since a room is a collection to browse, not shelves), a
  grouping (New's shape) or a multiroom as a page of shelves with its own links, the charts
  as the Charts page, anything else in the browser; each kept a day as the other editorial
  pages are. Any shelves page shows the links its answer carries, so a grouping's page ends
  as New does. Top Charts stays among them, first, unless Apple's links reach the charts
  themselves. Radio's hero and links are left as they were.
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

- **Replay is a pushed page, reached from Made for You and Home** (2026-10-20, #365). Apple
  Music shows Replay as a shelf of its Home and Made for You, not as a destination, so the
  app has none in the sidebar: More for You, a link card at the end of Made for You and of
  Home (`explore.replay_sections()`), pushes one page (`pages/replay.py`, `window.open_item`
  for kind `replay`), as Top Charts does. The page is a `ShelvesPage` over the music
  summaries (`/v1/me/music-summaries`, the latest year's views), its rankings numbered as
  the charts' are (Top Songs a grid of songs played as one queue, Top Artists and Top
  Albums numbered tiles), then each year's Replay playlist, which opens its page. Its year
  menu is the Charts page's genre menu again (a `Gtk.DropDown` in the header bar, the
  choice the page's, never remembered), over the years Apple lists, the latest year's
  asked without a year so one kept answer serves it whichever year it is; a past year
  Apple answers nothing for shows its playlist alone. Kept a day as the other pages of
  Apple's answers are. The minutes listened and milestones are left out: no documented
  read gives them.

## Open

- Nothing. The questions that were open here are settled above; what is left is in
  `TODO.md` and the open issues.

