import copy,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service
from secretary import notes


class DeleteArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
        self.service.archive.configure('codex',False);self.archive=self.service.archive
        self.item,_=self.archive.add('Private record','Private original text '*30,filename='example.txt',data=b'Private original file')
        self.other,_=self.archive.add('Keep record','Unrelated searchable body '*30)
        image='a'*32
        with self.archive.db() as db:db.execute('UPDATE items SET note=?,note_images=? WHERE id=?',('Private quick note',json.dumps([{'id':image,'name':'example.png','media':'image/png'}]),self.item))
        (self.archive.root/'files'/image).write_bytes(b'Synthetic attachment')
        self.archive.replace_capture(self.item,'Private record','Private refreshed text '*40)
        opened=self.archive.root/'open-files'/self.item;opened.mkdir(parents=True);(opened/'example.txt').write_bytes(b'Private opened copy')
        self.chat={'conversations':[{'id':'chat','title':'Private original title','updated':1,'messages':[
            {'id':'private-user','role':'user','text':'Private original request'},
            {'id':'private-answer','role':'assistant','text':'Private summary copy','items':[self.item]},
            {'id':'safe-user','role':'user','text':'Keep request'},
            {'id':'safe-answer','role':'assistant','text':'Keep summary','items':[self.other]},
            {'id':'private-question','role':'user','text':'Private follow-up'},
            {'id':'private-source-answer','role':'assistant','text':'Private sourced answer','sources':[{'item_id':self.item}]}
        ]}],'activeId':'chat'}
        self.service.chat_history(self.chat)
    def tearDown(self):self.service.close();self.temp.cleanup()

    def test_delete_cleans_record_files_indexes_copies_and_stale_chat_upload(self):
        kept=self.archive.get(self.other);revision=self.archive.get(self.item)['updated']
        result=self.service.delete_item(self.item,revision)
        with self.assertRaises(KeyError):self.archive.get(self.item)
        self.assertEqual(self.archive.get(self.other),kept)
        self.assertEqual(self.archive.list(q='Private'),[])
        with self.archive.db() as db:
            for table in ('search','chunks'):self.assertEqual(db.execute('SELECT count(*) FROM '+table+' WHERE item_id=?',(self.item,)).fetchone()[0],0)
        self.assertFalse((self.archive.root/'files'/self.item).exists());self.assertFalse((self.archive.root/'files'/('a'*32)).exists())
        self.assertFalse(list((self.archive.root/'capture-history').glob(self.item+'-*')))
        self.assertFalse((self.archive.root/'open-files'/self.item).exists())
        self.assertNotIn('Private',json.dumps(result['history']))
        stale=copy.deepcopy(self.chat);stale['conversations'][0]['updated']=999999999999
        saved=self.service.chat_history(stale)
        self.assertEqual(saved['conversations'][0]['title'],'Keep request')
        self.assertEqual([m['id'] for m in saved['conversations'][0]['messages']],['safe-user','safe-answer'])
        self.assertNotIn('Private',(self.archive.root/'conversations.json').read_text())
        stale_title=copy.deepcopy(saved);stale_title['conversations'][0]['title']='Private title without its old messages'
        stale_title['conversations'][0]['updated']+=1
        self.assertEqual(self.service.chat_history(stale_title)['conversations'][0]['title'],'Keep request')
        with zipfile.ZipFile(io.BytesIO(self.service.backup())) as backup:
            self.assertNotIn('files/'+self.item,backup.namelist())
            self.assertNotIn('Private',backup.read('archive.json').decode())
        with self.assertRaises(KeyError):notes.set_note(self.archive,self.item,'late upload',[],0)

    def test_busy_or_changed_record_is_not_deleted(self):
        item=self.archive.get(self.item)
        self.service.busy.add(self.item)
        with self.assertRaises(ValueError):self.service.delete_item(self.item,item['updated'])
        self.service.busy.clear()
        with self.assertRaises(ValueError):self.service.delete_item(self.item,'stale revision')
        self.assertEqual(self.archive.get(self.item),item)

    def test_file_move_failure_rolls_back_and_keeps_record(self):
        original=Path.rename;calls=[];before=self.archive.get(self.item)
        def move(source,target):
            calls.append(str(source))
            if len(calls)==2:raise PermissionError('Synthetic locked file')
            return original(source,target)
        with patch.object(Path,'rename',move),self.assertRaises(PermissionError):self.service.delete_item(self.item,before['updated'])
        self.assertEqual(self.archive.get(self.item),before)
        self.assertIn('Private',(self.archive.root/'conversations.json').read_text())
        self.assertEqual((self.archive.root/'files'/self.item).read_bytes(),b'Private original file')
        self.assertNotIn(self.item,self.archive.deletion_refs()['deletedItemIds'])

    def test_pending_file_cleanup_can_be_retried_without_restoring_record(self):
        with patch('secretary.core.shutil.rmtree',side_effect=PermissionError('Synthetic purge failure')):
            result=self.service.delete_item(self.item,self.archive.get(self.item)['updated'])
            self.assertTrue(result['warning'])
        self.assertTrue((self.archive.root/'delete-pending'/self.item).exists())
        self.assertNotIn('Private',json.dumps(self.service.chat_history()))
        self.archive.finish_deletions()
        self.assertFalse((self.archive.root/'delete-pending'/self.item).exists())

    def test_chat_file_write_failure_does_not_delete_archive(self):
        before=self.archive.get(self.item);chat=(self.archive.root/'conversations.json').read_text()
        with patch.object(Path,'replace',side_effect=PermissionError('Synthetic history lock')):
            with self.assertRaises(PermissionError):self.service.delete_item(self.item,before['updated'])
        self.assertEqual(self.archive.get(self.item),before)
        self.assertEqual((self.archive.root/'conversations.json').read_text(),chat)
        self.assertTrue((self.archive.root/'files'/self.item).exists())

    def test_interrupted_uncommitted_file_staging_is_restored(self):
        stage=self.archive.root/'delete-pending'/self.item;stage.mkdir(parents=True)
        (stage/'plan.json').write_text(json.dumps([['files/'+self.item,'0']]))
        (self.archive.root/'files'/self.item).rename(stage/'0')
        self.archive.finish_deletions()
        self.assertEqual((self.archive.root/'files'/self.item).read_bytes(),b'Private original file')
        self.assertFalse(stage.exists());self.assertEqual(self.archive.get(self.item)['title'],'Private record')


if __name__=='__main__':unittest.main()
