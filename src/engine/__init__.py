# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The Engine: Chrome's lifecycle inside the app, its one CDP connection, and the commands the
UI awaits.

    engine = Engine(profile_dir, browser_command)   # made once, in Application.do_startup
    await engine.start()                # Chrome on music.apple.com, the bridge in it: headless
                                        # (or a window when prefer_headless is off); a running
                                        # engine is kept in whichever mode it runs
    await engine.start(visible=True)    # a window instead (sign-in); restarts if it was headless
    await engine.restart(visible=False)
    await engine.stop()                 # Browser.close, then SIGTERM, 5 s, SIGKILL
    await engine.stop(grace=1)          # a shorter wait after SIGTERM (quitting)
    await engine.status()               # {ready, engine, authorized, storefront, bitrate}
    await engine.api(path, params)      # one Apple Music API read (mk.api.music), retried
    await engine.api_pages(path, params, page=100)   # every item of a paged endpoint
                                        # (unique=True: each id once, for a listing)
    await engine.api_all(paths)         # several reads at once; a failed one is None
    await engine.item(kind, id)         # a full Item with all its groups, its artwork fetched
                                        # (into <cache>/remote-art/ unless the library has it)
    await engine.signin()               # until MusicKit is authorized (event or 2 s polls)
    await engine.unauthorize()          # revoke the session at Apple's (sign-out); True if done
    await engine.account_name()         # the name on the page, or '' (best effort)
    await engine.play(kind, id, start_with=None, shuffle=None, start_id=None)  # setQueue, play
                                        # start_time=83.0: that far in (a restored session);
                                        # paused=True: queued, not played yet
    await engine.play_next(kind, id); await engine.play_later(kind, id)
    await engine.control('toggle')      # play, pause, toggle, next, previous, stop
    await engine.seek(seconds); await engine.volume(level)   # volume answers the level set
    await engine.shuffle('toggle'); await engine.repeat('cycle')   # answer {shuffle, repeat}
    await engine.now_playing()   # {state, track, position, duration, shuffle, repeat, volume}
    await engine.queue()         # {index, items: [Track…], edit: the last edit applied}
    await engine.queue_jump(3)   # play the queue's entry at index 3 (mk.changeToMediaAtIndex)
    await engine.queue_remove(4, 'i.abc', edit=7)  # the entry at 4, when it is still i.abc
                                           # (not the item playing): queue.spliceQueueItems;
                                           # `edit` the Player's number for it
    await engine.queue_move(4, 2, 'i.abc', edit=8)  # that entry to 2, within its section of
                                           # Up Next: two splices, posted as one change
    await engine.queue_clear()   # everything after the item playing (queue.clearAfterCurrent)
    await engine.queue_undo_clear()   # Clear's entries back after the item, while it plays
    await engine.set_autoplay(True)   # mk.autoplayEnabled (None: read): {autoplay, canAutoplay}
    await engine.set_bitrate(64)      # mk.bitrate, kept as preferred_bitrate for every start:
                                      # the bitrate MusicKit has after it (0: it says none)
    await engine.preview(song_id, url)   # Apple's 30-second clip of a song, outside the queue
                                         # (MusicKit pauses); previewDidChange events follow it
    await engine.stop_preview()  # the clip playing stopped: True if one was
    await engine.lyrics(catalog_song_id)   # {synced, lines: [{startMs, endMs, text[, stanza]
                                           # [, words][, background][, agent]
                                           # [, pronunciation][, translation]…}], languages,
                                           # format} (src/lyrics.py has every field), from
                                           # <cache>/lyrics/ when fetched this month
    await engine.love('song', id); await engine.unlove('album', id)   # the rating, set or gone
    await engine.suggest_less('station', id)   # the rating -1 (in place of a favourite);
                                               # unlove() takes it away too
    await engine.rating('song', id)        # 1 loved, -1 Suggest Less, 0 neither
    await engine.favourite_artist(id); await engine.unfavourite_artist(id)   # a catalog
                                           # artist's star (/v1/me/favorites: not a rating)
    await engine.is_favourite_artist(id)   # its inFavorites, read past MusicKit's cache
    await engine.add_to_library('album', catalog_id)
    await engine.remove_from_library('song', library_id)   # the library id removed (a catalog
                                                           # id is read for its twin first)
    await engine.in_library('album', library_id)   # False once Apple's library read is a 404
    await engine.songs_found(['i.abc', '1000000001'])   # the ids of those Apple still has
    await engine.catalog_url('album', library_id)   # its music.apple.com page, or None
    await engine.add_to_playlist(playlist_id, song_id)   # kind='video' for a music video
    await engine.add_tracks_to_playlist(playlist_id, [(kind, id)…])   # how many, in batches
    await engine.create_playlist(name, description, [(kind, id)…], folder_id, public)   # its id
    await engine.edit_playlist(playlist_id, name=None, description=None, public=None)
    await engine.delete_playlist(playlist_id)
    await engine.remove_from_playlist(playlist_id, track_id, index)   # that one entry
    await engine.remove_playlist_entries(playlist_id, shown, positions)   # several, in one
                                 # write: the entries Apple had, for put_back_playlist_entries
    await engine.put_back_playlist_entries(playlist_id, kept, entries)   # an Undo of that
    await engine.reorder_playlist(playlist_id, shown, order)   # its tracks in a new order:
                                 # `order` positions in `shown`, the ids as the app had them
    await engine.playlist_track_ids(playlist_id)   # its tracks' ids as Apple lists them now
    await engine.rename_folder(folder_id, name); await engine.delete_folder(folder_id)
    await engine.create_folder(name, folder_id)   # the new folder's id ('root': the top level)
    await engine.move_to_folder(kind, id, folder_id)   # a playlist (or folder) into a folder
    await engine.folder_children(folder_id)   # [{kind, id, name}] as Apple lists them now
    await engine.search(term, limit=20)    # {shelves}: a catalog search, each shelf's `next`
    await engine.search(term, limit=25, kind='songs', offset=20)   # one kind, a later page
    await engine.suggest(term, limit=10)   # {terms: [{term, display}], items}
    await engine.landing()       # {categories}: the search page's Browse Categories
    await engine.category(id)    # {id, title, shelves}: a category's page
    await engine.browse()        # {shelves, links}: the New page (the editorial groupings:
                                 # the banners, the shelves, More to Explore's links)
    await engine.room(id)        # {id, title, items}: a More to Explore link's collection
    await engine.grouping(id)    # {id, title, shelves, links}: a link's page of shelves
    await engine.multiroom(id)   # {id, title, shelves, links}: a link's page of shelves
    await engine.made_for_you()  # {shelves}: the personal mixes and stations
    await engine.recently_played()   # {items}: Home's Recently Played, newest first
    await engine.radio()         # {shelves[, expires]}: the Radio page (the radio grouping)
    await engine.charts()        # {shelves}: the Charts page (the catalog's charts: Top Songs,
                                 # Albums, Playlists, Music Videos, Daily Top 100, City Charts)
    await engine.charts(genre='21')   # {shelves}: one genre's charts (no Daily Top 100 or City
                                 # Charts)
    await engine.genres()        # {genres: [{id, title}]}: the genres the Charts page offers
    await engine.replay()        # {year, years, shelves}: Replay, the latest year's top songs,
                                 # artists and albums, and each year's Replay playlist
    await engine.replay(year='2025')   # {year, years, shelves}: a past year's
    await engine.artist_page(id) # {id, artist, banner, latest, topSongs, shelves,
                                 # favourite}: a catalog artist's page, every view of it at
                                 # once, and whether they are a favourite
    await engine.album_page(id, song_id=None)   # {id, artistId, artistName, release,
                                 # shelves}: what an album's page shows under its tracks (a
                                 # library album's through one of its songs)
    await engine.playlist_page(id)   # {id, curator, shelves}: what a catalog playlist's page
                                 # shows under its tracks, and the curator its title names
    await engine.playlist_suggestions(playlist_id, limit=16, offered=(), selected=(),
                                      previewed=())
                                 # {items}: the songs Apple suggests adding to a library
                                 # playlist, none of `offered`; more=True: a few more, unkept
    await engine.credits(catalog_song_id)   # {categories: [{kind, title, people: [{name,
                                 # roles}]}]}: a song's credits (View Credits), in Apple's order
    # The last nineteen are kept under the cache for a day (landing.json, categories/,
    # browse.json, rooms/, groupings/, multirooms/, made-for-you.json, radio.json,
    # charts.json, charts/, genres.json, replay.json, replay/, recent-played.json, artists/,
    # albums/, playlists/, suggestions/, credits/) and
    # answered from there without the engine;
    # refresh=True asks again. Each answer carries `cached`, when it was fetched; one older
    # than a day, answered when Apple cannot be asked, carries `stale: True` too. The
    # suggestions are kept with `basis`, what the playlist held, and asked again once it holds
    # something else; Radio's until its live programmes run out (`expires`), whatever its age.
    # Each is stamped `shape` too (normalize.ANSWER_SHAPE): one an older version kept in
    # another shape is asked again, whatever its age.
    await engine.artist_view(id, 'full-albums')   # [Item…]: one of an artist's views whole
    await engine.album_view(id, 'other-versions') # [Item…]: one of an album's views whole
    await engine.playlist_view(id, 'featured-artists')   # [Item…]: one of a playlist's views
    await engine.curator_playlists(id)   # [Item…]: an Apple curator's playlists whole (More By)
    await engine.catalog_artist(name, song_ids)   # the catalog artist a library one stands
                                                  # for, found through its songs, or None
    await engine.related('song', id)  # {album, artists}: a catalog song's (or music video's)
                                      # album and artists, or an album's artists

