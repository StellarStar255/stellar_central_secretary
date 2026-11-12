"""Reproduce the reported automatic-mode schedule question/follow-up with synthetic data."""
import base64,io,json,os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
calls=[]
def model(prompt,backend,**kwargs):
 payload=json.loads(prompt.split('\n',1)[1]);calls.append((payload,kwargs))
 if 'passages' not in payload:return json.dumps({'queries':['课程表'],'followup':bool(payload['history'])})
 assert len(kwargs.get('images',[]))==1
 assert payload['visual_evidence'][0]['status']=='image_attached_for_rechecking'
 number=next(p['source'] for p in payload['passages'] if p['title']=='2026年第9周课程表')
 if '依据这个判断' in payload['question']:
  return '**按你指定的这张课表判断，周四下午图示时段没有课**。这以本周沿用该表为前提；图片本身显示11月2日至8日。['+str(number)+']'
 return '**不能确定今天下午是否有课**。已核对图示范围为11月2日至8日，不能把旧周空白推断为今天无课。['+str(number)+']'

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 image=io.BytesIO();Image.new('RGB',(600,900),'white').save(image,'PNG')
 course=service.ingest({'text':'课程表','attachments':[{'name':'schedule.png','data':base64.b64encode(image.getvalue()).decode()}],'archive_only':True})['item']['id']
 service.archive.update(course,title='2026年第9周课程表',vision_text='第9周，2026年11月2日至8日，周四可见区域无课程块。')
 for title in ('罗马皇位继承','消费贷款','泰山登山'):
  service.archive.add(title,'今天下午讨论这个问题，有没有新的安排？')
 before=service.archive.export()
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.ai.run',side_effect=model),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
   expect(page.locator('#input-mode')).to_have_value('auto')
   page.locator('#message-input').fill('我老婆今天下午有课吗？');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(1);expect(page.locator('.message-body strong')).to_have_text('不能确定今天下午是否有课')
   assert '罗马' not in page.locator('#messages').inner_text()
   page.locator('#message-input').fill('看下课程表再告诉我');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(2)
   assert calls[-2][0]['history'][0]['question']=='我老婆今天下午有课吗？'
   assert calls[-2][0]['history'][0]['source_ids']==[course]
   page.locator('#message-input').fill('继续');page.locator('#send-button').click();expect(page.locator('.source')).to_have_count(3)
   # A legacy accidental archive must not erase the conversation's intent.
   page.evaluate("""()=>{const chat=currentChat();delete chat.dialogueActive;for(const m of chat.messages)delete m.knowledgeQuestion;addMessage(chat,'user','旧版误存的补充');addMessage(chat,'assistant','旧版已归档',{archiveOnly:true})}""")
   clarification='这个课程表就是她的，依据这个判断就行'
   page.locator('#message-input').fill(clarification);page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(4)
   expect(page.locator('.message-body strong').last).to_contain_text('按你指定的这张课表判断')
   assert calls[-1][0]['question']==clarification and calls[-1][0]['history'][0]['question']=='我老婆今天下午有课吗？'
   page.reload();expect(page.locator('#composer-hint')).to_contain_text('对话进行中')
   page.locator('#archive-only').check();expect(page.locator('#composer-hint')).to_contain_text('只保存，不会回答')
   expect(page.locator('#resume-conversation')).to_be_visible()
   page.locator('#message-input').fill(clarification);page.locator('#resume-conversation').click()
   expect(page.locator('#archive-only')).not_to_be_checked();expect(page.locator('#message-input')).to_have_value(clarification)
   page.locator('#send-button').click();expect(page.locator('.source')).to_have_count(5)
   assert service.archive.export()==before
   assert len([call for call in calls if call[1].get('images')])==5
   page.screenshot(path='/tmp/secretary-schedule-chat-fixed.png')
   assert not errors,errors
   browser.close()
   print('PASS: screenshot questions and declarative clarification, legacy accidental-archive recovery, persistent dialogue after reload, archive-only warning/return button, source cards, saved image supplied and zero new archives; deterministic model replies')
 finally:server.shutdown();server.server_close();service.close()
