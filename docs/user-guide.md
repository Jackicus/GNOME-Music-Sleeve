# User guide

Using Music Sleeve once it is installed: signing in, everyday use, what it cannot do, what to
do when something goes wrong, what it sends where, and where it keeps your data. The
[README](../README.md) has the requirements and the install steps.

## Signing in

1. Start Music Sleeve. On a first run, the sidebar ends with a **Sign In** button.
2. Click **Sign In**. A Chrome window opens on music.apple.com. Sign in there with your Apple
   Account, as you would in a browser: the app never sees the password.
3. Once Apple reports you as signed in, the window closes and Chrome carries on hidden. The
   app then syncs your library, and a banner shows its progress.

## Everyday use

- The app starts Chrome, its playback engine, whenever it starts. Preferences › Engine ›
  Browser › Start Engine on Launch turns that off; the first thing you play then starts it.
- The app opens with the song you last listened to in the player bar, paused where it
  stopped, and Up Next as it was (the songs you queued: Autoplay adds its own again once it
  plays, when it is on): **Play** carries on from that second. Before you press it,
  the previous and next buttons and the slider move through it without playing; a song in
  Up Next plays from its start. The queue comes back in its order with Shuffle off (turn it
  on to shuffle what follows), and with Repeat as it was. A radio station comes back as the
  station, live. The system's media controls show the song paused too. Signing out or
  clearing the cache forgets it.
- While the engine runs, the library is refreshed when the last refresh is older than the
  interval chosen in Preferences › General › Library › Refresh Library (every hour, every
  6 hours, the default, every day, or manually). Last Refreshed beneath says when it last was;
  its Refresh button, or <kbd>Ctrl</kbd>+<kbd>R</kbd>, refreshes it at any time.
- Preferences › Engine › Streaming Quality chooses how Apple Music streams: High Quality
  (256 kbps, the default) or High Efficiency (64 kbps), which uses less data on a metered or
  slow connection. While the engine runs, the row says the bitrate it streams at now: Apple's
  player may choose 64 kbps itself when the connection is slow.
- Closing the window quits the app and stops Chrome. To keep the music playing with the window
  closed, turn on Background Playback in Preferences (<kbd>Ctrl</kbd>+<kbd>,</kbd>); the
  system's media controls bring the window back.
- Preferences › General › Playback › Notify When the Song Changes shows a notification with
  the new song's title, artist and cover each time the song changes while the app is in the
  background (its window closed, or another window in front). It is off until you turn it on.
  Each notification replaces the last, so they never pile up; a song you skip within a second
  is passed over, and the first song after you start the app, a live station's next programme
  and anything that changes while you are looking at the window are not announced. Clicking
  the notification brings the window back.
- Preferences › General › Playback › Discord Presence puts the song playing on your Discord
  profile, as "Listening to Apple Music" with the title, the artist, the album and its cover,
  and the artist in the status under your name. It is off until you turn it on, and it needs
  the Discord desktop app running on the same computer (the web client cannot be reached).
  Discord shows it only while something plays (a live station with no clock): pausing stops
  the clock and, five seconds later, takes it off until the music plays again, as playback
  ending or the app quitting does.
- **Home** shows Apple Music's recommendations for you, your **Heavy Rotation** and what you
  added lately, from the last library refresh, and, after the first shelf, **Recently
  Played**: the albums, playlists and stations you played last, on any of your devices.
  Recently Played is asked of Apple Music each time you open Home (at most once a minute),
  showing the last one meanwhile; it comes in place, so the page does not move under you.
  The refresh button in the header bar, or <kbd>F5</kbd>, asks Apple Music for all of
  Home's shelves again at once. A recommendation that says why it is offered shows the
  reason under its title. <kbd>F5</kbd> refreshes New, Made for You, Radio and Charts too,
  and the pages New's links open.
- Search shows what you opened from it lately under **Recently Searched**, above the browse
  categories; **Clear** empties it. The list stays on this computer, as music.apple.com keeps
  its own in the browser, and goes with the cache (Clear Cache, signing out).
