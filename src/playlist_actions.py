# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The item actions that make, edit, move and delete playlists and folders and take items
out of the library (PlaylistActions, a part of actions.ItemActions): each shown at once, then
followed until Apple's listing agrees. ItemActions adds their win.item-* actions with the
rest (actions.py), and they are called on it:

    actions.drop_new_playlist(refs)        # songs dropped on All Playlists: a new playlist
    actions.move_to_folder(obj, folder_id) # a playlist (or folder) into a folder, at once
    actions.new_folder(parent_id, name)    # a folder made in parent_id ('root': top level)
    actions.ask_remove_from_library(tracks)     # one confirmation, then all of them
    actions.new_playlist_of(tracks)             # New Playlist… holding them
    actions.ask_new_playlist(folder_id=ROOT_FOLDER)   # New Playlist's dialog, made empty
    actions.edit_details(playlist, before, after)     # Edit Details… confirmed: what changed
    actions.duplicate(playlist)                 # a copy, "<name> Copy", beside it, shown
    actions.ask_add_songs(playlist)             # Add Songs…: songs picked, added in one write

Remove from Library takes the item out of the library's models at once (Library.hide), then
asks Apple; a refusal puts it back and is reported. Apple takes a song out of every playlist
too, and an album with its songs; its library listings drop them only seconds later, so the
library keeps leaving them out until a load no longer meets them, and the quick pass of a
sync that follows starts once Apple's read of the item answers 404 (wait_removed).

