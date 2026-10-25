"""Real keyboard shortcuts must resize content, never browser chrome or controls."""
import os,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 item,_=service.archive.add('Synthetic record','Original saved body. '*30)
 service.archive.update(item,summary='Synthetic saved summary.',state='ready');before=service.archive.get(item)
 service.chat_history({'conversations':[{'id':'example','title':'Synthetic conversation','updated':1,'messages':[{'id':'message','role':'assistant','text':'Synthetic discussion text for content-only resizing.'}]}],'activeId':'example'})
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':950});errors=[];writes=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:writes.append(request.post_data) if request.url.endswith('/api/appearance') else None)
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('.message-body')).to_have_text('Synthetic discussion text for content-only resizing.')
    def pixels(selector):return page.locator(selector).first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')
    def saved(scale):
     deadline=time.monotonic()+8
     while time.monotonic()<deadline:
      if service.archive.settings()['content_font_scale']==scale and not page.evaluate('contentFontChanging'):return
      page.wait_for_timeout(50)
     raise AssertionError('Content font size was not saved: '+str(scale))
    controls={selector:pixels(selector) for selector in ('body','#settings-open','#message-input','.message-tools button')}
    viewport=page.evaluate('({width:innerWidth,scale:visualViewport.scale})');baseline=pixels('.message-body')
    page.keyboard.press('Meta+Equal');saved(110);assert abs(pixels('.message-body')-baseline*1.1)<.01
    page.keyboard.press('Meta+Shift+Equal');saved(120)
    page.keyboard.press('Meta+Minus');saved(110)
    assert all(pixels(selector)==size for selector,size in controls.items())
    assert page.evaluate('({width:innerWidth,scale:visualViewport.scale})')==viewport,'must prevent browser page zoom'
    page.reload();expect(page.locator('.message-body')).to_be_visible()
    try:page.wait_for_function('()=>document.documentElement.style.getPropertyValue("--content-font-scale")==="1.1"',timeout=3000)
    except Exception:
     print({'writes':writes,'saved':service.archive.settings()['content_font_scale'],'client':page.evaluate('({css:document.documentElement.style.getPropertyValue("--content-font-scale"),cached:localStorage.getItem("stellar.content-font-scale"),value:contentFontScale,pending:contentFontChanging,revision:contentFontRevision})'),'errors':errors});raise
    assert abs(pixels('.message-body')-baseline*1.1)<.01,(pixels('.message-body'),baseline)
    page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    assert abs(pixels('#detail-dialog .detail-text')-13*1.1)<.01
    action=pixels('#edit-content');page.keyboard.press('Meta+Equal');saved(120)
    assert abs(pixels('#detail-dialog .detail-text')-13*1.2)<.01 and pixels('#edit-content')==action
    page.keyboard.press('Meta+Digit0');saved(100);assert abs(pixels('#detail-dialog .detail-text')-13)<.01
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
    page.locator('#message-input').fill('Unsent draft');page.keyboard.press('Shift+Equal');assert service.archive.settings()['content_font_scale']==100
    assert page.locator('#message-input').input_value().endswith('+'),'plain + must remain a typing key'
    page.keyboard.press('Control+Equal');saved(110);assert pixels('#message-input')==controls['#message-input']
    page.route('**/api/appearance',lambda route:route.fulfill(status=500,content_type='application/json',body='{"error":"Synthetic save failure"}'))
    page.keyboard.press('Meta+Equal');expect(page.locator('#toast')).to_have_text('Synthetic save failure');assert abs(pixels('.message-body')-baseline*1.1)<.01
    page.unroute('**/api/appearance');page.keyboard.press('Meta+Digit0');saved(100)
    for _ in range(15):page.keyboard.press('Meta+Equal')
    saved(200);assert abs(pixels('.message-body')-baseline*2)<.01
    for _ in range(20):page.keyboard.press('Meta+Minus')
    saved(70);assert abs(pixels('.message-body')-baseline*.7)<.01
    page.keyboard.press('Meta+Digit0');saved(100)
    assert service.archive.get(item)==before and not errors,errors
    print('PASS: real Cmd + / = / - / 0 and Ctrl alternative; content-only resizing in chat and detail; unchanged controls/composer/browser zoom; persistence; plain typing; rollback; bounds; source preserved')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
