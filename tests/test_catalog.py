import tempfile,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.catalog import page

class CatalogTest(unittest.TestCase):
 def test_complete_distinct_pages_and_exclusion(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root)
   try:
    ids={s.archive.add('Roman '+str(i),'Roman empire history '+str(i))[0] for i in range(65)}
    hidden,_=s.archive.add('Trashed Roman','Roman history');s.trash_item(hidden)
    pages=[page(s.archive,['Roman','empire'],offset=i) for i in (0,20,40,60)]
    self.assertTrue(all(p['catalog']['total']==65 for p in pages))
    self.assertEqual({v['item_id'] for p in pages for v in p['sources']},ids)
    self.assertEqual(sum(len(p['sources']) for p in pages),65)
    s.archive.configure('codex',False)
    with patch('secretary.ai.run',return_value='{"catalog":true,"queries":["Roman"]}') as model:
     result=s.ask_library('List all Roman records')
    self.assertEqual(result['catalog']['total'],65);self.assertEqual(model.call_count,1)
   finally:s.close()
