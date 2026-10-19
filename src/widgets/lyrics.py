# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""AppleMusicLyricsView: the Now Playing sheet's Lyrics tab, following the Player.

A Gtk.Stack of four pages: synced lyrics as a Gtk.ListView over the Lyrics object's store
of LyricLine, unsynced lyrics as one wrapping label in a scrolled window, a spinner while
the engine reads them, and a compact status page otherwise: "Lyrics" with nothing playing,
"No Lyrics" for a song without them.

A synced row is a box (`lyric-line`) of wrapping labels, one for each of PARTS, top to
bottom: the main vocals (`box.label`, title-3), their pronunciation and translation
(`box.pronunciation`, `box.translation`), then the background vocals (`box.background`,
smaller and fainter: `lyric-background`) and theirs (`box.pronunciation_background`,
`box.translation_background`, smaller still), as Apple's own view stacks them. A label
with nothing to show is hidden: a line of background vocals only has no main label. The
line current at the Player's position carries the `current` CSS class, the others
`dimmed`; a click seeks to the line's start; the line opening a verse or a chorus
`stanza`, a gap above its box, outside the highlight the box draws for the row. In a duet
each row goes on its line's side (`lyrics.side()`, set by set_side()): the lead singer's
lines at the start, their labels aligned to it, the second singer's at the end, aligned to
that, a group's in the middle, centred, each box narrowed to duet_measure() of the list's
width by a margin on its other side (or both), so the two singers read as two columns, as
Apple's own view has them; GTK mirrors the labels' alignment and the margins in a
right-to-left layout. A song that is not a duet has its rows across the list. The
unsynced text stacks the same parts the same way (text_markup()). The pronunciations
(Apple's transliterations) and the translations show while the `lyrics-pronunciations` and
`lyrics-translations` settings are on, which the sheet's Translation and Pronunciation
menu switches.

The list follows playback only while the sheet is open (set_active), and only when the
current line changes: scroll_to brings the row on screen, and once the list's geometry has
held still for a frame (a tick callback: the sheet's opening lays the list out over a few
frames) the row glides to the middle of the view; before the first line it glides back to
the top. Not while the list is the user's: scrolled by wheel, touch or scrollbar in the
last USER_SCROLL_PAUSE seconds, or with the focus on a line (a click or Enter on a line
seeks there and hands the list back). The line current is found at the Player's
estimated_position() (MusicKit reports whole seconds; the lines start at milliseconds), on
each position event and, while shown and playing, from one GLib timeout armed for the next
line's start, so the highlight moves as the line begins rather than up to a second after.
A duet's margins follow the list's width (its horizontal adjustment's page), set again on
the rows bound when it changes, from an idle (not inside the list's allocation).
"""

import logging
import time
from collections import namedtuple
from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk, Pango

from .. import lyrics as lyrics_model

log = logging.getLogger(__name__)

USER_SCROLL_PAUSE = 4.0    # seconds after the user scrolls before the list follows again
CENTRE_DURATION = 300      # ms, the glide bringing the current line to the middle
SETTLE_FRAMES = 40         # frames to wait for the row's geometry to hold still, at most
NEXT_LINE_FLOOR = 0.05     # seconds: the least a timeout for the next line waits (no spin
                           # when the estimate stands still before a line's start)
DUET_SHARE = 0.6           # a duet's line takes this share of the list's width (Apple's)...
DUET_MIN_WIDTH = 280       # px: ...or this much, in a narrow list, the whole width at most


class LyricsView(Gtk.Stack):
    """The Lyrics tab. See the module."""

    __gtype_name__ = 'AppleMusicLyricsView'

    def __init__(self):
        super().__init__(vhomogeneous=True, hhomogeneous=True,
                         transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.add_css_class('lyrics-view')
        self._player = None
        self._app = None
        self._active = False
        self._lyrics = None
        self._shown = Shown(False, False)   # the settings: the lines' extras shown
        self._current = -1              # the index of the line current, or -1
        self._rows = {}                 # bound position -> its row's box
        self._centre_pending = None     # a line to centre once its row holds still
        self._tick = None               # the tick callback watching for that
        self._tick_geometry = None      # what the last frame measured
        self._tick_frames = 0
        self._page_seen = None          # the page size the last scroll_to or centring saw
        self._user_scrolled_at = 0.0
        self._keyboard_in_list = False  # the focus is on a line: the list is the user's
        self._animation = None
        self._next_line_source = 0      # the timeout for the next line's start, while armed
        self._width = 0                 # the list's width, as its adjustment last said
        self._inset = 0                 # a duet's row's margin: the width it leaves
        self._inset_source = 0          # the idle setting a new one on the rows, while armed

        self.empty_page = Adw.StatusPage(icon_name='music-note-symbolic', title=_('Lyrics'))
        self.empty_page.add_css_class('compact')
        self.add_named(self.empty_page, 'empty')

        spinner = Adw.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                              width_request=32, height_request=32)
        self.add_named(spinner, 'loading')

        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._on_setup)
        factory.connect('bind', self._on_bind)
        factory.connect('unbind', self._on_unbind)
        # Tab leaves the list after the line with the focus; the arrows move between lines,
        # Enter seeks to one.
        self.list_view = Gtk.ListView(factory=factory, single_click_activate=True,
                                      model=Gtk.NoSelection(),
                                      tab_behavior=Gtk.ListTabBehavior.ITEM)
        self.list_view.add_css_class('lyrics-list')
        self.list_view.update_property([Gtk.AccessibleProperty.LABEL], [_('Lyrics')])
        self.list_view.connect('activate', self._on_activate)
        self.scrolled = Gtk.ScrolledWindow(child=self.list_view,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER)
        # The user scrolling the list, by any means, pauses the following: the wheel or a
        # touchpad, a finger dragging the list, the scrollbar dragged, and the keyboard
        # moving between lines (while the focus is on one, the list is the user's).
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL,
                                           propagation_phase=Gtk.PropagationPhase.CAPTURE)
        scroll.connect('scroll', self._on_user_scroll)
        self.scrolled.add_controller(scroll)
        touch = Gtk.GestureDrag(propagation_phase=Gtk.PropagationPhase.CAPTURE,
                                touch_only=True)
        touch.connect('drag-begin', self._on_user_drag)
        self.scrolled.add_controller(touch)
        scrollbar = Gtk.GestureDrag(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        scrollbar.connect('drag-begin', self._on_user_drag)
        self.scrolled.get_vscrollbar().add_controller(scrollbar)
        focus = Gtk.EventControllerFocus()
        focus.connect('enter', self._on_focus_enter)
        focus.connect('leave', self._on_focus_leave)
        self.list_view.add_controller(focus)
        # The sheet is laid out at its closed size until a frame or two after it opens (and
        # the window may be resized): a line brought into view in the old page is brought
        # into view again when the page changes.
        self.scrolled.get_vadjustment().connect('changed', self._on_adjustment_changed)
        self.scrolled.get_hadjustment().connect('changed', self._on_width_changed)
        self.add_named(self.scrolled, 'synced')

        self.text_label = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0,
                                    valign=Gtk.Align.START, selectable=True,
                                    margin_start=12, margin_end=12, margin_top=6,
                                    margin_bottom=24)
        self.text_label.add_css_class('lyrics-text')
        self.text_label.update_property([Gtk.AccessibleProperty.LABEL], [_('Lyrics')])
        self.text_scrolled = Gtk.ScrolledWindow(child=self.text_label,
                                                hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.add_named(self.text_scrolled, 'text')

    def set_player(self, player, app):
        self._player = player
        self._app = app
        player.connect('notify::lyrics', lambda *_: self._on_lyrics())
        player.connect('notify::lyrics-loading', lambda *_: self._update_page())
        player.connect('notify::track', lambda *_: self._update_page())
        player.connect('notify::position', lambda *_: self._follow())
        player.connect('notify::state', lambda *_: self._follow())
        for key in SETTINGS:
            app.settings.connect(f'changed::{key}', lambda *_: self._on_shown_changed())
        self._shown = shown(app.settings)
        self._on_lyrics()

    def set_active(self, active):
        """Follow playback (scroll to the current line) only while shown."""
        self._active = active
        if active:
            self._user_scrolled_at = 0.0
            self._follow(force=True)
        else:
            self._disarm_next_line()

    # -- the lyrics --------------------------------------------------------------------

    def _on_lyrics(self):
        lyrics = self._player.lyrics
        if lyrics is not self._lyrics:
            self._lyrics = lyrics
            self._current = -1
            self._disarm_next_line()
            self._stop_centring()
            self._stop_animation()  # a glide still running would scroll the new song's list
            self.list_view.set_model(
                Gtk.NoSelection(model=lyrics.lines if lyrics is not None and lyrics.synced
                                else None))
            self.text_label.set_markup(text_markup(lyrics, self._shown))
            self.scrolled.get_vadjustment().set_value(0)
            self.text_scrolled.get_vadjustment().set_value(0)
        self._update_page()
        self._follow(force=True)

    def _on_shown_changed(self):
        """Show or hide the pronunciations and translations of the rows on screen (the rest
        follow as they are bound) and in the text; the current line, taller or shorter
        now, is brought into view again."""
        self._shown = shown(self._app.settings)
        for box in self._rows.values():
            _show_parts(box, self._shown)
        if self._lyrics is not None:
            self.text_label.set_markup(text_markup(self._lyrics, self._shown))
        self._follow(force=True)

    def _update_page(self):
        """The page for what there is: the synced list, the text, the spinner while the
        engine reads, else the status page, which says what it can: with nothing playing
        that lyrics appear here, for a song without them that there are none."""
        lyrics = self._lyrics
        if lyrics is not None and lyrics.synced:
            self.set_visible_child_name('synced')
        elif lyrics is not None:
            self.set_visible_child_name('text')
        elif self._player is not None and self._player.lyrics_loading:
            self.set_visible_child_name('loading')
        else:
            if self._player is None or self._player.track is None:
                self.empty_page.set_title(_('Lyrics'))
                self.empty_page.set_description(_('Lyrics for the song playing appear here'))
            else:
                self.empty_page.set_title(_('No Lyrics'))
                self.empty_page.set_description(_('No lyrics are available for this song'))
            self.set_visible_child_name('empty')

    # -- the current line --------------------------------------------------------------

    def _follow(self, force=False):
        """Mark the line current at the Player's position and bring it into view when it
        changed (or `force`: the lyrics or the sheet's state changed); then wait for the
        next line's start."""
        lyrics = self._lyrics
        if lyrics is None or not lyrics.synced or self._player is None:
            return
        index = lyrics.index_at(self._player.estimated_position())
        if index != self._current or force:
            previous, self._current = self._current, index
            self._style(previous)
            self._style(index)
            if self._active:
                self._bring_into_view(index)
        self._arm_next_line()

    def _arm_next_line(self):
        """One timeout for the moment the next line starts, while the tab is shown and the
        music plays (the position events alone are up to a second late); it replaces any
        pending one, and the next position or state event arms it again."""
        self._disarm_next_line()
        lyrics = self._lyrics
        player = self._player
        if (not self._active or lyrics is None or not lyrics.synced or player is None
                or player.state != 'playing' or self._current + 1 >= len(lyrics)):
            return
        delay = lyrics.start_of(self._current + 1) - player.estimated_position()
        self._next_line_source = GLib.timeout_add(
            int(max(delay, NEXT_LINE_FLOOR) * 1000), self._on_next_line)

    def _on_next_line(self):
        self._next_line_source = 0
        self._follow()
        return GLib.SOURCE_REMOVE

    def _disarm_next_line(self):
        if self._next_line_source:
            GLib.source_remove(self._next_line_source)
            self._next_line_source = 0

    def _style(self, position):
        box = self._rows.get(position)
        if box is not None:
            _set_current(box, position == self._current)

    def _users_turn(self):
        """Whether the list is the user's for now: scrolled in the last USER_SCROLL_PAUSE
        seconds, or the focus on a line."""
        return (self._keyboard_in_list
                or time.monotonic() - self._user_scrolled_at < USER_SCROLL_PAUSE)

    def _bring_into_view(self, index):
        """scroll_to the line's row (a no-op when it is on screen), then centre it once
        its geometry holds still: the sheet's opening, and the list's own layout, take a
        few frames, during which a row's bounds are what an earlier layout left. Before the
        first line (an intro, the song restarted), the top."""
        if self._users_turn():
            return
        if index < 0:
            self._stop_centring()
            self._glide_to(self.scrolled.get_vadjustment().get_lower())
            return
        self._page_seen = round(self.scrolled.get_vadjustment().get_page_size())
        self.list_view.scroll_to(index, Gtk.ListScrollFlags.NONE, None)
        self._centre_pending = index
        self._tick_geometry = None
        self._tick_frames = 0
        if self._tick is None:
            self._tick = self.list_view.add_tick_callback(self._on_tick)

    def _on_tick(self, _widget, _clock):
        index = self._centre_pending
        if index is None or index != self._current:
            return self._stop_centring()
        box = self._rows.get(index)
        geometry = self._geometry(box) if box is not None and box.get_mapped() else None
        self._tick_frames += 1
        if geometry is not None and geometry == self._tick_geometry:
            log.debug('lyrics: line %d held still after %d frames: centring', index,
                      self._tick_frames)
            self._centre(box, geometry)
            return self._stop_centring()
        self._tick_geometry = geometry
        if self._tick_frames > SETTLE_FRAMES:
            adjustment = self.scrolled.get_vadjustment()
            log.debug('lyrics: line %d never held still; giving up (rows %s, value %.0f, '
                      'page %.0f, upper %.0f, list %d high)', index, sorted(self._rows),
                      adjustment.get_value(), adjustment.get_page_size(),
                      adjustment.get_upper(), self.list_view.get_height())
            return self._stop_centring()
        return GLib.SOURCE_CONTINUE

    def _on_adjustment_changed(self, adjustment):
        page = round(adjustment.get_page_size())
        if self._active and self._current >= 0 and page > 0 and page != self._page_seen:
            log.debug('lyrics: the page is %d now (was %s): line %d brought into view again',
                      page, self._page_seen, self._current)
            self._page_seen = page
            # Not from inside the list's allocation, where this signal comes from: a
            # scroll_to asked for there is lost.
            GLib.idle_add(self._bring_current_into_view)

    def _on_width_changed(self, adjustment):
        """The list's width changed: a duet's rows take a new margin, set from an idle (the
        signal comes from inside the list's allocation)."""
        width = round(adjustment.get_page_size())
        if width != self._width:
            self._width = width
            if not self._inset_source:
                self._inset_source = GLib.idle_add(self._update_inset)

    def _update_inset(self):
        self._inset_source = 0
        inset = self._width - duet_measure(self._width)
        if inset != self._inset:
            self._inset = inset
            if self._lyrics is not None and self._lyrics.duet:
                for box in self._rows.values():
                    set_side(box, box.side, inset)
                # The rows wrap anew: the current line, taller or shorter, is centred again.
                self._bring_current_into_view()
        return GLib.SOURCE_REMOVE

    def _bring_current_into_view(self):
        if self._active and self._current >= 0:
            self._bring_into_view(self._current)
        return GLib.SOURCE_REMOVE

    def _stop_centring(self):
        self._centre_pending = None
        if self._tick is not None:
            self.list_view.remove_tick_callback(self._tick)
            self._tick = None
        return GLib.SOURCE_REMOVE

    def _geometry(self, box):
        """(row y, row height, page, upper) for the row holding `box`, in the list's
        coordinates, or None while it has no place yet."""
        row = box.get_parent() or box
        ok, bounds = row.compute_bounds(self.list_view)
        adjustment = self.scrolled.get_vadjustment()
        page = adjustment.get_page_size()
        if not ok or bounds.get_height() <= 0 or page <= 0:
            return None
        return (round(bounds.get_y()), round(bounds.get_height()), round(page),
                round(adjustment.get_upper()))

    def _centre(self, box, geometry):
        """Glide the scrolled window so the row holding `box` sits in the middle."""
        y, height, page, upper = geometry
        self._page_seen = page
        adjustment = self.scrolled.get_vadjustment()
        target = adjustment.get_value() + y + height / 2 - page / 2
        target = max(adjustment.get_lower(), min(target, upper - page))
        log.debug('lyrics: centre row at y %d h %d: value %.0f -> %.0f (page %d, upper %d; '
                  'list %d, scrolled %d, stack %d high)', y, height, adjustment.get_value(),
                  target, page, upper, self.list_view.get_height(), self.scrolled.get_height(),
                  self.get_height())
        self._glide_to(target)

    def _glide_to(self, target):
        """Glide the list's scrolled window to `target` (from wherever a glide under way
        has got it)."""
        adjustment = self.scrolled.get_vadjustment()
        self._stop_animation()
        if abs(target - adjustment.get_value()) < 1:
            return
        animation = Adw.TimedAnimation(
            widget=self.scrolled, value_from=adjustment.get_value(), value_to=target,
            duration=CENTRE_DURATION, easing=Adw.Easing.EASE_OUT_CUBIC,
            target=Adw.PropertyAnimationTarget.new(adjustment, 'value'))
        self._animation = animation
        animation.play()

    def _stop_animation(self):
        """Leave the list where a glide has got it (skip() would jump to the glide's end)."""
        if self._animation is not None:
            self._animation.pause()
            self._animation = None

    def _on_user_scroll(self, _controller, _dx, _dy):
        self._user_took_over()
        return False

    def _on_user_drag(self, _gesture, _x, _y):
        self._user_took_over()

    def _user_took_over(self):
        self._user_scrolled_at = time.monotonic()
        self._stop_animation()
        self._stop_centring()

    def _on_focus_enter(self, _controller):
        self._keyboard_in_list = True
        self._stop_animation()
        self._stop_centring()

    def _on_focus_leave(self, _controller):
        self._keyboard_in_list = False

    # -- the list -----------------------------------------------------------------------

    def _on_setup(self, _factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class('lyric-line')
        box.side, box.inset = '', 0     # as set_side() left them: across the list
        for part in PARTS:
            label = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0,
                              justify=Gtk.Justification.LEFT, visible=False,
                              css_classes=part.css_classes)
            setattr(box, part.attribute, label)
            box.append(label)
        list_item.set_child(box)

    def _on_bind(self, _factory, list_item):
        position = list_item.get_position()
        box = list_item.get_child()
        line = list_item.get_item()
        for part in PARTS:
            getattr(box, part.attribute).set_label(getattr(line, part.field))
        _show_parts(box, self._shown)
        set_side(box, line.side, self._inset)
        list_item.set_accessible_label(spoken(line))
        # A gap before a verse or a chorus, as in the text: the box's margin, outside the
        # highlight the box draws for its row (style.css).
        if line.stanza and position:
            box.add_css_class('stanza')
        else:
            box.remove_css_class('stanza')
        self._rows[position] = box
        _set_current(box, position == self._current)

    def _on_unbind(self, _factory, list_item):
        position = list_item.get_position()
        if self._rows.get(position) is list_item.get_child():
            del self._rows[position]

    def _on_activate(self, _list_view, position):
        """A click on a line (or Enter on it) seeks to where it starts, and the list
        follows again from there."""
        if self._lyrics is None or self._player is None or self._player.track is None:
            return
        self._user_scrolled_at = 0.0
        self._keyboard_in_list = False  # until the focus leaves and comes back
        self._app.player_command(self._player.seek(self._lyrics.start_of(position)))


# What the lines show besides their vocals, and the settings that say so.
Shown = namedtuple('Shown', 'pronunciations translations')
SETTINGS = ('lyrics-pronunciations', 'lyrics-translations')

# The parts of a line a row shows, top to bottom (Apple's order): the box's attribute for
# the part's label, the LyricLine field it shows, the label's CSS classes, the Shown field
# that has to be on for it (None: shown whenever it has text), and its line in the
# unsynced text's markup.
Part = namedtuple('Part', 'attribute field css_classes setting markup')
_EXTRA = '<span size="smaller" alpha="70%">{}</span>'
_BACKGROUND = '<span size="90%" alpha="70%">{}</span>'
_BACKGROUND_EXTRA = '<span size="80%" alpha="60%">{}</span>'
PARTS = (
    Part('label', 'text', ['title-3'], None, '{}'),
    Part('pronunciation', 'pronunciation', ['lyric-pronunciation'], 'pronunciations', _EXTRA),
    Part('translation', 'translation', ['lyric-translation'], 'translations', _EXTRA),
    Part('background', 'background', ['lyric-background'], None, _BACKGROUND),
    Part('pronunciation_background', 'pronunciation_background',
         ['lyric-background', 'lyric-pronunciation'], 'pronunciations', _BACKGROUND_EXTRA),
    Part('translation_background', 'translation_background',
         ['lyric-background', 'lyric-translation'], 'translations', _BACKGROUND_EXTRA),
)


# Where a row's box goes for each side of a duet (lyrics.side(); '' for the lines of a song
# that is not one): its labels' xalign and justification, and the share of the row's inset
# its start margin takes (its end margin has the rest). GTK mirrors all of them in a
# right-to-left layout.
Side = namedtuple('Side', 'xalign justify start')
SIDES = {
    '': Side(0.0, Gtk.Justification.LEFT, 0.0),
    lyrics_model.START: Side(0.0, Gtk.Justification.LEFT, 0.0),
    lyrics_model.END: Side(1.0, Gtk.Justification.RIGHT, 1.0),
    lyrics_model.MIDDLE: Side(0.5, Gtk.Justification.CENTER, 0.5),
}


def duet_measure(width):
    """How wide a duet's row is in a list `width` px wide: DUET_SHARE of it, or
    DUET_MIN_WIDTH where that share would be narrower (a narrow window), never more than the
    list."""
    return min(width, max(round(width * DUET_SHARE), DUET_MIN_WIDTH))


def set_side(box, side, inset):
    """Put a row's box on `side` (a duet's line's, lyrics.side(); '' across the list) with
    `inset` px of the list's width left beside it: every label aligned to the side, the
    margin on the other side (both halves for the middle). A row bound again loses its
    previous line's side. Cheap when nothing changes: a row keeps what it was given."""
    if not side:
        inset = 0
    if box.side == side and box.inset == inset:
        return
    box.side, box.inset = side, inset
    xalign, justify, start = SIDES[side]
    for part in PARTS:
        label = getattr(box, part.attribute)
        label.set_xalign(xalign)
        label.set_justify(justify)
    start = int(inset * start)
    box.set_margin_start(start)
    box.set_margin_end(inset - start)


def shown(settings):
    return Shown(*(settings.get_boolean(key) for key in SETTINGS))


def _wanted(part, extras):
    return part.setting is None or getattr(extras, part.setting)


def spoken(line):
    """What a screen reader says for a row: the main vocals, then the background vocals."""
    if line.text and line.background:
        return f'{line.text} {line.background}'
    return line.text or line.background


def text_markup(lyrics, extras):
    """The unsynced view's text as Pango markup: the lines one to a line, a blank line
    before each stanza, and under each line its parts as the synced rows stack them (the
    background vocals smaller and fainter; the pronunciations and translations, as
    `extras`, a Shown, asks, smaller still); '' for no lyrics. With no extras it reads as
    Lyrics.text."""
    if lyrics is None:
        return ''
    texts = []
    for index, line in enumerate(lyrics.lines):
        if line.stanza and index:
            texts.append('')
        for part in PARTS:
            text = getattr(line, part.field)
            if text and _wanted(part, extras):
                texts.append(part.markup.format(GLib.markup_escape_text(text)))
    return '\n'.join(texts)


def _show_parts(box, extras):
    """Show the row's labels that have text and that `extras` asks for."""
    for part in PARTS:
        label = getattr(box, part.attribute)
        label.set_visible(bool(label.get_label()) and _wanted(part, extras))


def _set_current(box, current):
    if current:
        box.add_css_class('current')
        box.remove_css_class('dimmed')
    else:
        box.remove_css_class('current')
        box.add_css_class('dimmed')
