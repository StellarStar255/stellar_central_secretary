import re
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from secretary import ai, browser_reader as reader
from secretary.server import Service


def turn(i):
    return [{'id':f'u{i}','role':'user','text':f'第{i}轮问题，需要记录。'},
            {'id':f'a{i}','role':'assistant','text':f'第{i}轮的回答，保留表格、图表和详细正文。'}]


class CaptureRangesTest(unittest.TestCase):
    def test_partial_capture_does_not_wait_for_whole_page_signature_to_stabilize(self):
        page=Mock();page.url='https://chatgpt.com/c/fixture';page.is_closed.return_value=False
        page.title.return_value='测试会话';page.evaluate.return_value=turn(100)
        context=Mock();context.pages=[page];browser=Mock();browser.contexts=[context]
        snapshots=[{'messages':turn(i),'diagnostics':{'generating':False}} for i in (98,99,100)]
        with patch.object(reader,'snapshot',side_effect=snapshots) as snapshot:
            result=reader.read_from_browser(Mock(),{},page.url,Mock(),threading.Event(),browser=browser,scope='loaded')
        self.assertTrue(result['partial'])
        self.assertEqual(snapshot.call_count,2)
        self.assertIn(reader.PARTIAL_PREFIX,result['text'])

    def test_recent_range_keeps_latest_twenty_rounds_without_reaching_history_top(self):
        page=Mock();window={'end':100};directions=[]
        def evaluate(script):
            if script==reader.MESSAGES_SCRIPT:
                return [m for i in range(window['end']-5,window['end']+1) for m in turn(i)]
            direction=re.search(r"node.scrollTop='(\w+)'",script).group(1)
            directions.append(direction)
            if direction=='bottom':window['end']=100
            elif direction=='up':window['end']-=4
            return {'top':100,'max':10000,'bottom':direction=='bottom'}
        page.evaluate.side_effect=evaluate
        messages=reader.collect_messages(page,threading.Event(),scope='recent')
        self.assertEqual([m['id'] for m in messages],[f'{role}{i}' for i in range(81,101) for role in ('u','a')])
        self.assertNotIn('top',directions)
        self.assertLess(directions.count('up'),24)

    def test_loaded_content_never_scrolls_and_recent_budget_does_not_fail(self):
        page=Mock();page.evaluate.return_value=turn(100)
        self.assertEqual(reader.collect_messages(page,threading.Event(),scope='loaded'),turn(100))
        page.evaluate.assert_called_once_with(reader.MESSAGES_SCRIPT)
        page=Mock()
        page.evaluate.side_effect=lambda script:turn(100) if script==reader.MESSAGES_SCRIPT else {'top':100,'bottom':False}
        self.assertEqual(reader.collect_messages(page,threading.Event(),scope='recent'),turn(100))
        self.assertEqual(page.wait_for_timeout.call_count,27)

    def test_partial_capture_cannot_overwrite_existing_full_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp);service.archive.configure('codex',False)
            original,_=service.archive.add('完整资料','用户：\n完整的问题\n\nChatGPT：\n完整的既有正文。',url='https://chatgpt.com/c/fixture')
            service.archive.update(original,summary='完整摘要',state='ready')
            before=service.archive.get(original)
            sliced=reader.PARTIAL_PREFIX+' 最近片段，不是完整历史。\n\n'+reader.message_text(turn(100))
            try:
                with self.assertRaisesRegex(ValueError,'不能覆盖'):
                    service.archive.replace_capture(original,'部分',sliced,partial=True)
                stop=threading.Event();service.captures[original]=stop;service.login_confirmations[original]=threading.Event()
                result={'title':'最近片段','text':sliced,'partial':True,'capture_scope':'recent'}
                with patch('secretary.server.browser_reader.read',return_value=result):
                    service.capture(original,stop,False)
                after=service.archive.get(original)
                self.assertEqual(after['text'],before['text']);self.assertEqual(after['summary'],before['summary'])
                other=next(i for i in service.archive.export() if i['id']!=original)
                self.assertEqual(other['text'],sliced)
                self.assertIn('#stellar-slice-',other['url'])
                self.assertTrue(service.archive.retrieve('最近片段'))
            finally:service.close()

    def test_partial_summary_is_bounded_and_discloses_its_scope(self):
        text=reader.PARTIAL_PREFIX+' 最近20轮，不是完整历史。\n\n'+'旧正文'*30000+'最后的新内容'
        result={'summary':'摘要','tags':[],'category':'测试','title':'标题'}
        with patch('secretary.ai.summarize',return_value=result) as summarize:
            fields=ai.summary_fields({'text':text,'title':'原标题'},'codex')
        source=summarize.call_args.args[0]
        self.assertLess(len(source),40500)
        self.assertIn('最后的新内容',source)
        self.assertTrue(fields['summary'].startswith(reader.PARTIAL_PREFIX))
        self.assertIn('最近4万字符',fields['summary'])

    def test_scope_setting_persists_and_invalid_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            try:
                self.assertEqual(service.archive.settings()['capture_scope'],'recent')
                service.archive.configure('codex',False,capture_scope='loaded')
                service.archive.configure('codex',True)
                self.assertEqual(service.archive.settings()['capture_scope'],'loaded')
                with self.assertRaises(ValueError):service.archive.configure('codex',False,capture_scope='bad')
            finally:service.close()
