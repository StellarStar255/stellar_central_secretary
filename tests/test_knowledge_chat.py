import json
import tempfile
import unittest
from unittest.mock import patch
from secretary import company_ai, knowledge_chat
from secretary.server import Service


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
        self.assertEqual(answering['question'],'它的内存要求呢？')
        self.assertEqual(self.service.runtime()['answering'],0)

    def test_empty_library_does_not_call_model(self):
        with patch('secretary.ai.run') as model:
            self.assertEqual(self.service.ask_library('如何部署？')['sources'],[])
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


if __name__=='__main__':unittest.main()
