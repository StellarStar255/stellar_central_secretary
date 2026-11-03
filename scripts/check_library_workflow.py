"""Real-browser library checks with isolated synthetic material and no model calls."""
import json,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as folder:
 service=Service(folder);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 linked,_=service.archive.add('Robot camera source','Original robot camera details',url=base+'/tutorial?lang=en#fixture')
 service.archive.update(linked,summary='【网页已加载内容归档】 仅包含已加载内容。\n\nUseful robot camera overview.',tags=['网页片段'],state='ready')
 for index in range(105):service.archive.add('Other record '+str(index),'Unique robot camera reference '+str(index))
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   try:
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base);page.locator('#library-open').click()
    expect(page.locator('#items .library-row')).to_have_count(100);expect(page.locator('#library-next')).to_be_enabled();page.locator('#library-next').click();expect(page.locator('#items .library-row')).to_have_count(6)
    page.locator('#search').fill('robot camera');expect(page.locator('#items .library-row').first).to_have_attribute('data-id',linked);expect(page.locator('#items .library-row').first.locator('mark')).to_have_count(4)
    expect(page.locator('#items .library-row').first.locator('p')).not_to_contain_text('网页已加载');expect(page.locator('#items .library-row').first.locator('.coverage-badge')).to_have_text('部分内容')
    row=page.locator('#items .library-row').first
    with page.expect_popup() as opened:row.dblclick(delay=60)
    popup=opened.value;popup.wait_for_load_state();assert popup.url==base+'/tutorial?lang=en#fixture';popup.close();expect(page.locator('#detail-dialog')).not_to_be_visible()
    row.click();expect(page.locator('#detail-dialog')).to_be_visible();page.evaluate("document.querySelector('#detail-dialog').close()")
    page.locator('#sort-filter').select_option('viewed');expect(page.locator('#items .library-row').first).to_have_attribute('data-id',linked)
    page.locator('#state-filter').select_option('ready');expect(page.locator('#items .library-row')).to_have_count(1);page.screenshot(path='/tmp/secretary-library-workflow.png')
    assert not errors,errors
    print('PASS: compact scope badges, ranked/highlighted search, bounded pages, status filters, recent views, original-link double-click and single-click details')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
