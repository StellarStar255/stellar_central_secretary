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

 def test_history_suffix_only_relaxes_an_empty_catalog_and_reports_actual_keywords(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root)
   try:
    item=s.archive.add('罗马皇位继承','军队拥立和政治承认影响罗马皇位。')[0]
    result=page(s.archive,['罗马史'])
    self.assertEqual(result['catalog']['total'],1);self.assertEqual(result['sources'][0]['item_id'],item)
    self.assertIn('罗马',result['catalog']['queries']);self.assertTrue(result['retrieval_notice'])
    exact=s.archive.add('罗马史','Specific topic')[0]
    result=page(s.archive,['罗马史']);self.assertEqual({source['item_id'] for source in result['sources']},{exact})
    self.assertEqual(page(s.archive,['党史'])['catalog']['total'],0)
   finally:s.close()

 def test_combined_chinese_synonyms_do_not_become_an_impossible_and_query(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root)
   try:
    item=s.archive.add('罗马皇位继承','军队拥立影响罗马皇位。')[0]
    result=page(s.archive,['罗马史 罗马历史 古罗马史 古罗马','罗马史 罗马历史 古罗马史 古罗马历史'])
    self.assertEqual({source['item_id'] for source in result['sources']},{item})
    self.assertEqual(result['catalog']['queries'][0],'罗马');self.assertTrue(result['retrieval_notice'])
    self.assertEqual(page(s.archive,['罗马 帝国'])['catalog']['total'],0)
   finally:s.close()
