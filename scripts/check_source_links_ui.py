"""Reference cards open source links on double click; single click and PDF pages remain local."""
import os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 base=f'http://127.0.0.1:{server.server_port}';url=base+'/tutorial?lang=en#source-fixture'
 linked,_=service.archive.add('Older linked source','Reference material',url=url)
 note,_=service.archive.add('Local note source','A local note without a URL')
 for index in range(110):service.archive.add('Recent fixture '+str(index),'Unrelated recent content')
 reply={'answer':'Linked record [1], local record [2], PDF page [3].','sources':[
  {'number':1,'item_id':linked,'title':'Older linked source','url':url,'text':'Reference material. '+('Long reference excerpt kept compact. '*20)},
  {'number':2,'item_id':note,'title':'Local note source','url':'','text':'A local note without a URL'},
  {'number':3,'item_id':linked,'title':'PDF page reference','url':url,'origin':{'name':'source.pdf','page':2}}]}
 try:
  with patch.object(service,'ask_library',return_value=reply),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    page.locator('#input-mode').select_option('library');page.locator('#message-input').fill('Find saved references');page.locator('#send-button').click()
    expect(page.locator('.source')).to_have_count(3)
    link=page.locator('.source').nth(0)
    expect(link).to_have_attribute('title','双击打开原链接')
    with page.expect_popup() as opened:link.dblclick(delay=60)
    popup=opened.value;popup.wait_for_load_state();assert popup.url==url;popup.close()
    page.wait_for_timeout(500);expect(page.locator('#detail-dialog')).not_to_be_visible()
    page.evaluate('()=>{window.__viewDelay=null;document.addEventListener("click",e=>{if(e.target.closest(".source-view"))window.__viewClickAt=performance.now()},true);const fetch=window.fetch;window.fetch=(path,...args)=>{if(window.__viewClickAt&&String(path).includes("/api/items/")){window.__viewDelay=performance.now()-window.__viewClickAt;window.__viewClickAt=0}return fetch(path,...args)}}')
    page.locator('.source-view').first.click();expect(page.locator('#detail-dialog')).to_be_visible();expect(page.locator('#edit-title')).to_contain_text('Older linked source')
    assert page.evaluate('()=>window.__viewDelay')<100,'Explicit View item must start immediately without a double-click timer'
    page.locator('#detail-dialog .dialog-head button').click()
    with page.expect_popup() as direct:page.locator('.source-original').first.click()
    popup=direct.value;popup.wait_for_load_state();assert popup.url==url;popup.close()
    expect(page.locator('#detail-dialog')).not_to_be_visible()
    sizes=page.locator('.source-card').evaluate_all('nodes=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height}))')
    assert all(size['width']<=280 and size['height']<=112 for size in sizes),sizes
    page.screenshot(path='/tmp/stellar-source-compact.png')
    page.locator('.source').nth(1).click();expect(page.locator('#detail-dialog')).to_be_visible();expect(page.locator('#edit-title')).to_contain_text('Local note source')
    page.locator('#detail-dialog .dialog-head button').click()
    page.evaluate('()=>{window.__pdfSource=null;StellarPDF.open=(...args)=>{window.__pdfSource=args}}')
    page.locator('.source').nth(2).click()
    assert page.evaluate('()=>window.__pdfSource')==['/api/items/'+linked,'source.pdf',2]
    # Old saved answers may omit URL metadata: the dashboard must reload cited items.
    page.evaluate('()=>{for(const m of currentChat().messages)for(const s of m.sources||[])delete s.url;saveChats()}')
    page.reload();expect(page.locator('.source')).to_have_count(3)
    expect(page.locator('.source').first).to_have_attribute('title','双击打开原链接')
    with page.expect_popup() as reopened:page.locator('.source').first.dblclick(delay=60)
    popup=reopened.value;popup.wait_for_load_state();assert popup.url==url;popup.close()
    assert not errors,errors
    print('PASS: cited older links double-click directly without opening details; single-click details, local notes, PDF page navigation and reloaded legacy references preserved')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
