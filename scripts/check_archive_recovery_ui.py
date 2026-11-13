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
    page.locator('#message-input').fill(only_text)
    with page.expect_response(lambda response:response.url.endswith('/api/ingest')) as conflict:page.locator('#send-button').click()
    assert conflict.value.status==409 and conflict.value.json()['trashed_duplicate']['id']==saved['id']
    expect(page.locator('[data-restore-duplicate]')).to_have_count(1)
    expect(page.locator('#messages .message.assistant').last).not_to_have_class('error')
    expect(page.locator('#message-input')).to_have_value(only_text)
    assert service.archive.get(saved['id'],include_trashed=True)['trashed_at']
    page.screenshot(path='/tmp/stellar-archive-recovery.png');page.reload()
    expect(page.locator('[data-restore-duplicate]')).to_have_count(1)
    page.locator('[data-restore-duplicate]').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('已恢复原归档，保留原建档时间。')
    expect(page.locator('[data-restore-duplicate]')).to_have_count(0)
    assert service.archive.get(saved['id'])==saved and len(service.archive.list())==2
    assert not errors,errors
    print('PASS: live equivalent reused; trashed duplicate yields a durable restore action and preserves input; explicit restore keeps original ID, date and content; unrelated trash stays deleted')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
