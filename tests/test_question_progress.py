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

    def test_excerpts_are_separate_from_stage_labels(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            service.archive.add('Private course title','课程表：周四14:00有课。');stages=[]
            try:
                with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','14:00有课。[1]']):
                    service.ask_library('课程表有课吗？',progress=lambda name,count:stages.append((name,count)))
                self.assertEqual([name for name,count in stages if name!='excerpts'],['preparing','queued','planning','retrieving','images','answering'])
                self.assertEqual(stages[-1][1],1)
                self.assertNotIn('Private',str([s for s in stages if s[0]!='excerpts']))
                self.assertEqual(next(count for name,count in stages if name=='excerpts')[0]['title'],'Private course title')
                stages=[]
                with patch('secretary.ai.run',side_effect=AssertionError('No model')):
                    service.ask_library('你好呀',progress=lambda name,count:stages.append((name,count)))
                self.assertEqual(stages,[('preparing',None)])
            finally:service.close()


class QuestionCancellationTest(unittest.TestCase):
    def test_cancel_before_start_and_terminal_progress_cannot_be_resurrected(self):
        progress=QuestionProgress();key='d'*32
        self.assertTrue(progress.cancel(key))
        with self.assertRaises(ValueError):progress.begin(key)
        self.assertTrue(progress.event(key).is_set())
        progress.update(key,'done');progress.partial(key,'Late unverified answer')
        self.assertEqual(progress.snapshot(key)['stage'],'cancelled')
        self.assertNotIn('partial',progress.snapshot(key))
        other='e'*32;progress.begin(other);progress.update(other,'done')
        progress.partial(other,'late');progress.update(other,'answering');progress.update(other,'excerpts',[{}])
        self.assertEqual(progress.snapshot(other)['stage'],'done')
        self.assertNotIn('partial',progress.snapshot(other));self.assertNotIn('excerpts',progress.snapshot(other))
        self.assertFalse(progress.cancel(other));self.assertFalse(progress.event(other).is_set())
