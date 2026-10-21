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
| `queue-locked` | MusicKit allows no edits of the queue now (`capabilities.canEditPlaybackQueue` false: a station's) |
| `queue-changed` | the queue's entry an edit named (its index and id) is not there any more: the queue changed meanwhile |
| `conflict` | a write made against a list Apple no longer has: a playlist's new order whose tracks changed elsewhere since the app read them. Nothing was written |

## The bridge

`client.load_bridge()` injects `bridge.js` with its hash as `__appleMusicLibraryWanted`: the same
file injected twice is a no-op, a changed one replaces the old. `CDPClient.bridge(name, *args)`
calls `window.__appleMusicLibrary.<name>(...)`; the Engine's commands are thin calls into these.

| Call | Answer |
|---|---|
| `status()` | `{ready, engine, authorized, storefront, bitrate}` (`bitrate`: `mk.bitrate` in kbps, null when MusicKit has none) |
| `drm()` | `{widevine: true}`, or `{widevine: false, error}` when the browser refuses Widevine (`navigator.requestMediaKeySystemAccess`, AAC in MP4) or has no Encrypted Media Extensions; never a throw |
| `accountName()` | the account's name as the page shows it (`.account-menu .user__name`), or null; null while a sign-in control is on the page |
| `signin()` | `mk.authorize()`, then `{authorized}` |
| `signout()` | `mk.unauthorize()`, which revokes the session at Apple's end: `{ok: true}` or `{error}`, never a throw |
| `api(path, params, options)`, `apiAll(paths)` | the API's answer body (`mk.api.music()`); `apiAll` answers null in place of a failed read |
| `play(kind, id, {startWith, startId, shuffle, startTime, paused})` | `{ok: true}` (with `moved: {from, to}` when the queue held another item than `startId` at `startWith` and was moved to it, and `sought: true` when it sought to `startTime` itself), or `{error, code}` when MusicKit refuses. `kind`: `album playlist station song musicVideo artist songs` (`songs`: ids joined by commas; `artist`: its top songs, else its station). `shuffle` true turns shuffle on, false off, null leaves it. `startTime` (seconds: a restored session's position) goes to `setQueue`, and once the item plays, when MusicKit began it more than 2 s earlier and it is `startId`'s, a `seekToTime` follows. `paused` queues it without playing or moving it (`startPlaying: false`); the start time then waits for the next `control('play')` or `'toggle'` (a `pause` keeps it, anything else gives it up). With autoplay on, MusicKit's autoplay station is stopped first ("Autoplay across queues") |
| `playNext(kind, id)`, `playLater(kind, id)` | `{ok: true}`. `kind` as `play()` takes it; `songs` (ids joined by commas: a selection's run of songs, `actions.queue_commands()`) queues them in their order, after the item playing or at the end of the user's queue (before what autoplay added), checked live on 2026-10-20 with two catalog songs |
| `control(action)` | `play pause toggle next previous stop`: `{ok: true}` |
| `seek(seconds)` | `{ok: true}` |
| `volume(level)` | `{volume}`: MusicKit's level after the set (0 to 1; the page keeps it) |
| `shuffle(on\|off\|toggle)`, `repeat(none\|one\|all\|cycle)` | `{shuffle, repeat}` |
| `nowPlaying()` | `{state, track, position, duration, shuffle, repeat, volume, capabilities}`; `state` is MusicKit's `PlaybackStates` name; `capabilities` is `{canSeek, canPause, canSkipToNextItem, canSkipToPreviousItem, canSetShuffleMode, canSetRepeatMode}`, `mk.capabilities`' (each true when MusicKit has none, or not that one; all false on a live station: below) |
| `queue()` | `{index, items: [Track], editable, canAutoplay, autoplay, edit}`: `editable` and `canAutoplay` are `mk.capabilities`' `canEditPlaybackQueue` and `canAutoplay` (true when MusicKit has none), `autoplay` is `mk.autoplayEnabled`; a Track autoplay added carries `autoplay: true` (its queue item's `isAutoplay`); `edit` is the number of the last of the app's removes and moves the bridge has applied (0 since the page loaded: "Moving queue entries") |
| `queueRemove(index, id, edit)` | `{ok: true}` once the queue's entry at `index`, when it is still `id` and not the item playing, is out of the queue (`queue.spliceQueueItems(index, 1)`, else the deprecated `queue.remove(index)`), the snapshots after it naming `edit` (the Player's number for it, or null); or `{error, code}`: `NOT_EDITABLE` (a station's queue), `CURRENT`, `STALE` (another entry is there now) |
| `queueMove(from, to, id, edit)` | `{ok: true}` once the queue's entry at `from`, when it is still `id` and after the item playing, is at `to` (its index once moved), within its section of Up Next (before or from the first entry autoplay added after the item): `spliceQueueItems(from, 1)`, then `spliceQueueItems(to, 0, taken)`, the queue item given back as it came (so it keeps its `isAutoplay`), only the second's `queueItemsDidChange` posted, naming `edit`. When MusicKit does not put it at `to` (it throws, or its filter drops the item) it goes back to `from` if it can, the queue as it is is posted and the answer is `STALE`. Or `{error, code}`: `NOT_EDITABLE` (a station's queue, or no `spliceQueueItems`), `CURRENT`, `STALE` (another entry is there, an entry played, or no such place), `SECTION` (`to` in the other section) |
| `queueClear()` | `{ok: true, cleared}`: everything after the item playing out of the queue (`queue.clearAfterCurrent()`), its queue items kept for `queueUndoClear()`; or `{error, code: 'NOT_EDITABLE'}` |
| `queueUndoClear()` | `{ok: true, restored}`: the queue items the last `queueClear()` took, spliced back after the item playing while it is the same item (`queue.spliceQueueItems(position + 1, count, items)` over what follows it, the items as one array, autoplay's refill dropped when Clear took autoplay entries: "Autoplay across queues"), once, kept until the splice is done; `restored` is how many of Clear's MusicKit put in; or `{error, code}` (`STALE`: nothing kept, or another item plays) |
| `autoplay(on)` | `{autoplay, canAutoplay}` after `mk.autoplayEnabled = on` (null: only read) |
| `bitrate(kbps)` | `{bitrate}` after `mk.bitrate` is set: 64 is `MusicKit.PlaybackBitrate.STANDARD` (High Efficiency), anything else `HIGH` (256, High Quality); null only reads. `bitrate` is null when MusicKit says none ("Streaming quality") |
| `queueJump(index)` | `{ok: true}` (`mk.changeToMediaAtIndex`) |
| `rating(kind, id, value)`, `addToLibrary(kind, id)`, `addToPlaylist(playlistId, tracks)` | `{ok: true}`, or a throw with Apple's status and message. `tracks` is `[{id, type}]`, appended in order by one `POST /v1/me/library/playlists/<id>/tracks` `{data: tracks}` (`addToPlaylist(playlistId, songId, type)`, one song, still works); the engine sends an album's or a playlist's in runs of `api.PLAYLIST_BATCH` (100), one after the other: Apple documents no limit, and none has been checked yet. Writes go through `mk.api.client.createRequest(...).send()`: Apple answers them 202 or 204 with no body, which `music()` cannot read (a body Apple does send comes back as `data`) |
| `createPlaylist(attributes, tracks, parentId)` | `{id}`, the new playlist's; `attributes` `{name, description?, isPublic?}`, `tracks` `[{id, type}]`; `with=shared` in the query when `isPublic` is true, as the web player asks |
| `removeFromLibrary(type, id)` | `{ok: true}`, or a throw as above: `DELETE /v1/me/library/<type>/<id>` (below) |
| `favourite(type, id, on)` | `{ok: true}`, or a throw as above: `POST /v1/me/favorites?ids[<type>]=<id>` (`on`), else a `DELETE` of the same; the web player's `UpdateFavoritesIntent` (an artist's star, below) |
| `apiFresh(path, params)` | the JSON body of a `GET` through the request builder, never answered from `music()`'s cache (a read that must see a write: an artist's `inFavorites`); a throw with Apple's status and message |
| `libraryHas(type, id)` | `{has}`: `GET /v1/me/library/<type>/<id>` through the request builder (a read that must see a removal), `has` false for Apple's 404; a throw for any other failure |
| `updatePlaylist(id, attributes)`, `deletePlaylist(id)`, `removeFromPlaylist(id, type, trackId)`, `replacePlaylistTracks(id, tracks)`, `updateFolder(id, attributes)`, `deleteFolder(id)` | `{ok: true}`, or a throw as above (the requests below) |
| `createFolder(attributes, parentId)` | `{id}`, the new folder's; `attributes` `{name}`, `parentId` the folder it goes in (none: the top level) |
| `moveToFolder(type, id, folderId)` | `{ok: true}`: the playlist (`type` `library-playlists`) or folder (`library-playlist-folders`) into the folder `folderId` (`p.playlistsroot` for the top level), the web player's `requestMoveToFolder` |
| `lyrics(catalogSongId, languages)` | `{synced, lines: [Line]}`, the TTML read with the page's XML parser (`parseTtmlLyrics`). A Line is `{startMs, endMs, text, stanza?, words?, background?, backgroundWords?, agent?, pronunciation?, pronunciationWords?, pronunciationBackground?, pronunciationBackgroundWords?, translation?, translationBackground?}`, empty fields left out: `stanza: true` on a verse's first line (each `<div>`); `text` the main vocals, `background` the `<span ttm:role="x-bg">` (parentheses and all), each with its spaces run together; with `itunes:timing="Word"` on the root, `words` and `backgroundWords` are their timed `<span>`s as `[{startMs, endMs, text}]`, each piece's text with the space after it, so the pieces join to the text (a piece without one is a syllable joined to the next); `agent` the `<p>`'s (or its `<div>`'s) `ttm:agent`, kept only when some line's is not `v1`. src/lyrics.py's docstring has the shape, and engine.lyrics_answer checks it. music.apple.com's request (checked against the API on 2026-10-19): `/v1/catalog/<sf>/songs/<id>/syllable-lyrics?extend=ttmlLocalizations&l[lyrics]=<languages.lyrics>&l[script]=<languages.script>` (`api.lyrics_languages()`: `en-GB`, `en-Latn`), whose `attributes.ttmlLocalizations` is the TTML with `<head><metadata><iTunesMetadata><transliterations><transliteration xml:lang="ja-Latn"><text for="L1">…` and `<translations><translation xml:lang="en-US"><text for="L1">…`: a line's `pronunciation` and `translation` are the `<text>` its `itunes:key` names, split and (the transliteration's) timed as the line is, and dropped when they are the line itself. Its lines are the plain `/lyrics`' (which ignores those parameters); that is asked when syllable-lyrics fails |
| `search(term, limit, types, offset, top)` | the API's answer, shaped by `normalize.search_results()`: `GET /v1/catalog/<sf>/search` for `types` (`api.SEARCH_TYPES`, every kind the page shows, curators included; or one kind's, `api.SEARCH_KIND_TYPES`), `limit` a type (25 at most), from `offset` when there is one, and `with=topResults` with `top`. Each type's section names its next page in `next` (`/v1/catalog/<sf>/search?offset=25&…`, `api.next_offset()`), absent at the end |
| `suggest(term, limit)`, `searchLanding()`, `category(id)` | the API's answer, shaped by `normalize.search_suggestions()`, `search_landing()`, `category_page()` |
| `playlistSuggestions(playlistId, limit, offered, selected, previewed)` | `{results: {suggested: [songs]}}`, the songs Apple suggests adding to a library playlist, shaped by `normalize.playlist_suggestions()`: music.apple.com's own request (checked against the API on 2026-10-08), `POST /v1/me/recommendations/suggested?platform=web&omit[resource]=autos&contexts=playlist-suggested-songs&types=songs&include[songs]=artists&limit=<limit>` with `{targetContent: {id, type: 'library-playlists'}}`, through the request builder (`music()` sends no body); up to `limit` (20 by default) full catalog songs. With `offered` (catalog ids shown) or `selected` (those added) the body also carries `offered: {suggested: [{id, type: 'songs', meta: {impressed: true, previewed}}]}` (`previewed` true for the ids in `previewed`, those whose preview was played) and `selected: [{id, type: 'songs', meta: {source: 'suggested'}}]`, as the web player's Refresh sends them; Apple then answers none of the offered songs (checked 2026-10-08) |
| `preview(id, url)` | `{ok: true, id}` once Apple's 30-second clip of a song (`url`, https: the song's `previews[0].url`, kept as `previewUrl`) plays, or `{error, code}` (`NO_PREVIEW` for no https address, else the media error's name, such as `NotAllowedError`). MusicKit is paused first and its queue left alone: the clip plays in an `Audio` element of the page's own, at MusicKit's volume (`volume()` sets both), one at a time. `play()` and every `control()` stop it, and so does MusicKit playing again (`previewDidChange` follows each start and end) |
| `stopPreview()` | `{stopped}`: whether a preview was playing |
| `subscribe()`, `unsubscribe()` | MusicKit's listeners on or off, once per instance: `{subscribed: true, events: [names], attached}` (`attached` false when this bridge's listeners were on already), and `{subscribed: false}` |

