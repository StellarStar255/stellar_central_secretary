"""Six chat improvements through real HTTP, API-worker SSE and a real browser."""
import json,os,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import ai,model_api
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

finish=threading.Event();requests=[];fail_answers=False
class Model(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));prompt=data['messages'][-1]['content'];requests.append(prompt)
  if prompt.startswith('为个人知识库生成全文检索词'):
   question=json.loads(prompt.split('\n',1)[1])['question']
   if '罗马' in question:answer=json.dumps({'catalog':True,'queries':['罗马']})
   elif '闲聊' in question:answer=json.dumps({'route':'chat','answer':'可以继续聊天。','queries':[]})
   else:answer=json.dumps({'queries':['课程表'],'followup':True})
   body=json.dumps({'choices':[{'message':{'content':answer},'finish_reason':'stop'}]}).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if fail_answers:
   self.send_response(500);self.end_headers();return
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  def emit(text,reason=None):self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text},'finish_reason':reason}]})+'\n\n').encode());self.wfile.flush()
  emit('按课表，周四14:00有课。')
  if not finish.wait(30):return
  emit('[1]','stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()

model=ThreadingHTTPServer(('127.0.0.1',0),Model);threading.Thread(target=model.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('api',False)
 model_api.write(root,model_api.prepare(root,{'base_url':f'http://127.0.0.1:{model.server_port}/v1','model':'synthetic','use_key':False,'streaming':True}))
 for i in range(65):service.archive.add('罗马史资料 '+str(i),'罗马史唯一记录 '+str(i))
 course,_=service.archive.add('课程表','课程表：周四14:00有课。这个段落用于验证引用能定位到原文中的具体内容。')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.answer_cache.current_time',return_value={'date':'2026-11-12','time':'12:00','utc_offset':'+0800'}),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.add_init_script("window.__notices=[];window.Notification=class{static permission='granted';constructor(title,options){this.title=title;this.options=options;window.__notices.push(this)}close(){}}")
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_contain_text('synthetic')
    page.locator('#input-mode').select_option('library')
    def send(text):page.locator('#message-input').fill(text);page.locator('#send-button').click()
    send('列出所有罗马史资料')
    expect(page.locator('.catalog-pager')).to_contain_text('1–20 / 65');expect(page.locator('.source')).to_have_count(20)
    page.evaluate('()=>{const remote=JSON.parse(JSON.stringify(conversations));remote.find(c=>c.id===activeId).updated+=1;mergeChats({conversations:remote});renderChat(false)}')
    page.locator('[data-catalog]').last.click();expect(page.locator('.catalog-pager')).to_contain_text('21–40 / 65')
    page.locator('[data-catalog]').last.click();expect(page.locator('.catalog-pager')).to_contain_text('41–60 / 65')
    page.locator('[data-catalog]').last.click();expect(page.locator('.catalog-pager')).to_contain_text('61–65 / 65');expect(page.locator('.source')).to_have_count(5)
    page.locator('#new-chat').click();page.locator('#input-mode').select_option('library')
    send('她今天有课吗？')
    expect(page.locator('.streaming-answer')).to_contain_text('周四14:00有课',timeout=10000)
    assert not page.locator('[data-recheck]').count(),'Partial text must not become a completed answer'
    page.evaluate('()=>{saveChats();return sharedChatSaves}')
    assert 'questionProgress' not in json.dumps(service.chat_history()),'Transient streamed text must not be persisted as conversation data'
    finish.set();expect(page.locator('.source')).to_have_count(1)
    expect(page.locator('.source-quote')).to_contain_text('原文中的具体内容')
    page.locator('.source').click();expect(page.locator('#detail-dialog')).to_be_visible()
    assert page.evaluate("()=>CSS.highlights.has('cited-passage')||!!document.querySelector('mark[data-citation]')")
    page.locator('#detail-dialog .dialog-head button').click()
    count=len(requests);send('她今天有课吗？');expect(page.locator('.answer-timing').last).to_contain_text('复用近期回答');assert len(requests)==count
    page.locator('[data-recheck]').last.click();expect(page.locator('.answer-timing').last).not_to_contain_text('复用近期回答');expect(page.locator('.source')).to_have_count(2);assert len(requests)==count+2
    fail_answers=True;page.locator('[data-recheck]').last.click()
    expect(page.locator('#messages')).to_contain_text('重新核对未完成，保留上次回答。');expect(page.locator('.source')).to_have_count(2)
    fail_answers=False
    send('这个课程表就是她的，依据这个判断就行');expect(page.locator('.source')).to_have_count(3)
    for i in range(7):
     send('闲聊第'+str(i)+'轮');expect(page.locator('.message.assistant').last).to_contain_text('可以继续聊天')
    send('星期一呢？');expect(page.locator('.source')).to_have_count(4)
    payload=json.loads(requests[-1].split('\n',1)[1]);assert any('就是她的' in turn['question'] for turn in payload['history'])
    page.locator('#conversation-basis summary').click();expect(page.locator('#conversation-basis')).to_contain_text('这个课程表就是她的')
    page.evaluate('()=>{const remote=JSON.parse(JSON.stringify(conversations));remote.find(c=>c.id===activeId).updated+=1;mergeChats({conversations:remote});renderChat(false)}')
    page.locator('#clear-conversation-basis').click();assert page.evaluate('()=>rememberedContext(currentChat()).length')==0
    page.evaluate('()=>sharedChatSaves')
    page.reload();expect(page.locator('#model-label')).to_contain_text('synthetic')
    page.wait_for_function('()=>historyLoaded')
    assert page.evaluate('()=>rememberedContext(currentChat()).length')==0,'Cleared conditions must stay cleared after reload'
    with service.archive.db() as db:db.execute("INSERT OR REPLACE INTO settings VALUES ('completion_notifications','true')")
    with patch.object(ai,'summary_fields',return_value={'summary':'Synthetic completed summary','state':'ready','error':''}):
     service.queue(course,force=True)
     with service.lock:future=service.summary_futures.get(course)
     if future:future.result(timeout=5)
    page.evaluate('refresh()')
    page.wait_for_function('()=>window.__notices.length===1')
    assert page.evaluate('()=>window.__notices[0].title')=='资料已整理'
    page.evaluate('()=>window.__notices[0].onclick()');expect(page.locator('#tasks-dialog')).to_be_visible()
    assert not errors,errors
    print('PASS: complete 65-record catalog pages, actual API-worker streaming before completion, cited-text location, context beyond six turns and clear, cache reuse/manual refresh, opt-in completion notification and Tasks action')
   finally:browser.close()
 finally:finish.set();server.shutdown();server.server_close();service.close();model.shutdown();model.server_close()
