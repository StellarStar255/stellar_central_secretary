"""Real browser: cover/resume, unsent editor navigation, large upload and local restore."""
import base64,os,sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False);service.archive.set_language('en')
 clip=(Path(__file__).resolve().parent.parent/'tests/fixtures/video.mp4').read_bytes()
 item=service.ingest({'text':'Recovery fixture','attachments':[{'name':'clip.mp4','data':base64.b64encode(clip).decode()}],'archive_only':True})['item'];ident=item['id']
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base)
    page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click()
    expect(page.locator('#preview-attachments .video-duration')).to_have_text('0:03',timeout=15000)
    expect(page.locator('#preview-attachments img')).to_have_attribute('src',__import__('re').compile('/video-poster$'))
    page.locator('#preview-attachments [data-video-src]').click();page.wait_for_function('()=>document.querySelector("#video-viewer video").duration>0')
    page.locator('#video-viewer video').evaluate('(v)=>{v.pause();v.currentTime=.6}')
    page.wait_for_function('()=>document.querySelector("#video-viewer video").currentTime>=.59');page.keyboard.press('Escape')
    page.locator('#preview-attachments [data-video-src]').click();page.wait_for_function('()=>document.querySelector("#video-viewer video").currentTime>=.59');page.keyboard.press('Escape')
    page.locator('#preview-full').click();page.locator('#edit-content').click();page.locator('#detail-edit').fill('Body automatically saved before closing')
    page.locator('#detail-dialog .dialog-head button').click();expect(page.locator('#detail-dialog')).not_to_be_visible();assert service.archive.get(ident)['text']=='Body automatically saved before closing'
    page.locator('#library-dialog .dialog-head button').click()
    large=Path(root)/'large.bin'
    with large.open('wb') as f:f.truncate(55*1024*1024);f.seek(-4,2);f.write(b'TAIL')
    page.locator('#archive-only').check();page.locator('#file-input').set_input_files(large)
    with page.expect_response(lambda response:response.url.endswith('/api/ingest'),timeout=30000) as ingestion:page.locator('#send-button').click()
    result=ingestion.value.json();assert ingestion.value.ok,result
    page.wait_for_function('()=>document.querySelector("#attachments").textContent.trim()===""',timeout=30000)
    page.wait_for_function('async()=>((await (await fetch("/api/items")).json()).length===2)',timeout=30000)
    assert len(service.archive.list())==2,[(v['title'],v['id']) for v in service.archive.list()]
    uploaded=next(record for record in service.archive.list() if record['id']!=ident)
    assert service.item_detail(uploaded['id'])['attachments'][0]['size']==55*1024*1024
    page.wait_for_function('()=>!sending',timeout=30000)
    assert not list(service.uploads.folder.iterdir()),'Completed upload staging was not removed'
    page.locator('#settings-open').click();page.locator('#backup-create').click();expect(page.locator('#backup-entries').get_by_role('button',name='Restore this backup',exact=True)).to_have_count(1,timeout=15000)
    service.archive.update(ident,title='Later change')
    page.once('dialog',lambda dialog:dialog.accept());
    with page.expect_response(lambda response:response.url.endswith('/api/backups/restore'),timeout=30000) as restoration:page.locator('#backup-entries').get_by_role('button',name='Restore this backup',exact=True).click()
    assert restoration.value.ok,restoration.value.status
    page.wait_for_load_state('load');page.wait_for_function('()=>document.querySelector("#model-label").textContent.includes("Codex")')
    assert service.archive.get(ident)['title']==item['title'];assert not errors,errors
    print('PASS: actual video cover/duration and resumed playback, body saved on close, 55 MB chunked UI upload, staging cleanup, disk snapshot and exact local restore')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
