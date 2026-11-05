"""Delete without refreshing, stopping a summary manually, or waiting for another message."""
import json,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary import ai
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    item,_=service.archive.add('Synthetic deletion fixture','Original source must stay recoverable.');service.archive.update(item,summary='Original summary')
    started=threading.Event();release=threading.Event();calls=[]
    def summary(*args,**kwargs):
        calls.append(True);index=len(calls);started.set();release.wait(20)
        return {'title':'Synthetic deletion fixture' if index==1 else 'Late title must not overwrite','summary':'Completed while dialog open' if index==1 else 'Late summary must not overwrite','state':'ready','error':''}
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(ai,'summary_fields',side_effect=summary),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
            try:
                service.queue(item,force=True);first=service.summary_futures[item];assert started.wait(3)
                page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));held=[]
                page.route('**/api/ask',lambda route:held.append(route))
                page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
                page.locator('#input-mode').select_option('ask');page.locator('#message-input').fill('What does the synthetic material say?');page.locator('#send-button').click();expect(page.locator('#send-button')).to_be_disabled()
                page.locator('#recent-items [data-id="'+item+'"]').click(button='right');page.locator('#archive-delete-menu').click();expect(page.locator('#delete-archive-dialog')).to_be_visible()
                # A result changes the revision after the confirmation dialog opens.
                release.set();first.result(timeout=3);assert service.archive.get(item)['summary']=='Completed while dialog open'
                page.locator('#delete-archive-confirm').click();expect(page.locator('#delete-archive-dialog')).not_to_be_visible();expect(page.locator('#recent-items [data-id="'+item+'"]').first).to_have_count(0)
                expect(page.locator('#toast button')).to_have_text('撤销');page.locator('#toast button').click();expect(page.locator('#recent-items [data-id="'+item+'"]').first).to_be_visible()
                assert service.archive.get(item)['summary']=='Completed while dialog open'
                # Trash during a non-cooperative summary, then restore before it returns.
                started.clear();release.clear();service.queue(item,force=True);second=service.summary_futures[item];assert started.wait(3)
                page.locator('#recent-items [data-id="'+item+'"]').click(button='right');page.locator('#archive-delete-menu').click();expect(page.locator('#delete-archive-dialog')).to_be_visible()
                page.locator('#delete-archive-confirm').click();expect(page.locator('#delete-archive-dialog')).not_to_be_visible();expect(page.locator('#recent-items [data-id="'+item+'"]').first).to_have_count(0)
                assert not second.done() and service.archive.get(item,True)['trashed_at']
                page.locator('#toast button').click();expect(page.locator('#recent-items [data-id="'+item+'"]').first).to_be_visible();release.set();second.result(timeout=3)
                saved=service.archive.get(item);assert saved['summary']=='Completed while dialog open' and saved['title']=='Synthetic deletion fixture' and saved['text']=='Original source must stay recoverable.'
                assert held,'Question must still be pending while trashing is allowed'
                for route in held:route.fulfill(status=200,content_type='application/json',body=json.dumps({'answer':'Independent question completed.','sources':[]}))
                expect(page.locator('#messages')).to_contain_text('Independent question completed.');assert not errors,errors
                print('PASS: confirmation survives completed summary revision; trash while summarizing and another message is pending; no manual stop/reload; undo preserves latest source and summary; late model result fenced; independent message unaffected')
            finally:release.set();browser.close()
    finally:server.shutdown();server.server_close();service.close()
