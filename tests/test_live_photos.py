import base64,tempfile,unittest
from pathlib import Path
from secretary import live_photos
from secretary.server import Service

FIXTURES=Path(__file__).parent/'fixtures'

def photo_files(video=True):
    files=[{'name':'IMG_1.HEIC','data':base64.b64encode((FIXTURES/'synthetic.heic').read_bytes()).decode()}]
    if video:files.append({'name':'img_1.MOV','data':base64.b64encode((FIXTURES/'live-photo.mov').read_bytes()).decode()})
    return files

class LivePhotoTest(unittest.TestCase):
    def test_catalog_pairs_originals_without_replacing_either(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item=service.ingest({'attachments':photo_files(),'defer_summary':True})['item']
                photo,video=item['all_attachments']
                self.assertEqual(photo['live_video']['preview_url'],video['preview_url'])
                self.assertEqual(photo['live_video']['download_url'],video['download_url'])
                self.assertNotIn('live_video',video)
                # A legacy photo gains motion after its MOV is appended in a later batch.
                other=service.ingest({'text':'Separate legacy item','attachments':photo_files(False),'defer_summary':True})['item']
                self.assertNotIn('live_video',other['all_attachments'][0])
                service.append_material(other['id'],{'attachments':photo_files()[1:],'expected_updated':other['updated'],'summarize':False})
                linked=service.item_detail(other['id'])['all_attachments']
                self.assertEqual(linked[0]['live_video']['preview_url'],linked[1]['preview_url'])
                self.assertEqual(service.item_detail(item['id'])['all_attachments'][0]['live_video'],photo['live_video'])
            finally:service.close()

    def test_ambiguous_cross_batch_names_do_not_guess(self):
        def entry(name,batch,path):return dict(name=name,batch_id=batch,preview_url=path,download_url=path+'/file',can_open=True)
        photo=entry('photo.HEIC','a','photo');one=entry('PHOTO.mov','b','one');two=entry('photo.MOV','c','two')
        live_photos.annotate([photo,one,two]);self.assertNotIn('live_video',photo)
        one['batch_id']='a';live_photos.annotate([photo,one,two]);self.assertEqual(photo['live_video']['preview_url'],'one')
        # Removing the companion removes the derived association.
        live_photos.annotate([photo]);self.assertNotIn('live_video',photo)
        unrelated=entry('different.MOV','a','unrelated');live_photos.annotate([photo,unrelated]);self.assertNotIn('live_video',photo)
        duplicate=entry('photo.heif','a','duplicate');live_photos.annotate([photo,duplicate,one]);self.assertNotIn('live_video',photo)
