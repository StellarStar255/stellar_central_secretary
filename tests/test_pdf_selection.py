import io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_large_pdf_preview import fixture
from secretary import bundles,pdf_reading,pdf_preview,local_ocr
from secretary.server import Service,service_pdf_material

class PdfSelectionTest(unittest.TestCase):
 def test_range_continuation_search_and_summary_scope(self):
  with tempfile.TemporaryDirectory() as temp:
   source=Path(temp)/'source.pdf';fixture(source,pages=9)
   service=Service(Path(temp)/'data');service.archive.configure('codex',False)
   try:
    raw,text=bundles.create('',[{'name':'source.pdf','source':source}]);item_id,_=service.archive.add(text=text,filename='materials.stellar.zip',data=raw);bundles.cleanup(raw)
    item=service.item_detail(item_id);key=item['attachments'][0]['id'];original=(service.archive.root/'files'/item_id).read_bytes()
    result=pdf_reading.read(service.archive,item_id,None,key,{'start':6,'end':9})
    self.assertEqual(result['read_pages'],list(range(1,10)));self.assertIn('PAGETOKEN9',result['pages'][-1]['text'])
    self.assertTrue(service.archive.list(q='PAGETOKEN9'));self.assertTrue(service.archive.retrieve('PAGETOKEN9'));self.assertEqual(service.archive.retrieve('PAGETOKEN9')[0]['origin']['page'],9)
    source,scope=service_pdf_material(service.archive,service.archive.get(item_id),'original','default')
    self.assertIn('PAGETOKEN9',source);self.assertIn('1,2,3,4,5,6,7,8,9',scope)
    self.assertEqual(original,(service.archive.root/'files'/item_id).read_bytes())
    with self.assertRaises(ValueError):pdf_reading.read(service.archive,item_id,None,key,{'start':0,'end':1})
    with self.assertRaises(ValueError):pdf_reading.read(service.archive,item_id,None,key,{'start':1,'end':11})
   finally:service.close()
 @unittest.skipUnless(sys.platform in ('darwin','win32') or __import__('shutil').which('tesseract'),'Installed native OCR engine')
 def test_actual_scanned_page_ocr(self):
  from PIL import Image,ImageDraw,ImageFont
  with tempfile.TemporaryDirectory() as temp:
   image=Image.new('RGB',(1000,250),'white');ImageDraw.Draw(image).text((30,80),'STELLAR SCAN 58319',fill='black',font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf' if sys.platform=='darwin' else 'C:/Windows/Fonts/arial.ttf' if sys.platform=='win32' else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',48))
   source=Path(temp)/'scan.pdf';image.save(source,'PDF')
   self.assertFalse(pdf_preview.inspect(source)['pages'][0]['text'])
   with patch('secretary.ai.run',side_effect=AssertionError('Cloud call')):result=pdf_preview.inspect(source,1,1,True)
   self.assertIn('58319',result['pages'][0]['text']);self.assertEqual(result['pages'][0]['method'],'ocr')
