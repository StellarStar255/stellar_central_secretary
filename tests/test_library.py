import tempfile,unittest
from secretary.core import Archive
from secretary.library import query

class LibraryTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_title_priority_and_body_context_keep_all_keyword_matching(self):
  title,_=self.archive.add('Robot camera problem','Unique older original')
  body,_=self.archive.add('Other material','x'*180+' robot camera detected at work '+'y'*180)
  self.archive.add('Camera only','Unique unrelated body')
  result=query(self.archive,q='camera robot')
  self.assertEqual([item['id'] for item in result['items']],[title,body])
  self.assertIn('robot camera',result['items'][1]['search_snippet'])
  self.assertLess(len(result['items'][1]['search_snippet']),245)
 def test_viewed_order_does_not_change_content_revision(self):
  first,_=self.archive.add('One','First unique material');second,_=self.archive.add('Two','Second unique material')
  revision=self.archive.get(first)['updated'];self.archive.mark_viewed(first)
  self.assertEqual(query(self.archive,sort='viewed')['items'][0]['id'],first)
  self.assertEqual(self.archive.get(first)['updated'],revision)
  self.archive.mark_viewed(second);self.assertEqual(query(self.archive,sort='viewed')['items'][0]['id'],second)
 def test_filters_pagination_and_validation(self):
  ids=[self.archive.add('Record '+str(i),'Unique body '+str(i))[0] for i in range(105)]
  page=query(self.archive,offset=100);self.assertEqual(page['total'],105);self.assertEqual(len(page['items']),5)
  self.archive.update(ids[0],state='error');self.assertEqual(query(self.archive,state='error')['items'][0]['id'],ids[0])
  self.assertEqual(query(self.archive,state='active',active_ids=[ids[1]])['total'],1)
  with self.archive.db() as db:db.execute("UPDATE items SET created='2000-01-01T00:00:00+00:00' WHERE id=?",(ids[0],))
  self.assertEqual(query(self.archive,days='7')['total'],104)
  for args in ({'sort':'invalid'},{'days':'-1'},{'limit':101},{'offset':-1}):
   with self.assertRaises(ValueError):query(self.archive,**args)
