import json,subprocess,sys,unittest
from unittest.mock import patch
from secretary import ai

class ModelTimeoutTest(unittest.TestCase):
    def test_cli_deadline_kills_worker_closes_pipes_and_removes_tracking(self):
        popen=subprocess.Popen;workers=[]
        def worker(*args,**kwargs):
            proc=popen([sys.executable,'-c','import sys,time; sys.stdin.read(); time.sleep(30)'],**kwargs)
            workers.append(proc)
            return proc
        with patch.object(ai,'executable',return_value='synthetic-cli'),patch.object(ai.subprocess,'Popen',side_effect=worker):
            with self.assertRaises(ai.ModelTimeoutError):ai.run('Test','codex',timeout=.05)
        proc=workers[0]
        self.assertIsNotNone(proc.poll());self.assertNotIn(proc,ai._processes)
        self.assertTrue(all(stream.closed for stream in (proc.stdin,proc.stdout,proc.stderr)))

    def test_cli_stop_does_not_return_a_late_success(self):
        from unittest.mock import Mock
        proc=Mock(returncode=0)
        def stop(*args,**kwargs):
            ai.cancel_all()
            return json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'late'}}),''
        proc.communicate.side_effect=stop
        with patch.object(ai,'executable',return_value='synthetic-cli'),patch.object(ai.subprocess,'Popen',return_value=proc),patch('secretary.capture_worker.terminate_job'):
            with self.assertRaisesRegex(RuntimeError,'停止'):ai.run('Test','codex')
