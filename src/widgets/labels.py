# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What tiles and rows read to assistive technology: the rules in one place, the words
looked up once (a list binds its rows by the thousand, and gettext is slow when hot).

    list_item.set_accessible_label(accessible_label(item, artist=tile_is_an_artist))
    bind_label(list_item, item, artist)   # the same, following a renamed Item (unbind_label)
    list_item.set_accessible_label(track_label(track, show_artist=True, show_album=True))
    child = flow_child(tile, accessible_label(item))   # a Gtk.FlowBox's create function
    caption.set_text(song_caption(item))   # a song row's album and year, its second line
    row.set_factory(named_list_factory(row, popup=False))   # a combo row's or drop-down's

No template here, so the unit tests import it without a display.
"""

from gettext import gettext as _

from gi.repository import Gtk, Pango

_formats = {}


def _format(name):
    if not _formats:
        _formats.update({
            # Translators: what a screen reader says for a tile: its title, then its
            # subtitle (an album's artist, a playlist's curator): "Album, Artist".
            'subtitle': _('{title}, {subtitle}'),
            # Translators: what a screen reader says for a song's row is its title, then its
            # artist and album, each added to what comes before it with this, e.g.
            # "Song, Artist" then "Song, Artist, Album".
            'part': _('{label}, {part}'),
            # Translators: added to what a screen reader says for a song with explicit lyrics.
            'explicit': _('{label}, explicit'),
            # Translators: added to what a screen reader says for a song, album, playlist or
            # music video the user has marked as a favourite (the heart it shows).
            'favourite': _('{label}, favourite'),
            # Translators: what a screen reader says for a chart's entry: its place in the
            # chart, then the tile's or the song's words, e.g. "Number 1, Song, Artist".
            'rank': _('Number {rank}, {label}'),
        })
    return _formats[name]


def accessible_label(item, artist=False):
    """A tile's name: the title and the subtitle; the title alone for an artist (`artist`, or
    an Item of kind 'artist': the name is all there is) or an item without a subtitle; and
    "favourite" for a favourite (the heart the tile shows)."""
    if artist or item.kind == 'artist' or not item.subtitle:
        label = item.title
    else:
        label = _format('subtitle').format(title=item.title, subtitle=item.subtitle)
    if item.favourite and not artist and item.kind != 'artist':
        label = _format('favourite').format(label=label)
    return label


def ranked(rank, label):
    """A chart entry's name: its place in the chart (`rank`, from 1) before `label`, the
    words its tile or row has; `label` alone without a rank."""
    return _format('rank').format(rank=rank, label=label) if rank else label


def track_label(track, show_artist=True, show_album=True, favourite=False, columns=()):
    """A track row's name: its title, then its artist and its album when the row shows them
    and they are known (a missing one is left out, not read as an empty field), its genre
    and year when the table shows those columns (`columns`: song_columns.OPTIONAL names),
    "explicit" for explicit lyrics (the badge the row shows), and "favourite" for one of the
    account's favourites (`favourite`: the row's heart)."""
    parts = [track.title, track.artist if show_artist else '',
             track.album if show_album else '']
    if columns:
        if 'genre' in columns:
            parts.append(track.genre)
        if 'year' in columns and track.year:
            parts.append(str(track.year))
    parts = [part for part in parts if part]
    label = parts[0] if parts else ''
    for part in parts[1:]:
        label = _format('part').format(label=label, part=part)
    if track.explicit:
        label = _format('explicit').format(label=label)
    if favourite:
        label = _format('favourite').format(label=label)
    return label


def song_label(item):
    """A song Item's row name (an artist's Top Songs): its title, its album when known, and
    "explicit" for explicit lyrics, as track_label() words a track."""
    label = item.title
    album = item.raw.get('album') if isinstance(item.raw, dict) else None
    if album:
        label = _format('part').format(label=label, part=album)
    if item.explicit:
        label = _format('explicit').format(label=label)
    return label


def song_caption(item):
    """A song row's second line, beside song_label(): its album and year ("Album · 2026"),
    or whichever it has."""
    parts = [item.raw.get('album') or '', str(item.year) if item.year else '']
    return ' · '.join(part for part in parts if part)


def suggestion_label(item):
    """A suggested song's row name: its title, its artist and its album when known, and
    "explicit" for explicit lyrics, as track_label() words a track."""
    label = item.title
    album = item.raw.get('album') if isinstance(item.raw, dict) else None
    for part in (item.subtitle, album):
        if part:
            label = _format('part').format(label=label, part=part)
    if item.explicit:
        label = _format('explicit').format(label=label)
    return label


def suggestion_caption(item):
    """A suggested song's second line: its artist and its album ("Artist · Album"), or
    whichever it has."""
    parts = [item.subtitle or '', item.raw.get('album') or '']
    return ' · '.join(part for part in parts if part)


def flow_child(widget, label):
    """A Gtk.FlowBoxChild holding widget, named `label` for assistive technology (a flow box's
    children are not list items: their name is set on the child)."""
    child = Gtk.FlowBoxChild(child=widget)
    child.update_property([Gtk.AccessibleProperty.LABEL], [label])
    return child


def bind_label(list_item, item, artist=False, rank=None):
    """Name a recycled tile's list item accessible_label(item, artist), after its place in
    a chart when it has one (`rank`: ranked()), and name it again whenever the Item's title,
    subtitle or favourite changes while it is bound: a reload merges new values into the
    Item and a list does not rebind it (the tile follows its Item the same way).
    unbind_label() in the factory's unbind stops it."""
    unbind_label(list_item)
    list_item.set_accessible_label(ranked(rank, accessible_label(item, artist)))

    def on_notify(notified, pspec):
        if pspec.name in ('title', 'subtitle', 'favourite'):
            list_item.set_accessible_label(
                ranked(rank, accessible_label(notified, artist)))

    list_item.label_handler = (item, item.connect('notify', on_notify))


