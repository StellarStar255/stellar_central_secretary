import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secretary import pdf_reading
from secretary.server import Service
from test_large_pdf_preview import fixture
class PdfCoverageTest(unittest.TestCase):
 def test_actual_summary_scope_and_incremental_pages(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data');source=Path(temp)/'pages.pdf';fixture(source,pages=9)
   ident,_=service.archive.add(text='original description',filename='pages.pdf',data=source.read_bytes())
   calls=[]
   def analyze(source,title,*args):calls.append(source);return ({'summary':'Synthetic '+str(len(calls)),'state':'ready','error':''},'')
   try:
    pdf_reading.read(service.archive,ident,None,None,{'start':1,'end':2})
    self.assertFalse(pdf_reading.coverage(service.archive.get(ident))[0]['known'])
    with patch('secretary.ai.analyze_material',side_effect=analyze):service.process(ident)
    item=service.archive.get(ident);self.assertEqual(pdf_reading.coverage(item)[0]['summarized'],'1–2');first=item['base_summary']
    pdf_reading.read(service.archive,ident,None,None,{'start':6,'end':7})
    self.assertEqual(pdf_reading.coverage(service.archive.get(ident))[0]['pending'],'6–7')
    with patch('secretary.ai.analyze_material',side_effect=analyze):service.process(ident,pdf_new=True)
    item=service.archive.get(ident);self.assertTrue(item['base_summary'].startswith(first));self.assertIn('PAGETOKEN6',calls[-1]);self.assertNotIn('PAGETOKEN1',calls[-1])
    self.assertEqual(pdf_reading.coverage(item)[0]['summarized'],'1–2, 6–7');self.assertFalse(pdf_reading.coverage(item)[0]['pending'])
    # Changed OCR/text and manually replaced summaries cannot retain false coverage.
    values=item['pdf_reads'];values['original:original']['pages']['6']['text']='changed';service.archive.update(ident,pdf_reads=values)
    self.assertEqual(pdf_reading.coverage(service.archive.get(ident))[0]['pending'],'6')
    service.archive.update(ident,summary='manual replacement');self.assertFalse(pdf_reading.coverage(service.archive.get(ident))[0]['known'])
   finally:service.close()
 def test_budget_never_claims_unsent_page(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp);source=Path(temp)/'pages.pdf';fixture(source,pages=9);ident,_=service.archive.add(text='',filename='pages.pdf',data=source.read_bytes())
   try:
    pdf_reading.read(service.archive,ident,None,None,{'start':1,'end':2});item=service.archive.get(ident)
    size=len('[第 1 页]\n'+item['pdf_reads']['original:original']['pages']['1']['text'])
    source,scope,used=pdf_reading.summary_material(service.archive,item,budget=size)
    self.assertIn('PAGETOKEN1',source);self.assertNotIn('PAGETOKEN2',source);self.assertEqual(list(used['original:original']),['1'])
   finally:service.close()
