# Music Sleeve

A native GNOME app for Apple Music: your library, playlists, radio and
recommendations, in GTK 4 and libadwaita.

Not affiliated with Apple. Apple Music is a trademark of Apple Inc.

![Home: heavy rotation and recently played music, a song playing below](data/screenshots/home-light.png)

<p align="center">
  <img src="data/screenshots/album-dark.png" width="49%" alt="An album's page, in the dark style">
  <img src="data/screenshots/now-playing-light.png" width="49%" alt="Now Playing, tinted by the artwork, a duet's lyrics lit word by word as they are sung">
</p>

The screenshots show an invented demo library.

> [!IMPORTANT]
> Music plays through **Google Chrome**. Apple Music's streams are protected with Widevine
> DRM, which Chrome ships and plain Chromium lacks, so the app runs Apple's own web player in
> a hidden Chrome on a private profile. Chrome opens a window once, for you to sign in.

## Features

- **Your library**: Recently Added, Artists, Albums, Songs, Music Videos, Made for You and
  Genres, with your playlists and folders in the sidebar. Favourites, filtering as you type,
  and selecting several songs at once.
- **Apple Music's catalogue**: Home, New, Charts, Radio, Search and Replay, with full album,
  playlist and artist pages.
- **Playlists**: create, rename, duplicate, delete, reorder, and organise into folders by
  dragging them in the sidebar.
- **Now Playing**: the queue and History, Autoplay, and lyrics lit word by word as they are
  sung, with duets, translations and pronunciations. A full-screen player (<kbd>F11</kbd>)
  and a mini player (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>).
- **Part of GNOME**: media keys and media controls (MPRIS), results in the Activities
  search, light and dark styles, and a window that adapts down to phone width.
- Optional: song notifications, and what you are playing on your Discord profile.

Not supported, because Apple's web player lacks them: Lossless, Dolby Atmos, offline
downloads, Apple Music Sing, and smart or collaborative playlists. Music videos play as audio.
The full list is in the [user guide](docs/user-guide.md#known-limitations).

## Requirements

- An Apple Music subscription.
- Google Chrome. Microsoft Edge, Brave, Vivaldi or Chromium also work if they have Widevine
  (not their snaps), and Preferences can name another browser. Only Chrome is tested.
- GNOME 50's libraries or newer: GTK 4.20, libadwaita 1.9, GLib 2.84, Python 3.12 and
  PyGObject 3.50. Fedora 44, Ubuntu 26.04, Arch Linux and openSUSE Tumbleweed have them.

## Install

### Arch Linux and derivatives

Download `music-sleeve-…-any.pkg.tar.zst` from the
[latest release](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/latest), then:

```bash
sudo pacman -U ~/Downloads/music-sleeve-*-any.pkg.tar.zst
```

Google Chrome is in the AUR as `google-chrome`. To uninstall: `sudo pacman -R music-sleeve`.

### Other distributions

Build the [latest release](https://github.com/Jackicus/GNOME-Music-Sleeve/releases/latest)'s
`music-sleeve-….tar.xz` with Meson. Install the build dependencies first:

```bash
sudo dnf install gtk4-devel libadwaita-devel glib2-devel python3-gobject python3-gobject-devel meson gettext  # Fedora
sudo apt install libgtk-4-dev libadwaita-1-dev python3-gi python-gi-dev meson gettext                         # Ubuntu
```

Then build and install it:

```bash
tar xf music-sleeve-*.tar.xz && cd music-sleeve-*/
meson setup _build --prefix=/usr
meson compile -C _build
sudo meson install -C _build --skip-subprojects
```

To uninstall: `sudo ninja -C _build uninstall && sudo rm -r /usr/share/music-sleeve`.

## First run

Start Music Sleeve and click **Sign In** at the bottom of the sidebar. A Chrome window opens
on music.apple.com: sign in there (the app never sees your password). The window then closes,
Chrome carries on hidden, and your library syncs.

<kbd>Ctrl</kbd>+<kbd>?</kbd> lists the keyboard shortcuts. The [user guide](docs/user-guide.md)
covers the rest, including troubleshooting, privacy, and where your data is kept.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to build and run the app on an invented
library, without Chrome or an account, and how to translate it.
[docs/architecture.md](docs/architecture.md) describes how it fits together.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
