import copy,json,tempfile,threading,time,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary import ai

class QuestionJobsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.s=Service(self.temp.name);self.s.archive.configure('codex',False)
  self.item=self.s.archive.add('Timetable','课程表：周二14:00有课。')[0]
  self.chat={'id':'chat','title':'Schedule','updated':1,'messages':[{'id':'q','role':'user','text':'课表','knowledgeQuestion':True},{'id':'a','role':'assistant','text':'','pending':True,'questionId':'q'}]}
  self.s.chat_history({'activeId':'chat','conversations':[self.chat]})
  self.body={'progress_id':'a'*32,'chat_id':'chat','message_id':'a','question_id':'q','question':'课表'}
 def tearDown(self):self.s.close();self.temp.cleanup()
 def finish(self,key=None):
  deadline=time.monotonic()+3
  while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(self.s.question_jobs.active_count(),0)
  return self.s.question_jobs.get({**self.body,'progress_id':key or self.body['progress_id']})['message']
 def test_result_is_saved_without_any_polling_and_stale_clients_cannot_erase_it(self):
  entered=threading.Event();release=threading.Event()
  def ask(*args,**kwargs):entered.set();release.wait(2);return {'answer':'14:00有课。[1]','sources':[{'item_id':self.item,'number':1,'title':'Timetable'}]}
  with patch.object(self.s,'ask_library',side_effect=ask) as model:
   self.s.question_jobs.start(self.body);self.assertTrue(entered.wait(1));self.s.question_jobs.start(self.body)
   self.assertEqual(model.call_count,1);release.set();message=self.finish()
  self.assertEqual(message['requestState'],'done');self.assertIn('14:00',message['text'])
  stale=copy.deepcopy(self.chat);stale['updated']=int(time.time()*1000)+10000
  self.s.chat_history({'activeId':'chat','conversations':[stale]})
  self.assertEqual(self.s.chat_history()['conversations'][0]['messages'][1]['text'],message['text'])
  self.s.close();self.s=Service(self.temp.name)
  self.assertEqual(self.s.question_jobs.get(self.body)['message']['text'],message['text'])
 def test_restart_marks_unfinished_job_retryable_without_automatically_running_a_model(self):
  path=self.s.archive.root/'conversations.json';data=json.loads(path.read_text());message=data['conversations'][0]['messages'][1]
  message.update(requestId='c'*32,requestState='running',pending=True);path.write_text(json.dumps(data))
  self.s.close()
  with patch('secretary.ai.run',side_effect=AssertionError('No automatic rerun after restart')):self.s=Service(self.temp.name)
  state=self.s.question_jobs.get({**self.body,'progress_id':'c'*32})['message']
  self.assertFalse(state['pending']);self.assertTrue(state['retryable']);self.assertEqual(state['requestState'],'interrupted')
 def test_cancellation_is_saved_as_retryable(self):
  entered=threading.Event()
  def ask(*args,**kwargs):
   entered.set();kwargs['cancel'].wait(2);raise ai.ModelCancelledError('Stopped')
  with patch.object(self.s,'ask_library',side_effect=ask):
   self.s.question_jobs.start(self.body);self.assertTrue(entered.wait(1));self.s.question_progress.cancel(self.body['progress_id']);state=self.finish()
  self.assertEqual(state['requestState'],'cancelled');self.assertTrue(state['retryable'])
 def test_unrelated_target_and_duplicate_id_conflicts_are_rejected(self):
  with self.assertRaises(ValueError):self.s.question_jobs.start({**self.body,'question':'Different text'})
  with patch.object(self.s,'ask_library',return_value={'answer':'你好','sources':[]}):
   other={**self.body,'progress_id':'b'*32};self.s.question_jobs.start(other);self.finish('b'*32)
  with self.assertRaises(ValueError):self.s.question_jobs.start({**other,'question_id':'different'})

 def test_deleted_chat_is_not_resurrected_by_a_late_result_or_stale_snapshot(self):
  entered=threading.Event();release=threading.Event()
  def ask(*args,**kwargs):entered.set();release.wait(2);return {'answer':'Private result [1]','sources':[{'item_id':self.item,'number':1}]}
  with patch.object(self.s,'ask_library',side_effect=ask):
   self.s.question_jobs.start(self.body);self.assertTrue(entered.wait(1))
   with self.s.archive.db() as db:db.executemany('INSERT INTO deleted_messages VALUES (?,?)',[('chat','q'),('chat','a')])
   self.assertEqual(self.s.chat_history()['conversations'],[]);release.set()
   deadline=time.monotonic()+3
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(self.s.question_jobs.active_count(),0)
  stale=copy.deepcopy(self.chat);stale['updated']=int(time.time()*1000)+10000
  self.assertEqual(self.s.chat_history({'activeId':'chat','conversations':[stale]})['conversations'],[])
  with self.assertRaises(ValueError):self.s.question_jobs.get(self.body)

 def test_company_confirmation_pauses_background_job_and_can_resume(self):
  from secretary import company_ai
  self.s.archive.set_company_mode(True);company_ai.mark(self.s.archive,self.item)
  info=company_ai.status(self.s.archive,self.s.model_backend())
  with patch.object(self.s,'ask_library',side_effect=[company_ai.ApprovalRequired(info),{'answer':'Approved [1]','sources':[{'item_id':self.item,'number':1}]}]) as ask:
   self.s.question_jobs.start(self.body)
   deadline=time.monotonic()+2
   while self.s.question_progress.snapshot('a'*32)['stage']!='approval' and time.monotonic()<deadline:time.sleep(.01)
   with self.assertRaises(company_ai.ApprovalRequired):self.s.question_jobs.get(self.body)
   company_ai.approve(self.s.archive,self.s.model_backend(),{'acknowledged':True,'fingerprint':info['fingerprint']})
   self.assertEqual(self.finish()['requestState'],'done');self.assertEqual(ask.call_count,2)
