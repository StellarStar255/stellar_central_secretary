import io,json,tempfile,unittest,zipfile
from secretary.server import Service
from secretary.backup_import import import_backup
from secretary.library import query

class TrashTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.a=self.service.archive;self.a.configure('codex',False)
  self.id,_=self.a.add('Recover fixture','Recover searchable source '*30,filename='record.txt',data=b'original bytes')
 def tearDown(self):self.service.close();self.temp.cleanup()
 def test_restore_preserves_source_flags_and_revision(self):
  self.a.set_flags(self.id,{'favorite':True,'pinned':True});self.a.mark_viewed(self.id);before=self.a.get(self.id)
  self.service.trash_item(self.id,before['updated'])
  self.assertEqual(self.a.list(),[]);self.assertEqual(self.a.retrieve('Recover'),[])
  with self.assertRaises(KeyError):self.a.get(self.id)
  self.assertEqual((self.a.root/'files'/self.id).read_bytes(),b'original bytes')
  with self.assertRaises(ValueError):self.a.add('Duplicate','Recover searchable source '*30,filename='record.txt',data=b'original bytes')
  self.assertEqual(len(self.a.trash_items()),1);self.a.restore_item(self.id);self.assertEqual(self.a.get(self.id),before);self.assertTrue(self.a.retrieve('Recover'))
 def test_flags_ranking_and_validation(self):
  other,_=self.a.add('Other fixture','Another source');before=self.a.get(self.id)['updated'];self.a.set_flags(self.id,{'favorite':True,'pinned':True})
  self.assertEqual(query(self.a)['items'][0]['id'],self.id);self.assertEqual([i['id'] for i in query(self.a,favorite='1')['items']],[self.id]);self.assertEqual(self.a.get(self.id)['updated'],before)
  for invalid in ({'favorite':'true'},{'text':True},{}):
   with self.assertRaises(ValueError):self.a.set_flags(self.id,invalid)
 def test_busy_stale_and_purge_guard(self):
  before=self.a.get(self.id);self.service.busy.add(self.id)
  with self.assertRaises(ValueError):self.service.trash_item(self.id,before['updated'])
  self.service.busy.clear()
  with self.assertRaises(ValueError):self.service.trash_item(self.id,'old revision')
  self.service.trash_item(self.id,before['updated']);stamp=self.a.trash_items()[0]['trashed_at'];self.a.restore_item(self.id)
  with self.assertRaises(ValueError):self.service.delete_item(self.id,before['updated'],stamp)
  self.service.trash_item(self.id,before['updated'])
  with self.assertRaises(ValueError):self.service.delete_item(self.id,before['updated'],stamp)
  current=self.a.trash_items()[0];self.service.delete_item(self.id,current['updated'],current['trashed_at']);self.assertFalse((self.a.root/'files'/self.id).exists());self.assertIn(self.id,self.a.deletion_refs()['deletedItemIds'])
 def test_backup_retains_trash_and_metadata(self):
  self.a.set_flags(self.id,{'favorite':True,'pinned':True});self.a.mark_viewed(self.id);self.service.trash_item(self.id,self.a.get(self.id)['updated']);before=self.a.get(self.id,True)
  backup=self.service.backup()
  with tempfile.TemporaryDirectory() as root:
   service=Service(root)
   try:
    self.assertEqual(import_backup(service.archive,backup)['imported'],1);self.assertEqual(service.archive.list(),[]);restored=service.archive.trash_items()[0];full=service.archive.get(restored['id'],True)
    for field in ('favorite','pinned','last_viewed','trashed_at','summary','text','updated'):self.assertEqual(full[field],before[field])
    self.assertEqual((service.archive.root/'files'/full['id']).read_bytes(),b'original bytes');service.archive.restore_item(full['id']);self.assertTrue(service.archive.retrieve('Recover'))
   finally:service.close()
