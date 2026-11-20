import io
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from secretary import ai, model_api, summary_language
from secretary.server import Service


class SummaryLanguageTests(unittest.TestCase):
    def test_auto_ignores_capture_markers_and_falls_back_for_short_sources(self):
        self.assertEqual(summary_language.detect('【部分对话归档】最近 20 轮，仅供核对\nThe garden will open on Saturday.'), 'en')
        self.assertEqual(summary_language.detect('English Report.pdf\n[第 5 页]\n这是一份以中文写成的会议记录。'), 'zh')
        self.assertIsNone(summary_language.detect('https://example.com/english-words\nGarden reference photo.png'))
        with summary_language.preferences({'summary_language':'auto','ui_language':'en'}):
            self.assertEqual(summary_language.resolve('123'), 'en')

    def test_stored_preference_applies_to_summary_jobs_without_changing_existing_summaries(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Service(folder)
            try:
                item, _ = service.archive.add('中文资料', '请在周末前完成这份中文会议记录。')
                service.archive.update(item,summary='先前已保存的摘要')
                self.assertEqual(service.archive.settings()['summary_language'],'auto')
                service.save_settings({'backend':'codex','auto_ai':False,'summary_language':'en'})
                self.assertEqual(service.archive.settings()['summary_language'],'en')
                self.assertEqual(service.archive.get(item)['summary'],'先前已保存的摘要')
                with patch.object(ai,'run',return_value='{"summary":"Finish writing the meeting notes by the weekend.","tags":[]}') as model:
                    service.process(item)
                self.assertIn('in English',model.call_args.args[0])
                self.assertEqual(service.archive.get(item)['summary'],'Finish writing the meeting notes by the weekend.')
                self.assertIsNone(summary_language.output.get())
                self.assertEqual(ai.model_rules(),ai.RULES)
            finally:
                service.close()

    def test_english_pdf_coverage_and_all_segment_calls_use_english(self):
        with summary_language.preferences({'summary_language':'en','ui_language':'zh'}):
            source='[第 1 页]\n'+('Water when the soil is dry. '*1000)
            with patch.object(ai,'run',side_effect=['Section one notes','Section two notes','{"summary":"A plant care guide.","tags":[]}']) as model:
                fields=ai.summary_fields({'title':'PDF','text':source,'filename':'guide.pdf'},'codex',full_pdf=True)
        self.assertEqual(model.call_count,3)
        self.assertTrue(all('in English' in call.args[0] for call in model.call_args_list))
        self.assertTrue(fields['summary'].startswith('[Full PDF summary]'))

    def test_api_system_rules_receive_summary_language(self):
        response=io.BytesIO(b'{"choices":[{"message":{"content":"English result"}}]}')
        opener=Mock()
        opener.open.return_value=response
        config={**model_api.DEFAULT,'base_url':'http://localhost:1234/v1','use_key':False}
        with patch.object(model_api.urllib.request,'build_opener',return_value=opener):
            model_api.complete(config,'Test',[],summary_language='en')
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertIn('in English',payload['messages'][0]['content'])
