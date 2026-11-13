# Releasing and packaging

Releases are native: `meson install` with the release profile. **A release is a git tag and a
GitHub release** with two things attached: the `meson dist` tarball, and the Arch package
built from it (`music-sleeve-<version>-<pkgrel>-any.pkg.tar.zst`), which
`.github/workflows/package.yml` builds from `build-aux/aur/PKGBUILD` and attaches once the
release is published. Arch users install that with `pacman -U`; others build the tarball. The
AUR package is not published yet (#206: AUR sign-ups are closed for now). The Flatpak
manifest is for development only, and Flathub is out of scope (`docs/decisions.md`).

An agent may carry out a release end to end once the owner has said to release, and that
includes the tag and the GitHub release. The exception is the AUR upload, which needs the
maintainer's AUR account and an SSH key registered with aur.archlinux.org: an agent prepares
the PKGBUILD and `.SRCINFO` and hands over the exact commands. The tag is the irreversible
step — once it is pushed and anyone has installed it, it must not be moved or deleted; cut a
new version instead.

## Checklist

1. `main` is green in CI (the two checks branch protection requires, "check.sh (Arch Linux)"
   and "meson dist (Arch Linux, as packaged)") and `scripts/check.sh` passes locally.
2. Walk `docs/accessibility.md`'s keyboard checklist (`scripts/a11y_check.py`, also
   `--size 360x640` and `--names`).
3. Retake the metainfo screenshots, in one step (`scripts/retake_screenshots.sh`, the
   `screenshots` skill's step 5), at every release: the UI keeps changing between them (the
   sidebar, the player bar, the Now Playing sheet). Look at every one, and update the
   metainfo's captions, and its images' `width` and `height`, where a shot changed.
4. Set the version in `meson.build` (`version`). The development profile appends the git
   revision by itself. Which digit moves, given the last release:
   **patch** (0.9.0 → 0.9.1) for fixes alone; **minor** (→ 0.10.0) when a feature was added;
   **major** (→ 1.0.0) for a break, or for the first release the project stands behind. The
   digits count independently — 0.10.0 follows 0.9.2 and is newer, despite reading smaller.
   Nothing detects this: the version stays where it is while work lands on `main`, and moves
   only here, as the first step of releasing. The bug report form
   (`.github/ISSUE_TEMPLATE/bug_report.yml`) gives the version as its example: move it too.
5. Add a `<release version="…" date="…">` at the top of the metainfo's `<releases>`, with a
   short description: a `<p>` and a `<ul>`. Then bring `po/en_US.po` up to date, the new
   notes with it: `meson compile -C build music-sleeve-pot music-sleeve-update-po`, then
   CONTRIBUTING.md's steps under Translating, American English.
6. Pin the metainfo's screenshot URLs to the tag: `/main/` becomes `/v<version>/` in each
   `<image>`, so an installed copy keeps showing the shots it was released with whatever
   later happens to the files on `main`.
7. Bump the PKGBUILD's `pkgver`, reset `pkgrel=1` and set `sha256sums=('SKIP')`, then
   `.SRCINFO` (`makepkg --printsrcinfo > .SRCINFO` in `build-aux/aur`): the tarball does not
   exist yet.
8. All of it is one pull request ("Release <version>"): `main` takes no direct push, so the
   release lands as any change does, the two required checks green, then
   `gh pr merge --squash --delete-branch`. The pull request touches the PKGBUILD, so the
   Package workflow builds it too, from the checkout's own source.
9. Tag the merge commit on `main` `v<version>` (annotated) and push the tag. Branch
   protection does not apply to tags. Once anyone has installed it the tag is fixed: never
   move or delete it.
10. Publish the GitHub release for that tag (`gh release create`), with the metainfo's notes
   as the body and `meson dist -C build`'s tarball and its `.sha256sum` attached, made from a
   checkout of the tag (`meson dist` archives HEAD). **This is the release.**
11. Watch the Package workflow that publishing starts (`gh run list -w Package`): it takes the
   release's tarball, checks it against its `.sha256sum`, builds with that checksum, and ends
   by attaching the `.pkg.tar.zst` to the release. If it fails, fix the PKGBUILD on `main`
   and run it by hand for the tag: `gh workflow run package.yml -f tag=v<version>`.
