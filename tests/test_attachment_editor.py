import base64,io,json,tempfile,unittest,zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from secretary import attachment_editor as editor,bundles
from secretary.server import Service
from pdf_fixture import pdf_bytes

def sheet(value):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr(zipfile.ZipInfo('xl/worksheets/sheet1.xml',(2020,1,1,0,0,0)),'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'+value+'</t></is></c></row></sheetData></worksheet>')
    return stream.getvalue()

class AttachmentEditorTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name);self.service.archive.configure('codex',False)
    def tearDown(self):self.service.close();self.temp.cleanup()
    def open(self,item,key='',batch=''):
        with patch.object(editor,'launch') as launch:self.service.edit_file(item,'open',batch,key)
        return launch.call_args.args[0]
    def test_root_file_opens_with_name_preserves_local_edits_and_saves_index_and_backup(self):
        item=self.service.ingest({'filename':'Research workbook.xlsx','data':base64.b64encode(sheet('OldCell')).decode()})['item'];old=self.service.archive.get(item['id'])
        target=self.open(item['id']);self.assertEqual(target.name,'Research workbook.xlsx');target.write_bytes(sheet('NewCell'))
        self.assertEqual(self.open(item['id']).read_bytes(),sheet('NewCell'))
        self.assertEqual(self.service.archive.get(item['id']),old)
        with patch('secretary.ai.run') as model:result=self.service.edit_file(item['id'],'save');model.assert_not_called()
        self.assertTrue(result['changed']);current=self.service.item_detail(item['id']);self.assertIn('NewCell',current['text']);self.assertEqual(current['state'],'saved')
        self.assertTrue(self.service.archive.retrieve('NewCell'));self.assertFalse(self.service.archive.retrieve('OldCell'))
        self.assertFalse(self.service.edit_file(item['id'],'save')['changed'])
        versions=list((target.parent/'history').glob('*/Research workbook.xlsx'));self.assertEqual(len(versions),1);self.assertEqual(versions[0].read_bytes(),sheet('OldCell'))
        with zipfile.ZipFile(io.BytesIO(self.service.backup())) as backup:self.assertEqual(backup.read('files/'+item['id']),sheet('NewCell'))
    def test_bundle_edit_keeps_attachment_ids_other_files_and_marks_old_summary(self):
        data,source=bundles.create('Original context',[{'name':'notes.txt','data':base64.b64encode(b'old keyword').decode()},{'name':'other.txt','data':base64.b64encode(b'unrelated preserved').decode()}])
        item,_=self.service.archive.add('Group',source,filename='materials.stellar.zip',data=data);self.service.archive.update(item,summary='Prior summary',state='ready')
        files=self.service.item_detail(item)['attachments'];key=files[0]['id'];target=self.open(item,key);target.write_text('new searchablekeyword')
        self.service.edit_file(item,'save',key=key)
        current=self.service.item_detail(item);self.assertEqual([f['id'] for f in current['attachments']],[f['id'] for f in files]);self.assertIn('Prior summary',current['summary']);self.assertIn(editor.STALE,current['summary'])
        self.assertIn('Original context',current['text']);self.assertTrue(self.service.archive.retrieve('searchablekeyword'))
        self.assertEqual(bundles.attachment((self.service.archive.root/'files'/item).read_bytes(),files[1]['id'])[1],b'unrelated preserved')
    def test_appended_workbook_updates_same_batch_without_touching_parent_pdf(self):
        parent=self.service.ingest({'filename':'parent.pdf','data':base64.b64encode(pdf_bytes()).decode()})['item'];self.service.archive.update(parent['id'],summary='Parent summary',state='ready')
        before=self.service.archive.get(parent['id']);original=(self.service.archive.root/'files'/parent['id']).read_bytes()
        saved=self.service.append_material(parent['id'],{'text':'Additional workbook','attachments':[{'name':'batch.xlsx','data':base64.b64encode(sheet('Before')).decode()}],'expected_updated':before['updated'],'summarize':False})
        batch=saved['item']['additions'][0];key=batch['attachments'][0]['id'];target=self.open(parent['id'],key,batch['id']);target.write_bytes(sheet('AfterBatchCell'))
        self.service.edit_file(parent['id'],'save',batch['id'],key);current=self.service.item_detail(parent['id'])
        self.assertEqual(len(current['additions']),1);self.assertEqual(current['additions'][0]['id'],batch['id']);self.assertIn('AfterBatchCell',current['additions'][0]['text'])
        self.assertEqual(current['base_summary'],'Parent summary');self.assertEqual(current['text'],before['text']);self.assertEqual((self.service.archive.root/'files'/parent['id']).read_bytes(),original)
        self.assertTrue(self.service.archive.retrieve('AfterBatchCell'))
    def test_busy_save_and_conflicts_keep_local_work_and_original(self):
        item=self.service.ingest({'filename':'notes.txt','data':base64.b64encode(b'original').decode()})['item'];target=self.open(item['id']);target.write_bytes(b'local edits')
        self.service.busy.add(item['id'])
        try:
            with self.assertRaisesRegex(ValueError,'资料正在处理'):self.service.edit_file(item['id'],'save')
        finally:self.service.busy.discard(item['id'])
        (self.service.archive.root/'files'/item['id']).write_bytes(b'new archive version')
        with self.assertRaisesRegex(ValueError,'其他操作更新'):self.service.edit_file(item['id'],'save')
        self.assertEqual(target.read_bytes(),b'local edits');self.assertEqual((self.service.archive.root/'files'/item['id']).read_bytes(),b'new archive version')
    def test_ownership_and_active_file_types_are_checked(self):
        item=self.service.ingest({'filename':'run.command','data':base64.b64encode(b'echo must-not-run').decode()})['item']
        with patch.object(editor,'launch') as launch:
            with self.assertRaisesRegex(ValueError,'此文件类型'):self.service.edit_file(item['id'],'open')
            launch.assert_not_called()
        with self.assertRaises(ValueError):editor.directory(self.service.archive,'../outside','','')
        with self.assertRaises(KeyError):self.service.edit_file(item['id'],'open','f'*32,'a'*32)
    def test_failed_database_commit_restores_file_and_keeps_editing_copy(self):
        item=self.service.ingest({'filename':'notes.txt','data':base64.b64encode(b'original').decode()})['item'];target=self.open(item['id']);target.write_bytes(b'new content')
        old=self.service.archive.get(item['id']);original_db=self.service.archive.db
        @contextmanager
        def fail_commit():
            with original_db() as db:
                updated=[];db.set_trace_callback(lambda sql:updated.append(True) if sql.startswith('UPDATE items SET digest=') else None)
                yield db
                if updated:raise RuntimeError('Synthetic commit failure')
        with patch.object(self.service.archive,'db',side_effect=fail_commit):
            with self.assertRaisesRegex(RuntimeError,'commit failure'):self.service.edit_file(item['id'],'save')
        self.assertEqual(self.service.archive.get(item['id']),old);self.assertEqual((self.service.archive.root/'files'/item['id']).read_bytes(),b'original');self.assertEqual(target.read_bytes(),b'new content')
    def test_deletion_cleans_editing_copies_and_local_versions(self):
        item=self.service.ingest({'filename':'notes.txt','data':base64.b64encode(b'old').decode()})['item'];target=self.open(item['id']);target.write_bytes(b'changed');self.service.edit_file(item['id'],'save')
        current=self.service.archive.get(item['id']);self.service.archive.delete(item['id'],current['updated'])
        self.assertFalse((self.service.archive.root/'open-files'/item['id']).exists())
    def test_filenames_do_not_collide_with_edit_metadata_or_history(self):
        for name in ('edit.json','metadata.json'):
            original=json.dumps({'name':name,'version':'old'}).encode();changed=json.dumps({'name':name,'version':'new'}).encode()
            item=self.service.ingest({'filename':name,'data':base64.b64encode(original).decode()})['item'];target=self.open(item['id'])
            self.assertEqual(target.read_bytes(),original);target.write_bytes(changed);self.service.edit_file(item['id'],'save')
            self.assertEqual((self.service.archive.root/'files'/item['id']).read_bytes(),changed)
            histories=list((target.parent/'history').glob('*/'+name));self.assertEqual(histories[0].read_bytes(),original)
    def test_default_open_and_reveal_use_argument_lists(self):
        item=self.service.ingest({'filename':'workbook $(example).xlsx','data':base64.b64encode(sheet('Synthetic')).decode()})['item']
        with patch.object(editor.sys,'platform','darwin'),patch.object(editor.subprocess,'run') as run:
            self.service.edit_file(item['id'],'open');self.assertEqual(run.call_args.args[0][0],'/usr/bin/open');self.assertIn('workbook $(example).xlsx',run.call_args.args[0][-1])
            self.service.edit_file(item['id'],'reveal');self.assertEqual(run.call_args.args[0][:2],['/usr/bin/open','-R'])
