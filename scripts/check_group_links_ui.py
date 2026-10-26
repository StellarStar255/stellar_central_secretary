"""Same-message URLs and appended URLs remain one archive; synthetic sources only."""
import json,os,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright,expect
from secretary import ai
from secretary.server import Service,handler

def fetch(url):
 if url.endswith('/one'):return 'Synthetic source ONE about related research.',''
 raise OSError('Synthetic login-only page')
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.server.fetch_page',side_effect=fetch),patch.object(ai,'run',return_value=json.dumps({'summary':'Combined source summary','tags':[],'answer':'Answer based on the readable source. [1]'})) as model,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
    page.locator('#message-input').fill('请比较这些相关资料：\nhttps://example.com/one\nhttps://example.com/two')
    page.locator('#send-button').click();expect(page.locator('#messages')).to_contain_text('Answer based on the readable source.',timeout=15000)
    assert len(service.archive.list())==1 and model.call_count==1
    item=service.archive.list()[0];page.locator('#messages .archive-card').click()
    expect(page.locator('.group-link')).to_have_count(2);expect(page.locator('.group-links')).to_contain_text('未读取正文')
    expect(page.locator('.group-links')).to_contain_text('已读取')
    page.locator('#read-group-links').click();expect(page.locator('#append-material')).to_be_enabled(timeout=15000)
    assert model.call_count==1,'Re-reading links must respect disabled automatic AI'
    page.screenshot(path='/tmp/secretary-grouped-links.png')
    page.locator('#append-material').click();page.locator('#append-text').fill('更多同主题来源\nhttps://example.com/one\nhttps://example.com/three')
    page.locator('#append-summarize').check();page.locator('#append-save').click()
    expect(page.locator('#append-dialog')).not_to_be_visible();expect(page.locator('.addition-batch .group-link')).to_have_count(2,timeout=15000)
    deadline=time.monotonic()+5
    while service.runtime()['processing'] and time.monotonic()<deadline:time.sleep(.01)
    assert model.call_count==2 and len(service.archive.list())==1
    assert len(service.archive.get(item['id'])['additions'][0]['links'])==2
    page.reload();page.locator('#recent-items [data-id="'+item['id']+'"]').click();expect(page.locator('.group-link')).to_have_count(4)
    page.locator('#detail-dialog .dialog-head button').click()
    page.locator('#message-input').fill('Related references\nhttps://example.com/one?tab=info\nhttps://example.com/two?tab=overview')
    page.locator('#send-button').click();expect(page.locator('#messages .archive-card')).to_have_count(2)
    deadline=time.monotonic()+5
    while service.runtime()['processing'] and time.monotonic()<deadline:time.sleep(.01)
    assert model.call_count==2 and len(service.archive.list())==2,'URL query markers must not trigger a model question'
    assert not errors,errors
    print('PASS: two links in one message become one archive by default; read/unread states explicit; one scoped question; two appended URLs join same archive and generate one supplemental summary; reload retains all four sources; no live network or model call')
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close()
