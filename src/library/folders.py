# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The playlists and their folders as Apple's sidebar nests and orders them (PlaylistTree),
and the folder changes shown ahead of Apple's listing (TreeChange, apply_changes())."""

import time

from gi.repository import Gio

from .diff import apply_diff
from .objects import SORT_KEYS, Item
from .records import _dicts, _text
from .text_keys import title_key


# The id of the folders entry that lists the top level: the playlists and folders in no folder.
ROOT_FOLDER = 'root'

# How long a change to the playlist folders that Apple has taken is shown ahead of its listing
# (Library.hold()), in seconds: a sync that runs before Apple lists it keeps showing it, and
# after this the listing wins. A new playlist took 4 to 6.5 s to be listed (2026-10-03).
PENDING_HOLD = 120


class TreeNode:
    """A folder or a playlist in the PlaylistTree.

    `item` is its Item: the playlist's own, from the playlists section, or the folder's (kind
    'folder'). `depth` is 0 at the top level (the root's is -1), `parent` the TreeNode of the
    folder holding it (None for the root), and a folder's `children` are its nodes in the
    sidebar's order (PlaylistTree), as `store` holds their Items for a grid.
    """

    __slots__ = ('item', 'depth', 'parent', 'children', 'store')

    def __init__(self, item, depth, parent):
        self.item = item
        self.depth = depth
        self.parent = parent
        self.children = []
        self.store = None

    @property
    def kind(self):
        return self.item.kind

    @property
    def id(self):
        return self.item.id

    def ancestors(self):
        """The ids of the folders holding this node, outermost first, the root left out."""
        ids = []
        node = self.parent
        while node is not None and node.parent is not None:
            ids.append(node.item.id)
            node = node.parent
        ids.reverse()
        return ids

    def __repr__(self):
        return f'TreeNode({self.kind}, {self.id!r}, depth={self.depth})'