After a playlist or folder was made, renamed or deleted, the window leaves the pages of what
is gone (Window.leave), the sidebar shows a new name at once, and the library follows Apple's
listing once it shows the change (wait_listed: a new playlist takes seconds to be listed, a
folder made in or moved into a folder about a minute), through the playlists pass of a sync
(sync.py).
"""

import asyncio
import logging
from collections import namedtuple
from gettext import gettext as _
from gettext import ngettext

from gi.repository import GLib

from .action_messages import (added_message, duplicate_name, library_removed_message,
                              removal_words, removals_words)
from .backend import api
from .backend.errors import EngineError
from .item_menu import folder_path
from .item_targets import (SOURCE_KINDS, adds_to, container_tracks, duplicates,
                           is_manageable, move_targets, new_playlist_refs,
                           new_playlist_tracks, playlist_track, removal_target)
from .library import PUBLIC, ROOT_FOLDER, Item, ItemRefs, Track, TreeChange

log = logging.getLogger(__name__)

# After a playlist write, how long to wait before each look at Apple's listing, in seconds,
# until it shows the change: a new playlist was listed 4 to 6.5 s after it was made, a
# rename or a deletion within a second (2026-10-03); a playlist moved into a folder or out
# to the top level, and a folder out to the top level, 3 to 6 s after (2026-10-21). Then the
# library follows regardless.
SETTLE_DELAYS = (0.5, 1, 1, 1, 2, 2, 3, 3)
# The same for a folder made in a folder or moved into one: Apple lists it there only about
# a minute later (59 and 61 s, 2026-10-21), having stopped listing a moved one where it was
# within 6 s. So the sync that follows waits for it, up to a minute and a half.
FOLDER_SETTLE_DELAYS = SETTLE_DELAYS + (5,) * 15

# After a removal from the library, how long to wait before each look at Apple's library
# read of the item, in seconds, until it answers 404: a song's did within 2 s, an album's
# within 7 (2026-10-20). Then the library's listings, which dropped them within 2 to 7 s,
# are given LISTING_LAG more before the sync reads them.
REMOVAL_DELAYS = (1, 1, 1, 2, 2, 3, 3, 4)
LISTING_LAG = 2


# A playlist's details as the playlist dialog (dialogs/playlist.py) shows them: its name,
# its description, the id of the folder it is in (ROOT_FOLDER: the top level) and whether
# it is public.
Details = namedtuple('Details', 'name description folder public',
                     defaults=('', '', ROOT_FOLDER, False))


def playlist_changes(before, after):
    """What an edit changed, from the Details the dialog opened with to those confirmed:
    {name, description, public, folder}, each only when it differs (the name compared
    stripped). Empty when nothing did."""
    changed = {}
    name = (after.name or '').strip()
    if name and name != (before.name or '').strip():
        changed['name'] = name
    if (after.description or '') != (before.description or ''):
        changed['description'] = after.description or ''
    if bool(after.public) != bool(before.public):
        changed['public'] = bool(after.public)
    if (after.folder or ROOT_FOLDER) != (before.folder or ROOT_FOLDER):
        changed['folder'] = after.folder or ROOT_FOLDER
    return changed


def folder_choices(tree, obj=None):
    """The folders a playlist can be put in, for the playlist dialog's Folder row:
    [(folder id, label)], Top Level (ROOT_FOLDER) first, then the folders in the sidebar's
    order, one inside another named with the folders holding it (folder_path(): "Evenings ›
    Late Night"). For a new playlist (obj None) every folder; for the playlist obj, the one
    it is in and those Move to Folder offers (move_targets()), or None when it cannot be
    moved at all (no row then)."""
    if obj is not None and move_targets(tree, obj) is None:
        return None
    parent = None
    if obj is not None:
        node = tree.node(obj.kind, obj.id)
        parent = node.parent.id if node.parent is not None else ROOT_FOLDER

    def takes(folder_id):
        return (obj is None or folder_id == parent
                or (tree.can_move(obj.kind, obj.id, folder_id)
                    and api.can_move_to_folder(obj.kind, folder_id)))

    choices = [(ROOT_FOLDER, _('Top Level'))] if takes(ROOT_FOLDER) else []

    def walk(node, path):
        for child in node.children:
            if child.kind != 'folder' or (obj is not None and child.item is obj):
                continue
            inside = (*path, child.item.title)
            if takes(child.id):
                choices.append((child.id, folder_path(inside)))
            walk(child, inside)

    if tree is not None:
        walk(tree.root, ())
    return choices


def item_changes(item, written):
    """The changes to merge into a playlist's Item after Engine.edit_playlist wrote
    `written` ({name, description, public}, any of them): its title, summary and the
    attributes' isPublic (library.PUBLIC), as a sync would read them."""
    merged = {}
    if 'name' in written:
        merged['title'] = written['name']
    if 'description' in written:
        merged['summary'] = written['description']
    if 'public' in written:
        attributes = dict(item.raw.get('attributes') or {})
        if written['public']:
            attributes[PUBLIC] = True
        else:
            attributes.pop(PUBLIC, None)
        merged['attributes'] = attributes
    return merged


def settle_delays(kind, folder_id):
    """How long to look for a playlist or folder (`kind`) made in or moved into the folder
    folder_id (ROOT_FOLDER: the top level) in Apple's listing: FOLDER_SETTLE_DELAYS for a
    folder into a folder, which Apple lists there only about a minute later, else
    SETTLE_DELAYS."""
    if kind == 'folder' and folder_id not in (None, '', ROOT_FOLDER):
        return FOLDER_SETTLE_DELAYS
    return SETTLE_DELAYS


class PlaylistActions:
    """Part of ItemActions (actions.py), whose state and helpers (_run(), _unpack(),
    tracks_of()) it uses: making, editing, moving and deleting playlists and folders, and
    removing from the library. See the module."""

    def can_move_refs(self, refs, folder_id):
        """Whether the playlists and folders a drag carries (an ItemRefs of nothing else)
        may all go into the folder folder_id (ROOT_FOLDER: the top level): the tree takes
        each move (PlaylistTree.can_move: not into itself, a folder inside it, or where it
        is already) and Apple is known to take it (api.can_move_to_folder)."""
        if not isinstance(refs, ItemRefs) or not refs.only('playlist', 'folder'):
            return False
        tree = self.library.playlist_tree()
        for ref in refs:
            node = tree.node(ref.kind, ref.id)
            if (node is None or node.item.favourites or not api.can_move_to_folder(
                    ref.kind, folder_id) or not tree.can_move(ref.kind, ref.id, folder_id)):
                return False
        return True

    def new_playlist_of(self, objects):
        """New Playlist… for a selection: a playlist made in the playlist dialog holding the
        songs and music videos `objects` in their order (create_playlist(objects=…)), shown
        once made. The dialog."""
        objects = list(objects)
        return self.ask_new_playlist(objects=objects, show=True)

    def removals(self, objects):
        """What a selection's Remove from Library takes: (obj, removal_target) for each of
        `objects` the library holds, in order, each library item once."""
        found, seen = [], set()
        for obj in objects:
            target = self.removal_target(obj)
            if target is not None and target not in seen:
                seen.add(target)
                found.append((obj, target))
        return found

    def ask_remove_from_library(self, objects):
        """A selection's Remove from Library…: of `objects`, those the library holds
        (removals()) taken out once one dialog confirms (removal_words() for one,
        removals_words() for several). The dialog, or None when none is in the library."""
        found = self.removals(objects)
        if not found:
            self.app.toast(_('These are not in your library'))
            return None
        if len(found) == 1:
            obj, target = found[0]
            heading, body = removal_words(target[0], obj.title or '')
            return self.ask_confirm(heading, body, _('_Remove'),
                                    lambda: self.remove_from_library(obj, target))
        heading, body = removals_words(len(found))
        return self.ask_confirm(heading, body, _('_Remove'),
                                lambda: self.remove_all_from_library(found))

    def remove_all_from_library(self, found):
        """Take several items out of the library (`found`, removals()' pairs): the library
        leaves them all out at once (Library.hide), Apple is asked for each in turn, and one
        toast counts those it took; a failure brings back the rest (Library.unhide) and is
        reported. The pages of what went are left, and once Apple's read of the last no
        longer has it, one quick sync reads the songs and the playlists that held any of
        them (_follow_removal's, once for all). The task, whose result says whether all
        went, or None (the demo library). The playlists holding them are looked for once,
        for them all (a look goes through every playlist's entries, too long on the main
        loop for one a song), before the library leaves them out of its playlists; after a
        failure partway the sync reads the playlists that held any of those asked for."""
        if self.app.refuse_in_demo():
            return None
        parts = [(target, *self._removal_parts(obj, *target)) for obj, target in found]
        ids = set().union(*(part[2] for part in parts))
        holding = self.library.playlists_holding(ids) if ids else ()

        async def run():
            self.app.spawn(self.library.hide(set().union(*(part[1] for part in parts))))
            done = 0
            try:
                await self.app.player.ensure_engine()
                for (kind, library_id), *_refs in parts:
                    await self.engine.remove_from_library(kind, library_id)
                    done += 1
            except EngineError as error:
                self.app.spawn(self.library.unhide(set().union(
                    *(part[1] for part in parts[done:]))))
                self.app.report(error)
            if not done:
                return False
            removed = parts[:done]
            self.app.toast(library_removed_message(done))
            gone = set().union(*(part[3] for part in removed))
            if gone:
                self.window.leave(gone)
            kind, library_id = removed[-1][0]
            if await self.wait_removed(kind, library_id):
                await asyncio.sleep(LISTING_LAG)
            task = self.app.start_sync(quick=True,
                                       videos=any(part[0][0] == 'video' for part in removed),
                                       tracks_of=tuple(sorted(holding)))
            if task is not None:
                await asyncio.wait([task])
            return done == len(parts)

        return self.app.spawn(run())

    def drop_new_playlist(self, refs):
        """Songs, music videos or albums (a library.ItemRefs of nothing else) dropped on
        All Playlists: the playlist dialog, the name filled in with the first one's title,
        makes a playlist holding them all, an album's songs (create_playlist()), whose page
        is then shown. False when the drop is refused (new_playlist_refs())."""
        if not new_playlist_refs(refs):
            return False
        name = refs.refs[0].title
        tracks = new_playlist_tracks(refs)
        if tracks:
            title, objects = (name if len(tracks) == 1 else ''), None
        else:
            title, objects = '', self._ref_objects(refs)
        self.ask_new_playlist(name, tracks=tracks or (), title=title, show=True,
                              objects=objects)
        return True

    def drop_into_folder(self, folder_id, refs):
        """An ItemRefs of playlists or folders dropped on a sidebar folder (ROOT_FOLDER:
        All Playlists, the top level): each moved there (move_to_folder()). False when the
        drop is refused (can_move_refs())."""
        if not self.can_move_refs(refs, folder_id):
            return False
        tree = self.library.playlist_tree()
        for ref in refs:
            self.move_to_folder(tree.node(ref.kind, ref.id).item, folder_id)
        return True

    # -- managing playlists and folders ------------------------------------------------------

    def ask_name(self, heading, confirm, name='', description=None, done=None):
        """The name dialog over the window (dialogs/playlist.py's NameDialog), a folder's:
        `name` filled in; done(name, description) when it is confirmed. The dialog."""
        from .dialogs.playlist import NameDialog

        dialog = NameDialog(heading, confirm, name, description, done)
        dialog.present(self.shown_window())
        return dialog

    def ask_playlist(self, heading, confirm, details, folders, done):
        """The playlist dialog over the window (dialogs/playlist.py's PlaylistDialog), opened
        with `details` (a Details), `folders` the Folder row's choices (folder_choices();
        None: no row); done(details) when it is confirmed. The dialog."""
        from .dialogs.playlist import PlaylistDialog

        dialog = PlaylistDialog(heading, confirm, details, folders, done)
        dialog.present(self.shown_window())
        return dialog

    def ask_new_playlist(self, name='', folder_id=ROOT_FOLDER, **create):
        """New Playlist's dialog: `name` filled in, in the folder folder_id (ROOT_FOLDER: the
        top level; any folder can be chosen in it). Once confirmed the playlist is made as
        the dialog says, with create_playlist()'s other arguments `create` (tracks, title,
        show, objects). The dialog."""
        folders = folder_choices(self.library.playlist_tree())
        if folder_id not in {choice for choice, _label in folders}:
            folder_id = ROOT_FOLDER

        def done(details):
            return self.create_playlist(details.name, details.description, folder_id=details.folder,
                                 public=details.public, **create)

        return self.ask_playlist(_('New Playlist'), _('_Create'),
                                 Details(name or '', '', folder_id, False), folders, done)

    def ask_confirm(self, heading, body, confirm, done):
        """The confirmation before something is deleted, over the window
        (dialogs/playlist.py's confirm()): done() when it is confirmed. The dialog."""
        from .dialogs.playlist import confirm as confirm_dialog

        return confirm_dialog(self.shown_window(), heading, body, confirm, done)

    def _on_new_playlist(self, _action, parameter):
        """A new playlist, made in the playlist dialog: in the folder the target names, or
        holding the song or video it names, or the songs of the album or playlist it names
        (the name filled in with its title)."""
        obj, kind, item_id = self._unpack(parameter)
        if kind in SOURCE_KINDS:
            source = self._source(obj, kind, item_id)
            return self.ask_new_playlist(str(source.raw.get('title') or ''), objects=[source])
        if kind == 'folder':
            return self.ask_new_playlist(folder_id=item_id or ROOT_FOLDER)
        track = playlist_track(obj) if obj is not None else None
        return self.ask_new_playlist(tracks=(track or (kind, item_id),),
                                     title=obj.title if obj is not None else '')

    def create_playlist(self, name, description='', tracks=(), folder_id=None, title='',
                        show=False, objects=None, public=False, empty=False):
        """Make the playlist (Engine.create_playlist), in the folder folder_id (None or
        ROOT_FOLDER: the top level), public (shown on the profile and in search) when
        `public`, confirm with a toast and follow Apple's listing; one made empty (New
        Playlist), or with `show`, is then shown. `objects`: albums, playlists or tracks
        whose songs it holds in place of `tracks` (tracks_of()), counted in the toast; with
        none to add no playlist is made, unless `empty` (Duplicate's: an empty playlist's
        copy). The task, or None."""
        if self.app.refuse_in_demo():
            return None
        if title:
            message = _('Added “{title}” to the new playlist “{playlist}”').format(
                title=title, playlist=name)
        else:
            message = _('Created “{playlist}”').format(playlist=name)

        async def run():
            nonlocal tracks, message
            try:
                await self.app.player.ensure_engine()
                if objects is not None:
                    tracks = await self.tracks_of(objects)
                    if tracks:
                        message = added_message(len(tracks), name, new=True)
                    elif not empty:
                        self.app.toast(_('There are no songs to add'))
                        return
                new_id = await self.engine.create_playlist(name, description, tracks,
                                                           folder_id, public=public)
            except EngineError as error:
                self.app.report(error)
                return
            self.app.toast(message)
            await self._follow_listing(folder_id or ROOT_FOLDER, new_id, name)
            if (show or not tracks) and self.library.by_id('playlist', new_id) is not None:
                self.window.select_page(f'playlist:{new_id}')  # sidebar.playlist_key

        return self.app.spawn(run())

    def _on_duplicate(self, _action, parameter):
        return self.duplicate(self._unpack(parameter)[0])

    def duplicate(self, playlist):
        """Duplicate: a new playlist of the user's named duplicate_name(), with the
        playlist's description and its songs in its own order (whatever order its page
        shows: a sort is the view's), beside it (in its folder), its page shown once Apple
        lists it (create_playlist()). An empty playlist's copy is made empty, also one whose
        songs had to be read first (a playlist the library lists without its tracks). The
        task, or None."""
        if not duplicates(playlist):
            self.app.toast(_('This cannot be duplicated'))
            return None
        name = duplicate_name(playlist.title or '')
        folder_id = self._parent_of(playlist)
        description = playlist.summary or ''
        if playlist.groups and not container_tracks(playlist):
            return self.create_playlist(name, description, (), folder_id, show=True)
        return self.create_playlist(name, description, folder_id=folder_id, show=True,
                                    objects=[playlist], empty=True)

    def _on_add_songs(self, _action, parameter):
        return self.ask_add_songs(self._unpack(parameter)[0])

    def ask_add_songs(self, playlist):
        """Add Songs…: the dialog (dialogs/add_songs.py) that picks songs from the library
        and Apple Music's catalogue for a playlist of the user's, added in one write once
        chosen (add_items_to_playlist(): one POST of up to api.PLAYLIST_BATCH). The dialog, or
        None."""
        if not adds_to(playlist):
            self.app.toast(_('Songs cannot be added to this playlist'))
            return None
        from .dialogs.add_songs import AddSongsDialog

        playlist_id = playlist.id
        dialog = AddSongsDialog(self.app, self.library, playlist.title or '', lambda objects:
                                self.add_items_to_playlist(playlist_id, objects))
        dialog.present(self.shown_window())
        return dialog

    def _on_rename(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        if not is_manageable(obj):
            self.app.toast(_('This cannot be renamed'))
            return None
        if obj.kind == 'folder':
            return self.ask_name(_('Rename Folder'), _('_Rename'), obj.title, None,
                                 lambda name, _description: self.rename(obj, name))
        return self.ask_edit_details(obj)

    def ask_edit_details(self, playlist):
        """Edit Details…: the playlist dialog filled in with a playlist's name, description,
        folder and whether it is public; what is changed in it is written once confirmed
        (edit_details()). The dialog."""
        before = Details(playlist.title or '', playlist.summary or '',
                         self._parent_of(playlist), playlist.public)
        folders = folder_choices(self.library.playlist_tree(), playlist)
        return self.ask_playlist(_('Edit Details'), _('_Save'), before, folders,
                                 lambda after: self.edit_details(playlist, before, after))

    def edit_details(self, playlist, before, after):
        """What Edit Details… changed (playlist_changes(), from the Details
        `before` to `after`) written: the name, description and whether it is public in one
        write (Engine.edit_playlist), which the Item and the sidebar show at once, then a
        new folder as Move to Folder moves it (move_to_folder(): at once, with its toast and
        Undo); the library follows Apple's listing. The task, or None when nothing changed
        (or with the demo library)."""
        changed = playlist_changes(before, after)
        if not changed or self.app.refuse_in_demo():
            return None
        written = {key: changed[key] for key in ('name', 'description', 'public')
                   if key in changed}
        folder = changed.get('folder')
        parent = self._parent_of(playlist)

        async def run():
            if written:
                try:
                    await self.app.player.ensure_engine()
                    await self.engine.edit_playlist(playlist.id, **written)
                except EngineError as error:
                    self.app.report(error)
                    return False
                playlist.merge(item_changes(playlist, written))
                self.library.place_playlists()  # the sidebar retitles and places it now
            if folder is not None:
                task = self.move_to_folder(playlist, folder)
                return bool(task is not None and await task)
            await self._follow_listing(parent, playlist.id, playlist.title)
            return True

        return self.app.spawn(run())

    def rename(self, obj, name, description=None):
        """Give a playlist of the user's its name (and its description, unless None), or a
        folder its name: the Item and the sidebar follow at once, the library once Apple
        lists it. The task, or None."""
        if obj.kind == 'folder':
            method, args = self.engine.rename_folder, (obj.id, name)
        else:
            method, args = self.engine.edit_playlist, (obj.id, name, description)
        parent = self._parent_of(obj)

        async def after():
            changes = {'title': name}
            if description is not None:
                changes['summary'] = description
            obj.merge(changes)
            self.library.place_playlists()  # the sidebar retitles and places it now
            await self._follow_listing(parent, obj.id, name)

        return self._run(method, args, after=after)

    def _on_delete(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        if not is_manageable(obj):
            self.app.toast(_('This cannot be deleted'))
            return None
        name = obj.title
        if obj.kind == 'folder':
            count = sum(1 for kind, _id in self._inside(obj) if kind == 'playlist')
            heading = _('Delete Folder?')
            if count:
                body = ngettext(
                    '“{name}” and the playlist in it will be deleted from your library on all '
                    'your devices. This cannot be undone.',
                    '“{name}” and the {count} playlists in it will be deleted from your '
                    'library on all your devices. This cannot be undone.',
                    count).format(name=name, count=f'{count:n}')
            else:
                body = _('“{name}” will be deleted from your library on all your devices. '
                         'This cannot be undone.').format(name=name)
        else:
            heading = _('Delete Playlist?')
            body = _('“{name}” will be deleted from your library on all your devices. This '
                     'cannot be undone.').format(name=name)
        return self.ask_confirm(heading, body, _('_Delete'), lambda: self.delete(obj))

    def delete(self, obj):
        """Delete a playlist of the user's, or a folder with what is in it: the window leaves
        their pages, and the library follows once Apple's listing has them gone. The task,
        or None."""
        if obj.kind == 'folder':
            method = self.engine.delete_folder
        else:
            method = self.engine.delete_playlist
        parent = self._parent_of(obj)
        gone = {(obj.kind, obj.id), *self._inside(obj)}

        async def after():
            self.window.leave(gone, parent)
            await self._follow_listing(parent, obj.id, None)

        return self._run(method, (obj.id,), _('Deleted “{name}”').format(name=obj.title),
                         after=after, playlist=obj.id if obj.kind == 'playlist' else None)

    def _on_move_to_folder(self, _action, parameter):
        folder_id, kind, item_id = parameter.unpack()
        obj = self._resolve(kind, item_id)
        if not folder_id:  # Move to Folder's New Folder…
            return self._ask_new_folder_for(obj)
        return self.move_to_folder(obj, folder_id)

    def move_to_folder(self, obj, folder_id):
        """Move a playlist (or a folder) into the folder folder_id (ROOT_FOLDER: the top
        level). The library shows it there at once (Library.hold(): the sidebar and the
        folders' pages follow); Apple's refusal puts it back (Library.release()) and is
        reported; once Apple takes it, a toast says where it went, with Undo (a move back),
        and the library follows Apple's listing. The task, or None when it cannot be moved
        there (toasted) or with the demo library."""
        if self.app.refuse_in_demo():
            return None
        tree = self.library.playlist_tree()
        if (not isinstance(obj, Item) or move_targets(tree, obj) is None
                or not tree.can_move(obj.kind, obj.id, folder_id)
                or not api.can_move_to_folder(obj.kind, folder_id)):
            self.app.toast(_('This cannot be moved there'))
            return None
        previous = self._parent_of(obj)
        folder = self.library.by_id('folder', folder_id)
        if folder_id == ROOT_FOLDER or folder is None:
            message = _('Moved “{name}” to the top level').format(name=obj.title)
        else:
            message = _('Moved “{name}” to “{folder}”').format(name=obj.title,
                                                               folder=folder.title)
        change = TreeChange.move(obj.kind, obj.id, folder_id)
        self.library.hold(change)

        async def run():
            try:
                await self.app.player.ensure_engine()
                await self.engine.move_to_folder(obj.kind, obj.id, folder_id)
            except EngineError as error:
                self.library.release(change)
                self.app.report(error)
                return False
            if api.can_move_to_folder(obj.kind, previous):
                self.app.toast(message, _('Undo'), 'win.item-move-to-folder',
                               GLib.Variant('(sss)', (previous, obj.kind, obj.id)))
            else:
                self.app.toast(message)
            await self._follow_listing(folder_id, obj.id, obj.title,
                                       settle_delays(obj.kind, folder_id))
            return True

        return self.app.spawn(run())

    def _on_new_folder(self, _action, parameter):
        """A new folder, named in a dialog, in the folder the target names ('folder', its
        id; 'root': the top level)."""
        _obj, kind, item_id = self._unpack(parameter)
        parent = item_id if kind == 'folder' and item_id else ROOT_FOLDER
        return self.ask_name(_('New Folder'), _('_Create'), '', None,
                             lambda name, _description: self.new_folder(parent, name))

    def _ask_new_folder_for(self, obj):
        """Move to Folder's New Folder…: a folder named in a dialog, made in the folder
        that holds obj, and obj moved into it."""
        if not isinstance(obj, Item) or move_targets(self.library.playlist_tree(), obj) is None:
            self.app.toast(_('This cannot be moved there'))
            return None
        parent = self._parent_of(obj)
        return self.ask_name(_('New Folder'), _('_Create'), '', None,
                             lambda name, _description: self.new_folder(parent, name, obj))

    def new_folder(self, parent_id, name, holding=None):
        """Make a folder called `name` in the folder parent_id (ROOT_FOLDER: the top
        level), and, with `holding` (a playlist or folder Item), move that into it. The
        folder is shown as soon as Apple answers with its id (Library.hold()) and its page
        selected; the library then follows Apple's listing. A move that fails keeps the
        folder (the failure is reported). The task, or None with the demo library."""
        if self.app.refuse_in_demo():
            return None

        async def run():
            try:
                await self.app.player.ensure_engine()
                new_id = await self.engine.create_folder(name, parent_id)
            except EngineError as error:
                self.app.report(error)
                return False
            self.library.hold(TreeChange.create(new_id, name, parent_id))
            self.window.select_page(f'folder:{new_id}')  # sidebar.folder_key
            self.app.toast(_('Created “{folder}”').format(folder=name))
            if holding is not None:
                task = self.move_to_folder(holding, new_id)
                if task is not None:
                    await asyncio.wait([task])
            await self._follow_listing(parent_id, new_id, name,
                                       settle_delays('folder', parent_id))
            return True

        return self.app.spawn(run())

    def _tree_node(self, obj):
        """obj's node in the library's PlaylistTree, or None."""
        for node in self.library.playlist_tree().flat:
            if node.kind == obj.kind and node.id == obj.id:
                return node
        return None

    def _parent_of(self, obj):
        """The id of the folder holding a playlist or folder (ROOT_FOLDER: the top level)."""
        node = self._tree_node(obj)
        if node is None or node.parent is None or node.parent.parent is None:
            return ROOT_FOLDER
        return node.parent.id

    def _inside(self, obj):
        """(kind, id) of everything in a folder, however deep; nothing for a playlist."""
        node = self._tree_node(obj) if obj.kind == 'folder' else None
        found = []
        stack = list(node.children) if node is not None else []
        while stack:
            child = stack.pop()
            found.append((child.kind, child.id))
            stack.extend(child.children)
        return found

    async def _follow_listing(self, folder_id, item_id, name, delays=None):
        """After a playlist write: wait until Apple lists it (wait_listed), then bring the
        library up to date with the playlists pass of a sync, and wait for that."""
        await self.wait_listed(folder_id, item_id, name, delays)
        task = self.app.start_sync(playlists=True)
        if task is not None:
            await asyncio.wait([task])

    async def wait_listed(self, folder_id, item_id, name, delays=None):
        """Wait until Apple lists the playlist or folder item_id in the folder folder_id
        under `name` (None: not at all), looking again after each of `delays` (None:
        SETTLE_DELAYS; settle_delays() picks them). True once it does; False when it never
        did, or the engine could not say. Right after a deletion Apple can answer for the
        folder with
        nothing at all (a 404, or an empty list) while it still holds other things: for
        `name` None, an empty answer counts only when the folder held nothing else."""
        node = self.library.playlist_tree().folder(folder_id)
        others = node is not None and any(child.id != item_id for child in node.children)
        for delay in SETTLE_DELAYS if delays is None else delays:
            await asyncio.sleep(delay)
            try:
                children = await self.engine.folder_children(folder_id)
            except EngineError as error:
                log.debug('playlist listing not read: %s', error)
                return False
            found = next((child for child in children if child['id'] == item_id), None)
            if name is None and found is None and (children or not others):
                return True
            if name is not None and found is not None and found['name'] == name:
                return True
        log.info('Apple does not list the change yet: the library follows its listing')
        return False

    # -- removing from the library -----------------------------------------------------------

    def removal_target(self, obj):
        """obj's removal_target() in the app's library, or None."""
        return removal_target(obj, self.library)

    def _on_remove_from_library(self, _action, parameter):
        obj = self._unpack(parameter)[0]
        target = self.removal_target(obj) if obj is not None else None
        if target is None:
            self.app.toast(_('This is not in your library'))
            return None
        heading, body = removal_words(target[0], obj.title or '')
        return self.ask_confirm(heading, body, _('_Remove'),
                                lambda: self.remove_from_library(obj, target))

    def remove_from_library(self, obj, target):
        """Take obj out of the library (`target`, its removal_target: (kind, library id)).
        The library leaves it out at once (Library.hide: its stores, its albums and
        playlists, the pages), before Apple has answered; a failure brings it back
        (Library.unhide) and is reported. Once Apple has taken it, the window leaves its
        pages, and the library follows Apple's listings when they no longer hold it
        (_follow_removal). The task, or None."""
        if self.app.refuse_in_demo():
            return None
        kind, library_id = target
        hidden, holding, gone = self._removal_refs(obj, kind, library_id)
        # A catalog playlist's removal takes out the library's (removal_target): its folder.
        parent = (self._parent_of(self.library.by_id('playlist', library_id) or obj)
                  if kind == 'playlist' else None)
        title = obj.title or ''
        message = (_('Removed “{title}” from your library').format(title=title) if title
                   else _('Removed from your library'))

        async def run():
            self.app.spawn(self.library.hide(hidden))
            try:
                await self.app.player.ensure_engine()
                await self.engine.remove_from_library(kind, library_id)
            except EngineError as error:
                self.app.spawn(self.library.unhide(hidden))
                self.app.report(error)
                return False
            self.app.toast(message)
            if gone:
                self.window.leave(gone, parent)
            await self._follow_removal(kind, library_id, parent, holding)
            return True

        return self.app.spawn(run())

    def _removal_refs(self, obj, kind, library_id):
        """What a removal of obj takes with it: (the refs Library.hide leaves out, the ids
        of the playlists holding it, whose tracks the sync reads again, the (kind, id) of the
        pages to leave)."""
        hidden, ids, gone = self._removal_parts(obj, kind, library_id)
        if kind == 'playlist':
            return hidden, (), gone
        return hidden, self.library.playlists_holding(ids), gone

    def _removal_parts(self, obj, kind, library_id):
        """_removal_refs() without its look through the playlists: (the refs Library.hide
        leaves out, the ids and catalog ids of the songs that go, which the playlists
        holding it hold, the (kind, id) of the pages to leave)."""
        if kind == 'playlist':
            return {('playlist', library_id)}, set(), {('playlist', library_id)}
        if kind == 'album':
            album = self.library.by_id('album', library_id)
            ids = set()
            for group in (album.raw.get('groups') or []) if album is not None else ():
                for entry in group.get('entries') or []:
                    ids.update(value for value in (entry.get('id'), entry.get('catalogId'))
                               if value)
            return {('album', library_id)}, ids, {('album', library_id)}
        catalog_id = getattr(obj, 'catalog_id', None)
        hidden = {(kind, library_id)} | ({(kind, catalog_id)} if catalog_id else set())
        gone = {('video', library_id)} if kind == 'video' else set()
        if isinstance(obj, Track) and obj.play.get('kind') == 'album':
            album = self.library.by_id('album', obj.play.get('id'))
            if album is not None and sum(group.entries.get_n_items()
                                         for group in album.groups) <= 1:
                gone.add(('album', album.id))  # its one song: the album goes too
        return hidden, {library_id, catalog_id} - {None}, gone

    async def _follow_removal(self, kind, library_id, parent, holding):
        """After a removal Apple took: a playlist's, as a deleted playlist's
        (_follow_listing); anything else's once Apple's library read no longer has it
        (wait_removed), with the quick pass of a sync, which reads the songs, the music
        videos and the tracks of the playlists that held it (`holding`). Until a load no
        longer meets it, the library leaves it out (Library.hide)."""
        if kind == 'playlist':
            await self._follow_listing(parent, library_id, None)
            return
        if await self.wait_removed(kind, library_id):
            await asyncio.sleep(LISTING_LAG)
        task = self.app.start_sync(quick=True, videos=kind == 'video',
                                   tracks_of=tuple(holding))
        if task is not None:
            await asyncio.wait([task])

    async def wait_removed(self, kind, library_id):
        """Wait until Apple's library read answers that library_id is gone (Engine.
        in_library), looking after each of REMOVAL_DELAYS. True once it does; False when it
        never did, or the engine could not say."""
        for delay in REMOVAL_DELAYS:
            await asyncio.sleep(delay)
            try:
                if not await self.engine.in_library(kind, library_id):
                    return True
            except EngineError as error:
                log.debug('library read after a removal: %s', error)
                return False
        log.info('Apple still lists the item removed: the library follows its listing')
        return False