### The playlist writes

Found in music.apple.com's own code (its `requestCreateNewPlaylist`,
`requestUpdatePlaylist`, `requestRemoveFromPlaylist`, `requestUpdatePlaylistTracks`,
`requestMoveToFolder` and `requestDeleteFromLibrary`) and checked against a real account on
2026-10-03, on playlists and folders made for the check and deleted after it; the moves to
the top level, the folder moves and a folder made inside another on 2026-10-21, the same
way, the listings read past MusicKit's cache (`apiFresh`) once a second:

| Request | Apple's answer |
|---|---|
| `POST /v1/me/library/playlists` `{attributes: {name, description?}, relationships: {tracks: {data: [{id, type}]}, parent: {data: [{id, type: 'library-playlist-folders'}]}}}` | 201 with the new playlist; both relationships may be left out (an empty playlist at the top level). Listed by the listings 4 to 6.5 s later |
| `PATCH /v1/me/library/playlists/<id>` `{attributes: {name?, description?, isPublic?}}` | 204; any attribute alone; listed within a second. The web player adds `?with=shared` when it makes the playlist public (`updatePlaylist` does too); `isPublic: false` alone answered 204 (2026-10-21). Making one public was not tried on the account: it would show on the profile |
| `DELETE /v1/me/library/playlists/<id>/tracks?ids[library-songs]=<id>&mode=all` | 204: every entry of that song goes. The tracks of a library playlist are `library-songs` (or `library-music-videos`) by the song's own `i.` id, and carry no id of the entry |
| `PUT /v1/me/library/playlists/<id>/tracks` `{data: [{id, type}]}` | 204: the list replaced whole, in that order (the web player's reorder: `Engine.reorder_playlist()`); one entry of a song held twice is removed so. Checked on a playlist of three songs; one of about 500, how soon the tracks read shows the new order, and whether an entry Apple cannot play survives it are not checked yet |
| `DELETE /v1/me/library/playlists/<id>` | 204. A playlist is still listed for minutes after, nameless (`api.is_deleted`), and a second DELETE is a 500 |
| `PUT /v1/me/library/playlists/<id>/parent` `{data: [{id: <folder>, type: 'library-playlist-folders'}]}` | 204, no body: moved into the folder (Move to Folder, a drop on a sidebar folder). Listed in the folder, and gone from the top level, 5 s later (2026-10-21) |
| `PUT /v1/me/library/playlists/<id>/parent` with Apple's root folder, `p.playlistsroot` | 204, no body: out of its folder to the top level (Top Level, a drop on All Playlists; `api.MOVE_TO_TOP_LEVEL`). Listed at the top level, and gone from the folder, 5.2 s later (2026-10-21) |
| `PUT /v1/me/library/playlist-folders/<id>/parent` (the same body) | 204, no body: the folder, with what it holds, into the folder (`api.MOVE_FOLDERS`), or with `p.playlistsroot` to the top level. To the top level: listed there, and gone from its folder, 3.3 to 4.9 s later. Into a folder: gone from the top level 5.5 s later, but listed in the new folder only 59 s later, so for most of a minute Apple lists it nowhere (2026-10-21): `actions.FOLDER_SETTLE_DELAYS`, `TreeChange.entries` |
| `POST /v1/me/library/playlist-folders` `{attributes: {name}}` | 201 with the folder, `{data: [{id, type, href, attributes: {canDelete, canEdit, dateAdded, name}}]}` (New Folder…; the web player makes none); listed at the top level 5.8 s later. With `relationships: {parent: {data: [{id, type: 'library-playlist-folders'}]}}`, a folder inside another: the same 201, and the parent honoured (a read with `include=parent` names it at once), but listed in it only 61 s later (2026-10-21) |
| `PATCH /v1/me/library/playlist-folders/<id>` `{attributes: {name}}` | 204, although Apple lists every folder with `canEdit` false |
| `DELETE /v1/me/library/playlist-folders/<id>` | 204, the folder and what is in it gone; but playlists deleted with their folder stayed listed, nameless, for more than half an hour, where one deleted by itself left the listing within minutes: `Engine.delete_folder()` deletes the contents first |

A playlist the user may change lists `canEdit` and `canDelete` true; Favourite Songs both
false; one of Apple's added to the library `canEdit` false, `canDelete` true. The listing
carries a playlist's `description` when it has one.

A library playlist's attributes, as the listing has them (2026-10-20, counts only): `artwork`,
`canDelete`, `canEdit`, `dateAdded`, `description`, `hasCatalog`, `hasCollaboration`,
`isPublic`, `lastModifiedDate`, `name`, `playParams`; no `trackCount`. Its tracks read (`GET
…/tracks`, every page) does return the entries Apple cannot play, without `playParams` (four
across 33 playlists, all `library-songs`; the largest playlist held 478 songs). A PUT of the
tracks replaces the whole list, so a new order (`Engine.reorder_playlist()`) and the removal
of one entry of a song held twice read the list first and send back every entry read, by its
own `id` and `type` as Apple gave them (`api.playlist_entries()`): an entry without either is
refused (`api`) and nothing is written; a list that is not the one the app showed is
refused as `conflict` (`api.reordered_entries()`). The ids alone say whether it changed: a
rename moves `lastModifiedDate` too, and no count is listed.

A library playlist's cover cannot be set from the web (checked 2026-10-21, #556). The web
player's own playlist form (create and edit: its `requestCreateNewPlaylist` and
`requestUpdatePlaylist`) has a title (255 characters at most), a description (2,000) and a
"make public" check box, and sends `{name, description, isPublic}` and nothing else; neither
its code nor MusicKit JS has an upload of any image, and Apple's documented creation request
(`LibraryPlaylistCreationRequest`) takes a name, a description, the tracks and the parent.
A PATCH of `{attributes: {artwork: {url, width, height}}}` on a playlist made for the check
answered 204 and the playlist's read showed no `artwork` after it: Apple ignores it. A new
playlist answers with `canDelete`, `canEdit`, `dateAdded`, `description`, `hasCatalog`,
`hasCollaboration`, `isPublic` (false), `lastModifiedDate`, `name` and `playParams`, and no
`artwork` until Apple's own apps give it one (the web player draws one from its songs'
covers). So the playlist dialog (src/dialogs/playlist.py) has no image.

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
| `POST /v1/me/library?ids[songs]=<catalog id>` (or `ids[albums]`) | 202 (Add to Library). The library id and `inLibrary` show some seconds to a minute later, and the album leads `/v1/me/library/recently-added`; an album brings its tracks (as library songs of their own). The app notes an album or playlist it added (`Library.note_added()`), so its page says In Library before the listing does |
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
### The queue

