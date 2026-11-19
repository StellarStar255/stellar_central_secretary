import base64,io,json,tempfile,unittest
import threading
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from secretary import additions,ai,bundles,local_ocr
from secretary.server import Service
from secretary.backup_import import import_backup

def files():
    stream=io.BytesIO();Image.new('RGB',(24,20),'blue').save(stream,format='PNG')
    return [{'name':'new.png','data':base64.b64encode(stream.getvalue()).decode()}]

class AdditionTests(unittest.TestCase):
    def test_plain_addition_survives_running_summary(self):
        from secretary.notes import set_note
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            entered = threading.Event()
            release = threading.Event()
            item_id, _ = service.archive.add('Photo notes', 'Existing source')
            def summarize(*args, **kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('fixture timed out')
                return {'summary':'Completed summary','state':'ready','error':''}
            try:
                with patch.object(ai,'summary_fields',side_effect=summarize) as model:
                    service.queue(item_id,force=True)
                    self.assertTrue(entered.wait(5))
                    with service.lock:
                        future = service.summary_futures[item_id]
                    item = service.archive.get(item_id)
                    set_note(service.archive,item_id,'A note written during the summary',[],item['note_version'])
                    result = service.append_material(item_id, {
                        'text':'','attachments':files(),'expected_updated':service.archive.get(item_id)['updated'],
                        'summarize':False,'read_links':False,
                    })
                    self.assertEqual(result['item']['state'],'processing')
                    self.assertEqual(result['item']['additions'][0]['attachments'][0]['name'],'new.png')
                    with self.assertRaisesRegex(ValueError,'资料正在处理'):
                        service.append_material(item_id, {'text':'Another summary','summarize':True})
                    release.set()
                    future.result(timeout=5)
                    model.assert_called_once()
                saved = service.item_detail(item_id)
                self.assertEqual(saved['summary'],'Completed summary')
                self.assertEqual(saved['note'],'A note written during the summary')
                self.assertEqual(saved['additions'][0]['id'],result['batch_id'])
            finally:
                release.set()
                service.close()

    def test_pasted_generic_image_gets_local_title_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            self.addCleanup(service.close)
            item_id, _ = service.archive.add('A note', 'Original source')
            image = files()[0]
            original = base64.b64decode(image['data'])
            for name, pasted, expected in [('image.png', False, 'image.png'), ('experiment.png', True, 'experiment.png'),
                                           ('image.png', True, '训练 验证损失-'), ('image', True, '训练 验证损失-')]:
                with self.subTest(name=name, pasted=pasted), patch.object(local_ocr, 'recognize', return_value='OK\n训练 / 验证损失'):
                    bundle, _ = bundles.create('', [dict(image, name=name, clipboard_image=pasted)])
                    attachment = bundles.metadata(bundle)[0]
                    self.assertTrue(attachment['name'].startswith(expected))
                    self.assertTrue(attachment['name'].endswith('.png'))
                    self.assertEqual(bundles.attachment(bundle, attachment['id'])[1], original)

            upload = service.uploads.start('image.png', len(original))
            service.uploads.chunk(upload['id'], 0, io.BytesIO(original), len(original))
            with patch.object(local_ocr, 'recognize', return_value=''), patch.object(local_ocr, 'classify', return_value='line_chart'):
                result = service.append_material(item_id, {
                    'attachments': [{'name': 'image.png', 'upload_id': upload['id'], 'clipboard_image': True}],
                    'expected_updated': service.archive.get(item_id)['updated'], 'summarize': False,
                })
            saved = result['item']['additions'][0]['attachments'][0]
            self.assertTrue(saved['name'].startswith('line_chart-'))

    def test_unread_link_can_receive_searchable_supplemental_materials(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item_id,_=service.archive.add(url='https://example.com/unread')
                old=service.archive.get(item_id)
                service.append_material(item_id,{'text':'Additional link background','expected_updated':old['updated'],'summarize':False})
                saved=service.archive.get(item_id)
                self.assertEqual(saved['url'],old['url']);self.assertEqual(saved['text'],'')
                self.assertEqual(saved['addition_count'],1)
                self.assertEqual(service.archive.list(q='link background')[0]['id'],item_id)
            finally:service.close()

    def test_append_summary_retry_backup_and_deletion_preserve_original(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item_id,_=service.archive.add('My title','Original paper text',filename='paper.txt',data=b'Original paper text')
                service.archive.update(item_id,summary='Original summary',category='My category')
                service.archive.set_tags(item_id,['Manual tag'])
                old=service.archive.get(item_id)
                result=service.append_material(item_id,{'text':'New experiment context','attachments':files(),'expected_updated':old['updated'],'summarize':False})
                batch_id=result['batch_id'];saved=service.archive.get(item_id)
                self.assertEqual(len(service.archive.list()),1);self.assertEqual(saved['summary'],'Original summary')
                self.assertEqual((Path(root)/'files'/item_id).read_bytes(),b'Original paper text')
                self.assertEqual(saved['title'],old['title']);self.assertEqual(saved['text'],old['text'])
                answer=json.dumps({'title':'Do not replace title','summary':'New batch summary','tags':['new'],'vision_text':'DistinctBlueFigure visible'})
                with patch.object(ai,'run',return_value=answer) as model:service.process_addition(item_id,batch_id)
                self.assertEqual(model.call_count,1);self.assertEqual(len(model.call_args.kwargs['images']),1)
                saved=service.archive.get(item_id)
                self.assertTrue(saved['summary'].startswith('Original summary'));self.assertIn('New batch summary',saved['summary'])
                self.assertEqual(saved['title'],old['title']);self.assertEqual(saved['tags'],['Manual tag']);self.assertEqual(saved['category'],'My category')
                self.assertEqual(service.archive.list(q='DistinctBlueFigure')[0]['id'],item_id)
                self.assertEqual(service.archive.retrieve('New experiment')[0]['item_id'],item_id)
                with patch.object(ai,'run',return_value=answer):service.process_addition(item_id,batch_id)
                self.assertEqual(service.archive.get(item_id)['summary'].count('New batch summary'),1)
                with tempfile.TemporaryDirectory() as other_root:
                    other=Service(other_root)
                    try:
                        import_backup(other.archive,service.backup());restored=other.archive.list()[0];detail=other.item_detail(restored['id'])
                        self.assertEqual(detail['summary'].count('New batch summary'),1)
                        self.assertEqual(len(detail['additions'][0]['attachments']),1)
                        self.assertNotEqual(detail['additions'][0]['id'],batch_id)
                        self.assertTrue((Path(other_root)/'files'/detail['additions'][0]['id']).is_file())
                    finally:other.close()
                service.delete_item(item_id,service.archive.get(item_id)['updated'])
                self.assertFalse((Path(root)/'files'/batch_id).exists());self.assertFalse((Path(root)/'files'/item_id).exists())
            finally:service.close()

    def test_text_only_stale_revision_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item_id,_=service.archive.add('A note','Original source');old=service.archive.get(item_id)
                with self.assertRaises(ValueError):service.append_material(item_id,{'text':'New','expected_updated':'stale'})
                self.assertEqual(service.archive.get(item_id),old)
                result=service.append_material(item_id,{'text':'Text-only addition','expected_updated':old['updated'],'summarize':False});batch_id=result['batch_id']
                self.assertEqual(len(service.item_detail(item_id)['additions'][0]['attachments']),0)
                with patch.object(ai,'run',side_effect=RuntimeError('Synthetic unavailable model')):service.process_addition(item_id,batch_id)
                self.assertEqual(service.archive.get(item_id)['text'],'Original source')
                self.assertEqual(service.archive.get(item_id)['additions'][0]['state'],'error')
                self.assertTrue((Path(root)/'files'/batch_id).exists())
                additions.update(service.archive,item_id,batch_id,state='processing')
            finally:service.close()
            reopened=Service(root)
            try:self.assertEqual(reopened.archive.get(item_id)['additions'][0]['state'],'error')
            finally:reopened.close()
