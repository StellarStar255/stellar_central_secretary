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
                assert status['settings']['company_mode'] is False
                page.locator('#settings-open').click();expect(page.locator('#company-mode')).not_to_be_checked()
                expect(page.locator('#company-mode-controls')).not_to_be_visible()
                off=service.ingest({'url':'https://intranet.fixture.test/default-off','text':'DefaultOff fixture material '*20,'captured_at':'fixture'})['item']
                future=service.summary_futures.get(off['id'])
                if future:future.result(timeout=5)
                assert service.archive.get(off['id'])['summary']=='Synthetic permitted summary' and model.call_count==1
                assert page.locator('#company-model-dialog').count()==0
                model.reset_mock()
                page.locator('#company-mode').check();expect(page.locator('#company-mode-controls')).to_be_visible()
                expect(page.locator('#company-model-status')).to_contain_text('尚未确认')
                page.locator('#settings-dialog .dialog-head button').click()
                page.reload();expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
                assert page.request.get(base+'/api/status').json()['settings']['company_mode'] is True
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
                page.locator('#settings-open').click();page.locator('#company-mode').uncheck()
                expect(page.locator('#company-mode-controls')).not_to_be_visible()
                page.locator('#settings-dialog .dialog-head button').click()
                page.locator(f'#recent-items [data-id="{item["id"]}"]').click()
                expect(page.locator('.company-data-policy')).to_have_count(0)
                with page.expect_response(lambda r:r.url==base+'/api/items/'+item['id'] and r.request.method=='POST') as response:
                    page.locator('#retry-ai').click()
                assert response.value.ok
                future=service.summary_futures.get(item['id'])
                if future:future.result(timeout=5)
                assert page.locator('#company-model-dialog').count()==0
                expect(page.locator('#detail-content')).to_contain_text('Synthetic permitted summary')
                assert model.call_count==3
                page.screenshot(path='/tmp/secretary-company-model-policy.png')
                assert not errors,errors
                print('PASS: company mode defaults off and has no extra confirmation; toggle persists across reload; enabled mode direct HTTP enforcement; cancel preserves source with zero model calls; once-confirmed destination enables automatic summaries; revocation blocks library Q&A; original summary preserved; no live model/network provider calls')
            except Exception:
                print({'page_errors':errors,'company_mode':service.archive.settings()['company_mode'],'model_calls':model.call_count,'mode_handler':page.locator('#company-mode').evaluate('(e)=>typeof e.onchange'),'toast':page.locator('#toast').inner_text()},flush=True)
                raise
            finally:browser.close()
    finally:service.close();server.shutdown();server.server_close()