def unbind_label(list_item):
    """Stop following what bind_label() followed."""
    followed = getattr(list_item, 'label_handler', None)
    if followed is not None:
        item, handler = followed
        item.disconnect(handler)
        list_item.label_handler = None


def named_list_factory(view, popup, drop_down=False):
    """A factory for the list items of a value chooser (an Adw.ComboRow, a Gtk.DropDown) over
    a Gtk.StringList, as the toolkit's own (a label; in the popup, a check mark on the item
    selected) but naming each item for assistive technology: the defaults leave them unnamed,
    in the popup and in the chooser's own display of the value, which is a list of one item
    too (the chooser itself is named by its title or label). Laid out as AdwComboRow's (the
    label shortens to fit), or with `drop_down` as GtkDropDown's (the label as wide as its
    text, 10 px before the check mark). The view is held weakly: the factory is the view's
    own, and a closure holding the view would keep a closed dialog or a dropped page alive."""
    view_ref = view.weak_ref()

    def setup(_factory, item):
        if drop_down:
            box = Gtk.Box(spacing=10)
            label = Gtk.Label(xalign=0, valign=Gtk.Align.CENTER)
        else:
            box = Gtk.Box()
            label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=20,
                              width_chars=1, valign=Gtk.Align.CENTER)
        box.append(label)
        if popup:
            box.append(Gtk.Image(icon_name='object-select-symbolic',
                                 accessible_role=Gtk.AccessibleRole.PRESENTATION))
        item.set_child(box)

    def bind(_factory, item):
        view = view_ref()
        if view is None:
            return
        text = item.get_item().get_string()
        box = item.get_child()
        box.get_first_child().set_label(text)
        item.set_accessible_label(text)
        if not popup:
            return
        check = box.get_last_child()

        def follow(*_args):
            current = view_ref()
            selected = current.get_selected_item() if current is not None else None
            check.set_opacity(1.0 if selected == item.get_item() else 0.0)

        item.follow_handler = view.connect('notify::selected-item', follow)
        follow()

    def unbind(_factory, item):
        view = view_ref()
        handler = getattr(item, 'follow_handler', None)
        if view is not None and handler is not None:
            view.disconnect(handler)
        item.follow_handler = None

    factory = Gtk.SignalListItemFactory()
    factory.connect('setup', setup)
    factory.connect('bind', bind)
    factory.connect('unbind', unbind)
    return factory
