# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The developer scripts' shared start: the installed app, on its own, off the desktop's
settings, on the demo library.

screenshot.py, a11y_check.py, scroll_test.py and bench.py each run the installed build (meson
install -C build, or scripts/run.sh, first) in-process. make_app() does what they all need:

- the installed modules on sys.path (build/install/share/music-sleeve) and the translations
  bound (i18n.setup, as the launcher does);
- GSettings on the memory backend with the installed schema, so nothing the script sets (window
  size, last-page, signed-in) reaches the desktop's settings; engine-autostart off, so a script
  never starts Chrome, even one run without the demo library;
- the demo library: build/demo, generated first when it is missing or out of date
  (demo_stamp), unless APPLE_MUSIC_CACHE names another (the app's --demo reads it), passed as
  --demo by run_app();
- gi's versions, the gresource registered, main.Application under an app ID of its own
  (io.github.jackicus.MusicSleeve.<suffix>, NON_UNIQUE: beside a running app), asyncio on the
  GLib loop (main.use_glib_event_loop());
- at startup: the colour scheme forced dark (or light), animations off unless asked for, and
  with `stock_look` stock GNOME's icon theme and font (Adwaita, Adwaita Sans 11) instead of the
  desktop's, which GTK otherwise takes from the Settings portal; the installed icons findable
  (installed_icon() names the app's); each window made non-resizable, a fixed size a tiling
  window manager leaves alone. The version is the project's (build/meson-info).

Call make_app() before importing Gtk: importing it starts GTK, which may read the settings
schemas once and for all. invented_playing_state() is what the Player shows while the demo's
first album plays; popovers() finds the popovers shown under a widget.
"""

import json
import os
import shutil
import subprocess
import sys

import demo_stamp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = os.path.join(ROOT, 'build', 'install')
PKGDATADIR = os.path.join(PREFIX, 'share', 'music-sleeve')
GRESOURCE = os.path.join(PKGDATADIR, 'applemusic.gresource')
SCHEMA_DIR = os.path.join(PREFIX, 'share', 'glib-2.0', 'schemas')
LOCALEDIR = os.path.join(PREFIX, 'share', 'locale')
ICONS = os.path.join(PREFIX, 'share', 'icons')
DEMO_DIR = os.path.join(ROOT, 'build', 'demo')  # what the development launcher passes
BASE_ID = 'io.github.jackicus.MusicSleeve'

# invented_playing_state()'s artwork URLs, one per album (ALBUM: its id): the album's cover
# and thumbnail are copied to where remote.fetch_remote would put this URL's 640 px and
# 320 px images, so nothing is fetched.
DEMO_ART_URL = 'https://example.invalid/demo-art/ALBUM/{w}x{h}bb.jpg'
PLAYING_POSITION = 65.0  # seconds in: a line of the lyrics fixture is current, mid-song


def ensure_demo_library():
    """Generate build/demo when it is missing or out of date (demo_stamp.current(): made by
    an older demo_library.py, or with other options) and APPLE_MUSIC_CACHE names no other
    library."""
    if os.environ.get('APPLE_MUSIC_CACHE') or demo_stamp.current(DEMO_DIR):
        return
    subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'demo_library.py'),
                    '--cache', DEMO_DIR], check=True)


def project_version():
    """The version meson.build declares, as the build's introspection records it."""
    try:
        with open(os.path.join(ROOT, 'build', 'meson-info', 'intro-projectinfo.json'),
                  encoding='utf-8') as file:
            return json.load(file)['version']
    except (OSError, ValueError, KeyError):
        return '0.0.0'


def installed_icon():
    """The installed app icon's name (the .Devel one in the development profile), or None."""
    apps = os.path.join(ICONS, 'hicolor', 'scalable', 'apps')
    names = sorted(name for name in os.listdir(apps)) if os.path.isdir(apps) else []
    return next((name.removesuffix('.svg') for name in names
                 if name.startswith(BASE_ID) and name.endswith('.svg')), None)


def require_install():
    """Exit with a message unless the build is installed (build/install)."""
    if not os.path.exists(GRESOURCE):
        sys.exit(f'{os.path.basename(sys.argv[0])}: no installed build in {PREFIX}: '
                 'run meson install -C build first')


def make_app(suffix, demo=True, light=False, animations=False, stock_look=True, size=None,
             demo_dir=DEMO_DIR, name=None):
    """The installed app's main.Application, set up as the module says, not yet run (run_app()
    runs it). `size` (width, height) is written to the window-size settings; `name` is the
    program name (argv[0] and GLib's prgname), the suffix lower-cased by default."""
    require_install()
    if demo:
        ensure_demo_library()
    os.environ['GSETTINGS_SCHEMA_DIR'] = SCHEMA_DIR
    os.environ['GSETTINGS_BACKEND'] = 'memory'  # never the desktop's settings
    sys.path.insert(1, PKGDATADIR)
    from applemusic import i18n

    i18n.setup(LOCALEDIR)

    import gi

    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

    Gio.Resource.load(GRESOURCE)._register()
    from applemusic import main

    name = name or suffix.lower()
    GLib.set_prgname(name)
    app = main.Application(project_version(), f'{BASE_ID}.{suffix}', BASE_ID, 'default',
                           demo_dir)
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.harness_argv = [name] + (['--demo'] if demo else [])
    app.settings.set_boolean('engine-autostart', False)
    if size is not None:
        app.settings.set_int('window-width', size[0])
        app.settings.set_int('window-height', size[1])

    def on_startup(_app):
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_LIGHT if light else Adw.ColorScheme.FORCE_DARK)
        settings = Gtk.Settings.get_default()
        if not animations:
            # Pages arrive at once: a transition the compositor starves of frames (an
            # unfocused window) could still be sliding when a script looks.
            settings.set_property('gtk-enable-animations', False)
        if stock_look:
            settings.set_property('gtk-icon-theme-name', 'Adwaita')
            settings.set_property('gtk-font-name', 'Adwaita Sans 11')
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(ICONS)

    def on_window_added(_app, window):
        window.set_resizable(False)  # a tiling window manager leaves a fixed size alone

    app.connect('startup', on_startup)
    app.connect('window-added', on_window_added)
    main.use_glib_event_loop()  # as main.main() does, so app.spawn() works
    return app


def run_app(app, *options):
    """Run the app from make_app() (with --demo when it was made for the demo library, and
    `options`, e.g. '--debug'); its exit status."""
    return app.run(app.harness_argv + list(options))


# The lyrics fixtures (tests/fixtures/) invented_playing_state() can show, by name.
LYRICS_FIXTURES = {
    'lyrics': 'lyrics.json',              # English lines, timed by the line
    'localized': 'lyrics_localized.json',  # Japanese lines, each with its romanisation
                                           # and its English translation
    'syllable': 'lyrics_syllable.json',    # a word-timed duet: syllables, background
                                           # vocals, two singers and a group, long breaks
}


def album_entries(album):
    """An Item album's tracks as the bridge's Track entries."""
    return [dict(entry) for group in album.raw.get('groups') or []
            for entry in group.get('entries') or []]


def demo_art_url(album):
    """An invented artwork URL for a demo album, its cover and thumbnail put where
    remote.fetch_remote keeps that URL's images (so nothing is ever fetched for it)."""
    from applemusic.backend import config
    from applemusic.remote import remote_art_path

    url = DEMO_ART_URL.replace('ALBUM', album.id)
    for size, source in ((config.COVER_SIZE, album.art), (config.THUMB_SIZE, album.thumb)):
        path = remote_art_path(url, size)
        if source and path and os.path.exists(source) and not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(source, path)
    return url


def album_queue_entries(album, count=None, **extra):
    """The first `count` (all: None) of an album's tracks as queue entries with its
    artwork URL (demo_art_url()) and `extra` keys."""
    url = demo_art_url(album)
    return [dict(entry, artUrl=url, **extra) for entry in album_entries(album)[:count]]


def invented_playing_state(app, lyrics=False, fixture='lyrics', position=None,
                           autoplay=False, album=0, history=False):
    """A Player.apply() dict: the demo library's album at position `album` (the first by
    default) as the queue, its first track playing `position` seconds in (PLAYING_POSITION,
    65 s, by default), the album's cover as the artwork, and with `lyrics` the synced lyrics
    of the LYRICS_FIXTURES file named `fixture`; with `autoplay`, the album's first
    AUTOPLAY_AFTER tracks, then the next album's first AUTOPLAY_COUNT as entries autoplay
    added; with `history`, the queue first holds HISTORY_COUNT tracks of each of the
    HISTORY_ALBUMS albums after those, played already (Up Next's History). Each album's
    entries have its own artwork. The demo cannot play: this is what the Player would
    show."""
    if not app.demo:
        sys.exit('harness: an invented playing state needs the demo library')
    albums = app.library.albums
    playing = albums.get_item(album)
    if playing is None:
        sys.exit(f'harness: the demo library has no album {album}')
    entries = album_queue_entries(playing)
    if not entries:
        sys.exit('harness: the demo album has no tracks')
    if autoplay:
        following = albums.get_item(album + 1)
        added = (album_queue_entries(following, AUTOPLAY_COUNT, autoplay=True)
                 if following is not None else [])
        entries = entries[:AUTOPLAY_AFTER] + added
    played = []
    if history:
        for number in range(HISTORY_ALBUMS):
            earlier = albums.get_item((album + 2 + number) % albums.get_n_items())
            played += album_queue_entries(earlier, HISTORY_COUNT)
    entries = played + entries
    for index, entry in enumerate(entries):
        entry['index'] = index
    current = len(played)
    state = {
        'state': 'playing', 'track': entries[current],
        'position': PLAYING_POSITION if position is None else position,
        'duration': entries[current].get('durationMs', 0) / 1000, 'shuffle': 'off',
        'repeat': 'none', 'volume': 0.7, 'queue': {'index': current, 'items': entries},
    }
    if lyrics:
        path = os.path.join(ROOT, 'tests', 'fixtures', LYRICS_FIXTURES[fixture])
        with open(path, encoding='utf-8') as file:
            state['lyrics'] = json.load(file)
    return state


def invented_live_state(app):
    """A Player.apply() dict of a live radio station playing (#343), as the bridge gives
    one: the demo library's first station as the item (type radioStation, isLive, no length
    of its own, its cover as the artwork), the position a place in the stream's window as
    MusicKit reports it (112 s of 160), and nothing allowed: no seek, pause or skip."""
    if not app.demo:
        sys.exit('harness: an invented playing state needs the demo library')
    station = app.library.radio.get_item(0)
    if station is None:
        sys.exit('harness: the demo library has no station')
    track = {'id': station.id, 'type': 'radioStation', 'isLive': True,
             'catalogId': station.id, 'title': station.title, 'artist': '', 'album': '',
             'trackNumber': 1, 'discNumber': 1, 'durationMs': 0, 'durationLabel': '0:00',
             'explicit': False, 'artUrl': demo_art_url(station), 'index': 0}
    return {
        'state': 'playing', 'track': track, 'position': 112, 'duration': 160,
        'shuffle': 'off', 'repeat': 'none', 'volume': 0.7,
        'queue': {'index': 0, 'items': [track], 'editable': False},
        'capabilities': dict.fromkeys(('canSeek', 'canPause', 'canSkipToNextItem',
                                       'canSkipToPreviousItem'), False),
    }


AUTOPLAY_AFTER = 4   # the album's tracks an invented queue with autoplay keeps
AUTOPLAY_COUNT = 5   # and the entries autoplay added after them
HISTORY_ALBUMS = 3   # an invented queue with history: the albums played before
HISTORY_COUNT = 2    # and the tracks of each


def invented_session(app, position=None):
    """A Player.restore() session (session.read()'s shape) of invented_playing_state's: the
    demo's first album as the queue, its first track paused `position` seconds in, the
    album its source."""
    state = invented_playing_state(app, position=position)
    queue = [{key: value for key, value in entry.items() if key != 'index'}
             for entry in state['queue']['items']]
    return {'queue': queue, 'index': 0, 'offset': 0, 'position': state['position'],
            'duration': state['duration'], 'repeat': 'none',
            'source': {'kind': 'album', 'id': app.library.albums.get_item(0).id}}


def popovers(widget):
    """The popovers shown under widget (each a child of the widget it points from), depth
    first."""
    from gi.repository import Gtk

    found = []
    if isinstance(widget, Gtk.Popover) and widget.get_visible():
        found.append(widget)
    child = widget.get_first_child()
    while child is not None:
        found.extend(popovers(child))
        child = child.get_next_sibling()
    return found