12. After the release, a pull request on `main`: the metainfo's screenshot URLs back to
   `/main/`, and `updpkgsums && makepkg --printsrcinfo > .SRCINFO` in `build-aux/aur`, so the
   PKGBUILD names the released tarball's checksum (the AUR needs it). When the AUR is wanted,
   set the `# Maintainer:` line to the contact to be public there; publishing needs an AUR
   account and an SSH key registered with aur.archlinux.org, so it is the maintainer's to do.
13. A rebuild of a released version (a `pkgrel` bump after a Python minor release) is the
   same workflow run by hand with that version's tag: `--clobber` replaces a package of the
   same name, and a new `pkgrel` is a new file beside the old one, which can be deleted.

## Installing from source

```bash
meson setup _build --prefix=/usr
meson compile -C _build
sudo meson install -C _build --skip-subprojects
```

Use a build directory of its own, never `build/`: that is the development build that
`scripts/run.sh` and `scripts/check.sh` keep on the development profile with the prefix
`build/install`. Running `meson setup build --prefix=/usr` on it only changes the prefix and
keeps the development profile, so the install would put the `.Devel` build into /usr.

`--skip-subprojects` matters when Meson fell back to the blueprint-compiler wrap: that
subproject would otherwise install its own `reference_docs.json` into the prefix. To
uninstall: `sudo ninja -C _build uninstall`, then remove `/usr/share/music-sleeve`, since the
byte-compiled `__pycache__` directories are not in Meson's install log.

## Byte-compiling

The app's modules install as data under `share/music-sleeve/applemusic`, outside
site-packages, so Meson's own `python.bytecompile` never reaches them. `src/meson.build` runs
`build-aux/meson/compile-python.py` at install time instead: `compileall` over the installed
package, level 0, plus `-O` or `-OO` when `python.bytecompile` is 1 or 2 (arch-meson sets 1),
skipped at -1. Only stale files are compiled again, so development installs stay quick.

## Testing the packages

- `meson dist -C build` archives HEAD (commit first) without the subprojects, into
  `build/meson-dist/`, and builds and tests the tarball with the build directory's options, so
  it needs `blueprint-compiler` installed or the network for the wrap.
