# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""The song tables' optional columns, Genre and Year: the Songs table's and a playlist's.

    columns = shown(settings)                # frozenset of OPTIONAL names the setting names
    set_shown(settings, 'genre', True)       # the setting changed (both tables follow it)
    section = menu_section('songs')          # "Genre Column", "Year Column" check items
    actions = make_actions(group, callback)  # their stateful actions, in a page's group
    year_text(track.year)                    # what the Year column shows ('' for none)

One setting, song-columns, holds the columns shown, for the Songs table and every
playlist's table alike: a column turned on in one shows in the other. Each table leaves them
out where it is too narrow for them (songs.blp's and detail.blp's breakpoints), and its menu
then hides their items (`hidden-when` action-disabled: the page disables the actions).
"""

from gettext import gettext as _

from gi.repository import Gio, GLib

# The optional columns, in the order the tables show them (after the album, before the time).
OPTIONAL = ('genre', 'year')
SETTING = 'song-columns'


def shown(settings):
    """The optional columns the setting names (unknown names ignored); none without
    settings (a test's stand-in application)."""
    if settings is None:
        return frozenset()
    return frozenset(name for name in settings.get_strv(SETTING) if name in OPTIONAL)


def set_shown(settings, name, show):
    """Show the optional column `name` in the song tables, or not (the setting, in
    OPTIONAL's order); nothing without settings or for a name OPTIONAL does not have."""
    if settings is None or name not in OPTIONAL:
        return
    columns = set(shown(settings))
    if show:
        columns.add(name)
    else:
        columns.discard(name)
    settings.set_strv(SETTING, [column for column in OPTIONAL if column in columns])


def year_text(year):
    """The Year column's text for a track's year (an int, 0 when unknown)."""
    return str(year) if year else ''


def labels():
    """The menu items' labels, by column: their mnemonics are their own in the Songs page's
    Sort and Filter menu and a playlist's Sort By (songs.blp, detail.PLAYLIST_SORTS, the
    directions and Favourites Only), which sort by _Genre and _Year."""
    return {'genre': _('Genre _Column'), 'year': _('Year Co_lumn')}


def action_name(name):
    """The page's action showing the column `name`: column-genre, column-year."""
    return f'column-{name}'


def menu_section(group):
    """A menu section of check items, one a column, of the stateful actions make_actions()
    made in the action group `group` ('songs', 'tracks'); each is hidden while its action is
    disabled (the table too narrow for it)."""
    section = Gio.Menu()
    words = labels()
    for name in OPTIONAL:
        item = Gio.MenuItem.new(words[name], f'{group}.{action_name(name)}')
        item.set_attribute_value('hidden-when', GLib.Variant('s', 'action-disabled'))
        section.append_item(item)
    return section


def make_actions(actions, changed):
    """A stateful boolean action per column in the Gio.SimpleActionGroup `actions`, off; a
    change of state is handed to `changed(name, show)` (the page writes the setting), not
    applied here. The actions hold `changed`: a page passes widgets.util.weak_method() of
    its own method, or the actions would keep it alive. The actions, by column."""
    made = {}
    for name in OPTIONAL:
        action = Gio.SimpleAction.new_stateful(action_name(name), None,
                                               GLib.Variant('b', False))
        action.connect('change-state', _on_change_state, name, changed)
        actions.add_action(action)
        made[name] = action
    return made


def _on_change_state(_action, value, name, changed):
    changed(name, value.get_boolean())


def show_states(actions, columns, available):
    """Set the actions' states to the columns shown (`columns`), and enable them only where
    the table has room for them (`available`)."""
    for name, action in actions.items():
        state = name in columns
        if action.get_state().get_boolean() != state:
            action.set_state(GLib.Variant('b', state))
        action.set_enabled(available)
