# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Jack Tully

"""po/: every catalogue is listed in LINGUAS and compiles under `msgfmt --check`, and en_US's
loads and gives the app its American words, a message it lacks falling back to the source
(so a string added since the catalogue was last updated fails nothing)."""

import gettext
import locale
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import ROOT

from applemusic import i18n

PO = ROOT / 'po'


def catalogues():
    return sorted(PO.glob('*.po'))


class CatalogueTest(unittest.TestCase):
    def test_linguas_lists_every_catalogue(self):
        listed = []
        for line in (PO / 'LINGUAS').read_text(encoding='utf-8').splitlines():
            if not line.startswith('#'):
                listed.extend(line.split())
        self.assertEqual(sorted(listed), [path.stem for path in catalogues()])
        self.assertIn('en_US', listed)

    @unittest.skipIf(shutil.which('msgfmt') is None, 'msgfmt is not installed')
    def test_every_catalogue_compiles(self):
        for path in catalogues():
            with self.subTest(path.name):
                done = subprocess.run(['msgfmt', '--check', '-o', os.devnull, str(path)],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipIf(shutil.which('msgfmt') is None, 'msgfmt is not installed')
class AmericanEnglishTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        localedir = pathlib.Path(tmp.name)
        target = localedir / 'en_US' / 'LC_MESSAGES' / f'{i18n.DOMAIN}.mo'
        target.parent.mkdir(parents=True)
        subprocess.run(['msgfmt', '-o', str(target), str(PO / 'en_US.po')], check=True)
        # What setup() changes, put back after (as test_i18n does).
        domain = gettext.textdomain()
        bound = gettext.bindtextdomain(i18n.DOMAIN)
        self.addCleanup(gettext.textdomain, domain)
        self.addCleanup(gettext.bindtextdomain, i18n.DOMAIN, bound)
        if hasattr(locale, 'bindtextdomain'):
            c_domain = locale.textdomain(None)
            c_bound = locale.bindtextdomain(i18n.DOMAIN, None)
            self.addCleanup(locale.textdomain, c_domain)
            self.addCleanup(locale.bindtextdomain, i18n.DOMAIN, c_bound)
        patcher = mock.patch.dict(os.environ, {'LANGUAGE': 'en_US'})
        patcher.start()
        self.addCleanup(patcher.stop)
        i18n.setup(str(localedir))

    def test_the_catalogue_loads_and_translates(self):
        self.assertEqual(gettext.gettext('Favourite Songs'), 'Favorite Songs')
        self.assertEqual(gettext.gettext('_Favourites Only'), '_Favorites Only')
        self.assertEqual(gettext.ngettext('Removed {count} song from Favourite Songs',
                                          'Removed {count} songs from Favourite Songs', 2),
                         'Removed {count} songs from Favorite Songs')
        self.assertEqual(gettext.pgettext('album release date', '%-d %B %Y'), '%B %-d, %Y')

    def test_a_message_it_lacks_is_the_source(self):
        self.assertEqual(gettext.gettext('Home'), 'Home')  # the same in both: untranslated
        self.assertEqual(gettext.gettext('A string added after the catalogue'),
                         'A string added after the catalogue')


if __name__ == '__main__':
    unittest.main()
