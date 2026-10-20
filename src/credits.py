# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""What View Credits (dialogs/credits.py) shows of a song's credits, worked out without GTK.

    sections(answer)        # [(heading, [(name, roles)])]: Engine.credits' answer, worded
    heading('performer', '')            # 'Performers': Apple's title, else the app's own
    roles_text(['Vocals', 'Guitar'])    # 'Vocals, Guitar'

Engine.credits answers {categories: [{kind, title, people: [{name, roles}]}]} in Apple's order
(normalize.song_credits). Apple titles each category in the account's language, so its title
is the heading; one without a title is named by its kind here (the backend writes no words),
and a kind Apple adds later by a word of the app's own. A category with nobody in it is left
out, so no sections means Apple has no credits for the song.
"""

from gettext import gettext as _


def kind_headings():
    """The app's headings for Apple's kinds of credits, translated on call."""
    return {
        'performer': _('Performers'),
        'composer-and-lyrics': _('Composition and Lyrics'),
        'production-and-engineering': _('Production and Engineering'),
    }


def heading(kind, title):
    """The heading over a category of credits: Apple's `title`, else the app's for its
    `kind`, else Other Credits."""
    title = ' '.join(str(title or '').split())
    return title or kind_headings().get(kind) or _('Other Credits')


def roles_text(roles):
    """A person's roles in a song's credits as one line ("Vocals, Guitar"); '' for none."""
    # Translators: between a person's roles in a song's credits ("Vocals, Guitar").
    roles = roles if isinstance(roles, (list, tuple)) else ()
    return _(', ').join(str(role) for role in roles if role)


def sections(answer):
    """The dialog's sections for Engine.credits' answer: [(heading, [(name, roles)])], in
    Apple's order, each category with someone in it."""
    categories = answer.get('categories') if isinstance(answer, dict) else None
    found = []
    for category in categories if isinstance(categories, list) else []:
        if not isinstance(category, dict):
            continue
        people = [(str(person.get('name') or ''), roles_text(person.get('roles')))
                  for person in category.get('people') or () if isinstance(person, dict)]
        people = [(name, roles) for name, roles in people if name]
        if people:
            found.append((heading(category.get('kind'), category.get('title')), people))
    return found
