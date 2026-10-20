# Accessibility

The keyboard walkthrough every release should pass, and how to check it. The rules for new
widgets (names, roles, tooltips, focus) are in `.claude/rules/ui.md`; the keys themselves are in
`src/shortcuts.py`, which also feeds the Keyboard Shortcuts dialog (Ctrl+?).

## Keyboard walkthrough

`scripts/headless.sh scripts/a11y_check.py` walks these steps on the demo library (add
`--size 360x640` for the narrow layout, `--names` for the accessible names), step 8 with the
window maximized (a dialog is inside the window only when that is maximized or tiled; else it
is a window of its own, which the window's keys never reach). The keys are real: the headless
mutter injects them through its RemoteDesktop interface (`scripts/remote_keys.py`), so the
window is active and what needs that is walked too — Tab from row to row in Preferences and,
in the narrow layout, Down from one sidebar section to the next. Of the mnemonics in
Preferences it presses Clear's and checks that every labelled button has one, since the demo
leaves the other buttons insensitive or hidden. When a key or a page changes, change this
list and the script together.

1. Ctrl+1 puts the focus on the selected sidebar row. Down and Up move through every
   destination: in the wide layout they select, which shows the page; in the narrow one they
   only move (each section is a boxed list of its own there, and libadwaita passes the focus
   on from one to the next). Enter shows the row's page (and, in the wide layout, opens or
   closes a folder); Right opens a focused folder and Left closes it, without changing the
   page, and Left on a playlist inside a folder moves to the folder. Menu or Shift+F10 opens
   the focused playlist's or folder's menu under its row (its page's More Options: a
   folder's starts with New Playlist… and New Folder…), and Escape closes it, back on the
   row. A screen reader hears whether a folder is expanded, how deep an item is nested and
   that a playlist's row has a menu.
2. Ctrl+2 puts the focus in the page: the first tile of a grid, the Songs table, the Search
   entry, an album's Play, the Artists list's selected artist; from the page's header bar
   (Back, a filter's button, Sort By) and from the sidebar too. Arrows
   move between tiles and rows, Tab leaves a grid, shelf or list after one item, Enter opens a
   tile or plays a row, Menu or Shift+F10 opens the focused item's context menu and Escape
   closes it. On Albums, Return on Sort and Filter opens it, Down reaches Favourites Only,
   and Return shows the favourite albums alone.
3. On an album or playlist: Play, Tab to Shuffle and to More Options (the item's menu), Tab to
   the first track (Shift+Tab goes back to More Options), Down, and Enter plays from that
   track. On an album, Tab from the last track goes past the footer into Apple Music's
   shelves of it (Other Versions, More By…), and Shift+Tab from there goes back to the last
   track. One of Apple Music's the library lacks has Add between Shuffle and More Options;
   once added, the focus goes to More Options and "In Library" is read as text. Alt+Left
   (or Escape inside the page) goes back. On an artist: Play, the star (Space stars the
   artist or takes it back; read as the toggle "Favourite", pressed or not), More Options,
   the latest release, then (past the Top Songs arrows and See All) the top songs, where the
   arrows move from song to song and Enter plays the top songs from the one focused. On
   Artists, Ctrl+2 puts the focus on the list's selected artist; Up and Down move through the
   list (in the wide layout they select, which shows the artist beside it; in the narrow one
   they only move), and Enter shows the artist's albums with the focus on Play; Tab goes to
   Shuffle, More Options and the first album, and Enter opens it. Alt+Left from the album
   comes back to the artist and, in the narrow layout, again to the list, the focus on the
   artist.
4. The player bar shows only while something plays. With nothing playing there is no bar:
   Ctrl+3 leaves the focus where it is and a screen reader hears "Not Playing", while
   Ctrl+Shift+N still opens Now Playing (Nothing Queued), and Escape closes it with the focus
   back where it was. An item playing reveals the bar, and Ctrl+3 puts the focus on its play
   button. Space presses the focused button, switch, check box or boxed-list row, as anywhere
   in GNOME; on a tile, a list item, the seek slider or nothing, it plays or pauses, but never
   in an entry, in a menu or in a dialog. Ctrl+Right and Ctrl+Left skip. Menu or Shift+F10
   opens the item playing's menu (Go to Album, Go to Artist…); Escape closes it, the focus
   back on the button. A live radio station shows LIVE in place of the slider and its play
   button is Stop: a screen reader hears "Now playing live: …" as it starts, and "Stop,
   Live Radio" on the focused play button (the bar's, the sheet's and the full screen's;
   the LIVE badge itself takes no focus). Space stops it, Ctrl+Right and Ctrl+Left do
   nothing, and Shuffle and Repeat are insensitive. When the music stops and the bar goes, a focus it held moves
   into the page. The walkthrough does step 13 here.
5. Ctrl+Shift+N opens Now Playing with the focus on its play button; Tab goes through the controls,
   the Lyrics and Up Next toggle (Left and Right move between the two, Space or Enter
   switches), on Up Next its History toggle, Autoplay toggle and Clear (Space clears what
   follows the entry playing, with an Undo toast, and the focus moves to the entry playing as
   Clear goes insensitive), and into the list (arrows move, Enter seeks to a line or plays an entry, Menu opens an entry's menu, with
   Remove from Up Next after the entry playing; Delete removes the focused entry, and the
   focus moves to the one that took its place). Space on History shows the entries played
   before, most recent first, in place of Up Next (Autoplay and Clear go): Tab reaches them,
   Enter plays one again, their menus have no Remove, and Space on the toggle goes back.
   Then the close button and the header bar's buttons, More Options among them (the item
   playing's menu). Escape closes a menu, then the sheet, and the focus goes back to where
   it was. Ctrl+Shift+U opens Now Playing on Up Next and Ctrl+Shift+L on
   Lyrics (the bar's toggle for the tab shown reads as pressed); the other key switches the
   tab, the same key again closes the sheet. Space on the bar's Up Next button (wide windows:
   the narrow bar leaves the two to the sheet) opens it on Up Next, and Escape brings the
   focus back to the button. In the full-screen player, Ctrl+Shift+U goes back to Now
   Playing on Up Next. In an entry, the keys are the entry's (Ctrl+Shift+U is GTK's Unicode
   entry).
6. Ctrl+F shows Search with the cursor in the entry, over any page opened from its results;
   Ctrl+Up there leaves the volume alone. Tab from the entry reaches Apple Music's filter
   (All Results): Space, Down and Enter choose one kind, whose list shows, and the focus
   stays on the filter. Tab again, Right and Space choose Your Library. Escape in the entry
   clears it. Enter in the entry shows the results as shelves; Space on Songs' See All opens
   the kind's page with the focus in its list, End there loads the next page down to the
   end, and Escape goes back to the results. On Albums, Artists, Songs, Music Videos and a playlist
   (Favourite Songs too), Ctrl+F shows the page's own filter bar instead, with the cursor in
   its entry; typing on the page (in the list, or on the header bar's buttons) shows it too,
   with what was typed; the new count is read out once the typing pauses ("2 of 40
   albums"); Escape, in the entry or on the list, closes it, clears the filter and puts the
   focus back on the item it was on, scrolled into view however far down the list it was and
   whatever the filter left (the first item when the focus was elsewhere, the filter's
   button when no list shows), so the next arrow key moves on from it; on a playlist opened
   from a grid a second Escape goes back.
7. F10 opens the main menu, from a page in the narrow layout too (the sidebar comes back with
   it); it starts with New Playlist… (Ctrl+N, which the menu shows) and New Folder….
   Ctrl+, opens Preferences: Tab through the rows, Alt and the underlined letter for its
   buttons, Escape closes it. Ctrl+? lists every shortcut. A page's Sort By or Sort and
   Filter menu (Enter on its button) has a mnemonic of its own on every item: on Albums, F
   shows the favourites alone.
8. With a dialog open over the window, Alt+Left, Ctrl+F, Ctrl+1 to 3, Ctrl+Shift+N,
   Ctrl+Shift+L, Ctrl+Shift+U, Space, Ctrl+N, Ctrl+L and Ctrl+Up leave the page behind it
   alone (and open no other dialog).
9. A playlist's Rename… (and New Playlist…, Ctrl+N) opens its dialog with the cursor in the
   name;
   Tab reaches the description and the buttons, Enter renames (or creates), and Escape
   closes it with nothing changed. Remove from Library… asks first, with Cancel the default
   and Remove destructive (Escape closes the question, nothing removed); Delete Playlist…
   asks the same way, which the script does not walk.
10. F11 with nothing playing does nothing. With an item playing it shows the full-screen
    player with the focus on its play button (a screen reader hears the "Fullscreen Player"
    group, then the button); Tab goes through its controls and into the lyrics and never out
    of it (the rest of the window is not shown); on a line, Space plays or pauses and Enter
    seeks to it; Escape (once a menu or a toast has had it) leaves, the window back to its
    size and the focus back where it was. Now Playing's Fullscreen button shows it too, and F11
    leaves it, back on that button. The script walks this after step 5.
11. On All Playlists the header bar has New Playlist and New Folder, each named. A playlist's
    tile (Ctrl+2, then the arrows) opens its menu with Menu or Shift+F10: Move to Folder
    lists the folders it can go into by name, in one list (a folder inside another named
    after both), then New Folder…, a new folder holding it. A move is confirmed by a toast (with Undo), which a
    screen reader hears; dragging a playlist onto a sidebar folder does the same by pointer.
    The other drops have their keys too: Play Later and Play Next in a menu are what a drop
    on the player bar does, Add to Playlist › New Playlist… what songs dropped on All
    Playlists do, and an album's or playlist's Add to Playlist what its tile dropped on a
    sidebar playlist does.
12. On a playlist of your own, Alt+Down on the focused song moves it one place down and
    Alt+Up one place up; the focus stays on the song, and the move is announced ("“Song”
    moved to position 3 of 12"). Menu on a song lists Move Up and Move Down (Move Up not on
    the first song). Dragging a song within the list does the same by pointer. The demo
    shows the moves and keeps none.
13. With an item playing, Ctrl+L (Go to Current Song) opens the album or playlist it plays
    from (else its album) with the focus on its row, scrolled into view; from Now Playing
    and the full-screen player too, which close for it. Ctrl+Up and Ctrl+Down turn the
    volume a step up or down (a tenth) on a row, a tile or a button, and a screen reader
    hears the level ("Volume 80%"); on a sidebar row they are the row's (the focus moves,
    nothing is selected), on the seek slider the slider's, and in an entry the entry's.
14. Home shows Recently Played after its first shelf, and Tab reaches its tiles. F5 refreshes
    the page shown when it has a Refresh (Home, New, Made for You, Radio, Charts, a category),
    the focus staying where it was; the header bar's Refresh is named, and Space on it
    refreshes too, the focus staying on it.
15. Radio shows the live stations as large cards, then Recently Played: Ctrl+2 puts the
    focus in the live stations, Tab (past the shelf's arrows and See All) reaches the first,
    and Right, Enter plays the second. Charts (New's or Search's Top Charts tile) shows Top
    Songs as a numbered grid of songs, then numbered tiles: Ctrl+2 and Tab reach the first
    song, Enter plays the chart from it, and Escape goes back. The script walks this before
    step 14.

## The tools

- `scripts/a11y_check.py` sends real key presses. `scripts/remote_keys.py` starts a session on
  the headless mutter's `org.gnome.Mutter.RemoteDesktop` and `NotifyKeyboardKeycode` injects
  each one as a keyboard would; only keyboard events are asked for, so no screen-cast stream is
  needed. That call takes evdev keycodes, which the module works out from the accelerator
  through the keymap the compositor gave the client (`Gtk.accelerator_parse`, then
  `Gdk.Display.map_keyval`, a Wayland or XKB keycode being the evdev one plus 8); a keyval on a
  shifted level of its key brings Shift with it. Typing is real too. The compositor points the
  keyboard at a window only once it has an event to deliver, so the script presses Shift on its
  own first: without that the window is never active and the first key is lost.
- `--emulate-keys`, and the fallback where that interface is not on the session bus (on a
  desktop session it is behind the remote-desktop portal, which asks the user first),
  dispatches each press through GTK's own handlers instead. `press()` runs the handlers a real
  event would reach: the capture-phase key and shortcut controllers from the window down to the
  focus (a mnemonic, Alt and a label's underlined letter, runs there on its label, through the
  shortcut manager above it), then the shortcut controllers from the focus up, and a popover's
  own key handler. Typing is not emulated (the entry's text is set), the window is never
  active, and the steps that need an active window are left out.
- `--names` starts a private accessibility bus (a `dbus-daemon` with at-spi's configuration,
  from /usr/share/defaults/at-spi2 or /etc/at-spi2, on an abstract socket, and
  `at-spi2-registryd` from /usr/libexec, /usr/lib or /usr/lib/at-spi2-core), stops both when it
  exits, and lists each page's focusable controls that have no accessible name, as libatspi
  (and so Orca) reads them, Search's Show Results Of open among them. GTK and libatspi both follow `AT_SPI_BUS_ADDRESS`.
- An `Atspi.EventListener` sees events only when registered before the app starts, and after
  `Atspi.init()`. `Gtk.Accessible.announce()` from a widget that no client has asked about is
  dropped; from the window it is always sent (`object:announcement`), which is why the app
  announces through the window.

## Known gaps

- libadwaita's own, worked around here: `AdwSidebar` names none of its rows in sidebar mode
  and does not expose a folder's state or level (`sidebar_view.py` sets them);
  `AdwShortcutsDialog`'s rows are unnamed (dialogs/shortcuts.py names them); `AdwComboRow`'s
  default factories leave its list items unnamed, in the popup and in the row's own display
  of the value, and so do `GtkDropDown`'s (`widgets.labels.named_list_factory()` names them,
  for Preferences' combo row and Search's Show Results Of); an open
  `Adw.BottomSheet` leaves the content behind it "showing".
- Not checked by machine: input methods, Orca itself, the high-contrast switch live, and
  right-to-left layouts. Nor is CI: its container has no mutter, so the keyboard walkthrough is
  a tool to run here, not a job there.