- Apple Music's results come as shelves of every kind, **Top Results** first, then artists,
  songs, albums, playlists, music videos, stations, **Radio Shows** and **Curators**. The
  menu beside the search field (**All Results**) shows one kind instead, as a list; a
  shelf's **See All** opens its kind on a page of its own. Both lists load more as you
  scroll, down to the last one Apple Music has, and say how many there are at the end; if
  more cannot be loaded, **Try Again** at the end of the list asks once more. A radio show
  or a curator opens its page (one Apple Music has no page for here opens in your browser).
- **Your Library**, beside **Apple Music** by the search field, searches your library
  instead, as you type, whether or not the engine runs, in Apple Music's order: **Top
  Results** first (your artists, albums and playlists whose name is or begins with what you
  typed), then your songs as a list, then artists, albums and playlists as shelves. When
  there are more songs than it lists, the songs' **See All** opens Songs filtered by what
  you typed.
- On Albums, Artists, Songs, Music Videos and a playlist's page (Favourite Songs too),
  just start typing to filter what the page lists (or press <kbd>Ctrl</kbd>+<kbd>F</kbd>,
  or click the search button in the header bar): it keeps what has the text in its title,
  its artist or its album, case and accents aside. <kbd>Esc</kbd> clears the filter. It
  works with **Favourites Only**; while it filters a playlist, the playlist's songs cannot be
  moved. Elsewhere <kbd>Ctrl</kbd>+<kbd>F</kbd> goes to Search. On Songs, click a column
  title to sort by it, or use **Sort and Filter**.
- **Play** and **Shuffle** beside the Songs title (under it in a narrow window) play the
  songs the page lists, as sorted and filtered (**Favourites Only** too): Play in that
  order from the first, Shuffle in a random order drawn from all of them. Either queues up
  to 300 songs at once, about a day of music.
- Your favourites (songs, albums, playlists and music videos you marked as a favourite, here
  or in another Apple Music app) have a small heart: on a song's row before its time, on a
  tile after its artist. **Favourites Only** in **Sort and Filter**, on Albums, Songs and
  Music Videos, shows them alone, until you choose it again; each page remembers it.
- **Recently Added** is everything in your library, newest first: albums and playlists, and
  music videos when Apple Music dates them. Albums can also be sorted by **Date Added**.
- In a wide window a playlist's songs are a table, as the Songs page is: click an artist
  or an album there to open its page.
- A playlist's page names its curator under its title (your name, for your own playlists,
  once Music Sleeve knows it from the sign-in), then when it was last updated and how long
  it is. An album or playlist from Apple Music that is not in your library has **Add**
  beside **Play** and **Shuffle**: it adds it to your library, and the page then says
  **In Library**, as it does for one you added before. Apple Music takes up to a minute to
  list what you add; the page shows it at once all the same.
- An album's page ends as Apple Music's does: under the last song, the release date, how
  many songs and minutes it holds and its ℗ line, then **Other Versions** (deluxe editions,
  remasters), **Music Videos**, **More By** the artist, **Featured On** (playlists with its
  songs) and **You Might Also Like**, each shown when Apple Music has some. They come a
  moment after the songs and are kept for a day.
- Under your own playlists, **Suggested Songs** are songs Apple Music suggests adding, based
  on what the playlist holds, six at a time (twelve with Preferences › General › Suggested
  Songs › Show More Suggestions): click one to play it, its **+** button to add it to the
  playlist (the next suggestion takes its place), and the refresh button for new ones.
  They are kept for a day, or until the playlist's songs change. With **Preview
  Suggestions** on (in the same place), a click plays Apple Music's 30-second preview
  instead, and a second click stops it: the music playing pauses meanwhile, and the play
  button in the bottom bar takes it up again.
