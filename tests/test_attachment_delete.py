import base64,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service
from secretary import bundles,notes,attachment_delete as deletion
from PIL import Image

def file(name,data):return {'name':name,'data':base64.b64encode(data).decode()}

class AttachmentDeleteTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.service.archive.configure('codex',False)
    def tearDown(self):self.service.close();self.temp.cleanup()
    def delete(self,item,key='',batch=''):
        return self.service.delete_attachment(item['id'],batch,key,{'confirmed':True,'expected_updated':item['updated']})
    def test_removes_only_selected_original_and_reindexes_preserving_ids(self):
        item=self.service.ingest({'text':'Keep annotation','attachments':[file('same.txt',b'DeleteSourceKeyword'),file('same.txt',b'KeepSourceKeyword')],'archive_only':True})['item']
        notes.set_note(self.service.archive,item['id'],'Keep my private note',[],0);self.service.archive.update(item['id'],summary='Original summary')
        item=self.service.item_detail(item['id']);first,second=item['attachments'];self.delete(item,first['id'])
        saved=self.service.item_detail(item['id']);self.assertEqual(saved['note'],item['note']);self.assertEqual(saved['title'],item['title']);self.assertNotIn('DeleteSourceKeyword',saved['text']);self.assertIn('KeepSourceKeyword',saved['text']);self.assertTrue(saved['base_summary'].startswith(deletion.STALE))
        source=(self.service.archive.root/'files'/item['id']).read_bytes();self.assertEqual(bundles.metadata(source)[0]['id'],second['id']);self.assertEqual(bundles.attachment(source,second['id'])[1],b'KeepSourceKeyword')
        with self.assertRaises(KeyError):bundles.attachment(source,first['id'])
        backups=list((self.service.archive.root/'open-files'/item['id']).rglob('same.txt'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),b'DeleteSourceKeyword')
    def test_same_named_added_files_are_independent_and_last_file_keeps_batch(self):
        item=self.service.ingest({'text':'Original body','archive_only':True})['item']
        item=self.service.append_material(item['id'],{'text':'','attachments':[file('duplicate.txt',b'FirstBatch')],'expected_updated':item['updated'],'summarize':False})['item']
        item=self.service.append_material(item['id'],{'text':'','attachments':[file('duplicate.txt',b'SecondBatch')],'expected_updated':item['updated'],'summarize':False})['item']
        before=self.service.item_detail(item['id']);batch=before['additions'][0];key=batch['attachments'][0]['id'];other=before['additions'][1]
        self.delete(before,key,batch['id']);after=self.service.item_detail(item['id'])
        self.assertEqual(len(after['additions']),2);self.assertEqual(after['text'],before['text']);self.assertEqual(after['additions'][0]['attachments'],[]);self.assertIn(deletion.EMPTY,after['additions'][0]['text']);self.assertEqual(after['additions'][1]['text'],other['text']);self.assertEqual(len(after['all_attachments']),1)
    def test_single_primary_file_removal_retains_record_and_user_prose(self):
        item=self.service.ingest({'filename':'original.txt','data':base64.b64encode(b'File body').decode(),'archive_only':True})['item']
        notes.set_note(self.service.archive,item['id'],'Private note',[],0);self.service.archive.update(item['id'],text='User edited prose');item=self.service.archive.get(item['id']);self.delete(item)
        saved=self.service.item_detail(item['id']);self.assertEqual(saved['filename'],'');self.assertEqual(saved['text'],'User edited prose');self.assertEqual(saved['note'],'Private note');self.assertFalse((self.service.archive.root/'files'/item['id']).exists());self.assertEqual(saved['all_attachments'],[])
    def test_confirmation_stale_version_and_busy_reject_without_mutating(self):
        item=self.service.ingest({'text':'Sample','attachments':[file('sample.txt',b'Original')],'archive_only':True})['item'];key=self.service.item_detail(item['id'])['attachments'][0]['id'];path=self.service.archive.root/'files'/item['id'];before=path.read_bytes()
        for body in ({'expected_updated':item['updated']},{'confirmed':True,'expected_updated':'stale'}):
            with self.assertRaises(ValueError):self.service.delete_attachment(item['id'],'',key,body)
        self.service.busy.add(item['id'])
        with self.assertRaises(ValueError):self.delete(item,key)
        self.service.busy.clear();self.assertEqual(path.read_bytes(),before)
    def test_failure_after_file_replacement_rolls_back_archive_and_database(self):
        item=self.service.ingest({'text':'Sample','attachments':[file('one.txt',b'One'),file('two.txt',b'Two')],'archive_only':True})['item'];key=self.service.item_detail(item['id'])['attachments'][0]['id'];path=self.service.archive.root/'files'/item['id'];before=path.read_bytes();record=self.service.archive.get(item['id'])
        real_db=self.service.archive.db
        from contextlib import contextmanager
        calls=0
        @contextmanager
        def db():
            nonlocal calls
            calls+=1
            with real_db() as connection:
                yield connection
                if calls>=2:raise OSError('Simulated commit failure')
        with patch.object(self.service.archive,'db',side_effect=db):
            with self.assertRaises(OSError):self.delete(item,key)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.service.archive.get(item['id']),record)
