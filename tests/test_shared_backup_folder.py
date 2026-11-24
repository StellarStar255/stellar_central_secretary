import json
import shutil
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from secretary.core import Archive
from secretary.local_backups import Backups
from secretary.server import Service


class SharedBackupTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.service = Service(root/'a')
        self.addCleanup(self.service.close)
        self.a = self.service.backups
        self.b = Backups(Archive(root/'b'))
        for backups in (self.a, self.b):
            backups.configure({'folder':str(root/'shared'), 'other_keep':1})

    def test_copied_libraries_rotate_and_restore_independently(self):
        a = self.a
        item, _ = a.archive.add('Original', 'shared starting point')
        first = a.create()
        a.due()
        clone = a.archive.root.parent/'clone'
        shutil.copytree(a.archive.root, clone)
        b = Backups(Archive(clone))
        self.assertFalse(b.owns(first))
        self.assertIsNone(b.status()['last_success'])
        b.due()
        self.assertNotEqual(a.library_id, b.library_id)
        self.assertEqual(len([e for e in b.entries() if b.owns(e) and e['reason']=='daily']), 1)
        for backups, title in ((b, 'B first'), (a, 'A latest'), (b, 'B latest')):
            backups.archive.update(item, title=title)
            backups.create()
        for original, title in ((b, 'B latest'), (a, 'A latest')):
            reopened = Backups(original.archive)
            self.assertEqual(reopened.library_id, original.library_id)
            latest, = [e for e in reopened.entries() if reopened.owns(e) and e['reason']=='manual']
            reopened.archive.update(item, title='Changed again')
            reopened.restore(latest['id'])
            self.assertEqual(reopened.archive.get(item)['title'], title)

    def test_same_path_and_directory_number_on_another_machine(self):
        first = self.a.create()
        with patch('secretary.backup_identity._machine', return_value='another computer'):
            second = Backups(self.a.archive)
            self.assertFalse(second.owns(first))
            second.create()
            self.assertNotEqual(second.library_id, first['library_id'])
            self.assertEqual(second.verify(first['id'])['verification']['state'], 'verified')

    def test_unbound_legacy_settings_cannot_claim_an_existing_backup(self):
        a = self.a
        first = a.create()
        config = json.loads(a.config_path.read_text())
        del config['library_binding']
        a.config_path.write_text(json.dumps(config))
        reopened = Backups(a.archive)
        reopened.create()
        self.assertFalse(reopened.owns(first))
        self.assertEqual(reopened.verify(first['id'])['verification']['state'], 'verified')

    def test_independent_rotation_daily_schedule_and_cleanup(self):
        a, b = self.a, self.b
        old = a.create()
        foreign = b.create()
        self.assertEqual(len(a.entries()), 2)
        a.due()
        b.due()
        for backups in (a, b):
            reopened = Backups(backups.archive)
            reopened.due()
            daily = [e for e in reopened.entries() if reopened.owns(e) and e['reason']=='daily']
            self.assertEqual(len(daily), 1)
        newest = a.create()
        self.assertFalse((a.folder/(old['id']+'.zip')).exists())
        a.limit = newest['size']
        a._prune(newest['id'])
        self.assertEqual(b.verify(foreign['id'])['verification']['state'], 'verified')
        self.assertFalse(self.service.storage.preview()['items'])

    def test_failed_rotation_and_index_recovery_preserve_other_library(self):
        a, b = self.a, self.b
        for backups in (a, b):
            key, _ = backups.archive.add('file', '', filename='file.txt', data=b'original')
            (backups.archive.root/'files'/key).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                backups.create()
        self.assertEqual(len(a.entries()), 2)
        with self.assertRaises(ValueError):
            a.create()
        foreign, = [e for e in a.entries() if b.owns(e)]
        self.assertEqual(foreign['verification']['state'], 'failed')
        (b.archive.root/'files'/key).write_bytes(b'original')
        saved = b.create()
        (b.folder/(saved['id']+'.json')).unlink()
        a.repair_indexes()
        self.assertTrue(b.owns(b.verify(saved['id'])))
        self.assertFalse(self.service.storage.preview()['items'])

    def test_unknown_legacy_owner_survives_and_can_be_restored(self):
        a = self.a
        item, _ = a.archive.add('Before', 'text')
        legacy = a.create('daily')
        meta = a.folder/(legacy['id']+'.json')
        index = json.loads(meta.read_text())
        del index['library_id']
        meta.write_text(json.dumps(index))
        a.archive.update(item, title='After')
        a.due()
        self.assertEqual(len(a.entries()), 2)
        a.limit = 1
        a._prune(next(e['id'] for e in a.entries() if a.owns(e)))
        self.assertFalse(self.service.storage.preview()['items'])
        a.limit = 100*1024**2
        a.restore(legacy['id'])
        self.assertEqual(a.archive.get(item)['title'], 'Before')
        self.assertFalse(a.owns(a.verify(legacy['id'])))
