# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicCreditsDialog: a song's credits (View Credits, presented by the item actions).

    CreditsDialog(app, catalog_song_id, title).present(window)

Presenting it asks Engine.credits for the song (kept for a day: no engine needed then) with a
spinner meanwhile, then shows a boxed list for each kind of credit, in Apple's order, titled
as Apple titles it (src/credits.py words the rest): each person's name, with their roles
under it. A song Apple has no credits for shows No Credits; what the engine's failure means
(engine down, signed out, the demo, Apple failing) is widgets.engine_status.EngineStatus's,
with its button (Start Engine, Sign In…, Try Again), and the engine is followed while the
dialog is shown, so a start it waits for loads the credits. The song's title is the header
bar's subtitle. Escape closes it, which cancels the request; libadwaita gives the focus back
to where it was, the row or the menu's button. A dialog can be dropped: its children's signals
are connected weakly (widgets/util.py).
"""

import logging
from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk

from ..backend.errors import EngineError
from ..credits import sections
from ..widgets.engine_status import EngineStatus
from ..widgets.util import connect_weak

log = logging.getLogger(__name__)


@Gtk.Template(resource_path='/io/github/jackicus/MusicSleeve/credits.ui')
class CreditsDialog(Adw.Dialog):
    __gtype_name__ = 'AppleMusicCreditsDialog'

    window_title = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    status_button = Gtk.Template.Child()
    credits_page = Gtk.Template.Child()

    def __init__(self, app, song_id, title=''):
        super().__init__()
        self._app = app
        self.song_id = str(song_id or '')
        self._task = None
        self._groups = []
        self.status = None  # what shows: 'loading', 'credits', 'empty' or EngineStatus's
        self.window_title.set_subtitle(title or '')
        self._engine_status = EngineStatus(app, self._show_status, self.load, {
            'engine-down': _('Start the engine to see the credits'),
            'not-signed-in': _('Credits appear once you sign in to Apple Music'),
            'failed': _('Could Not Load the Credits'),
            'demo': _('Credits come from Apple Music; the demo library is offline'),
        })
        # Weakly (widgets/util.py): a bound method would keep every closed dialog alive.
        connect_weak(self.status_button, 'clicked', self._on_status_clicked)
        self.connect('closed', CreditsDialog._on_closed)

    def present(self, parent=None):
        Adw.Dialog.present(self, parent)
        if self._task is None and self.status is None:
            self.load()

    def do_map(self):
        Adw.Dialog.do_map(self)
        self._engine_status.watch()

    def do_unmap(self):
        self._engine_status.unwatch()
        Adw.Dialog.do_unmap(self)

    def load(self):
        """Ask for the credits (again: Try Again, or the engine come up)."""
        self._cancel()
        self._task = self._app.spawn(self._load())

    async def _load(self):
        self._engine_status.loading()
        try:
            answer = await self._app.engine.credits(self.song_id)
        except EngineError as error:
            log.info('credits of %s: %s', self.song_id, error)
            self._engine_status.fail(error)
            return
        self._engine_status.clear()
        self.show_credits(answer)

    def show_credits(self, answer):
        """Show Engine.credits' answer: its sections, or No Credits."""
        for group in self._groups:
            self.credits_page.remove(group)
        self._groups = []
        found = sections(answer)
        if not found:
            self.status = 'empty'
            self._show_page(_('No Credits'),
                            _('Apple Music has no credits for this song'), None)
            return
        for heading, people in found:
            # A group's title is markup; Apple's words and the names are text.
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(heading))
            for name, roles in people:
                row = Adw.ActionRow(use_markup=False)
                row.set_title(name)
                row.set_subtitle(roles)
                group.add(row)
            self.credits_page.add(group)
            self._groups.append(group)
        self.status = 'credits'
        self.stack.set_visible_child_name('credits')

    def _show_status(self, status, title, description, button):
        """EngineStatus's states: the spinner ('loading'), or the status page with its
        words and button."""
        self.status = status
        if status == 'loading':
            self.stack.set_visible_child_name('loading')
            return
        self._show_page(title, description, button)

    def _show_page(self, title, description, button):
        self.status_page.set_title(title or '')
        self.status_page.set_description(description or '')
        self.status_button.set_label(button or '')
        self.status_button.set_visible(bool(button))
        self.stack.set_visible_child_name('status')

    def _on_status_clicked(self, _button):
        self._engine_status.activate()

    def _on_closed(self):
        self._engine_status.unwatch()
        self._cancel()

    def _cancel(self):
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
