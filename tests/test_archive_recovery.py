import base64,tempfile,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.core import Archive


class ArchiveRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.service.archive.configure('codex',False)
 def tearDown(self):self.service.close();self.temp.cleanup()
 def test_live_equivalent_is_reused_without_restoring_trashed_wrapper(self):
  text='周六上午11:00带测试对象去复查'
  live=self.service.ingest({'text':text,'archive_only':True})['item']
  deleted,_=self.service.archive.add('Old wrapper','建档：\n'+text)
  self.service.trash_item(deleted,self.service.archive.get(deleted)['updated'])
  original_trash=self.service.archive.get(deleted,include_trashed=True)
  with patch.object(self.service,'queue',side_effect=AssertionError('No repeated AI work')):
   result=self.service.ingest({'text':'建档：\n'+text})
  self.assertTrue(result['reused']);self.assertEqual(result['item']['id'],live['id'])
  self.assertEqual(result['item']['created'],live['created'])
  self.assertEqual(self.service.archive.get(deleted,include_trashed=True),original_trash)
  self.assertEqual(len(self.service.archive.list()),1)
 def test_rearchiving_keeps_trash_and_restore_preserves_original(self):
  text='建档：\n周六上午11:00测试对象复查 only-trash'
  saved=self.service.ingest({'text':text,'archive_only':True})['item']
  self.service.trash_item(saved['id'],saved['updated'])
  deleted=self.service.archive.get(saved['id'],include_trashed=True)
  fresh=self.service.ingest({'text':text,'archive_only':True})['item']
  self.assertNotEqual(fresh['id'],saved['id'])
  self.assertEqual(self.service.ingest({'text':text,'archive_only':True})['item']['id'],fresh['id'])
  self.assertTrue(self.service.archive.get(saved['id'],include_trashed=True)['trashed_at'])
  with self.assertRaises(ValueError):self.service.archive.restore_item(saved['id'],expected_updated='stale',expected_trashed_at=deleted['trashed_at'])
  self.service.archive.restore_item(saved['id'],expected_updated=deleted['updated'],expected_trashed_at=deleted['trashed_at'])
  restored=self.service.archive.get(saved['id'])
  self.assertEqual(restored,saved)
  self.assertTrue(self.service.archive.retrieve('only-trash'))
 def test_existing_unique_digest_migrates_and_file_can_be_rearchived(self):
  data=b'rearchive fixture'
  body={'filename':'paper.txt','data':base64.b64encode(data).decode(),'archive_only':True}
  original=self.service.ingest(body)['item']
  with self.service.archive.db() as db:
   schema=db.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()[0]
   legacy=schema[schema.index('('):].replace('digest TEXT','digest TEXT UNIQUE',1)
   fields=','.join(row[1] for row in db.execute('PRAGMA table_info(items)'))
   db.execute('CREATE TABLE legacy_items'+legacy)
   db.execute('INSERT INTO legacy_items(rowid,'+fields+') SELECT rowid,'+fields+' FROM items')
   db.execute('DROP TABLE items')
   db.execute('ALTER TABLE legacy_items RENAME TO items')
  archive=Archive(self.temp.name)
  self.assertEqual(archive.list(q='fixture')[0]['id'],original['id'])
  archive.trash_item(original['id'],original['updated'])
  fresh=self.service.ingest(body)['item']
  self.assertNotEqual(original['id'],fresh['id'])
  self.assertEqual(original['digest'],fresh['digest'])
  self.assertEqual((archive.root/'files'/fresh['id']).read_bytes(),data)
  backup=self.service.backups.create()
  self.assertEqual(backup['verification']['state'],'verified')
  from secretary.backup_import import import_backup
  with tempfile.TemporaryDirectory() as target:
   imported=Archive(target)
   self.assertEqual(import_backup(imported,self.service.backup())['imported'],2)
   self.assertEqual(len(imported.list()),1)
   self.assertEqual(len(imported.trash_items()),1)
 def test_optional_speaker_reuses_arrangement_in_both_directions(self):
  text='周六上午11:00带测试对象去复查'
  first=self.service.ingest({'text':'建档：\n'+text,'archive_only':True})['item']
  repeated=self.service.ingest({'text':'建档：\n我'+text,'archive_only':True})
  self.assertTrue(repeated['reused']);self.assertEqual(repeated['item']['id'],first['id'])
  self.assertEqual(len(self.service.archive.list()),1)
  second='周六下午15:00测试对象复查'
  with_speaker=self.service.ingest({'text':'我'+second,'archive_only':True})['item']
  without_speaker=self.service.ingest({'text':second,'archive_only':True})
  self.assertTrue(without_speaker['reused']);self.assertEqual(without_speaker['item']['id'],with_speaker['id'])
  for different in ['她'+text,'我们'+text,text.replace('11:00','10:00'),text.replace('测试对象','另一对象')]:
   self.assertTrue(self.service.ingest({'text':different,'archive_only':True})['created'])
  self.assertEqual(self.service.archive.get(first['id'])['text'],'建档：\n'+text)
