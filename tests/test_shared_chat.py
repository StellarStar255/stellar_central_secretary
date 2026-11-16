import copy,json,tempfile,threading,time,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.shared_chat import SharedChat,ChatBusy,context
from secretary import ai

class SharedChatTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.s=Service(self.temp.name);self.s.archive.configure('codex',False);self.mobile=SharedChat(self.s)
  self.item=self.s.archive.add('课表','周二 14:00 有课')[0]
  self.chat={'id':'desktop-chat','title':'电脑上的会话','updated':1,'messages':[
   {'id':'q0','role':'user','text':'我的课表','knowledgeQuestion':True},
   {'id':'a0','role':'assistant','text':'周二有课。[1]','sources':[{'number':1,'item_id':self.item,'title':'课表'}]},
   {'id':'c0','role':'user','text':'以后请用中文回答','knowledgeQuestion':True},
   {'id':'ca0','role':'assistant','text':'好的','sources':[]}],
   'contextEdits':{'c0':'以后请使用简体中文回答'}}
  self.s.chat_history({'activeId':self.chat['id'],'conversations':[self.chat]})
 def tearDown(self):self.s.close();self.temp.cleanup()
 def finish(self):
  until=time.monotonic()+4
  while self.s.question_jobs.active_count() and time.monotonic()<until:time.sleep(.01)
  self.assertEqual(self.s.question_jobs.active_count(),0)
 def test_shared_context_deduplicated_submission_and_desktop_persistence(self):
  body={'request_id':'phone-1','text':'那周三呢？'}
  with patch.object(self.s,'ask_library',return_value={'answer':'周三没有记录。[1]','sources':[{'item_id':self.item,'number':1,'title':'课表'}]}) as model:
   first=self.mobile.send('phone',self.chat['id'],body);self.finish()
   self.assertEqual(self.mobile.send('phone',self.chat['id'],body),first)
   self.s.question_jobs.jobs.clear()
   self.mobile.send('phone',self.chat['id'],body)
   self.assertEqual(model.call_count,1)
   args,kwargs=model.call_args
   self.assertEqual(args[1][0]['question'],'我的课表');self.assertEqual(args[1][0]['source_ids'],[self.item])
   self.assertEqual(args[1][1]['question'],'以后请使用简体中文回答')
   self.assertEqual(kwargs['context'],[{'statement':'以后请使用简体中文回答','source_ids':[self.item]}])
  desktop=self.s.chat_history()['conversations'][0]
  self.assertEqual(len(desktop['messages']),6)
  self.assertEqual(desktop['messages'][-1]['text'],'周三没有记录。[1]')
  stale=copy.deepcopy(self.chat);stale['updated']=int(time.time()*1000)+10000
  self.s.chat_history({'activeId':self.chat['id'],'conversations':[stale]})
  self.assertEqual(len(self.s.chat_history()['conversations'][0]['messages']),6)
  self.assertEqual(self.mobile.detail(self.chat['id'])['messages'][-1]['requestState'],'done')
  with self.assertRaises(ValueError):self.mobile.send('phone',self.chat['id'],{**body,'text':'Different'})
 def test_stream_delta_survives_disconnection_and_can_be_cancelled(self):
  entered=threading.Event()
  def ask(question,history,progress,**kwargs):
   progress('partial','已生成的部分回答');entered.set();kwargs['cancel'].wait(3);raise ai.ModelCancelledError('Stopped')
  with patch.object(self.s,'ask_library',side_effect=ask):
   result=self.mobile.send('phone',self.chat['id'],{'request_id':'stream','text':'继续解释'})
   self.assertTrue(entered.wait(1));self.assertGreater(self.s.runtime()['answering'],0)
   first=self.mobile.detail(self.chat['id']);mid=result['message_id']
   self.assertEqual(first['progress']['partial'],'已生成的部分回答')
   same=self.mobile.detail(self.chat['id'],first['revision'],partial_offset=len(first['progress']['partial']),partial_id=mid)
   self.assertTrue(same['unchanged']);self.assertEqual(same['progress']['partial'],'')
   reset=self.mobile.detail(self.chat['id'],first['revision'],partial_offset=999,partial_id='old-answer')
   self.assertTrue(reset['progress']['reset']);self.assertEqual(reset['progress']['partial'],'已生成的部分回答')
   with self.assertRaises(ChatBusy):self.mobile.send('phone',self.chat['id'],{'request_id':'another','text':'另一条问题'})
   self.mobile.stop(self.chat['id'],{'message_id':mid});self.finish()
  self.assertEqual(self.mobile.detail(self.chat['id'])['messages'][-1]['requestState'],'cancelled')
 def test_summary_revision_pagination_and_metadata_allowlist(self):
  listing=self.mobile.listing();self.assertEqual(listing['active_id'],self.chat['id'])
  self.assertTrue(self.mobile.listing(listing['revision'])['unchanged'])
  chat=copy.deepcopy(self.chat)
  chat['messages']=[{'id':str(i),'role':'assistant' if i%2 else 'user','text':str(i),'requestApproval':{'secret':'never-export','fingerprint':'private'}} for i in range(45)]
  chat['updated']=2;self.s.chat_history({'activeId':chat['id'],'conversations':[chat]})
  first=self.mobile.detail(chat['id']);self.assertEqual(len(first['messages']),20);self.assertEqual(first['messages'][0]['text'],'25');self.assertTrue(first['has_more'])
  second=self.mobile.detail(chat['id'],before='25');self.assertEqual(second['messages'][0]['text'],'5')
  last=self.mobile.detail(chat['id'],before='5');self.assertEqual(len(last['messages']),5);self.assertFalse(last['has_more'])
  self.assertNotIn('never-export',json.dumps(first));self.assertNotIn('fingerprint',json.dumps(first))
 def test_cleared_conditions_and_recent_source_anchor_match_desktop_rules(self):
  chat=copy.deepcopy(self.chat);chat['contextIgnored']=['c0']
  history,retained=context(chat);self.assertEqual(len(history),1);self.assertEqual(retained,[])
  chat=copy.deepcopy(self.chat);chat['contextReset']='ca0'
  history,retained=context(chat);self.assertEqual(len(history),1);self.assertEqual(retained,[])
  for i in range(8):chat['messages'] += [{'id':'q'+str(i+10),'role':'user','text':'新问题','knowledgeQuestion':True},{'id':'a'+str(i+10),'role':'assistant','text':'普通回复','sources':[]}]
  history,_=context(chat);self.assertEqual(len(history),6);self.assertEqual(history[0]['source_ids'],[self.item])
 def test_create_retry_is_idempotent_and_deleted_messages_are_not_recreated(self):
  first=self.mobile.create('phone',{'request_id':'new'});self.assertEqual(first,self.mobile.create('phone',{'request_id':'new'}))
  with patch.object(self.s,'ask_library',return_value={'answer':'Done','sources':[]}):
   self.mobile.send('phone',first['chat_id'],{'request_id':'message','text':'Hello'});self.finish()
  chat=next(c for c in self.s.chat_history()['conversations'] if c['id']==first['chat_id'])
  with self.s.archive.db() as db:db.executemany('INSERT INTO deleted_messages VALUES (?,?)',[(chat['id'],m['id']) for m in chat['messages']])
  self.s.chat_history()
  with self.assertRaises(ValueError):self.mobile.send('phone',first['chat_id'],{'request_id':'message','text':'Hello'})
