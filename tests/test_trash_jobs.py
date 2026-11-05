"""Trashing selected work cancels only that work and fences late results."""
import tempfile,threading,unittest
from unittest.mock import patch
from secretary import ai
from secretary.server import Service

class TrashJobsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.a=self.service.archive;self.a.configure('codex',False)
 def tearDown(self):self.service.close();self.temp.cleanup()
 def test_running_summary_can_be_trashed_and_restored_before_late_result(self):
  item,_=self.a.add('Selected work','Synthetic original text');self.a.update(item,summary='Keep existing summary');before=self.a.get(item)
  started=threading.Event();release=threading.Event()
  def model(*args,**kwargs):started.set();release.wait(10);return {'title':'Late title must not overwrite','summary':'Late summary must not overwrite','state':'ready','error':''}
  with patch.object(ai,'summary_fields',side_effect=model):
   try:
    self.service.queue(item,force=True);future=self.service.summary_futures[item];self.assertTrue(started.wait(3))
    self.service.trash_item(item,before['updated']);self.assertTrue(self.a.get(item,True)['trashed_at']);self.assertFalse(future.done())
    self.a.restore_item(item);release.set();future.result(timeout=3)
    after=self.a.get(item);self.assertEqual(after['title'],before['title']);self.assertEqual(after['text'],before['text']);self.assertEqual(after['summary'],before['summary']);self.assertNotIn(item,self.service.busy);self.assertNotIn(item,self.service.trash_cancellations)
   finally:release.set()
 def test_waiting_summary_is_canceled_without_model_call(self):
  item,_=self.a.add('Waiting work','Source',filename='sample.txt',data=b'Source')
  lane=self.service.summary_jobs.lanes['long'];lane.acquire()
  with patch.object(ai,'summary_fields') as model:
   try:
    self.service.queue(item,force=True);future=self.service.summary_futures[item]
    self.service.trash_item(item);future.result(timeout=3)
    self.assertFalse(model.called);self.assertTrue(self.a.get(item,True)['trashed_at']);self.assertNotIn(item,self.service.busy)
   finally:lane.release()
 def test_trash_does_not_cancel_other_item(self):
  selected,_=self.a.add('Selected','Long source',filename='selected.txt',data=b'Long source');other,_=self.a.add('Other','Short source')
  started=threading.Event();release=threading.Event()
  def model(item,*args,**kwargs):
   if item['id']==selected:started.set();release.wait(10)
   return {'summary':'Summary for '+item['title'],'state':'ready','error':''}
  with patch.object(ai,'summary_fields',side_effect=model):
   try:
    self.service.queue(selected,force=True);first=self.service.summary_futures[selected];self.assertTrue(started.wait(3))
    self.service.queue(other,force=True);second=self.service.summary_futures[other];second.result(timeout=3)
    self.service.trash_item(selected);release.set();first.result(timeout=3)
    self.assertEqual(self.a.get(other)['summary'],'Summary for Other');self.assertFalse(self.service.summary_jobs.cancelled(other));self.assertTrue(self.a.get(selected,True)['trashed_at'])
   finally:release.set()
 def test_late_capture_cannot_overwrite_restored_source_or_start_summary(self):
  item,_=self.a.add('Capture work','Keep source',url='http://127.0.0.1:19876/fixture');self.a.update(item,summary='Keep summary')
  started=threading.Event();release=threading.Event()
  def capture(*args,**kwargs):started.set();release.wait(10);return {'title':'Late capture','text':'Late captured source'}
  with patch('secretary.capture_worker.run',side_effect=capture),patch.object(self.service,'close_capture_browsers'),patch.object(ai,'summary_fields') as model:
   try:
    self.service.start_capture(item,force_summary=True);future=self.service.capture_futures[item];self.assertTrue(started.wait(3))
    self.service.trash_item(item);self.a.restore_item(item);release.set();future.result(timeout=3)
    after=self.a.get(item);self.assertEqual(after['title'],'Capture work');self.assertEqual(after['text'],'Keep source');self.assertEqual(after['summary'],'Keep summary');model.assert_not_called();self.assertNotIn(item,self.service.captures)
   finally:release.set()
 def test_repeated_trash_is_idempotent(self):
  item,_=self.a.add('Repeat','Source');self.service.trash_item(item)
  before=self.a.get(item,True);self.service.trash_item(item,'outdated')
  self.assertEqual(self.a.get(item,True),before)
 def test_worker_starting_after_trash_finishes_its_progress_record(self):
  item,_=self.a.add('Scheduled work','Source');self.service.busy.add(item);self.service.summary_jobs.enqueue(item)
  self.service.trash_item(item);self.service.process(item);self.a.restore_item(item)
  self.assertFalse(self.service.summary_jobs.snapshot(item)['active']);self.assertNotIn(item,self.service.busy);self.assertNotIn(item,self.service.trash_cancellations)