class PlaylistTree:
    """The playlists and their folders, as Apple's sidebar nests and orders them.

    `root` is the nested tree: a TreeNode for the folder with id ROOT_FOLDER, the top level.
    `flat` is every node below it, depth first (each folder followed by its contents), each
    with its `depth`: the order a sidebar lists them in. The children lists of library.json's
    `folders` decide the nesting. What they do not reach is added to the top level; so a
    library without `folders` is every playlist at the top level. A child naming nothing in
    the library is left out, and nothing is listed twice. Without a root entry, the top level
    is the folders whose parent is null.

    Each folder's contents are in the order Apple Music's sidebar shows, whatever the order of
    the children lists (Apple's API answers in an order of its own): Favourite Songs first,
    then the folders, then the playlists, each group by title (place_key), ties in the lists'
    order. sort() places them again after a title changed in place. Built by Library.load()
    (the model: GObject only, no GTK).
    """

    def __init__(self, folders=(), playlists=(), existing=None, stores=None):
        """folders: library.json's `folders` dicts; playlists: the playlist Items; existing:
        a {(kind, id): Item} index whose folder Items are reused (a reload keeps them; those
        whose SORT_KEYS changed are listed in `changed`); stores: {folder id: Gio.ListStore},
        the stores a folder still in the tree keeps, brought to its new contents with the
        fewest changes (apply_diff: a reload keeps them, as a grid over one keeps its place)."""
        folders = [raw for raw in folders if _text(raw.get('id'))]
        raw_by_id = {}
        for raw in folders:
            raw_by_id.setdefault(_text(raw.get('id')), raw)
        playlist_by_id = {}
        for item in playlists:
            playlist_by_id.setdefault(item.id, item)
        root_raw = raw_by_id.get(ROOT_FOLDER)
        if root_raw is None:
            root_raw = {'id': ROOT_FOLDER, 'title': '', 'parent': None, 'children': [
                {'kind': 'folder', 'id': _text(raw.get('id'))} for raw in folders
                if raw.get('parent') is None]}
        existing = existing or {}
        self.changed = []

        def folder_item(raw):
            return _folder_item(raw, existing.get(('folder', _text(raw.get('id')))),
                                self.changed)

        self.root = TreeNode(folder_item(root_raw), -1, None)
        self.flat = []
        self._folders = {ROOT_FOLDER: self.root}
        placed = set()  # (kind, id) already in the tree

        def fill(node, children):
            for child in _dicts(children):
                kind, child_id = child.get('kind'), _text(child.get('id'))
                if (kind, child_id) in placed:
                    continue
                if kind == 'folder' and child_id in raw_by_id:
                    add(node, folder_item(raw_by_id[child_id]), raw_by_id[child_id])
                elif kind == 'playlist' and child_id in playlist_by_id:
                    add(node, playlist_by_id[child_id])

        def add(parent, item, raw=None):
            placed.add((item.kind, item.id))
            child = TreeNode(item, parent.depth + 1, parent)
            parent.children.append(child)
            if item.kind == 'folder':
                self._folders[item.id] = child
                fill(child, raw.get('children'))

        placed.add(('folder', ROOT_FOLDER))
        fill(self.root, root_raw.get('children'))
        for raw in folders:
            if ('folder', _text(raw.get('id'))) not in placed:
                add(self.root, folder_item(raw), raw)
        for item in playlists:
            if ('playlist', item.id) not in placed:
                add(self.root, item)
        stores = stores or {}
        for folder_id, node in self._folders.items():
            node.store = stores.get(folder_id)
        self._place()

    def _place(self):
        """Sort each folder's children (place_key; the sort is stable, so ties keep Apple's
        order), list `flat` depth first again, and bring each folder's store to its children:
        made when it has none, else with the fewest changes (apply_diff)."""
        for node in self._folders.values():
            node.children.sort(key=lambda child: place_key(child.item))
        self.flat = []

        def walk(node):
            for child in node.children:
                self.flat.append(child)
                if child.children:
                    walk(child)

        walk(self.root)
        for node in self._folders.values():
            items = [child.item for child in node.children]
            if node.store is None:
                node.store = Gio.ListStore(item_type=Item)
                node.store.splice(0, 0, items)
            else:
                apply_diff(node.store, items)

    def sort(self):
        """Place everything again by the titles the Items have now, after one changed in
        place (a rename merged into its Item): the stores follow with the fewest changes.
        True when anything moved. A load or reload makes a new tree, sorted as it is made."""
        before = [node.item for node in self.flat]
        self._place()
        return any(old is not node.item for old, node in zip(before, self.flat, strict=True))

    def folder(self, folder_id):
        """The TreeNode of the folder with that id (ROOT_FOLDER for the top level), or None."""
        return self._folders.get(folder_id)

    def folders(self):
        """Every folder's TreeNode but the root's, depth first."""
        return [node for node in self.flat if node.kind == 'folder']

    def node(self, kind, item_id):
        """The TreeNode of the playlist or folder of that kind and id (the root's for the
        folder ROOT_FOLDER), or None."""
        if kind == 'folder':
            return self._folders.get(item_id)
        return next((node for node in self.flat if node.kind == kind and node.id == item_id),
                    None)

    def can_move(self, kind, item_id, folder_id):
        """Whether the playlist or folder of that kind and id can go into the folder
        `folder_id` (ROOT_FOLDER: the top level): both are in the tree, it is not Favourite
        Songs, not the top level itself, not in that folder already, and a folder does not go
        into itself or into a folder inside it."""
        node = self.node(kind, item_id)
        target = self._folders.get(folder_id)
        if node is None or target is None or node is self.root or node.item.favourites:
            return False
        if node.parent is target:
            return False
        ancestor = target
        while ancestor is not None:
            if ancestor is node:
                return False
            ancestor = ancestor.parent
        return True

    def stores(self):
        """Every folder's store by the folder's id, the root's (ROOT_FOLDER) first."""
        return {folder_id: node.store for folder_id, node in self._folders.items()}


def _folder_item(raw, existing=None, changed=None):
    """A folders entry as an Item of kind 'folder': `existing` brought up to date (added to the
    list `changed` when its SORT_KEYS changed), or a new one."""
    folder_id = _text(raw.get('id'))
    data = {'id': folder_id, 'kind': 'folder', 'title': _text(raw.get('title')) or '',
            'play': {}, 'groups': [], 'parent': raw.get('parent'),
            'children': raw.get('children')}
    if existing is not None and existing.kind == 'folder' and existing.id == folder_id:
        if not SORT_KEYS.isdisjoint(existing.merge(data, replace=True)) and changed is not None:
            changed.append(existing)
        return existing
    return Item(data)


class TreeChange:
    """A change to the playlist folders that Apple has taken but may not list yet
    (Library.hold()): `op` 'move' (the playlist or folder of `kind` and `id` into the folder
    `folder_id`, ROOT_FOLDER for the top level) or 'create' (a new folder `id` called
    `title`, in `folder_id`). `expires` is when Apple's listing wins regardless (_now()
    seconds). A folder's move carries `entries`, library.json's entries of the folder and
    of the folders inside it as they were when it moved (Library.hold() fills them in):
    Apple stops listing a folder where it was seconds after a move into another folder,
    but lists it in its new folder only about a minute later, and a sync in between finds
    it nowhere."""

    __slots__ = ('op', 'kind', 'id', 'folder_id', 'title', 'expires', 'entries')

    def __init__(self, op, kind, item_id, folder_id, title='', hold=None):
        self.op = op
        self.kind = kind
        self.id = item_id
        self.folder_id = folder_id or ROOT_FOLDER
        self.title = title
        self.expires = _now() + (PENDING_HOLD if hold is None else hold)
        self.entries = ()

    @classmethod
    def move(cls, kind, item_id, folder_id):
        return cls('move', kind, item_id, folder_id)

    @classmethod
    def create(cls, folder_id, title, parent_id):
        return cls('create', 'folder', folder_id, parent_id, title)

    def __repr__(self):
        return f'TreeChange({self.op}, {self.kind}, {self.id!r}, into {self.folder_id!r})'


