import tempfile,unittest
from unittest.mock import patch
from secretary.question_progress import QuestionProgress
from secretary.server import Service


class QuestionProgressTest(unittest.TestCase):
    def test_request_isolation_validation_and_terminal_state(self):
        progress=QuestionProgress();a='a'*32;b='b'*32
        progress.begin(a);progress.begin(b);progress.update(a,'answering',2)
        self.assertEqual(progress.snapshot(a)['stage'],'answering')
        self.assertEqual(progress.snapshot(a)['count'],2)
        self.assertEqual(progress.snapshot(b)['stage'],'preparing')
        with self.assertRaises(ValueError):progress.begin(a)
        with self.assertRaises(ValueError):progress.snapshot('../invalid')
        progress.update(a,'error');progress.begin(a)
        progress.update(a,'done');self.assertEqual(progress.snapshot(a)['stage'],'done')
        with patch('secretary.question_progress.time.monotonic',return_value=progress.records[a]['ended']+121):
            progress.begin('c'*32)
        self.assertNotIn(a,progress.records)

    def test_real_operations_emit_stages_without_content(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            service.archive.add('Private course title','课程表：周四14:00有课。');stages=[]
            try:
                with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','14:00有课。[1]']):
                    service.ask_library('课程表有课吗？',progress=lambda name,count:stages.append((name,count)))
                self.assertEqual([name for name,count in stages],['preparing','queued','planning','retrieving','images','answering'])
                self.assertEqual(stages[-1][1],1)
                self.assertNotIn('Private',str(stages))
                stages=[]
                with patch('secretary.ai.run',side_effect=AssertionError('No model')):
                    service.ask_library('你好呀',progress=lambda name,count:stages.append((name,count)))
                self.assertEqual(stages,[('preparing',None)])
            finally:service.close()
