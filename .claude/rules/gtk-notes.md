---
paths:
  - "src/**/*.blp"
  - "src/window.py"
  - "src/pages/**"
  - "src/widgets/**"
  - "src/dialogs/**"
  - "src/player_bar.py"
  - "src/main.py"
---

# GTK 4.22, libadwaita 1.9 and PyGObject 3.56: behaviour this code depends on

Each of these was checked against the toolkit (or found the hard way). The sidebar's are in
`sidebar.md`; measurements are in docs/notes.md.

## Lists and grids

- A `Gtk.GridView` recycles only as the direct scrollable child of a `Gtk.ScrolledWindow`
  (hence the grid page's title is an overlay over the grid's top padding). After a sort change
  it follows its old top item: `scroll_to(0, …)`.
- A `Gtk.ListView` gives each row its minimum height. Tab never reaches focusable widgets in a
  `header-factory` header, only in items, so a page's hero is its list's first item. A
  `Gtk.FlattenListModel` is a `Gtk.SectionModel` (one section per child model).
- CSS padding on a `Gtk.ListView` scrolls with its rows and lies outside the adjustment's page:
  when geometry is computed from the list, pad with margins around it instead. A `scroll_to`
  asked from inside the adjustment's `changed` handler is lost: defer it to an idle.
- `Gtk.ColumnView.sort_by_column()` leaves the previous column's sort arrow; use it for the
  initial order only, or call `sort_by_column(None, …)` first.
- A `Gtk.StringFilter` over `Gtk.ClosureExpression.new(str, lambda item: item.search_key, None)`
  filters tens of thousands of items in one pass (fold the text first, `ignore-case: false`).
  With no search it matches everything without reading an item; a longer search refilters
  only what matched.
- `Gtk.ListView.scroll_to(position, FOCUS)` focuses the row only when the focus is in the
  list already; from elsewhere (a header bar, an entry, the sidebar) it only moves the list's
  own focus there, and `list_view.grab_focus()` then focuses that row
  (`widgets.util.focus_position()`). The view's grab alone focuses the widget it last
  focused, which a model change may have recycled for another item, out of view.
- `Gtk.Editable.set_text()` empties the entry before it inserts, and a `Gtk.SearchEntry`
  emits `search-changed` at once for an empty text: replacing a filter's text refilters
  twice (everything, then the text). Typing inserts and deletes, which waits for the delay.
- A `Gtk.ListView` keeps its focused row's widget alive, unmapped (not child-visible), once
  it has scrolled away from it, and Tab back into the list focuses that widget: the keys
  then reach nothing (GTK delivers them to the list). `LyricsView` moves the focus to the
  current line when it finds it there.
- A `Gtk.SliceListModel` whose `offset` plus `size` passes `G_MAXUINT` wraps its end and
  ignores changes after it, or reports them wrongly (a `Gtk.ListView` over it has crashed):
  "the rest from N" is `size = GLib.MAXUINT32 - N`, set again whenever the offset changes.
- Sections over one list: a small Python `Gtk.SectionModel` (`GObject.Object, Gio.ListModel,
  Gtk.SectionModel`, its `do_get_section` answering `(start, end)`, `sections_changed()` when
  they move, never with a range past the items) passes its model's items through untouched.
  Two slices of one store in a `Gtk.FlattenListModel` give sections too, but moving their
  bound moves items between the parts: their rows are built again and the list's focus item
  can land on the last row (`widgets.queue.QueueSections`, docs/notes.md). The list binds a
  header again only when its section's start or end moves, not on `sections_changed()` alone:
  a header that depends on anything else is titled again by its view (`QueueView._headers`).

## Layout and widgets

- A Python `do_map` or `do_unmap` that raises leaves GTK a widget in a state it cannot leave:
  an exception before `do_unmap` chains up keeps the widget mapped, and unrealizing it then
  aborts the process (`Gtk:ERROR … gtk_widget_real_unrealize: assertion failed (!priv->mapped)`),
  so what these vfuncs reach for has to be there whether or not a page has an application.
- A Python `do_measure` on a widget with a layout manager (an `Adw.Bin`) is never called: set
  the layout manager to None and implement both `do_measure` and `do_size_allocate`.
