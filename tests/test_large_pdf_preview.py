import base64,io,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
from secretary import bundles,pdf_preview,thumbnails,ai
from secretary.server import Service


def fixture(path,pages=6,padding=0,blank=False,text_size=0):
    writer=PdfWriter()
    for index in range(pages):
        page=writer.add_blank_page(width=400,height=300)
        if blank:continue
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 100 Td ('+f'PAGETOKEN{index+1} readable synthetic reference '.encode()+b'x'*text_size+b') Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);data=output.getvalue()
    if not padding:path.write_bytes(data);return
    offset=int(re.search(rb'startxref\s+(\d+)',data)[1])
    with path.open('wb') as dst:
        dst.write(data[:offset]);dst.write(f'999999 0 obj\n<< /Length {padding} >>\nstream\n'.encode());dst.seek(padding,1);dst.write(b'\nendstream\nendobj\n')
        start=dst.tell();dst.write(re.sub(rb'(startxref\s+)\d+',lambda match:match[1]+str(start).encode(),data[offset:]))

class LargePdfPreviewTest(unittest.TestCase):
    def test_large_pdf_reads_five_pages_without_whole_file_reads(self):
        import pypdfium2 as pdfium
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'large.pdf';fixture(path,padding=51*1024*1024)
            original=pdfium.PdfDocument.__getitem__;pages=[]
            def page(document,index):pages.append(index);return original(document,index)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole-file read')),patch.object(pdfium.PdfDocument,'__getitem__',page):
                text,warning=pdf_preview.read(path)
            self.assertEqual(pages,list(range(5)));self.assertIn('PAGETOKEN5',text);self.assertNotIn('PAGETOKEN6',text)
            self.assertIn('共 6 页',text);self.assertIn('未覆盖后续页面',warning)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole-file read')):
                data,source=bundles.create('',[{'name':'large.pdf','source':path}])
                try:
                    prompt,images,scope=bundles.model_material(data,source)
                    self.assertIn('PAGETOKEN5',prompt);self.assertNotIn('PAGETOKEN6',prompt);self.assertIn('大 PDF',scope)
                    file,member=bundles.member(data,bundles.metadata(data)[0]['id'])
                    image,media=thumbnails.render(file['name'],member);self.assertEqual(media,'image/png');self.assertTrue(image)
                finally:bundles.cleanup(data)

    def test_character_cap_scans_and_encrypted_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'page.pdf';fixture(path,pages=1,text_size=20000)
            text,warning=pdf_preview.read(path);self.assertLess(len(text),8500);self.assertIn('8000',warning)
            fixture(path,blank=True);text,warning=pdf_preview.read(path);self.assertEqual(text,'');self.assertIn('OCR',warning)
            from pdf_fixture import pdf_bytes
            path.write_bytes(pdf_bytes(password='secret'));text,warning=pdf_preview.read(path);self.assertEqual(text,'');self.assertIn('密码',warning)
            path.write_bytes(b'invalid PDF');self.assertEqual(pdf_preview.read(path)[0],'')

    def test_full_summary_does_not_claim_partial_pdf_is_complete(self):
        with self.assertRaisesRegex(ValueError,'仅提取了前 5 页'):
            ai.summary_fields({'text':'【大 PDF 前部概览：第 1–5 页 / 共 9 页】\n[第 1 页]\ntext','filename':'large.pdf','title':'PDF'},'codex',full_pdf=True)

    def test_large_pdf_upload_keeps_original_and_searches_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'large.pdf';fixture(source,padding=51*1024*1024)
            service=Service(Path(temp)/'archive');service.archive.configure('codex',False)
            try:
                upload=service.uploads.start('large.pdf',source.stat().st_size);target=service.uploads.path(upload['id'])
                bundles.copy_data(source,target)
                with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole-file read')):
                    item=service.ingest({'attachments':[{'name':'large.pdf','upload_id':upload['id']}],'archive_only':True})['item']
                self.assertIn('PAGETOKEN5',item['text']);self.assertNotIn('PAGETOKEN6',item['text'])
                self.assertEqual(len(service.archive.list(q='PAGETOKEN5')),1);self.assertEqual(service.archive.list(q='PAGETOKEN6'),[])
                self.assertGreater(item['attachments'][0]['size'],50*1024*1024)
            finally:service.close()
