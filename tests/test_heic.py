import base64,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from secretary import ai,bundles,image_formats,thumbnails
from secretary.server import Service

FIXTURE=Path(__file__).parent/'fixtures/synthetic.heic'

def legacy_bundle():
    data,text=bundles.create('',[{'name':'IMG_1.HEIC','data':base64.b64encode(FIXTURE.read_bytes()).decode()}])
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        manifest=json.loads(source.read('manifest.json'));manifest['files'][0]['media']='application/octet-stream'
        result=io.BytesIO()
        with zipfile.ZipFile(result,'w') as target:
            for name in source.namelist():target.writestr(name,json.dumps(manifest) if name=='manifest.json' else source.read(name))
    return result.getvalue(),bundles.assemble(manifest)

class HeicTest(unittest.TestCase):
    def test_real_decode_orientation_and_preserved_original(self):
        original=FIXTURE.read_bytes()
        for name in ('IMG_1.HEIC','photo.heif','photo.hif'):
            data,text=bundles.create('',[{'name':name,'data':base64.b64encode(original).decode()}])
            file=bundles.metadata(data)[0];self.assertEqual(file['media'],'image/heic')
            self.assertEqual(bundles.attachment(data,file['id'])[1],original)
            _,images,_=bundles.model_material(data,text);self.assertEqual(len(images),1)
            for raw in (images[0]['data'],image_formats.preview(original),thumbnails.render(name,original)[0]):
                with Image.open(io.BytesIO(raw)) as image:
                    image.load();self.assertGreater(image.height,image.width)
                    # The original left blue half becomes the upper half after rotation.
                    pixel=image.convert('RGB').getpixel((image.width//2,image.height//4))
                    self.assertGreater(pixel[2],pixel[0])

    def test_legacy_bundle_summary_receives_actual_image(self):
        data,text=legacy_bundle();self.assertEqual(bundles.metadata(data)[0]['media'],'image/heic')
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                ident,_=service.archive.add('Old HEIC',text,filename='materials.stellar.zip',data=data)
                result={'title':'Decoded HEIC','summary':'Blue and orange blocks','category':'Test','tags':['HEIC'],'vision_text':'Blue upper half, orange lower half','answer':'Visible blocks [1]'}
                with patch.object(ai,'run',return_value=json.dumps(result)) as model:
                    response=service.ask_material('Describe the photo',[ident])
                self.assertIn('Visible blocks',response['answer'])
                image=model.call_args.kwargs['images'][0];self.assertEqual(image['media'],'image/jpeg')
                with Image.open(io.BytesIO(image['data'])) as decoded:self.assertEqual(decoded.size,(64,96))
                self.assertEqual((service.archive.root/'files'/ident).read_bytes(),data)
                self.assertIn('Blue upper half',service.archive.get(ident)['vision_text'])
            finally:service.close()

    def test_corrupt_and_oversized_images_do_not_reach_model(self):
        with self.assertRaisesRegex(ValueError,'无法解码'):image_formats.preview(b'broken HEIC')
        with patch('secretary.image_formats.Image.open') as opened:
            opened.return_value.__enter__.return_value.width=10000
            opened.return_value.__enter__.return_value.height=10000
            with self.assertRaisesRegex(ValueError,'4000'):image_formats.preview(b'synthetic')

    def test_raw_legacy_photo_without_text_can_be_summarized(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                ident,_=service.archive.add('Raw HEIC','',filename='raw.HEIC',data=FIXTURE.read_bytes())
                with patch.object(service.pool,'submit') as submit:
                    service.queue(ident,force=True);submit.assert_called_once()
                result={'title':'Photo','summary':'Two colored blocks','category':'Test','tags':[],'vision_text':'Blue and orange'}
                with patch.object(ai,'run',return_value=json.dumps(result)) as model:service.process(ident)
                self.assertEqual(len(model.call_args.kwargs['images']),1)
                self.assertEqual(service.archive.get(ident)['state'],'ready')
                self.assertEqual((service.archive.root/'files'/ident).read_bytes(),FIXTURE.read_bytes())
            finally:service.close()