`mk.queue` (MusicKit v3) holds `_queueItems`, each `{item, isAutoplay}`; `queue.items` are
the MediaItems, `queue.position` the current index (-1 for none), and
`queue.userAddedItems`, `queue.autoplayItems`, `queue.unplayedUserItems`,
`queue.unplayedAutoplayItems` filter them (MediaItems, not queue items). Checked live on
2026-10-20 on a throwaway album queue while it played (#332): none of the calls below
changed the playback state, the item or the time (no gap), and each splice posts one
`queueItemsDidChange`. The bridge's `queueRemove`, `queueMove`, `queueClear`, `queueUndoClear` and
`autoplay` use them.

| Call | What it does |
|---|---|
| `queue.spliceQueueItems(start, count, items = [])` | `Array.splice` on the queue items, answering those taken out; `queue.splice()` is the same over MediaItems. `items` is **one array** of queue items (`{item, isAutoplay}`, as a splice answers them), never spread out: MusicKit's own first line is `r = r.filter(a => cn(a?.item, this.playbackMode))`, so spread arguments make `items` the first entry and throw `TypeError: r.filter is not a function` (#462), and an entry without a playable `item` (a MediaItem) is dropped. A fourth argument, true by default, was not looked into |
| `queue.remove(index)` | removes a later entry; logs a deprecation warning; throws `INVALID_ARGUMENTS` (`mk-007`) for the current index. The web player's own Remove from Up Next is this, after checking `queue.item(index).id` is the item it means |
| `queue.clearAfterCurrent()` | everything after the current item goes; the current item and those before it stay (the history) |
| `mk.autoplayEnabled` | read and written as a property; `autoplayEnabledDidChange` carries the new boolean. Set true at the end of a queue, it adds about ten entries some 2 s later (one `queueItemsDidChange`), each `isAutoplay: true`, a song whose `container` is a `stations` resource with an `ra.cp-…` id. Set false, it removes them one at a time (a `queueItemsDidChange` each). It does not start while repeat is on |

`mk.capabilities` says what may be done now: `canEditPlaybackQueue`, `canAutoplay`, `canSeek`,
`canPause`, `canSkipToNextItem`, `canSkipToPreviousItem` (and the bridge passes on
`canSetShuffleMode` and `canSetRepeatMode`, true when MusicKit leaves them out). On an album or a playlist they
are all true; on a song-seeded station `canEditPlaybackQueue` is false (its queue is the
station's, two entries at a time) and the rest true; on a live station all are false.
Autoplay is the page's, not the account's: the web player keeps it in the page's
`localStorage` under `music-app-pref:autoplay-<music user token>` and sets
`mk.autoplayEnabled` from it when it loads, and the page started with it off; the app sets
its own `autoplay` setting at every start and after a reload (`Player.apply_autoplay`).

### Autoplay across queues (#471)

Autoplay is run by MusicKit's `SerialPlaybackController` (`mk.playbackControllers.serial`,
also `mk._playbackController` while it plays; every queue but a station's), read in the
page's bundle (MusicKit `playback/AppleMusic-2642.7.0-external`):

- `mk.setQueue()` loads the items and calls the controller's `replaceQueue`: the old item
  stopped, a new queue posted with `queueItemsDidChange`, then `stopAutoplay()` (the
  station dropped: `_autoplayStation` undefined, `queue.hasAutoplayStation` false, the
  unplayed autoplay entries removed) and `startAutoplay()`, which makes a station from the
  last ten items (`POST /v1/me/stations/continuous`) and asks it for songs
  (`queueAutoplayTracks()`: `POST /v1/me/stations/next-tracks/<id>`, enough for ten
  unplayed autoplay entries, appended as `{item, isAutoplay: true}`, one
  `queueItemsDidChange`). Every `queueItemsDidChange`, `queuePositionDidChange` and
  `nowPlayingItemDidChange` asks for more the same way (so Clear refills it, about 2 s
  later); nothing more is needed per queue, and the web player does nothing more
  (`await setQueue(…); await play()`).
- `queueAutoplayTracks()` sets `loadingAutoplayTracks` before its request and clears it
  after, with no `finally`, and between the two reads `this._autoplayStation.id` again for
  a log line. A queue set with `startWith` (the bridge always passed one, 0 for the top;
  the web player only when a track is picked) starts initiated (`position` set), so its
  first `queueItemsDidChange` asks the **old** station for songs before `stopAutoplay()`
  drops it; that answer lands while the new station is being made, the log line throws a
  `TypeError` (an unhandled rejection), and `loadingAutoplayTracks` stays true: from then
  on every `queueAutoplayTracks()` returns at "already loading", for every later queue,
  while `hasAutoplayStation` and `autoplayEnabled` say true and toggling `autoplayEnabled`
  changes nothing, until the page reloads. The first queue after a load had no old station,
  so it alone got autoplay's songs.
- The bridge's `play()` therefore calls the controller's `stopAutoplay()` and clears
  `loadingAutoplayTracks` before `setQueue` (`releaseAutoplay`, only while autoplay is on):
  the new queue asks nothing until its own station is made, and a flag left stuck (autoplay
  turned off while a request was out, a station's controller taking over) is cleared. When
  `setQueue` fails before replacing the queue, `startAutoplay()` gives the queue that stays
  a station again. `autoplay(true)` clears a stuck flag too, when no station is held. A
  request still out when its station goes may yet land on the new queue (MusicKit appends
  it, so ten more autoplay entries); rare, and better than none.
- Live, 2026-10-20 (.Devel, Autoplay on): before, a page's first queue got its ten
  autoplay entries in about 2 s and seven later ones (library albums by `l.` id, the
  bridge's `play()`) none within 25 s, `hasAutoplayStation` true, `autoplayItems` empty.
  `mk.setQueue({album})` straight, without `startWith`, got ten twice in a row; with the
  fix, three albums in a row through the app each made a station of its own and asked it
  for songs, the ten entries there when read after they landed, no `TypeError` among the
  page's unhandled rejections and `loadingAutoplayTracks` never left stuck.

Clear's Undo (`queueUndoClear`, #473): about 2 s after a Clear, autoplay refills the queue
with ten new entries. Undo puts Clear's entries back as `undoneTail()` orders them with what
follows the item then, in one `spliceQueueItems(position + 1, count, queueItems)`: those
Clear took, the songs queued since (not autoplay's) before the first autoplay entry among
them, and the refill dropped when Clear took autoplay entries (else it stays, after the
rest), so Up Next has one Autoplay batch. An Undo made while the refill is still out
(`loadingAutoplayTracks`) arms `lateRefill`: the autoplay entries that arrive after it are
taken out in the bridge's own `queueItemsDidChange` handler, before the event is posted, so
the app never sees them. `Player.undo_clear()` orders its store the same way
(`player.undone_tail()`). Live: a queue of the item and five songs, Clear, the refill, Undo
4 s later: the five back and the refill after them (16 entries, ten autoplay, one batch);
then Clear and Undo 0.2 s later, before the refill: 16 entries, ten autoplay, one batch.

### Streaming quality (#368)

MusicKit JS streams AAC at 256 kbps (`MusicKit.PlaybackBitrate.HIGH`) or 64 kbps
(`STANDARD`), nothing higher (docs/decisions.md, "Not possible through the web player").
`mk.bitrate` is read and written as a property; MusicKit may also set it on its own (64 kbps
on a slow connection), and is expected to post `playbackBitrateDidChange` (`{bitrate}`) when
it changes. Not checked live yet: whether a set takes effect on the item playing or from the
next one, whether the web player keeps a choice of its own as it loads (the app sets its
`streaming-quality` again at every start and after every `bridgeReset`, when MusicKit has
another), and that the event exists in MusicKit v3 under that name (`subscribe()` skips an
event `addEventListener` refuses, so the others still come). The harness's instance posts the
event when `bitrate` is set to another value.

### Ratings: Favourite and Suggest Less

An item has one rating, `PUT /v1/me/ratings/<type>s/<id>` with `{type: 'ratings',
attributes: {value}}` (the bridge's `rating(kind, id, value)`): 1 is a favourite
(`Engine.love()`), -1 Suggest Less (`Engine.suggest_less()`), and `DELETE` takes either
away (`Engine.unlove()`); `Engine.rating()` reads it back from `GET
/v1/me/ratings/<type>s?ids=<id>`. `<type>` is `api.resource_type()`'s, singular (the bridge
adds the `s`): `song`, `album`, `playlist`, `station`, `music-video`, or `library-<type>` for
a library id (but a station's). A PUT
replaces the rating there was, so Suggest Less replaces a favourite and Favourite a Suggest
Less. Checked against a real account on 2026-10-20 (MusicKit
`playback/AppleMusic-2642.7.0-external`, the `gb` storefront) on a song:

| Request | Apple's answer |
|---|---|
| `PUT /v1/me/ratings/songs/<id>` `{type: 'ratings', attributes: {value: -1}}` | 200 with the rating (`value` -1): Suggest Less. `GET` answers it, the catalog read gives `personalRating: -1`; `DELETE` takes it away (204, then 404). The web player offers Suggest Less for albums, artists, music videos, playlists, songs and stations, and not with a favourite |

The menus follow the web player: Favourite or Remove from Favourites, and Suggest Less (not
beside a favourite) or Undo Suggest Less (`actions.rating_actions()`). An artist's favourite
is not a rating ("Favourites of artists", below): an artist's menu has Favourite or Remove
from Favourites alone (`actions.favourite_items()`).

### Favourites of artists

An artist's favourite (Apple's star on the artist page, which shapes recommendations; #357)
is not a rating, and favouriting an artist does not add them to the library. The app writes
it with the bridge's `favourite('artists', id, on)` (`Engine.favourite_artist()`,
`unfavourite_artist()`) and reads it as the artist page's `inFavorites` (`extend=inFavorites`
in `api.ARTIST_PARAMS`: no request more), or alone through `apiFresh` with
`api.FAVOURITE_PARAMS` (`Engine.is_favourite_artist()`, which an artist's menu asks as it
opens). The engine remembers what it wrote and read this session over a page kept for a day,
and a write patches the kept page (`normalize.patch_answer()`, its `cached` stamp kept).
Checked against a real account on 2026-10-20 (MusicKit `playback/AppleMusic-2642.7.0-external`,
the `gb` storefront), one artist favourited and unfavourited, put back:

| Request | Apple's answer |
|---|---|
| `POST /v1/me/favorites?ids[artists]=<catalog id>` | 202. The web player's `UpdateFavoritesIntent`, which takes any `ids[<type>]`; DELETE to unfavourite (204) |
| `GET /v1/catalog/<sf>/artists/<id>?extend=inFavorites` | `attributes.inFavorites`, a boolean, true within 200 ms of the POST |
| `GET /v1/catalog/<sf>?ids[artists]=<id>&fields[artists]=personalRating&relate=library&omit[resource]=autos` | `personalRating: 1` while favourited, absent otherwise (how the web player's menus read it; the app reads `inFavorites`) |
| `GET /v1/me/ratings/artists/<id>` | 404 whether favourited or not: an artist's favourite is not a rating |

The catalog read that finds an item's library twin (`api.library_twin_params()`, above) also
gives `personalRating` (1 favourite, -1 Suggest Less, absent for none) with
`fields[<type>]=inLibrary,personalRating`.

### The editorial groupings: New and Radio

The Radio page (`groupings?name=radio`, below) and the New page (`name=music`) answer one
`groupings` resource whose `tabs` hold one `editorial-elements` (kind 382) with `children`,
each a shelf by `attributes.editorialElementKind` (checked live on 2026-10-20):

| Kind | What it is |
|---|---|
| 316 | the hero row: children 320 (wide, with `artwork`, `editorialArtwork`, `designBadge` such as "UPDATED PLAYLIST", `designTag`, sometimes `editorialVideo`), 317 and 383 (`designBadge`), each one resource in `contents` |
| 488 | Radio's live stations: children 489, each one live station in `contents` and a `stationGlyph` (the station's logo with its colours) |
| 326 | a shelf: `name`, `displayStyle` (`compact`, `expanded`), `contents` (albums, playlists, stations, `apple-curators`, `music-videos`, `uploaded-videos`), and `room`, its See All |
| 327 | a shelf of songs |
| 385 | New's "New for <month>": children 386 (an `apple-curators` in `contents`) and 394 (`artwork`, `designTag`, and a `link` or an `apple-curators`) |
| 391 | More to Explore: `name` and `links`, `[{label, url, target?}]` |
| 322 | untitled `links`, every one a genre's grouping |

`normalize._grouping_shelves()` makes a shelf of every titled element with something in its
`contents` or its children's (326, 327, 385's curators, 488), and of the first untitled one
made of children (316) the featured shelf; `radio_shelves()` tells 316 and 488 apart
(`RADIO_HERO_KIND`, `RADIO_LIVE_KIND`). New's (`editorial_shelves()`, through
`_grouping_parts()`) also has, for the featured shelf's items, what their banners show
(`featured_extras()`, below) and, as `links`, the 391 and 322 rows (`element_links()`,
below). A room (a 326's See All), `designTag`, `stationGlyph` and a 394's `artwork` are not
used yet.

### New's banners and More to Explore (#370)

New's answer (`Engine.browse()`, `normalize.editorial_shelves()`) is `{shelves, links}`:

- the featured shelf's items carry, from the hero row's child that holds each:
  `badge`, the child's `designBadge` ("NEW ALBUM", in the account's language); `banner`, a
  wide artwork as `normalize.wide_artwork()` makes one (`{url, crop, width, height,
  color}`, the template cut `sr`, its source's shape): the child's own `editorialArtwork`
  (a 320's), else its content's (a 317's), the first of `subscriptionHero` and
  `superHeroWide` (`BANNER_ARTWORK_KEYS`). A template with an effect code
  (`…_cropped.png/{w}x{h}SH.FPESS04.jpg?l=en-GB`, 3 banners in 15 live, all Essentials
  playlists: Apple's composite of the artist's picture on a colour beside the word) is
  kept as it is, query and all, its `crop` the effect code (`normalize.template_effect()`):
  an `sr` cut of its source crops the picture, where the composite is made for the
  4320x1080 shape. And `tagline`, the content's
  `plainEditorialNotes` `tagline`, else `short` (else the child's). The shelf is `form:
  'banners'` when one item has a banner (the page's wide cards), else a plain featured
  shelf (hero cards). Radio's hero gets none of it;
- `links`, each row `{key, title, links}` (391's `name` its title, 322's untitled), each
  link `normalize.editorial_link()`'s `{title, kind, id, url[, genre]}`, each once:

| URL | `kind` | What the app opens |
|---|---|---|
| `https://itunes.apple.com/<sf>/collection/<slug>/id<n>?fcId=<id>&mt=14`, `…/viewRoom?fcId=<id>`, `https://music.apple.com/<sf>/room/<id>` | `room` | `Engine.room(id)`: `GET /v1/editorial/<sf>/rooms/<id>` (`api.ROOM_ENDPOINT`), `rooms` with `title`, `sorts`, `contents` (up to 100): `normalize.editorial_room()`'s `{id, title, items}`, a grid |
| `…/viewGrouping?cc=<sf>&id=<id>` | `grouping` | `Engine.grouping(id)`: `GET /v1/editorial/<sf>/groupings/<id>` with `api.GROUPING_PARAMS` (`platform=web`, without which it is a 400, "A single platform must be supplied"; `extend=editorialArtwork`), the same shape as New: `editorial_grouping()`'s `{id, title, shelves, links}` |
| `…/viewMultiRoom?cc=<sf>&fcId=<id>` | `multiroom` | `Engine.multiroom(id)`: `GET /v1/editorial/<sf>/multirooms/<id>` with `api.MULTIROOM_PARAMS` (`extend=editorialArtwork,uber,lockupStyle`): `multirooms` with `title`, `uber` (`masterArt`, `name`, `description`, colours) and `children` (404 a header, 345 shelves with `contents` and `room`): `editorial_multiroom()`'s `{id, title, shelves, links}` |
| `…/viewTop?genreId=<n>`, `https://music.apple.com/<sf>/charts` | `charts` | the Charts page, on the genre `genre` names (an `api.is_genre_id()` id) when the link has one other than Music's (`api.ROOT_GENRE`, 34, the genre without a parent: New's "Charts" link names it, and its charts are every genre's, All Genres) |
| any other https URL, or one with `target: 'external'` (`https://music.apple.com/concerts`) | `link` | the browser |

The `music.apple.com/<sf>/room/<id>` and `/charts` forms were not among the links seen live
(checked on 2026-10-20): they are read as the web player's own routes. A link's id goes into
a path: one that is not `api.is_editorial_id()` is no link. Each of
the three pages is kept a day (`rooms/`, `groupings/`, `multirooms/`, by id). The
`uber`'s art and description, and a 345's `room`, are not shown.

### The Radio page

`Engine.radio()` asks `GET /v1/editorial/<sf>/groupings` with `api.RADIO_PARAMS`
(`name=radio`, `platform=web`, without which it is a 400, `tabs=subscriber`,
`extend=editorialArtwork`, `include[stations]=events,radio-show`), the web player's request
for its Radio page less `extend[station-events]=editorialVideo`, checked live on 2026-10-20.
The answer is the editorial grouping New's is (see "The editorial groupings" above for its
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
  category page (`bridge.category()`: its episodes and playlists; see below);
- the 391 (More to Explore) and 322 (genre links) elements have no `contents` and are left
  out, as on New, and so are `uploaded-videos`.

### Home's Recently Played

`Engine.recently_played()` asks Apple's documented `GET /v1/me/recent/played`
(`api.RECENT_PLAYED_ENDPOINT`), `limit=10` (its documented most) by `offset`, up to 30,
following `next`; a later page that fails keeps the pages read, the first must answer. The
resources (albums, playlists, stations, the library's or the catalog's, newest first) are
shaped by `normalize.recently_played()` into `{items: [Item]}`, each once, as a shelf's
items (no track lists; artwork as a search hit's), and kept in `recent-played.json`. Home
shows the kept answer at once and asks again with `refresh` once it is a minute old
(src/home.py). Not yet checked live: which resource types the account's answer holds, and
how far `offset` goes. Apple's recommendations (`/v1/me/recommendations`) may carry a
`reason` (`{stringForDisplay}`, documented): `normalize.recommendation_reason()` keeps it
as the shelf's `subtitle` unless it only says the title again.

### An artist's banner

The artist page's header (#355). The web player's artist page asks `GET
/v1/catalog/<sf>/artists/<id>` with
`extend=artistBio,editorialArtwork,editorialVideo,extendedAssetUrls,hasBiographyContent,hero,keyColor,plainEditorialNotes`
(and its canvas shelves). Its wide header is `editorialArtwork.centeredFullscreenBackground`
(4320x2160, crop `sr`) when there is one (1 artist in 24), else the portrait in
`attributes.hero[0].content[0].artwork` cut with crop code `vf` when its
`recommendedCropCodes` lists `vf` (11 in 23); with neither, the round portrait. The hero
artwork is the artist's `artwork` itself (square, 902 to 6000 px) with
`recommendedCropCodes` from `va vb vc vd vf vn`; `{w}x{h}vf.jpg` in place of
`{w}x{h}bb.jpg` answers an image of exactly that size cropped where Apple chose (2400x1000,
3000x1000), where `bb` fits the square inside it. Some `hero[0]` entries have no `content`.
Other keys seen: `originalFlowcaseBrick`, `storeFlowcase`, `subscriptionHero`,
`musicContentColorLogoTrimmed` (a logo); `bannerUber` is a curator's, never an artist's.
Checked against a real account on 2026-10-20 (24 catalog artists, the `gb` storefront).

The app adds `editorialArtwork,hero` to its own `extend` (`api.ARTIST_PARAMS`), and
`normalize.artist_banner()` makes the answer's `banner`, `{url, crop, width, height,
color}` (the template with its crop, `{w}x{h}` left to fill; the source's size; Apple's
`bgColor`), by the web player's rule, or None. `remote.fetch_banner()` asks it at the
header's width in device pixels, in steps of 480, no wider than the source: a `vf` cut at
3:1, an `sr` one at its own 2:1 (that `sr` answers sizes other than 4320x2160 is to be
confirmed live), into `remote-art/`. The demo's invented banners carry `art`, a file, and
no `url`.

### Curators and radio shows

An `apple-curators` resource has `attributes.kind` `Show` (a radio show, with
`showHostName`), `Genre` or `Curator`; third parties are `curators`. None has `playParams`:
nothing plays a curator, and there is nothing to favourite (checked live on 2026-10-20).
`normalize.normalize_curator()` makes every one a category tile (kind `category`, a show
subtitled with its host) wherever Apple puts one: a grouping's shelf (New's "New for …",
Radio, a category page), the search landing, an artist's `view/radio-shows`, and
`normalize_item()`, which never makes one a station. Its menu is Open in Browser and Copy
Link alone (`actions.curator_menu()`), and its tile opens its page:

- `bridge.category(id)` asks `GET
  /v1/catalog/<sf>/apple-curators/<id>?include=grouping,playlists&include[editorial-elements]=children,contents,room&extend=editorialArtwork&platform=web`,
  music.apple.com's request. `normalize.category_page()` makes `relationships.grouping`'s
  326 shelves (a show's: its episodes, as `stations`, and albums and playlists) into
  shelves, then `relationships.playlists`, less those already shown, into one keyed
  `playlists` (untitled: the app names it);
- an artist's `view/radio-shows` is not empty for the hosts of Apple's shows (21 of 24
  tried), every entry an `apple-curators` of kind `Show`: the artist page's Radio Shows
  (`CURATOR_VIEWS`). Their `view/more-to-hear` holds the episodes (`stations`, `streaming`,
  not live), which play as stations;
- search answers curators only when asked for (`types=apple-curators`, and `curators` for
  third parties): `api.SEARCH_TYPES` asks for both. `normalize.search_results()` shelves
  Apple's of kind Show as `radio-shows` and the rest as `curators`, each marked
  `curatorKind`; a third party's has no page the app can read (`category()` asks
  `apple-curators`), so it is a link to music.apple.com's (`curator_link()`);
- a catalog playlist's curator (its `curator` relationship, `include=curator`) is the link
  under its title: an Apple curator's category page, a third party's page in the browser
  (`normalize.playlist_curator()`; its shape under library.json below).

### The Charts page

`Engine.charts()` asks `GET /v1/catalog/<sf>/charts` with `api.CHARTS_PARAMS`
(`types=songs,albums,playlists,music-videos`, `limit=100`, and
`with=dailyGlobalTopCharts,cityCharts` for the Daily Top 100 and City Charts playlists);
a 400 is asked again without `with` (`api.CHARTS_PLAIN_PARAMS`, the documented request).
Not checked live yet: the `with` values and the keys they answer under are the web
player's as remembered, so the normaliser takes any key. The documented answer is
`results`, one entry per type, each a list of charts `{chart, name, orderId, href, next,
data}` (`chart` `most-played`, `name` Apple's title in the account's language, "Top Songs",
`data` the resources in chart order). `Engine.charts(genre=<id>)` narrows it to a genre
(`api.charts_params()`: `CHARTS_PLAIN_PARAMS` and `genre=<id>`, without `with`: the Daily
Top 100 and City Charts are no genre's; an id that is not `api.is_genre_id()`, digits, is
`usage`), kept as `charts/<id>.json`. The genres the page offers are `Engine.genres()`:
`GET /v1/catalog/<sf>/genres` (`api.GENRES_ENDPOINT`, no parameters), Apple's documented
`genres` resources `{id, attributes: {name, parentId, parentName}}`, shaped by
`normalize.catalog_genres()` as `{genres: [{id, title}]}` in Apple's order, the genre the
others belong to (Music, without a parent and every other's parent: what the charts are
without a genre) left out, kept as `genres.json` for a day. Not checked live yet: the
`genre` parameter with `types` of four kinds, and whether the list is the top level alone
or the subgenres too.
`normalize.charts_shelves()` makes a shelf of each chart with something in it, in the
page's order (`CHART_ORDER`: songs, albums, playlists, `dailyGlobalTopCharts`,
`cityCharts`, music videos, then any other key), keyed `charts-<key>`, with `chart` (the
key) and Apple's `name` as its title ('' without one: the app names it,
`remote.CHART_TITLES`); the rankings (`RANKED_CHARTS`) are `ranked`, Top Songs
`form: 'songs'`, and a song carries its `album`. The page is kept as `charts.json` for a
day.

### Replay (#365)

`Engine.replay()` asks three reads, their shapes checked live on 2026-10-20 (the web player
loads its Replay page from a module of its own, `replay.esm.js`, which the bundles read here
do not hold):

- the summary (`api.replay_request()`): the latest year's as
  `GET /v1/me/music-summaries?filter[year]=latest&views=top-songs,top-artists,top-albums`
  (`api.REPLAY_ENDPOINT`), a past year's as its own resource,
  `GET /v1/me/music-summaries/year-<YYYY>?views=…` (`api.REPLAY_YEAR_ENDPOINT`;
  `api.is_replay_year()`, four digits, anything else is `usage`), since Apple answers
  `filter[year]=<YYYY>` with a 400 (`?ids=year-<YYYY>&views=…` answers too). `data` is one
  `music-summaries` resource `{id: 'year-<YYYY>', attributes: {name, period: 'year',
  topSongCount, year}, relationships: {playlist: {data: [{id, type, href}], meta: {title}}},
  meta: {views: {order}}, views}`, `year` a number; the latest answer's `meta.filters.year
  .latest[0]` names its resource. Each view (`top-songs`, `top-artists`, `top-albums`) is
  `{href, attributes: {title, shortTitle, subtitle, highlights}, meta: {count, types}, data}`
  with every item in the one page (no `next`; up to a hundred songs, some fifteen albums and
  twenty artists). An item is a **period summary**, not the song, album or artist:
  `{id, type: 'song-period-summaries' | 'album-period-summaries' | 'artist-period-summaries',
  attributes: {playCount, firstPlayed, lastPlayed, year, listenTimeInMinutes?},
  relationships: {song | album | artist: {data: [resource]}}}`, in rank order. An album or
  artist there is the whole catalog resource, with its attributes; a song is
  `{id, type: 'songs', href}` alone, its catalog id. A 400 or a 404 is taken as no summary
  (no listening history for the year), anything else is the command's;
- the top songs, `GET /v1/catalog/<storefront>/songs?ids=…` (`api.REPLAY_SONGS_ENDPOINT`,
  `api.replay_songs_params()`): the summary's song ids (`normalize.replay_song_ids()`, in
  rank order, each once, catalog ids only), up to a hundred in one read, which Apple answers
  in an order of its own. A 404 is none of them (no Top Songs), anything else is the
  command's; without songs to ask for it is not asked;
- the years, `GET /v1/me/music-summaries/search?period=year&fields[music-summaries]=period,year&include[music-summaries]=playlist`
  (`api.REPLAY_YEARS_ENDPOINT`, `api.REPLAY_YEARS_PARAMS`), the web player's Replay listing:
  a `music-summaries` resource a year, newest first, `{id: 'year-<YYYY>', attributes:
  {period: 'year', year}, relationships: {playlist: {data: [playlist]}}}`, the playlist that
  year's Replay playlist, inline with its attributes (nothing in `included`). Its failing
  (but for `engine-down`) is no years.

`normalize.replay_page()` makes `{year, years, shelves}` of them: `year` the summary's (its
`attributes.year`, else its id's, else the year asked), `years` every year the listing has,
newest first, as strings (`normalize.replay_years()`); a shelf of each view with something
in it, in `normalize.REPLAY_VIEWS`' order, keyed `replay-<chart>` (`songs`, `artists`,
`albums`), with `chart`, `ranked` and Apple's view title ('' without one: the app names it,
`remote.CHART_TITLES`), its items the resources the period summaries hold, a song the
catalog read's (one it did not answer left out), Top Songs `form: 'songs'`, a song with its
`album`, as a chart's; then the years' playlists, newest first (`replay-playlists`,
untitled). The latest year's is kept as `replay.json`, a past year's as
`replay/<year>.json`, a day each, with `normalize.REPLAY_SHAPE` as their `basis`: one kept in
an older shape (without it, as before the period summaries were read) is asked again. Not
read: the play counts and minutes listened, the highlights and the milestones the web
player shows.

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
position and duration. So a live item is told by its type and `isLive`, not by its duration:
`formatTrack()` gives it `isLive: true` (`isLiveRadioStation`, or the type with
`attributes.isLive`), and `capabilities` (all false) come with its item and its states. The
app shows LIVE in place of the slider and the times, Stop in place of Pause, Next,
Previous, Shuffle and Repeat off (whatever the capabilities say: a mode set on a stream
would only change what plays after it), and publishes no length or position on MPRIS
(src/player.py's `live`).

### A song's credits (#364)

View Credits reads `GET /v1/catalog/<sf>/songs/<id>/credits` (`api.SONG_CREDITS_ENDPOINT`,
through the bridge's `api()`; `include=credits` on the song answers the same, and the web
player asks `include=albums,artists,credits,lyrics,music-videos`), about 250 to 300 ms
(checked live on 2026-10-20): `data` is the song's `role-categories`, each `{attributes:
{kind, title}, relationships: {'credit-artists': {data}}}`, `kind` `performer`,
`composer-and-lyrics` or `production-and-engineering` (all three on the six songs tried),
`title` Apple's heading for it in the account's language; a `credit-artists` entry is
`{id, type, attributes: {name, roleNames: [..], artwork?}}`, its id (`<n>-ami:identity:<hex>`)
not an artist's catalog id, so a credit links to no artist page. `Engine.credits()` keeps
`normalize.song_credits()`'s `{categories: [{kind, title, people: [{name, roles}]}]}` in
`credits/<id>.json` for a day; Apple's 404 is no categories. A library song is asked by its
catalog id, and one without (an upload) has no View Credits.

## Checked live, not used yet

What music.apple.com's own code asks for, and what the API and MusicKit answered, checked
against a real account on 2026-10-20 (MusicKit `playback/AppleMusic-2642.7.0-external`, the
`gb` storefront), for the features still to build. Only the shapes are kept here. Every
write was made on items picked for the check and put back. Reads go through `music()`;
the writes, and any read that must see a write (MusicKit's `music()` may answer from a
cache), go through the request builder, as `apiWrite()` does.

### Moving queue entries (#361)

A move is two `queue.spliceQueueItems` calls on the queue items (the queue section above):
`spliceQueueItems(from, 1)`, then `spliceQueueItems(to, 0, taken)`, and so two
`queueItemsDidChange`; the next item played follows the new order. The web player has no
reorder of its own. Whether an entry moved into or out of autoplay's keeps its `isAutoplay`
was not tried. The bridge's `queueMove` (#361) is these two splices: the first's event is
not posted (a flag set around it), so the app sees the queue moved and never one an entry
short, whether MusicKit posts during the call or after it (the snapshot is read as the
queue is then). It keeps a move within its section (what the user queued, or what autoplay
added), so an autoplay entry is never moved among the user's. Removes and moves carry the
Player's number for them (`edit`), and every queue snapshot names the last applied: while
the Player has edits out (a burst of Alt+Down or Delete), a snapshot tells it which it
holds, and it replays the others onto it before comparing it with its queue
(`Player._rebased`). Not checked live yet: moving the next entry (`position + 1`) further
down and letting the item end on its own (does MusicKit play the new next item, or one it
had loaded ahead?); a move with Shuffle on, then Shuffle off (is the move kept?); whether
MusicKit posts `queueItemsDidChange` during `spliceQueueItems` or after it. `queue.removeQueueItems(predicate)` removes every queue item
`predicate(queueItem, index)` accepts, from the end, one event each; `mk.clearQueue()` (the
web player's Clear) empties the whole queue (`position` -1, `length` 0) while the current
item plays on, so it is not Up Next's Clear.

### The editorial pages' rooms and design keys

What the editorial groupings ("The editorial groupings" above) hold that the app does not
use yet: a 326 shelf's `room` (its See All: `GET /v1/editorial/<sf>/rooms/<id>`, which
`Engine.room()` asks for a link's room), `designTag`, `stationGlyph`, a 394's `artwork`, a
multiroom's `uber`. A live station's events also carry `heroArtwork`, and some an
`editorialVideo` (the web player's `extend[station-events]=editorialVideo`), which the
Radio page does not use.

### A radio show's banner (#401)

A show's page (the category page, "Curators and radio shows" above) carries its banner in
the curator's `editorialArtwork`: `bannerUber`, else `subscriptionCover`, else
`subscriptionHero`. `normalize.curator_banner()` takes the first of these
(`CURATOR_BANNER_KEYS`) that has an https template and a size, as `wide_artwork()` makes it
(`{url, crop, width, height, color}`, cut `sr`, `CURATOR_BANNER_CROP`: the source's shape),
whatever the curator's `kind` (a genre or an editor carrying one gets it too), and
`category_page()` answers it as `banner` (or None), with the show's `host`
(`showHostName`, '' for any other kind). The category page (pages/shelves.py) puts its
title and the host in white at the foot of that banner (widgets/banner.py's
`ArtistBanner`, fetched by `remote.fetch_banner()` as an artist's is), else on the page.
The demo's shows carry invented 3:1 banners on disk (`art`, no `url`), but the last.
Not checked live yet: the keys' sizes and shapes (whether `sr` answers other sizes than
the source's), and which genres and editors carry them.

## Events

The client dispatches each bridge event as `am:<name>`; the Engine re-emits it as
`event(name, data)`. The data is read from the instance at the moment of the event.

| Event | Data |
|---|---|
| `authorizationStatusDidChange` | `{authorized, status}` |
| `playbackStateDidChange` | `{state, position, duration, capabilities}`; a play walks `playing`, `waiting`, `loading`, `playing` |
| `nowPlayingItemDidChange` | `{track: Track or null, index, capabilities}` |
| `capabilitiesChanged` | `{capabilities}`, as `nowPlaying()` gives them: what MusicKit allows changed |
| `playbackTimeDidChange` | `{position, duration}` in seconds, about four times a second while playing |
| `playbackDurationDidChange` | `{duration}` |
| `queueItemsDidChange` | `{index, items: [Track], editable, canAutoplay, autoplay, edit}`, as `queue()` answers (index -1 before playback starts); not posted for the queue between a move's two splices |
| `queuePositionDidChange` | `{index, oldIndex}` |
| `shuffleModeDidChange`, `repeatModeDidChange` | `{shuffle: "on"\|"off"}`, `{repeat: "none"\|"one"\|"all"}` |
| `playbackVolumeDidChange` | `{volume}` |
| `mediaPlaybackError` | `{code, message}` (`code`: MusicKit's `errorCode`, such as `CONTENT_UNAVAILABLE`, else '') |
| `autoplayEnabledDidChange` | `{autoplay}`: MusicKit's autoplay turned on or off |
| `playbackBitrateDidChange` | `{bitrate}`: the kbps MusicKit streams at changed (the app's set, or MusicKit's own choice); the event's `bitrate`, else `mk.bitrate` ("Streaming quality") |
| `previewDidChange` | `{id}` as a preview starts; `{id: null, ended, reason}` as it stops (`ended` its id; `reason` `ended`, `error`, `stopped`, `replaced` or `playback`, MusicKit taken in hand). The bridge's own, not MusicKit's |
| `bridgeReset` | `{}`: the client's own, after it put the bridge back into a new document |

## library.json

`<cache>/library.json`, written by `src/sync.py` (and `scripts/demo_library.py`), read by
`src/library.py`. Version 5: a Track carries its `genre` and `year`; version 4: the shape
of 3, written by a full sync (a short pass keeps the version of the file it kept from, and
1.0.0's could stamp 3 on a file without 3's keys);
version 3: Items carry `added` and the file `favourites`; version 2: an album's track
`index` counts on across its discs. The app syncs an older file again at once (an older one
still reads: no dates, no hearts, Recently Added Apple's shelf).

```jsonc
{
  "version": 5, "generated": "2026-09-25T12:00:00Z", "storefront": "us",
  "sections": {"albums": [Item], "artists": [Item], "playlists": [Item], "radio": [Item],
               "videos": [Item]},
  "shelves": [{"key": "rec-<id>", "title": "…", "items": [Item],   // Apple's recommendations
               "subtitle": "…"},                // its reason, when Apple gives one
              {"key": "heavy-rotation", "title": "", …}, {"key": "recently-added", …}],
                                                // empty titles: the app titles them by key
  "folders": [{"id": "root", "title": "", "parent": null,
               "children": [{"kind": "playlist", "id": "p.…"}, {"kind": "folder", "id": "p.…"}]}],
  "favourites": {"songs": ["<catalog id, else i.…>"], "albums": ["l.…", "<catalog id>"],
                 "playlists": ["p.…"], "videos": ["i.…", "<catalog id>"]}
                                                // the account's favourites (inFavorites)
}

Item = {
  "id": "l.…",                  // library id, or catalog id when not in the library
  "kind": "album" | "playlist" | "artist" | "station" | "video" | "song" | "link",
  "title": "…", "subtitle": "…", "year": 2007, "genre": "…", "summary": "…" /* or null */,
  "art": "<cache>/art/<sha1>.jpg" /* or null */,     // 640 px, the pages' hero
  "thumb": "<cache>/thumb/<sha1>.jpg" /* or null */, // 320 px, tiles and rows
                                                     // (a video's <sha1>-wide.jpg, 320 px high)
  "artUrl": "https://…/640x640bb.jpg",               // for fetching `art` on demand
  "artColor": "#1a1a1a" /* or null */, "explicit": false,
  "trackCount": 12, "durationMs": 2580000,           // albums, playlists (videos: length)
  "albumCount": 3,                                   // artists
  "catalogId": "…" /* or null */, "url": "https://music.apple.com/…" /* or null */,
                                // a library playlist's: its playParams' globalId ("pl.…",
                                // not checked against the API yet)
  "attributes": {"isFavourites": true, "canEdit": false, "canDelete": false},   // playlists,
                                                     // when they apply
  "added": "2025-05-01T09:00:00Z",                   // Apple's dateAdded, as Apple writes it
                                                     // (albums, playlists; videos when
                                                     // dated): left out when unknown
  "modified": "2025-05-01T09:00:00Z",                // playlists: Apple's lastModifiedDate as
                                                     // last listed (an item() answer's, its
                                                     // own): the page's "Updated"
  "tracksModified": "2025-05-01T09:00:00Z",          // playlists, the sync's: lastModifiedDate
                                                     // as listed when `groups` was last read,
                                                     // kept while it holds (sync.py); left out
                                                     // when a short pass read them (an edit)
  "prerelease": true,                                // an album not out yet (Apple's
  "releaseDate": "2026-12-04",                       // isPrerelease) and when it comes: only
                                                     // then (normalize.is_prerelease())
  "play": {"kind": "album", "id": "l.…"},            // what the bridge's play() takes
  "groups": [{"name": "Disc 1", "play": {…}, "entries": [Track]}]   // an album's discs, a
                                                     // playlist's "Tracks", an artist's albums
}
Track = {"id": "i.…", "catalogId": "…" /* or null */, "title": "…", "artist": "…",
         "album": "…", "trackNumber": 1, "discNumber": 1, "durationMs": 216000,
         "durationLabel": "3:36", "explicit": true,
         "index": 0,                     // its place in its group's `play` queue
         "thumb": "…" /* or null */,     // a playlist's rows
         "type": "library-songs",        // the API's: songs, music-videos, library-…, or ''
                                         // (the item playing may carry MusicKit's own
                                         // 'song' or 'musicVideo' instead)
         "genre": "…" /* or null */,     // the first of its genreNames (version 5)
         "year": 2007 /* or null */,     // its releaseDate's year (version 5)
         "artUrl": "…" /* or null */,    // the bridge's: the artwork at 256x256, for MPRIS
         "unreleased": true,             // a pre-release album's track not out yet: Apple
                                         // gives it no playParams (only then:
                                         // normalize.track_released())
         "autoplay": true,               // a queue entry autoplay added (only then)
         "isLive": true}                 // the item playing is a live radio station (only
                                         // then: its type 'radioStation', durationMs 0)
```

A pre-release album (`attributes.isPrerelease`, Apple's, with a `releaseDate` to come) is
shaped by `normalize.normalize_album()` with `prerelease` and its `releaseDate`, wherever it
comes from (an item() answer, a shelf, a search, an artist's latest release), and each of its
tracks without `playParams` (`normalize.track_released()`: one not out yet; a pre-release
single has them) with `unreleased`. An album out has none of the three keys, whatever its
tracks' playParams (a playlist's entries Apple cannot play are not marked). Apple's
`isComplete` (false until every track is out) is not read: the tracks say it. The album's
page plays only the tracks out, by id (`release.released_play()`), never the album, so
MusicKit is never asked for a track it cannot play. An item() answer of the album once out,
with its groups, takes `prerelease` and `releaseDate` off the Item it merges into
(`Item.merge()`). Not checked live: what Apple's answer holds for a pre-added album in the
library (its library songs, and whether a library album carries the flag).

The dates and favourites come with the listings the sync reads (`sync.SONGS_PARAMS`,
`PLAYLIST_PARAMS`, `VIDEOS_PARAMS`: `extend=inFavorites`, the songs' included albums by
`extend[library-albums]=inFavorites`), no request more: `normalize.date_added()` keeps a
library resource's `dateAdded`, `normalize.favourite_ids()` the ids of those with
`inFavorites: true` (a song by its catalog id, else its own: the id the app rates it by;
anything else by its library and catalog ids). Apple's documentation gives `dateAdded` to
library albums (a date) and playlists (a date and time), not to songs or music videos, and
`inFavorites` to library songs, albums, playlists and music videos. Checked live on
2026-10-20 (read only, counts kept, nothing else): of 100 library songs read with
`extend=inFavorites`, every one carried the key, 3 were rated 1 (the app's favourite) and
those 3 were `inFavorites: true`, with no mismatch either way, so a favourite made by the
app's rating write reads back as one; every included album carried both `inFavorites` and
`dateAdded`, and 50 of 50 albums' `dateAdded` were full timestamps (to the second), not the
documented date; no song carried `dateAdded` (0 of 100); the extended read took no longer
(1.33 s plain, 1.21 s extended, for 100 songs). Music videos were not tried (that library
had none): the app offers their Date Added only when the data has it.

An artist's page (`Engine.artist_page()`, `normalize.artist_page()`) is
`{id, artist, banner: {url, crop, width, height, color} | null, latest: {key, title, item} |
null, topSongs: {key, title, items, more} | null, shelves: [{key, title, items, more}],
favourite: bool | null}`:
`artist` an Item without groups whose `summary` is the biography, with `origin`,
`bornOrFormed` (Apple's own words) and `isGroup` where Apple has them; `banner` the wide
header ("An artist's banner" above); `latest` the featured or latest release, with its
`releaseDate`; the top songs song Items with their `album`; each shelf one of the artist's views in music.apple.com's
order, titled as Apple titles it, `more` when `Engine.artist_view()` has more of it. A
video about the artist (an interview, a film) is a `link` Item marked `"video": true`
(its tile a 16:9 frame, its thumbnail asked 320 px high, as a music video's): its `url` is
its page, its subtitle its length, and it has nothing to play. `favourite` is the artist's
`inFavorites` (`normalize.in_favourites()`; null when Apple does not say): the star
("Favourites of artists" above).

What an album's page shows under its tracks (`Engine.album_page()`, `normalize.album_page()`)
is `{id, artistId, artistName, release: {releaseDate?, copyright?, recordLabel?},
shelves: [{key, title, items, more}]}`: `id` the catalog album's, `release` what its footer
says (`normalize.album_release()`: each key only where Apple has it), and the shelves in
music.apple.com's order: `other-versions`, `related-videos`, `more-by-artist`, `appears-on`
and `you-might-also-like`, all but More By the album's own views (`api.ALBUM_VIEWS`, one read
with the album: `views=other-versions,related-videos,appears-on,you-might-also-like`, each
under the album's `views` as `{href, attributes: {title}, data, next?}`), titled as Apple
titles them. Apple has no `related-albums` view (never in the answer; `/view/related-albums`
is a 400). The shelf `more-by-artist` is a page of the first artist's `full-albums` view,
less the album, untitled (the app names it "More By …"); Apple's album has a
`more-by-artist` view too, which the app does not ask for. `more` when
`Engine.album_view()` (or `artist_view()` for More By) has more. A library album is asked
by its own id and one of its songs' catalog ids, through which the engine finds its catalog
album (`api.SONG_ALBUMS_PARAMS`); the answer is kept under the id it was asked by, with the
views asked as its `basis`, so one kept with other views is asked again.

What a catalog playlist's page shows under its tracks (`Engine.playlist_page()`,
`normalize.playlist_page()`; #371) is `{id, curator, shelves: [{key, title, items, more}]}`
from two reads: `GET /v1/catalog/<sf>/playlists/<id>` with `api.PLAYLIST_PARAMS`
(`include=curator`, `views=featured-artists,more-by-curator,you-might-also-like`), then,
for a playlist of an Apple curator's, a page of `api.CURATOR_PLAYLISTS_LIMIT` (10) of the
curator's playlists, `GET /v1/catalog/<sf>/apple-curators/<id>/playlists` (its failure only
leaves More By out), kept a day in `playlists/<id>.json` with the views as its `basis`.
`curator` is the playlist's `curator` relationship (`normalize.playlist_curator()`): an
`apple-curators` is its category tile, titled with its whole name (its page the category
page, "Curators and radio shows" above; with its id alone, named by the playlist's
`curatorName`), a third party's `curators` or a shared playlist's listener's
`social-profiles` a `link` to its `url` on music.apple.com (a listener's is
`https://music.apple.com/profile/<handle>`; none without an https page), anything else
None. The shelves are the views in that order, titled as Apple titles them (the app names
an untitled one: Featured Artists, "More By <curator>", You Might Also Like), each under
the playlist's `views` as the album's are; More By is the curator's playlists, under the
view's title; the curator's and the alike playlists leave the playlist itself out; `more`
when `Engine.playlist_view()` (`Engine.curator_playlists()` for More By) has more. Only a
playlist of the catalog's is asked (`release.playlist_target()`: a `pl.` id, its own or the
catalog id a library playlist of Apple's carries; never the user's, Favourite Songs or a
`pl.u-` one shared from an account).

Checked live on 2026-10-20 (20 catalog playlists, the `gb` storefront): `include=curator`
answers an Apple curator's `name`, `kind` and `url`, and every shared playlist
(`playlistType: "user-shared"`) has a `social-profiles` curator (`name`, `handle`, `url`,
`isPrivate`, `isVerified`); a few editorial ones have no curator relationship at all, only
`curatorName`. `featured-artists` is never empty, titled "Featured Artists" (or "Featured
Artist"). `more-by-curator` is always there and always empty (`data: []`, no `next`),
titled "More By <curator>" on about half; `extend=editorialArtwork` and
`with=curatorContent` leave it empty, and its `/view/more-by-curator` is a 404, hence the
curator's own playlists (`api.PLAYLIST_READABLE_VIEWS` leaves it out of See All's views).
Apple leaves `you-might-also-like` out of a playlist's answer (no 400), so the
`api.PLAYLIST_PLAIN_PARAMS` retry has never run; `views=contributors` answers an empty view.

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
| `landing.json`, `categories/`, `browse.json`, `rooms/`, `groupings/`, `multirooms/`, `made-for-you.json`, `radio.json`, `charts.json`, `replay.json`, `replay/`, `recent-played.json`, `artists/`, `albums/`, `playlists/`, `suggestions/`, `credits/` | `Engine._kept_answer()` | the same, `cache.read_kept()` | a day (a playlist's suggestions only while it holds the same songs, their `basis`; an album's or a playlist's page only for the views it asked; Replay only in its shape, `normalize.REPLAY_SHAPE`; Radio's only until its `expires`); not one an older version kept in another shape (`shape`, `normalize.ANSWER_SHAPE`); an older one only when Apple cannot be asked (`stale: True`), pruned 30 days after it was written (`normalize.ANSWER_KEEP_AGE`); in demo mode, only what the demo library invented (marked `demo`), at any age |

| `recent-searches.json` | `src/recent_searches.py` (what was opened from Search) | the same, the Search page's Recently Searched | the `LIMIT` (10) opened last, until Search's Clear |
| `session.json` | `src/session.py` (the last session: the queue, the item and its position) | the same, at launch | until a newer session replaces it, or MusicKit refuses it (`session-dropped` deletes it) |

`normalize.prune_caches()` runs after the library's first load and after every sync; it also
removes what older versions kept (`items/`) and temporary files over an hour old. Clear
Cache (`src/cache.py`'s `CACHE_ENTRIES`) also removes `items/` and `library.lock`, an older
version's leftovers.

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
