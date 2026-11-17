import hashlib
import base64
import tempfile
import unittest
from unittest.mock import patch
from pypdf.errors import DependencyError
from secretary.core import extract
from secretary.server import Service
from secretary import ai
from pdf_fixture import pdf_bytes
from test_large_pdf_preview import fixture
from pathlib import Path


class PdfExtractionTest(unittest.TestCase):
    def test_parser_limit_falls_back_to_bounded_native_preview(self):
        from pypdf.errors import LimitReachedError
        import pypdfium2 as pdfium
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'complex.pdf';fixture(path,pages=8,text_size=20000)
            original=pdfium.PdfDocument.__getitem__;visited=[]
            def page(document,index):visited.append(index);return original(document,index)
            with patch('pypdf._page.PageObject.extract_text',side_effect=LimitReachedError('Reached maximum number of tokens per stream.')),patch.object(pdfium.PdfDocument,'__getitem__',page):
                text,warning=extract(path.name,path.read_bytes())
            self.assertEqual(visited,list(range(5)))
            self.assertIn('第 1–5 页 / 共 8 页',text)
            self.assertIn('PAGETOKEN5',text);self.assertNotIn('PAGETOKEN6',text)
            self.assertLess(len(text),41000)
            self.assertIn('自动切换',warning);self.assertIn('8000',warning)
            self.assertNotIn('tokens',warning)
            item={'text':text,'title':'Complex PDF','filename':path.name}
            with patch('secretary.ai.summarize',return_value={'summary':'Overview','tags':[]}) as summarize:
                result=ai.summary_fields(item,'codex')
            self.assertIn('未覆盖后续页面',result['summary'])
            self.assertNotIn('PAGETOKEN6',summarize.call_args.args[0])
            with self.assertRaisesRegex(ValueError,'仅提取了前 5 页'):
                ai.summary_fields(item,'codex',full_pdf=True)

    def test_parser_limit_upload_and_reextract_keep_original(self):
        from pypdf.errors import LimitReachedError
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'complex.pdf';fixture(path,pages=8)
            data=path.read_bytes();service=Service(Path(temp)/'archive')
            service.archive.configure('codex',False)
            try:
                with patch('pypdf._page.PageObject.extract_text',side_effect=LimitReachedError('Reached maximum number of tokens per stream.')):
                    item=service.ingest({'filename':path.name,'data':base64.b64encode(data).decode(),'archive_only':True})['item']
                    self.assertIn('PAGETOKEN5',item['text'])
                    self.assertEqual((service.archive.root/'files'/item['id']).read_bytes(),data)
                    result=service.reextract(item['id'])
                    self.assertTrue(result['parsed']);self.assertNotIn('PAGETOKEN6',result['item']['text'])
                    from secretary import bundles
                    bundle,source=bundles.create('',[{'name':path.name,'data':base64.b64encode(data).decode()}])
                    prompt,_,scope=bundles.model_material(bundle,source)
                    self.assertIn('PAGETOKEN5',prompt);self.assertNotIn('PAGETOKEN6',prompt)
                    self.assertIn('自动切换',scope)
            finally:service.close()

    def test_aes_document_with_empty_open_password_extracts_text(self):
        text,error=extract('fixture.pdf',pdf_bytes(password=''))
        self.assertIn('Encrypted PDF extraction fixture',text)
        self.assertEqual(error,'')

    def test_password_required_and_missing_crypto_are_explained(self):
        text,error=extract('locked.pdf',pdf_bytes(password='locked'))
        self.assertFalse(text);self.assertIn('需要打开密码',error)
        with patch('pypdf.PdfReader',side_effect=DependencyError('missing crypto')):
            text,error=extract('fixture.pdf',b'fixture')
        self.assertFalse(text);self.assertIn('加密读取组件不完整',error)

    def test_empty_page_labels_are_not_mistaken_for_body(self):
        text,error=extract('scan.pdf',pdf_bytes(pages=10))
        self.assertEqual(text,'');self.assertIn('OCR',error)

    def test_reextract_repairs_existing_item_without_changing_original(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp);service.archive.configure('codex',False)
            content=pdf_bytes(password='');item,_=service.archive.add('PDF','',filename='fixture.pdf',data=content,warning='previous dependency failure')
            before=service.archive.get(item)
            try:
                result=service.reextract(item)
                self.assertTrue(result['parsed']);self.assertEqual(result['item']['id'],item)
                self.assertIn('readable text',result['item']['text'])
                self.assertEqual(result['item']['digest'],before['digest'])
                self.assertEqual(hashlib.sha256((service.archive.root/'files'/item).read_bytes()).digest(),hashlib.sha256(content).digest())
                with patch('secretary.server.extract',return_value=('','OCR required')):
                    result=service.reextract(item)
                self.assertFalse(result['parsed']);self.assertIn('readable text',result['item']['text'])
            finally:service.close()

    def test_pdf_preview_only_sends_first_five_pages(self):
        text='\n\n'.join(f'[第 {i} 页]\nPage {i} body '+('readable text '*5000) for i in range(1,9))
        output={'title':'Magazine','summary':'Overview','category':'Science','tags':['Science']}
        with patch('secretary.ai.summarize',return_value=output) as summarize:
            result=ai.summary_fields({'text':text,'title':'Original','filename':'magazine.pdf'},'codex')
        source=summarize.call_args.args[0]
        self.assertLessEqual(len(source),40000)
        self.assertIn('Page 1 body',source);self.assertNotIn('Page 6 body',source)
        self.assertTrue(result['summary'].startswith('【PDF 前 5 页概览】'))
        self.assertIn('前部概览',result['tags']);self.assertNotIn('部分对话',result['tags'])
        short='\n\n'.join(f'[第 {i} 页]\nPage {i} body' for i in range(1,9))
        with patch('secretary.ai.summarize',return_value=output) as summarize:
            ai.summary_fields({'text':short,'title':'Original','filename':'magazine.pdf'},'codex')
        source=summarize.call_args.args[0]
        self.assertIn('Page 5 body',source);self.assertNotIn('Page 6 body',source)

    def test_explicit_full_pdf_summary_covers_all_extracted_text(self):
        text='[第 1 页]\n'+('body paragraph '*21000)+'\n[第 100 页]\nDOCUMENT END'
        output={'title':'Magazine','summary':'Overview','category':'Science','tags':[]}
        with patch('secretary.ai.summarize',return_value=output) as summarize:
            result=ai.summary_fields({'text':text,'title':'Original','filename':'magazine.pdf'},'codex',full_pdf=True)
        self.assertEqual(summarize.call_args.args[0],text)
        self.assertTrue(result['summary'].startswith('【PDF 全文摘要】'))

    def test_pdf_without_page_labels_discloses_character_limit(self):
        with patch('secretary.ai.summarize',return_value={'summary':'Overview','tags':[]}) as summarize:
            result=ai.summary_fields({'text':'text '*10000,'title':'Original','filename':'old.pdf'},'codex')
        self.assertEqual(len(summarize.call_args.args[0]),24000)
        self.assertIn('未取得页码信息',result['summary'])

    def test_blank_pdf_front_pages_do_not_summarize_later_pages(self):
        with patch('secretary.ai.summarize') as summarize:
            with self.assertRaisesRegex(ValueError,'前 5 页没有可读取文字'):
                ai.summary_fields({'text':'[第 6 页]\nLater page text','title':'Original','filename':'blank-front.pdf'},'codex')
        summarize.assert_not_called()
