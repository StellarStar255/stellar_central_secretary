"""Synthetic delayed-model UI checks: independent lanes, progress and archive-only."""
import json,os,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import ai
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',True)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 long_started=threading.Event();short_started=threading.Event();release_long=threading.Event();release_short=threading.Event()
 def model(item,*args,**kwargs):
  ai.report('waiting_model')
  if len(item['text'])>4000:long_started.set();assert release_long.wait(60)
  else:short_started.set();assert release_short.wait(60)
  return {'title':item['title'],'summary':'Synthetic concise summary.','state':'ready','error':''}
 try:
  with patch.object(ai,'summary_fields',side_effect=model) as summarize,patch.object(service,'ask',side_effect=AssertionError('Archive only must not ask')) as ask,patch('secretary.server.fetch_page',side_effect=AssertionError('Archive only must not fetch')) as fetch,sync_playwright() as pw:
   long_id,_=service.archive.add('Long synthetic source','L'*5000);other,_=service.archive.add('Second long source','M'*5000)
   service.queue(long_id,force=True);assert long_started.wait(3);service.queue(other,force=True)
   executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
   browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
   try:
    page=browser.new_page(viewport={'width':1250,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    page.locator('#message-input').fill('tar -czf synthetic.tar.gz samples/');page.locator('#send-button').click();assert short_started.wait(3)
    expect(page.locator('#messages .summary-progress')).to_contain_text('模型处理中',timeout=5000)
    expect(page.locator('#messages .summary-progress')).to_contain_text('模型阶段（含启动）')
    expect(page.locator('#composer-status')).to_have_text('')
    page.evaluate("window.__testMessageBody=document.querySelector('#messages .message-body');true")
    page.evaluate('refresh()');assert page.evaluate("window.__testMessageBody===document.querySelector('#messages .message-body')"),'Timing updates must preserve message nodes and text selection'
    page.screenshot(path='/tmp/secretary-summary-progress.png')
    release_short.set();expect(page.locator('#messages .archive-summary')).to_contain_text('Synthetic concise summary.',timeout=5000)
    expect(page.locator('#messages .summary-progress')).to_contain_text('处理完成')
    assert service.archive.get(long_id)['state']=='processing' and service.archive.get(other)['state']=='pending'
    assert 'queue_seconds' not in json.dumps(service.chat_history()),'Timing polls must not rewrite chat history with transient metrics'
    calls=summarize.call_count
    page.locator('#archive-only').check();page.locator('#input-mode').select_option('ask')
    page.locator('#message-input').fill('为什么这个命令需要引号？仅作为备忘保存。');page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(2);expect(page.locator('#messages')).to_contain_text('未调用 AI')
    page.locator('#input-mode').select_option('auto');page.locator('#message-input').fill('Related links\nhttps://example.invalid/one\nhttps://example.invalid/two');page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(3)
    assert summarize.call_count==calls and not ask.called and not fetch.called
    saved=[item for item in service.archive.list() if item['state']=='saved'];assert len(saved)==2
    page.locator('#settings-open').click();page.locator('#ui-language').select_option('en')
    expect(page.locator('.archive-only-control')).to_contain_text('Archive only, skip summary')
    page.locator('#settings-dialog .dialog-head button').click();expect(page.locator('#messages .summary-progress')).to_contain_text('Completed')
    page.screenshot(path='/tmp/secretary-summary-english.png')
    assert not errors,errors
    print('PASS: real GUI shows live model stage and timing, short task bypasses blocked long tasks, archive-only overrides questions and grouped URL capture, no AI/fetch and no transient chat-history writes, bilingual controls')
   finally:browser.close()
 finally:
  release_long.set();release_short.set();server.shutdown();server.server_close();service.close()
