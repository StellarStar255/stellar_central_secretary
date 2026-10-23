import subprocess,sys,tempfile,threading,time,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from secretary import capture_worker,browser_reader
from secretary.server import Service

class CaptureStopTest(unittest.TestCase):
 def test_stop_interrupts_stuck_browser_process_without_touching_other_process(self):
  # A blocked child stands in for a browser driver stuck in navigation.
  real_popen=subprocess.Popen;owned=[];other=real_popen([sys.executable,'-c','import time;time.sleep(30)'])
  def spawn(*args,**kwargs):
   proc=real_popen([sys.executable,'-c','import sys,time;sys.stdin.readline();time.sleep(30)'],**kwargs);owned.append(proc);return proc
  stop=threading.Event();errors=[]
  def run():
   try:capture_worker.run('web','https://example.test/',tempfile.gettempdir(),lambda *a:None,stop,threading.Event())
   except browser_reader.CaptureCancelled:errors.append('cancelled')
  try:
   with patch.object(capture_worker.subprocess,'Popen',side_effect=spawn):
    thread=threading.Thread(target=run);thread.start()
    deadline=time.monotonic()+3
    while not owned and time.monotonic()<deadline:time.sleep(.02)
    self.assertTrue(owned);start=time.monotonic();stop.set();thread.join(3)
   self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-start,3)
   self.assertEqual(errors,['cancelled']);self.assertIsNotNone(owned[0].poll());self.assertIsNone(other.poll())
  finally:
   other.terminate();other.wait()
   for proc in owned:capture_worker.terminate_job(proc)

 def test_waiting_page_does_not_block_other_capture_and_cancel_preserves_material(self):
  with tempfile.TemporaryDirectory() as root:
   service=Service(root);service.archive.configure('codex',False);waiting=threading.Event()
   first,_=service.archive.add('First','Original text',url='https://chatgpt.com/c/first');service.archive.update(first,summary='Original summary',state='ready')
   second,_=service.archive.add('Second','',url='https://chatgpt.com/c/second')
   def read(kind,url,profile,notify,stop,confirmation,**kwargs):
    if url.endswith('first'):
     notify('waiting_login','Waiting');waiting.set();stop.wait(5)
     # Even a late result must never overwrite the saved archive after stop.
     return {'title':'Late','text':'Late cancelled content'}
    return {'title':'Second','text':'Second readable body'}
   try:
    with patch.object(capture_worker,'run',side_effect=read):
     service.start_capture(first);self.assertTrue(waiting.wait(2));service.start_capture(second)
     deadline=time.monotonic()+2
     while second in service.captures and time.monotonic()<deadline:time.sleep(.02)
     self.assertEqual(service.archive.get(second)['text'],'Second readable body')
     self.assertTrue(service.cancel_capture(first)['stopped'])
    self.assertEqual(service.archive.get(first)['text'],'Original text');self.assertEqual(service.archive.get(first)['summary'],'Original summary')
    self.assertEqual(service.runtime()['reading'],0)
   finally:service.close()

 def test_queued_task_can_be_removed_without_ever_opening_browser(self):
  with tempfile.TemporaryDirectory() as root:
   service=Service(root);service.archive.configure('codex',False);service.capture_pool.shutdown();service.capture_pool=ThreadPoolExecutor(max_workers=1)
   gate=threading.Event();blocker=service.capture_pool.submit(gate.wait,3)
   item,_=service.archive.add('Queued','',url='https://chatgpt.com/c/queued')
   try:
    with patch.object(capture_worker,'run') as read:
     service.start_capture(item);self.assertEqual(service.archive.get(item)['state'],'queued_capture')
     self.assertTrue(service.cancel_capture(item)['stopped']);self.assertEqual(service.runtime()['reading'],0)
     gate.set();blocker.result();read.assert_not_called()
   finally:gate.set();service.close()

if __name__=='__main__':unittest.main()
