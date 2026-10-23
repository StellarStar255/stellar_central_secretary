"""Validate display-language changes, data isolation and both tutorial languages."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 item,_=service.archive.add('知识库','这段原文叫模型与设置，必须保持原样。')
 service.archive.update(item,summary='保留这段中文摘要',tags=['中文标签'],state='ready')
 before=service.archive.export()
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base);page.locator('#message-input').fill('未发送的中文草稿');page.locator('#settings-open').click()
    page.locator('#auto-ai').check();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en')
    assert 'Models & settings' in page.locator('#settings-open').inner_text()
    assert page.locator('#auto-ai').is_checked(),'unsaved settings must survive language switching'
    assert page.locator('#message-input').input_value()=='未发送的中文草稿'
    assert page.locator('#tutorial-open').get_attribute('href')=='/tutorial?lang=en'
    assert page.locator('#settings-save').inner_text()=='Save settings'
    page.screenshot(path='/tmp/secretary-english-settings.png',full_page=True)
    page.locator('#settings-dialog .dialog-head button').click();assert page.locator('#chat-scroll').bounding_box()['height']>150;page.screenshot(path='/tmp/secretary-english-home.png');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    page.locator('#edit-title').wait_for();assert page.locator('#edit-title').inner_text().strip()=='知识库 ✎'
    assert page.get_by_role('heading',name='Summary',exact=True).count()==1
    assert '保留这段中文摘要' in page.locator('#detail-content .detail-text').first.inner_text()
    assert '这段原文叫模型与设置' in page.locator('#detail-content').inner_text()
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
    page.reload();expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-open').click();page.locator('#ui-language').select_option('zh');expect(page.locator('html')).to_have_attribute('lang','zh-CN')
    assert '模型与设置' in page.locator('#settings-open').inner_text()
    tutorial=browser.new_page(viewport={'width':1280,'height':1000});tutorial.goto(base+'/tutorial?lang=en')
    assert tutorial.locator('h1').inner_text()=='Learn by trying it yourself.'
    tutorial.locator('#import-sample').click();tutorial.locator('#next').click();tutorial.locator('#practice-search').fill('June Science Monthly');assert tutorial.locator('#search-results .result').count()==1
    tutorial.locator('#next').click();tutorial.locator('#practice-title').click();tutorial.locator('#practice-title-input').fill('My reading list');tutorial.locator('#practice-title-input').press('Enter')
    tutorial.locator('#next').click()
    with tutorial.expect_popup() as opened:tutorial.locator('#practice-open-pdf').click()
    pdf=opened.value;pdf.wait_for_load_state();pdf.close()
    tutorial.locator('#next').click();tutorial.locator('#settings').click();tutorial.locator('#practice-mode').click();assert tutorial.locator('#mode-badge').inner_text()=='Desktop practice'
    tutorial.locator('#next').click();tutorial.locator('#backup').click();assert tutorial.locator('#completion').inner_text()=='Completed 6 / 6'
    tutorial.screenshot(path='/tmp/secretary-english-tutorial.png',full_page=True)
    tutorial.locator('#tutorial-language').select_option('zh');assert tutorial.locator('#completion').inner_text()=='已完成 6 / 6'
    assert tutorial.evaluate('renamedTitle')=='My reading list'
    tutorial.locator('#tutorial-language').select_option('en');assert tutorial.locator('#completion').inner_text()=='Completed 6 / 6'
    tutorial.set_viewport_size({'width':390,'height':844});assert tutorial.evaluate('document.documentElement.scrollWidth<=innerWidth')
    offline=browser.new_page();offline.goto((ROOT/'docs/tutorial.html').as_uri()+'?lang=en');assert offline.locator('h1').inner_text()=='Learn by trying it yourself.'
    assert service.archive.export()==before,'display language must not alter archived content'
    assert service.archive.settings()['ui_language']=='zh','tutorial language must not change real app preference'
    assert not errors,errors
    print('PASS: live Chinese/English switching, saved preference, draft/unsaved-setting preservation, raw titles/text/summaries unchanged, English six-step tutorial, tutorial progress/name retention, offline English and mobile layout')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
