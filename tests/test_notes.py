import base64,io,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from secretary import notes
from secretary.core import Archive
from secretary.server import Service
from secretary.backup_import import import_backup

def png():
 stream=io.BytesIO();Image.new('RGB',(8,8),'#77aacc').save(stream,format='PNG');return stream.getvalue()
def attachment():return {'name':'example.png','data':base64.b64encode(png()).decode()}

class NotesTest(unittest.TestCase):
 def test_note_text_and_image_are_local_and_survive_ai_updates(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Fixture','Original body.')
   saved=notes.set_note(archive,item,'PersonalMemoUnique',[attachment()],0)
   image=saved['note_images'][0];self.assertEqual((archive.root/'files'/image['id']).read_bytes(),png())
   self.assertEqual(archive.list(q='PersonalMemoUnique Fixture')[0]['id'],item)
   self.assertFalse(archive.retrieve('PersonalMemoUnique'))
   archive.update(item,summary='AI summary',tags=['AI tag'])
   archive.replace_capture(item,'New title','Original body with more context.')
   self.assertEqual(archive.get(item)['note'],'PersonalMemoUnique')
   self.assertEqual(notes.note_image(archive,item,image['id'])[0]['media'],'image/png')
   with self.assertRaises(KeyError):notes.note_image(archive,item,'../outside')

 def test_version_conflict_and_bad_image_preserve_saved_note_and_files(self):
  with tempfile.TemporaryDirectory() as root:
   archive=Archive(root);item,_=archive.add('Fixture','Original body.');notes.set_note(archive,item,'Saved',[attachment()],0)
   before=archive.get(item);files=set((archive.root/'files').iterdir())
   with self.assertRaisesRegex(ValueError,'其他窗口'):notes.set_note(archive,item,'Stale',[],0)
   with self.assertRaises(ValueError):notes.set_note(archive,item,'Invalid',[attachment(),{'data':base64.b64encode(b'not an image').decode()}],1)
   self.assertEqual(archive.get(item),before);self.assertEqual(set((archive.root/'files').iterdir()),files)
   with self.assertRaises(ValueError):notes.set_note(archive,item,'x',[{'id':'a'*32}],1)

 def test_remove_image_and_roundtrip_backup(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as restored:
   service=Service(root)
   try:
    item,_=service.archive.add('Fixture','Original body.');saved=notes.set_note(service.archive,item,'My notes',[attachment()],0)
    archive=Archive(restored);import_backup(archive,service.backup());copy=archive.get(archive.list()[0]['id'])
    self.assertEqual(copy['note'],'My notes');self.assertEqual(notes.note_image(archive,copy['id'],copy['note_images'][0]['id'])[1].read_bytes(),png())
    image_id=saved['note_images'][0]['id'];notes.set_note(service.archive,item,'Edited',[],1)
    self.assertFalse((service.archive.root/'files'/image_id).exists());self.assertEqual(service.archive.get(item)['note'],'Edited')
   finally:service.close()

class BrowserCleanupTest(unittest.TestCase):
 def test_does_not_close_browser_with_existing_page_or_active_capture(self):
  with tempfile.TemporaryDirectory() as root:
   service=Service(root)
   browser=Mock();browser.contexts=[SimpleNamespace(pages=[SimpleNamespace(url='https://example.test/existing')])]
   pw=Mock();pw.chromium.connect_over_cdp.return_value=browser
   context=Mock();context.__enter__=Mock(return_value=pw);context.__exit__=Mock(return_value=False)
   try:
    with patch('secretary.browser_reader.existing_session',return_value={'websocket':'ws://127.0.0.1:1234/fixture'}),patch('playwright.sync_api.sync_playwright',return_value=context):
     self.assertEqual(service.close_capture_browsers(only_empty=True)['closed'],0);browser.new_browser_cdp_session.assert_not_called()
     browser.contexts=[SimpleNamespace(pages=[SimpleNamespace(url='about:blank')])]
     self.assertEqual(service.close_capture_browsers(only_empty=True)['closed'],2)
     browser.new_browser_cdp_session.return_value.send.assert_called_with('Browser.close')
    service.captures['fixture']=Mock()
    with self.assertRaises(ValueError):service.close_capture_browsers()
   finally:service.captures.clear();service.close()

if __name__=='__main__':unittest.main()
