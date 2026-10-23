"""Real Chrome fixture: requests must continue while capture waits for confirmation."""
import json,os,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import web_reader,browser_reader
from playwright.sync_api import sync_playwright,TimeoutError as BrowserTimeout
HTML='''<!doctype html><title>Dynamic fixture</title><main><h1>Dynamic record</h1><p>This synthetic record is intentionally long enough to be extracted after its delayed data has finished loading. It contains no account or private data.</p><div id="async"></div><a id="next" href="/next">Open another page</a><button id="refresh" onclick="load()">Refresh data</button><div id="frame"></div></main><script>async function load(){const response=await fetch('/data');document.querySelector('#async').textContent=await response.text();document.querySelector('#async').dataset.ready='yes'}setTimeout(()=>{load();const frame=document.createElement('iframe');frame.src='/frame';document.querySelector('#frame').append(frame)},1000)</script>'''
requests=[]
class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  requests.append(self.path)
  body='Dynamic API data is loaded successfully.' if self.path=='/data' else '<p>Embedded page loaded</p>' if self.path=='/frame' else '<main><h1>Another page loads normally</h1><a id=return href="/record?tab=comments#comments">Return</a></main>' if self.path=='/next' else HTML
  encoded=body.encode();self.send_response(200);self.send_header('Content-Type','text/plain' if self.path=='/data' else 'text/html; charset=utf-8');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
 def log_message(self,*args):pass
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
 proc=subprocess.Popen([os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),'--headless=new',f'--user-data-dir={root/"chrome"}',f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 cancelled=threading.Event();confirmed=threading.Event();waiting=threading.Event();results=[];errors=[];worker=None
 try:
  for _ in range(100):
   try:session=browser_reader.debug_info(f'http://127.0.0.1:{port}');break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('Temporary Chrome did not start')
  session.update(process=proc,confirmed=True)
  target=f'http://127.0.0.1:{server.server_port}/record?tab=comments#comments'
  def notify(state,message):
   if state=='waiting_login':waiting.set()
  def read():
   try:results.append(web_reader.read(target,root/'profile',notify,cancelled,login_complete=confirmed,background=True,close_new_tabs=False,language='en'))
   except browser_reader.CaptureCancelled:pass
   except Exception as error:errors.append(str(error))
  with patch.object(web_reader,'browser_proxy',return_value=None),patch.object(web_reader,'validate_public_url',side_effect=lambda url:url),patch.object(browser_reader,'start_or_reuse_browser',return_value=session):
   worker=threading.Thread(target=read);worker.start();assert waiting.wait(10),'Capture did not wait for confirmation'
   with sync_playwright() as pw:
    browser=pw.chromium.connect_over_cdp(session['websocket']);page=next(page for page in browser.contexts[0].pages if page.url==target)
    page.wait_for_selector('#async[data-ready="yes"]',timeout=5000);page.frame_locator('iframe').get_by_text('Embedded page loaded').wait_for(timeout=5000)
    assert '/data' in requests and '/frame' in requests and worker.is_alive()
    page.locator('#next').click();page.get_by_text('Another page loads normally').wait_for();page.locator('#return').click();page.wait_for_selector('#async[data-ready="yes"]',timeout=5000)
    before=requests.count('/data');confirmed.set();page.locator('#refresh').click()
    deadline=time.monotonic()+4
    while requests.count('/data')==before and time.monotonic()<deadline:page.wait_for_timeout(100)
    assert requests.count('/data')>before,'API must still work while extraction is running'
    worker.join(10);assert not worker.is_alive() and not errors,errors
    assert len(results)==1 and 'Dynamic API data is loaded successfully.' in results[0]['text'] and results[0]['url']==target
    print('PASS: API/iframe loading during confirmation wait, normal user navigation, API refresh during extraction, loaded-text capture, original query/fragment, no accounts or AI calls.')
 finally:
  cancelled.set()
  if worker:worker.join(5)
  proc.terminate();proc.wait(timeout=15);server.shutdown();server.server_close()
