import copy,tempfile,unittest
from secretary.server import Service
from secretary.chat_cleanup import clean_chats

class ChatTitlesTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
  self.chat={'id':'sample','title':'Original','updated':1,'messages':[{'id':'q','role':'user','text':'Original note'},{'id':'a','role':'assistant','text':'Reply'}]}
  self.service.chat_history({'conversations':[self.chat],'activeId':'sample'})
 def tearDown(self):self.service.close();self.temp.cleanup()
 def test_persists_and_preserves_messages(self):
  renamed=self.service.rename_chat('sample','  My topic  ','Original')['chat']
  self.assertEqual(renamed['title'],'My topic');self.assertTrue(renamed['titleCustom'])
  self.service.close();self.service=Service(self.temp.name)
  saved=self.service.chat_history()['conversations'][0]
  self.assertEqual(saved['title'],'My topic');self.assertEqual(saved['messages'],self.chat['messages'])
 def test_stale_snapshot_cannot_undo_name_but_can_add_messages(self):
  self.service.rename_chat('sample','Custom')
  stale=copy.deepcopy(self.chat);stale['updated']=10**15;stale['messages'].append({'id':'q2','role':'user','text':'Next'})
  self.service.chat_history({'conversations':[stale],'activeId':'sample'})
  saved=self.service.chat_history()['conversations'][0]
  self.assertEqual(saved['title'],'Custom');self.assertEqual(len(saved['messages']),3)
 def test_validation_and_conflict_leave_chat_intact(self):
  for title in ('','  ',None,12,'x'*101):
   with self.assertRaises(ValueError):self.service.rename_chat('sample',title)
  with self.assertRaises(KeyError):self.service.rename_chat('missing','Name')
  self.service.rename_chat('sample','First','Original')
  with self.assertRaises(ValueError):self.service.rename_chat('sample','Second','Original')
  self.assertEqual(self.service.chat_history()['conversations'][0]['title'],'First')
 def test_cleanup_keeps_custom_title(self):
  chat=copy.deepcopy(self.chat);chat.update(title='Custom',titleCustom=True)
  chat['messages'] += [{'id':'q2','role':'user','text':'Keep'},{'id':'a2','role':'assistant','text':'Keep'}]
  result,_=clean_chats([chat],[],[('sample','a')])
  self.assertEqual(result[0]['title'],'Custom')
