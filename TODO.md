# TODO

What is left to do, as of 2026-11-13; the smaller fixes are in the
[open issues](https://github.com/Jackicus/GNOME-Music-Sleeve/issues). What each release brought
is in its [GitHub release](https://github.com/Jackicus/GNOME-Music-Sleeve/releases) and in git; how
a release is made is in `docs/release.md`, and why the app is built the way it is in
`docs/decisions.md`.

## Open

- [ ] Publish to the AUR when the maintainer wants it
      ([#206](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/206)): `build-aux/aur/` is
      ready (set the `# Maintainer:` contact, `updpkgsums && makepkg --printsrcinfo > .SRCINFO`,
      `makepkg -si` to try it, then push to aur.archlinux.org with the maintainer's account;
      README's install section changes then).
- [ ] The lyrics cache: since the word timings (#315) a kept song is about five times bigger
      (14 to 41 KB), so the 2,000 songs `LYRICS_KEEP` allows may take about 60 MB. Lower the
      limit or keep the files compressed if that turns out to matter.
- [ ] Run the Flatpak signed in: the manifest in `build-aux/flatpak/` builds, and the
      sandboxed app runs its demo and the host's Chrome up to `drm()` (docs/release.md), but
      playback, MPRIS with something playing, notifications and Discord's presence need a
      sign-in in its own profile, which has not been done; nor has a Flatpak Discord.
- [ ] Left by the review of everything since v1.0.1 (2026-11-11):
      [#573](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/573), a playlist song's
      Delete swallowed while the last removal's sync runs.
- [ ] The second parity audit's findings (2026-11-13, summary in
      [#637](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/637)): the
      [After v1.2.0](https://github.com/Jackicus/GNOME-Music-Sleeve/milestone/8) milestone,
      several of them waiting for a decision (`needs-decision`).
- [ ] [#590](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/590): resizing the window
      stutters as the pages rearrange (the Songs table's own breakpoints are
      [#662](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/662)).
- [ ] [#580](https://github.com/Jackicus/GNOME-Music-Sleeve/issues/580): the widget tests
      crashed once on CI (a callback on an object already freed), and passed when run again.
      Not reproduced locally in about 50 runs of the whole suite (Wayland and X11, cairo);
      the suite now runs under `-X faulthandler`, so the next crash names its test.
- [ ] Report to GTK that a popover menu keeps its model's sections after it is freed (found
      for #541, `docs/notes.md`, Memory; the app shares its Sort By sections instead, but a
      menu built each time it opens still leaves its sections behind).
- [ ] Translations: the strings are ready (`po/`, CONTRIBUTING.md's Translating) and en_US
      loads; other languages are #645.
- [ ] The internal names that still say Apple Music, none of them user-visible: the
      `applemusic` Python package, the `AppleMusic*` GType names, the `APPLE_MUSIC_*`
      environment variables, and the cache and Chrome profile directories. Left alone on
      purpose: renaming the directories would strand an existing sign-in and library.

## Working on it

Every change goes through a pull request with CI. `CLAUDE.md` and `.claude/` hold the rules for
Claude Code sessions (area rules load as files are touched; skills: `fix-bug`, `hig-polish`,
`performance-pass`, `review-pass`, `screenshots`, `live-engine-check`). Run GUI scripts through
`scripts/headless.sh` so no window opens on the desktop.

`ruff`, `python-cairo` and `oxipng` are installed here; `scripts/check.sh` falls back to uv's
cached ruff (`uvx --offline`) when none is on the path, and without either it skips the lint,
saying so. The demo library, and the tests that make one, need python-cairo. On a machine
without them: `sudo pacman -S ruff python-cairo oxipng`.
