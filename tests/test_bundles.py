import base64,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from secretary import ai,bundles
from secretary.server import Service
from secretary.backup_import import import_backup

def picture():
    stream=io.BytesIO();Image.new('RGB',(32,24),'orange').save(stream,format='PNG');return stream.getvalue()

def files():return [{'name':'example.png','data':base64.b64encode(picture()).decode()},{'name':'context.txt','data':base64.b64encode(b'Synthetic attached context and decisions.').decode()}]

class BundleTest(unittest.TestCase):
    def test_pre_tags_database_migrates_without_losing_search(self):
        from secretary.core import Archive
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root);item,_=archive.add('Legacy record','Legacy source text')
            with archive.db() as db:
                db.execute('ALTER TABLE items DROP COLUMN tags_manual')
                db.execute('ALTER TABLE items DROP COLUMN vision_text')
            upgraded=Archive(root)
            self.assertEqual(upgraded.get(item)['vision_text'],'')
            self.assertEqual(upgraded.list(q='Legacy source')[0]['id'],item)

    def test_one_submission_originals_and_safe_preview_metadata(self):
        data,text=bundles.create('User explanation',files())
        self.assertIn('User explanation',text);self.assertIn('Synthetic attached context',text)
        metadata=bundles.metadata(data);self.assertEqual(len(metadata),2);self.assertEqual(metadata[0]['media'],'image/png')
        _,original=bundles.attachment(data,metadata[0]['id']);self.assertEqual(original,picture())
        with zipfile.ZipFile(io.BytesIO(data)) as archive:self.assertEqual(archive.read('files/02-context.txt'),b'Synthetic attached context and decisions.')
        source,images,scope=bundles.model_material(data,text)
        self.assertEqual(len(images),1);self.assertEqual(images[0]['media'],'image/jpeg');self.assertIn('context.txt',source)

    def test_combined_question_uses_current_material_once_and_indexes_vision(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                result=service.ingest({'text':'Please explain the screenshot and context','attachments':files(),'defer_summary':True});item=result['item']
                self.assertEqual(len(service.archive.list()),1)
                answer={'title':'Combined record','summary':'Combined summary','category':'Examples','tags':['Example'],'vision_text':'DistinctiveVisionOrange visible in the picture.','answer':'The image and text agree. [1]'}
                with patch.object(ai,'run',return_value=json.dumps(answer)) as model:
                    response=service.ask('Explain this material',[item['id']])
                self.assertEqual(model.call_count,1);self.assertEqual(len(model.call_args.kwargs['images']),1)
                self.assertIn('The image and text agree',response['answer'])
                self.assertEqual(response['sources'][0]['item_id'],item['id'])
                saved=service.archive.get(item['id']);self.assertNotIn('DistinctiveVisionOrange',saved['text'])
                self.assertEqual(service.archive.list(q='DistinctiveVisionOrange')[0]['id'],item['id'])
                self.assertEqual(service.archive.retrieve('DistinctiveVisionOrange')[0]['item_id'],item['id'])
                with tempfile.TemporaryDirectory() as destination:
                    other=Service(destination)
                    try:
                        import_backup(other.archive,service.backup());restored=other.archive.list()[0]
                        self.assertIn('DistinctiveVisionOrange',other.archive.get(restored['id'])['vision_text'])
                        restored_data=(other.archive.root/'files'/restored['id']).read_bytes()
                        self.assertEqual(bundles.attachment(restored_data,item['attachments'][0]['id'])[1],picture())
                    finally:other.close()
            finally:service.close()

    def test_model_failure_keeps_all_originals(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item=service.ingest({'text':'Question','attachments':files(),'defer_summary':True})['item']
                with patch.object(ai,'run',side_effect=RuntimeError('Synthetic unavailable vision model')):
                    with self.assertRaises(RuntimeError):service.ask('Question',[item['id']])
                self.assertEqual(service.archive.get(item['id'])['vision_text'],'')
                self.assertEqual(len(service.item_detail(item['id'])['attachments']),2)
            finally:service.close()

    def test_invalid_bundle_paths_and_attachment_limits(self):
        with self.assertRaises(ValueError):bundles.create('',files()*11)
        with self.assertRaises(ValueError):bundles.create('',[files()[0]]*9)
        data,_=bundles.create('',files());source=zipfile.ZipFile(io.BytesIO(data));manifest=json.loads(source.read('manifest.json'));manifest['files'][0]['path']='../escape'
        altered=io.BytesIO()
        with zipfile.ZipFile(altered,'w') as target:
            for name in source.namelist():target.writestr(name,json.dumps(manifest) if name=='manifest.json' else source.read(name))
        source.close()
        with self.assertRaises(ValueError):bundles.load(altered.getvalue())

    def test_codex_and_claude_receive_image_data_without_file_tools(self):
        for backend in ('codex','claude'):
            proc=Mock(returncode=0)
            def communicate(prompt,timeout):
                if backend=='claude':
                    content=json.loads(prompt)['message']['content'];self.assertEqual(content[1]['type'],'image')
                    self.assertEqual(base64.b64decode(content[1]['source']['data']),b'JPEG fixture')
                    return json.dumps({'result':'done'}),''
                command=popen.call_args.args[0];path=Path(command[command.index('--image')+1]);self.assertEqual(path.read_bytes(),b'JPEG fixture')
                self.assertIn('read-only',command);return json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'done'}}),''
            proc.communicate.side_effect=communicate
            with patch.object(ai,'executable',return_value='synthetic-cli'),patch.object(ai.network,'child_env',return_value={}),patch.object(ai.subprocess,'Popen',return_value=proc) as popen:
                self.assertEqual(ai.run('Prompt',backend,images=[{'name':'example.jpg','media':'image/jpeg','data':b'JPEG fixture'}]),'done')
                if backend=='claude':self.assertIn('stream-json',popen.call_args.args[0]);self.assertIn('--tools',popen.call_args.args[0])

if __name__=='__main__':unittest.main()
