# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""A Gio.ListStore brought to new contents with the fewest splices, so the views over it keep
their rows and their scroll position."""

import difflib


def apply_diff(store, items, old=None):
    """Bring a Gio.ListStore to hold `items` (objects) in that order with the fewest splices:
    runs of the same objects in the same order are left alone, so a view over the store keeps
    its rows and its scroll position through a reload that changed little. `old` is what the
    store holds, as a list, when the caller has read it already.

    The runs of the same objects at either end are set aside first. In what is left, when
    the objects both lists hold are in the same order in both (nothing moved, as after most
    syncs), one walk finds the runs that went and came, and each is one splice (a whole new
    list is one); only moves need difflib, which takes 45 ms over 40,000 songs where the
    walk takes 8."""
    if old is None:
        old = [store.get_item(position) for position in range(store.get_n_items())]
    start, old_end, new_end = 0, len(old), len(items)
    while start < old_end and start < new_end and old[start] is items[start]:
        start += 1
    while old_end > start and new_end > start and old[old_end - 1] is items[new_end - 1]:
        old_end -= 1
        new_end -= 1
    if start == old_end and start == new_end:
        return
    old_part, new_part = old[start:old_end], items[start:new_end]
    runs = _changed_runs(old_part, new_part)
    if runs is None:  # something moved, or is there twice
        matcher = difflib.SequenceMatcher(None, [id(item) for item in old_part],
                                          [id(item) for item in new_part], autojunk=False)
        runs = [opcode[1:] for opcode in matcher.get_opcodes() if opcode[0] != 'equal']
    for old_from, old_to, new_from, new_to in reversed(runs):
        store.splice(start + old_from, old_to - old_from, new_part[new_from:new_to])


def _changed_runs(old, new):
    """The runs that differ between two lists of objects, as (old from, old to, new from, new
    to) in order, when the objects in both are in the same order in both and none is in
    either twice; else None."""
    positions = {id(item): position for position, item in enumerate(new)}
    if len(positions) != len(new):
        return None
    runs = []
    gone = None  # where the run of old objects not in `new` began
    last = -1  # the new position of the last object in both
    for position, item in enumerate(old):
        found = positions.get(id(item))
        if found is None:
            if gone is None:
                gone = position
            continue
        if found <= last:
            return None
        went = gone if gone is not None else position
        if went < position or last + 1 < found:
            runs.append((went, position, last + 1, found))
        gone, last = None, found
    went = gone if gone is not None else len(old)
    if went < len(old) or last + 1 < len(new):
        runs.append((went, len(old), last + 1, len(new)))
    return runs
