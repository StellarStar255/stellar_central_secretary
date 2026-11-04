"""Synthetic company material; verify consent and real HTTP enforcement without a model call."""
import json,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',True,capture_close_tabs=False)
    source=('Confidential synthetic project result. '*20).strip()
    item=service.ingest({'url':'https://intranet.fixture.test/report','text':source,'captured_at':'fixture','archive_only':True})['item']
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch('secretary.ai.run',return_value=json.dumps({'summary':'Synthetic permitted summary','tags':[]})) as model,sync_playwright() as pw:
            executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
            browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
            try:
                page=browser.new_page(viewport={'width':1280,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
                status=page.request.get(base+'/api/status').json()
                # Direct HTTP requests cannot bypass the UI acknowledgement.
                blocked=page.request.post(base+'/api/items/'+item['id'],data={},headers={'X-Knowledge-Token':status['token']})
                assert blocked.status==409 and 'company_model' in blocked.json() and model.call_count==0
                service.queue(item['id']);assert model.call_count==0
                page.locator(f'#recent-items [data-id="{item["id"]}"]').click()
                expect(page.locator('.company-data-policy')).to_be_visible()
                page.locator('#retry-ai').click()
                expect(page.locator('#company-model-dialog')).to_be_visible()
                expect(page.locator('#company-model-dialog')).to_contain_text('ChatGPT · Codex CLI')
                expect(page.locator('#company-model-approve')).to_be_disabled()
                page.locator('#company-model-cancel').click()
                assert model.call_count==0 and service.archive.get(item['id'])['text']==source
                page.locator('#retry-ai').click();page.locator('#company-model-ack').check();page.locator('#company-model-approve').click()
                expect(page.locator('#company-model-dialog')).to_have_count(0)
                expect(page.locator('#detail-content')).to_contain_text('Synthetic permitted summary',timeout=15000)
                assert model.call_count==1
                # One confirmation enables later automatic summaries, rather than per-item prompts.
                second=service.ingest({'url':'https://intranet.fixture.test/second','text':'Second company fixture result '*20,'captured_at':'fixture'})['item']
                future=service.summary_futures.get(second['id'])
                if future:future.result(timeout=5)
                assert service.archive.get(second['id'])['summary']=='Synthetic permitted summary' and model.call_count==2
                page.locator('#detail-dialog .dialog-head button').click();page.locator('#settings-open').click()
                expect(page.locator('#company-model-status')).to_contain_text('已确认用于公司资料')
                page.locator('#company-model-revoke').click();expect(page.locator('#company-model-status')).to_contain_text('尚未确认')
                page.locator('#settings-dialog .dialog-head button').click()
                # A library question cannot send protected retrieved passages after revocation.
                page.locator('#input-mode').select_option('ask');page.locator('#message-input').fill('Confidential synthetic project result?');page.locator('#send-button').click()
                expect(page.locator('#company-model-dialog')).to_be_visible();assert model.call_count==2
                page.locator('#company-model-cancel').click();expect(page.locator('#company-model-dialog')).to_have_count(0)
                assert model.call_count==2
                assert service.archive.get(item['id'])['summary']=='Synthetic permitted summary'
                page.screenshot(path='/tmp/secretary-company-model-policy.png')
                assert not errors,errors
                print('PASS: direct HTTP enforcement; cancel preserves source with zero model calls; once-confirmed destination enables automatic summaries; revocation blocks library Q&A; original summary preserved; no live model/network provider calls')
            finally:browser.close()
    finally:service.close();server.shutdown();server.server_close()
