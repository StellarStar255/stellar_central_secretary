import io,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from secretary import ai,model_api
from secretary.server import Service
from secretary.streaming import chat_sse,worker_result
from secretary.completion_notifications import CompletionConsumer

class ImprovementsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.s=Service(self.temp.name);self.s.archive.configure('codex',False)
  self.item,_=self.s.archive.add('Timetable','课程表：周四14:00有课。')
 def tearDown(self):self.s.close();self.temp.cleanup()
 def ask(self,**kwargs):
  with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','周四14:00有课。[1]']) as model:
   result=self.s.ask_library('周四有课吗？',**kwargs)
  return result,model.call_count
 def test_cache_and_explicit_refresh_and_record_changes(self):
  first,count=self.ask();self.assertEqual(count,2)
  second,count=self.ask();self.assertEqual(count,0);self.assertTrue(second['timings']['cache_hit'])
  _,count=self.ask(force_refresh=True);self.assertEqual(count,2)
  self.s.archive.update(self.item,text='课程表：周四15:00有课。');_,count=self.ask();self.assertEqual(count,2)
  self.s.archive.add('New evidence','New timetable exception');_,count=self.ask();self.assertEqual(count,2)
 def test_cached_original_file_changes_and_company_gate(self):
  path=self.s.archive.root/'files'/self.item;path.write_bytes(b'first original')
  self.ask();path.write_bytes(b'changed original');_,count=self.ask();self.assertEqual(count,2)
  backend=self.s.model_backend()
  def gate(item_ids=None):
   if self.item in (item_ids or []):raise ValueError('Approval required')
   return backend
  with patch.object(self.s,'model_backend',side_effect=gate),patch('secretary.ai.run',side_effect=AssertionError('No model before approval')):
   with self.assertRaisesRegex(ValueError,'Approval'):self.s.ask_library('周四有课吗？')
 def test_cache_expiry_backend_and_semantic_rebuild(self):
  self.ask()
  for entry in self.s.answer_cache.entries.values():entry['at']-=301
  _,count=self.ask();self.assertEqual(count,2)
  self.s.semantic.generation+=1
  _,count=self.ask();self.assertEqual(count,2)
  self.s.archive.configure('claude',False)
  _,count=self.ask();self.assertEqual(count,2)
 def test_context_kept_beyond_recent_turns_and_invalidates_cache(self):
  context=[{'statement':'这个课程表就是她的，依据这个判断就行','source_ids':[self.item]}]
  with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','按你指定的课表，有课。[1]']) as model:
   self.s.ask_library('周四有课吗？',history=[{'question':str(i),'answer':'Recent small talk','source_ids':[]} for i in range(6)],context=context)
  payload=json.loads(model.call_args.args[0].split('\n',1)[1]);self.assertIn(context[0]['statement'],payload['history'][0]['question'])
  self.assertEqual(payload['history'][0]['answer'],'')
  _,count=self.ask(context=context);self.assertEqual(count,2)
  _,count=self.ask(context=context);self.assertEqual(count,0)
  _,count=self.ask(context=[{'statement':'更正为下周适用','source_ids':[self.item]}]);self.assertEqual(count,2)
  with self.assertRaises(ValueError):self.s.ask_library('Hi',context=[{'statement':'x','source_ids':['bad']}])
 def test_opt_in_notifications_and_no_source_content(self):
  with patch('secretary.ai.summary_fields',return_value={'summary':'Synthetic result','state':'ready','error':''}):
   self.s.queue(self.item,force=True)
   with self.s.lock:future=self.s.summary_futures.get(self.item)
   if future:future.result(timeout=5)
  self.assertEqual(self.s.completion_events.snapshot(),[])
  with self.s.archive.db() as db:db.execute("INSERT OR REPLACE INTO settings VALUES ('completion_notifications','true')")
  with patch('secretary.ai.summary_fields',return_value={'summary':'Private result','state':'ready','error':''}):
   self.s.queue(self.item,force=True)
   with self.s.lock:future=self.s.summary_futures.get(self.item)
   if future:future.result(timeout=5)
  events=self.s.completion_events.snapshot();self.assertEqual(len(events),1)
  self.assertNotIn('Private',json.dumps(events));self.assertNotIn('Timetable',json.dumps(events))
  c=CompletionConsumer();status={'completion_events':events,'settings':{'completion_notifications':True}}
  self.assertEqual(len(c.consume(status)),1);self.assertEqual(c.consume(status),[])
  with patch('secretary.ai.summary_fields',side_effect=RuntimeError('Synthetic error')):
   self.s.queue(self.item,force=True)
   with self.s.lock:future=self.s.summary_futures.get(self.item)
   if future:future.result(timeout=5)
  self.assertEqual(self.s.completion_events.snapshot()[-1]['stage'],'error')
  self.assertEqual(self.s.archive.get(self.item)['state'],'error')

class StreamingTest(unittest.TestCase):
 def test_sse_partial_redaction_and_incomplete_output(self):
  def chunk(text,reason=None):return ('data: '+json.dumps({'choices':[{'delta':{'content':text},'finish_reason':reason}]})+'\n\n').encode()
  parts=[]
  with patch('secretary.streaming.time.monotonic',side_effect=range(1,100)):
   result=chat_sse(io.BytesIO(chunk('secret-')+chunk('api-key text')+chunk('', 'stop')+b'data: [DONE]\n'),parts.append,'secret-api-key')
  self.assertEqual(result,'[redacted] text');self.assertEqual(parts[0],'');self.assertNotIn('secret',str(parts))
  with self.assertRaisesRegex(ValueError,'中断'):chat_sse(io.BytesIO(chunk('Incomplete')),lambda value:None)
 def test_worker_emits_text_before_final_result_and_has_deadline(self):
  proc=subprocess.Popen([sys.executable,'-c','import sys,json,time;sys.stdin.read();print(json.dumps({"partial":"first"}),flush=True);time.sleep(.1);print(json.dumps({"answer":"final"}),flush=True)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  parts=[]
  try:self.assertEqual(worker_result(proc,'{}',parts.append,3,lambda p:p.kill()),{'answer':'final'});self.assertEqual(parts,['first'])
  finally:proc.wait(timeout=2);proc.stdout.close()