- CI's `dist` job does the same on every pull request and push to main, from a build
  directory set up by `arch-meson` (the release profile, as the PKGBUILD's), with only the
  PKGBUILD's dependencies and no display, so the release's `meson dist` meets no test that
  check.sh passed only because build/'s gresource was there.
- Test a tarball in a temporary directory with its own `--prefix`.
- The Package workflow builds the PKGBUILD as it stands on every pull request that touches it,
  and uploads the package as a workflow artifact. Locally, test it in a temporary copy: run
  `makepkg` there without `-i` (build and check it, don't install it); it downloads the
  release tarball itself. Without `blueprint-compiler` installed, use `makepkg --nodeps` with
  a `blueprint-compiler` shim on PATH that answers `--version` with 0.22 or newer and
  otherwise runs `subprojects/blueprint-compiler/blueprint-compiler.py`.
- The PKGBUILD's `check()` runs `meson test`: the unit tests (Meson's `unit` suite, whose
  widget tests skip without a display) and the desktop file, metainfo and schema validation.

## Screenshots

`data/screenshots/{home,albums,album,now-playing,artist,search}-{light,dark}.png`: the window
at its default size, 1100×760 at scale 1, with its shadow on a transparent background (1150×810
in all), taken with `scripts/screenshot.py --demo` from the invented library only.
`scripts/retake_screenshots.sh` takes the set in one step (its `SUBJECTS` table has the exact
options; the `screenshots` skill's step 5 says how): it needs `oxipng` and a `build/` that
`scripts/check.sh` has configured, installs the build itself, and shrinks each picture
losslessly with `oxipng --opt 4 --strip safe`. The metainfo lists the light ones first
(`environment="gnome"`, Home as `type="default"`), then the dark ones
(`environment="gnome:dark"`), by `raw.githubusercontent.com/…/data/screenshots/…` URLs: on
`main` between releases, pinned to the tag at a release (step 6) and back after it (step 12).
Renaming or removing a file still breaks the metainfo of any build from `main` that names it.
Check that none carries a text chunk before committing:
`grep -c -a -E 'tEXt|iTXt|zTXt' data/screenshots/*.png` prints 0 for each.

## The Flatpak manifest

`build-aux/flatpak/io.github.jackicus.MusicSleeve.Devel.json` builds the development profile
for GNOME Builder or flatpak-builder. It talks to `org.freedesktop.Flatpak` so the app can run
the host's Chrome, and has no audio socket, because the host's Chrome makes the sound; the MPRIS
name, `org.mpris.MediaPlayer2.<app id>`, is one Flatpak lets an app own without asking. The
" (Development)" after its name comes from the development profile (`data/meson.build`), so
the manifest adds none of its own. In the sandbox, `chrome.find_chrome()` asks the host for the
binary through `flatpak-spawn --host`, and `chrome_args()` prefixes
`flatpak-spawn --host --watch-bus --forward-fd=3 --forward-fd=4`, which passes the DevTools pipe
on to the host's Chrome. The pid the engine holds is flatpak-spawn's, which relays SIGTERM to
Chrome and whose end ends Chrome (`--watch-bus`), so `setpriv` is not used there; the profile's
`SingletonLock` names a host pid, which the sandbox cannot check, so a Chrome left on the
profile is not ended at the next start. It targets GNOME 51 (org.gnome.Sdk//51).

What has been run (2026-11-13), and what has not:

- **Build and install: works.** `flatpak run org.flatpak.Builder --user --install
  --force-clean --state-dir=STATE BUILDDIR build-aux/flatpak/io.github.jackicus.MusicSleeve.Devel.json`
  (org.flatpak.Builder is a user Flatpak; a state directory outside the source tree, since
  the module's source is the whole tree; Builder's sandbox sees the home directory but not
  /tmp, so a directory there needs `flatpak run --filesystem=DIR org.flatpak.Builder …`).
  `--install` adds a user remote, `devel-origin`, pointing at the state directory's cache.
- **Demo mode: works**, on scripts/headless.sh's display. `flatpak run` inside it hands the
  sandbox the headless mutter's Wayland socket (the one `WAYLAND_DISPLAY` names, as the
  sandbox's `wayland-0`) and proxies the private session bus, so nothing reaches the desktop.
  The launcher's `DEMO_DIR` is a path in the build sandbox, so the demo library is named and
  exposed: `scripts/headless.sh flatpak run --filesystem=$PWD/build/demo
  --env=APPLE_MUSIC_CACHE=$PWD/build/demo io.github.jackicus.MusicSleeve.Devel --demo`.
  scripts/screenshot.py runs in the sandbox against its `/app` with `--command=python3`, from
  a copy of scripts/ beside a `build/install` that is a link to `/app`, given the same
  `--filesystem` and `APPLE_MUSIC_CACHE`.
- **Exports: valid.** The desktop file, both icons, the metainfo, the search provider's .ini
  and the D-Bus service file are in `~/.local/share/flatpak/exports/share`, named by the app
  ID, the service's and the desktop file's `Exec` rewritten to `flatpak run`; they pass
  desktop-file-validate and `appstreamcli validate`. The settings schema is not exported (a
  sandboxed app reads its own, in `/app`, and keeps its settings in a keyfile under
  `~/.var/app`); it passes `glib-compile-schemas --strict`.
- **Not run yet**: the engine (the host's Chrome through flatpak-spawn), playback, MPRIS, the
  Shell's search, notifications, Discord, and which finish-args can go. A host command
  flatpak-spawn starts has the environment of the flatpak-session-helper on the sandbox's
  session bus: under scripts/headless.sh that is the private bus, where no keyring answers.

Nothing installed may set `APPLE_MUSIC_DEBUG_PORT`: the launcher, the desktop file, the
PKGBUILD and the manifest leave the engine on its pipe alone.