- A `Gtk.Overlay` gives an overlay child its natural size, and a `Gtk.Picture`'s natural size is
  its image's: give the picture an overlay whose main child is a sized placeholder. An
  overlay child with `layout { measure: true; }` counts in the overlay's size, so the
  overlay is as tall as the taller of it and the main child, and as that child alone while
  the main child is hidden (the artist page's hero over its banner).
- A `Gtk.Stack` that holds the focus moves it into the child it switches to at once, before
  a layout: a `Gtk.ScrolledWindow` there whose lists have no rows yet (they come at the
  layout) takes the focus itself, where no key reaches a row (`ShelvesPage._focus_shelves`
  moves it on a frame later).
- A `Gtk.Stack` will not switch to a child that is not visible. `Gtk.Inscription`'s CSS name is
  `label`.
- Several `Adw.Breakpoint`s: only the last matching one applies, so the window's narrower one
  (600sp) repeats the wider one's (640sp) setters, and each width band's short variant
  (`max-height: 880sp`, 640sp for the wide one) repeats its band's (playback.md). A
  navigation page takes no breakpoints: put an `Adw.BreakpointBin` inside it.
- libadwaita's `.card` sets its own `color`, so a card placeholder on a coloured background
  needs `color: inherit`; `--card-bg-color` is white in the light theme.
- `Adw.BottomSheet`: the bottom bar is laid over the content (window.blp binds the content's
  `margin-bottom` to `bottom-bar-height`, which is 0 while the sheet is open). With `can-open`
  the bar is wrapped in a focusable `Gtk.Button`, which the player bar names. The sheet gets its
  child's natural height (clamped to the window), so a full-height sheet asks for a tall one;
  the child is laid out while closed and keeps that size briefly after opening, so wait for the
  adjustment's `changed`. Opening focuses its first focusable widget; closing restores focus.
- `Gtk.Window.fullscreen()` keeps the window's `default-size` and `is_maximized()` as they
  were (so the state saved while full screen is the normal one). The headless mutter makes
  a non-resizable window (the scripts' harness) full screen in name only, at its size.
  `AdwToastOverlay` takes Escape while a toast shows.
- `Adw.NavigationView` pops on Escape, Back, Alt+Left (local shortcuts: only with the focus
  inside it) and the mouse back button; a push moves the focus into the new page. `win.back`
  covers the rest. A push maps, unmaps and maps the pushed page again: stop a page's requests
  in `do_hidden` (after it has really gone), not in `do_unmap`.
- An `Adw.Dialog` over a window that is neither maximized nor tiled is a separate
  `Gtk.Window` transient for it: its widgets find no `app.*` actions (Preferences inserts the
  `app` group itself), `get_active_window()` stays the main window, `get_visible_dialog()` does
  not see it (use `Gtk.Window.list_toplevels()`), and a screenshot of the window misses it.
- An actionable widget's sensitivity is its action's: `set_sensitive(False)` on a row with an
  `action-name` is undone.
- A callback GtkBuilder connected (`clicked => $on_x()`) is not found by
  `handler_block_by_func`: use a flag. `Gtk.SearchEntry.grab_focus()` focuses its inner
  `Gtk.Text`. An `Adw.ToggleGroup`'s `active-name` is the toggle's `name`.

## Menus, drags, clipboard

- Context menu controllers go on the view, not the recycled tiles, in the capture phase and
  claimed, so the item's own click gesture never sees them. A popover can be parented to any
  widget with a layout manager; unparent it from an idle after `closed`, because the chosen
  item's action runs after the popover closes and finds `win.*` through its parent.
- The one drag type is `library.ItemRefs` (one or more library objects, in order), offered
  with `Gdk.ContentProvider.new_for_value(refs)` through `widgets/dnd.py`. Only in-app drags
  are taken: a drop target decides from `dnd.current()`, the ItemRefs its source made at
  `drag-begin`, since GTK loads a drop's value only asynchronously and AdwSidebar's
  `drop-enter` gets nothing but the item's index. Every drag source goes through
  `dnd.attach_source()`, every drop target's look and auto-scroll through `dnd.DropFeedback`
  (`.drop-highlight`, `.drop-before`/`.drop-after`: inset shadows, never a margin). A
  `Gtk.DragSource` in the capture phase on a container sees the press before its rows'
  click gestures and cancels them once the drag starts. GDK's drag and drop events carry no
  modifier state of their own; Shift held makes the drop's action MOVE where the source
  offers COPY too (GTK chooses so under X11, mutter under Wayland), which
  `dnd.shift_held()` reads with the keyboard's own state. A target's `enter`/`motion`
  must answer one of the drop's own actions (`dnd.choose_action()`): a sidebar row's drag
  offers MOVE alone. `Gtk.DragSource`'s `prepare` can be
  emitted from a test (no event device then). `Gdk.Clipboard.set(text)` works from Python (it
  is `set_value`).
- A `Gtk.PopoverMenu` (sliding, the default) keeps each submenu as a page of one
  `GtkStack` named by the submenu's label, mnemonic underscore and all, and a submenu's
  item opens the page of that name: two submenus of one label share the first's page
  (`duplicate child name in GtkStack`), and one labelled `main` is the menu's own. Nothing
  names a page otherwise (4.20 to 4.22), so a menu has no submenu labelled with a name of
  the user's: its folders are headed sections (a section's label, plain text, no
  mnemonic), docs/decisions.md.
- A `Gio.MenuItem` with the attribute `hidden-when` = `action-disabled` is shown by a
  `Gtk.PopoverMenu` only while its action is enabled, and follows the action's state while
  the menu is open (Favourite / Remove from Favourites, as Nautilus's Star / Unstar).

## PyGObject and asyncio

- Python 3.14 deprecates `asyncio.set_event_loop_policy` (removal in 3.16), but it is still how
  PyGObject 3.56 puts asyncio on the GLib loop; `main.use_glib_event_loop()` filters the warning.
  `Gio.Application.run` marks the GLib loop as asyncio's running loop only with that policy set.
- Gio's `*_async` methods (`Gio.Subprocess.wait_async`, `Gio.InputStream.read_bytes_async`,
  `Gio.File.load_contents_async`) are awaitable on this loop.