- **Radio** is Apple Music's radio page: the live stations first, as large cards, each with
  the show on air as you open the page, then the stations you played recently (**Recently
  Played**), then Apple's shelves of episodes, radio shows, genre stations and more. A
  station plays when you click it; a radio show opens its page: its name and host over the
  show's wide banner (when Apple has one), then its episodes and its playlists. The page is kept for a day, or until the shows on air change, and its refresh
  button asks Apple again. A live station (Apple Music 1 and the others) plays as it is
  broadcast: the player bar, Now Playing and the full-screen player show **LIVE** in place
  of the slider and the times, and the play button is a stop button, since a live station
  cannot be paused, wound on or skipped (previous and next are off, and so are shuffle
  and repeat). Stopped, the station
  stays in the bar, and **Play** tunes in again, live. The system's media controls and
  Discord show it with no length or progress, and their pause stops it too. An artist who hosts a show on Apple Music Radio has it under
  **Radio Shows** on their page, and its episodes under **More To Hear**.
- **New** is Apple Music's New page: its featured banners first, each with Apple's label
  ("NEW ALBUM", "UPDATED PLAYLIST") over the title and a line about it, then its shelves
  (new songs, new releases, playlists, stations, music videos), then **More to Explore**,
  Apple's links to its collections and pages, and its genres. A collection opens as a grid
  of what it holds, a page as its shelves (with its own links at the end), the charts as
  **Top Charts** below, and a link to a web page in your browser. These pages are kept for
  a day; their refresh button asks Apple again.
- **Top Charts**, at the end of **New** (under **More to Explore**, unless Apple's own links
  go there) and first among Search's browse categories, opens Apple Music's charts: **Top Songs** as a numbered list
  (click a song to play the chart from it; right-click for Play Next and the rest),
  **Top Albums** and **Top Playlists** as numbered tiles, the **Daily Top 100** playlists
  (the world's and each country's) and **City Charts** (a playlist for each of a number of
  cities), which open their pages, and **Top Music Videos**. The genre menu in its header
  bar (**All Genres** to start with) narrows the charts to a genre: its top songs, albums,
  playlists and music videos (the Daily Top 100 and City Charts are every genre's). A link
  on **New** to a genre's charts opens the page on that genre. The page always opens on all
  genres otherwise: the choice is not remembered. The charts, each genre's and the list of
  genres are kept for a day; the refresh button asks Apple again.
- **Artists** lists the artists in your library beside the one you choose: their albums in
  your library, newest first (**Sort By** for titles), with **Play** and **Shuffle** for all
  their songs. A song you added without its album shows as its album. Clicking an artist you
  have anywhere else (a song's artist, an album's) shows the same; their name at the top, or
  **Go to Artist** in a menu, opens their page on Apple Music, whose **In Your Library**
  leads back with **See All**. That page opens with Apple's wide picture of the artist, their
  name over it, when Apple has one (about half of its artists do), else with their round
  portrait; their latest release sits beside their top songs unless the window is narrow.
  The star beside **Play** makes the artist one of your favourites (Apple Music uses them for
  its recommendations; it does not add them to your library), and pressing it again takes
  that back; **Favourite** and **Remove from Favourites** in an artist's menu do the same.
  In a narrow window the list comes first, and choosing an
  artist shows their albums, with a back button.
- A title too long for its tile ends in "…": rest the pointer on the tile to read all of it.
  Music videos are wide tiles, with a play symbol under the pointer.
- Right-click a song, an album or a playlist (or press and hold it, or press
  <kbd>Menu</kbd>) for its menu: play it next or later, add it to a playlist or your
  favourites, open it on music.apple.com, and, for a song, **Go to Album** and **Go to
  Artist**; an artist's menu has **Favourite** too. **Suggest Less** (for a song, an album, a playlist, a station or a music video)
  tells Apple Music to recommend less like it; **Undo Suggest Less** takes that back. A
  favourite offers no Suggest Less, and **Favourite** replaces a Suggest Less. The song playing has the same menu: right-click the player bar, or use **More
  Options** in Now Playing; Up Next's songs have theirs too. A radio show or a category
  (Search's, New's) has only **Open in Browser** and **Copy Link**: it is a page to open,
  with nothing of its own to play or favourite.
- **View Credits** in a song's menu (a row's, the player bar's, Now Playing's **More
  Options**) shows who performed, wrote and produced it, as Apple Music lists them: a list
  for each, each person with their roles. Apple Music has no credits for a song of yours it
  does not have (an upload), so that has none; a song it has nothing for says so. The
  credits are kept for a day, so a song's open again without the engine; signed out or
  with the engine stopped, the dialog says what to do.
