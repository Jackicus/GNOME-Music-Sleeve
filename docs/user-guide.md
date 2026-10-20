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

- The app starts Chrome, its playback engine, whenever it starts. Preferences › Engine › Start
  Engine on Launch turns that off; the first thing you play then starts it.
- The app opens with the song you last listened to in the player bar, paused where it
  stopped, and Up Next as it was: **Play** carries on from that second. Before you press it,
  the previous and next buttons and the slider move through it without playing; a song in
  Up Next plays from its start. The queue comes back in its order with Shuffle off (turn it
  on to shuffle what follows), and with Repeat as it was. A radio station comes back as the
  station, live. The system's media controls show the song paused too. Signing out or
  clearing the cache forgets it.
- While the engine runs, the library is refreshed when the last refresh is older than the
  interval chosen in Preferences › General › Library › Refresh Library (every hour, every
  6 hours, the default, every day, or manually). Last Refreshed beneath says when it last was;
  its Refresh button, or <kbd>Ctrl</kbd>+<kbd>R</kbd>, refreshes it at any time.
- Closing the window quits the app and stops Chrome. To keep the music playing with the window
  closed, turn on Background Playback in Preferences (<kbd>Ctrl</kbd>+<kbd>,</kbd>); the
  system's media controls bring the window back.
- Preferences › General › Playback › Discord Presence puts the song playing on your Discord
  profile, as "Listening to Apple Music" with the title, the artist, the album and its cover,
  and the artist in the status under your name. It is off until you turn it on, and it needs
  the Discord desktop app running on the same computer (the web client cannot be reached).
  Discord shows it only while something plays: pausing stops the clock and, five seconds
  later, takes it off until the music plays again, as playback ending or the app quitting
  does.
- Search shows what you opened from it lately under **Recently Searched**, above the browse
  categories; **Clear** empties it. The list stays on this computer, as music.apple.com keeps
  its own in the browser, and goes with the cache (Clear Cache, signing out).
- On the Songs page, just start typing to filter the songs (or press
  <kbd>Ctrl</kbd>+<kbd>F</kbd>, or click the search button in the header bar);
  <kbd>Esc</kbd> clears the filter. Click a column title to sort by it, or use **Sort By**.
- In a wide window a playlist's songs are a table, as the Songs page is: click an artist
  or an album there to open its page.
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
- **Artists** lists the artists in your library beside the one you choose: their albums in
  your library, newest first (**Sort By** for titles), with **Play** and **Shuffle** for all
  their songs. A song you added without its album shows as its album. Clicking an artist you
  have anywhere else (a song's artist, an album's) shows the same; their name at the top, or
  **Go to Artist** in a menu, opens their page on Apple Music, whose **In Your Library**
  leads back with **See All**. In a narrow window the list comes first, and choosing an
  artist shows their albums, with a back button.
- A title too long for its tile ends in "…": rest the pointer on the tile to read all of it.
  Music videos are wide tiles, with a play symbol under the pointer.
- Right-click a song, an album or a playlist (or press and hold it, or press
  <kbd>Menu</kbd>) for its menu: play it next or later, add it to a playlist or your
  favourites, open it on music.apple.com, and, for a song, **Go to Album** and **Go to
  Artist**. The song playing has the same menu: right-click the player bar, or use **More
  Options** in Now Playing; Up Next's songs have theirs too.
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
- Now Playing's **Lyrics** follow the song when Apple Music has them timed: click a line to
  go to it. When Apple Music times them word by word, each word of the line being sung
  fills in as it is sung (with animation effects turned off in Settings, each word lights
  whole). Where the music plays on without words for a while, before the first verse or
  between two, three dots fill in until the singing comes back. Background vocals, such
  as echoes, show under their line, smaller. In a duet
  each singer's lines keep to a side of their own, and lines sung together sit in the
  middle. When Apple Music has translations or pronunciations for a song's lyrics, the
  translation button (beside the volume) offers **Show Translations**, each line's meaning
  in your language under it, and **Show Pronunciations**, how a line in another script,
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
- Your own playlists can be managed from their menus (right-click one in the sidebar or on
  All Playlists, or use **More Options** on its page): **Rename…** changes its name and
  description, **Delete Playlist…** deletes it from your library on all your devices, after
  asking. A song's menu on one of your playlists has **Remove from Playlist**, which takes out
  that one entry (the same song elsewhere in the playlist stays). **New Playlist…** is at the
  end of **Add to Playlist** (a new playlist holding that song), in a folder's menu, in the
  main menu, and is the **+** button of All Playlists and of a folder's page. A folder's menu
  also has **Rename…** and **Delete Folder…**, which deletes the playlists in it too.
  Favourite Songs and Apple's playlists in your library cannot be renamed or deleted;
  Apple's playlists can be removed from your library instead (below). A change takes a few
  seconds to reach the library's listing, as Apple lists it.
