"""Real Chrome smoke test with synthetic project pages; no accounts or model calls."""
import json,os,socket,subprocess,sys,tempfile,threading,time,urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import web_reader,browser_reader
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
HTML='''<!doctype html><title>Example project</title><nav>PRIVATE NAVIGATION</nav><main><h1>Project issue</h1><p>Loaded project discussion and requirements. This content is already visible and should be archived with its table and field values.</p><button>Status: in progress</button><table><tr><th>Field</th><th>Value</th></tr><tr><td>Priority</td><td>High</td></tr></table><div hidden>HIDDEN MATERIAL</div><textarea>DRAFT SECRET</textarea><input value="FORM SECRET"><div contenteditable="true">UNSENT DRAFT</div></main>'''
class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  text=('<main><p>没有访问权限，请联系管理员</p></main>' if self.path.startswith('/denied') else HTML).encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(text)
 def log_message(self,*args):pass
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=fixture.serve_forever,daemon=True).start()
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
 proc=subprocess.Popen([os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),'--headless=new',f'--user-data-dir={root/"chrome"}',f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 service=None;app=None
 try:
  for _ in range(100):
   try:session=browser_reader.debug_info(f'http://127.0.0.1:{port}');break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('Chrome did not start')
  session.update(process=proc,confirmed=True)
  target=f'http://127.0.0.1:{fixture.server_port}/issue?tabKey=comment#comment'
  def tabs():
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:return [tab for tab in json.load(response) if tab['type']=='page']
  existing={tab['id'] for tab in tabs()}
  confirmation=threading.Event()
  def notify(state,message):
   if state=='waiting_login':confirmation.set()
  with patch.object(web_reader,'browser_proxy',return_value=None),patch.object(web_reader,'validate_public_url',side_effect=lambda url:url),patch.object(browser_reader,'start_or_reuse_browser',return_value=session):
   result=web_reader.read(target,root/'profile',notify,threading.Event(),login_complete=confirmation,background=True,close_new_tabs=True,language='en')
  assert result['url']==target and result['text'].startswith(web_reader.PREFIX_EN)
  assert '| Priority | High |' in result['text'] and 'Status: in progress' in result['text']
  for secret in ('PRIVATE NAVIGATION','HIDDEN MATERIAL','DRAFT SECRET','FORM SECRET','UNSENT DRAFT'):assert secret not in result['text'],secret
  assert {tab['id'] for tab in tabs()}==existing,'close only the newly opened successful task tab'
  with patch.object(web_reader,'browser_proxy',return_value=None),patch.object(web_reader,'validate_public_url',side_effect=lambda url:url),patch.object(browser_reader,'start_or_reuse_browser',return_value=session):
   try:web_reader.read(target.replace('/issue','/denied'),root/'profile',notify,threading.Event(),login_complete=confirmation,close_new_tabs=True)
   except RuntimeError as error:assert '访问权限' in str(error)
   else:raise AssertionError('permission page should not be saved')
  assert len(tabs())==len(existing)+1,'failed page remains available for inspection'
  service=Service(root/'library');service.archive.configure('codex',False)
  item,_=service.archive.add('Example issue','',url='https://example.test/issue?tabKey=comment#comment')
  service.archive.update(item,state='waiting_login')
  app=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=app.serve_forever,daemon=True).start()
  with sync_playwright() as pw:
   browser=pw.chromium.connect_over_cdp(session['websocket']);page=browser.contexts[0].new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{app.server_port}');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
   expect(page.locator('[data-confirm-login="'+item+'"]')).to_have_text('页面已打开，开始读取')
   page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en')
   page.locator('#settings-dialog .dialog-head button').click();page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
   expect(page.locator('[data-confirm-login="'+item+'"]')).to_have_text('Page is ready, start reading')
   assert 'Waiting for page confirmation' in page.locator('#detail-content').inner_text();assert not errors,errors
   page.screenshot(path='/tmp/secretary-web-capture-en.png');page.close()
  print('PASS: loaded webpage and Markdown tables, exact query/fragment, hidden/form/draft exclusions, permission refusal, only owned success tab closed, failure tab retained, bilingual capture controls and zero model calls')
 finally:
  if app:app.shutdown();app.server_close()
  if service:service.close()
  fixture.shutdown();fixture.server_close();proc.terminate();proc.wait(timeout=15)
