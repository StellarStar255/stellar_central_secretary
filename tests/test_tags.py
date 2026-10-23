import sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from secretary.core import Archive
from secretary.server import Service
from secretary.backup_import import import_backup

class TagsTest(unittest.TestCase):
 def test_custom_tags_search_and_retrieval_are_immediate(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Issue tracker','A reproducible issue with a saved body.')
   archive.set_tags(item,[' Sprint Review ','sprint review','云端算法'])
   self.assertEqual(archive.get(item)['tags'],['Sprint Review','云端算法'])
   self.assertEqual([i['id'] for i in archive.list(q='云端算法 tracker')],[item])
   self.assertEqual(archive.retrieve('云端算法')[0]['item_id'],item)
   archive.set_tags(item,['Sprint Review'])
   self.assertFalse(archive.list(q='云端算法'));self.assertFalse(archive.retrieve('云端算法'))

 def test_manual_tags_survive_ai_and_reextraction_even_when_empty(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Example','Saved body.')
   archive.set_tags(item,['My tag'])
   archive.update(item,summary='New summary',tags=['AI replacement'],title='New title')
   self.assertEqual(archive.get(item)['tags'],['My tag'])
   archive.replace_capture(item,'Refreshed title','Saved body with additional context.')
   self.assertEqual(archive.get(item)['tags'],['My tag'])
   archive.set_tags(item,[]);archive.update(item,tags=['Deleted tag returning'])
   self.assertEqual(archive.get(item)['tags'],[])

 def test_invalid_and_stale_edits_do_not_overwrite(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Example','Saved body.');archive.set_tags(item,['First'])
   for invalid in (None,'string',[''],['a'*61],['x']*51,[1]):
    with self.subTest(invalid=invalid),self.assertRaises(ValueError):archive.set_tags(item,invalid)
   with self.assertRaisesRegex(ValueError,'标签已变化'):archive.set_tags(item,['Old edit'],expected=[])
   self.assertEqual(archive.get(item)['tags'],['First'])

 def test_backup_keeps_manual_ownership(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as restored:
   service=Service(root)
   try:
    item,_=service.archive.add('Example','Saved body.');service.archive.set_tags(item,['Keep me'])
    archive=Archive(restored);import_backup(archive,service.backup());saved=archive.list()[0]
    archive.update(saved['id'],tags=['AI replacement'])
    self.assertEqual(archive.get(saved['id'])['tags'],['Keep me'])
   finally:service.close()

 def test_old_database_migrates_without_changing_original_material(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Old title','Old body.');archive.update(item,tags=['Legacy keyword'])
   # Model an installed database from before manual tags existed.
   with closing(sqlite3.connect(Path(root)/'archive.sqlite3')) as db:
    db.execute('ALTER TABLE items DROP COLUMN tags_manual');db.commit()
   migrated=Archive(root);saved=migrated.get(item)
   self.assertEqual(saved['text'],'Old body.');self.assertEqual(saved['tags'],['Legacy keyword']);self.assertEqual(saved['tags_manual'],0)
   self.assertEqual(migrated.retrieve('Legacy')[0]['item_id'],item)

if __name__=='__main__':unittest.main()
