import json,subprocess,sys,tempfile,threading,time,unittest
from unittest.mock import patch
from secretary import ai
from secretary.server import Service

def wait(check):
 deadline=time.monotonic()+5
 while time.monotonic()<deadline:
  if check():return
  time.sleep(.01)
 raise AssertionError('Task fixture timed out')

class TaskControlTests(unittest.TestCase):
 def test_cancel_only_one_cli_process_and_keep_other_job_running(self):
  original=subprocess.Popen;started=[];events=[threading.Event(),threading.Event()];results={}
  def child(command,*args,**kwargs):
   proc=original([sys.executable,'-c',"import sys,time,json; sys.stdin.read(); time.sleep(1.2); print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'OK'}}))"],*args,**kwargs);started.append(proc);return proc
  def work(index):
   try:
    with ai.cancellation(events[index]):results[index]=ai.run('Fixture','codex',timeout=5)
   except ai.ModelCancelledError:results[index]='stopped'
  with patch.object(ai,'executable',return_value='fixture-cli'),patch.object(ai.network,'child_env',return_value={}),patch.object(ai.subprocess,'Popen',side_effect=child):
   threads=[threading.Thread(target=work,args=(i,)) for i in range(2)]
   for thread in threads:thread.start()
   wait(lambda:len(started)==2);ai.cancel_job(events[0])
   for thread in threads:thread.join(5)
  self.assertEqual(results,{0:'stopped',1:'OK'});self.assertFalse(ai._processes)
 def test_cancel_queue_and_late_result_preserves_original_summary(self):
  with tempfile.TemporaryDirectory() as folder:
   service=Service(folder);release=threading.Event();started=threading.Event()
   first,_=service.archive.add('Running','a'*5000);second,_=service.archive.add('Queued','b'*5000)
   service.archive.update(first,summary='Previous summary',state='ready')
   def summarize(item,*args,**kwargs):
    started.set();release.wait(4)
    return {'summary':'Late replacement must not save','state':'ready','error':''}
   try:
    with patch.object(ai,'summary_fields',side_effect=summarize):
     service.queue(first,force=True);self.assertTrue(started.wait(2));service.queue(second,force=True)
     self.assertTrue(service.cancel_summary(second)['stopped']);self.assertTrue(service.cancel_summary(first)['stopped']);release.set()
     wait(lambda:not service.runtime()['processing'])
     self.assertEqual(service.archive.get(first)['summary'],'Previous summary');self.assertEqual(service.archive.get(second)['text'],'b'*5000)
     self.assertEqual(service.summary_jobs.snapshot(first)['stage'],'stopped');self.assertEqual(service.summary_jobs.snapshot(second)['stage'],'stopped')
     self.assertFalse(service.cancel_summary(first)['stopped'])
   finally:release.set();service.close()
 def test_error_categories(self):
  from secretary.task_status import explain
  for error,kind in [('deadline exceeded','timeout'),('HTTP 401 unauthorized','login'),('429 quota exceeded','quota'),('proxy connection refused','network'),('invalid JSON','format')]:self.assertEqual(explain(error)['kind'],kind)