- **Create Station** in the menu of a song or an artist (on an artist's page, in **More
  Options**) plays a station of music like it at once, in place of what was playing. A song
  of yours that Apple Music does not have (an upload) has none, and neither has an artist
  of your library that the app has not matched to Apple Music. As on Apple's own players,
  a station's Up Next is the station's and cannot be changed.
- The **Lyrics** and **Up Next** buttons at the right of the player bar open Now Playing on
  that tab, and close it again when it shows that tab (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>L</kbd>
  and <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>U</kbd> do the same, from anywhere but a text
  field). Lyrics is greyed out for a song Apple Music has no lyrics for. In a narrow window
  the bar leaves them out to keep the song's title readable: click the bar and pick the tab.
  In a narrower window still, such as on a phone, the bar shows the artwork and the song
  first, then **Play** and **Next**; click it for Previous, the position and the rest.
- Now Playing takes on the colours of the song's artwork, faintly, and changes with each
  song. It stays light enough (or dark enough) for its text to read: with a cover that would
  not allow that, or with high contrast on, it keeps its plain background.
- Now Playing's **Up Next** lists the song playing, then what you queued (**Playing Next**),
  each with its cover. The **History** button (the clock at the top left of the list) shows
  the songs played before it in this queue instead, the most recent first: double-click one
  (or press <kbd>Enter</kbd>) to play it again. Leaving the tab goes back to Up Next.
  Right-click a song
  there (or press and hold it, or press <kbd>Menu</kbd>) and choose **Remove from Up Next**,
  or select it and press <kbd>Delete</kbd>. **Clear**, above the list, takes out everything
  after the song playing; **Undo** on the message that follows puts it back. **Autoplay**
  (the ∞ button beside Clear, also in Preferences › General › Playback) is on unless you
  turn it off: when the queue ends, Apple Music keeps playing similar songs, which Up Next lists under
  **Autoplay** (and which you can remove like any other). It is this app's setting: Apple's
  other players keep their own. While a station plays, its queue is Apple's and cannot be
  changed, and Autoplay does not start while Repeat is on.
- To change the order of Up Next, drag a song to its new place (a line shows where it will
  go), or choose **Move Up** or **Move Down** in its menu, or press
  <kbd>Alt</kbd>+<kbd>↑</kbd> or <kbd>Alt</kbd>+<kbd>↓</kbd> on the selected song. A song
  moves within its own list: what you queued stays under **Playing Next**, and Autoplay's
  songs stay under **Autoplay**, so a song of Autoplay's cannot be moved up among yours.
  On a touchscreen, dragging scrolls the list: press and hold a song and use **Move Up** or
  **Move Down**. The song playing and the History do not move, and nor does a station's
  queue.
- Now Playing's **Lyrics** follow the song when Apple Music has them timed: click a line to
  go to it. When Apple Music times them word by word, each word of the line being sung
  fills in as it is sung (with animation effects turned off in Settings, each word lights
  whole). Where the music plays on without words for a while, before the first verse or
  between two, three dots fill in until the singing comes back. Background vocals, such
  as echoes, show under their line, smaller. In a duet
  each singer's lines keep to a side of their own, and lines sung together sit in the
  middle. When Apple Music has translations or pronunciations for a song's lyrics, the
  translation button (beside the Fullscreen button) offers **Show Translations**, each
  line's meaning in your language under it, and **Show Pronunciations**, how a line in another script,
  such as Japanese or Korean, is pronounced, written in the script of your language (Latin
  letters for English). Each stays on for the songs after until you turn it off. The lyrics
  have no scrollbar: scroll them with the mouse wheel, the touchpad or a finger, or move
  from line to line with the arrow keys; they fade out at the top and the bottom where
  there is more (with high contrast on, the edges stay sharp).
