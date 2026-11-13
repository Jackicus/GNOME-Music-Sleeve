# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The one menu of an item, built in code per kind (build_menu()): its sections, its
submenus (Add to Playlist, Move to Folder) and its labels, each with a mnemonic. The actions
its items run are actions.py's.

The menus are built in code, per kind (build_menu): Play, Play Next, Play Later (none for a
pre-release album's track not out yet: Track.unreleased), Create
Station (a song's or an artist's whose catalog id is known: station_target), and for an Up
Next entry Move to Top, Move Up, Move Down, Move to Bottom (where it can go in its section)
and Remove from Up Next, its Play Next moving it to just after the entry playing where its
section begins there (queue_play_next()); Go to
Album, Go to Artist (not where the page shown is that album or artist already), View Credits
(a song's whose catalog id is known: credits_target); Favourite or Remove from Favourites,
then Suggest Less or Undo Suggest Less (all four, of which the menu shows those whose actions
are enabled: rating_actions(), by the item's rating; as on Apple's players, a favourite
offers no Suggest Less; an artist whose catalog id is known has Favourite or Remove from
Favourites alone: favourite_items()), Add to Library (not what the
library holds already: a catalog album or playlist by Library.holds(), the test its page's
In Library makes; Pre-Add to Library for an album not out yet: pre_adds()), Add to
Playlist (a song's, a video's, an album's or a playlist's: the
library's playlists that take songs, each folder a submenu, or a section headed by its
name where a submenu's page would not be its own: playlist_submenu(); a playlist not
offered to itself, then New Playlist…), Move to Folder (a playlist's or folder's: Top
Level, the folders it can go into in one list, then New Folder…: move_targets()), Remove from
Playlist and, where it can go, Move to Top, Move Up, Move Down and Move to Bottom (a track shown
in a playlist of the user's: `container`); Open in Browser, Copy Link (only an address anyone
can open: not the web player's library routes; a library artist's is the catalog artist's page,
which the engine finds through their songs); Add Songs… (a playlist of the user's: adds_to()),
Duplicate (a library playlist: duplicates()), Edit Details… and Delete Playlist… (a playlist of
the user's, Item.editable) or Rename… and Delete Folder… (a folder of theirs), Remove from
Library… (what the library holds: removal_target; a playlist of Apple's, which cannot be deleted
as the user's own are; a catalog album or playlist held, as the library's own it was found as,
Library.held_item()); a folder's menu starts with New Playlist… and New Folder… (in it); each
only where it applies. A category (an Apple curator: a genre's page, a radio show) has Open in
Browser and Copy Link alone (curator_menu): Apple gives a curator nothing to play or favourite.

The menus of the player's queue (the item playing's in the Now Playing sheet and the player
bar, Up Next's) have no Play, which would replace the queue: activating the row plays it.
"""

from gettext import gettext as _

from gi.repository import Gio, GLib

from . import keyboard, related
from .item_targets import (adds_songs, adds_to, can_play, credits_target, describe,
                           duplicates, favourite_target, is_curator, is_folder,
                           is_manageable, library_target, playlist_song, pre_adds,
                           queue_target, rating_target, station_target)
from .library import ROOT_FOLDER, Item, Track
from .playlist_order import PlaylistOrder
from .web_links import needs_catalog_artist, needs_catalog_url, share_url, web_url

MENU_KINDS = ('album', 'playlist', 'song', 'station', 'artist', 'video', 'folder')

def action_labels():
    """The menu's labels, by action, translated on call (after gettext is set up). Each has
    a mnemonic (GtkPopoverMenu shows them with use-underline), no two the same letter."""
    return {
        'item-play': _('_Play'),
        'item-play-next': _('Play _Next'),
        'item-play-later': _('Play _Later'),
        # Translators: a menu item marking the item as a favourite (a verb; the heart).
        'item-love': _('_Favourite'),
        'item-unlove': _('_Remove from Favourites'),
        'item-suggest-less': _('_Suggest Less'),
        'item-undo-suggest-less': _('_Undo Suggest Less'),
        'item-add-to-library': _('_Add to Library'),
        'item-add-to-playlist': _('Add to Pla_ylist'),
        'item-go-to-album': _('_Go to Album'),
        'item-go-to-artist': _('Go to Ar_tist'),
        'item-open-in-browser': _('Open in Bro_wser'),
        'item-copy-link': _('Copy Lin_k'),
        'item-remove-from-playlist': _('Remo_ve from Playlist'),
        'item-remove-from-queue': _('Remove from Up Ne_xt'),
        'item-new-playlist': _('Ne_w Playlist…'),
        'item-rename': _('Rena_me…'),
        'item-delete': _('_Delete Playlist…'),
        'item-move-to-folder': _('Mov_e to Folder'),
        'item-new-folder': _('New _Folder…'),
        'item-remove-from-library': _('Remove from Li_brary…'),
        'item-create-station': _('Create Stat_ion'),
        'item-move-up': _('_Move Up'),
        'item-move-down': _('Move _Down'),
        'item-move-to-top': _('Move to T_op'),
        'item-move-to-bottom': _('Mov_e to Bottom'),
        'item-view-credits': _('View _Credits'),
        'item-duplicate': _('Dupl_icate'),
        'item-add-songs': _('Add Son_gs…'),
    }


def pre_add_label():
    """Add to Library's label for an album it pre-adds (pre_adds()); its mnemonic is Add to
    Library's."""
    # Translators: Add to Library for an album not out yet (its songs come as they are
    # released); keep the mnemonic of "_Add to Library".
    return _('Pre-_Add to Library')


def delete_label(kind):
    """Delete's label for a playlist, or for a folder (kind 'folder')."""
    return _('_Delete Folder…') if kind == 'folder' else action_labels()['item-delete']


def rename_label(kind):
    """item-rename's label: Edit Details… for a playlist (its name, description, folder and
    whether it is public, in the playlist dialog), Rename… for a folder (kind 'folder')."""
    return action_labels()['item-rename'] if kind == 'folder' else _('Edit De_tails…')


def station_items(obj):
    """Create Station for obj, when Apple can seed a station from it (station_target)."""
    named = describe(obj)
    if named is None or station_target(obj) is None:
        return []
    return [menu_item('item-create-station', GLib.Variant('(ss)', named))]


def favourite_items(obj):
    """Favourite and Remove from Favourites for an artist (favourite_target), of which a menu
    shows the one whose action is enabled, as rating_items() does: an artist has no Suggest
    Less here (Apple's is a rating, and an artist's rating path is a 404)."""
    named = describe(obj)
    if named is None or favourite_target(obj) is None:
        return []
    return rating_items(GLib.Variant('(ss)', named), ('item-love', 'item-unlove'))


def removal_items(obj, removable):
    """Remove from Library… for obj, when `removable` (its removal_target) says it is in
    the library."""
    named = describe(obj)
    if removable is None or named is None:
        return []
    return [menu_item('item-remove-from-library', GLib.Variant('(ss)', named))]


def entry_target(container, obj):
    """The item-remove-from-playlist target for the Track obj shown in the playlist Item
    `container` (one of the user's): (playlist id, track id, its index), or None."""
    if not isinstance(obj, Track) or not is_manageable(container) or not obj.id:
        return None
    if container.kind != 'playlist':
        return None
    return GLib.Variant('(ssi)', (container.id, obj.id, obj.index))


# The moves a song's or an Up Next entry's menu offers, in its order: the step (as
# keyboard.move_step() names it) and the action whose label it has.
MOVES = ((keyboard.TOP, 'item-move-to-top'), (-1, 'item-move-up'), (1, 'item-move-down'),
         (keyboard.BOTTOM, 'item-move-to-bottom'))


def move_places(index, first, last):
    """{step: the index it moves to} for the song or entry at `index` in a list from `first`
    to `last` (keyboard.move_place()): each of MOVES' steps that moves it somewhere. Move to
    Top and Move to Bottom are offered also where Move Up or Move Down goes to the same
    place, so the menu's items stay where they are from one song to the next."""
    places = {}
    for step, _action in MOVES:
        to_index = keyboard.move_place(step, index, first, last)
        if to_index is not None:
            places[step] = to_index
    return places


def move_items(container, obj):
    """Move to Top, Move Up, Move Down and Move to Bottom for the Track obj shown in the
    playlist Item `container`, where its songs can be reordered
    (PlaylistOrder.can_reorder()): each only where the track can go, not up from the first
    or down from the last. Their targets are item-move-in-playlist's (playlist id, track id,
    its index, the index to move it to)."""
    if not isinstance(obj, Track) or not obj.id or not PlaylistOrder.can_reorder(container):
        return []
    ids = container.track_ids()
    index = obj.index
    if not 0 <= index < len(ids) or ids[index] != obj.id:
        return []
    places = move_places(index, 0, len(ids) - 1)
    items = []
    for step, action in MOVES:
        if step in places:
            item = Gio.MenuItem.new(action_labels()[action], None)
            item.set_action_and_target_value(
                'win.item-move-in-playlist',
                GLib.Variant('(ssii)', (container.id, obj.id, index, places[step])))
            items.append(item)
    return items


def queue_move_items(queue_entry, moves):
    """Move to Top, Move Up, Move Down and Move to Bottom for the Up Next entry
    `queue_entry` ((index, id)), each where `moves` (the entry's context_queue_moves: {step:
    the index it moves to}) has its step. Their targets are item-move-in-queue's (index, the
    index to move it to, id)."""
    if queue_entry is None:
        return []
    index, entry_id = int(queue_entry[0]), str(queue_entry[1])
    items = []
    for step, action in MOVES:
        if step in moves:
            item = Gio.MenuItem.new(action_labels()[action], None)
            item.set_action_and_target_value(
                'win.item-move-in-queue',
                GLib.Variant('(iis)', (index, int(moves[step]), entry_id)))
            items.append(item)
    return items


def queue_play_next(queue_entry, moves):
    """What Play Next is on the Up Next entry `queue_entry` ((index, id)), by its `moves`
    (context_queue_moves): 'move' when it moves the entry to just after the one playing
    (moves' 'next', item-move-in-queue's target), None when the entry plays next already
    (moves' 'next' is None: no Play Next), or 'queue' when it queues the song again after
    the one playing, as on any other song (no queue entry, or an Autoplay entry behind the
    songs the user queued, which MusicKit's queue cannot move out of its section)."""
    if queue_entry is None or 'next' not in moves:
        return 'queue'
    return None if moves['next'] is None else 'move'


def manage_items(obj):
    """Add Songs… (a playlist of the user's), Duplicate (a library playlist), then Edit
    Details… and Delete Playlist… (or Rename… and Delete Folder…) for obj, when it is
    manageable."""
    target = GLib.Variant('(ss)', (obj.kind, obj.id)) if describe(obj) is not None else None
    items = []
    if adds_to(obj):
        items.append(menu_item('item-add-songs', target))
    if duplicates(obj):
        items.append(menu_item('item-duplicate', target))
    if is_manageable(obj):
        items += [menu_item('item-rename', target, label=rename_label(obj.kind)),
                  menu_item('item-delete', target, label=delete_label(obj.kind))]
    return items


def menu_item(action, target, label=None):
    """A Gio.MenuItem running win.<action> with target, labelled as action_labels() says."""
    item = Gio.MenuItem.new(label or action_labels()[action], None)
    item.set_action_and_target_value(f'win.{action}', target)
    return item


RATING_ACTIONS = ('item-love', 'item-unlove', 'item-suggest-less', 'item-undo-suggest-less')


def rating_actions(value):
    """Which of RATING_ACTIONS are enabled (and so shown) for an item rated `value` (1
    loved, -1 Suggest Less, 0 neither): Favourite or Remove from Favourites, and Suggest Less
    or Undo Suggest Less, but no Suggest Less beside a favourite, as Apple's players have it.
    Favourite replaces a Suggest Less (one rating an item)."""
    return {
        'item-love': value != 1,
        'item-unlove': value == 1,
        'item-suggest-less': value == 0,
        'item-undo-suggest-less': value == -1,
    }


def rating_items(target, actions=RATING_ACTIONS):
    """The rating's items (RATING_ACTIONS, or those of `actions`), of which a menu shows
    those whose actions are enabled (GMenu's hidden-when): ItemActions keeps the actions'
    state as the item's rating (rating_actions()), so the menu follows an answer without its
    items being replaced."""
    items = []
    for action in actions:
        item = menu_item(action, target)
        item.set_attribute_value('hidden-when', GLib.Variant('s', 'action-disabled'))
        items.append(item)
    return items


def mnemonic_escaped(title):
    """A name of the user's as a menu label: its underscores doubled, since the label's
    underscores are mnemonics."""
    return title.replace('_', '__')


def folder_path(titles):
    """A folder's name as a menu shows it, `titles` the names of the folders holding it and
    its own, outermost first: "Evenings › Late Night" for a folder inside another, Untitled
    Folder for one without a name."""
    names = [title or _('Untitled Folder') for title in titles]
    path = names[0]
    for name in names[1:]:
        # Translators: a folder inside another, as Add to Playlist and Move to Folder name
        # it: "Evenings › Late Night".
        path = _('{outer} › {inner}').format(outer=path, inner=name)
    return path


def submenu_labels(menu):
    """The labels of every submenu in a Gio.MenuModel, nested ones and those in its sections
    too, as a Gtk.PopoverMenu names their pages (the label, mnemonic underscores and all)."""
    found = []
    for position in range(menu.get_n_items()):
        submenu = menu.get_item_link(position, Gio.MENU_LINK_SUBMENU)
        if submenu is not None:
            label = menu.get_item_attribute_value(position, Gio.MENU_ATTRIBUTE_LABEL, None)
            found.append(label.unpack() if label is not None else '')
        for linked in (submenu, menu.get_item_link(position, Gio.MENU_LINK_SECTION)):
            if linked is not None:
                found.extend(submenu_labels(linked))
    return found


def pages_distinct(labels):
    """Whether submenus of these labels each get a page of their own in a Gtk.PopoverMenu,
    which names a submenu's page by its label and its own first page `main`: no two alike,
    none `main`."""
    labels = list(labels)
    return len(set(labels)) == len(labels) and 'main' not in labels


def playlist_submenu(entries, named, action=None, taken=()):
    """The Add to Playlist items for `entries` ((id, title, children), as
    ItemActions.playlists() lists them), adding the song or video `named` ((kind, id)), or
    an album's or a playlist's songs, to the playlist chosen: the top level's playlists,
    then each folder as a submenu of its name holding its own playlists and then its
    folders, as the sidebar nests them. A Gtk.PopoverMenu names a submenu's page by its
    label, so the folders are submenus only when every submenu label of the menu would be
    distinct (pages_distinct()): the folders' and `taken`, the labels of the menu's other
    submenus (Add to Playlist's own, Move to Folder's). Otherwise (two Untitled Folders, a
    folder named `main` or like another submenu) each folder's playlists are a section
    headed by its name (folder_path()), a folder inside another after that one's own
    playlists (docs/decisions.md). A playlist is not offered its own songs, nor a folder
    holding only it. With `action` (a full action name that takes the playlist's id, "s": a
    selection's Add to Playlist), each item runs that instead; `named` is then only what is
    not offered (('playlist', id), or None)."""

    def item_for(entry_id, title):
        label = mnemonic_escaped(title or _('Untitled Playlist'))
        if action is None:
            return menu_item('item-add-to-playlist',
                             GLib.Variant('(sss)', (entry_id, *named)), label=label)
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(action, GLib.Variant('s', entry_id))
        return item

    def offered(entries):
        """entries without the playlist `named` and the folders left holding nothing."""
        kept = []
        for entry_id, title, children in entries:
            if children is not None:
                inside = offered(children)
                if inside:
                    kept.append((entry_id, title, inside))
            elif named is None or tuple(named) != ('playlist', entry_id):
                kept.append((entry_id, title, None))
        return kept

    def nest(entries):
        menu = Gio.Menu()
        for entry_id, title, children in entries:
            if children is None:
                menu.append_item(item_for(entry_id, title))
        for _entry_id, title, children in entries:
            if children is not None:
                menu.append_submenu(mnemonic_escaped(title or _('Untitled Folder')),
                                    nest(children))
        return menu

    def flat(entries, path, menu):
        section = Gio.Menu()
        for entry_id, title, children in entries:
            if children is None:
                section.append_item(item_for(entry_id, title))
        if section.get_n_items():
            # A section's header is plain text, not a mnemonic label: the name as it is.
            menu.append_section(folder_path(path) if path else None, section)
        for _entry_id, title, children in entries:
            if children is not None:
                flat(children, (*path, title), menu)
        return menu

    entries = offered(entries)
    nested = nest(entries)
    if pages_distinct([*taken, *submenu_labels(nested)]):
        return nested
    return flat(entries, (), Gio.Menu())


def folder_items(entries, named, path=(), menu=None):
    """The Move to Folder items for `entries` (move_targets()'s), moving the playlist or
    folder `named` ((kind, id)), in one list in the sidebar's order: each folder it can go
    into, one inside another named with the folders holding it (folder_path()). No folder
    is a submenu: each is a place to move to, not a list to look into, and in one list
    every folder is a step away (docs/decisions.md)."""
    menu = Gio.Menu() if menu is None else menu
    for folder_id, title, movable, children in entries:
        inside = (*path, title)
        if movable:
            menu.append_item(menu_item('item-move-to-folder',
                                       GLib.Variant('(sss)', (folder_id, *named)),
                                       label=mnemonic_escaped(folder_path(inside))))
        folder_items(children, named, inside, menu)
    return menu


def move_submenu(moves, named):
    """Move to Folder's submenu for the playlist or folder `named` ((kind, id)), from
    move_targets()'s `moves`: Top Level (when it can go there), the folders
    (folder_items()), then New Folder…, a folder holding it. Never empty."""
    top_level, entries = moves
    submenu = Gio.Menu()
    if top_level:
        top = Gio.Menu()
        top.append_item(menu_item('item-move-to-folder',
                                  GLib.Variant('(sss)', (ROOT_FOLDER, *named)),
                                  label=_('_Top Level')))
        submenu.append_section(None, top)
    listed = folder_items(entries, named)
    if listed.get_n_items():
        submenu.append_section(None, listed)
    created = Gio.Menu()
    created.append_item(menu_item('item-move-to-folder', GLib.Variant('(sss)', ('', *named)),
                                  label=action_labels()['item-new-folder']))
    submenu.append_section(None, created)
    return submenu


def new_items(folder_id):
    """New Playlist… and New Folder…, both in the folder folder_id (ROOT_FOLDER: the top
    level)."""
    target = GLib.Variant('(ss)', ('folder', folder_id))
    return [menu_item('item-new-playlist', target), menu_item('item-new-folder', target)]


def main_menu_section():
    """The main menu's first section: New Playlist… (win.new-playlist, which the menu shows
    with its key, Ctrl+N) and New Folder…, both at the top level."""
    section = Gio.Menu()
    section.append_item(Gio.MenuItem.new(action_labels()['item-new-playlist'],
                                         'win.new-playlist'))
    section.append_item(new_items(ROOT_FOLDER)[1])
    return section


def build_menu(obj, playlists=(), storefront=None, here=None, queued=False, container=None,
               moves=None, removable=None, queue_entry=None, reorder=True, held=False,
               queue_moves=None):
    """The menu for obj (an Item or a Track), or None when nothing applies; a category's is
    curator_menu(). It is the one menu of an item wherever it shows: a tile's or row's, a
    page's More Options, a sidebar row's (a folder's, All Playlists' too: New Playlist… and
    New Folder… in it). `playlists` are the entries the Add to
    Playlist submenu lists (ItemActions.playlists(): (id, title, children), a folder's
    children its own entries, a section); `here` is the Item of the page shown (Go to Album
    and Go to Artist are left out where they would go nowhere: related.shows); `queued`, obj
    is in the player's queue (no Play); `container`, the playlist Item the track obj is
    shown in (Remove from Playlist, when it is one of the user's); `moves`, where a playlist
    or folder can be moved (move_targets(): Move to Folder; None, not at all); `removable`,
    obj's removal_target (Remove from Library…, and no Add to Library); `queue_entry`,
    (index, id) of the queue's entry obj is when it may be taken out of Up Next (Remove from
    Up Next) and `queue_moves` where it can go there ({step: the index it moves to}, step
    'top', -1, 1, 'bottom' for Move to Top, Move Up, Move Down, Move to Bottom, and 'next'
    for Play Next, None when it plays next already: queue_play_next()), as
    item-move-in-queue moves it; `reorder` false leaves out a playlist's moves (the
    playlist's page shows a
    filter of its songs); `held`, the library holds obj, a catalog album or playlist
    (Library.holds(), as its page's In Library says: no Add to Library)."""
    if is_curator(obj):
        return curator_menu(obj, storefront)
    queue_moves = queue_moves or {}
    named = describe(obj)
    if named is None or (isinstance(obj, Item) and obj.kind not in MENU_KINDS):
        return None
    target = GLib.Variant('(ss)', named)
    sections = [Gio.Menu(), Gio.Menu(), Gio.Menu(), Gio.Menu(), Gio.Menu()]
    play, go, keep, share, manage = sections
    if is_folder(obj):
        for item in new_items(obj.id):
            play.append_item(item)
    if can_play(obj) and not queued:
        play.append_item(menu_item('item-play', target))
    if queue_target(obj) is not None:
        play_next = queue_play_next(queue_entry, queue_moves)
        if play_next == 'move':
            item = Gio.MenuItem.new(action_labels()['item-play-next'], None)
            item.set_action_and_target_value(
                'win.item-move-in-queue',
                GLib.Variant('(iis)', (int(queue_entry[0]), int(queue_moves['next']),
                                       str(queue_entry[1]))))
            play.append_item(item)
        elif play_next == 'queue':
            play.append_item(menu_item('item-play-next', target))
        play.append_item(menu_item('item-play-later', target))
    for item in station_items(obj):
        play.append_item(item)
    for item in queue_move_items(queue_entry, queue_moves):
        play.append_item(item)
    if queue_entry is not None:
        play.append_item(menu_item('item-remove-from-queue',
                                   GLib.Variant('(is)', (int(queue_entry[0]),
                                                         str(queue_entry[1])))))
    if related.has_album(obj) and not related.shows(here, obj, 'album'):
        go.append_item(menu_item('item-go-to-album', target))
    if related.has_artist(obj) and not related.shows(here, obj, 'artist'):
        go.append_item(menu_item('item-go-to-artist', target))
    if credits_target(obj) is not None:
        go.append_item(menu_item('item-view-credits', target))
    if rating_target(obj) is not None:
        for item in rating_items(target):
            keep.append_item(item)
    for item in favourite_items(obj):
        keep.append_item(item)
    if library_target(obj) is not None and removable is None and not held:
        keep.append_item(menu_item('item-add-to-library', target,
                                   pre_add_label() if pre_adds(obj) else None))
    labels = action_labels()
    moved = move_submenu(moves, named) if moves is not None else None
    if playlist_song(obj) or adds_songs(obj):
        # The playlists that take songs, folders as submenus (or as sections where a
        # submenu's page would not be its own: playlist_submenu()), then New Playlist…, one
        # holding this song (an album's or a playlist's songs).
        taken = [labels['item-add-to-playlist']]
        if moved is not None:
            taken += [labels['item-move-to-folder'], *submenu_labels(moved)]
        submenu = Gio.Menu()
        listed = playlist_submenu(playlists, named, taken=taken)
        if listed.get_n_items():
            submenu.append_section(None, listed)
        created = Gio.Menu()
        created.append_item(menu_item('item-new-playlist', target))
        submenu.append_section(None, created)
        keep.append_submenu(labels['item-add-to-playlist'], submenu)
    if moved is not None:
        keep.append_submenu(labels['item-move-to-folder'], moved)
    for item in move_items(container, obj) if reorder else ():
        keep.append_item(item)
    removed = entry_target(container, obj)
    if removed is not None:
        keep.append_item(menu_item('item-remove-from-playlist', removed))
    if web_url(obj, storefront) or needs_catalog_artist(obj):
        share.append_item(menu_item('item-open-in-browser', target))
        # Copy Link: an address anyone can open, or a library album's or artist's catalog
        # page, which the engine can say when the link is asked for.
        if share_url(obj, storefront) or needs_catalog_url(obj) or needs_catalog_artist(obj):
            share.append_item(menu_item('item-copy-link', target))
    for item in manage_items(obj):
        manage.append_item(item)
    for item in removal_items(obj, removable):
        manage.append_item(item)
    menu = Gio.Menu()
    for section in sections:
        if section.get_n_items():
            menu.append_section(None, section)
    return menu if menu.get_n_items() else None


def curator_menu(obj, storefront=None):
    """A curator's menu: Open in Browser and Copy Link (its music.apple.com page, the
    curator's own `url`: web_url), or None when it has no page."""
    named = describe(obj)
    if named is None or not web_url(obj, storefront):
        return None
    target = GLib.Variant('(ss)', named)
    share = Gio.Menu()
    share.append_item(menu_item('item-open-in-browser', target))
    if share_url(obj, storefront):
        share.append_item(menu_item('item-copy-link', target))
    menu = Gio.Menu()
    menu.append_section(None, share)
    return menu
