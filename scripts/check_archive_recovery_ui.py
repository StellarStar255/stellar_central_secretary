"""Real-browser recovery for duplicate archives; isolated synthetic records only."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 text='周六上午11:00带测试对象去复查'
 live=service.ingest({'text':text,'archive_only':True})['item']
 resolved=live['user_context'].split('\n',2)[-1]
 service.archive.update(live['id'],state='ready',summary='【日期解析】\n'+resolved+'\n\n'+resolved.replace('11:00带','11:00，带')+'。')
 live=service.archive.get(live['id'])
 wrapper,_=service.archive.add('Deleted wrapper','建档：\n'+text)
 service.trash_item(wrapper,service.archive.get(wrapper)['updated'])
 only_text='建档：\n周六上午11:00测试对象复查 only-trash'
 saved=service.ingest({'text':only_text,'archive_only':True})['item'];service.trash_item(saved['id'],saved['updated'])
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as pw:
   executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
   browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
   try:
    page=browser.new_page(viewport={'width':1300,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#count')).to_have_text('1')
    page.locator('#message-input').fill('建档：\n'+text);page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(1)
    expect(page.locator('#messages .archive-card')).to_have_attribute('data-id',live['id'])
    assert page.locator('#messages .message.assistant .message-body').inner_text().count(resolved.split('（')[0])==1
    assert page.locator('#messages .archive-card p').inner_text().count(resolved.split('（')[0])==1
    page.screenshot(path='/tmp/stellar-date-summary-clean.png')
    assert len(service.archive.list())==1 and service.archive.get(wrapper,include_trashed=True)['trashed_at']
    page.locator('#message-input').fill('建档：\n我'+text);page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(2)
    expect(page.locator('#messages .archive-card').last).to_have_attribute('data-id',live['id'])
    body=page.locator('#messages .message.assistant .message-body').last
    assert body.inner_text().count(resolved.split('（')[0])==1
    expect(body).not_to_contain_text('我2026年')
    assert len(service.archive.list())==1
    page.locator('#message-input').fill(only_text)
    with page.expect_response(lambda response:response.url.endswith('/api/ingest')) as archived:page.locator('#send-button').click()
    assert archived.value.status==200 and archived.value.json()['created']
    fresh=archived.value.json()['item']['id']
    assert fresh!=saved['id']
    expect(page.locator('#messages .archive-card').last).to_have_attribute('data-id',fresh)
    expect(page.locator('[data-restore-duplicate]')).to_have_count(0)
    expect(page.locator('#message-input')).to_have_value('')
    assert service.archive.get(saved['id'],include_trashed=True)['trashed_at']
    assert len(service.archive.list())==2 and not errors,errors
    print('PASS: active equivalent reused; rearchiving from trash creates a new archive and leaves the old one recoverable')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
