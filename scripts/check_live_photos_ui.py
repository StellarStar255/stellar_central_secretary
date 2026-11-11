"""Decode and play a genuine MOV companion from the HEIC viewer, locally."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from secretary.server import Service,handler
from test_live_photos import photo_files,FIXTURES

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 item=service.ingest({'attachments':photo_files(False),'defer_summary':True})['item'];ident=item['id']
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'queue') as queue,sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ.get('CHROME_PATH') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'} if os.environ.get('CHROME_PATH') or sys.platform=='darwin' else {}))
   try:
    page=browser.new_page(viewport={'width':1200,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    base=f'http://127.0.0.1:{server.server_port}';page.goto(base);page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    page.locator('#detail-attachments [data-image-view]').click()
    expect(page.locator('.image-viewer-motion-hint')).to_contain_text('同名 MOV');expect(page.locator('[data-viewer="motion"]')).to_be_hidden()
    page.keyboard.press('Escape');expect(page.locator('#detail-dialog')).to_be_visible()
    service.append_material(ident,{'attachments':photo_files()[1:],'expected_updated':service.archive.get(ident)['updated'],'summarize':False})
    page.locator('#detail-attachments [data-image-view]').click()
    expect(page.locator('[data-viewer="motion"]')).to_be_visible();expect(page.locator('.image-viewer-motion-hint')).to_contain_text('已找到同名 MOV')
    # The companion is found at opening time even before the underlying detail re-renders.
    page.locator('[data-viewer="motion"]').click();expect(page.locator('#video-viewer')).to_be_visible()
    page.wait_for_function('()=>{const v=document.querySelector("#video-viewer video");return v.videoWidth>0&&v.currentTime>.1&&!v.paused}')
    page.evaluate('document.querySelector("#video-viewer video").pause()');assert page.locator('#video-viewer video').evaluate('v=>v.paused')
    page.evaluate('document.querySelector("#video-viewer video").play()');page.wait_for_function('()=>!document.querySelector("#video-viewer video").paused')
    assert page.evaluate('StellarCloseTopLayer()');expect(page.locator('#video-viewer')).not_to_be_visible();expect(page.locator('#image-viewer')).to_be_visible()
    page.wait_for_function('()=>document.querySelector("#video-viewer video").paused&&!document.querySelector("#video-viewer video").getAttribute("src")')
    assert page.evaluate('StellarCloseTopLayer()');expect(page.locator('#detail-dialog')).to_be_visible()
    files=service.item_detail(ident)['all_attachments'];photo,video=files
    for file,fixture in ((photo,'synthetic.heic'),(video,'live-photo.mov')):assert page.request.get(base+file['download_url']).body()==(FIXTURES/fixture).read_bytes()
    response=page.request.get(base+video['preview_url'],headers={'Range':'bytes=0-63'});assert response.status==206 and len(response.body())==64
    # Opening from chat and quick previews uses the same metadata lookup.
    page.evaluate('(src)=>StellarImageViewer.open([{src,name:"IMG_1.HEIC"}])',photo['preview_url']);expect(page.locator('[data-viewer="motion"]')).to_be_visible();page.keyboard.press('Escape')
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-dialog .dialog-head button').click()
    page.evaluate('(src)=>StellarImageViewer.open([{src,name:"IMG_1.HEIC"}])',photo['preview_url']);expect(page.locator('[data-viewer="motion"]')).to_have_attribute('aria-label','Play Live Photo')
    expect(page.locator('.image-viewer-motion-hint')).to_contain_text('Matching MOV found')
    page.screenshot(path='/tmp/stellar-live-photo-viewer.png');assert not errors,errors;queue.assert_not_called()
    print('PASS: static-only hint, late MOV append, actual decoded motion and pause/resume, close stops video and preserves photo/details, exact originals, byte ranges, chat entry and bilingual labels; no model calls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
