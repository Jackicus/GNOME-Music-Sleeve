# Contributing

Thanks for helping with Music Sleeve. Bug reports, fixes, features and translations are all
welcome; for anything bigger than a small fix, open or pick an issue first so the approach can
be agreed before the work. Everyone taking part is expected to follow the
[GNOME Code of Conduct](https://conduct.gnome.org).

## Setting up

The app needs GTK 4.20, libadwaita 1.9, GLib 2.84, Python 3.12 and PyGObject 3.50, or newer:
the libraries of GNOME 50. Nothing in it is tied to a distribution. Fedora 44, Ubuntu 26.04,
Arch Linux and openSUSE Tumbleweed ship those versions; Debian 13 and Ubuntu 24.04 do not.
To build and test it you also need Meson 1.2, gettext, `blueprint-compiler` 0.22 (Meson downloads
its own when the installed one is missing or older), pycairo for the demo library generator,
`appstream` and `desktop-file-utils` for the data checks, `ruff` for the lint, and `gjs` for
the tests of `src/backend/bridge.js` (skipped without it).

```bash
# Arch Linux
sudo pacman -S --needed gtk4 libadwaita python-gobject python-cairo meson blueprint-compiler \
    gettext appstream desktop-file-utils ruff gjs
# Fedora 44 or later
sudo dnf install gtk4-devel libadwaita-devel glib2-devel python3-gobject python3-gobject-devel \
    python3-cairo meson gettext appstream desktop-file-utils ruff gjs
```

Google Chrome (or another Chromium-based browser with Widevine) is only needed to play
music: the demo library and the tests work without it, and without an Apple Account.

## Build, run and test

```bash
scripts/demo.sh          # build the development profile into ./build and run it on an
                         # invented library: no Chrome, no Apple Account
scripts/run.sh           # the same with the real engine (Chrome on the app's own profile)
scripts/check.sh         # byte-compile, ruff, build, unit tests, desktop/metainfo/schema checks
scripts/headless.sh python3 -m unittest discover -s tests -v    # the unit tests alone
scripts/headless.sh scripts/screenshot.py --demo build/shot.png --page albums [--light]
scripts/headless.sh COMMAND   # any of these on an invisible display, off your desktop
```

The development build has its own app ID (`io.github.jackicus.MusicSleeve.Devel`), Chrome
profile, cache and sign-in, so it installs beside a release build without touching it.
`scripts/check.sh` is what CI runs (in an Arch Linux container, with the widget tests on
Xvfb) and must pass before a pull request is merged. Beside it, CI builds and tests the
`meson dist` tarball as a distribution package would (`arch-meson`, the PKGBUILD's
dependencies, no display): a test that imports a module with a widget template has to be
marked `@requires_gtk` (`tests/gtk.py`) even when it builds no widget, or it fails there.
GNOME Builder can also build the
development profile through the Flatpak manifest in `build-aux/flatpak/`, which runs the
host's Chrome from the sandbox; that manifest has never been built, so it is untested.

## Conventions

[docs/architecture.md](docs/architecture.md) explains how the app is put together and
[docs/decisions.md](docs/decisions.md) why. The code conventions are in [CLAUDE.md](CLAUDE.md),
with the rules for each area in `.claude/rules/`; please read them before a larger change.
In short:

- Follow the [GNOME HIG](https://developer.gnome.org/hig/) and use libadwaita widgets and style
  classes before custom CSS.
- Never block the main loop: it runs both GTK and asyncio.
- Collections are list models over `Gio.ListStore`, not boxes of widgets.
- Every user-visible string goes through `_()`; a new file with strings goes in
  `po/POTFILES.in`. Source strings use en-GB spelling.
- New Python modules go in `src/meson.build`'s install list, new `.blp` files in its blueprint
  list and their `.ui` (by bare name) in `src/applemusic.gresource.xml`; a test checks these
  lists.
- Backend and model changes come with a unit test (stdlib `unittest`) in `tests/`.
- 4-space Python, single quotes; `ruff check .` must be clean.

## Privacy

The repository is public. Never commit real account data: no names, emails, playlist or song
titles, library IDs, tokens, artwork, or anything from `~/.cache/apple-music` or the Chrome
profile. Tests, fixtures, docs and screenshots use invented data only (`scripts/demo_library.py`
generates the demo library). The same goes for logs pasted into issues.

## Pull requests

1. Branch from `main`. You do not need write access: fork the repository, push your branch
   to your fork and open the pull request from there. CI runs on it automatically.
2. Keep commits focused (one logical change each, mechanical changes such as renames in their
   own commit), with messages that say what changes and why.
3. Fill in the pull request template: link the issues with `Closes #123` so they close on
   merge, and attach screenshots for UI changes.
4. `main` is protected: nothing is pushed to it directly, and a pull request is merged only
   once its `check.sh (Arch Linux)` run has passed. No approving review is required; the
   maintainer merges, and only the maintainer can. Pull requests are squashed, so `main` keeps
   a linear history, and the branch is deleted after the merge.

Security problems are reported privately, not as pull requests or issues: see
[SECURITY.md](SECURITY.md).

## Translating

The strings are in gettext's usual form, and the sources are in British English. The one
catalogue so far is `po/en_US.po`, American English. #645 is where new languages are
discussed: say there which one you are starting.

Everything below runs after a `scripts/demo.sh` or `scripts/check.sh` has configured
`build/`. It needs no Apple account and no Chrome.

### Starting a language

```bash
meson compile -C build music-sleeve-pot          # the template, po/music-sleeve.pot (not committed)
cd po && msginit -l de -i music-sleeve.pot -o de.po
```

Then add `de` to `po/LINGUAS` and translate `de.po`.

- The comments starting `Translators:` explain strings that cannot be understood alone:
  what a placeholder holds, whether a word is a verb or a noun, where a short label shows.
- Keep each placeholder (`{count}`, `{title}`) as it is; you can move it within the sentence.
- Keep one `_` in a menu item or button label for its keyboard access key.
- Leave "Apple Music" (the service) and "Music Sleeve" (the app) as the source has them.
- Dates are formats for `GLib.DateTime.format()`, such as `%-d %B %Y` for "24 September
  2026": put the parts in your language's order.

### Updating a language

```bash
meson compile -C build music-sleeve-pot music-sleeve-update-po
```

This makes the template again from the source and merges it into every catalogue in
`po/LINGUAS`. New strings arrive untranslated and changed ones are marked fuzzy. Until they
are translated, the app shows them in the source's English, so a catalogue that is behind
fails nothing.

### Trying it

Install the build, then run the demo library in your language through the screenshot script.
It runs on a private, invisible display:

```bash
meson install -C build --skip-subprojects
LANGUAGE=de scripts/headless.sh scripts/screenshot.py build/de.png --demo --page albums
LANGUAGE=de scripts/headless.sh scripts/screenshot.py build/de-narrow.png --demo --page albums --size 360x640
```

`scripts/screenshot.py --help` lists the other pages and dialogs. `LANGUAGE=de
scripts/demo.sh` opens the demo itself on your desktop.

`scripts/pseudo_locale.py` builds two pseudo-translations into `build/locale`:

- `en_XA`: every letter accented and every string 40 % longer.
- `ar_XB`: right to left.

Run them with `MUSIC_SLEEVE_LOCALEDIR=build/locale LANGUAGE=en_XA` (and `--rtl` for
`ar_XB`) to find text that is clipped or not translated.

### Checks

`tests/test_translations.py`, which CI runs, checks two things:

- every `.po` file is listed in `po/LINGUAS`;
- every `.po` compiles under `msgfmt --check`, which catches broken placeholders and plural
  forms.

`tests/test_build_lists.py` checks that every file with translatable strings is in
`po/POTFILES.in`.

### American English

`po/en_US.po` translates only what American English spells or orders differently:
"Favourite" becomes "Favorite", "catalogue" becomes "catalog", "colours" becomes "colors",
"cancelled" becomes "canceled", "centred" becomes "centered", and dates go month first. Every
other message is left untranslated and shows as the source.

Before each release, the maintainer:

1. runs the update above;
2. searches the template for British spellings, for example
   `grep -inE 'favourit|catalogu|colour|cancell|centred|ise[sd]?\b' po/music-sleeve.pot`,
   and lists the catalogue's fuzzy entries with `msgattrib --only-fuzzy po/en_US.po`;
3. translates the entries that differ and clears the fuzzy flags;
4. commits it with the release.
