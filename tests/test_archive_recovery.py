import tempfile,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.core import TrashedDuplicateError


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
 def test_trash_conflict_is_structured_and_restore_preserves_original(self):
  text='建档：\n周六上午11:00测试对象复查 only-trash'
  saved=self.service.ingest({'text':text,'archive_only':True})['item']
  self.service.trash_item(saved['id'],saved['updated'])
  deleted=self.service.archive.get(saved['id'],include_trashed=True)
  with self.assertRaises(TrashedDuplicateError) as error:self.service.ingest({'text':text})
  self.assertEqual(error.exception.item['id'],saved['id'])
  self.assertTrue(self.service.archive.get(saved['id'],include_trashed=True)['trashed_at'])
  with self.assertRaises(ValueError):self.service.archive.restore_item(saved['id'],expected_updated='stale',expected_trashed_at=deleted['trashed_at'])
  self.service.archive.restore_item(saved['id'],expected_updated=deleted['updated'],expected_trashed_at=deleted['trashed_at'])
  restored=self.service.archive.get(saved['id'])
  self.assertEqual(restored,saved)
  self.assertTrue(self.service.archive.retrieve('only-trash'))
