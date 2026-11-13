import tempfile,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.evidence_context import expand
from secretary.knowledge_chat import SearchPlan

class EvidenceContextTest(unittest.TestCase):
 def test_relevant_late_section_and_neighbor_are_read_without_an_extra_model_call(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root);s.archive.configure('codex',False)
   try:
    text='无关开头。'*1600+' RARESECTION 方案选择。'+('解释方案。'*250)+' CONTINUATION 后续限制：仅周二适用。'
    item=s.archive.add('Design guide',text)[0];first=s.archive.retrieve('Design guide')
    stages=[];expanded,count,_=expand(s.archive,'RARESECTION',SearchPlan(['RARESECTION']),first,lambda *args:stages.append(args))
    self.assertGreater(count,0);self.assertIn('RARESECTION',''.join(p['text'] for p in expanded));self.assertTrue(stages)
    self.assertLessEqual(sum(len(p['text']) for p in expanded),24000);self.assertLessEqual(len(expanded),20)
    self.assertEqual({p['item_id'] for p in expanded},{item})
   finally:s.close()
 def test_short_source_needs_no_expansion_and_trashed_source_is_not_added(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root)
   try:
    s.archive.add('Small','Short text');passages=s.archive.retrieve('Short');calls=[]
    self.assertEqual(expand(s.archive,'Short',[],passages,lambda *args:calls.append(args))[1],0);self.assertFalse(calls)
   finally:s.close()

 def test_adjacent_pdf_page_is_read_without_mutating_indexed_ranges(self):
  from pathlib import Path
  from tests.test_large_pdf_preview import fixture
  from secretary import bundles
  with tempfile.TemporaryDirectory() as root:
   source=Path(root)/'source.pdf';fixture(source,pages=7,padding=51*1024*1024)
   s=Service(Path(root)/'data')
   try:
    raw,text=bundles.create('',[{'name':'source.pdf','source':source}])
    try:item=s.archive.add(text=text,filename='materials.stellar.zip',data=raw)[0]
    finally:bundles.cleanup(raw)
    passages=s.archive.retrieve('PAGETOKEN5');self.assertEqual(passages[0]['origin']['page'],5)
    self.assertFalse(s.archive.retrieve('PAGETOKEN6'));before=s.archive.get(item)['pdf_reads'];expanded,count,notice=expand(s.archive,'PAGETOKEN5',['PAGETOKEN5'],passages)
    sixth=[p for p in expanded if p.get('origin',{}).get('page')==6]
    self.assertTrue(sixth);self.assertIn('PAGETOKEN6',sixth[0]['text']);self.assertEqual(before,s.archive.get(item)['pdf_reads'])
    self.assertFalse(s.archive.retrieve('PAGETOKEN6'))
   finally:s.close()
