"""Real browser/HTTP integration with deterministic local embedding and answer fixtures."""
import json,os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

requests=[];fail=False;answers=[]
class Embeddings(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,body))
  if fail:
   self.send_response(503);self.end_headers();return
  assert self.path=='/api/embed' and body['truncate'] is False
  vectors=[[1.,0.,0.] if any(word in text for word in ('battery','省电','节能')) else [0.,1.,0.] for text in body['input']]
  encoded=json.dumps({'embeddings':vectors}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)

def model(prompt,backend,**kwargs):
 payload=json.loads(prompt.split('\n',1)[1])
 if 'passages' not in payload:return json.dumps({'queries':['battery' if 'battery' in payload['question'] else '节能']})
 answers.append(payload);return '关闭后台应用可以延长续航。[1]'

with tempfile.TemporaryDirectory() as root:
 embeddings=ThreadingHTTPServer(('127.0.0.1',0),Embeddings);threading.Thread(target=embeddings.serve_forever,daemon=True).start()
 service=Service(root);service.archive.configure('codex',False)
 item,_=service.archive.add('Travel memo','Improve battery life by closing background applications.')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.ai.run',side_effect=model),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
   page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
   page.locator('#settings-open').click();expect(page.locator('#semantic-progress')).to_contain_text('已保留索引')
   page.locator('#semantic-url').fill(f'http://127.0.0.1:{embeddings.server_port}')
   page.locator('#semantic-test').click();expect(page.locator('#semantic-test-result')).to_contain_text('向量维度：3')
   page.locator('#semantic-enabled').check();page.locator('#semantic-save').click()
   expect(page.locator('#semantic-progress')).to_contain_text('1 / 1',timeout=15000)
   page.locator('#semantic-settings').scroll_into_view_if_needed();page.screenshot(path='/tmp/secretary-semantic-settings.png')
   page.locator('#settings-dialog .dialog-head button').click();page.locator('[data-suggestion="ask"]').click()
   assert service.archive.retrieve('如何省电')==[]
   page.locator('#message-input').fill('如何省电');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(1)
   assert answers[-1]['passages'][0]['text'].startswith('Improve battery')
   assert page.locator('.source').get_attribute('data-id')==item
   page.screenshot(path='/tmp/secretary-semantic-answer.png')
   fail=True
   page.locator('#message-input').fill('battery 用法');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(2)
   expect(page.locator('#messages')).to_contain_text('语义检索暂不可用，已使用关键词检索。')
   assert answers[-1]['passages'][0]['text'].startswith('Improve battery')
   fail=False
   page.locator('#settings-open').click();page.locator('#semantic-rebuild').click()
   expect(page.locator('#semantic-progress')).to_contain_text('1 / 1',timeout=15000)
   page.locator('#ui-language').select_option('en');expect(page.locator('#semantic-settings h3')).to_have_text('Local semantic search')
   expect(page.locator('#semantic-progress')).to_contain_text('Indexed passages',timeout=10000)
   page.locator('#semantic-enabled').uncheck();page.locator('#settings-save').click()
   expect(page.locator('#settings-dialog')).not_to_be_visible()
   assert service.semantic.status()['config']['enabled'] is False
   assert len(service.archive.export())==1
   assert not errors,errors
   browser.close()
   print('PASS: embedding HTTP contract, connection test, background backfill, semantic-only cross-language retrieval, source citation, service-failure keyword fallback, rebuild, English UI and main-settings save; model/embedding outputs are fixtures')
 finally:
  server.shutdown();server.server_close();service.close();embeddings.shutdown();embeddings.server_close()
