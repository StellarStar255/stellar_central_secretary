import io,tempfile,threading,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from secretary import desktop_downloads,bundles
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
class DesktopDownloadsTest(unittest.TestCase):
 def test_owned_routes_and_real_original_added_attachment_downloads(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data');service.archive.configure('codex',False)
   original,_=service.archive.add('clip',filename='原始 视频.mp4',data=b'ORIGINAL')
   raw,text=bundles.create('',[{'name':'同次 视频.mp4','data':__import__('base64').b64encode(b'BUNDLE').decode()}]);ident,_=service.archive.add(text=text,filename='materials.stellar.zip',data=raw);bundles.cleanup(raw)
   item=service.append_material(ident,{'attachments':[{'name':'追加 视频.mp4','data':__import__('base64').b64encode(b'ADDED').decode()}],'expected_updated':service.archive.get(ident)['updated'],'summarize':False})['item']
   server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
   try:
    files=service.material_attachments(item)['all_attachments'];cases=[(f'/api/items/{original}/file','原始 视频.mp4',b'ORIGINAL')]+[(file['download_url'],file['name'],b'BUNDLE' if not file['batch_id'] else b'ADDED') for file in files]
    for path,name,data in cases:
     self.assertEqual(desktop_downloads.filename(base,base+path),name);target=Path(temp)/name;desktop_downloads.save(base,base+path,target);self.assertEqual(target.read_bytes(),data)
    self.assertIsNotNone(desktop_downloads.route(base,base+f'/api/items/{ident}/additions/{item["additions"][0]["id"]}/file'))
    for url in ('https://example.com/api/backup',base+'/api/items/'+ident,base+'/api/items/'+ident+'/preview',base+'/api/backup?next=elsewhere'):
     self.assertIsNone(desktop_downloads.route(base,url))
    service.trash_item(ident,service.archive.get(ident)['updated'])
    with self.assertRaises(urllib.error.HTTPError):desktop_downloads.filename(base,base+files[0]['download_url'])
   finally:server.shutdown();server.server_close();service.close()
 def test_bounded_atomic_writes_and_partial_download_preserve_existing_file(self):
  with tempfile.TemporaryDirectory() as temp:
   target=Path(temp)/'clip.mp4';target.write_bytes(b'EXISTING');base='http://127.0.0.1:8768';url=base+'/api/items/'+'a'*32+'/file'
   class Source(io.BytesIO):
    status=200;headers={'Content-Length':'10'}
    def read(self,size=-1):
     if size<0 or size>1024*1024:raise AssertionError('Unbounded memory read')
     return super().read(size)
   class Open:
    def open(self,*args,**kwargs):return Source(b'short')
   with patch('secretary.desktop_downloads.opener',return_value=Open()):
    with self.assertRaisesRegex(ValueError,'不完整'):desktop_downloads.save(base,url,target)
   self.assertEqual(target.read_bytes(),b'EXISTING');self.assertFalse(list(Path(temp).glob('.stellar-download-*.part')))
   Source.headers={'Content-Length':'5'}
   with patch('secretary.desktop_downloads.opener',return_value=Open()):desktop_downloads.save(base,url,target)
   self.assertEqual(target.read_bytes(),b'short')
