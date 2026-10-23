import base64
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
from secretary.core import Archive, extract
from secretary.server import Service, handler
from secretary import browser_reader
from secretary.diagnose_capture import persist_capture


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.archive = Archive(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_dedup_search_and_reindex(self):
        item, created = self.archive.add('产品规划', '知识管理工具需要全文检索和来源追溯。')
        self.assertTrue(created)
        self.assertEqual(self.archive.add('重复', '知识管理工具需要全文检索和来源追溯。'), (item, False))
        self.assertEqual(self.archive.retrieve('全文检索')[0]['item_id'], item)
        self.archive.update(item, text='新的研究：火星气候与大气成分。')
        self.assertFalse(self.archive.retrieve('全文检索'))
        self.assertEqual(self.archive.retrieve('火星气候')[0]['item_id'], item)
        reopened = Archive(self.temp.name)
        self.assertEqual(len(reopened.list(q='气候')), 1)
    def test_contextual_person_alias_search(self):
        item,_=self.archive.add('权力集中与制衡','反对毛需要达成共识，反对四人帮则是不同阵营排除共同威胁。')
        self.archive.add('毛衣清洗','羊毛衣服怎么清洗？')
        self.assertEqual([r['id'] for r in self.archive.list(q='毛泽东')],[item])
        self.assertEqual([r['id'] for r in self.archive.list(q='毛主席')],[item])
    def test_library_search_requires_all_keywords_in_any_order_across_fields(self):
        wanted,_=self.archive.add('科学美国人杂志','本期主题包含神经科学与天文。',filename='SciAm_06_2026.pdf')
        self.archive.update(wanted,summary='2026年6月刊概览',tags=['Science'],category='科学')
        self.archive.add('科学美国人往期','2026年5月刊')
        self.archive.add('美国市场','6月经济与收入分析')
        for query in ('科学美国人 6月','6月 科学美国人','  科学美国人　\t6月  ','SCIENCE\n6月','SciAm_06 6月','神经科学 6月'):
            results=self.archive.list(q=query)
            self.assertEqual([r['id'] for r in results],[wanted],query)
            self.assertNotIn('text',results[0])
        self.assertEqual(self.archive.list(q='科学美国人 不存在'),[])
        self.assertEqual(self.archive.list(q='科学美国人 6月',kind='link'),[])
        self.assertEqual(self.archive.list(q='科学美国人 6月',category='历史'),[])
        self.assertEqual(len(self.archive.list(q='科学美国人 6月',kind='file',category='科学')),1)
        self.assertEqual(len(self.archive.list(q=' \t　')),3)
    def test_library_search_matches_keywords_across_body_chunks(self):
        wanted,_=self.archive.add('长文','深海探索'+('正文内容。'*3000)+'人工智能')
        self.archive.add('无关资料','深海研究与机器学习')
        self.assertEqual([r['id'] for r in self.archive.list(q='人工智能 深海探索')],[wanted])
    def test_longer_capture_replaces_body_and_preserves_old_version(self):
        item,_=self.archive.add('原版','用户：\n提问\n\nChatGPT：\n旧回答')
        self.archive.update(item,summary='旧摘要',state='ready')
        longer='用户：\n提问\n\nChatGPT：\n旧回答与补齐的段落、更多资料和结论。'
        saved=persist_capture(self.temp.name,{'url':'https://chatgpt.com/c/new','title':'新会话','text':longer})
        self.archive.replace_capture(item,'补齐版',longer)
        self.assertEqual(self.archive.get(item)['text'],longer)
        backup=list((Path(self.temp.name)/'capture-history').glob('*.json'))
        self.assertEqual(len(backup),1)
        self.assertEqual(json.loads(backup[0].read_text())['summary'],'旧摘要')
        with self.assertRaisesRegex(ValueError,'短于'):self.archive.replace_capture(item,'截断版','太短')
        self.assertEqual(self.archive.get(item)['text'],longer)
    def test_capture_persists_without_service_and_preserves_other_jobs(self):
        existing,_=self.archive.add('后台任务','后台仍在运行的任务正文')
        self.archive.update(existing,state='processing')
        capture={'title':'会话正文','url':'https://chatgpt.com/c/example','text':'用户：如何归档？\n助手：保留原件并创建正文索引。'}
        saved=persist_capture(self.temp.name,capture)
        self.assertEqual(saved['state'],'pending');self.assertEqual(saved['text'],capture['text'])
        self.assertEqual(self.archive.get(existing)['state'],'processing')
        self.assertTrue(self.archive.retrieve('正文索引'))
        self.assertEqual(persist_capture(self.temp.name,capture)['id'],saved['id'])

    def test_html_and_unsupported(self):
        text, _ = extract('test.html', b'<h1>Title</h1><script>hidden</script><p>Hello</p>')
        self.assertIn('Hello', text); self.assertNotIn('hidden', text)
        self.assertTrue(extract('image.png', b'fake')[1])
    def test_office_and_zip_limit(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data,'w') as z: z.writestr('word/document.xml', '<document><p><t>Research</t></p></document>')
        self.assertIn('Research', extract('a.docx',data.getvalue())[0])


class ManualLoginTest(unittest.TestCase):
    def test_background_launch_defers_window_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            proc=Mock();proc.poll.return_value=0
            info={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/example'}
            with patch('secretary.browser_reader.existing_session',return_value=None), patch('secretary.browser_reader.chrome_executable',return_value='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'), patch('secretary.browser_reader.free_loopback_port',return_value=9371), patch('secretary.browser_reader.debug_info',return_value=info), patch('secretary.browser_reader.subprocess.Popen',return_value=proc) as launch:
                result=browser_reader.start_or_reuse_browser('about:blank#task',Path(directory),threading.Event(),background=True)
            command=launch.call_args.args[0]
            self.assertIn('--no-startup-window',command)
            self.assertNotIn('--new-window',command)
            self.assertNotIn('about:blank#task',command)
            self.assertNotIn('startup_url',result)

    def test_collection_scrolls_down_for_later_virtualized_turns(self):
        def message(i):return {'id':str(i),'role':'user' if i%2 else 'assistant','text':f'第{i}条消息，这段正文需要完整保存。'}
        page=Mock();position={'step':0}
        def evaluate(script):
            if script==browser_reader.MESSAGES_SCRIPT:
                start=min(position['step'],3)*2+1
                return [message(start),message(start+1)]
            if "'down'" in script:
                position['step']+=1
                return {'top':position['step']*500,'max':2000,'bottom':position['step']>=3}
            return {'top':0,'max':2000,'bottom':False}
        page.evaluate.side_effect=evaluate
        messages=browser_reader.collect_messages(page,threading.Event())
        self.assertEqual([m['id'] for m in messages],[str(i) for i in range(1,9)])
        self.assertGreaterEqual(position['step'],6)
    def test_collection_preserves_repeated_questions_with_distinct_message_ids(self):
        messages=[{'id':'q1','role':'user','text':'同一个问题'},
                  {'id':'a1','role':'assistant','text':'第一次回答包含足够长的正文。'},
                  {'id':'q2','role':'user','text':'同一个问题'},
                  {'id':'a2','role':'assistant','text':'第二次回答包含足够长的正文。'}]
        page=Mock()
        page.evaluate.side_effect=lambda script: messages if script==browser_reader.MESSAGES_SCRIPT else {'bottom':True}
        captured=browser_reader.collect_messages(page,threading.Event())
        self.assertEqual([m['id'] for m in captured],['q1','a1','q2','a2'])

    def test_start_browser_with_local_connection_keeps_process_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory);proc=Mock();proc.poll.return_value=None
            info={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/example'}
            with patch('secretary.browser_reader.existing_session',return_value=None), patch('secretary.browser_reader.chrome_executable',return_value='/chrome'), patch('secretary.browser_reader.free_loopback_port',return_value=9371), patch('secretary.browser_reader.debug_info',return_value=info), patch('secretary.browser_reader.subprocess.Popen',return_value=proc) as launch:
                session=browser_reader.start_or_reuse_browser('https://chatgpt.com/c/example',profile,threading.Event())
            args=launch.call_args.args[0]
            self.assertIn('--remote-debugging-address=127.0.0.1',args)
            self.assertIn('--remote-debugging-port=9371',args)
            self.assertIn('--user-data-dir='+str(profile),args)
            self.assertFalse(any('enable-automation' in a or 'no-sandbox' in a for a in args))
            self.assertIs(session['process'],proc)
            proc.terminate.assert_not_called();proc.kill.assert_not_called()
            self.assertTrue((profile/'.reader-session.json').exists())

    def test_manual_confirmation_does_not_close_or_relaunch_browser(self):
        proc=Mock();proc.poll.return_value=None
        confirmed=threading.Event();confirmed.set()
        session={'confirmed':False,'process':proc}
        notify=Mock()
        with patch('secretary.browser_reader.start_or_reuse_browser',return_value=session) as start:
            result=browser_reader.manual_login('https://chatgpt.com/c/example',Path('/tmp/profile'),notify,threading.Event(),confirmed,10)
        self.assertIs(result,session);start.assert_called_once()
        proc.terminate.assert_not_called();proc.kill.assert_not_called();proc.wait.assert_not_called()
        self.assertEqual(notify.call_args_list[0].args[0],'waiting_login')
        self.assertEqual(notify.call_args_list[-1].args[0],'confirming_login')

    def test_live_instance_is_reused_without_new_process(self):
        session={'confirmed':True,'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/original'}
        with patch('secretary.browser_reader.existing_session',return_value=session), patch('secretary.browser_reader.subprocess.Popen') as launch:
            self.assertIs(browser_reader.start_or_reuse_browser('https://chatgpt.com/c/example',Path('/tmp/profile'),threading.Event()),session)
        launch.assert_not_called()

    def test_endpoint_reuse_requires_same_browser_identity(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory)
            saved={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/original','confirmed':True}
            browser_reader.save_session(profile,saved)
            with patch('secretary.browser_reader.debug_info',return_value={**saved,'websocket':'ws://127.0.0.1:9371/devtools/browser/different'}):
                self.assertIsNone(browser_reader.existing_session(profile))
            with patch('secretary.browser_reader.debug_info',return_value={k:saved[k] for k in ('endpoint','websocket')}):
                self.assertTrue(browser_reader.existing_session(profile)['confirmed'])
        for address in ('http://example.com:9371','http://192.168.1.1:9371','https://127.0.0.1:9371'):
            with self.assertRaises(ValueError): browser_reader.debug_info(address)

    def test_read_uses_original_context_and_does_not_reload_or_close(self):
        target='https://chatgpt.com/c/example'
        messages=[{'id':'1','role':'user','text':'如何做好个人知识归档？'},{'id':'2','role':'assistant','text':'保留原件，提取正文，分段索引，并创建可追溯的摘要。'}]
        page=Mock();page.url=target;page.is_closed.return_value=False
        page.evaluate.side_effect=lambda script: {'messages':messages,'diagnostics':{'generating':False,'stopButtons':1,'visibleStopButtons':0}} if script==browser_reader.SNAPSHOT_SCRIPT else messages
        page.locator.return_value.count.return_value=0
        page.title.return_value='知识归档对话'
        context=Mock();context.pages=[page]
        browser=Mock();browser.contexts=[context]
        pw=Mock();pw.chromium.connect_over_cdp.return_value=browser
        session={'websocket':'ws://127.0.0.1:9371/devtools/browser/original'}
        result=browser_reader.read_from_browser(pw,session,target,Mock(),threading.Event(),timeout=2)
        self.assertIn('保留原件',result['text'])
        pw.chromium.connect_over_cdp.assert_called_once_with(session['websocket'],timeout=15000)
        pw.chromium.launch_persistent_context.assert_not_called()
        browser.new_context.assert_not_called();context.new_page.assert_not_called()
        browser.close.assert_not_called();context.close.assert_not_called();page.close.assert_not_called();page.goto.assert_not_called()

    def test_matching_logged_in_tab_wins_over_stale_guest_tab(self):
        target='https://chatgpt.com/c/example'
        messages=[{'role':'user','text':'如何构建个人知识库？'},{'role':'assistant','text':'可以保留资料原件，提取正文并创建分段检索索引。'}]
        guest=Mock();guest.url=target;guest.is_closed.return_value=False
        guest.evaluate.return_value={'messages':[],'diagnostics':{'login':True}}
        ready=Mock();ready.url=target;ready.is_closed.return_value=False
        ready.evaluate.side_effect=lambda script:{'messages':messages,'diagnostics':{'generating':False}} if script==browser_reader.SNAPSHOT_SCRIPT else messages
        ready.title.return_value='实际会话'
        context=Mock();context.pages=[guest,ready];browser=Mock();browser.contexts=[context]
        pw=Mock();pw.chromium.connect_over_cdp.return_value=browser
        reports=[]
        result=browser_reader.read_from_browser(pw,{'websocket':'ws://127.0.0.1:9371/devtools/browser/original'},target,Mock(),threading.Event(),timeout=2,diagnose=reports.append)
        self.assertEqual(result['title'],'实际会话');self.assertIn('提取正文',result['text'])
        self.assertEqual(len(reports[-1]['tabs']),2)
        guest.goto.assert_not_called();ready.goto.assert_not_called();browser.close.assert_not_called()

    def test_guest_page_fails_without_closing_original_browser(self):
        target='https://chatgpt.com/c/example'
        page=Mock();page.url=target;page.is_closed.return_value=False
        page.evaluate.return_value={'messages':[],'diagnostics':{'login':True,'generating':False}};page.locator.return_value.count.return_value=1
        context=Mock();context.pages=[page];browser=Mock();browser.contexts=[context]
        pw=Mock();pw.chromium.connect_over_cdp.return_value=browser
        with self.assertRaisesRegex(RuntimeError,'未登录状态'):
            browser_reader.read_from_browser(pw,{'websocket':'ws://127.0.0.1:9371/devtools/browser/original'},target,Mock(),threading.Event())
        browser.close.assert_not_called();context.close.assert_not_called();page.goto.assert_not_called()

    def test_login_confirmation_and_cancellation_gate_reading(self):
        proc=Mock();proc.poll.return_value=None
        confirmed=Mock();confirmed.wait.side_effect=[False,True]
        browser_reader.wait_for_manual_login(proc,confirmed,threading.Event(),timeout=10)
        self.assertEqual(confirmed.wait.call_count,2)
        stop=threading.Event();stop.set()
        with self.assertRaises(browser_reader.CaptureCancelled): browser_reader.wait_for_manual_login(proc,threading.Event(),stop,timeout=10)

    def test_google_refusal_is_detected_without_reading_form_fields(self):
        page=Mock();page.url='https://accounts.google.com/signin/rejected'
        page.get_by_text.return_value.count.return_value=1
        self.assertTrue(browser_reader.login_rejected(page))
        page.url='https://chatgpt.com/c/example';page.reset_mock()
        self.assertFalse(browser_reader.login_rejected(page));page.get_by_text.assert_not_called()


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.service = Service(self.temp.name)
        self.service.archive.configure('codex',False)
    def tearDown(self): self.service.capture_pool.shutdown(wait=True); self.service.pool.shutdown(wait=True); self.temp.cleanup()
    def test_private_link_needs_content_then_edit_and_answer(self):
        with patch.object(self.service, 'start_capture') as capture:
            item = self.service.ingest({'url':'https://chatgpt.com/c/private'})['item']
            capture.assert_called_once_with(item['id'])
        self.assertEqual(item['state'],'needs_content'); self.assertFalse(item['summary'])
        enriched=self.service.ingest({'url':item['url'],'text':'产品规划结论：先做知识归档。'})
        self.assertTrue(enriched['updated']); self.assertEqual(enriched['item']['id'],item['id'])
        self.assertEqual(len(self.service.archive.list()),1)
        with patch('secretary.ai.run', return_value='先做知识归档。[1]'):
            result = self.service.ask('产品规划')
        self.assertEqual(result['sources'][0]['item_id'],item['id'])
        self.assertEqual(self.service.ask('宇宙量子黑洞')['sources'],[])
    def test_original_backup_and_restore(self):
        result = self.service.ingest({'filename':'../../资料.txt','data':base64.b64encode('数据与检索'.encode()).decode()})
        item=result['item']; self.assertEqual(item['filename'],'资料.txt')
        backup=self.service.backup()
        with zipfile.ZipFile(io.BytesIO(backup)) as z:
            self.assertEqual(z.read('files/'+item['id']), '数据与检索'.encode())
            restore=Path(self.temp.name)/'restored'; z.extractall(restore)
        self.assertEqual(Archive(restore).get(item['id'])['text'],'数据与检索')
    def test_ai_error_keeps_original(self):
        item=self.service.ingest({'text':'自动归档的资料'})['item']
        with patch('secretary.ai.summarize', side_effect=RuntimeError('网络断开')):
            self.service.process(item['id'])
        saved=self.service.archive.get(item['id'])
        self.assertEqual(saved['state'],'error'); self.assertEqual(saved['text'],item['text'])
    def test_capture_and_invalid_url(self):
        capture={'url':'https://chatgpt.com/c/abc','title':'已登录对话','text':'用户：如何设计知识库？\n助手：分段索引。'}
        result=self.service.ingest({'filename':'会话.knowledge.json','data':base64.b64encode(json.dumps(capture).encode()).decode()})
        self.assertEqual(result['item']['text'],capture['text'])
        with self.assertRaises(ValueError): self.service.ingest({'url':'javascript:alert(1)'})
    def test_login_capture_indexes_and_summarizes(self):
        item_id, _ = self.service.archive.add('会话', url='https://chatgpt.com/c/example')
        result = {'title':'知识管理讨论', 'text':'用户：怎么归档？\nChatGPT：使用分段索引、来源链接和摘要。'}
        with patch('secretary.browser_reader.read', return_value=result), patch('secretary.ai.summarize', return_value={'title':'知识管理讨论','summary':'使用分段索引并保存来源。','category':'知识管理','tags':['归档']}):
            self.service.start_capture(item_id, force_summary=True)
            self.service.capture_pool.shutdown(wait=True)
            self.service.pool.shutdown(wait=True)
        saved = self.service.archive.get(item_id)
        self.assertEqual(saved['state'], 'ready')
        self.assertEqual(saved['text'], result['text'])
        self.assertEqual(saved['summary'], '使用分段索引并保存来源。')
        self.assertEqual(self.service.archive.retrieve('分段索引')[0]['item_id'], item_id)
        self.assertFalse(self.service.captures)

    def test_manual_login_confirmation_requires_live_task(self):
        item_id, _ = self.service.archive.add('会话',url='https://chatgpt.com/c/example')
        with self.assertRaises(ValueError): self.service.confirm_login(item_id)
        self.service.archive.update(item_id,state='waiting_login')
        confirmation=threading.Event()
        self.service.login_confirmations[item_id]=confirmation
        self.service.confirm_login(item_id)
        self.assertTrue(confirmation.is_set())
        self.assertEqual(self.service.archive.get(item_id)['state'],'confirming_login')
        self.service.confirm_login(item_id)  # repeated confirmation is idempotent

    def test_capture_failure_preserves_previous_archive(self):
        item_id, _ = self.service.archive.add('会话', text='已经归档的对话正文', url='https://chatgpt.com/c/example')
        self.service.archive.update(item_id, summary='原有总结', state='ready')
        with patch('secretary.browser_reader.read', side_effect=RuntimeError('登录超时')):
            self.service.start_capture(item_id, force_summary=True)
            self.service.capture_pool.shutdown(wait=True)
        saved = self.service.archive.get(item_id)
        self.assertEqual(saved['summary'], '原有总结')
        self.assertEqual(saved['text'], '已经归档的对话正文')
        self.assertEqual(saved['state'], 'ready')
        self.assertIn('登录超时', saved['error'])

    def test_capture_url_and_login_page_rejected(self):
        self.assertEqual(browser_reader.conversation_url('https://chatgpt.com/c/abc?x=1'), 'https://chatgpt.com/c/abc')
        for url in ('http://chatgpt.com/c/abc','https://evil.com/c/abc','https://chatgpt.com/auth/login','https://chatgpt.com:8080/c/abc','https://example.com/?next=https://chatgpt.com/c/abc'):
            with self.assertRaises(ValueError): browser_reader.conversation_url(url)
        self.assertEqual(browser_reader.validate_messages([{'role':'user','text':'登录按钮登录页面'}]), [])
        self.assertEqual(browser_reader.validate_messages([{'role':'system','text':'登录 ChatGPT 查看会话'}]), [])
        valid=browser_reader.validate_messages([{'role':'user','text':'如何做知识管理？'},{'role':'assistant','text':'可以通过保存原件、正文分段和检索来实现。'}])
        self.assertEqual(len(valid),2)
        self.assertFalse(browser_reader.same_conversation('https://chatgpt.com/c/other','https://chatgpt.com/c/abc'))

    def test_http_token_and_download(self):
        # Exercise the real HTTP parser and handler using socket-shaped in-memory streams.
        class Socket:
            def __init__(self, request): self.input=io.BytesIO(request); self.output=io.BytesIO()
            def makefile(self, *args): return self.input
            def sendall(self, data): self.output.write(data)
        class Server: server_port=8768
        handler_class=handler(self.service)
        def request(path, payload=None, token='', host='127.0.0.1:8768'):
            data=json.dumps(payload).encode() if payload is not None else b''
            method='POST' if payload is not None else 'GET'
            headers=f'{method} {path} HTTP/1.0\r\nHost: {host}\r\nContent-Length: {len(data)}\r\nX-Knowledge-Token: {token}\r\n\r\n'
            sock=Socket(headers.encode()+data)
            handler_class(sock, ('127.0.0.1',12345), Server())
            head, body=sock.output.getvalue().split(b'\r\n\r\n',1)
            return int(head.split()[1]), body
        status, body=request('/api/status'); self.assertEqual(status,200)
        status_payload=json.loads(body)
        self.assertTrue(status_payload['capabilities']['conversation_capture'])
        token=status_payload['token']
        self.assertEqual(request('/api/ingest', {'text':'测试 HTTP 全文检索'})[0],403)
        status, body=request('/api/ingest', {'text':'测试 HTTP 全文检索'}, token)
        self.assertEqual(status,200); record=json.loads(body); self.assertTrue(record['created'])
        item_id=record['item']['id']
        self.service.archive.update(item_id,summary='已有摘要',state='ready')
        with patch.object(self.service,'queue') as queue:
            status,body=request('/api/items/'+item_id+'/title',{'title':'  自定义资料名称  '},token)
            self.assertEqual(status,200)
            renamed=json.loads(body)['item']
            self.assertEqual(renamed['title'],'自定义资料名称')
            self.assertEqual(renamed['summary'],'已有摘要');self.assertEqual(renamed['state'],'ready')
            self.assertEqual(renamed['text'],record['item']['text'])
            self.assertEqual(request('/api/items/'+item_id+'/title',{'title':'   '},token)[0],400)
            self.assertEqual(request('/api/items/'+item_id+'/title',{'title':'字'*301},token)[0],400)
            queue.assert_not_called()
        self.assertEqual([r['id'] for r in self.service.archive.list(q='自定义资料名称')],[item_id])
        with patch.object(self.service, 'start_capture') as capture:
            status, body=request('/api/items/'+item_id+'/capture',{},token)
            self.assertEqual(status,200);self.assertTrue(json.loads(body)['capture_started'])
            capture.assert_called_once_with(item_id,force_summary=True)
        with patch.object(self.service, 'confirm_login', return_value=self.service.archive.get(item_id)) as confirm:
            status, body=request('/api/items/'+item_id+'/confirm-login',{},token)
            self.assertEqual(status,200);self.assertTrue(json.loads(body)['login_confirmed'])
            confirm.assert_called_once_with(item_id)
        with patch.object(self.service, 'queue') as queue:
            self.assertEqual(request('/api/items/'+item_id+'/unknown-action',{},token)[0],404)
            queue.assert_not_called()
        self.assertEqual(request('/api/items',host='evil.example')[0],403)
        status, body=request('/api/items?q=HTTP'); self.assertEqual(len(json.loads(body)),1)
        status, body=request('/app.js'); self.assertEqual(status,200); self.assertIn(b'function refresh',body)


if __name__=='__main__': unittest.main()
