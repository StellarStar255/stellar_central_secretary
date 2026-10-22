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

    def test_long_pdf_overview_is_bounded_and_disclosed(self):
        text='DOCUMENT START\n'+'body paragraph '*21000+'\nDOCUMENT END'
        output={'title':'Magazine','summary':'Overview','category':'Science','tags':['Science']}
        with patch('secretary.ai.summarize',return_value=output) as summarize:
            result=ai.summary_fields({'text':text,'title':'Original','filename':'magazine.pdf'},'codex')
        source=summarize.call_args.args[0]
        self.assertLess(len(source),42000)
        self.assertIn('DOCUMENT START',source);self.assertIn('DOCUMENT END',source)
        self.assertTrue(result['summary'].startswith('【长 PDF 概览】'))
        self.assertIn('长文概览',result['tags']);self.assertNotIn('部分对话',result['tags'])
