import base64,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from secretary.media import byte_range
from secretary.server import Service,handler


class MediaTest(unittest.TestCase):
    def test_ranges(self):
        for value,bounds in [('bytes=0-1',(0,1)),('bytes=5-',(5,9)),('bytes=-3',(7,9)),('bytes=8-99',(8,9)),('bytes=-99',(0,9))]:
            self.assertEqual(byte_range(value,10),bounds)
        for value in ['bytes=10-','bytes=4-1','bytes=-0','bytes=-','bytes=0-1,4-5','items=0-1']:
            with self.assertRaises(ValueError):byte_range(value,10)

    def test_original_bundle_and_added_video_ranges_preserve_downloads(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            content=b'0123456789abcdef';encoded=base64.b64encode(content).decode()
            item_id,_=service.archive.add('Original',filename='clip.MP4',data=content)
            bundled=service.ingest({'attachments':[{'name':'clip.mp4','data':encoded}],'archive_only':True})['item']
            added=service.append_material(bundled['id'],{'attachments':[{'name':'extra.webm','data':base64.b64encode(b'Z'+content[1:]).decode()}], 'expected_updated':bundled['updated'],'summarize':False})['item']
            urls=[f'/api/items/{item_id}/preview']+[f['preview_url'] for f in service.material_attachments(added)['all_attachments']]
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_port}'
            try:
                for path in urls:
                    with opener.open(urllib.request.Request(base+path,headers={'Range':'bytes=2-5'})) as response:
                        self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345')
                        self.assertEqual(response.headers['Content-Range'],'bytes 2-5/16');self.assertTrue(response.headers['Content-Type'].startswith('video/'))
                    with self.assertRaises(urllib.error.HTTPError) as error:opener.open(urllib.request.Request(base+path,headers={'Range':'bytes=99-'}))
                    self.assertEqual(error.exception.code,416);self.assertEqual(error.exception.headers['Content-Range'],'bytes */16')
                with opener.open(base+f'/api/items/{item_id}/file') as response:
                    self.assertEqual(response.read(),content);self.assertIn('attachment',response.headers['Content-Disposition'])
            finally:server.shutdown();server.server_close();service.close()
