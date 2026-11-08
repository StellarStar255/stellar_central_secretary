import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service
from secretary.local_backups import Backups
class BackupCapacityTest(unittest.TestCase):
 def test_directory_change_retains_restore_access_and_limits_count(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data');service.archive.configure('codex',False)
   try:
    ident,_=service.archive.add('Before','retained backup text');old=service.backups.create()
    service.backups.configure({'folder':str(Path(temp)/'other'),'max_bytes':100*1024**2,'daily_keep':1,'other_keep':1})
    service.archive.update(ident,title='After');service.backups.create();service.backups.create()
    entries=service.backups.entries();self.assertEqual(len([entry for entry in entries if Path(entry['folder'])==service.backups.folder]),1)
    self.assertTrue(any(entry['id']==old['id'] for entry in entries));service.backups.restore(old['id']);self.assertEqual(service.archive.get(ident)['title'],'Before')
    self.assertLessEqual(service.backups.status()['used_bytes'],100*1024**2)
    again=Backups(service.archive);self.assertEqual(again.folder,service.backups.folder);self.assertTrue(again.status()['last_success'])
   finally:service.close()
 def test_failure_retains_previous_backup_and_persists_notice(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    service.archive.add('test','text');saved=service.backups.create();path=service.backups.folder/(saved['id']+'.zip');before=path.read_bytes()
    with patch('secretary.local_backups.zipfile.ZipFile',side_effect=OSError('Synthetic full disk')):
     with self.assertRaises(OSError):service.backups.create()
    self.assertEqual(path.read_bytes(),before);self.assertEqual(service.backups.status()['state'],'error')
    self.assertIn('Synthetic full disk',Backups(service.archive).status()['last_error'])
    with self.assertRaises(ValueError):service.backups.configure({'folder':str(Path(temp)/'files'),'max_bytes':100*1024**2})
   finally:service.close()
 def test_byte_cap_prunes_oldest_only_after_new_snapshot_is_complete(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    service.archive.add('capacity','sample text');first=service.backups.create();service.backups.limit=first['size']*2
    service.backups.create();latest=service.backups.create()
    self.assertLessEqual(service.backups.status()['used_bytes'],service.backups.limit)
    self.assertTrue(any(entry['id']==latest['id'] for entry in service.backups.entries()))
    service.backups.limit=1
    with self.assertRaisesRegex(ValueError,'超过容量'):service.backups.create()
    self.assertTrue(any(entry['id']==latest['id'] for entry in service.backups.entries()))
   finally:service.close()

 def test_older_backup_schema_is_migrated_before_restoring_live_database(self):
  import hashlib,json,sqlite3,zipfile
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data')
   try:
    ident,_=service.archive.add('Legacy','retained legacy text');saved=service.backups.create();source=service.backups.folder/(saved['id']+'.zip')
    with tempfile.TemporaryDirectory() as work:
     work=Path(work)
     with zipfile.ZipFile(source) as archive:archive.extractall(work)
     with sqlite3.connect(work/'archive.sqlite3') as db:
      db.execute('ALTER TABLE items DROP COLUMN pdf_reads');db.execute('ALTER TABLE chunks DROP COLUMN origin')
     db.close()
     with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
      for file in work.rglob('*'):
       if file.is_file():archive.write(file,str(file.relative_to(work)))
    meta=source.with_suffix('.json');value=json.loads(meta.read_text());value.update(size=source.stat().st_size,sha256=hashlib.sha256(source.read_bytes()).hexdigest());meta.write_text(json.dumps(value))
    service.backups.restore(saved['id']);self.assertEqual(service.archive.get(ident)['title'],'Legacy');self.assertTrue(service.archive.retrieve('legacy'));self.assertEqual(service.archive.get(ident)['pdf_reads'],{})
   finally:service.close()
