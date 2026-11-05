"""Actual H.264 playback/seek and title click-away save with failure/cancel handling."""
import base64,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False);service.archive.set_language('en')
    clip=(Path(__file__).resolve().parent.parent/'tests/fixtures/video.mp4').read_bytes()
    item=service.ingest({'text':'Synthetic video fixture','attachments':[{'name':'clip.mp4','data':base64.b64encode(clip).decode()}],'archive_only':True})['item'];ident=item['id']
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
                page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click()
                page.locator('#preview-attachments [data-video-src]').click();expect(page.locator('#video-viewer')).to_be_visible()
                page.wait_for_function('()=>{const v=document.querySelector("#video-viewer video");return v.duration>0&&v.currentTime>.1&&!v.paused}',timeout=15000)
                page.locator('#video-viewer video').evaluate('(video)=>{video.pause();video.currentTime=2}')
                page.wait_for_function('()=>document.querySelector("#video-viewer video").currentTime>=1.9')
                assert len(page.context.pages)==1,'Video opened an external tab'
                page.keyboard.press('Escape');expect(page.locator('#video-viewer')).not_to_be_visible()
                page.wait_for_function('()=>{const video=document.querySelector("#video-viewer video");return video.paused&&!video.hasAttribute("src")}')
                page.locator('#preview-title').dblclick();page.locator('#preview-title-input').fill('Preview click-away title')
                page.locator('#preview-summary-heading').click();expect(page.locator('#preview-title-editor')).to_be_hidden()
                assert service.archive.get(ident)['title']=='Preview click-away title'
                page.locator('#preview-full').click();page.locator('#edit-title').click();page.locator('#rename-title').fill('Detail click-away title')
                page.locator('#detail-attachments h3').click();expect(page.locator('#title-editor')).to_be_hidden()
                assert service.archive.get(ident)['title']=='Detail click-away title'
                page.locator('#edit-title').click();page.locator('#rename-title').fill('Canceled title');page.locator('#cancel-title').click()
                assert service.archive.get(ident)['title']=='Detail click-away title'
                page.locator('#edit-title').click();page.locator('#rename-title').fill('Escaped title');page.keyboard.press('Escape')
                assert service.archive.get(ident)['title']=='Detail click-away title'
                page.locator('#edit-title').click();page.locator('#rename-title').fill('Retry click-away title')
                page.route('**/api/items/'+ident+'/title',lambda route:route.fulfill(status=500,json={'error':'Synthetic save failure'}))
                page.locator('#detail-attachments h3').click();expect(page.locator('#toast')).to_contain_text('Synthetic save failure')
                expect(page.locator('#rename-title')).to_have_value('Retry click-away title');expect(page.locator('#rename-title')).to_be_enabled()
                page.unroute('**/api/items/'+ident+'/title');page.locator('#detail-attachments h3').click();expect(page.locator('#title-editor')).to_be_hidden()
                assert service.archive.get(ident)['title']=='Retry click-away title'
                assert not errors,errors
                print('PASS: real in-app H.264 playback/seek/close, no external tabs, preview/detail click-away title save, explicit Cancel/Escape, failed draft retained and retry saved')
            finally:browser.close()
    finally:server.shutdown();server.server_close();service.close()
