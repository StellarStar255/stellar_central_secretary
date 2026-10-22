import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pypdf.errors import DependencyError
from secretary.core import extract
from secretary.server import Service
from secretary import ai
from pdf_fixture import pdf_bytes


class PdfExtractionTest(unittest.TestCase):
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
