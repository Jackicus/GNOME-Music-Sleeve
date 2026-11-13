# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What the item actions say: the toasts that confirm them, the confirmations' headings
and bodies, and what assistive technology is told as an Up Next entry moves. Translated on
call, so after gettext is set up.
"""

from gettext import gettext as _
from gettext import ngettext

def queue_message(title, later, count=1, total=None):
    """The toast after Play Next or Play Later (`later`) of one item called `title`, or of
    `count` of them; of the first `count` of `total` selected, when that is more (a
    selection's queue actions take at most PLAY_LIMIT)."""
    if total is not None and total > count:
        if later:
            return ngettext('The first {count} of {total} items will play later',
                            'The first {count} of {total} items will play later',
                            count).format(count=f'{count:n}', total=f'{total:n}')
        return ngettext('The first {count} of {total} items will play next',
                        'The first {count} of {total} items will play next',
                        count).format(count=f'{count:n}', total=f'{total:n}')
    if count > 1:
        if later:
            return ngettext('{count} item will play later', '{count} items will play later',
                            count).format(count=f'{count:n}')
        return ngettext('{count} item will play next', '{count} items will play next',
                        count).format(count=f'{count:n}')
    if later:
        return (_('“{title}” will play later').format(title=title) if title
                else _('Playing later'))
    return _('“{title}” will play next').format(title=title) if title else _('Playing next')


def added_message(count, playlist='', new=False):
    """The toast after `count` songs (an album's, a playlist's) were added to the playlist
    named `playlist`, or (`new`) to the new playlist of that name."""
    if new:
        return ngettext('Added {count} song to the new playlist “{playlist}”',
                        'Added {count} songs to the new playlist “{playlist}”',
                        count).format(count=f'{count:n}', playlist=playlist)
    if playlist:
        return ngettext('Added {count} song to “{playlist}”',
                        'Added {count} songs to “{playlist}”',
                        count).format(count=f'{count:n}', playlist=playlist)
    return ngettext('Added {count} song to the playlist', 'Added {count} songs to the playlist',
                    count).format(count=f'{count:n}')


def removed_message(count, playlist='', title=''):
    """The toast after `count` songs (a selection's, or Delete's) were taken out of the
    playlist named `playlist`; one song by its `title`, when it has one."""
    if count == 1 and title and playlist:
        return _('Removed “{title}” from “{playlist}”').format(title=title, playlist=playlist)
    if playlist:
        return ngettext('Removed {count} song from “{playlist}”',
                        'Removed {count} songs from “{playlist}”',
                        count).format(count=f'{count:n}', playlist=playlist)
    return ngettext('Removed {count} song from the playlist',
                    'Removed {count} songs from the playlist', count).format(count=f'{count:n}')


def removals_words(count):
    """(heading, body) of the confirmation before Remove from Library takes out `count`
    songs (a selection's), and the toast once they are gone."""
    heading = ngettext('Remove {count} Song from Library?', 'Remove {count} Songs from Library?',
                       count).format(count=f'{count:n}')
    body = ngettext('The song will be removed from your library and from your playlists on '
                    'all your devices.',
                    'The songs will be removed from your library and from your playlists on '
                    'all your devices.', count)
    return heading, body


def library_removed_message(count):
    """The toast once `count` songs (a selection's) were taken out of the library."""
    return ngettext('Removed {count} song from your library',
                    'Removed {count} songs from your library', count).format(count=f'{count:n}')


def removal_words(kind, title):
    """(heading, body) of the confirmation before Remove from Library takes out an item of
    `kind` named `title`: what else goes with it."""
    heading = _('Remove from Library?')
    if kind == 'playlist':
        body = (_('“{title}” will be removed from your library on all your devices.')
                if title else _('The playlist will be removed from your library on all your '
                                'devices.'))
    elif kind == 'album':
        body = (_('“{title}” and its songs will be removed from your library and from your '
                  'playlists on all your devices.') if title
                else _('The album and its songs will be removed from your library and from '
                       'your playlists on all your devices.'))
    else:
        body = (_('“{title}” will be removed from your library and from your playlists on '
                  'all your devices.') if title
                else _('It will be removed from your library and from your playlists on all '
                       'your devices.'))
    return heading, body.format(title=title)


def duplicate_name(name):
    """The name of a playlist's copy (Duplicate), as GNOME's Files names a copy."""
    # Translators: the name Duplicate gives a copy of a playlist: {name} is its name
    # ("Road Trip Copy").
    return _('{name} Copy').format(name=name) if name else _('Untitled Playlist Copy')


def queue_move_message(title, index, queue_index, count):
    """What assistive technology is told as an Up Next entry moves: its title, and its place
    among the entries after the one playing (at `queue_index`, of `count` in the queue)."""
    # Translators: said to screen reader users as a song is moved in Up Next: “Harbour
    # Lights” moved to position 2 of 9 in Up Next (1 plays next).
    return _('“{title}” moved to position {position} of {count} in Up Next').format(
        title=title or _('Unknown Title'), position=f'{index - queue_index:n}',
        count=f'{count - queue_index - 1:n}')


def not_found_message(kind):
    """The toast when Go to Album (`kind` 'album') or Go to Artist finds nothing."""
    return _('Could not find the album') if kind == 'album' else _('Could not find the artist')


def love_messages(kind):
    """(loved, unloved) toasts for an item of kind: a song goes into Favourite Songs."""
    if kind == 'song':
        return _('Added to Favourite Songs'), _('Removed from Favourite Songs')
    return _('Added to Favourites'), _('Removed from Favourites')


def unfavourited_messages(count):
    """(removed, put back) toasts after a selection's Remove from Favourites took `count`
    songs out of Favourite Songs, and after its Undo put them back."""
    number = f'{count:n}'
    return (ngettext('Removed {count} song from Favourite Songs',
                     'Removed {count} songs from Favourite Songs', count).format(count=number),
            ngettext('Put back {count} song in Favourite Songs',
                     'Put back {count} songs in Favourite Songs', count).format(count=number))


def suggest_less_messages():
    """(set, undone) toasts for Suggest Less and Undo Suggest Less."""
    return _('Apple Music will suggest less like this'), _('Suggest Less undone')
