"""Real API-worker cancellation/retry, citation revisions and setup guidance."""
import json,os,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import model_api
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
block=threading.Event();entered=threading.Event()
class Model(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  try:
   payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
   prompt=payload['messages'][-1]['content']
   if prompt.startswith('为个人知识库生成全文检索词'):
    body=json.dumps({'choices':[{'message':{'content':'{"queries":["课程表"]}'},'finish_reason':'stop'}]}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   def emit(text,reason=None):self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text},'finish_reason':reason}]})+'\n\n').encode());self.wfile.flush()
   entered.set();emit('按课表，周二下午无课。')
   while not block.wait(.1):self.wfile.write(b': waiting\n\n');self.wfile.flush()
   emit('[1]','stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as root:
 s=Service(root);s.archive.configure('api',False)
 model_api.write(root,model_api.prepare(root,{'base_url':f'http://127.0.0.1:{model.server_port}/v1','model':'synthetic','use_key':False,'streaming':True}))
 item=s.archive.add('课程表','课程表：周二下午无课。')[0]
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(s));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    held=[];page.route('**/api/conversations',lambda route:held.append(route))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.wait_for_function('()=>!!token')
    page.locator('#input-mode').select_option('library');assert not page.evaluate('historyLoaded')
    for route in list(held):route.continue_()
    page.unroute('**/api/conversations')
    page.wait_for_function('()=>historyLoaded');expect(page.locator('#input-mode')).to_have_value('library')
    page.locator('#message-input').fill('课程表周二有课吗？');page.locator('#send-button').click()
    expect(page.locator('.streaming-answer')).to_contain_text('周二下午无课',timeout=15000)
    page.locator('[data-cancel-question]').click()
    expect(page.locator('#messages')).to_contain_text('问答已停止，可重试。',timeout=10000)
    expect(page.locator('[data-recheck]')).to_have_text('重试回答')
    assert s.runtime()['answering']==0,'Stopped API worker must release its model lane'
    assert not s.answer_cache.entries,'Partial answers must not enter answer cache'
    assert not page.locator('.source').count(),'Unverified streamed citations must not become final references'
    block.set();page.locator('[data-recheck]').click();expect(page.locator('.source')).to_have_count(1,timeout=15000)
    expect(page.locator('.message-body').last).to_contain_text('周二下午无课。')
    assert not page.locator('.question-stop').count()
    # Failed rechecks preserve a completed answer and its references.
    page.route('**/api/ask/start',lambda route:route.fulfill(status=500,content_type='application/json',body='{"error":"Synthetic retry failure"}'))
    page.locator('[data-recheck]').click();expect(page.locator('#messages')).to_contain_text('重新核对未完成，保留上次回答。')
    expect(page.locator('.source')).to_have_count(1);page.unroute('**/api/ask/start')
    s.archive.update(item,text='课程表：周二下午已调整。');page.evaluate('refresh()')
    expect(page.locator('.source-changed')).to_have_text('资料已更新')
    s.trash_item(item);page.evaluate('refresh()');expect(page.locator('.source-changed')).to_have_text('已移入回收站')
    page.locator('.source-view').click();expect(page.locator('#toast')).to_contain_text('可恢复后查看');assert not page.locator('#detail-dialog').is_visible()
    page.locator('#settings-open').click();page.locator('#model-readiness summary').click();expect(page.locator('[data-readiness-status]')).to_contain_text('API 配置')
    expect(page.locator('#model-readiness')).to_contain_text('关键词检索无需下载模型')
    page.screenshot(path='/tmp/stellar-conversation-controls.png',full_page=True)
    page.locator('#ui-language').select_option('en');expect(page.locator('#model-readiness summary')).to_have_text('Search and answer readiness')
    assert not errors,errors
    print('PASS: real API worker stopped and lane released; partial answer not cached; retry succeeds; failed recheck preserves prior answer; updated/trashed citation states; local readiness guidance and English translation')
   finally:browser.close()
 finally:block.set();server.shutdown();server.server_close();s.close();model.shutdown();model.server_close()