- **Fullscreen** (the button beside the translation button in Now Playing, or <kbd>F11</kbd>
  while something plays) fills the screen with the song playing: its artwork large over its
  own colours, the controls, and the lyrics beside it, larger. When the pointer rests for a
  few seconds while the music plays, the controls and the pointer fade away; move the
  pointer or press a key to bring them back. <kbd>Esc</kbd>, <kbd>F11</kbd> or **Leave
  Fullscreen** goes back to the window as it was. It stays from one song to the next, and
  closes on its own when nothing plays any more.
- A playlist's or a folder's row in the sidebar has the same menu as **More Options** on
  its page: right-click it, press and hold it, or press <kbd>Menu</kbd> (or
  <kbd>Shift</kbd>+<kbd>F10</kbd>) on the focused row. **All Playlists** has **New
  Playlist…** and **New Folder…**.
- Your own playlists can be managed from their menus (right-click one in the sidebar or on
  All Playlists, or use **More Options** on its page): **Rename…** changes its name and
  description, **Delete Playlist…** deletes it from your library on all your devices, after
  asking. A song's menu on one of your playlists has **Remove from Playlist**, which takes out
  that one entry (the same song elsewhere in the playlist stays); <kbd>Delete</kbd> on the
  focused song does the same, with **Undo** in the message that follows, and the focus moves
  to the song that took its place (while selecting songs, <kbd>Delete</kbd> takes out the
  songs selected). **Duplicate** in a playlist's menu (any in your library, Favourite Songs
  too) makes a playlist of your own with the same songs in the same order, named "… Copy",
  beside it, and opens it. **New Playlist…** is at the
  end of **Add to Playlist** (a new playlist holding that song), in a folder's menu, in the
  main menu (<kbd>Ctrl</kbd>+<kbd>N</kbd>), and is the **+** button of All Playlists and of a folder's page. A folder's menu
  also has **Rename…** and **Delete Folder…**, which deletes the playlists in it too.
  Favourite Songs and Apple's playlists in your library cannot be renamed or deleted;
  Apple's playlists can be removed from your library instead (below). A change takes a few
  seconds to reach the library's listing, as Apple lists it.
- A playlist of your own can be put in a new order on its page: drag a song up or down the
  list (a line shows where it will go, and the list scrolls when you drag near its top or
  bottom), or use **Move Up** and **Move Down** in the song's menu, or
  <kbd>Alt</kbd>+<kbd>↑</kbd> and <kbd>Alt</kbd>+<kbd>↓</kbd> on the focused song. The song
  moves at once and the new order goes to Apple: a drop at once, the keys a moment after the
  last press, so a run of them is one change. The toast that follows has **Undo**. If Apple
  refuses, or the playlist changed on another device in the meantime, the song goes back to
  where Apple has it and the app says why: try again on the order shown. A click on a song
  still plays it; only a drag moves it. Favourite Songs and Apple's playlists keep their
  order. Up Next does not change when you reorder the playlist that is playing: the next time
  you play it, it plays in the new order. In the demo library a move shows but is not kept.
- **Sort By**, the button beside the filter in a playlist's header bar, shows its songs by
  title, artist, album or time, either way round, or back in **Playlist Order**. It changes
  only what the page shows: the playlist keeps its order, plays in it from Play, and is
  duplicated in it. While another order shows, songs cannot be moved. The page keeps the
  order you chose while it stays open; a playlist opened again shows its own order.
- **Add Songs…** in the menu of one of your playlists (and the button of an empty one) opens
  a dialog to pick songs for it: **Your Library** lists all your songs, narrowed as you type,
  and **Apple Music** searches the catalogue for what you type. Click a song, or press
  <kbd>Enter</kbd> on it, to pick it or unpick it; picks from both stay as you search again,
  and the header bar counts them. **Add** puts them at the end of the playlist, in the order
  you picked them, in one change. <kbd>Enter</kbd> in the search moves to the first song;
  <kbd>Esc</kbd> or **Cancel** closes the dialog, adding nothing (in the search,
  <kbd>Esc</kbd> first clears what you typed).