Properties `state` ('down', 'starting', 'up', 'signing-in'), `authorized`, `headless`,
`widevine`, which goes False when the page of the browser just started says it cannot decrypt
Widevine (asked once per start, beside it: play() and queue_jump() then raise 'no-widevine', as
no song would play; previews still do), and `bitrate`, the kbps MusicKit streams at (256 or
64; 0 while down or unknown), from the status reads, set_bitrate() and MusicKit's
playbackBitrateDidChange; the `event(name, data)` signal re-emits the bridge's
MusicKit events (name without the 'am:' prefix), and `rated(kind, id, value)` follows love(),
unlove(), suggest_less() and rating() (the kind and id as they were asked, value 1 loved, -1
Suggest Less, 0 neither), so a heart shows what a menu did, and ('artist', catalog id, 1 or
0) follows favourite_artist(), unfavourite_artist(), is_favourite_artist() and an
artist_page() that says (the page's star), and `lost(reason)` says the engine
went down on its own (Chrome crashed or was killed, the page crashed, closed or stopped
answering), never for a stop, a restart or quitting. Every failure is an EngineError; nothing
here blocks the loop: Chrome is a Gio.Subprocess (awaitable wait_async), the connection is the
asynchronous CDPClient over Chrome's DevTools pipe (its descriptors 3 and 4: no port is open),
and the JSON shaping and artwork HTTP of item() run in a thread. In demo mode (`demo=True`)
start() and stop() do nothing and every command raises EngineError('engine-down') at once, but
for a kept answer the demo library invented (scripts/demo_library.py writes its artists' and
albums' pages, marked `demo`), answered from its cache, a search or its suggestions, answered
from the invented catalog it writes (demo-search.json: demo_search()), and an artist's
favourite, which the session only remembers.
"""

from .core import Engine

__all__ = ['Engine']
