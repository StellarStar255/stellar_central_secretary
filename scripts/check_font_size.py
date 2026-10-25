"""Real GUI font-size preview, persistence, rollback and layout check."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 item,_=service.archive.add('Synthetic reading record','Original source remains unchanged. '*10)
 service.archive.update(item,summary='Saved summary',state='ready')
 before=service.archive.get(item)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    assert page.locator('body').evaluate('e=>getComputedStyle(e).fontSize')=='14px'
    page.locator('#message-input').fill('Unsent draft is kept while resizing')
    page.locator('#settings-open').click();size=page.locator('#ui-font-size');size.focus();size.press('End')
    expect(page.locator('#ui-font-size-value')).to_have_text('24 px');expect(page.locator('#toast')).to_have_text('字号已保存')
    assert service.archive.settings()['ui_font_size']==24
    assert page.locator('body').evaluate('e=>getComputedStyle(e).fontSize')=='24px'
    assert float(page.locator('#message-input').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>24
    assert page.locator('#message-input').input_value()=='Unsent draft is kept while resizing'
    page.screenshot(path='/tmp/secretary-font-size-24.png')
    page.reload();page.locator('#settings-open').click();expect(page.locator('#ui-font-size')).to_have_value('24')
    page.locator('#ui-language').select_option('en');expect(page.get_by_text('Interface font size',exact=True)).to_be_visible()
    page.locator('#ui-font-size-reset').click();expect(page.locator('#toast')).to_have_text('Font size saved')
    assert service.archive.settings()['ui_font_size']==14
    page.route('**/api/appearance',lambda route:route.fulfill(status=500,content_type='application/json',body='{"error":"Synthetic save failure"}'))
    size.focus();size.press('End');expect(page.locator('#toast')).to_have_text('Synthetic save failure')
    expect(size).to_have_value('14');assert page.locator('body').evaluate('e=>getComputedStyle(e).fontSize')=='14px'
    page.unroute('**/api/appearance')
    size.focus();size.press('End');expect(page.locator('#toast')).to_have_text('Font size saved')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'large font must not overflow the mobile viewport'
    page.screenshot(path='/tmp/secretary-font-size-mobile.png')
    page.locator('#ui-font-size-reset').click();expect(page.locator('#ui-font-size-value')).to_have_text('14 px')
    assert service.archive.get(item)==before,'font settings must not change source, title, summary or notes'
    assert not errors,errors
    print('PASS: GUI preview to 24 px; text scaling without page zoom; persisted reload; reset; bilingual labels; save-failure rollback; mobile viewport; unsent draft and archived content preserved')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
