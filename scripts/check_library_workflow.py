"""Real-browser library checks with isolated synthetic material and no model calls."""
import json,os,sys,tempfile,threading
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
 created_fixture='2025-01-02T03:04:05+00:00';updated_fixture='2026-02-03T04:05:06+00:00'
 with service.archive.db() as db:db.execute('UPDATE items SET created=?,updated=? WHERE id=?',(created_fixture,updated_fixture,linked))
 for index in range(105):service.archive.add('Other record '+str(index),'Unique robot camera reference '+str(index))
 try:
  def fake_summary(item,*args,**kwargs):
   if item['title']=='Cancellable fixture':
    ai.report('waiting_model')
    for _ in range(250):
     ai.check_cancelled();threading.Event().wait(.02)
   return {'summary':'Synthetic retry result','state':'ready','error':''}
  with sync_playwright() as pw,patch.object(ai,'summary_fields',side_effect=fake_summary):
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    page=browser.new_page(viewport={'width':1440,'height':1000},timezone_id='Asia/Shanghai');errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base);expect(page.locator('#count')).to_have_text('106');page.locator('#library-open').click()
    for shortcut in ('Meta+k','Control+k'):
     page.keyboard.press(shortcut);expect(page.locator('#library-dialog')).not_to_be_visible()
     page.keyboard.press(shortcut);expect(page.locator('#library-dialog')).to_be_visible();expect(page.locator('#search')).to_be_focused()
    page.locator('#search').evaluate("node=>node.dispatchEvent(new KeyboardEvent('keydown',{key:'k',metaKey:true,repeat:true,bubbles:true,cancelable:true}))")
    expect(page.locator('#library-dialog')).to_be_visible()
    expect(page.locator('#items .library-row')).to_have_count(100);expect(page.locator('#library-next')).to_be_enabled();page.locator('#library-next').click();expect(page.locator('#items .library-row')).to_have_count(6)
    page.locator('#search').fill('robot camera');expect(page.locator('#items .library-row').first).to_have_attribute('data-id',linked);expect(page.locator('#items .library-row').first.locator('mark')).to_have_count(4)
    expect(page.locator('#items .library-row').first.locator('p')).not_to_contain_text('网页已加载');expect(page.locator('#items .library-row').first.locator('.coverage-badge')).to_have_text('部分内容')
    row=page.locator('#items .library-row').first
    with page.expect_popup() as opened:row.dblclick(delay=60)
    popup=opened.value;popup.wait_for_load_state();assert popup.url==base+'/tutorial?lang=en#fixture';popup.close();expect(page.locator('#detail-dialog')).not_to_be_visible()
    row.click();expect(page.locator('#preview-title')).to_have_text('Robot camera source')
    expect(page.locator('#preview-timestamps [data-record-created]')).to_have_text('2025-01-02 11:04:05')
    expect(page.locator('#preview-timestamps [data-record-created]')).to_have_attribute('datetime',created_fixture)
    expect(page.locator('#preview-timestamps [data-record-created]')).to_have_attribute('title','本地时间 · UTC+08:00')
    expect(page.locator('#preview-timestamps [data-record-updated]')).to_have_text('2026-02-03 12:05:06')
    assert 'Invalid Date' not in page.evaluate('()=>StellarLibraryPreview.timestamps({created:"invalid",updated:""})')
    page.screenshot(path='/tmp/stellar-preview-timestamps.png')
    page.locator('#preview-source').dblclick();expect(page.locator('#detail-dialog')).to_be_visible();expect(page.locator('#library-dialog')).to_be_visible()
    expect(page.locator('#edit-title')).to_contain_text('Robot camera source');page.locator('#detail-dialog .dialog-head button').click()
    page.locator('#preview-summary').dblclick();expect(page.locator('#detail-dialog')).to_be_visible();page.locator('#detail-dialog .dialog-head button').click()
    before_rename=service.archive.get(linked)
    page.locator('#preview-title').dblclick();expect(page.locator('#preview-title-input')).to_have_value('Robot camera source');expect(page.locator('#detail-dialog')).not_to_be_visible()
    page.locator('#preview-title-input').fill('Uncommitted draft');page.evaluate('refresh()');expect(page.locator('#preview-title-input')).to_have_value('Uncommitted draft')
    page.locator('#preview-title-input').press('Escape');expect(page.locator('#preview-title')).to_have_text('Robot camera source');expect(page.locator('#library-dialog')).to_be_visible();expect(page.locator('#preview-material')).to_be_visible()
    page.locator('#preview-title').press('Enter');page.locator('#preview-title-input').fill('   ');page.locator('#preview-title-input').press('Enter');expect(page.locator('#preview-title-error')).to_have_text('标题不能为空')
    page.locator('#preview-title-input').fill('Robot camera 新标题 <draft>');page.keyboard.press('Meta+k');expect(page.locator('#library-dialog')).not_to_be_visible()
    page.keyboard.press('Meta+k');expect(page.locator('#library-dialog')).to_be_visible();expect(page.locator('#search')).to_have_value('robot camera')
    expect(page.locator('#preview-title')).to_have_text('Robot camera 新标题 <draft>');expect(page.locator('#items .library-row').first).to_contain_text('Robot camera 新标题 <draft>')
    after_rename=service.archive.get(linked);assert after_rename['title']=='Robot camera 新标题 <draft>'
    for key in ('created','text','summary','tags','state','filename','url'):assert after_rename[key]==before_rename[key],key
    expect(page.locator('#preview-timestamps [data-record-created]')).to_have_attribute('datetime',created_fixture)
    expect(page.locator('#preview-timestamps [data-record-updated]')).to_have_attribute('datetime',after_rename['updated'])
    page.locator('#preview-title').dblclick();page.locator('#preview-title-input').fill('Robot camera saved via double click')
    page.locator('#preview-source').dblclick();expect(page.locator('#detail-dialog')).to_be_visible()
    assert service.archive.get(linked)['title']=='Robot camera saved via double click'
    expect(page.locator('#edit-title')).to_contain_text('Robot camera saved via double click');page.locator('#detail-dialog .dialog-head button').click()
    # Restore the fixture title for subsequent persistence checks.
    page.locator('#preview-title').dblclick();page.locator('#preview-title-input').fill('Robot camera 新标题 <draft>');page.locator('#preview-title-save').click();expect(page.locator('#preview-title')).to_have_text('Robot camera 新标题 <draft>')
    page.reload();page.locator('#library-open').click();page.locator('#search').fill('robot camera');page.locator('#items [data-id="'+linked+'"]').click();expect(page.locator('#preview-title')).to_have_text('Robot camera 新标题 <draft>')
    page.locator('#preview-title').dblclick();page.locator('#preview-title-input').fill('Robot camera source');page.locator('#preview-title-save').click();expect(page.locator('#preview-title')).to_have_text('Robot camera source');expect(page.locator('#items .library-row').first).to_contain_text('Robot camera source')
    row.click();expect(page.locator('#preview-title')).to_have_text('Robot camera source');expect(page.locator('#detail-dialog')).not_to_be_visible();page.locator('#preview-full').click();expect(page.locator('#detail-dialog')).to_be_visible();page.evaluate("document.querySelector('#detail-dialog').close()")
    page.locator('#sort-filter').select_option('viewed');expect(page.locator('#items .library-row').first).to_have_attribute('data-id',linked)
    page.locator('#preview-close').click();page.locator('#search').focus();page.locator('#search').press('ArrowDown');expect(page.locator('#preview-title')).to_have_text('Robot camera source');expect(page.locator('#detail-dialog')).not_to_be_visible()
    page.locator('#items .library-row').first.press('ArrowDown');expect(page.locator('#preview-title')).not_to_have_text('Robot camera source');page.locator('#items .library-row[aria-pressed="true"]').press('Enter');expect(page.locator('#preview-material')).to_be_visible()
    page.keyboard.press('Escape');expect(page.locator('#preview-empty')).to_be_visible();expect(page.locator('#library-dialog')).to_be_visible()
    page.locator('#state-filter').select_option('ready');expect(page.locator('#items .library-row')).to_have_count(1);page.locator('#items .library-row').click();expect(page.locator('#preview-title')).to_have_text('Robot camera source')
    with page.expect_popup() as keyboard_opened:page.locator('#items .library-row').press('Control+Enter')
    keyboard_popup=keyboard_opened.value;keyboard_popup.wait_for_load_state();assert keyboard_popup.url==base+'/tutorial?lang=en#fixture';keyboard_popup.close()
    flag=page.locator('[data-result-id="'+linked+'"] [data-flag="favorite"]');flag.click();expect(flag).to_have_attribute('aria-pressed','true')
    page.locator('[data-result-id="'+linked+'"] [data-flag="pinned"]').click();page.locator('#favorite-filter').select_option('1');expect(page.locator('#items .library-row')).to_have_count(1)
    page.locator('#preview-trash').click();page.locator('#delete-archive-confirm').click();expect(page.locator('#items .library-row')).to_have_count(0);expect(page.locator('#toast button')).to_have_text('撤销');page.locator('#toast button').click();expect(page.locator('#items .library-row')).to_have_count(1)
    page.locator('#items .library-row').click();page.locator('#preview-trash').click();page.locator('#delete-archive-confirm').click();expect(page.locator('#items .library-row')).to_have_count(0)
    page.locator('#library-trash').click();expect(page.locator('.trash-row')).to_have_count(1);page.locator('.trash-row').get_by_role('button',name='恢复',exact=True).click();expect(page.locator('.trash-row')).to_have_count(0);page.locator('#trash-dialog .dialog-head button').click();expect(page.locator('#items .library-row')).to_have_count(1)
    disposable,_=service.archive.add('Purge fixture','Purge only this synthetic original');service.trash_item(disposable,service.archive.get(disposable)['updated'])
    page.locator('#library-trash').click();page.locator('.trash-row').get_by_role('button',name='永久删除…',exact=True).click();page.locator('#purge-cancel').click();expect(page.locator('.trash-row')).to_have_count(1);page.locator('.trash-row').get_by_role('button',name='永久删除…',exact=True).click();page.locator('#purge-confirm').click();expect(page.locator('.trash-row')).to_have_count(0);assert disposable in service.archive.deletion_refs()['deletedItemIds'];page.locator('#trash-dialog .dialog-head button').click()
    page.locator('#favorite-filter').select_option('');
    page.locator('#items .library-row').click();expect(page.locator('#preview-material')).to_be_visible();page.screenshot(path='/tmp/secretary-library-workflow.png')
    task,_=service.archive.add('Cancellable fixture','Task original source remains available');service.queue(task,force=True)
    page.locator('#library-tasks').click();row=page.locator('[data-task-key="summary:'+task+'"]');expect(row).to_be_visible();row.get_by_role('button',name='停止这条任务').click();expect(row).to_contain_text('已停止',timeout=8000);assert service.archive.get(task)['text']=='Task original source remains available'
    failed,_=service.archive.add('Failed fixture','Failure original source');service.archive.update(failed,state='error',error='proxy connection refused')
    failed_row=page.locator('[data-task-key="summary:'+failed+'"]');expect(failed_row).to_contain_text('网络或代理连接未成功',timeout=5000);failed_row.get_by_role('button',name='重新尝试').click();expect(failed_row).to_contain_text('处理完成',timeout=8000);assert service.archive.get(failed)['summary']=='Synthetic retry result'
    page.screenshot(path='/tmp/secretary-tasks-workflow.png');page.evaluate("document.querySelector('#tasks-dialog').close()")
    page.locator('#library-dialog').evaluate('node=>node.close()');page.locator('#settings-open').click();page.locator('#ui-language').select_option('en')
    expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-dialog .dialog-head button').click()
    page.locator('#library-open').click();page.locator('#search').fill('robot camera');page.locator('#items [data-id="'+linked+'"]').click()
    expect(page.locator('#preview-timestamps')).to_contain_text('Archived at')
    expect(page.locator('#preview-timestamps [data-record-created]')).to_have_text('2025-01-02 11:04:05')
    print('PASS: preview shows full archive timestamp and independent updated timestamp in local timezone; rename preserves archive time, refreshes updated time, and English labels work')
    assert not errors,errors
    print('PASS: compact scope badges, inline preview title edit, Enter save, Esc cancel, refresh preserves draft, persisted rename without source changes, ranked/highlighted search, bounded pages, status filters, recent views, original-link double-click and single-click details')
   except Exception:
    print({'page_errors':errors,'toast':page.locator('#toast').inner_text(),'html':page.locator('#result-count').inner_text()},flush=True);raise
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
