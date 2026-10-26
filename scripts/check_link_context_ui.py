"""Verify failed link reads retain the submitted annotation; synthetic data only."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.server.fetch_page',side_effect=OSError('Synthetic inaccessible page')),patch.object(service,'start_capture') as capture,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
    page.locator('#message-input').fill('模型量化测试机器链接：\nhttps://example.com/private-console')
    page.locator('#send-button').click();expect(page.locator('#messages')).to_contain_text('已按你提供的说明归档')
    item=service.archive.list()[0];assert item['title']=='模型量化测试机器链接' and not capture.called
    page.locator('#messages .archive-card').click();expect(page.locator('#link-context')).to_have_text('模型量化测试机器链接：')
    assert service.archive.retrieve('模型量化')[0]['item_id']==item['id']
    page.reload();page.locator('#recent-items [data-id="'+item['id']+'"]').click()
    expect(page.locator('#link-context')).to_have_text('模型量化测试机器链接：')
    assert not errors,errors
    print('PASS: annotation and link sent together; descriptive title, explicit unread-page reply, searchable context, detail and reload persistence; no browser or cloud call')
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close()
