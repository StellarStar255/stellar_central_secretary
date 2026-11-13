"""Synthetic reproductions of reported conversations; no personal library fixtures."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from secretary import ai
from secretary.server import Service
from secretary.knowledge_chat import quick_plan,SearchPlan
from secretary.conversation_context import for_sources
from secretary.library import dashboard

CASES=json.loads((Path(__file__).parent/'fixtures/conversation_regressions.json').read_text())

class ConversationRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.service.archive.configure('codex',False)
        self.course=self.service.archive.add('课程表','课程表：周一09:45有材料课；周二下午无课；周四14:00有课。')[0]
        self.rome=self.service.archive.add('罗马皇位继承','罗马皇位由军队拥立和政治承认影响。')[0]
        self.daughter=self.service.archive.add('女儿课程','女儿：周二上午有课。')[0]
        self.turns=[{'question':'我老婆今天下午有课吗？','answer':'课表周四14:00有课。[1]','source_ids':[self.course]}]

    def tearDown(self):self.service.close();self.temp.cleanup()

    def test_reported_question_matrix_sources_and_call_budget(self):
        for case in CASES:
            with self.subTest(case=case['name']):
                turns=[] if case['name']=='schedule_today' else self.turns
                expected={'course':self.course,'rome':self.rome,'daughter':self.daughter}[case['topic']]
                captured=[]
                def model(prompt,backend,**kwargs):
                    captured.append(prompt)
                    if prompt.startswith('为个人知识库生成全文检索词'):
                        return json.dumps({'queries':case.get('queries',[]),'catalog':case.get('catalog',False),'followup':False})
                    payload=json.loads(prompt.split('\n',1)[1])
                    source=next(p['source'] for p in payload['passages'] if p['title']==self.service.archive.get(expected)['title'])
                    return '依据资料作答。['+str(source)+']'
                with patch('secretary.ai.run',side_effect=model):result=self.service.ask_library(case['question'],turns,force_refresh=True)
                self.assertEqual(result['timings']['fast_followup'],case['quick'])
                self.assertEqual(result['timings']['model_calls'],1 if case['quick'] or case.get('catalog') else 2)
                self.assertEqual({s['item_id'] for s in result['sources']},{expected})
                self.assertGreaterEqual(result['timings']['total_seconds'],0)

    def test_scoped_conditions_cannot_leak_to_a_new_topic(self):
        condition={'statement':'这张课表就是她的，按这个判断就行','source_ids':[self.course]}
        with patch('secretary.ai.run',side_effect=['{"queries":["罗马"]}','继承规则。[1]']) as model:
            self.service.ask_library('罗马皇位如何继承？',self.turns,context=[condition])
        payload=json.loads(model.call_args.args[0].split('\n',1)[1])
        self.assertEqual(payload['history'],[])
        self.assertEqual(for_sources(self.turns,[self.course]),self.turns)

    def test_document_changed_does_not_reuse_an_old_answer(self):
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','周四有课。[1]']):before=self.service.ask_library('查课程表')
        self.service.archive.update(self.course,text='课程表：周四已取消。')
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','周四已取消。[1]']) as model:after=self.service.ask_library('查课程表')
        self.assertEqual(model.call_count,2);self.assertNotEqual(before['sources'][0]['revision'],after['sources'][0]['revision'])
        self.assertNotIn('cache_hit',after['timings'])
        self.service.trash_item(self.course)
        states=dashboard(self.service.archive,[self.course])['source_states']
        self.assertEqual(states[self.course]['state'],'trashed')
        self.assertEqual(dashboard(self.service.archive,['f'*32])['source_states']['f'*32]['state'],'missing')

    def test_scoped_cancel_releases_interactive_lane_without_stopping_summary(self):
        entered=threading.Event();cancel=threading.Event();errors=[]
        def model(*args,**kwargs):
            entered.set()
            while not cancel.wait(.01):pass
            ai.check_cancelled()
            raise AssertionError('Cancellation must interrupt this request')
        def ask():
            try:self.service.ask_library('课程表',cancel=cancel)
            except ai.ModelCancelledError:errors.append('cancelled')
        with patch('secretary.ai.run',side_effect=model):
            worker=threading.Thread(target=ask);worker.start();self.assertTrue(entered.wait(2));ai.cancel_job(cancel);worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,['cancelled']);self.assertEqual(self.service.runtime()['answering'],0)
        self.assertFalse(self.service.answer_cache.entries)
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','有课。[1]']):self.assertTrue(self.service.ask_library('课程表')['sources'])

    def test_ambiguous_ellipsis_and_long_documents_keep_planning(self):
        self.assertIsNone(quick_plan('那周二我女儿呢？',self.turns))
        self.assertIsNone(quick_plan('那周二呢？',[{'question':'罗马史','answer':'历史内容','source_ids':[self.rome]}]))
        self.service.archive.update(self.course,text='课程表长文。'*3000)
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','资料内容。[1]']) as model:result=self.service.ask_library('那周二呢？',self.turns)
        self.assertEqual(model.call_count,2);self.assertFalse(result['timings']['fast_followup'])


    def test_removed_history_is_not_sent_even_when_other_sources_exist(self):
        self.service.trash_item(self.course)
        with patch('secretary.ai.run',side_effect=['{"queries":["罗马"]}','继承规则。[1]']) as model:
            self.service.ask_library('罗马皇位继承？',self.turns)
        payload=json.loads(model.call_args_list[0].args[0].split('\n',1)[1])
        self.assertEqual(payload['history'],[])

    def test_queued_cancel_does_not_cancel_independent_summary_lane(self):
        cancel=threading.Event();started=threading.Event();outcome=[]
        lane=self.service.summary_jobs.lanes['interactive'];lane.acquire()
        def ask():
            started.set()
            try:self.service.ask_library('课表',cancel=cancel)
            except ai.ModelCancelledError:outcome.append('stopped')
        worker=threading.Thread(target=ask)
        try:
            with self.service.summary_jobs.session('independent-summary',short=True):
                with patch('secretary.ai.run',side_effect=AssertionError('A cancelled queued request must not call a model')):
                    worker.start();self.assertTrue(started.wait(1));ai.cancel_job(cancel);worker.join(2)
                self.assertFalse(self.service.summary_jobs.cancelled('independent-summary'))
            self.assertFalse(worker.is_alive());self.assertEqual(outcome,['stopped'])
        finally:
            cancel.set();lane.release();worker.join(2)
