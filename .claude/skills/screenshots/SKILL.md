---
name: screenshots
description: Take and check screenshots of the real app window on the invented demo library - to verify a visible change, to attach to a pull request, or to retake the metainfo screenshots in data/screenshots/. Use whenever a change is visible or screenshots are asked for.
argument-hint: "[page key or item, e.g. albums, album:first, now-playing]"
---

What to shoot: $ARGUMENTS

1. The shots come from the installed build, so install the current code first:
   `meson install -C build` (after `scripts/headless.sh scripts/check.sh`, which configures
   and compiles build/).
2. Always run the script through `scripts/headless.sh` (a private, invisible display: no window
   on the desktop) and always pass `--demo` (without it the script reads the real cache). Write
   into build/, which git ignores:
   - `scripts/headless.sh scripts/screenshot.py build/<name>.png --demo --page KEY`: a root
     page (a destination key from `src/sections.py`, `playlist:ID`, `folder:ID` or
     `folder:first`);
   - `--open KIND:first` (or `KIND:ID`; KIND `album`, `artist`, `playlist`, `folder`,
     `station` or `video`): a pushed page over `--page`; an ID the library lacks opens the
     catalog's album or playlist (`album:demo.edition0010`, `playlist:pl.demo001`: Add in
     its header), or a library album's catalog copy by its catalog id (`album:1724040010`:
     In Library);
   - `--playing`: an invented item playing (the first album's first track), the player bar in
     its playing state; `--now-playing [lyrics|queue]`: the same with the Now Playing sheet
     open on that tab (`localized`: Lyrics, invented Japanese lines with pronunciations and
     translations, shown with `--setting lyrics-pronunciations=true` and
     `--setting lyrics-translations=true`; `syllable`: Lyrics, an invented word-timed duet
     with background vocals, a long intro and a long break); `--position SECONDS` puts the
     item that far in (65 by default), mid-word or inside a break; `--autoplay` (with
     `--now-playing queue`) ends the queue with entries autoplay added, under Up Next's
     Autoplay header; `--history` puts entries played already before the item (with
     `--now-playing queue`, Up Next's History shown); `--album N` plays the demo's Nth
     album, another cover (the sheet's tint another colour); `--restored`: the item as the last session restored at launch, paused,
     the sheet closed; `--live` (with `--playing`, `--now-playing` or `--fullscreen-player`):
     an invented live radio station instead, LIVE in place of the slider, Stop for Pause;
   - `--signed-in [NAME]`: the account button signed in (an invented NAME: its avatar's colour
     follows the name); `--banner sign-in|expired`: the sign-in banner;
   - `--sidebar` (the narrow layout: the sidebar rather than the page), `--expand first`,
     `--search TERM`, `--context-menu` (`--menu-of N` for the Nth row's, after `--scroll`
     when given, or with `--now-playing queue` the Up Next entry N after the one playing;
     `--submenu NAME` for one of its submenus, by its label, underscore and all: `"Add to Pla_ylist"`, `"Mov_e to Folder"`), `--preferences [general|engine]`,
     `--dialog about|shortcuts`; `--scroll PX` for the rest of a page taller than the
     window (an artist's: `--open artist:first --scroll 900`; an album's footer and shelves:
     `--open album:first --scroll 650`, and `1400` for the last of them; a playlist's Suggested Songs:
     `--page playlist:l.pl002 --scroll 1600`; a catalog playlist's shelves:
     `--open playlist:pl.demo001 --scroll 700`); `--focus` focuses the page's first tile or
     row with its focus ring (a music video's play symbol); `--setting KEY=VALUE` sets a setting first
     (`--setting more-suggestions=true` shows twelve suggestions);
   - the main menu: `--main-menu` (with `--sidebar` at a narrow `--size`); the sidebar's
     Playlists heading's **+** menu: `--new-menu` (the same);
   - the playlists' menus and dialogs: `--more-options` (the page's More Options menu),
     `--sidebar-menu playlist:first|folder:first|all-playlists`, and
     `--dialog new-playlist|new-folder|rename|delete` for the playlist or folder the page
     shows (a playlist's rename is its Edit Details…, the playlist dialog);
     `--dialog remove-from-library` for the item the page shows (else the first album),
     `--dialog credits` and `--dialog add-songs`;
   - `--select N` (a track list in its selection mode, its first N selected), `--filter TEXT`
     (the page's filter bar), `--fullscreen-player [lyrics|localized|syllable|none]`
     (`--idle`: its controls hidden), `--mini-player` (`--mini-pane lyrics|queue`);
     `--help` lists the rest.
   Dark is the default; add `--light`, `--high-contrast` for libadwaita's high-contrast
   style (with or without `--light`), and `--rtl` for a right-to-left layout (a mirrored
   window, its strings still English). Sizes: the default (1100x760), `--size 400x700`, and
   `--size 360x640`, the narrowest supported. The script waits for the artwork to decode
   before it shoots.
3. Look at every PNG with the Read tool. Check that the change is there; that nothing is
   clipped, overlapping, or ellipsized where it should fit; both schemes; focus and selection;
   covers rather than placeholders (retake a shot that shows placeholders). A harmless at-spi
   warning in the script's output is expected.
4. Shots of work in progress stay in build/. Never commit or share a shot taken without
   `--demo`.
5. Retaking the metainfo screenshots (`data/screenshots/`) is one step:
   `scripts/retake_screenshots.sh` (after `scripts/headless.sh scripts/check.sh` has
   configured build/; it installs the build itself). It shoots each subject of its `METAINFO`
   list as `<name>-dark.png` and `<name>-light.png`: the window at its default size
   (1100x760, scale 1) with `--frame` (its shadow and rounded corners on a transparent
   background, 1150x810 in all, as a window screenshot is), `--signed-in 'Alex Rivera'`
   (invented), each run as `GSETTINGS_BACKEND=memory scripts/headless.sh …` so the private
   session's Settings portal answers GNOME's defaults (the blue accent, a close button
   alone) rather than the desktop's; then `oxipng --opt 4 --strip safe`. Its `SUBJECTS`
   table holds each subject's options. The metainfo's six: `home`, `albums`, `album` (the
   album playing), `now-playing` (the invented duet, the only word-timed lyrics fixture, at
   its first, English stanza: a line lit part-way, background vocals, the second singer's
   lines on their side below), `artist` (Apple's page of the first artist, its banner) and
   `search` (Apple Music searched for `drift`: every cover in its Songs shelf another); the
   other candidates, by name: `fullscreen-lyrics` (fullscreen: no shadow, and the same tinted
   picture in both schemes), `selection` (a playlist, three songs selected) and `narrow`
   (360x640). `--out DIR` writes elsewhere (candidates go in build/); name subjects, or
   `all`, to take others than the metainfo's. The app runs as the release profile there, so
   no .Devel stripes, name or icon. Keep the names: installed metainfo files link them by
   URL. Look at each one (demo data only), and check that none carries a text chunk:
   `grep -c -a -E 'tEXt|iTXt|zTXt' data/screenshots/*.png` prints 0 for each. Update the
   captions in the metainfo, and its images' `width` and `height`, if what a shot shows
   or its size changed.
