import json
import io
import base64
import tempfile
import unittest
from unittest.mock import patch
from secretary import company_ai, knowledge_chat
from secretary.server import Service
from PIL import Image


class KnowledgeChatTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.service=Service(self.temp.name)
        self.service.archive.configure('codex',False)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_synonym_planning_and_followup_use_real_sources(self):
        item,_=self.service.archive.add('部署指南','Ollama supports offline inference on Apple Silicon. Requires 16 GB RAM.')
        history=[dict(question='有哪些离线模型方案？',answer='可以使用 Ollama。[1]',source_ids=[item])]
        with patch('secretary.ai.run',side_effect=['{"queries":["Ollama RAM","Apple Silicon"]}','需要 16 GB 内存。[1]']) as model:
            result=self.service.ask_library('它的内存要求呢？',history)
        self.assertEqual(result['sources'][0]['item_id'],item)
        self.assertEqual(result['sources'][0]['number'],1)
        self.assertEqual(len(result['sources']),1)
        planning=json.loads(model.call_args_list[0].args[0].split('\n',1)[1])
        self.assertEqual(planning['history'][0]['answer'],history[0]['answer'])
        answering=json.loads(model.call_args_list[1].args[0].split('\n',1)[1])
        self.assertIn('16 GB',answering['passages'][0]['text'])
        self.assertEqual(result['answer_evidence']['passage_count'],len(answering['passages']))
        self.assertEqual(result['answer_evidence']['history_turns'],len(answering['history']))
        self.assertEqual(answering['question'],'它的内存要求呢？')
        self.assertEqual(self.service.runtime()['answering'],0)

    def test_named_definitions_skip_planning_only_with_evidence(self):
        item,_=self.service.archive.add('测试资料','SQLite 是一种嵌入式数据库。')
        for question in ('什么是SQLite？','What is SQLite?'):
            with patch('secretary.ai.run',return_value='嵌入式数据库。[1]') as model:
                result=self.service.ask_library(question)
                self.assertEqual(model.call_count,1)
                self.assertEqual(result['sources'][0]['item_id'],item)
                self.assertIn('"passages"',model.call_args.args[0])
        for question in ('SQLite 和其他数据库的区别是什么？','什么是未知术语？'):
            self.assertIsNone(knowledge_chat.definition_plan(self.service.archive,question))
        with patch('secretary.ai.run',side_effect=['{"queries":["SQLite"]}','复核。[1]']) as model:
            self.service.ask_library('什么是SQLite？',force_refresh=True)
            self.assertEqual(model.call_count,2)

    def test_explicit_keyword_catalog_remains_local_and_pageable(self):
        for i in range(23):self.service.archive.add('SQLite 笔记',f'SQLite 测试记录 {i}')
        with patch.object(self.service,'model_backend',side_effect=AssertionError('Local search only')):
            for q in ('列出所有包含「SQLite」的资料','List all records containing "SQLite"'):
                result=self.service.ask_library(q)
                self.assertEqual(result['timings']['model_calls'],0)
                self.assertEqual(result['catalog']['total'],23)
                self.assertEqual(len(result['sources']),20)
                next_page=self.service.catalog_page(dict(result['catalog'],offset=20))
                self.assertEqual(len(next_page['sources']),3)
            for q in ('列出包含「SQLite 历史」的资料','列出包含「SQLite 记录」的资料'):
                self.assertEqual(self.service.ask_library(q)['catalog']['total'],0)

    def test_catalog_reloads_last_available_page_after_removals(self):
        ids=[self.service.archive.add('库存',f'库存记录 {i}')[0] for i in range(24)]
        page=self.service.ask_library('列出包含「库存记录」的资料')['catalog']
        for key in ids[:6]:
            self.service.archive.trash_item(key,self.service.archive.get(key)['updated'])
        result=self.service.catalog_page(dict(page,offset=20))
        self.assertEqual(result['catalog']['offset'],0)
        self.assertEqual({hit['item_id'] for hit in result['sources']},set(ids[6:]))
        self.assertEqual(result['catalog']['total'],18)

    def test_definition_uses_whole_original_term_in_one_field(self):
        self.service.archive.add('Graph API','Gateway deployment. Graph APIs are listed below.')
        for question in ('What is Graph API Gateway?', 'What is Graph APIs are lis?'):
            self.assertIsNone(knowledge_chat.definition_plan(self.service.archive,question))
        self.assertIsNotNone(knowledge_chat.definition_plan(self.service.archive,'什么是Graph API？'))
        with patch('secretary.ai.run',side_effect=['{"queries":["Graph API"]}','网关配置。[1]']) as model:
            result=self.service.ask_library('What is Graph API Gateway?')
            self.assertEqual(model.call_count,2)
            self.assertTrue(result['sources'])

    def test_grounded_new_questions_skip_only_planning(self):
        person,_=self.service.archive.add('示例甲的个人资料','示例甲的出生日期：1995年8月12日。')
        visit,_=self.service.archive.add('医院门诊预约','就诊日期：2026年11月28日，预约时间：10:30–11:00。')
        project,_=self.service.archive.add('青杉计划','负责人：示例乙。')
        history=[dict(question='示例甲的生日',answer='档案中有出生日期。[1]',source_ids=[person])]
        for question,expected in [('我的生日呢？',person),('明天看病是几点？',visit),('「青杉计划」的负责人是谁？',project),('青杉计划的负责人是谁？',project)]:
            def reply(prompt,*args,**kwargs):
                data=json.loads(prompt.split('\n',1)[1])
                hits=[p for p in data['passages'] if p['title']==self.service.archive.get(expected)['title']]
                self.assertTrue(hits)
                if question=='我的生日呢？':
                    self.assertEqual(data['history'][-1]['question'],'示例甲的生日')
                if question=='明天看病是几点？':
                    self.assertIn('current_time',data)
                    self.assertNotIn('示例甲的个人资料',[p['title'] for p in data['passages']])
                return '已核对。['+str(hits[0]['source'])+']'
            with patch('secretary.ai.run',side_effect=reply) as model:
                result=self.service.ask_library(question,history)
                self.assertTrue(result['timings']['local_plan'])
                self.assertEqual(model.call_count,1)
                self.assertEqual(result['sources'][0]['item_id'],expected)

    def test_weak_evidence_or_recheck_uses_normal_planner(self):
        self.service.archive.add('预约', '门诊暂未公布时间。')
        for q in ('我的生日呢？','明天看病是几点？','明天挂号需要带什么？','「青杉计划」的地点在哪里？'):
            self.assertIsNone(knowledge_chat.grounded_lookup(self.service.archive,q,[],None,[]))
        self.service.archive.add('资料摘录','青杉计划的负责人仍未确定。')
        self.assertIsNone(knowledge_chat.grounded_lookup(self.service.archive,'青杉计划的负责人是谁？',[],None,[]))
        self.service.archive.add('就诊安排','明天看病时间为下午三点。')
        with patch('secretary.ai.run',side_effect=['{"queries":["就诊安排"]}','下午三点。[1]']) as model:
            self.service.ask_library('明天看病是几点？',force_refresh=True)
            self.assertEqual(model.call_count,2)

    def test_empty_library_does_not_call_model(self):
        with patch('secretary.ai.run') as model:
            result=self.service.ask_library('如何部署？')
            self.assertEqual(result['sources'],[])
            self.assertEqual(result['answer_evidence']['kind'],'no_match')
            model.assert_not_called()

    def test_no_evidence_does_not_generate_an_answer(self):
        self.service.archive.add('天文','Galaxy astronomy observations')
        with patch('secretary.ai.run',return_value='{"queries":["Ollama"]}') as model:
            result=self.service.ask_library('quantization')
        self.assertEqual(result['sources'],[])
        self.assertIn('没有找到',result['answer'])
        self.assertEqual(model.call_count,1)

    def test_malformed_plan_falls_back_to_literal_question(self):
        item,_=self.service.archive.add('Memory','Ollama RAM requirement is 16 GB')
        with patch('secretary.ai.run',side_effect=['not JSON','16 GB [1]']):
            self.assertEqual(self.service.ask_library('Ollama RAM')['sources'][0]['item_id'],item)

    def test_runtime_is_cleared_on_planning_and_answer_errors(self):
        self.service.archive.add('Memory','Ollama RAM requirement')
        for outputs in ([RuntimeError('failed')],['{"queries":["Ollama"]}',RuntimeError('failed')]):
            with patch('secretary.ai.run',side_effect=outputs):
                with self.assertRaisesRegex(RuntimeError,'failed'):self.service.ask_library('Ollama')
            self.assertEqual(self.service.runtime()['answering'],0)

    def test_company_sources_checked_before_answering_and_before_history_planning(self):
        item,_=self.service.archive.add('Private','Confidential Ollama deployment')
        company_ai.mark(self.service.archive,item)
        self.service.archive.set_company_mode(True)
        with patch('secretary.ai.run',return_value='{"queries":["Ollama"]}') as model:
            with self.assertRaises(company_ai.ApprovalRequired):self.service.ask_library('Ollama')
            self.assertEqual(model.call_count,1)  # Planner sees only the user's question.
            model.reset_mock()
            with self.assertRaises(company_ai.ApprovalRequired):
                self.service.ask_library('继续',[dict(question='Ollama',answer='Private facts',source_ids=[item])])
            model.assert_not_called()
        info=company_ai.status(self.service.archive,self.service.model_backend())
        company_ai.approve(self.service.archive,self.service.model_backend(),dict(acknowledged=True,fingerprint=info['fingerprint']))
        with patch('secretary.ai.run',side_effect=['{"queries":["Ollama"]}','Approved [1]']):
            self.assertEqual(self.service.ask_library('Ollama')['answer'],'Approved [1]')

    def test_trashed_sources_are_excluded(self):
        item,_=self.service.archive.add('Discarded','Ollama RAM')
        self.service.archive.add('Other','Astronomy')
        self.service.archive.trash_item(item,self.service.archive.get(item)['updated'])
        with patch('secretary.ai.run',return_value='{"queries":["Ollama"]}'):
            self.assertEqual(self.service.ask_library('Ollama')['sources'],[])

    def test_model_destination_is_rechecked_for_historical_sources(self):
        private,_=self.service.archive.add('Private','Secret historical answer')
        self.service.archive.add('Public','Ollama memory')
        company_ai.mark(self.service.archive,private)
        self.service.archive.set_company_mode(True)
        config=self.service.model_backend();info=company_ai.status(self.service.archive,config)
        company_ai.approve(self.service.archive,config,dict(acknowledged=True,fingerprint=info['fingerprint']))
        def planner(*args,**kwargs):
            self.service.archive.configure('claude',False)
            return '{"queries":["Ollama"]}'
        with patch('secretary.ai.run',side_effect=planner) as model:
            with self.assertRaises(company_ai.ApprovalRequired):
                self.service.ask_library('内存要求',[dict(question='旧问题',answer='Secret historical answer',source_ids=[private])])
            self.assertEqual(model.call_count,1)

    def test_history_is_validated_and_bounded(self):
        for value in ({},[{}],[dict(question='x',answer='y',source_ids=['bad'])],[{}]*7):
            with self.assertRaises(ValueError):knowledge_chat.history(value)
        turn=knowledge_chat.history([dict(question='x'*3000,answer='y'*5000)])[0]
        self.assertEqual(len(turn['question']),2000)
        self.assertEqual(len(turn['answer']),4000)

    def test_specific_planned_keywords_do_not_fill_sources_with_generic_today_matches(self):
        schedule,_=self.service.archive.add('课程表','11月2日至8日的课程表，周四所示区域无课程。')
        for title in ('罗马皇位继承','消费贷款','登山笔记'):
            self.service.archive.add(title,'今天下午讨论这个话题，问题是有没有安排。')
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','这份课表只覆盖11月2日至8日，不能证明今天的课程。[1]']):
            result=self.service.ask_library('我老婆今天下午有课吗？')
        self.assertEqual([source['item_id'] for source in result['sources']],[schedule])

    def test_only_cited_sources_are_returned_and_invalid_citations_are_rejected(self):
        hits=[dict(item_id='a',title='无关'),dict(item_id='b',title='课表')]
        self.assertEqual(knowledge_chat.citations('根据旧课表仍不能确认。[2]',hits),[dict(hits[1],number=2)])
        self.assertEqual(knowledge_chat.citations('没有足够信息。',hits),[])
        with self.assertRaises(ValueError):knowledge_chat.citations('有课。[8]',hits)

    def test_followup_reloads_prior_cited_document_even_without_current_term_match(self):
        schedule,_=self.service.archive.add('课程表','11月2日至8日，周四可见区域无课。')
        turns=[dict(question='今天下午有课吗',answer='只能确认旧周课表。[1]',source_ids=[schedule])]
        with patch('secretary.ai.run',side_effect=['{"queries":["仔细核对"],"followup":true}','核对的仍是旧周课表，不能推断今天。[1]']) as model:
            result=self.service.ask_library('再仔细看看',turns)
        payload=json.loads(model.call_args_list[-1].args[0].split('\n',1)[1])
        self.assertIn('11月2日至8日',payload['passages'][0]['text'])
        self.assertIn('weekday',payload['current_time'])
        self.assertEqual(result['sources'][0]['item_id'],schedule)

    def test_schedule_question_rechecks_saved_image_without_rewriting_archive(self):
        image=io.BytesIO();Image.new('RGB',(800,1200),'white').save(image,'PNG')
        item=self.service.ingest({'text':'2026年课程表','attachments':[{'name':'timetable.png','data':base64.b64encode(image.getvalue()).decode()}],'archive_only':True})['item']['id']
        self.service.archive.update(item,title='课程表',vision_text='第9周，2026年11月2日至8日。星期四没有可见课程块。')
        before=self.service.archive.get(item)
        with patch('secretary.ai.run',side_effect=['{"queries":["课程表"]}','已核对原图，只能确认11月2日至8日的安排。[1]']) as model:
            result=self.service.ask_library('看下课程表再告诉我')
        call=model.call_args_list[-1]
        self.assertEqual(len(call.kwargs['images']),1)
        self.assertTrue(call.kwargs['images'][0]['data'].startswith(b'\xff\xd8'))
        payload=json.loads(call.args[0].split('\n',1)[1])
        self.assertEqual(payload['visual_evidence'][0]['status'],'image_attached_for_rechecking')
        self.assertIn(result['sources'][0]['item_id'],[item])
        self.assertEqual(self.service.archive.get(item),before)


if __name__=='__main__':unittest.main()