- Playlist folders: **New Folder…** is in the main menu, in a folder's menu (a folder inside
  it) and in All Playlists' menu, and is the folder button beside the **+** of All Playlists
  and of a folder's page. A playlist's menu (in the sidebar, on its tile, or **More Options**
  on its page) has **Move to Folder**: the folders it can go into, in one list (a folder
  inside another is named after both, "Evenings › Late Night"), and **New Folder…**, a new
  folder beside it with the playlist inside. Or drag the playlist's row in the sidebar, or its
  tile in All Playlists or a folder's page, onto a folder in the sidebar: the folder lights
  up when it can take it, a closed folder opens when you hold the drag over it, and the
  sidebar scrolls when you drag near its top or bottom. The playlist moves at once; if Apple
  refuses, it goes back and the app says why. The toast after a move has **Undo**.
- **Add to Playlist** lists your playlists that take songs: those at the top level, then
  each folder's under the folder's name. In an album's or a playlist's menu (on its tile,
  or **More Options** on its page) it adds all its songs, in order, to the playlist you
  choose; **New Playlist…**
  at its end makes one of them, named after the album or playlist. One message says how many
  were added. Or drag the album's or playlist's tile (or a playlist's row in the sidebar)
  onto a playlist in the sidebar. An album or playlist from Apple Music's catalogue has its
  songs read first, which takes a moment.
- Drag a song, a music video, an album or a playlist onto the player bar to add it to Up
  Next: it plays after everything already there, as **Play Later** does, or right after the
  song playing if you hold <kbd>Shift</kbd> as you drop it, as **Play Next** does. The bar
  lights up while it can take what you drag (a folder cannot be queued); it is there only
  while something plays. Drag songs, music videos or an album onto **All Playlists** in the
  sidebar to make a new playlist of them: the New Playlist dialog opens with the first one's name
  filled in, and once Apple lists the new playlist, its page opens. The menus do the same
  from the keyboard: **Play Later**, **Play Next**, and **Add to Playlist › New
  Playlist…**.
- To act on several songs at once, select them: on Songs, an album's page or a playlist's
  page (Favourite Songs too), click the **Select** button in the header bar, or
  <kbd>Ctrl</kbd>+click or <kbd>Shift</kbd>+click a song. Each song gets a check box: a
  click (or <kbd>Space</kbd> on the focused song) selects or unselects it,
  <kbd>Shift</kbd>+click (or <kbd>Shift</kbd>+<kbd>Space</kbd>) selects every song from the
  last one you clicked, <kbd>Ctrl</kbd>+<kbd>A</kbd> selects them all and
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd> none (also in the menu of the header bar's
  "3 Selected"). The bar at the bottom then has **Play Next**, **Play Later**, **Add to
  Playlist** (or a **New Playlist…** of them), **Remove from Playlist** on one of your
  playlists (one change, with **Undo** in the message that follows) and **Remove from
  Library…** (asking once for them all); in a narrow window some are under its **⋮** menu.
  Drag a selected song to drag them all, onto a playlist in the sidebar or the player bar.
  A filter keeps only the selected songs it still shows. **Cancel**, <kbd>Esc</kbd> or any of
  the bar's actions ends selecting. Without selecting, a click on a song still plays it.
- **Remove from Library…** in the menu of a song, an album or a music video in your library,
  or of one of Apple's playlists you added, takes it out of your library on all your
  devices, after asking. A song goes from every playlist that held it too, and an album
  with its songs. It leaves the app's pages at once; if Apple refuses, it comes back and a
  message says why. (Your own playlists are deleted with **Delete Playlist…** instead.)
- The Activities overview's search finds your albums, artists, playlists and songs (songs
  once the running app has listed them: after a visit to Songs, or a library search in
  the app): choosing one opens its page, or plays the song; the Music Sleeve heading above
  the results opens the app's Search page with what you typed. A search while the app is not running starts it in the background,
  without a window or Chrome, until you choose a result. Settings › Search lists Music
  Sleeve among the providers: turn it off there to keep your library out of the overview.