- Playlist folders: **New Folder…** is in the main menu, in a folder's menu (a folder inside
  it) and in All Playlists' menu, and is the folder button beside the **+** of All Playlists
  and of a folder's page. A playlist's menu (in the sidebar, on its tile, or **More Options**
  on its page) has **Move to Folder**: the folders it can go into, and **New Folder…**, a new
  folder beside it with the playlist inside. Or drag the playlist's row in the sidebar, or its
  tile in All Playlists or a folder's page, onto a folder in the sidebar: the folder lights
  up when it can take it, a closed folder opens when you hold the drag over it, and the
  sidebar scrolls when you drag near its top or bottom. The playlist moves at once; if Apple
  refuses, it goes back and the app says why. The toast after a move has **Undo**.
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
- <kbd>Ctrl</kbd>+<kbd>?</kbd> lists every keyboard shortcut.
- Because the sound comes from Chrome, the system's per-app volume controls list it as Chrome.

## Known limitations

Music Sleeve plays your music through Apple's web player, music.apple.com, running in Chrome:
Apple Music's streams are protected with Widevine, and a browser that has it is the only
way to play them on Linux. So what the web player cannot do, the app cannot do either:

- No Lossless, Hi-Res Lossless or Dolby Atmos (Spatial Audio): the web player streams AAC
  at up to 256 kbps, in stereo, and that is what you hear. For the same reason, albums carry
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
  Preferences › Engine › Run Browser Hidden to see it), and Chromium needs its
  distribution's Widevine package. Only Google Chrome is tested. A snap cannot be the
  engine. Changing browser may mean signing in again.
- Music videos play as audio only: the engine has no window to show them in.
- An album's shelves and its release date and ℗ line need the engine and your sign-in (or a
  day-old copy of them): without them, or for an album Apple Music no longer has, the page
  shows the songs and their count alone. Songs you added without their album, which show as
  an album of their own, have no shelves.
- Reordering a playlist's songs happens in Apple's own apps.
- A playlist moves into a folder, but not yet out of every folder to the top level, and a
  folder does not move into another folder: Apple's service has not been seen to take those
  moves from the app yet, so it does not offer them. Apple's own apps can.
- One Apple Account per build: a release install and a development build each have their own
  Chrome profile, cache and sign-in, so each is signed in and synced on its own.
- The account's name next to the avatar is read from Apple's web page and may stay
  "Signed In" when the page does not show it.
- The song you last listened to comes back at launch only as Apple still has it: a song
  since removed from your library, or not available any more in your country or region,
  leaves it out (or, when Apple refuses the whole queue, nothing comes back, and a message
  says why). Where the app ended without quitting (a crash, the computer switched off), it
  comes back up to half a minute earlier in the song. A queue of more than 250 songs comes
  back as the 250 around the song, unless it is still an album or playlist as it was
  started, which comes back whole.

## Troubleshooting

- **"Install Google Chrome to play Apple Music."** No browser was found: neither Google
  Chrome nor another Chromium-based browser. Install Google Chrome, or name another
  browser's command in Preferences › Engine › Browser program.
- **"This browser cannot play songs; Google Chrome can."** The browser the engine runs in
  has no Widevine, which the songs are protected with: browsing, your library and the
  30-second previews work, but songs do not play. Install Google Chrome and name it in
  Preferences › Engine › Browser program (`google-chrome-stable`), or give the browser its
  Widevine module.
- **"The playback engine stopped."** Chrome exited or its page stopped answering. Click
  **Restart** in the message, or just play something.
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
  the cache.
- **Preferences › General › Cache › Clear** deletes only the cache.
- To remove everything by hand, quit the app first, then run:

  ```bash
  rm -r ~/.cache/apple-music ~/.local/share/apple-music
  gsettings reset-recursively io.github.jackicus.MusicSleeve
  ```
