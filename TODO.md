# TODO

What is left, as of 2026-10-08. Music Sleeve (`io.github.jackicus.MusicSleeve`) is released:
[v0.9.0](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/tag/v0.9.0), the first
release, v0.10.0, which adds Discord rich presence, v0.11.0, the GNOME HIG pass, artist pages
in Apple Music's structure and Go to Album and Go to Artist, and
[v0.12.0](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/tag/v0.12.0), the latest:
playlist management (new, rename, delete, folders, remove from a playlist), the library's
Artists view, Add to Playlist by folder, a quicker refresh (#193), and Suggested Songs under a
playlist (six or twelve, Refresh, in full or as a preview). A release is a tag and a GitHub
release (`docs/release.md`); why the app is built the way it is, is in `docs/decisions.md`.

## Open

- [ ] Publish to the AUR when the maintainer wants it
      ([#206](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/206)): `build-aux/aur/` is
      ready (set the `# Maintainer:` contact, `updpkgsums && makepkg --printsrcinfo > .SRCINFO`,
      `makepkg -si` to try it, then push to aur.archlinux.org with the maintainer's account;
      README's install section changes then).
- [ ] [#153](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/153) (Later): a lazy Songs
      model, about 21 MB on a large library. Only if memory turns out to matter on a real one.
- [ ] [#293](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/293) (Later): an added
      suggestion leaves the grid before Apple confirms the add; a decision between leaving it,
      putting it back on a failure, or waiting for Apple.
- [ ] Build and run the Flatpak in GNOME Builder (the manifest in `build-aux/flatpak/` has
      never been built: no GNOME 50 runtime on the development machine). It can reach a
      native or Flatpak Discord's socket; that is untested too.
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
