import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretary import library_location
from secretary.core import Archive
from secretary.local_backups import Backups
from secretary.server import Service


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

    def test_preflight_checks_size_space_and_destination_without_scheduling(self):
        self.archive.add('Memory', 'Original bytes', filename='original.txt', data=b'original')
        result = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertGreater(result['estimated_bytes'], len(b'original'))
        self.assertGreater(result['free_bytes'], 0)
        self.assertEqual((result['empty'], result['writable']), (True, True))
        self.assertFalse(list(self.target.iterdir()))
        self.assertFalse(self.preference.exists())

        (self.root/'updates').mkdir()
        (self.root/'updates'/'installer').write_bytes(b'x'*1024)
        (self.target/'existing').touch()
        nonempty = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertEqual(nonempty['estimated_bytes'], result['estimated_bytes'])
        self.assertFalse(nonempty['empty'])
        self.assertTrue(nonempty['error'])
        (self.target/'existing').unlink()

        with patch.object(library_location.tempfile, 'TemporaryFile', side_effect=PermissionError):
            unwritable = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertFalse(unwritable['writable'])
        self.assertTrue(unwritable['error'])

        disk = type('Disk', (), {'free': 0})()
        with patch.object(library_location.shutil, 'disk_usage', return_value=disk):
            full = library_location.preflight(self.root, str(self.target), self.backups.folder)
            self.assertEqual(full['free_bytes'], 0)
            with self.assertRaisesRegex(ValueError, '空间不足'):
                library_location.schedule(self.root, str(self.target), self.backups.folder)
        self.assertTrue(full['error'])
        self.assertFalse(self.preference.exists())

    def test_restart_admission_checks_pending_destination_and_active_work(self):
        service = Service(self.root)
        self.addCleanup(service.close)
        service.restart_supported = True
        library_location.schedule(self.root, str(self.target), service.backups.folder)
        self.assertTrue(service.enter_post())
        with self.assertRaisesRegex(ValueError, '目录已更改'):
            service.request_library_restart(str(self.backup))
        with patch.object(service, 'runtime', return_value={'processing': 1}):
            with self.assertRaisesRegex(ValueError, '等待当前任务'):
                service.request_library_restart(str(self.target))
        with patch('secretary.server.updater.status', return_value={'phase': 'installing'}):
            with self.assertRaisesRegex(ValueError, '等待当前任务'):
                service.request_library_restart(str(self.target))
        self.assertTrue(service.enter_post())
        with self.assertRaisesRegex(ValueError, '等待当前任务'):
            service.request_library_restart(str(self.target))
        service.leave_post()
        with patch('secretary.server.updater.status', return_value={'phase': 'idle'}):
            service.request_library_restart(str(self.target))
        self.assertFalse(service.enter_post())
        self.assertTrue(service.backups.stop.is_set())
        service.leave_post()
