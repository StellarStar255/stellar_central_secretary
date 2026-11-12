import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from secretary.server import Service


class KnowledgeChatSpeedTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
        self.service.archive.configure('codex',False)

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def context(self,text='周四下午13:00—16:10无课。'):
        item,_=self.service.archive.add('课程表',text)
        return item,[dict(question='她下午有课吗？',answer='课表所示时段无课。[1]',source_ids=[item])]

    def test_social_messages_need_no_model_configuration_or_library(self):
        self.service.archive.configure('api',False)
        with patch('secretary.ai.run',side_effect=AssertionError('No model for greetings')),patch.object(self.service.archive,'retrieve',side_effect=AssertionError('No search for greetings')):
            for question in ['你好呀',' 您好！ ','谢谢你！','HELLO!', 'Thank you.','早上好']:
                with self.subTest(question=question):
                    result=self.service.ask_library(question)
                    self.assertTrue(result['answer'])
                    self.assertEqual(result['sources'],[])
                    self.assertTrue(result['local_reply'])
                    self.assertEqual(result['timings']['model_calls'],0)

    def test_social_prefix_does_not_swallow_material_question(self):
        self.context()
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','无课。[1]']) as model:
            result=self.service.ask_library('你好呀，帮我找课程表')
        self.assertEqual(model.call_count,2)
        self.assertTrue(result['sources'])

    def test_creative_chat_finishes_in_first_model_call_without_search(self):
        self.context()
        with patch('secretary.ai.run',return_value=json.dumps(dict(route='chat',answer='月光洒在窗前。',queries=[]))) as model,patch.object(self.service.archive,'retrieve',side_effect=AssertionError('No library search for creative chat')):
            result=self.service.ask_library('写一句关于月亮的诗')
        self.assertEqual(model.call_count,1)
        self.assertEqual(result['answer'],'月光洒在窗前。')
        self.assertEqual(result['sources'],[])
        self.assertTrue(result['timings']['general_chat'])

    def test_explicit_clarification_uses_one_model_call_with_fresh_evidence(self):
        item,turns=self.context()
        self.service.archive.update(item,text='最新课表：周四下午14:00有材料课。')
        with patch('secretary.ai.run',return_value='按新课表14:00有课。[1]') as model:
            result=self.service.ask_library('这个课程表就是她的，依据这个判断就行',turns)
        self.assertEqual(model.call_count,1)
        payload=json.loads(model.call_args.args[0].split('\n',1)[1])
        self.assertIn('14:00有材料课',payload['passages'][0]['text'])
        self.assertEqual(model.call_args.kwargs['reasoning_effort'],'low')
        self.assertTrue(result['timings']['fast_followup'])
        self.assertEqual(result['timings']['model_calls'],1)
        self.assertGreaterEqual(result['timings']['total_seconds'],result['timings']['answer_seconds'])

    def test_new_topic_keeps_query_planning(self):
        _,turns=self.context()
        other,_=self.service.archive.add('Roman history','Roman succession history')
        with patch('secretary.ai.run',side_effect=['{"queries":["Roman succession"],"followup":false}','Succession answer [1]']) as model:
            result=self.service.ask_library('Roman succession?',turns)
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['sources'][0]['item_id'],other)
        self.assertFalse(result['timings']['fast_followup'])
        self.assertEqual(model.call_args_list[0].kwargs['reasoning_effort'],'low')

    def test_long_document_falls_back_and_retrieves_relevant_late_chunk(self):
        _,turns=self.context('无关前文。'*2000+' LATETOKEN：下午14:00有课。')
        with patch('secretary.ai.run',side_effect=['{"queries":["LATETOKEN"]}','14:00有课。[1]']) as model:
            result=self.service.ask_library('依据这个判断就行',turns)
        self.assertFalse(result['timings']['fast_followup'])
        self.assertEqual(model.call_count,2)
        payload=json.loads(model.call_args.args[0].split('\n',1)[1])
        self.assertIn('LATETOKEN',payload['passages'][0]['text'])

    def test_complex_question_keeps_medium_reasoning(self):
        self.context()
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','详细分析结果。[1]']) as model:
            self.service.ask_library('请详细分析课程表')
        self.assertEqual(model.call_args.kwargs['reasoning_effort'],'medium')

    def test_background_short_summary_does_not_block_library_question(self):
        self.context();busy=threading.Event();release=threading.Event();done=threading.Event();errors=[]
        def summary():
            with self.service.summary_jobs.session('synthetic-background',short=True):
                busy.set();release.wait(5)
        def question():
            try:self.service.ask_library('课程表')
            except Exception as exc:errors.append(exc)
            finally:done.set()
        worker=threading.Thread(target=summary);worker.start();self.assertTrue(busy.wait(1))
        answering=None
        try:
            with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','无课。[1]']):
                answering=threading.Thread(target=question);answering.start()
                self.assertTrue(done.wait(2),'A held background-summary lane must not block an interactive question')
            self.assertEqual(errors,[])
        finally:
            release.set();worker.join(2)
            if answering:answering.join(2)


if __name__=='__main__':unittest.main()
