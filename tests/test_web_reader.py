import tempfile
import threading
import unittest
import uuid
from urllib.parse import urlunsplit
from unittest.mock import Mock,patch
from secretary import web_reader,ai
from secretary.server import Service

URL='https://example.test/project/item?tabKey=comment#comment'

class WebReaderTest(unittest.TestCase):
    def test_preserves_full_target_and_rejects_non_web_urls(self):
        self.assertEqual(web_reader.capture_url(URL),URL)
        for url in ('http://localhost/x','http://127.0.0.1/x','http://[::1]/x','file:///tmp/a',urlunsplit(('https','fixture:'+uuid.uuid4().hex+'@example.test','/x','','')),'https://example.test/file.pdf'):
            with self.subTest(url=url),self.assertRaises(ValueError):web_reader.capture_url(url)

    def test_public_dns_rechecked(self):
        with patch.object(web_reader.socket,'getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',443))]):
            with self.assertRaises(ValueError):web_reader.validate_public_url(URL)

    def test_login_and_permission_pages_do_not_become_body(self):
        for field in ('login','denied'):
            page=Mock(url=URL);page.is_closed.return_value=False
            page.evaluate.return_value={'text':'Do not save this', 'login':field=='login','denied':field=='denied'}
            with patch.object(web_reader,'validate_public_url'),self.assertRaises(RuntimeError):
                web_reader.capture_loaded_page(page,URL,threading.Event())

    def test_redirect_and_cancel_preserve_original(self):
        page=Mock(url='https://example.test/another');page.is_closed.return_value=False
        with patch.object(web_reader,'validate_public_url'),self.assertRaises(RuntimeError):
            web_reader.capture_loaded_page(page,URL,threading.Event())
        page.url=URL;stop=threading.Event();stop.set()
        with patch.object(web_reader,'validate_public_url'),self.assertRaises(web_reader.reader.CaptureCancelled):
            web_reader.capture_loaded_page(page,URL,stop)

    def test_success_has_explicit_loaded_scope_and_full_original_url(self):
        page=Mock(url=URL);page.is_closed.return_value=False
        page.evaluate.return_value=dict(text='Loaded project comments. '*10,login=False,denied=False,busy=False,ready=True,truncated=False,title='Project')
        stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        with patch.object(web_reader,'validate_public_url'):result=web_reader.capture_loaded_page(page,URL,stop)
        self.assertEqual(result['url'],URL)
        self.assertTrue(result['text'].startswith(web_reader.PREFIX_ZH))
        self.assertNotIn('partial',result)

    def test_service_generic_fallback_and_media_exclusion(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                with patch('secretary.server.fetch_page',return_value=('','正文不足')),patch.object(service,'start_capture') as start:
                    result=service.ingest({'url':URL});start.assert_called_once_with(result['item']['id'])
                with patch('secretary.server.fetch_page',return_value=('','链接已保存；请下载文件后拖入知识库以解析正文。')),patch.object(service,'start_capture') as start:
                    service.ingest({'url':'https://example.test/download'});start.assert_not_called()
            finally:service.close()

    def test_service_dispatch_and_failed_refresh_preserves_saved_material(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item,_=service.archive.add('Original','Saved body '*30,url=URL)
                service.archive.update(item,summary='Saved summary',state='ready')
                stop=threading.Event();service.captures[item]=stop;service.login_confirmations[item]=threading.Event()
                with patch.object(web_reader,'read',side_effect=RuntimeError('No permission')) as read,patch('secretary.browser_reader.read') as chat:
                    service.capture(item,stop,False)
                    read.assert_called_once();chat.assert_not_called()
                saved=service.archive.get(item)
                self.assertEqual(saved['text'],'Saved body '*30)
                self.assertEqual(saved['summary'],'Saved summary')
                self.assertEqual(saved['state'],'ready')
            finally:service.close()

    def test_summary_retains_scope(self):
        text=web_reader.PREFIX_EN+' Loaded content only.\n\nExample project body.'
        with patch.object(ai,'summarize',return_value={'summary':'Summary','tags':[]}) as summarize:
            result=ai.summary_fields({'text':text,'title':'Example'},'codex')
        self.assertTrue(result['summary'].startswith(web_reader.PREFIX_EN))
        self.assertEqual(summarize.call_args.args[0],text)

if __name__=='__main__':unittest.main()
