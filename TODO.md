# TODO

What is left, as of 2026-10-20. Music Sleeve (`io.github.jackicus.MusicSleeve`) is released:
[v0.9.0](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/tag/v0.9.0), the first
release, v0.10.0, which adds Discord rich presence, v0.11.0, the GNOME HIG pass, artist pages
in Apple Music's structure and Go to Album and Go to Artist, v0.12.0, playlist management,
the library's Artists view and Suggested Songs, v0.13.0, lyrics word by word, translations and
pronunciations and a full-screen player, and
[v1.0.0](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/tag/v1.0.0), the latest and
the first release the project stands behind: the v1.0.0 milestone of the parity audit against
Apple Music's own apps (Charts, Apple's Radio page, an album's release footer and shelves,
curators and radio shows, Search's See All and Recently Searched, favourites and Date Added,
filters, Create Station, Suggest Less, Remove from Library, playlist folders and reordering,
Add to Playlist for albums and playlists, drag and drop, a fuller Up Next with History and
Autoplay, the last session restored, live radio, any Chromium-based browser with Widevine).
What the audit found for later is the
[After v1.0.0](https://github.com/Jackicus/GNOME-Music-Sleeve/milestone/5) milestone. A
release is a tag and a GitHub release (`docs/release.md`); why the app is built the way it
is, is in `docs/decisions.md`.

## Open

- [ ] Publish to the AUR when the maintainer wants it
      ([#206](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/206)): `build-aux/aur/` is
      ready (set the `# Maintainer:` contact, `updpkgsums && makepkg --printsrcinfo > .SRCINFO`,
      `makepkg -si` to try it, then push to aur.archlinux.org with the maintainer's account;
      README's install section changes then).
- [ ] [#153](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/153) (Later): a lazy Songs
      model, about 21 MB on a large library. Only if memory turns out to matter on a real one.
- [ ] [#320](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/320): the playback
      position in fractions of a second from the page, so the lyrics' words light on time
      (the estimate from MusicKit's whole seconds runs about 130 ms behind).
- [ ] The lyrics cache: since the word timings (#315) a kept song is about five times bigger
      (14 to 41 KB), so the 2,000 songs `LYRICS_KEEP` allows may take about 60 MB. Lower the
      limit or keep the files compressed if that turns out to matter.
- [ ] Build and run the Flatpak in GNOME Builder (the manifest in `build-aux/flatpak/` has
      never been built: no GNOME 50 runtime on the development machine). It can reach a
      native or Flatpak Discord's socket; that is untested too.
- [ ] The [After v1.0.0](https://github.com/Jackicus/GNOME-Music-Sleeve/milestone/5)
      milestone: what the parity audit and the v1.0.0 work left for later (Up Next's
      reordering, selection mode, credits, a mini player, Replay, a Genres view, the
      folder moves still switched off (#389), and the rest).
- [ ] Translations: the strings are ready (`po/`), no languages yet.
- [ ] The internal names that still say Apple Music, none of them user-visible: the
      `applemusic` Python package, the `AppleMusic*` GType names, the `APPLE_MUSIC_*`
      environment variables, and the cache and Chrome profile directories. Left alone on
      purpose: renaming the directories would strand an existing sign-in and library.

## Working on it

Every change goes through a pull request with CI. `CLAUDE.md` and `.claude/` hold the rules for
Claude Code sessions (area rules load as files are touched; skills: `fix-bug`, `hig-polish`,
`performance-pass`, `review-pass`, `screenshots`, `live-engine-check`). Run GUI scripts through
`scripts/headless.sh` so no window opens on the desktop.

`python-cairo` and `oxipng` are installed here, and `scripts/check.sh` runs ruff through `uvx`
(uv's cached copy) when no `ruff` is on the path (2026-10-08), so it runs the lint and the whole
suite. Without ruff and python-cairo it used to skip the lint and three demo-library tests
silently, which once let a line-length error reach CI; if a machine lacks them,
`sudo pacman -S ruff python-cairo oxipng` (or uv for the lint).
