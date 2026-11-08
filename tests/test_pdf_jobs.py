import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service
from test_large_pdf_preview import fixture

class PdfJobsTest(unittest.TestCase):
 def test_cancel_is_transactional_and_browsing_remains_available(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data');source=Path(temp)/'source.pdf';fixture(source,pages=9)
   ident,_=service.archive.add(text='',filename='source.pdf',data=source.read_bytes())
   entered=threading.Event();release=threading.Event()
   def recognize(image):entered.set();release.wait(5);return 'never committed'
   try:
    with patch('secretary.local_ocr.recognize',side_effect=recognize):
     task=service.pdf_jobs.start(ident,None,None,{'start':1,'end':2,'ocr':True});self.assertTrue(entered.wait(5))
     # OCR must not hold PDFium's lock: another page can render meanwhile.
     from secretary import pdf_preview
     self.assertTrue(pdf_preview.page_image(source,2).startswith(b'\x89PNG'))
     service.pdf_jobs.cancel(task['id']);release.set()
     for _ in range(100):
      result=service.pdf_jobs.get(task['id'])
      if result['state']=='cancelled':break
      time.sleep(.01)
     self.assertEqual(result['state'],'cancelled');self.assertFalse(service.archive.get(ident)['pdf_reads'])
     self.assertFalse(service.busy)
   finally:release.set();service.close()