- <kbd>Ctrl</kbd>+<kbd>L</kbd> (Go to Current Song) shows the album or playlist the song
  playing is played from (else the song's album), the focus on the song, from Now Playing
  and the full-screen player too; a filter on the playlist that hides the song is cleared.
  <kbd>Ctrl</kbd>+<kbd>↑</kbd> and
  <kbd>Ctrl</kbd>+<kbd>↓</kbd> turn the volume up and down while something plays (not while
  you type, or on the sidebar or a slider, where those keys are theirs).
- <kbd>Ctrl</kbd>+<kbd>?</kbd> lists every keyboard shortcut.
- Because the sound comes from Chrome, the system's per-app volume controls list it as Chrome.

## Known limitations

Music Sleeve plays your music through Apple's web player, music.apple.com, running in Chrome:
Apple Music's streams are protected with Widevine, and a browser that has it is the only
way to play them on Linux. So what the web player cannot do, the app cannot do either:

- No Lossless, Hi-Res Lossless or Dolby Atmos (Spatial Audio): the web player streams AAC
  at up to 256 kbps, in stereo, and that is what you hear (Preferences › Engine › Streaming
  Quality chooses 256 or 64 kbps). For the same reason, albums carry
  no Lossless or Dolby Atmos badges.
- No equaliser, crossfade, AutoMix or Sound Check: the web player has none of them. An
  equaliser for the whole system, such as EasyEffects, can work on the sound instead (the
  system lists it as Chrome's).
- No offline listening or downloads: the app streams, as the web player does.
- No Apple Music Sing, lyrics share cards, profiles or friends, collaborative playlists,
  making smart playlists, or artwork of your own for a playlist: the web player offers no
  way to them, so they stay in Apple's own apps.

Other limits:

- Songs play only in a browser with Widevine: Google Chrome has it. Microsoft Edge, Brave
  and Vivaldi can fetch it (Brave and Vivaldi may ask first, in their own window: turn off
  Preferences › Engine › Browser › Run Browser Hidden to see it), and Chromium needs its
  distribution's Widevine package. Only Google Chrome is tested. A snap cannot be the
  engine. Changing browser may mean signing in again.
- Music videos play as audio only: the engine has no window to show them in.
- An album's shelves and its release date and ℗ line need the engine and your sign-in (or a
  day-old copy of them): without them, or for an album Apple Music no longer has, the page
  shows the songs and their count alone. Songs you added without their album, which show as
  an album of their own, have no shelves.
- Radio's shelves need the engine and your sign-in (or the last copy of them): without them
  the page shows only the stations you played recently, or says what is missing. Apple's
  links at the end of its radio page (More to Explore, the genres) are not shown.
- The charts are your storefront's. Like New and the pages its links open, they need the
  engine and your sign-in (or the last copy of them); a genre you have not opened before
  needs them too, and without the list of genres the genre menu is not shown.
- A playlist moves into a folder, but not yet out of every folder to the top level, and a
  folder does not move into another folder: Apple's service has not been seen to take those
  moves from the app yet, so it does not offer them. Apple's own apps can.
- One Apple Account per build: a release install and a development build each have their own
  Chrome profile, cache and sign-in, so each is signed in and synced on its own.
- The account's name next to the avatar is read from Apple's web page and may stay
  "Signed In" when the page does not show it.
- The song you last listened to comes back at launch only as Apple still has it: a song
  since removed from your library, or not available any more in your country or region,
  is left out of the queue when you press **Play**, and the rest plays. When that song is
  the one you were listening to, or Apple refuses the whole queue, nothing comes back, and
  a message says why. Where the app ended without quitting (a crash, the computer switched off), it
  comes back up to half a minute earlier in the song. A queue of more than 250 songs comes
  back as the 250 around the song, unless it is still an album or playlist as it was
  started, which comes back whole.
- The hearts are as the last library refresh found them, and as you change them here. A
  favourite changed in another app shows here after the next refresh (or when you open its
  menu); one changed here and then the app restarted before a refresh may show its old
  state until then.
- Apple Music gives no date for a single song added to the library, so Songs cannot be
  sorted by date added, and a song added without its album comes last in Recently Added.

## Troubleshooting

- **"Install Google Chrome to play Apple Music."** No browser was found: neither Google
  Chrome nor another Chromium-based browser. Install Google Chrome, or name another
  browser's command in Preferences › Engine › Browser › Browser program.
- **"This browser cannot play songs; Google Chrome can."** The browser the engine runs in
  has no Widevine, which the songs are protected with: browsing, your library and the
  30-second previews work, but songs do not play. Install Google Chrome and name it in
  Preferences › Engine › Browser › Browser program (`google-chrome-stable`), or give the
  browser its Widevine module.
- **"The playback engine stopped."** Chrome exited or its page stopped answering. The
  player bar keeps the song, paused where it stopped, with Up Next (a radio station stays,
  stopped): **Play** starts the engine again and carries on. Click **Restart** in the
  message to start it without playing, or just play something else.
- **"Unlock the keyring, then start the engine."** Chrome keeps the key that encrypts its
  sign-in in your keyring (GNOME Keyring or KWallet's Secret Service), and none answered on
  the session bus, so the app did not start Chrome: without that key, Chrome would delete
  the sign-in. Make sure the keyring is running and unlocked, then click **Start**.
- **"Your Apple Music sign-in has expired."** Apple ended the session: click **Sign In** on
  that banner, or **Sign In Again** in the account menu at the bottom of the sidebar.
- **Discord shows nothing.** Check that the setting is on and that the Discord desktop app is
  running (Discord installed as a Flatpak or a Snap is found too), and that Discord's own
  Settings › Activity Privacy › Share your detected activities with others is on. Discord
  learns of a track when it starts or changes, so after starting Discord, give it until the
  next track.
- **Something else.** Run `music-sleeve --debug` from a terminal and look at what it logs (no
  password or tokens are logged). Preferences › Engine shows whether the engine is running;
  turning off **Run Browser Hidden** shows Chrome's window at the next start.
- **Starting over.** Sign Out deletes the sign-in and the cache; the commands under "Where your
  data lives" remove everything.

## Privacy

- The app itself talks only to Apple: the music.apple.com page in its Chrome (and the Apple
  services that page uses), and artwork it downloads directly from Apple's servers. No
  telemetry, analytics or crash reports.
- With Discord presence on, and only then, the app also tells the Discord app running on your
  computer what is playing: the title, the artist, the album and the address of the album's
  cover on Apple's servers. Discord shows these on your profile, to the people who can see your
  activity there, and fetches the cover itself. Nothing of your account is sent: no Apple ID,
  no library, no playlists.
- Chrome, as the engine, also talks to Google the way any Chrome does, for example to update
  its components (the Widevine module among them) and for Safe Browsing. The app does not turn
  these off.
- The app never sees your Apple Account password: you sign in on Apple's own page, and the
  session lives in the app's own Chrome profile, apart from your everyday browser's.
- The app controls Chrome through a private pipe, with no network port that other programs
  could use. A developer can open a port with the `APPLE_MUSIC_DEBUG_PORT` environment
  variable, but while it is set any program on the computer can control the signed-in
  session: never set it for everyday use.

## Where your data lives, and how to remove it

| What | Where |
|---|---|
| The library snapshot, artwork, lyrics, cached pages, Recently Searched and the last session (the queue the player bar shows at launch) | `~/.cache/apple-music/` |
| Chrome's profile, which holds your Apple sign-in | `~/.local/share/apple-music/chrome/` |
| Settings | GSettings schema `io.github.jackicus.MusicSleeve` |

(`~/.cache` and `~/.local/share` stand for `$XDG_CACHE_HOME` and `$XDG_DATA_HOME`.) The
development build uses `~/.local/share/apple-music/chrome-devel/` and
`~/.cache/apple-music-devel/` instead, and settings of its own for the account.

- **Sign Out** (in the account menu at the bottom of the sidebar) signs out of Apple Music,
  asking Apple to end the session too, stops Chrome and deletes both the Chrome profile and
  the cache. Nothing of the account stays on screen either: the next account signed in
  starts with its own Recently Played, favourites and Recently Searched.
- **Preferences › General › Library › Cache › Clear…** deletes only the cache.
- To remove everything by hand, quit the app first, then run:

  ```bash
  rm -r ~/.cache/apple-music ~/.local/share/apple-music
  gsettings reset-recursively io.github.jackicus.MusicSleeve
  ```
