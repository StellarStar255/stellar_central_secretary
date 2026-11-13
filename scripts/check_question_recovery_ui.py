"""Real worker survives closed/reloaded pages; editable conditions and wake reconnect."""
import json,os,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import model_api
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
release=threading.Event();prompts=[]
class Model(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  try:
   data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));prompt=data['messages'][-1]['content'];prompts.append(prompt)
   if prompt.startswith('为个人知识库生成全文检索词'):
    body=json.dumps({'choices':[{'message':{'content':'{"queries":["课程表"],"followup":true}'},'finish_reason':'stop'}]}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   def emit(text,reason=None):self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text},'finish_reason':reason}]})+'\n\n').encode());self.wfile.flush()
   emit('按指定课表，周二14:00有课。')
   while not release.wait(.1):self.wfile.write(b': waiting\n\n');self.wfile.flush()
   emit('[1]','stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as root:
 s=Service(root);s.archive.configure('api',False)
 model_api.write(root,model_api.prepare(root,{'base_url':f'http://127.0.0.1:{model.server_port}/v1','model':'synthetic','use_key':False,'streaming':True}))
 s.archive.add('课程表','课程表：周二14:00有课。')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(s));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    errors=[]
    def page_open():
     page=browser.new_page(viewport={'width':1280,'height':900});page.on('pageerror',lambda e:errors.append(str(e)));page.goto(base);page.wait_for_function('()=>historyLoaded&&!!token');return page
    page=page_open();page.locator('#input-mode').select_option('library')
    def send(text):page.locator('#message-input').fill(text);page.locator('#send-button').click()
    send('课程表周二有课吗？');expect(page.locator('.streaming-answer')).to_contain_text('14:00',timeout=15000)
    page.close();release.set()
    deadline=time.monotonic()+10
    while s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.05)
    assert s.question_jobs.active_count()==0,'Worker must complete without an open page'
    count=len(prompts);saved=s.chat_history()['conversations'][0]['messages'][-1];assert saved['requestState']=='done' and '[1]' in saved['text']
    page=page_open();expect(page.locator('.source')).to_have_count(1);assert len(prompts)==count,'Reopen must not submit a model request'
    send('这个课程表就是她的，依据这个判断就行');expect(page.locator('.source')).to_have_count(2,timeout=15000)
    send('以后都按这张表判断');expect(page.locator('.source')).to_have_count(3,timeout=15000)
    page.locator('#conversation-basis summary').click();expect(page.locator('[data-basis-edit]')).to_have_count(2)
    page.locator('[data-basis-edit]').first.click();page.locator('.basis-editor textarea').fill('这个课程表就是我女儿的，依据这个判断就行')
    page.locator('.basis-editor button[type=submit]').click();expect(page.locator('.basis-row').first).to_contain_text('女儿')
    page.locator('[data-basis-remove]').last.click();expect(page.locator('[data-basis-edit]')).to_have_count(1)
    page.evaluate('()=>sharedChatSaves');page.reload();page.wait_for_function('()=>historyLoaded');page.locator('#conversation-basis summary').click()
    expect(page.locator('.basis-row')).to_contain_text('女儿');expect(page.locator('[data-basis-edit]')).to_have_count(1)
    expect(page.locator('.message.user').nth(1)).to_contain_text('这个课程表就是她的')
    release.clear();send('那周三呢？');expect(page.locator('.streaming-answer')).to_contain_text('14:00',timeout=15000)
    payload=json.loads(prompts[-1].split('\n',1)[1]);history=str(payload['history'])
    assert '就是我女儿的' in history and '以后都按这张表判断' not in history,history
    page.reload();expect(page.locator('[data-cancel-question]')).to_have_count(1,timeout=10000)
    before=len(prompts);page.evaluate('()=>StellarSessionRecovery.check(Date.now()+60000)')
    page.wait_for_timeout(1000);assert len(prompts)==before,'A resume gap must reconnect without a new model request'
    release.set();expect(page.locator('.source')).to_have_count(4,timeout=15000);assert not page.locator('[data-cancel-question]').count()
    page.screenshot(path=str(Path(os.environ.get('STELLAR_TEST_ARTIFACTS','/tmp'))/'stellar-question-recovery.png'),full_page=True)
    assert not errors,errors
    print('PASS: closed-page completion saved; fresh browser restores final answer without model calls; edited/removed conditions persist and affect model history; original chat unchanged; reload reconnects active worker; simulated wake gap never resubmits')
   finally:browser.close()
 finally:release.set();server.shutdown();server.server_close();s.close();model.shutdown();model.server_close()
