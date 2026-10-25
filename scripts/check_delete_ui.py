"""Synthetic deletion UI: confirmation, references, stale windows and local drafts."""
import json,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

SECRET='DELETE_FIXTURE_SECRET'
with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 keep,_=service.archive.add('Keep record','Unrelated record '*30)
 item,_=service.archive.add(SECRET,SECRET*30,filename='example.txt',data=SECRET.encode())
 service.archive.update(item,summary=SECRET,state='ready');before=service.archive.get(keep)
 stale={'conversations':[{'id':'chat','title':SECRET,'updated':1,'messages':[
  {'id':'private-u','role':'user','text':SECRET}, {'id':'private-a','role':'assistant','text':SECRET,'items':[item]},
  {'id':'keep-u','role':'user','text':'Keep request'}, {'id':'keep-a','role':'assistant','text':'Keep answer','items':[keep]}
 ]}],'activeId':'chat'}
 service.chat_history(stale)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    context=browser.new_context(viewport={'width':1280,'height':950});page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    second_context=browser.new_context();second=second_context.new_page()
    for current in (page,second):
     current.goto(base)
     try:expect(current.locator('#recent-items [data-id="'+item+'"]')).to_be_visible()
     except Exception:print({'page_errors':errors,'toast':current.locator('#toast').inner_text()});raise
     current.evaluate('(id)=>localStorage.setItem("stellar-note-draft:"+id,JSON.stringify({text:"DELETE_FIXTURE_SECRET",version:0}))',item)
    row=page.locator('#recent-items [data-id="'+item+'"]')
    row.click(button='right');expect(page.locator('#archive-context-menu')).to_be_visible()
    page.locator('#archive-delete-menu').click();expect(page.locator('#delete-archive-title')).to_have_text(SECRET)
    page.locator('#delete-archive-cancel').click();assert service.archive.get(item)['title']==SECRET
    # Same menu must work above the library's native modal layer.
    page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click(button='right')
    expect(page.locator('#archive-context-menu')).to_be_visible();page.keyboard.press('Escape')
    expect(page.locator('#library-dialog')).to_be_visible();page.locator('#library-dialog .dialog-head button').click()
    row.click(button='right');page.locator('#archive-delete-menu').click()
    service.busy.add(item);page.locator('#delete-archive-confirm').click();expect(page.locator('#toast')).to_contain_text('正在处理')
    assert service.archive.get(item)['title']==SECRET;service.busy.clear()
    page.locator('#delete-archive-confirm').click();expect(page.locator('#toast')).to_have_text('归档已删除')
    expect(row).to_have_count(0);assert SECRET not in page.locator('#messages').inner_text()
    assert SECRET not in page.evaluate('localStorage.getItem("stellar.conversations.v1")')
    assert page.evaluate('id=>localStorage.getItem("stellar-note-draft:"+id)',item) is None
    second.evaluate('refresh()');expect(second.locator('#recent-items [data-id="'+item+'"]')).to_have_count(0)
    assert SECRET not in second.locator('#messages').inner_text()
    assert second.evaluate('id=>localStorage.getItem("stellar-note-draft:"+id)',item) is None
    # A fresh browser with an old local cache must never render the deleted text.
    third=browser.new_context();third.add_init_script('localStorage.setItem("stellar.conversations.v1",'+json.dumps(json.dumps(stale))+');globalThis.privateFlash=false;new MutationObserver(()=>{if(document.querySelector("#messages")?.textContent.includes("DELETE_FIXTURE_SECRET"))privateFlash=true}).observe(document,{childList:true,subtree:true})')
    fresh=third.new_page();fresh.goto(base);expect(fresh.locator('#recent-items [data-id="'+keep+'"]')).to_be_visible()
    assert not fresh.evaluate('privateFlash') and SECRET not in fresh.locator('#messages').inner_text()
    assert service.archive.get(keep)==before and not errors,errors
    page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');page.locator('#settings-dialog .dialog-head button').click()
    page.locator('#recent-items [data-id="'+keep+'"]').click(button='right');expect(page.locator('#archive-delete-menu')).to_have_text('Delete archive…')
    page.screenshot(path='/tmp/secretary-delete-menu.png')
    page.locator('#archive-delete-menu').click();page.locator('#delete-archive-confirm').click()
    expect(page.locator('#toast')).to_have_text('Archive deleted');expect(page.locator('#messages')).to_be_empty()
    expect(page.locator('#recent-items button')).to_have_count(0)
    print('PASS: sidebar/library right-click menu, cancel, busy protection, confirmed deletion, linked chat cleanup, unrelated archive preserved, stale window cleanup, local note-draft removal, no deleted cache flash on startup, English labels; synthetic data only')
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close()
