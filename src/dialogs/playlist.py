# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The playlists' dialogs, which the item actions (actions.py) present over the window.

    PlaylistDialog(heading, confirm, details, folders, done)   # a playlist's details
    NameDialog(heading, confirm, name, description, done)   # a folder's name
    confirm(parent, heading, body, confirm, done)           # before something is deleted

PlaylistDialog is the one dialog that makes a playlist (New Playlist…, wherever it is
offered) and changes one (Edit Details…): an `Adw.Dialog` (playlist.blp) with Cancel and the
confirming button in its header bar, the name (Enter confirms; the button is off while the
name is blank), the description (several lines), the folder it goes in (`folders`, the
choices actions.folder_choices() makes: Top Level and the folders, as Move to Folder names
them; no row when None) and whether it is public, shown on the account's profile and in
search (Apple's isPublic). `details` is the actions.Details it opens with; done(details)
gets the Details confirmed, the name stripped, the description at most DESCRIPTION_LIMIT
characters (Apple's limits, as the web player's form sets them). Apple takes no cover image
for a library playlist (src/backend/README.md), so it has none.

NameDialog asks for a folder's name (and, given a `description`, a description too). Its
confirming response is the default, so Enter in either row confirms, and it is off while
the name is blank; done(name, description) gets the name stripped and the description as
typed, or None when it is the one the dialog opened with (nothing to change). confirm() is
libadwaita's alert, the deleting response destructive and Cancel the default, as Clear
Cache's and Sign Out's are. A dialog can be dropped: its children's signals are connected
weakly (widgets/util.py).
"""

from gettext import gettext as _

from gi.repository import Adw, Gtk

from ..actions import Details
from ..library import ROOT_FOLDER
from ..widgets.labels import named_list_factory
from ..widgets.util import connect_weak

CANCEL = 'cancel'
CONFIRM = 'confirm'

# Apple's own limits, as the web player's playlist form sets them (maxlength).
NAME_LIMIT = 255
DESCRIPTION_LIMIT = 2000


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/playlist.ui')
class PlaylistDialog(Adw.Dialog):
    """A playlist's details, for a new one or Edit Details…. See the module."""

    __gtype_name__ = 'AppleMusicPlaylistDialog'

    cancel_button = Gtk.Template.Child()
    confirm_button = Gtk.Template.Child()
    name_row = Gtk.Template.Child()
    description_view = Gtk.Template.Child()
    folder_row = Gtk.Template.Child()
    public_row = Gtk.Template.Child()

    def __init__(self, heading, confirm, details=None, folders=None, done=None):
        super().__init__(title=heading)
        details = details or Details()
        self._done = done
        self._details = details
        self.confirm_button.set_label(confirm)
        self.name_row.set_text(details.name or '')
        delegate = self.name_row.get_delegate()
        if isinstance(delegate, Gtk.Text):
            delegate.set_max_length(NAME_LIMIT)
        self.description_view.get_buffer().set_text(details.description or '')
        self._folders = [folder_id for folder_id, _label in folders or ()]
        if folders:
            self.folder_row.set_model(Gtk.StringList.new([label for _id, label in folders]))
            self.folder_row.set_factory(named_list_factory(self.folder_row, popup=False))
            self.folder_row.set_list_factory(named_list_factory(self.folder_row, popup=True))
            folder = details.folder or ROOT_FOLDER
            if folder in self._folders:
                self.folder_row.set_selected(self._folders.index(folder))
        else:
            self.folder_row.set_visible(False)
        self.public_row.set_active(bool(details.public))
        connect_weak(self.name_row, 'changed', self._on_name_changed)
        connect_weak(self.confirm_button, 'clicked', self._on_confirm)
        connect_weak(self.cancel_button, 'clicked', self._on_cancel)
        self.connect('closed', PlaylistDialog._on_closed)
        self._on_name_changed()

    def name(self):
        return self.name_row.get_text().strip()

    def details(self):
        """The Details as the dialog has them now."""
        buffer = self.description_view.get_buffer()
        description = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        folder = self._details.folder or ROOT_FOLDER
        selected = self.folder_row.get_selected()
        if self._folders and 0 <= selected < len(self._folders):
            folder = self._folders[selected]
        return Details(self.name(), description[:DESCRIPTION_LIMIT], folder,
                       self.public_row.get_active())

    def _on_name_changed(self, *_args):
        self.confirm_button.set_sensitive(bool(self.name()))

    def _on_confirm(self, *_args):
        if not self.name():
            return
        done, self._done = self._done, None  # the actions it holds go with the answer
        details = self.details()
        self.close()
        if done is not None:
            done(details)

    def _on_cancel(self, *_args):
        self.close()

    def _on_closed(self):
        self._done = None


class NameDialog(Adw.AlertDialog):
    """A name (and a description) for a folder. See the module."""

    __gtype_name__ = 'AppleMusicNameDialog'

    def __init__(self, heading, confirm, name='', description=None, done=None):
        super().__init__(heading=heading)
        self._done = done
        self._description = description
        self.name_row = Adw.EntryRow(title=_('Name'), text=name or '', activates_default=True)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=['boxed-list'])
        rows.append(self.name_row)
        self.description_row = None
        if description is not None:
            self.description_row = Adw.EntryRow(title=_('Description'), text=description,
                                                activates_default=True)
            rows.append(self.description_row)
        self.set_extra_child(rows)
        self.add_response(CANCEL, _('_Cancel'))
        self.add_response(CONFIRM, confirm)
        self.set_response_appearance(CONFIRM, Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response(CONFIRM)
        self.set_close_response(CANCEL)
        self.set_focus(self.name_row)
        connect_weak(self.name_row, 'changed', self._on_name_changed)
        self.connect('response', NameDialog._on_response)
        self._on_name_changed()

    def name(self):
        return self.name_row.get_text().strip()

    def description(self):
        """The description typed, or None when it is unchanged (or there is none to edit)."""
        if self.description_row is None:
            return None
        text = self.description_row.get_text()
        return None if text == self._description else text

    def _on_name_changed(self, *_args):
        self.set_response_enabled(CONFIRM, bool(self.name()))

    def _on_response(self, response):
        if response == CONFIRM and self.name() and self._done is not None:
            self._done(self.name(), self.description())
        self._done = None  # the actions it holds go with the dialog's answer


def confirm(parent, heading, body, label, done):
    """An alert over `parent` asking to delete something: Cancel (the default, and what
    Escape does) and `label`, destructive, which calls done(). The dialog."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response(CANCEL, _('_Cancel'))
    dialog.add_response(CONFIRM, label)
    dialog.set_response_appearance(CONFIRM, Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response(CANCEL)
    dialog.set_close_response(CANCEL)
    dialog.connect('response', lambda _dialog, response: done() if response == CONFIRM else None)
    dialog.present(parent)
    return dialog