def _now():
    return time.monotonic()


def _with_root(folders):
    """library.json's `folders` as fresh dicts (their `children` lists copied), with a root
    entry: made from the parentless folders when the file has none, as PlaylistTree does."""
    copied = [dict(raw, children=list(_dicts(raw.get('children')))) for raw in _dicts(folders)
              if _text(raw.get('id'))]
    if not any(_text(raw.get('id')) == ROOT_FOLDER for raw in copied):
        copied.insert(0, {'id': ROOT_FOLDER, 'title': '', 'parent': None, 'children': [
            {'kind': 'folder', 'id': _text(raw.get('id'))} for raw in copied
            if raw.get('parent') is None]})
    return copied


def folder_of(folders, kind, item_id):
    """The id of the folder library.json's `folders` lists the playlist or folder in (the
    first that does), ROOT_FOLDER when none does (PlaylistTree puts it at the top level), or
    None for a folder the file does not have at all."""
    if kind == 'folder' and not any(_text(raw.get('id')) == item_id for raw in _dicts(folders)):
        return None
    for raw in _dicts(folders):
        for child in _dicts(raw.get('children')):
            if child.get('kind') == kind and _text(child.get('id')) == item_id:
                return _text(raw.get('id'))
    return ROOT_FOLDER


def folder_entries(folders, folder_id):
    """The entries of `folders` (library.json's) for the folder folder_id and every folder
    inside it, the folder's first, as copies; none when the folder is not there."""
    by_id = {_text(raw.get('id')): raw for raw in _dicts(folders)}
    found = []
    queue = [folder_id]
    seen = set()
    while queue:
        raw = by_id.get(queue.pop(0))
        if raw is None or _text(raw.get('id')) in seen:
            continue
        seen.add(_text(raw.get('id')))
        found.append(dict(raw, children=list(_dicts(raw.get('children')))))
        queue.extend(_text(child.get('id')) for child in _dicts(raw.get('children'))
                     if child.get('kind') == 'folder')
    return tuple(found)


def change_settled(folders, change):
    """Whether library.json's `folders` shows the TreeChange already: the item listed in
    its new folder, the folder created."""
    if change.op == 'create':
        return folder_of(folders, 'folder', change.id) is not None
    return folder_of(folders, change.kind, change.id) == change.folder_id


def apply_changes(folders, changes):
    """library.json's `folders` with the TreeChanges applied, in order, as a new list (the
    one given is left alone): a moved playlist or folder taken out of every folder's
    children and added to its new folder's (a folder's own `parent` follows), a created
    folder added with no children. A moved folder the list lacks (a sync while Apple
    listed it nowhere) is put back from the change's `entries`, with the folders inside it
    that the list lacks too; failing that the change is skipped, as is one into a folder
    the list lacks. PlaylistTree orders each folder's contents by title, so where a child
    goes in its list does not matter."""
    if not changes:
        return list(_dicts(folders))
    result = _with_root(folders)
    by_id = {_text(raw.get('id')): raw for raw in result}
    for change in changes:
        target = by_id.get(change.folder_id)
        if target is None:
            continue
        if change.op == 'create':
            if change.id in by_id:
                continue
            entry = {'id': change.id, 'title': change.title, 'parent': change.folder_id,
                     'children': []}
            result.append(entry)
            by_id[change.id] = entry
        elif change.kind == 'folder' and change.id not in by_id:
            for raw in change.entries:
                entry_id = _text(raw.get('id'))
                if entry_id and entry_id not in by_id:
                    entry = dict(raw, children=list(_dicts(raw.get('children'))))
                    result.append(entry)
                    by_id[entry_id] = entry
            if change.id not in by_id:
                continue
        for raw in result:
            raw['children'] = [child for child in raw['children']
                               if (child.get('kind'), _text(child.get('id')))
                               != (change.kind, change.id)]
        target['children'].append({'kind': change.kind, 'id': change.id})
        if change.kind == 'folder':
            by_id[change.id]['parent'] = change.folder_id
    return result


def place_key(item):
    """Where a playlist tree's Item goes among its folder's, as Apple Music's sidebar places
    it: Favourite Songs first, then the folders, then the playlists, each by title_key()."""
    rank = 0 if item.favourites else 1 if item.kind == 'folder' else 2
    return rank, title_key(item.title)
