import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from secretary import company_ai,model_api
from secretary.server import Service
from secretary.backup_import import import_backup


class CompanyAITest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
        self.service.archive.configure('codex',True,capture_close_tabs=False)
        self.service.archive.set_company_mode(True)

    def tearDown(self):
        self.service.close();self.service.quick_pool.shutdown(wait=True);self.service.pool.shutdown(wait=True);self.temp.cleanup()

    def item(self):
        return self.service.ingest({'url':'https://intranet.company.test/report','text':'Confidential fixture project result. '*20,'captured_at':'fixture','archive_only':True})['item']['id']

    def approve(self):
        config=self.service.model_backend();info=company_ai.status(self.service.archive,config)
        company_ai.approve(self.service.archive,config,{'acknowledged':True,'fingerprint':info['fingerprint']})

    def wait(self,item):
        future=self.service.summary_futures.get(item)
        if future:future.result(timeout=5)

    def test_company_mode_is_off_by_default_and_only_enabled_mode_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            other=Service(root)
            try:self.assertFalse(other.archive.settings()['company_mode'])
            finally:other.close()
        self.service.archive.set_company_mode(False)
        item=self.item()
        with patch('secretary.ai.summary_fields',return_value={'summary':'Default mode summary','state':'ready'}) as model:
            self.service.queue(item);self.wait(item)
            self.assertEqual(model.call_count,1)
        self.assertEqual(self.service.archive.get(item)['summary'],'Default mode summary')
        self.service.archive.set_company_mode(True)
        with self.assertRaises(company_ai.ApprovalRequired):self.service.queue(item,force=True)
        self.approve();self.service.archive.set_company_mode(False);self.service.archive.set_company_mode(True)
        self.assertFalse(company_ai.status(self.service.archive,self.service.model_backend())['approved'])
        from secretary.core import Archive
        self.assertTrue(Archive(self.temp.name,recover=False).settings()['company_mode'])
        for invalid in (None,1,'true'):
            with self.assertRaises(ValueError):self.service.archive.set_company_mode(invalid)

    def test_unconfirmed_content_never_reaches_auto_manual_or_question_models(self):
        item=self.item()
        with patch('secretary.ai.run') as model:
            self.service.queue(item)
            self.assertEqual(self.service.archive.get(item)['state'],'saved')
            with self.assertRaises(company_ai.ApprovalRequired):self.service.queue(item,force=True)
            with self.assertRaises(company_ai.ApprovalRequired):self.service.ask('Confidential fixture project')
            current=self.service.archive.get(item)
            with self.assertRaises(company_ai.ApprovalRequired):self.service.append_material(item,{'text':'New private result','summarize':True,'expected_updated':current['updated']})
            self.service.process(item)
            model.assert_not_called()
        self.assertEqual(self.service.archive.get(item)['text'],current['text'])

    def test_once_confirmed_service_keeps_automatic_summaries_and_qa_usable(self):
        self.approve()
        with patch('secretary.ai.summary_fields',return_value={'summary':'Approved fixture summary','state':'ready'}) as model:
            first=self.item();self.service.queue(first);self.wait(first)
            self.assertEqual(self.service.archive.get(first)['summary'],'Approved fixture summary')
            second,_=self.service.archive.add('Another','Second protected fixture')
            company_ai.mark(self.service.archive,second);self.service.queue(second);self.wait(second)
            self.assertEqual(model.call_count,2)
        with patch('secretary.ai.run',return_value='Approved fixture answer') as answer:
            self.assertEqual(self.service.ask('Confidential fixture project')['answer'],'Approved fixture answer')
            answer.assert_called_once()
        company_ai.revoke(self.service.archive)
        with patch('secretary.ai.run') as model:
            with self.assertRaises(company_ai.ApprovalRequired):self.service.ask('Confidential fixture project')
            model.assert_not_called()

    def test_read_confirmation_and_auto_ai_off_do_not_force_a_summary(self):
        self.service.archive.configure('codex',False,capture_close_tabs=False)
        item,_=self.service.archive.add('Browser fixture',url='https://example.test/docs')
        stop=threading.Event();self.service.captures[item]=stop;self.service.login_confirmations[item]=threading.Event()
        result={'title':'Captured fixture','text':'Loaded confidential fixture text '*20}
        with patch('secretary.capture_worker.run',return_value=result),patch('secretary.ai.run') as model:
            self.service.capture(item,stop,False)
            model.assert_not_called()
        self.assertTrue(self.service.archive.get(item)['company_data'])
        self.assertEqual(self.service.archive.get(item)['text'],result['text'])

    def test_service_changes_invalidate_confirmation_and_stale_dialog_cannot_approve(self):
        self.approve();old=company_ai.status(self.service.archive,self.service.model_backend())
        self.service.save_settings({'backend':'gemini','auto_ai':True})
        self.assertFalse(company_ai.status(self.service.archive,self.service.model_backend())['approved'])
        with self.assertRaisesRegex(ValueError,'配置已变化'):
            company_ai.approve(self.service.archive,self.service.model_backend(),{'acknowledged':True,'fingerprint':old['fingerprint']})
        self.service.save_settings({'backend':'codex','auto_ai':True})
        self.assertFalse(company_ai.status(self.service.archive,self.service.model_backend())['approved'])

    def test_api_destination_model_and_credentials_are_bound_without_exposing_keys(self):
        config={**model_api.DEFAULT,'base_url':'https://approved.company.test/v1','model':'company-model','api_key':'synthetic-secret-key'}
        info=company_ai.descriptor(config)
        self.assertNotIn('synthetic-secret-key',json.dumps(info))
        for change in ({'base_url':'https://another.company.test/v1'},{'model':'other-model'},{'api_key':'different-synthetic-key'}):
            self.assertNotEqual(info['fingerprint'],company_ai.descriptor({**config,**change})['fingerprint'])
        with self.assertRaises(ValueError):company_ai.approve(self.service.archive,config,{'acknowledged':False,'fingerprint':info['fingerprint']})

    def test_backup_preserves_material_policy_but_not_model_approval(self):
        item=self.item();self.approve()
        with tempfile.TemporaryDirectory() as other:
            restored=Service(other)
            try:
                import_backup(restored.archive,self.service.backup())
                copied=restored.archive.get(restored.archive.list()[0]['id'])
                self.assertTrue(copied['company_data']);self.assertEqual(copied['text'],self.service.archive.get(item)['text'])
                self.assertFalse(company_ai.status(restored.archive,restored.model_backend())['approved'])
            finally:restored.close()

    def test_incomplete_api_config_can_still_show_settings_without_any_model_call(self):
        self.service.archive.configure('api',False)
        with patch('secretary.ai.run') as model:
            info=self.service.company_model_status()
            self.assertFalse(info['approved']);self.assertEqual(info['fingerprint'],'')
            model.assert_not_called()

    def test_queued_work_rechecks_destination_before_model_call(self):
        item=self.item();self.approve()
        with patch.object(self.service.quick_pool,'submit'):
            self.service.queue(item)
        self.service.save_settings({'backend':'claude','auto_ai':True})
        with patch('secretary.ai.run') as model:
            self.service.process(item);model.assert_not_called()
