"""The database must converge without a browser polling any endpoint."""
import sqlite3,tempfile,threading,unittest
from contextlib import closing
from unittest.mock import patch
from secretary import ai
from secretary.core import Archive
from secretary.server import Service

class BackgroundConvergenceTest(unittest.TestCase):
 def test_completion_failure_and_restart_do_not_require_gui(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root);s.archive.configure('codex',False)
   try:
    for failure in (False,True):
     item=s.archive.add('Background '+str(failure),'Source '+str(failure))[0]
     entered=threading.Event();release=threading.Event()
     def summarize(*args,**kwargs):
      entered.set();release.wait(3)
      if failure:raise ai.ModelTimeoutError('Synthetic timeout')
      return {'summary':'Completed without GUI','state':'ready','error':''}
     with patch('secretary.ai.summary_fields',side_effect=summarize):
      s.queue(item,force=True);self.assertTrue(entered.wait(2))
      with s.lock:future=s.summary_futures[item]
      # No HTTP server, GUI, details request or status polling is started.
      release.set();future.result(3)
     with closing(sqlite3.connect(s.archive.root/'archive.sqlite3')) as db:
      state,summary,error=db.execute('SELECT state,summary,error FROM items WHERE id=?',(item,)).fetchone()
     self.assertEqual(state,'error' if failure else 'ready')
     self.assertEqual(bool(summary),not failure);self.assertEqual(bool(error),failure)
     self.assertEqual(s.runtime()['processing'],0)
    interrupted=s.archive.add('Interrupted','Saved source')[0];s.archive.update(interrupted,state='processing')
   finally:s.close()
   recovered=Archive(root)
   self.assertEqual(recovered.get(interrupted)['state'],'pending')
   self.assertIn('中断',recovered.get(interrupted)['error'])
