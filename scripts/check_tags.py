"""Verify tag editing, polling, search and bilingual UI with isolated data."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 item,_=service.archive.add('Fixture document','Original document body stays unchanged.')
 service.archive.update(item,tags=['AI tag','Remove me'],state='processing');service.busy.add(item)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'queue') as queue,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1100,'height':850});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    expect(page.locator('#add-tag')).to_have_text('＋ 添加标签');page.locator('#add-tag').click();page.locator('#tag-input').fill('私人 分类')
    service.archive.update(item,summary='Background progress')
    page.evaluate('refresh()');expect(page.locator('#tag-input')).to_have_value('私人 分类')
    page.locator('#tag-input').press('Enter');expect(page.locator('.editable-tags .tag')).to_have_count(3)
    page.get_by_role('button',name='删除标签：Remove me',exact=True).click();expect(page.locator('.editable-tags .tag')).to_have_count(2)
    service.archive.update(item,tags=['AI replacement'],summary='Finished summary',state='ready');service.busy.clear()
    page.reload();page.locator('#library-open').click();page.locator('#search').fill('私人 Fixture')
    expect(page.locator('#items .library-row')).to_have_count(1)
    page.locator('#items [data-id="'+item+'"]').click();expect(page.locator('.editable-tags .tag')).to_have_count(2)
    assert service.archive.get(item)['tags']==['AI tag','私人 分类'];assert service.archive.retrieve('私人')[0]['item_id']==item
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-dialog .dialog-head button').click()
    page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click();expect(page.locator('#add-tag')).to_have_text('+ Add tag')
    page.locator('#add-tag').click();page.locator('#tag-input').fill('<img src=x onerror=alert(1)>');page.locator('#tag-input').press('Enter');expect(page.locator('.editable-tags .tag')).to_have_count(3)
    assert page.locator('.editable-tags img').count()==0
    page.get_by_role('button',name='Remove tag: <img src=x onerror=alert(1)>',exact=True).click();expect(page.locator('.editable-tags .tag')).to_have_count(2)
    page.screenshot(path='/tmp/secretary-custom-tags-en.png');assert not errors,errors;queue.assert_not_called()
    assert service.archive.get(item)['text']=='Original document body stays unchanged.'
    print('PASS: Chinese/English tag add/remove, edits during AI processing, polling preserves draft, reload persistence, unordered keyword search, question retrieval, escaped HTML labels, zero AI calls and original body unchanged')
   finally:browser.close()
 finally:
  service.busy.clear();server.shutdown();server.server_close();service.close()
