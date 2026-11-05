import io,unittest
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from secretary import thumbnails
from pdf_fixture import pdf_bytes

class ThumbnailTest(unittest.TestCase):
    def test_pdf_first_page_is_bounded_png(self):
        data,media=thumbnails.render('report.pdf',pdf_bytes(pages=3))
        self.assertEqual(media,'image/png')
        with Image.open(io.BytesIO(data)) as image:self.assertEqual(image.size,(320,160))
    def test_image_preview_is_bounded_and_original_pixels_retained(self):
        output=io.BytesIO();Image.new('RGB',(1600,800),'blue').save(output,format='PNG')
        data,media=thumbnails.render('picture.png',output.getvalue())
        self.assertEqual(media,'image/png')
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size,(320,160));self.assertEqual(image.convert('RGB').getpixel((10,10)),(0,0,255))
    def test_broken_encrypted_and_unsupported_files_have_safe_type_cards(self):
        for name,source in [('bad.pdf',b'broken'),('locked.pdf',pdf_bytes(password='secret')),('notes.txt',b'<script>')]:
            data,media=thumbnails.render(name,source)
            self.assertEqual(media,'image/svg+xml');self.assertNotIn(b'<script>',data)
    def test_concurrent_pdf_previews_and_new_content(self):
        samples=[pdf_bytes(password='',pages=i+1) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda data:thumbnails.render('report.pdf',data),samples))
        self.assertTrue(all(media=='image/png' for _,media in results))
        self.assertNotEqual(thumbnails.render('picture.png',b'bad')[1],results[0][1])
