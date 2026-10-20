#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""Render the app's window to a PNG, for checking UI changes without a human.

    scripts/headless.sh scripts/screenshot.py [out.png] --demo [--light] [--rtl] [--size WxH]
                          [--page KEY] [--open KIND:ID] [--sidebar] [--expand ID[,ID…]]
                          [--banner sign-in|expired] [--signed-in [NAME]]
                          [--now-playing [lyrics|localized|syllable|queue]]
                          [--fullscreen-player [lyrics|localized|syllable|none]]
                          [--idle] [--position SECONDS] [--playing] [--restored]
                          [--autoplay] [--history] [--album N]
                          [--search TERM [--search-in music|library] [--search-kind KIND]
                           [--see-all KEY]]
                          [--context-menu [KIND] [--submenu NAME]]
                          [--preferences [general|engine]]
                          [--dialog about|shortcuts|new-playlist|new-folder|rename|delete|
                                    remove-from-library]
                          [--more-options] [--main-menu] [--sidebar-menu KEY [--submenu NAME]]
                          [--drop-target KEY] [--drop-line N] [--scroll PX]

Builds nothing itself: run meson install -C build (or scripts/demo.sh) first. Run it
through scripts/headless.sh, so the window opens on a private display and never on
the desktop. The window is really mapped for a moment, so --size is only a request:
a tiling window manager may choose its own. Settings go to a memory backend,
and animations are off, so transitions finish at once. The shots use stock
GNOME's icons and font (the Adwaita icon theme, Adwaita Sans 11), not the
desktop's (scripts/harness.py). Before the shot, the script waits until no
artwork decode has been in flight for a few polls (5 s at most), so tiles show
their covers rather than placeholders.
In the narrow (collapsed) layout the shot shows the sidebar, or the page when
--page is given (--sidebar keeps the sidebar, scrolled to the page's row).
--demo shows the invented library in build/demo (generated first if missing)
or in $APPLE_MUSIC_CACHE when that is set, as scripts/demo.sh does. The shot
waits for the library to finish loading.
--open KIND:ID opens an item once the library has loaded, as activating its
tile does (window.open_item), over the --page (default home): KIND is album,
artist, playlist, folder, station or video, and ID an item id or "first", the
first of that section (for folder, the library's first playlist folder). An
artist opens as the library's page of them; artist-page:ID opens Apple Music's
page of the artist instead, as Go to Artist does (window.open_artist_page);
category:ID the page of a category the demo library invented (a radio show's,
categories/<ID>.json), as its tile does; charts:top opens the Charts
page, as its Top Charts tile does (the demo's invented charts.json). An
ID the library lacks opens the catalog's album or playlist of that id, as a
shelf's tile would: one of the demo's invented catalog answers (an album page's
or an artist page's shelves, demo.edition0010 say), else the catalog's copy of
the library's album or playlist with that catalog id (in the library, then).
--page also takes a sidebar playlist or folder, as last-page names them:
playlist:ID or folder:ID (folder:first too). --expand opens these playlist
folders in the sidebar (the expanded-folders setting); "first" is the library's
first folder.
--banner sign-in|expired reveals the sign-in banner as a signed-out release build,
or one whose sign-in expired, shows it (the demo has no account, so none).
--signed-in shows the account button as signed in (the signed-in and account-name
settings, in the memory backend only), with NAME on it when given; the engine is
never started here.
--now-playing puts an invented item on the Player (the first track of the demo
library's first album, playing, its queue the album, the synced lyrics of
tests/fixtures/lyrics.json, the album's cover as its artwork) and opens the Now
Playing sheet on its Lyrics tab, or on Up Next with "queue"; "localized" shows the
Lyrics tab with tests/fixtures/lyrics_localized.json's lines, which have
pronunciations and translations (--setting lyrics-pronunciations=true and
lyrics-translations=true show them), and "syllable" with lyrics_syllable.json's, an
invented word-timed duet (syllables, background vocals, two singers and a group, a long
intro and a long break between verses) with pronunciations and translations too.
--autoplay makes the queue the album's first four tracks and five of the next album's
as entries autoplay added, which Up Next shows under its Autoplay header. --history
puts two tracks of each of three other albums before the item in the queue, played
already, and with --now-playing queue shows them: Up Next's History. --album N plays
the demo's Nth album (0, the first, by default): another cover, the sheet's tint
another colour. Each album's entries have their own artwork.
With --demo only.
--position SECONDS puts the invented item that many seconds in (65 by default: a
line of each lyrics fixture is current), say mid-word, or inside a break.
--playing puts the same item on the Player and leaves the sheet closed: the player
bar in its playing state. --restored shows it as the last session restored at launch
(Player.restore): paused at --position, its queue the album, MusicKit not asked. With
--demo only.
--fullscreen-player puts the same item on the Player with the lyrics of the fixture
named (syllable by default; none: a song without lyrics) and enters the full-screen
player (win.fullscreen-player, F11's). The harness's window is not resizable, so the
headless mutter keeps it at --size while it is full screen: the shot is the player at
that size. --idle shoots it with the controls and the cursor hidden. With --demo only.
--search TERM shows the Search page in Your Library mode with TERM typed (the
results of the offline filter; the engine is never started here). --search-in music
searches Apple Music instead, as Enter does: with --demo, the demo's invented catalog
answers (its search of `tide` has every kind, and more songs than a shelf shows);
--search-kind KIND chooses the filter first (songs, albums, radio-shows… : the list of
that kind), and --see-all KEY then opens the See All of the shelf KEY (songs…).
--context-menu pops up the context menu of the page's first tile or row (the
first shown widget with a context_item; with KIND, the first whose item is of
that kind, such as category), as a right click on it would, and
draws the popover into the shot where the compositor put it. --submenu NAME
shows its submenu labelled NAME (a GtkPopoverMenu names each submenu by its
label, mnemonic underscore and all: "Add to Pla_ylist", a folder's name inside
it) rather than its top level.
--preferences opens the Preferences dialog (app.preferences) on its General page, or
on Engine, and shoots it: inside the window when libadwaita put it there, else its
own window (a fixed-size window that is neither maximized nor tiled gets one), at
--size when that is narrower than 640 px.
--dialog opens the About (app.about) or Keyboard Shortcuts (app.shortcuts) dialog and
shoots it as --preferences does; new-playlist, new-folder, rename and delete open the
playlists' dialogs (win.item-new-playlist, win.item-new-folder, win.item-rename,
win.item-delete) for the playlist or folder the page shows, else the library's first playlist
of the user's (a new playlist or folder: in the folder shown, else at the top level);
remove-from-library the confirmation of win.item-remove-from-library for the item the page
shows, else the library's first album. The demo writes nothing: the dialogs only show.
--more-options pops up the More Options menu of the page shown (an album's, a playlist's, a
folder's) as a click on it would; --main-menu the main menu (in the narrow layout, with
--sidebar, where its button is).
--sidebar-menu KEY pops up the sidebar's context menu for KEY (playlist:ID, folder:ID,
all-playlists; playlist:first and folder:first are the library's first of each), drawn from
the menu the sidebar fills for it, beside its row (--expand the folder holding it); with
--submenu NAME, its submenu of that label ("Mov_e to Folder").
--drop-target KEY marks KEY's sidebar row (as --sidebar-menu names one) as where a drop goes,
as a drag over it that the row takes marks it (SidebarController.show_drop_target, which the
sidebar's drop-enter calls): the drop highlight, which no headless script can drag to.
--drop-target player-bar highlights the player bar so (PlayerBar.show_drop_target), with
--playing.
--drop-line N draws the insertion line a drag of one of its songs shows on a playlist's page
(--open playlist:ID, one of the user's), above its song at index N (0: the first; -1: below
the last), as DetailPage.show_insertion() draws it.
--scroll PX scrolls the page shown down by PX pixels before the shot (its first
scrolled window that scrolls vertically): the rest of a page taller than the
virtual monitor, which a --size cannot show.
--focus gives the keyboard focus to the page's first tile or row (its grid cell or list row,
as Tab would), with the focus ring shown: a music video's play symbol shows with it.
--rtl lays the window out right to left, as a right-to-left language would
(Gtk.Widget.set_default_direction), its strings still the source's.
"""

import argparse
import json
import os
import sys

import harness

parser = argparse.ArgumentParser()
parser.add_argument('out', nargs='?', default=os.path.join(harness.ROOT, 'build',
                                                            'screenshot.png'))
parser.add_argument('--light', action='store_true')
parser.add_argument('--rtl', action='store_true', help='lay the window out right to left')
parser.add_argument('--size', default='1100x760')
parser.add_argument('--page')
parser.add_argument('--demo', action='store_true', help='show the demo library in build/demo')
parser.add_argument('--open', metavar='KIND:ID',
                    help='open an item (ID an item id or "first") over the page; '
                         "artist-page:ID for Apple Music's page of an artist, charts:top "
                         'for the Charts page')
parser.add_argument('--sidebar', action='store_true',
                    help='in the narrow layout, show the sidebar rather than the --page')
parser.add_argument('--expand', metavar='ID[,ID…]', default='',
                    help='expand these playlist folders in the sidebar ("first": the first one)')
parser.add_argument('--banner', choices=['sign-in', 'expired'],
                    help='reveal the sign-in banner as a signed-out release build, or one '
                         'whose sign-in expired, shows it (the demo has no account)')
parser.add_argument('--signed-in', metavar='NAME', nargs='?', const='',
                    help='show the account as signed in, as NAME when given')
parser.add_argument('--now-playing', metavar='TAB', nargs='?', const='lyrics',
                    choices=['lyrics', 'localized', 'syllable', 'queue'],
                    help='an invented item playing, the Now Playing sheet open on TAB')
parser.add_argument('--position', metavar='SECONDS', type=float,
                    help='with --now-playing or --playing, the item that many seconds in')
parser.add_argument('--fullscreen-player', metavar='LYRICS', nargs='?', const='syllable',
                    choices=['lyrics', 'localized', 'syllable', 'none'],
                    help='an invented item playing, in the full-screen player')
parser.add_argument('--idle', action='store_true',
                    help='with --fullscreen-player, the controls hidden as when idle')
parser.add_argument('--playing', action='store_true',
                    help='an invented item playing, the sheet closed (the player bar)')
parser.add_argument('--restored', action='store_true',
                    help='the invented item as the last session restored at launch, paused')
parser.add_argument('--autoplay', action='store_true',
                    help='with --now-playing: entries autoplay added at the end of the queue')
parser.add_argument('--history', action='store_true',
                    help='with --now-playing or --fullscreen-player: entries played before '
                         'the item in the queue (with --now-playing queue: History shown)')
parser.add_argument('--album', metavar='N', type=int, default=0,
                    help='with --now-playing, --playing or --fullscreen-player: the demo '
                         "library's Nth album playing (0: the first)")
parser.add_argument('--search', metavar='TERM',
                    help='the Search page in Your Library mode with TERM typed')
parser.add_argument('--search-in', choices=['music', 'library'], default='library',
                    help='with --search, the mode searched (Apple Music: Enter pressed)')
parser.add_argument('--search-kind', metavar='KIND',
                    help="with --search-in music, the filter's kind (songs, albums…)")
parser.add_argument('--see-all', metavar='KEY',
                    help='with --search-in music, open the See All of the shelf KEY')
parser.add_argument('--context-menu', metavar='KIND', nargs='?', const=True,
                    help="pop up the context menu of the page's first tile or row (of KIND)")
parser.add_argument('--submenu', metavar='NAME',
                    help='with --context-menu, show the submenu labelled NAME')
parser.add_argument('--preferences', metavar='PAGE', nargs='?', const='general',
                    choices=['general', 'engine'],
                    help='open Preferences on PAGE and shoot the dialog')
parser.add_argument('--dialog', choices=['about', 'shortcuts', 'new-playlist', 'new-folder',
                                         'rename', 'delete', 'remove-from-library'],
                    help='open the About, Keyboard Shortcuts, a playlist or the Remove from '
                         'Library dialog; shoot it')
parser.add_argument('--more-options', action='store_true',
                    help='pop up the More Options menu of the page shown')
parser.add_argument('--main-menu', action='store_true',
                    help="pop up the main menu (the sidebar's header bar's)")
parser.add_argument('--sidebar-menu', metavar='KEY',
                    help="pop up the sidebar's context menu for KEY")
parser.add_argument('--drop-target', metavar='KEY',
                    help="mark KEY's sidebar row as a drop's target (player-bar: the bar)")
parser.add_argument('--drop-line', metavar='N', type=int,
                    help="the insertion line above the playlist's song N (-1: below the last)")
parser.add_argument('--scroll', metavar='PX', type=int, default=0,
                    help='scroll the page shown down by PX pixels before the shot')
parser.add_argument('--focus', action='store_true',
                    help="give the keyboard focus to the page's first tile or row")
parser.add_argument('--setting', metavar='KEY=VALUE', action='append', default=[],
                    help='set a setting first (VALUE in GVariant text: true, 3, "text"), in '
                         'the memory backend only; repeatable')
args = parser.parse_args()
if args.search:
    args.page = 'search'
if (args.search_kind or args.see_all) and not (args.search and args.search_in == 'music'):
    parser.error('--search-kind and --see-all need --search TERM --search-in music')
if args.submenu and not (args.context_menu or args.sidebar_menu):
    parser.error('--submenu needs --context-menu or --sidebar-menu')
if (args.now_playing or args.playing or args.restored or args.fullscreen_player) \
        and not args.demo:
    parser.error('--now-playing, --playing, --restored and --fullscreen-player need --demo')
if args.drop_target == 'player-bar' and not args.playing:
    parser.error('--drop-target player-bar needs --playing')
if args.autoplay and not args.now_playing:
    parser.error('--autoplay needs --now-playing')
if args.history and not (args.now_playing or args.fullscreen_player):
    parser.error('--history needs --now-playing or --fullscreen-player')
if args.album and not (args.now_playing or args.playing or args.fullscreen_player):
    parser.error('--album needs --now-playing, --playing or --fullscreen-player')
if args.position is not None and not (args.now_playing or args.playing or args.restored
                                      or args.fullscreen_player):
    parser.error('--position needs --now-playing, --playing, --restored or '
                 '--fullscreen-player')
if args.idle and not args.fullscreen_player:
    parser.error('--idle needs --fullscreen-player')
width, height = (int(n) for n in args.size.split('x'))

app = harness.make_app('Screenshot', demo=args.demo, light=args.light, size=(width, height))

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk  # noqa: E402  (after make_app)

if args.rtl:
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)  # before the window is made


def first_folder():
    """The id of the first playlist folder of the library the app will load, or None."""
    from applemusic.backend import config
    try:
        with open(config.cache_dir() / 'library.json', encoding='utf-8') as file:
            folders = json.load(file).get('folders') or []
    except (OSError, ValueError):
        return None
    return next((folder['id'] for folder in folders if folder.get('id') != 'root'), None)


def on_activate(_app):
    page = args.page or 'home'
    if page == 'folder:first':
        page = f'folder:{first_folder()}'
    app.settings.set_string('last-page', page)
    expand = [folder_id for folder_id in args.expand.split(',') if folder_id]
    expand = [first_folder() if folder_id == 'first' else folder_id for folder_id in expand]
    app.settings.set_strv('expanded-folders', [folder_id for folder_id in expand if folder_id])
    if args.signed_in is not None:
        app.settings.set_boolean('signed-in', True)
        app.settings.set_string('account-name', args.signed_in)  # no engine: autostart is off
    for setting in args.setting:
        key, _sep, text = setting.partition('=')
        kind = app.settings.get_value(key).get_type_string()
        app.settings.set_value(key, GLib.Variant.parse(GLib.VariantType(kind), text))
    GLib.timeout_add(1200, shoot)


# The library's store for each kind --open takes.
SECTIONS = {'album': 'albums', 'artist': 'artists', 'playlist': 'playlists', 'station': 'radio',
            'video': 'videos'}
opened = False
sheet_opened = False
searched = False
seen_all = False
menu_opened = False
banner_shown = False
scrolled = False
focused = False
drop_line_scrolled = False
failed = False  # a step raised: the app quits and the script exits 1
preferences = None  # the Preferences dialog, once --preferences has opened it
dialog = None  # the --dialog dialog, once opened
# Waiting for the artwork before the shot: a poll every ARTWORK_POLL ms, the shot once
# ARTWORK_QUIET polls in a row found no decode in flight (an ArtworkSlot asks in an idle
# after its frame, so one quiet poll is not enough), or after ARTWORK_POLLS polls whatever.
ARTWORK_POLL = 100
ARTWORK_QUIET = 3
ARTWORK_POLLS = 50
artwork_polls = 0
artwork_quiet = 0


def open_now_playing(window):
    """--now-playing: the invented item on the Player (the demo's first album playing, with
    the lyrics fixture) and the sheet open on the tab; --playing: the item only, for the
    player bar; --restored: the item as the last session restored, paused."""
    if args.restored:
        app.player.restore(harness.invented_session(app, position=args.position))
        return
    chosen = args.fullscreen_player or args.now_playing
    fixture = chosen if chosen in harness.LYRICS_FIXTURES else 'lyrics'
    app.player.apply(harness.invented_playing_state(app, lyrics=chosen != 'none',
                                                    fixture=fixture, position=args.position,
                                                    autoplay=args.autoplay, album=args.album,
                                                    history=args.history))
    if args.fullscreen_player:
        window.activate_action('win.fullscreen-player', None)
        if args.idle:
            window.fullscreen_host.view.set_idle(True)
    elif args.now_playing:
        window.now_playing.tab_stack.set_visible_child_name(
            'queue' if args.now_playing == 'queue' else 'lyrics')
        window.bottom_sheet.set_open(True)
        if args.history and args.now_playing == 'queue':
            window.now_playing.queue_view.history_button.set_active(True)


def search_library(window):
    """--search: Your Library mode (or --search-in's) with the term typed into the entry;
    Apple Music's searched as Enter does, with --search-kind's filter."""
    page = window.navigation_view.get_visible_page()
    page.set_mode(args.search_in)
    if args.search_kind:
        page.set_kind(args.search_kind)
    page.search_entry.set_text(args.search)
    if args.search_in == 'music':
        page.search_entry.emit('activate')


def open_see_all(window):
    """--see-all: the See All of the search's shelf KEY, as its button opens it."""
    page = window.navigation_view.get_visible_page()
    shelf = next((shelf for shelf in page._column.shelves if shelf.key == args.see_all), None)
    if shelf is None:
        sys.exit(f'screenshot: no {args.see_all} shelf in the results')
    window.open_shelf(shelf)


def catalog_item(kind, item_id):
    """The catalog's album or playlist of that id, as a shelf's tile would carry it: from the
    demo's invented answers (albums/, artists/), else a copy of the library's Item whose
    catalog id it is, under that id. None when neither has it."""
    from applemusic.backend import config
    from applemusic.library import Item
    from applemusic.remote import remote_item

    for path in sorted(config.cache_dir().glob('albums/*.json')) + sorted(
            config.cache_dir().glob('artists/*.json')):
        try:
            with open(path, encoding='utf-8') as file:
                answer = json.load(file)
        except (OSError, ValueError):
            continue
        for shelf in answer.get('shelves') or []:
            for data in shelf.get('items') or []:
                if data.get('kind') == kind and data.get('id') == item_id:
                    return Item(remote_item(data))
    store = getattr(app.library, SECTIONS.get(kind, ''), None)
    for position in range(store.get_n_items() if store is not None else 0):
        item = store.get_item(position)
        if item.catalog_id == item_id:
            play = {'kind': kind, 'id': item_id}
            groups = [dict(group, play=play) for group in item.raw.get('groups') or []]
            return Item(dict(item.raw, id=item_id, play=play, groups=groups))
    return None


def open_item(window):
    """--open: the item it names, opened as its tile would be."""
    kind, _sep, item_id = args.open.partition(':')
    if kind == 'charts':
        from applemusic.pages.charts import charts_item

        window.open_item(charts_item())
        return
    catalog = kind == 'artist-page'  # Apple Music's page of the artist, as Go to Artist opens
    if catalog:
        kind = 'artist'
    if item_id == 'first' and kind in SECTIONS:
        item = getattr(app.library, SECTIONS[kind]).get_item(0)
    elif item_id == 'first' and kind == 'folder':
        item = app.library.by_id('folder', first_folder())
    elif kind == 'category':
        item = invented_category(item_id)
    else:
        item = app.library.by_id(kind, item_id) or catalog_item(kind, item_id)
    if item is None:
        sys.exit(f'screenshot: no {args.open} in the library')
    if catalog:
        window.open_artist_page(item)
    else:
        window.open_item(item)


def invented_category(item_id):
    """The category Item whose page the demo library invented (categories/<id>.json), named
    as its page is; None without one."""
    from applemusic.backend import config, normalize
    from applemusic.library import Item

    try:
        with open(normalize.category_cache_path(str(config.cache_dir()), item_id),
                  encoding='utf-8') as file:
            page = json.load(file)
    except (OSError, ValueError):
        return None
    return Item({'id': item_id, 'kind': 'category', 'title': page.get('title') or ''})


def first_context_widget(widget, kind=None):
    """The first mapped widget under `widget` with a context_item (of `kind`, when given),
    depth first."""
    item = getattr(widget, 'context_item', None)
    if item is not None and widget.get_mapped() and kind in (None, getattr(item, 'kind', None)):
        return widget
    child = widget.get_first_child()
    while child is not None:
        if child.get_mapped():
            found = first_context_widget(child, kind)
            if found is not None:
                return found
        child = child.get_next_sibling()
    return None


def open_context_menu(window):
    """--context-menu: the first tile's or row's menu, pointing into it as a click would."""
    from applemusic.widgets import context_menu

    kind = args.context_menu if isinstance(args.context_menu, str) else None
    widget = first_context_widget(window.navigation_view.get_visible_page(), kind)
    if widget is None:
        sys.exit('screenshot: nothing on the page has a context menu')
    x, y = widget.get_width() * 0.6, widget.get_height() * 0.35
    popover = context_menu.popup(widget, widget.context_item, x, y)
    if popover is None:
        sys.exit('screenshot: the first item has no menu')
    if args.submenu:
        popover.set_property('visible-submenu', args.submenu)


def focus_first(window):
    """--focus: the first tile's or row's cell focused, as Tab would, its focus ring shown."""
    widget = first_context_widget(window.navigation_view.get_visible_page())
    if widget is None:
        sys.exit('screenshot: nothing on the page takes the focus')
    cell = widget.get_parent()  # the grid cell or the list row, which a tile sits in
    if not cell.grab_focus():
        sys.exit('screenshot: the first tile or row did not take the focus')
    window.set_focus_visible(True)


def find_widget(widget, kind):
    """The first widget of type kind under widget (itself included), depth first, or None."""
    if isinstance(widget, kind):
        return widget
    child = widget.get_first_child()
    while child is not None:
        found = find_widget(child, kind)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def first_playlist():
    """The library's first playlist of the user's (one that can be renamed), or None."""
    return next((node.item for node in app.library.playlist_tree().flat
                 if node.kind == 'playlist' and node.item.editable), None)


def subject(window):
    """The playlist or folder the page shows (a pushed one's, or the sidebar key's), else
    the library's first playlist of the user's."""
    item = window.shown_item()
    if item is not None and item.kind in ('playlist', 'folder'):
        return item
    kind, _sep, item_id = (args.page or '').partition(':')
    if kind == 'folder' and item_id == 'first':
        item_id = first_folder()
    item = app.library.by_id(kind, item_id) if kind in ('playlist', 'folder') else None
    return item or first_playlist()


def open_playlist_dialog(window):
    """--dialog new-playlist, new-folder, rename or delete: the item action, as its menu item
    runs it."""
    item = subject(window)
    if args.dialog in ('new-playlist', 'new-folder'):
        folder = item.id if item is not None and item.kind == 'folder' else 'root'
        target = ('folder', folder)
    elif item is None:
        sys.exit("screenshot: no playlist of the user's to show the dialog for")
    else:
        target = (item.kind, item.id)
    window.activate_action(f'win.item-{args.dialog}', GLib.Variant('(ss)', target))


def open_removal_dialog(window):
    """--dialog remove-from-library: the confirmation, as the menu item asks it, for the
    item the page shows, else the library's first album."""
    item = window.shown_item() or (app.library.albums.get_item(0)
                                   if app.library.albums.get_n_items() else None)
    if item is None:
        sys.exit('screenshot: nothing in the library to show the dialog for')
    window.activate_action('win.item-remove-from-library',
                           GLib.Variant('(ss)', (item.kind, item.id)))


def open_more_options(window):
    """--more-options: the page's More Options menu, popped up."""
    page = window.navigation_view.get_visible_page()
    button = next((found for found in harness_descendants(page, Gtk.MenuButton)
                   if found.get_tooltip_text() == 'More Options' and found.get_mapped()), None)
    if button is None:
        sys.exit('screenshot: the page shown has no More Options menu')
    button.popup()


def open_sidebar_menu(window):
    """--sidebar-menu: the menu the sidebar fills for the key's item (sidebar_view's
    setup-menu handler), popped up beside its row as the sidebar shows it."""
    key = sidebar_key(args.sidebar_menu)
    sidebar = window._sidebar
    item = sidebar.item_for(key)
    row = sidebar.row(item.get_index()) if item is not None else None
    if row is None:
        sys.exit(f'screenshot: no sidebar row for {key}')
    sidebar._on_setup_menu(None, item)
    popover = Gtk.PopoverMenu.new_from_model(sidebar._sidebar_menu)
    popover.set_has_arrow(False)
    popover.set_parent(row)
    rectangle = Gdk.Rectangle()
    rectangle.x, rectangle.y = int(row.get_width() * 0.4), int(row.get_height() * 0.6)
    rectangle.width = rectangle.height = 1
    popover.set_pointing_to(rectangle)
    popover.set_halign(Gtk.Align.START)
    popover.popup()
    if args.submenu:
        popover.set_property('visible-submenu', args.submenu)


def sidebar_key(key):
    """A sidebar key, with playlist:first and folder:first the library's first of each."""
    if key == 'folder:first':
        return f'folder:{first_folder()}'
    if key == 'playlist:first':
        return f'playlist:{first_playlist().id}'
    return key


def mark_drop_target(window):
    """--drop-target: the row marked as where a drop goes, scrolled into view (or the
    player bar highlighted)."""
    if args.drop_target == 'player-bar':
        window.player_bar.show_drop_target()
        return
    key = sidebar_key(args.drop_target)
    sidebar = window._sidebar
    item = sidebar.item_for(key)
    row = sidebar.row(item.get_index()) if item is not None else None
    if row is None:
        sys.exit(f'screenshot: no sidebar row for {key}')
    sidebar.show_drop_target(key)
    viewport = row.get_ancestor(Gtk.Viewport)
    if viewport is not None:
        viewport.scroll_to(row, None)


def drop_line_place(page):
    """--drop-line's song index on the page, and whether the line is below it."""
    count = len(page.item.track_ids() or ()) if getattr(page, 'item', None) else 0
    return (count - 1, True) if args.drop_line < 0 else (args.drop_line, False)


def scroll_to_drop_line(window):
    """--drop-line, first: the song's row scrolled into view (in a narrow window the hero
    takes the first screen), so the list has made it."""
    page = window.navigation_view.get_visible_page()
    if getattr(page, 'show_insertion', None) is None:
        sys.exit('screenshot: --drop-line needs a playlist page (--open playlist:ID)')
    index, _after = drop_line_place(page)
    page.list_view.scroll_to(1 + index, Gtk.ListScrollFlags.NONE, None)  # after the hero


def mark_drop_line(window):
    """--drop-line, then: the insertion line on the playlist page shown."""
    page = window.navigation_view.get_visible_page()
    if not page.show_insertion(*drop_line_place(page)):
        sys.exit(f'screenshot: no insertion line for song {args.drop_line} on this page')


def harness_descendants(widget, kind):
    if isinstance(widget, kind):
        yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from harness_descendants(child, kind)
        child = child.get_next_sibling()


def open_dialog(window):
    """--dialog: the About or Keyboard Shortcuts dialog, as its menu item opens it (inside
    the window, or in a window of its own), or a playlist dialog; the dialog, or None when
    none is shown."""
    if args.dialog in ('new-playlist', 'new-folder', 'rename', 'delete'):
        open_playlist_dialog(window)
        kind = Adw.AlertDialog
    elif args.dialog == 'remove-from-library':
        open_removal_dialog(window)
        kind = Adw.AlertDialog
    else:
        kind = {'about': Adw.AboutDialog, 'shortcuts': Adw.ShortcutsDialog}[args.dialog]
        app.activate_action(args.dialog)
    shown = next((found for found in map(lambda toplevel: find_widget(toplevel, kind),
                                         Gtk.Window.list_toplevels()) if found is not None),
                 None)
    if isinstance(shown, Adw.AboutDialog) and harness.installed_icon():
        shown.set_application_icon(harness.installed_icon())  # not the script's own app ID
    if shown is not None and width < 640:
        shown.set_content_width(width)  # as narrow as the window, as for --preferences
        shown.set_content_height(height)
    return shown


def draw_popovers(window, snapshot):
    """Draw the window's popovers over it, each where its surface is: a popup's position is
    relative to the window's surface, both offset by their shadows' margins."""
    window_x, window_y = window.get_surface_transform()
    for popover in harness.popovers(window):
        if not popover.get_mapped():
            continue
        surface = popover.get_surface()
        popover_x, popover_y = popover.get_surface_transform()
        point = Graphene.Point()
        point.x = surface.get_position_x() + popover_x - window_x
        point.y = surface.get_position_y() + popover_y - window_y
        snapshot.save()
        snapshot.translate(point)
        Gtk.WidgetPaintable(widget=popover).snapshot(
            snapshot, popover.get_width(), popover.get_height())
        snapshot.restore()


def scroll_page(window):
    """Scroll the visible page's first vertically scrolling scrolled window that is shown by
    args.scroll (not one in a stack's hidden child: an empty state's status page has one)."""
    def find(widget):
        if not widget.get_mapped():
            return None
        if isinstance(widget, Gtk.ScrolledWindow) and \
                widget.props.vscrollbar_policy != Gtk.PolicyType.NEVER:
            return widget
        child = widget.get_first_child()
        while child is not None:
            found = find(child)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    scrolled_window = find(window.navigation_view.get_visible_page())
    if scrolled_window is None:
        sys.exit('screenshot: the page shown does not scroll')
    adjustment = scrolled_window.get_vadjustment()
    adjustment.set_value(min(args.scroll, adjustment.get_upper() - adjustment.get_page_size()))


def artwork_settled():
    """Whether the artwork has arrived: ARTWORK_QUIET polls in a row with no decode in
    flight, or ARTWORK_POLLS polls in all."""
    global artwork_polls, artwork_quiet
    from applemusic.widgets import artwork

    artwork_polls += 1
    artwork_quiet = 0 if artwork.get_default().pending() else artwork_quiet + 1
    return artwork_quiet >= ARTWORK_QUIET or artwork_polls >= ARTWORK_POLLS


def shoot():
    """One step of the shot (each stage waits for the next frame), or the shot itself. A
    step that raises ends the run: the app quits, the traceback shown, rather than waiting
    for a step that never comes."""
    global failed
    try:
        return _shoot()
    except Exception:
        import traceback

        traceback.print_exc()
        failed = True
        app.quit()
        return GLib.SOURCE_REMOVE


def _shoot():
    global opened, sheet_opened, searched, menu_opened, banner_shown, preferences, dialog
    global seen_all
    global scrolled, focused, drop_line_scrolled
    if app.library.props.state == 'loading':
        GLib.timeout_add(100, shoot)  # pages show what loaded, not "Loading…"
        return GLib.SOURCE_REMOVE
    window = app.get_active_window()
    split_view = window.split_view
    showing_sidebar = split_view.get_collapsed() and not split_view.get_show_content()
    if (args.page or args.open) and showing_sidebar and not args.sidebar:
        split_view.set_show_content(True)  # the page, not the sidebar
        GLib.timeout_add(600, shoot)  # after the transition
        return GLib.SOURCE_REMOVE
    if args.open and not opened:
        opened = True
        open_item(window)
        GLib.timeout_add(1500, shoot)  # after the push, with the artwork decoded
        return GLib.SOURCE_REMOVE
    if (args.now_playing or args.playing or args.restored or args.fullscreen_player) \
            and not sheet_opened:
        sheet_opened = True
        open_now_playing(window)
        GLib.timeout_add(1500, shoot)  # the sheet open, the artwork decoded
        return GLib.SOURCE_REMOVE
    if args.search and not searched:
        searched = True
        search_library(window)
        GLib.timeout_add(1500, shoot)  # after the debounce, the songs built, artwork decoded
        return GLib.SOURCE_REMOVE
    if args.see_all and not seen_all:
        seen_all = True
        open_see_all(window)
        GLib.timeout_add(1500, shoot)  # after the push, the next page in, artwork decoded
        return GLib.SOURCE_REMOVE
    if args.context_menu and not menu_opened:
        menu_opened = True
        open_context_menu(window)
        GLib.timeout_add(800, shoot)  # the popover shown and placed
        return GLib.SOURCE_REMOVE
    if args.more_options and not menu_opened:
        menu_opened = True
        open_more_options(window)
        GLib.timeout_add(800, shoot)  # the popover shown and placed
        return GLib.SOURCE_REMOVE
    if args.main_menu and not menu_opened:
        menu_opened = True
        if not window.primary_menu_button.get_mapped():
            sys.exit('screenshot: the main menu button is not shown (narrow: add --sidebar)')
        window.primary_menu_button.popup()
        GLib.timeout_add(800, shoot)  # the popover shown and placed
        return GLib.SOURCE_REMOVE
    if args.sidebar_menu and not menu_opened:
        menu_opened = True
        open_sidebar_menu(window)
        GLib.timeout_add(800, shoot)
        return GLib.SOURCE_REMOVE
    if args.drop_target and not menu_opened:
        menu_opened = True
        mark_drop_target(window)
        GLib.timeout_add(400, shoot)
        return GLib.SOURCE_REMOVE
    if args.drop_line is not None and not menu_opened:
        if not drop_line_scrolled:
            drop_line_scrolled = True
            scroll_to_drop_line(window)
            GLib.timeout_add(800, shoot)  # scrolled, the row made and its artwork decoded
            return GLib.SOURCE_REMOVE
        menu_opened = True
        mark_drop_line(window)
        GLib.timeout_add(400, shoot)
        return GLib.SOURCE_REMOVE
    if args.preferences and preferences is None:
        preferences = app.show_preferences(args.preferences)
        if width < 640:
            # A narrow --size: the dialog as narrow (a window of its own takes its content
            # size, not the main window's).
            preferences.set_content_width(width)
            preferences.set_content_height(height)
        GLib.timeout_add(1200, shoot)  # shown, the cache measured
        return GLib.SOURCE_REMOVE
    if args.dialog and dialog is None:
        dialog = open_dialog(window)
        if dialog is None:
            sys.exit(f'screenshot: no {args.dialog} dialog shown')
        GLib.timeout_add(1200, shoot)  # shown
        return GLib.SOURCE_REMOVE
    if args.banner and not banner_shown:
        banner_shown = True
        from applemusic.window import sign_in_title

        window.sign_in_banner.set_title(sign_in_title(args.banner == 'expired'))
        window.sign_in_banner.set_revealed(True)
        GLib.timeout_add(600, shoot)  # laid out under the header bar
        return GLib.SOURCE_REMOVE
    if args.scroll and not scrolled:
        scrolled = True
        scroll_page(window)
        GLib.timeout_add(1200, shoot)  # what scrolled into view bound, its artwork decoded
        return GLib.SOURCE_REMOVE
    if args.focus and not focused:
        focused = True
        focus_first(window)
        GLib.timeout_add(600, shoot)  # the focus ring and what follows it drawn
        return GLib.SOURCE_REMOVE
    if not artwork_settled():
        GLib.timeout_add(ARTWORK_POLL, shoot)
        return GLib.SOURCE_REMOVE
    for shown in (preferences, dialog):
        if shown is not None and shown.get_root() is not window:
            window = shown.get_root()  # a window of its own
    paintable = Gtk.WidgetPaintable(widget=window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    draw_popovers(window, snapshot)
    texture = window.get_renderer().render_texture(snapshot.to_node(), None)
    texture.save_to_png(args.out)
    print(args.out)
    app.quit()
    return GLib.SOURCE_REMOVE


app.connect('activate', on_activate)
harness.run_app(app)
if failed:
    sys.exit(1)
