"""Hold actual HTTP question calls at model stages and verify live browser progress."""
import json,os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

planning=threading.Event();answering=threading.Event();fail=False

def model(prompt,*args,**kwargs):
 if fail:raise RuntimeError('Synthetic model failure')
 if prompt.startswith('为个人知识库生成全文检索词'):
  if not planning.wait(15):raise RuntimeError('Test planning deadline')
  return json.dumps({'queries':['课程表']})
 if not answering.wait(15):raise RuntimeError('Test answer deadline')
 return '周四14:00有课。[1]'

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False);service.archive.add('课程表','周四14:00有课。')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.ai.run',side_effect=model),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
   page.locator('#message-input').fill('课程表有课吗？');page.locator('#send-button').click()
   expect(page.locator('.question-progress')).to_contain_text('规划检索')
   page.wait_for_timeout(1200)
   expect(page.locator('.question-progress small')).to_contain_text('已等待 1')
   planning.set()
   expect(page.locator('.question-progress')).to_contain_text('生成回答')
   expect(page.locator('.question-progress small')).to_contain_text('相关资料 1')
   answering.set()
   expect(page.locator('.source')).to_have_count(1)
   expect(page.locator('.question-progress')).to_have_count(0)
   fail=True
   page.locator('#message-input').fill('明天有课吗？');page.locator('#send-button').click()
   expect(page.locator('.message.error')).to_contain_text('Synthetic model failure')
   expect(page.locator('.question-progress')).to_have_count(0)
   fail=False
   page.locator('#message-input').fill('谢谢');page.locator('#send-button').click()
   expect(page.locator('.answer-timing').last).to_contain_text('本地即时回复')
   expect(page.locator('.question-progress')).to_have_count(0)
   assert not errors,errors
   assert len(service.archive.list())==1,'Questions must not be archived'
   browser.close()
   print('PASS: live HTTP planning/answer stages, elapsed timer, real source count, completion/error cleanup and instant greeting')
 finally:
  planning.set();answering.set();server.shutdown();server.server_close();service.close()
