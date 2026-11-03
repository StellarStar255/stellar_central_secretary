"""Real-browser library checks with isolated synthetic material and no model calls."""
import json,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from unittest.mock import patch
from secretary import ai
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as folder:
 service=Service(folder);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 linked,_=service.archive.add('Robot camera source','Original robot camera details',url=base+'/tutorial?lang=en#fixture')
 service.archive.update(linked,summary='【网页已加载内容归档】 仅包含已加载内容。\n\nUseful robot camera overview.',tags=['网页片段'],state='ready')
 for index in range(105):service.archive.add('Other record '+str(index),'Unique robot camera reference '+str(index))
 try:
  def fake_summary(item,*args,**kwargs):
   if item['title']=='Cancellable fixture':
    ai.report('waiting_model')
    for _ in range(250):
     ai.check_cancelled();threading.Event().wait(.02)
   return {'summary':'Synthetic retry result','state':'ready','error':''}
  with sync_playwright() as pw,patch.object(ai,'summary_fields',side_effect=fake_summary):
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
    task,_=service.archive.add('Cancellable fixture','Task original source remains available');service.queue(task,force=True)
    page.locator('#library-tasks').click();row=page.locator('[data-task-key="summary:'+task+'"]');expect(row).to_be_visible();row.get_by_role('button',name='停止这条任务').click();expect(row).to_contain_text('已停止',timeout=8000);assert service.archive.get(task)['text']=='Task original source remains available'
    failed,_=service.archive.add('Failed fixture','Failure original source');service.archive.update(failed,state='error',error='proxy connection refused')
    failed_row=page.locator('[data-task-key="summary:'+failed+'"]');expect(failed_row).to_contain_text('网络或代理连接未成功',timeout=5000);failed_row.get_by_role('button',name='重新尝试').click();expect(failed_row).to_contain_text('处理完成',timeout=8000);assert service.archive.get(failed)['summary']=='Synthetic retry result'
    page.screenshot(path='/tmp/secretary-tasks-workflow.png');page.evaluate("document.querySelector('#tasks-dialog').close()")
    assert not errors,errors
    print('PASS: compact scope badges, ranked/highlighted search, bounded pages, status filters, recent views, original-link double-click and single-click details')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
