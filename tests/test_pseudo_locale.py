# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""scripts/pseudo_locale.py: the pseudo-translations keep what a translation must keep
(placeholders, date formats, mnemonics), change every word, and compile."""

import gettext
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest

from tests import ROOT

SCRIPT = ROOT / 'scripts' / 'pseudo_locale.py'

TEMPLATE = r"""# A header comment
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\n"

#. Translators: a comment
#: src/a.py:1
msgid "Add to Pla_ylist"
msgstr ""

#: src/a.py:2
#, python-brace-format
msgid "{count} song"
msgid_plural "{count} songs"
msgstr[0] ""
msgstr[1] ""

#: src/a.py:3
msgctxt "release date"
msgid "%-d %b %Y"
msgstr ""

#: src/a.py:4
msgid ""
"A long sentence, "
"over two \"lines\""
msgstr ""

#: src/a.py:5
msgid "translator-credits"
msgstr ""
"""


def load():
    spec = importlib.util.spec_from_file_location('pseudo_locale', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PseudoLocaleTest(unittest.TestCase):
    def setUp(self):
        self.pseudo = load()

    def test_the_template_is_read(self):
        self.assertEqual(self.pseudo.entries(TEMPLATE), [
            {'msgid': 'Add to Pla_ylist'},
            {'msgid': '{count} song', 'msgid_plural': '{count} songs'},
            {'msgctxt': 'release date', 'msgid': '%-d %b %Y'},
            {'msgid': 'A long sentence, over two "lines"'},
            {'msgid': 'translator-credits'},
        ])

    def test_accented_keeps_what_a_translation_keeps(self):
        accented = self.pseudo.accented
        self.assertEqual(accented('Add to Pla_ylist'), '⟦Àđđ ţö Þļà_ýļîšţ ~~~~⟧')
        text = accented('Removed {count} songs from “{playlist}”')
        self.assertIn('{count}', text)
        self.assertIn('{playlist}', text)
        self.assertNotIn('songs', text)
        self.assertGreaterEqual(len(text), len('Removed {count} songs from “{playlist}”') * 1.3)
        for unchanged in ('%-d %b %Y', ', ', '{percent}%', '{outer} › {inner}'):
            self.assertEqual(accented(unchanged), unchanged)

    def test_mirrored_overrides_the_words_only(self):
        mirrored = self.pseudo.mirrored
        self.assertEqual(mirrored('{count} songs'), '‏{count}‮ songs‬')
        self.assertEqual(mirrored('%-d %B'), '%-d %B')

    def test_the_catalogues_compile_and_translate(self):
        if shutil.which('msgfmt') is None:
            self.skipTest('msgfmt is not installed')
        messages = self.pseudo.entries(TEMPLATE)
        with tempfile.TemporaryDirectory() as directory:
            for language, transform in self.pseudo.TRANSFORMS.items():
                po = os.path.join(directory, language + '.po')
                with open(po, 'w', encoding='utf-8') as file:
                    file.write(self.pseudo.catalogue(messages, transform, language))
                mo = os.path.join(directory, language + '.mo')
                subprocess.run(['msgfmt', '--check', '-o', mo, po], check=True)
                with open(mo, 'rb') as file:
                    translations = gettext.GNUTranslations(file)
                self.assertEqual(translations.ngettext('{count} song', '{count} songs', 3),
                                 transform('{count} songs'))
                self.assertEqual(translations.pgettext('release date', '%-d %b %Y'),
                                 '%-d %b %Y')
                self.assertEqual(translations.gettext('translator-credits'),
                                 'translator-credits')  # left untranslated


if __name__ == '__main__':
    unittest.main()
