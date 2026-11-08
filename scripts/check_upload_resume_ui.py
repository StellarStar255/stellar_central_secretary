"""Pause/reload/resume verified chunks and cancel using a real browser and isolated files."""
import os,sys,tempfile,threading,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as temp:
 source=Path(temp)/'resume.bin'
 with source.open('wb') as stream:stream.truncate(20*1024*1024);stream.seek(-4,2);stream.write(b'TAIL')
 service=Service(Path(temp)/'data');service.archive.configure('codex',False)
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1300,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base);held=[];offsets=[]
    def hold(route):
     offset=int(route.request.headers.get('x-upload-offset','0'));offsets.append(offset)
     if offset==4*1024*1024 and not held:held.append(route)
     else:route.continue_()
    page.route('**/api/uploads/*/chunk',hold);page.locator('#archive-only').check();page.locator('#file-input').set_input_files(source);page.locator('#send-button').click()
    expect(page.locator('.upload-progress-row span')).to_contain_text('20%');row=page.locator('.upload-progress-row');row.locator('button').nth(0).click();expect(row.locator('span')).to_contain_text('已暂停')
    for route in held:
     try:route.abort()
     except Exception:pass
    meta=json.loads(next(service.uploads.folder.glob('*.json')).read_text());assert meta['offset']==4*1024*1024
    page.once('dialog',lambda dialog:dialog.accept());page.reload();page.unroute('**/api/uploads/*/chunk',hold)
    resumed=[];page.on('request',lambda request:resumed.append(int(request.headers.get('x-upload-offset','-1'))) if request.url.endswith('/chunk') else None)
    page.locator('#archive-only').check();page.locator('#file-input').set_input_files(source)
    with page.expect_response(lambda response:response.url.endswith('/api/ingest'),timeout=30000) as saved:page.locator('#send-button').click()
    result=saved.value.json();assert saved.value.ok,result;assert resumed and min(resumed)==4*1024*1024,resumed
    page.wait_for_function('()=>!sending');assert len(service.archive.list())==1 and not list(service.uploads.folder.glob('*.json'))
    preview=result['item']['all_attachments'][0]['preview_url'];response=page.request.get(base+preview.removesuffix('/preview'),headers={'Range':'bytes=-4'});assert response.status==206 and response.body()==b'TAIL'
    cancel_source=Path(temp)/'cancel.bin';cancel_source.write_bytes(source.read_bytes());blocked=[]
    starts=[]
    def hold_start(route):starts.append(route)
    page.route('**/api/uploads/start',hold_start);page.locator('#file-input').set_input_files(cancel_source)
    with page.expect_request('**/api/uploads/start'):page.locator('#send-button').click()
    expect(page.locator('.upload-progress-row')).to_have_count(1);page.locator('.upload-progress-row button').nth(1).click()
    for route in starts:route.continue_()
    expect(page.locator('#attachments')).to_contain_text('cancel.bin');page.wait_for_function('()=>!sending');assert len(service.archive.list())==1
    page.unroute('**/api/uploads/start',hold_start);page.locator('.upload-progress-row button').nth(1).click()
    page.route('**/api/uploads/*/chunk',lambda route:blocked.append(route))
    with page.expect_request(re.compile(r'/api/uploads/[^/]+/chunk$')):page.locator('#send-button').click()
    expect(page.locator('.upload-progress-row')).to_have_count(1)
    page.locator('.upload-progress-row button').nth(1).click();expect(page.locator('#attachments')).to_contain_text('cancel.bin');assert len(service.archive.list())==1
    for route in blocked:
     try:route.abort()
     except Exception:pass
    assert not errors,errors
    print('PASS: pause after first 4 MB, reload/reselect resumes at verified offset, no first-chunk retransmission, original tail intact, per-upload cleanup, cancellation keeps original input and creates no archive')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
