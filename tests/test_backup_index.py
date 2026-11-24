import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from secretary.core import Archive
from secretary.local_backups import Backups


class BackupIndexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.archive = Archive(Path(temp.name))
        self.item, _ = self.archive.add('Snapshot', 'example', filename='note.txt', data=b'original')
        self.backups = Backups(self.archive)

    def test_bad_index_does_not_block_listing_verifying_or_restoring_another(self):
        good = self.backups.create()
        broken = self.backups.create()
        meta = self.backups.folder/(broken['id']+'.json')
        for malformed in ({'id': broken['id']}, None, {'created': {}, 'reason': []},
                          {**broken, 'verification': {'checked_at': 42, 'state': 'verified'}}):
            meta.write_text(json.dumps(malformed))
            entries = {entry['id']:entry for entry in self.backups.entries()}
            self.assertEqual(entries[broken['id']]['index_issue'], 'invalid_index')
            self.assertEqual(self.backups.verify(good['id'])['verification']['state'], 'verified')
            self.backups.status()
        self.archive.update(self.item, title='Edited')
        self.backups.restore(good['id'])
        self.assertEqual(self.archive.get(self.item)['title'], 'Snapshot')
        self.backups.repair_indexes()
        self.assertEqual(json.loads(meta.read_text())['verification']['state'], 'verified')

    def test_process_exit_after_zip_publish_recovers_the_snapshot(self):
        first = self.backups.create()
        self.archive.update(self.item, title='After')
        script = """
import os,sys
from pathlib import Path
from secretary.core import Archive
from secretary.local_backups import Backups
original=Path.replace
def interrupt(path,target):
    result=original(path,target)
    if path.suffix=='.part' and target.suffix=='.zip':os._exit(73)
    return result
Path.replace=interrupt
Backups(Archive(sys.argv[1])).create()
"""
        child = subprocess.run([sys.executable, '-c', script, str(self.archive.root)], timeout=30)
        self.assertEqual(child.returncode, 73)
        backups = Backups(Archive(self.archive.root))
        orphan, = [entry for entry in backups.entries() if entry['id']!=first['id']]
        self.assertEqual(orphan['index_issue'], 'missing_index')
        self.assertEqual(backups.status()['used_bytes'], sum(p.stat().st_size for p in backups.folder.glob('*.zip')))
        meta = backups.folder/(orphan['id']+'.json')
        self.assertFalse(meta.exists())
        backups.start()
        try:
            import time
            deadline=time.monotonic()+10
            while not meta.exists() and time.monotonic()<deadline:
                time.sleep(.02)
        finally:
            backups.close()
        self.assertEqual(json.loads(meta.read_text())['verification']['state'], 'verified')
        self.assertEqual(json.loads(meta.read_text())['reason'], 'manual')
        self.archive.update(self.item, title='Later')
        backups.restore(orphan['id'])
        self.assertEqual(self.archive.get(self.item)['title'], 'After')

    def test_keep_unrepairable_zip_and_never_replace_a_known_checksum(self):
        good = self.backups.create()
        bad = self.backups.create()
        payload = self.backups.folder/(bad['id']+'.zip')
        meta = payload.with_suffix('.json')
        index = json.loads(meta.read_text())
        del index['created']
        index['sha256'] = '0'*64
        meta.write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.backups.verify(bad['id'])
        self.assertEqual(json.loads(meta.read_text()),index)
        meta.unlink()
        payload.write_bytes(b'damaged archive')
        with self.assertLogs('secretary.local_backups', level='WARNING'):
            self.backups.repair_indexes()
        self.backups.limit=1
        self.backups._prune(good['id'])
        self.assertEqual(payload.read_bytes(),b'damaged archive')
        self.assertFalse(meta.exists())
        self.assertEqual(self.backups.verify(good['id'])['verification']['state'],'verified')

    def test_orphan_legacy_archive_needs_an_independent_checksum(self):
        entry = self.backups.create()
        path = self.backups.folder/(entry['id']+'.zip')
        with zipfile.ZipFile(path) as z:
            contents = {name:z.read(name) for name in z.namelist() if name!='manifest.json'}
        with zipfile.ZipFile(path,'w') as z:
            for name,data in contents.items():
                z.writestr(name,data)
        path.with_suffix('.json').unlink()
        with self.assertRaisesRegex(ValueError, '逐文件清单'):
            self.backups.restore(entry['id'])
        self.assertFalse(path.with_suffix('.json').exists())
