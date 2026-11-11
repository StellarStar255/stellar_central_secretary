"""Real HEIC thumbnails/viewer for legacy and newly uploaded local originals."""
import base64,io,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from secretary.server import Service,handler
from test_heic import legacy_bundle,FIXTURE

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 data,text=legacy_bundle();ident,_=service.archive.add('Legacy HEIC',text,filename='materials.stellar.zip',data=data)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'queue') as queue,sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ.get('CHROME_PATH') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'} if os.environ.get('CHROME_PATH') or sys.platform=='darwin' else {}))
   try:
    page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    base=f'http://127.0.0.1:{server.server_port}';page.goto(base)
    page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    thumb=page.locator('#detail-attachments [data-image-view] img');expect(thumb).to_have_count(1)
    page.wait_for_function('()=>document.querySelector("#detail-attachments [data-image-view] img").naturalHeight===96')
    page.locator('#detail-attachments [data-image-view]').click();expect(page.locator('#image-viewer')).to_be_visible()
    page.wait_for_function('()=>document.querySelector("#image-viewer img").naturalHeight===96')
    page.locator('[data-viewer="in"]').click();expect(page.locator('[data-viewer="zoom"]')).to_have_text('125%')
    page.keyboard.press('Escape');expect(page.locator('#detail-dialog')).to_be_visible()
    file=service.item_detail(ident)['all_attachments'][0]
    for suffix,media in (('/preview','image/jpeg'),('/thumbnail','image/png')):
     response=page.request.get(base+file['path']+suffix);assert response.ok and response.headers['content-type'].startswith(media)
     with Image.open(io.BytesIO(response.body())) as image:assert image.size==(64,96)
    assert page.request.get(base+file['download_url']).body()==FIXTURE.read_bytes()
    fresh=service.ingest({'attachments':[{'name':'new.heif','data':base64.b64encode(FIXTURE.read_bytes()).decode()}],'defer_summary':True})['item']
    assert fresh['all_attachments'][0]['media']=='image/heic'
    assert page.request.get(base+fresh['all_attachments'][0]['preview_url']).ok
    assert (service.archive.root/'files'/ident).read_bytes()==data
    assert not errors,errors;queue.assert_not_called()
    print('PASS: real HEIC decoding, legacy/new metadata, thumbnail and full viewer, zoom/Escape, compatible JPEG preview, exact original download, zero model calls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
