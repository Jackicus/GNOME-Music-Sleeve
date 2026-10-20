# The backend

Everything that reaches Chrome, MusicKit or Apple's API, below the app's `Engine`
(`src/engine.py`). The standard library and asyncio only: nothing here imports gi
(`tests/test_backend.py` checks), and importing the package imports none of its modules. The
app reaches Chrome only through the Engine; other modules may import the pure parts (`api`,
`config`, `errors`, `normalize`, `store`).

## What is here

| File | What it holds |
|---|---|
| `errors.py` | `EngineError(code, message, status=None, musickit_code=None)`, the one error that leaves the backend, and its codes |
| `api.py` | the Apple Music API apart from any connection: library ids, an item's endpoint, resource types, the endpoints the pages use, Apple's `{errors}` answers as an `EngineError` (`api_error()`), and which failures are final (`is_final()`) |
| `chrome.py` | finding Chrome (`find_chrome()`), its argv (`chrome_args()`: `--remote-debugging-pipe`, `--headless=new`, an `--app=` window when visible; `flatpak-spawn --host` from a Flatpak sandbox), its environment (`chrome_environment()`: the session bus of `APPLE_MUSIC_HOST_SESSION_BUS`), whether a profile's `Local State` records the keyring's key (`profile_used_keyring()`), which Chrome holds a profile (`profile_owner()`, from its `SingletonLock`), `select_page()`, and `get_json()` for the developer attach |
| `client.py` | the transports (`PipeTransport`, Chrome's DevTools pipe on its descriptors 3 and 4; `WebSocketTransport`, a DevTools port) and `CDPClient`: one asynchronous CDP connection attached to the music.apple.com page, its calls, events, and the bridge kept in the page across navigations |
| `cdp.py` | the RFC 6455 handshake and frame codec as pure functions, for `WebSocketTransport`, and `exception_message()`, a page's JavaScript exception in one line |
| `bridge.js` | the only code that runs in the page: `window.__appleMusicLibrary` over the page's MusicKit instance, and MusicKit's events posted through the `__amEvent` binding |
| `normalize.py` | Apple's answers as the library's Item, Track and shelf shapes; the artwork cache (naming, fetching, pruning); library.json; the kept answers; `prune_caches()` |
| `store.py` | every write into the cache: `atomic_write()` / `atomic_create()`, the cache's generation (`cache_generation()`, `bump_cache_generation()`), `CacheGone` and `Cancelled` |
| `config.py` | the cache and profile directories for each build profile, the developer's DevTools port, Chrome's session bus when the app runs on another (`host_session_bus()`), the artwork sizes, `BRIDGE_JS` |

## Error codes

`backend/errors.py`; `src/errors.py`'s `error_message()` gives each one its sentence and button.

| Code | Meaning |
|---|---|
| `engine-down` | Chrome is not running, exited, or the connection closed (also every command in demo mode) |
| `no-browser` | no Chromium-based browser to run, or it could not be started |
| `no-widevine` | the browser runs but cannot decrypt Widevine (its page's `drm()` said so): `play()` and `queueJump()` refuse, since no song would play |
| `no-keyring` | the keyring that encrypts the profile's sign-in is not reachable on Chrome's session bus: Chrome was not started, as it would delete the sign-in |
| `not-signed-in` | MusicKit is not authorized |
| `api` | Apple, MusicKit or the page said no (`status`: Apple's HTTP status; `musickit_code`: MusicKit's code for a refused play) |
| `timeout` | Chrome or the page took too long |
| `usage` | a bad argument (`scripts/am.py`) |

## The bridge

`client.load_bridge()` injects `bridge.js` with its hash as `__appleMusicLibraryWanted`: the same
file injected twice is a no-op, a changed one replaces the old. `CDPClient.bridge(name, *args)`
calls `window.__appleMusicLibrary.<name>(...)`; the Engine's commands are thin calls into these.

| Call | Answer |
|---|---|
| `status()` | `{ready, engine, authorized, storefront, bitrate}` |
| `drm()` | `{widevine: true}`, or `{widevine: false, error}` when the browser refuses Widevine (`navigator.requestMediaKeySystemAccess`, AAC in MP4) or has no Encrypted Media Extensions; never a throw |
| `accountName()` | the account's name as the page shows it (`.account-menu .user__name`), or null; null while a sign-in control is on the page |
| `signin()` | `mk.authorize()`, then `{authorized}` |
| `signout()` | `mk.unauthorize()`, which revokes the session at Apple's end: `{ok: true}` or `{error}`, never a throw |
| `api(path, params, options)`, `apiAll(paths)` | the API's answer body (`mk.api.music()`); `apiAll` answers null in place of a failed read |
| `play(kind, id, {startWith, startId, shuffle, startTime, paused})` | `{ok: true}` (with `moved: {from, to}` when the queue held another item than `startId` at `startWith` and was moved to it, and `sought: true` when it sought to `startTime` itself), or `{error, code}` when MusicKit refuses. `kind`: `album playlist station song musicVideo artist songs` (`songs`: ids joined by commas; `artist`: its top songs, else its station). `shuffle` true turns shuffle on, false off, null leaves it. `startTime` (seconds: a restored session's position) goes to `setQueue`, and once the item plays, when MusicKit began it more than 2 s earlier and it is `startId`'s, a `seekToTime` follows. `paused` queues it without playing or moving it (`startPlaying: false`); the start time then waits for the next `control('play')` or `'toggle'` (a `pause` keeps it, anything else gives it up) |
| `playNext(kind, id)`, `playLater(kind, id)` | `{ok: true}` |
| `control(action)` | `play pause toggle next previous stop`: `{ok: true}` |
| `seek(seconds)` | `{ok: true}` |
| `volume(level)` | `{volume}`: MusicKit's level after the set (0 to 1; the page keeps it) |
| `shuffle(on\|off\|toggle)`, `repeat(none\|one\|all\|cycle)` | `{shuffle, repeat}` |
| `nowPlaying()` | `{state, track, position, duration, shuffle, repeat, volume}`; `state` is MusicKit's `PlaybackStates` name |
| `queue()` | `{index, items: [Track]}` |
| `queueJump(index)` | `{ok: true}` (`mk.changeToMediaAtIndex`) |
| `rating(kind, id, value)`, `addToLibrary(kind, id)`, `addToPlaylist(playlistId, songId, type)` | `{ok: true}`, or a throw with Apple's status and message. Writes go through `mk.api.client.createRequest(...).send()`: Apple answers them 202 or 204 with no body, which `music()` cannot read (a body Apple does send comes back as `data`) |
| `createPlaylist(attributes, tracks, parentId)` | `{id}`, the new playlist's; `attributes` `{name, description?}`, `tracks` `[{id, type}]` |
| `removeFromLibrary(type, id)` | `{ok: true}`, or a throw as above: `DELETE /v1/me/library/<type>/<id>` (below) |
| `libraryHas(type, id)` | `{has}`: `GET /v1/me/library/<type>/<id>` through the request builder (a read that must see a removal), `has` false for Apple's 404; a throw for any other failure |
| `updatePlaylist(id, attributes)`, `deletePlaylist(id)`, `removeFromPlaylist(id, type, trackId)`, `replacePlaylistTracks(id, tracks)`, `updateFolder(id, attributes)`, `deleteFolder(id)` | `{ok: true}`, or a throw as above (the requests below) |
| `createFolder(attributes, parentId)` | `{id}`, the new folder's; `attributes` `{name}`, `parentId` the folder it goes in (none: the top level) |
| `moveToFolder(type, id, folderId)` | `{ok: true}`: the playlist (`type` `library-playlists`) or folder (`library-playlist-folders`) into the folder `folderId` (`p.playlistsroot` for the top level), the web player's `requestMoveToFolder` |
| `lyrics(catalogSongId, languages)` | `{synced, lines: [Line]}`, the TTML read with the page's XML parser (`parseTtmlLyrics`). A Line is `{startMs, endMs, text, stanza?, words?, background?, backgroundWords?, agent?, pronunciation?, pronunciationWords?, pronunciationBackground?, pronunciationBackgroundWords?, translation?, translationBackground?}`, empty fields left out: `stanza: true` on a verse's first line (each `<div>`); `text` the main vocals, `background` the `<span ttm:role="x-bg">` (parentheses and all), each with its spaces run together; with `itunes:timing="Word"` on the root, `words` and `backgroundWords` are their timed `<span>`s as `[{startMs, endMs, text}]`, each piece's text with the space after it, so the pieces join to the text (a piece without one is a syllable joined to the next); `agent` the `<p>`'s (or its `<div>`'s) `ttm:agent`, kept only when some line's is not `v1`. src/lyrics.py's docstring has the shape, and engine.lyrics_answer checks it. music.apple.com's request (checked against the API on 2026-10-19): `/v1/catalog/<sf>/songs/<id>/syllable-lyrics?extend=ttmlLocalizations&l[lyrics]=<languages.lyrics>&l[script]=<languages.script>` (`api.lyrics_languages()`: `en-GB`, `en-Latn`), whose `attributes.ttmlLocalizations` is the TTML with `<head><metadata><iTunesMetadata><transliterations><transliteration xml:lang="ja-Latn"><text for="L1">…` and `<translations><translation xml:lang="en-US"><text for="L1">…`: a line's `pronunciation` and `translation` are the `<text>` its `itunes:key` names, split and (the transliteration's) timed as the line is, and dropped when they are the line itself. Its lines are the plain `/lyrics`' (which ignores those parameters); that is asked when syllable-lyrics fails |
| `search(term, limit)`, `suggest(term, limit)`, `searchLanding()`, `category(id)` | the API's answer, shaped by `normalize.search_results()`, `search_suggestions()`, `search_landing()`, `category_page()` |
| `playlistSuggestions(playlistId, limit, offered, selected, previewed)` | `{results: {suggested: [songs]}}`, the songs Apple suggests adding to a library playlist, shaped by `normalize.playlist_suggestions()`: music.apple.com's own request (checked against the API on 2026-10-08), `POST /v1/me/recommendations/suggested?contexts=playlist-suggested-songs&types=songs&limit=<limit>` with `{targetContent: {id, type: 'library-playlists'}}`, through the request builder (`music()` sends no body); up to `limit` (20 by default) full catalog songs. With `offered` (catalog ids shown) or `selected` (those added) the body also carries `offered: {suggested: [{id, type: 'songs', meta: {impressed: true, previewed}}]}` (`previewed` true for the ids in `previewed`, those whose preview was played) and `selected: [{id, type: 'songs', meta: {source: 'suggested'}}]`, as the web player's Refresh sends them; Apple then answers none of the offered songs (checked 2026-10-08) |
| `preview(id, url)` | `{ok: true, id}` once Apple's 30-second clip of a song (`url`, https: the song's `previews[0].url`, kept as `previewUrl`) plays, or `{error, code}` (`NO_PREVIEW` for no https address, else the media error's name, such as `NotAllowedError`). MusicKit is paused first and its queue left alone: the clip plays in an `Audio` element of the page's own, at MusicKit's volume (`volume()` sets both), one at a time. `play()` and every `control()` stop it, and so does MusicKit playing again (`previewDidChange` follows each start and end) |
| `stopPreview()` | `{stopped}`: whether a preview was playing |
| `subscribe()`, `unsubscribe()` | MusicKit's listeners on or off, once per instance |

### The playlist writes

Found in music.apple.com's own code (its `requestCreateNewPlaylist`,
`requestUpdatePlaylist`, `requestRemoveFromPlaylist`, `requestUpdatePlaylistTracks`,
`requestMoveToFolder` and `requestDeleteFromLibrary`) and checked against a real account on
2026-10-03, on playlists and folders made for the check and deleted after it:

| Request | Apple's answer |
|---|---|
| `POST /v1/me/library/playlists` `{attributes: {name, description?}, relationships: {tracks: {data: [{id, type}]}, parent: {data: [{id, type: 'library-playlist-folders'}]}}}` | 201 with the new playlist; both relationships may be left out (an empty playlist at the top level). Listed by the listings 4 to 6.5 s later |
| `PATCH /v1/me/library/playlists/<id>` `{attributes: {name?, description?}}` | 204; either attribute alone; listed within a second |
| `DELETE /v1/me/library/playlists/<id>/tracks?ids[library-songs]=<id>&mode=all` | 204: every entry of that song goes. The tracks of a library playlist are `library-songs` (or `library-music-videos`) by the song's own `i.` id, and carry no id of the entry |
| `PUT /v1/me/library/playlists/<id>/tracks` `{data: [{id, type}]}` | 204: the list replaced whole, in that order (the web player's reorder); one entry of a song held twice is removed so |
| `DELETE /v1/me/library/playlists/<id>` | 204. A playlist is still listed for minutes after, nameless (`api.is_deleted`), and a second DELETE is a 500 |
| `PUT /v1/me/library/playlists/<id>/parent` `{data: [{id: <folder>, type: 'library-playlist-folders'}]}` | 204: moved into the folder (Move to Folder, a drop on a sidebar folder) |
| `PUT /v1/me/library/playlists/<id>/parent` with Apple's root folder, `p.playlistsroot` | Not checked yet: the app does not offer it (`api.MOVE_TO_TOP_LEVEL` off) |
| `PUT /v1/me/library/playlist-folders/<id>/parent` (the same body) | Not checked yet: the app does not offer it (`api.MOVE_FOLDERS` off) |
| `POST /v1/me/library/playlist-folders` `{attributes: {name}}` | 201 with the folder (New Folder…; the web player makes none). With `relationships: {parent: {data: [{id, type: 'library-playlist-folders'}]}}` for a folder inside another: not checked yet |
| `PATCH /v1/me/library/playlist-folders/<id>` `{attributes: {name}}` | 204, although Apple lists every folder with `canEdit` false |
| `DELETE /v1/me/library/playlist-folders/<id>` | 204, the folder and what is in it gone; but playlists deleted with their folder stayed listed, nameless, for more than half an hour, where one deleted by itself left the listing within minutes: `Engine.delete_folder()` deletes the contents first |

A playlist the user may change lists `canEdit` and `canDelete` true; Favourite Songs both
false; one of Apple's added to the library `canEdit` false, `canDelete` true. The listing
carries a playlist's `description` when it has one.

### Removing from the library

The web player's `requestDeleteFromLibrary` (`Engine.remove_from_library()`, the bridge's
`removeFromLibrary`): `DELETE /v1/me/library/<type>/<id>`, `<type>` the catalog type of the
kind (`api.LIBRARY_ROUTES`: `songs`, `albums`, `music-videos`, `playlists`), `<id>` the
item's **library** id (`i.` for a song, `l.` for an album, `p.` for a playlist). When it has
only the catalog id, it first reads the library id, as the engine does: `GET
/v1/catalog/<sf>?ids[<type>]=<catalog id>&relate=library&fields[<type>]=inLibrary&omit[resource]=autos`
(`api.library_twin_params()`), the id in `relationships.library.data[0].id`
(`api.library_twin()`; `attributes.inLibrary` beside it). Checked against a real account on
2026-10-20 (MusicKit `playback/AppleMusic-2642.7.0-external`, the `gb` storefront), on a
song and an album added for the check and removed again:

| Request | Apple's answer |
|---|---|
| `POST /v1/me/library?ids[songs]=<catalog id>` (or `ids[albums]`) | 202 (Add to Library). The library id and `inLibrary` show some seconds to a minute later, and the album leads `/v1/me/library/recently-added`; an album brings its tracks (as library songs of their own) |
| `DELETE /v1/me/library/songs/<library id>`, `.../albums/<library id>` | 204, no body. `GET /v1/me/library/songs/<id>` (the bridge's `libraryHas`, `Engine.in_library()`) is 404 within 2 s, the album within 7 s, and the library listings drop them within 2 to 7 s; the catalog read's `inLibrary` turns false after about 19 s. An album goes with its tracks, and no library artist was left behind |
| `DELETE /v1/me/library/songs/<catalog id>` | 500, not a 404: a catalog id is never the id to delete by |

Removing a song from the library takes it out of every library playlist that held it (the
playlist stays, without the entry). Music videos and Apple's playlists added to the library
were not tried; the web player removes them by the same request (`music-videos`,
`playlists`, which `deletePlaylist()` sends for the user's own). The app leaves an item
removed out of its models at once and until a load no longer meets it (`Library.hide`), and
syncs once `libraryHas` answers false (actions.py).

### Stations from a song or an artist

Create Station (`actions.station_target()`). Checked against a real account on 2026-10-20
(MusicKit `playback/AppleMusic-2642.7.0-external`, the `gb` storefront):
`GET /v1/catalog/<sf>/songs/<id>?include=station` and `.../artists/<id>?include=station`
both answer `relationships.station.data[0]`, a `stations` resource whose id is `ra.<the
song's or artist's catalog id>` (`attributes.kind` `songSeeded` or `artistSeeded`, `isLive`
false). The web player's Create Station does not read it: it builds the id and plays
`mk.setQueue({station: 'ra.' + id})`. The app does the same, with no read: the bridge's
`play('station', 'ra.<id>')` plays it as it is (a song first, two entries queued, rolling),
and on it `mk.capabilities.canEditPlaybackQueue` is false. A library song is seeded by its
`catalogId`; a library artist only by the catalog id the library has for them.

### Ratings: Favourite and Suggest Less

An item has one rating, `PUT /v1/me/ratings/<type>s/<id>` with `{type: 'ratings',
attributes: {value}}` (the bridge's `rating(kind, id, value)`): 1 is a favourite
(`Engine.love()`), -1 Suggest Less (`Engine.suggest_less()`), and `DELETE` takes either
away (`Engine.unlove()`); `Engine.rating()` reads it back from `GET
/v1/me/ratings/<type>s?ids=<id>`. `<type>` is `api.resource_type()`'s: `songs`, `albums`,
`playlists`, `stations`, `music-videos`, or the `library-` type for a library id. A PUT
replaces the rating there was, so Suggest Less replaces a favourite and Favourite a Suggest
Less. Checked against a real account on 2026-10-20 (MusicKit
`playback/AppleMusic-2642.7.0-external`, the `gb` storefront) on a song:

| Request | Apple's answer |
|---|---|
| `PUT /v1/me/ratings/songs/<id>` `{type: 'rating', attributes: {value: -1}}` | 200 with the rating (`value` -1): Suggest Less. `GET` answers it, the catalog read gives `personalRating: -1`; `DELETE` takes it away (204, then 404). The web player offers Suggest Less for albums, artists, music videos, playlists, songs and stations, and not with a favourite |

The menus follow the web player: Favourite or Remove from Favourites, and Suggest Less (not
beside a favourite) or Undo Suggest Less (`actions.rating_actions()`). An artist's favourite
is not a rating (below).

### The Radio page

`Engine.radio()` asks `GET /v1/editorial/<sf>/groupings` with `api.RADIO_PARAMS`
(`name=radio`, `platform=web`, without which it is a 400, `tabs=subscriber`,
`extend=editorialArtwork`, `include[stations]=events,radio-show`), the web player's request
for its Radio page less `extend[station-events]=editorialVideo`, checked live on 2026-10-20.
The answer is the editorial grouping New's is (see "The editorial pages" below for its
element kinds), shaped by `normalize.radio_shelves()` through New's own
`_grouping_shelves()`:

- the live stations (kind 488, a `title`, children 489 each holding one station in
  `contents`) are the first shelf, marked `live`; the hero (316, untitled, children of one
  item each) follows as the featured shelf, less the stations the live row has, and goes
  when nothing is left;
- a live station is `stations` with `isLive: true`, `kind: 'streaming'` and
  `relationships.events` (`station-events`: `title`, `startTime`, `endTime`, `description`,
  `artwork`): the shelf item gets `events`, `[{title, start, end}]` by start time, the
  times UTC stamps; the page picks the one on air as it is shown (`src/radio.py`). The answer's
  `expires` is when the first live station's last programme known ends (at least five
  minutes on): from then it is not fresh (`normalize.answer_expired()`), whatever its age;
- an episode of a show is `stations`, `kind: 'streaming'`, `isLive: false`, with `airTime`,
  `durationInMillis` and its show in `relationships.radio-show`: subtitled with the show's
  name; genre stations are `kind: 'editorial'`. All play as `{kind: 'radioStation', id:
  'ra.<n>'}`, which the app's `{kind: 'station', id}` play is;
- a radio show is an `apple-curators` of `kind` `Show` (with `showHostName`): a category
  tile, as every curator on a shelf is, subtitled with its host, whose page is the
  category page (`bridge.category()`, the curator with its grouping: its episodes);
- the 391 (More to Explore) and 322 (genre links) elements have no `contents` and are left
  out, as on New, and so are `uploaded-videos`.

## Checked live, not used yet

What music.apple.com's own code asks for, and what the API and MusicKit answered, checked
against a real account on 2026-10-20 (MusicKit `playback/AppleMusic-2642.7.0-external`, the
`gb` storefront), for the features still to build. Only the shapes are kept here. Every
write was made on items picked for the check and put back. Reads go through `music()`;
the writes, and any read that must see a write (MusicKit's `music()` may answer from a
cache), go through the request builder, as `apiWrite()` does.

### The queue (#332, #361)

`mk.queue` (MusicKit v3) holds `_queueItems`, each `{item, isAutoplay}`; `queue.items` are
the MediaItems, `queue.position` the current index (-1 for none), and
`queue.userAddedItems`, `queue.autoplayItems`, `queue.unplayedUserItems`,
`queue.unplayedAutoplayItems` filter them (MediaItems, not queue items). Tried on a
throwaway album queue while it played: none of these changed the playback state, the item
or the time (no gap), and each splice posts one `queueItemsDidChange`.

| Call | What it does |
|---|---|
| `queue.remove(index)` | removes a later entry; logs a deprecation warning; throws `INVALID_ARGUMENTS` (`mk-007`) for the current index. The web player's own Remove from Up Next is this, after checking `queue.item(index).id` is the item it means |
| `queue.spliceQueueItems(start, count, items = [])` | `Array.splice` on the queue items, answering those taken out; `queue.splice()` is the same over MediaItems. A move is two calls, `spliceQueueItems(from, 1)` then `spliceQueueItems(to, 0, taken)`, and so two `queueItemsDidChange`; the next item played follows the new order. The web player has no reorder of its own |
| `queue.removeQueueItems(predicate)` | removes every queue item `predicate(queueItem, index)` accepts, from the end, one event each |
| `queue.clearAfterCurrent()` | everything after the current item goes; the current item and those before it stay (the history) |
| `mk.clearQueue()` | the web player's Clear: the whole queue goes (`position` -1, `length` 0) while the current item plays on |
| `mk.autoplayEnabled` | read and written as a property; `autoplayEnabledDidChange` carries the new boolean. Set true at the end of a queue, it adds about ten entries some 2 s later (one `queueItemsDidChange`), each `isAutoplay: true`, a song whose `container` is a `stations` resource with an `ra.cp-…` id. Set false, it removes them one at a time (a `queueItemsDidChange` each: coalesce them). It does not start while repeat is on |

`mk.capabilities` says what may be done now: `canEditPlaybackQueue`, `canAutoplay`, `canSeek`,
`canPause`, `canSkipToNextItem`, `canSkipToPreviousItem`. On an album or a playlist they
are all true; on a song-seeded station `canEditPlaybackQueue` is false (its queue is the
station's, two entries at a time) and the rest true; on a live station all are false. Autoplay is the
page's, not the account's: the web player keeps it in the page's `localStorage` under
`music-app-pref:autoplay-<music user token>` and sets `mk.autoplayEnabled` from it when it
loads, and the page started with it off. The bridge's `formatTrack()` drops `isAutoplay`.

### Live radio (#343)

A live station (`attributes.isLive: true`, `kind: 'streaming'`) plays as one item:
`nowPlayingItem.type` `radioStation`, `isLiveRadioStation` true, `attributes.isLive` true,
its `container` the `stations` resource. MusicKit reports a finite duration that is the
stream's window, not the programme (`currentPlaybackDuration` 160, then 176 a little later),
and a position inside it (from about 112, counting up), with `isPlayingAtLiveEdge` false and
`seekableTimeRanges` `[{start: 0, end: …}]`; `playbackTimeDidChange` and
`playbackDurationDidChange` arrive as for a song. Every capability is false: `seekToTime()`
does nothing, `pause()` leaves it playing, `mk.stop()` ends it (state `stopped`, no item).
The bridge's `nowPlaying()` gives `track.type: 'radioStation'`, `durationMs: 0` and that
position and duration. So a live item is told by its type and `isLive`, not by its duration.

### Favourites of artists (#357)

The catalog read that finds an item's library twin (`api.library_twin_params()`, above) also
gives `personalRating` (1 favourite, -1 Suggest Less, absent for none) with
`fields[<type>]=inLibrary,personalRating`.

| Request | Apple's answer |
|---|---|
| `POST /v1/me/favorites?ids[artists]=<catalog id>` | 202. The web player's `UpdateFavoritesIntent`, which takes any `ids[<type>]`; DELETE to unfavourite (204) |
| `GET /v1/catalog/<sf>/artists/<id>?extend=inFavorites` | `attributes.inFavorites`, a boolean, true within 200 ms of the POST |
| `GET /v1/catalog/<sf>?ids[artists]=<id>&fields[artists]=personalRating&relate=library&omit[resource]=autos` | `personalRating: 1` while favourited, absent otherwise |
| `GET /v1/me/ratings/artists/<id>` | 404 whether favourited or not: an artist's favourite is not a rating |

Favouriting an artist does not add them to the library.

### Credits (#364)

`GET /v1/catalog/<sf>/songs/<id>/credits` (or `include=credits` on the song; the web player
asks `include=albums,artists,credits,lyrics,music-videos`), about 250 to 300 ms: `role-categories`, each `{attributes: {kind, title},
relationships: {'credit-artists': {data}}}`, `kind` `performer`, `composer-and-lyrics` or
`production-and-engineering`, `title` Apple's heading for it; a `credit-artists` entry is
`{id, type, attributes: {name, roleNames: [..], artwork?}}`, its id not an artist's catalog
id. A library song needs its catalog id.

### The editorial pages: New's banners and links, rooms (#370)

The Radio page (`groupings?name=radio`, above) and the New page (`name=music`) answer one
`groupings` resource whose `tabs` hold one `editorial-elements` (kind 382) with `children`,
each a shelf by `attributes.editorialElementKind`:

| Kind | What it is |
|---|---|
| 316 | the hero row: children 320 (wide, with `artwork`, `editorialArtwork`, `designBadge` such as "UPDATED PLAYLIST", `designTag`, sometimes `editorialVideo`), 317 and 383 (`designBadge`), each one resource in `contents` |
| 488 | Radio's live stations: children 489, each one live station in `contents` and a `stationGlyph` (the station's logo with its colours) |
| 326 | a shelf: `name`, `displayStyle` (`compact`, `expanded`), `contents` (albums, playlists, stations, `apple-curators`, `music-videos`, `uploaded-videos`), and `room`, its See All |
| 327 | a shelf of songs |
| 385 | New's "New for <month>": children 386 (an `apple-curators` in `contents`) and 394 (`artwork`, `designTag`, and a `link` or an `apple-curators`) |
| 391 | More to Explore: `name` and `links`, `[{label, url, target?}]` |
| 322 | untitled `links`, every one a genre's grouping |

The links' URLs and what opens them (the web player's routes):

| URL | Request |
|---|---|
| `https://itunes.apple.com/<sf>/collection/<slug>/id<n>?fcId=<id>&mt=14`, `…/viewRoom?fcId=<id>` | `GET /v1/editorial/<sf>/rooms/<id>`: `rooms` with `title`, `sorts`, `contents` (up to 100) |
| `…/viewGrouping?cc=<sf>&id=<id>` | `GET /v1/editorial/<sf>/groupings/<id>?platform=web`, the same shape as New; without `platform` a 400 ("A single platform must be supplied") |
| `…/viewMultiRoom?cc=<sf>&fcId=<id>` | `GET /v1/editorial/<sf>/multirooms/<id>?extend=editorialArtwork,uber,lockupStyle`: `multirooms` with `title`, `uber` (`masterArt`, `name`, `description`, colours) and `children` (404 a header, 345 shelves with `contents` and `room`) |
| `…/viewTop?genreId=<n>` | a chart page, by genre (not tried) |
| `https://music.apple.com/concerts` (`target: 'external'`) | a web page |

A live station's events also carry `heroArtwork`, and some an `editorialVideo` (the web
player's `extend[station-events]=editorialVideo`), which the Radio page does not use.

### Curators and radio shows (#359, #360)

An `apple-curators` resource has `attributes.kind` `Show` (a radio show, with
`showHostName`), `Genre` or `Curator`; third parties are `curators`. None has `playParams`:
nothing plays, and there is nothing to favourite. Its page is `GET
/v1/catalog/<sf>/apple-curators/<id>?include=grouping,playlists&include[editorial-elements]=children,contents,room&extend=editorialArtwork&platform=web`:
`relationships.grouping` a grouping of 326 shelves as above (a show's: its episodes, as
`stations`, and albums and playlists) and `relationships.playlists`. A show's banner is
`editorialArtwork.bannerUber`, else `subscriptionCover`, else `subscriptionHero`. Search
answers curators only when asked for (`types=apple-curators`), never with the app's
`types`. An artist's `view/radio-shows` is not empty for the hosts of Apple's shows (21 of
24 tried), every entry an `apple-curators` of kind `Show`; their `view/more-to-hear` holds
episodes (`stations`, `streaming`, not live).

### An artist's banner (#355)

The web player's artist page asks `GET /v1/catalog/<sf>/artists/<id>` with
`extend=artistBio,editorialArtwork,editorialVideo,extendedAssetUrls,hasBiographyContent,hero,keyColor,plainEditorialNotes`
(and its canvas shelves). Its wide header is `editorialArtwork.centeredFullscreenBackground`
(4320x2160, crop `sr`) when there is one (1 artist in 24), else the portrait in
`attributes.hero[0].content[0].artwork` cut with crop code `vf` when its
`recommendedCropCodes` lists `vf` (11 in 23); with neither, the round portrait. The hero
artwork is the artist's `artwork` itself (square, 902 to 6000 px) with
`recommendedCropCodes` from `va vb vc vd vf vn`; `{w}x{h}vf.jpg` in place of
`{w}x{h}bb.jpg` answers an image of exactly that size cropped where Apple chose (2400x1000,
3000x1000), where `bb` fits the square inside it. Other keys seen: `originalFlowcaseBrick`,
`storeFlowcase`, `subscriptionHero`, `musicContentColorLogoTrimmed` (a logo).

## Events

The client dispatches each bridge event as `am:<name>`; the Engine re-emits it as
`event(name, data)`. The data is read from the instance at the moment of the event.

| Event | Data |
|---|---|
| `authorizationStatusDidChange` | `{authorized, status}` |
| `playbackStateDidChange` | `{state, position, duration}`; a play walks `playing`, `waiting`, `loading`, `playing` |
| `nowPlayingItemDidChange` | `{track: Track or null, index}` |
| `playbackTimeDidChange` | `{position, duration}` in seconds, about four times a second while playing |
| `playbackDurationDidChange` | `{duration}` |
| `queueItemsDidChange` | `{index, items: [Track]}` (index -1 before playback starts) |
| `queuePositionDidChange` | `{index, oldIndex}` |
| `shuffleModeDidChange`, `repeatModeDidChange` | `{shuffle: "on"\|"off"}`, `{repeat: "none"\|"one"\|"all"}` |
| `playbackVolumeDidChange` | `{volume}` |
| `mediaPlaybackError` | `{code, message}` (`code`: MusicKit's `errorCode`, such as `CONTENT_UNAVAILABLE`, else '') |
| `previewDidChange` | `{id}` as a preview starts; `{id: null, ended, reason}` as it stops (`ended` its id; `reason` `ended`, `error`, `stopped`, `replaced` or `playback`, MusicKit taken in hand). The bridge's own, not MusicKit's |
| `bridgeReset` | `{}`: the client's own, after it put the bridge back into a new document |

## library.json

`<cache>/library.json`, written by `src/sync.py` (and `scripts/demo_library.py`), read by
`src/library.py`. Version 2: an album's track `index` counts on across its discs; the app
syncs an older file again at once.

```jsonc
{
  "version": 2, "generated": "2026-09-25T12:00:00Z", "storefront": "us",
  "sections": {"albums": [Item], "artists": [Item], "playlists": [Item], "radio": [Item],
               "videos": [Item]},
  "shelves": [{"key": "rec-<id>", "title": "…", "items": [Item]},   // Apple's recommendations
              {"key": "heavy-rotation", "title": "", …}, {"key": "recently-added", …}],
                                                // empty titles: the app titles them by key
  "folders": [{"id": "root", "title": "", "parent": null,
               "children": [{"kind": "playlist", "id": "p.…"}, {"kind": "folder", "id": "p.…"}]}]
}

Item = {
  "id": "l.…",                  // library id, or catalog id when not in the library
  "kind": "album" | "playlist" | "artist" | "station" | "video" | "song" | "link",
  "title": "…", "subtitle": "…", "year": 2007, "genre": "…", "summary": "…" /* or null */,
  "art": "<cache>/art/<sha1>.jpg" /* or null */,     // 640 px, the pages' hero
  "thumb": "<cache>/thumb/<sha1>.jpg" /* or null */, // 320 px, tiles and rows
  "artUrl": "https://…/640x640bb.jpg",               // for fetching `art` on demand
  "artColor": "#1a1a1a" /* or null */, "explicit": false,
  "trackCount": 12, "durationMs": 2580000,           // albums, playlists (videos: length)
  "albumCount": 3,                                   // artists
  "catalogId": "…" /* or null */, "url": "https://music.apple.com/…" /* or null */,
  "attributes": {"isFavourites": true, "canEdit": false, "canDelete": false},   // playlists,
                                                     // when they apply
  "modified": "2025-05-01T09:00:00Z",                // playlists: Apple's lastModifiedDate as
                                                     // listed when `groups` was last read; the
                                                     // sync keeps them while it holds (sync.py)
  "play": {"kind": "album", "id": "l.…"},            // what the bridge's play() takes
  "groups": [{"name": "Disc 1", "play": {…}, "entries": [Track]}]   // an album's discs, a
                                                     // playlist's "Tracks", an artist's albums
}
Track = {"id": "i.…", "catalogId": "…" /* or null */, "title": "…", "artist": "…",
         "album": "…", "trackNumber": 1, "discNumber": 1, "durationMs": 216000,
         "durationLabel": "3:36", "explicit": true,
         "index": 0,                     // its place in its group's `play` queue
         "thumb": "…" /* or null */,     // a playlist's rows
         "type": "library-songs"}        // the API's: songs, music-videos, library-…, or ''
                                         // (the item playing may carry MusicKit's own
                                         // 'song' or 'musicVideo' instead)
```

An artist's page (`Engine.artist_page()`, `normalize.artist_page()`) is
`{id, artist, latest: {key, title, item} | null, topSongs: {key, title, items, more} | null,
shelves: [{key, title, items, more}]}`: `artist` an Item without groups whose `summary` is
the biography, with `origin`, `bornOrFormed` (Apple's own words) and `isGroup` where Apple
has them; `latest` the featured or latest release, with its `releaseDate`; the top songs
song Items with their `album`; each shelf one of the artist's views in music.apple.com's
order, titled as Apple titles it, `more` when `Engine.artist_view()` has more of it. A
video about the artist (an interview, a film) is a `link` Item: its `url` is its page,
its subtitle its length, and it has nothing to play.

What an album's page shows under its tracks (`Engine.album_page()`, `normalize.album_page()`)
is `{id, artistId, artistName, release: {releaseDate?, copyright?, recordLabel?},
shelves: [{key, title, items, more}]}`: `id` the catalog album's, `release` what its footer
says (`normalize.album_release()`: each key only where Apple has it), and the shelves in
music.apple.com's order: `other-versions`, `related-videos`, `more-by-artist`, `appears-on`
and `related-albums`, all but More By the album's own views (`api.ALBUM_VIEWS`, one read
with the album), titled as Apple titles them; `more-by-artist` is a page of its first
artist's `full-albums` view, less the album, untitled (the app names it "More By …"); `more`
when `Engine.album_view()` (or `artist_view()` for More By) has more. A library album is
asked by its own id and one of its songs' catalog ids, through which the engine finds its
catalog album (`api.SONG_ALBUMS_PARAMS`); the answer is kept under the id it was asked by.

A playlist's suggested songs (`Engine.playlist_suggestions()`,
`normalize.playlist_suggestions()`) are `{items: [Item]}`: song Items as the top songs are
(with their `album`), in Apple's order, each once. Apple may suggest a song the playlist
holds; the playlist page leaves those out. The first answer (16 songs: the most a page
shows, twelve, and four spare) is kept for a day; a Refresh's replaces it; `more=True`
asks for a few more beside them, unkept. Each kept answer carries `basis`, the page's
`suggestions.basis()` of the songs the playlist held when it was asked: one kept for other
songs (one added or removed since, here or elsewhere and synced) is not fresh, and Apple is
asked again; it is answered `stale` only when Apple cannot be asked.

The app shows none of the data's own words: a missing name is '', the app names shelves by
key, writes the captions from the counts and titles an album's discs from `discNumber`. A song without an album of its own sits under a stand-in album
(`l.alb_…`) that plays `{"kind": "songs", "id": "<id>,<id>…"}`; a video plays as MusicKit's
`musicVideo`. Older files may hold an English `countLabel` or `sections.songs` (loose Tracks);
the model still reads both.

## The caches

All under `config.cache_dir()`, every file written through `store.py` (a dot-named temporary
file beside it, renamed over it; directories 0700, files 0600), with the writer's cache
generation, so a write after Clear Cache or sign-out lands nowhere.

| Path | Written by | Read by | Kept |
|---|---|---|---|
| `library.json` | the sync | `library.py` | until the next sync |
| `art/`, `thumb/`, `art/.sizes` | the sync (thumbnails), the pages (covers) | the artwork loader | pruned against library.json after every sync |
| `remote-art/` | `src/remote.py`, `Engine.item()` | the pages, MPRIS | trimmed to 32 MB, oldest first |
| `lyrics/<id>.json` | `Engine.lyrics()` | the same | fetched again after 30 days, or when its `languages` (the translations' and pronunciations', `api.lyrics_languages()`) are not the ones asked for now, or its `format` is older than `lyrics.FORMAT` (2: the words, the background vocals and the singers), though still read while the engine cannot answer; the 2,000 played last |
| `landing.json`, `categories/`, `browse.json`, `made-for-you.json`, `radio.json`, `artists/`, `albums/`, `suggestions/` | `Engine._kept_answer()` | the same, `cache.read_kept()` | a day (a playlist's suggestions only while it holds the same songs, their `basis`; Radio's only until its `expires`); an older one only when Apple cannot be asked (`stale: True`); in demo mode, only what the demo library invented (marked `demo`), at any age |

`normalize.prune_caches()` runs after the library's first load and after every sync; it also
removes what older versions kept (`items/`) and temporary files over an hour old.

## Environment

Read by `config.py` on every call:

| Variable | What it does |
|---|---|
| `APPLE_MUSIC_CACHE` | the cache directory (default `$XDG_CACHE_HOME/apple-music`, `apple-music-devel` for the development build) |
| `APPLE_MUSIC_PROFILE` | Chrome's profile (default `$XDG_DATA_HOME/apple-music/chrome`, `chrome-devel` for the development build) |
| `APPLE_MUSIC_DEBUG_PORT` | also opens a DevTools port on 127.0.0.1, for `scripts/am.py --attach`. Developers only: while it is set, any local program can drive the signed-in session |
| `APPLE_MUSIC_HOST_SESSION_BUS` | the D-Bus address Chrome runs with as its session bus when the app runs on another one (`scripts/headless.sh` sets it to the desktop's): the keyring that encrypts the profile's cookies answers there. Unset, Chrome inherits the app's |

## Provenance

Forked on 2026-09-27 from the backend of the owner's GNOME Shell extension, Apple Music
Library, at its commit 906bfa9 (`cdp.py`, `bridge.js`, `sync.py`, now `normalize.py`, and this
README). This app has rewritten most of it since and maintains it for itself; the history is
`git log -- src/backend`.
