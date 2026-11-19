import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretary import library_location
from secretary.core import Archive
from secretary.local_backups import Backups


class LibraryLocationTest(unittest.TestCase):
    def setUp(self):
        work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.preference = work/'settings'/'library-location.json'
        self.enterContext(patch.object(library_location, 'preference_file', return_value=self.preference))
        self.root, self.target, self.backup = (work/name for name in ('library', 'new library', 'backup'))
        self.target.mkdir()
        self.archive = Archive(self.root)
        self.backups = Backups(self.archive)

    def test_move_preserves_archive_and_independent_backup_location(self):
        item, _ = self.archive.add('Memory', 'A saved memory', filename='original.txt', data=b'original')
        (self.root/'conversations.json').write_text('[]')
        old = self.backups.create()
        self.backups.configure({'folder':str(self.backup)})
        self.assertEqual(library_location.schedule(self.root, str(self.target), self.backups.folder)['pending'], str(self.target))
        self.archive.update(item, title='Edited before restart')

        with library_location.lease(self.root):
            self.assertEqual(library_location.migrate(self.root, library_location.read()), self.target)

        preference = library_location.read()
        self.assertEqual(library_location.selected(preference, None), self.target)
        self.assertEqual(library_location.selected(preference, str(self.root)), self.target)
        self.assertEqual(library_location.selected(preference, str(self.root.parent/'separate')), self.root.parent/'separate')
        self.assertEqual(library_location.status(self.target), {})
        moved = Archive(self.target)
        self.assertEqual(moved.get(item)['title'], 'Edited before restart')
        self.assertEqual((self.target/'files'/item).read_bytes(), b'original')
        self.assertEqual((self.target/'conversations.json').read_text(), '[]')
        self.assertTrue((self.root/'files'/item).exists())
        self.assertFalse((self.target/'local-backups').exists())
        moved_backups = Backups(moved)
        self.assertEqual(moved_backups.folder, self.backups.folder)
        self.assertIn(old['id'], {entry['id'] for entry in moved_backups.entries()})
        moved_backups.restore(old['id'])
        self.assertEqual(moved.get(item)['title'], 'Memory')

    def test_unavailable_destination_keeps_original_and_can_cancel(self):
        library_location.schedule(self.root, str(self.target), self.backups.folder)
        self.target.rmdir()
        self.assertEqual(library_location.migrate(self.root, library_location.read()), self.root)
        self.assertTrue(library_location.status(self.root)['error'])
        self.assertFalse(self.target.exists())
        self.assertEqual(library_location.schedule(self.root, '', self.backups.folder), {})

    def test_migration_rejects_nonempty_and_overlapping_locations(self):
        self.backups.configure({'folder':str(self.target)})
        with self.assertRaises(ValueError):
            library_location.schedule(self.root, str(self.target), self.backups.folder)
        (self.backup/'existing').mkdir(parents=True)
        with self.assertRaises(ValueError):
            library_location.schedule(self.root, str(self.backup), self.backups.default)
        self.assertFalse(self.preference.exists())
