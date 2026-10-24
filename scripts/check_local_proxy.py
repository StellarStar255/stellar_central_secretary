"""Real origin + loopback reverse proxy: navigation, empty responses and capture."""
import http.client,json,subprocess,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import web_reader,browser_reader,capture_worker
from playwright.sync_api import sync_playwright,Error

BODY='Synthetic conversation loaded through a local port forward. The displayed discussion and final result are readable after the proxy becomes ready. '*3
counts={}
HTML='''<!doctype html><title>Forwarded viewer</title><main><h1>Selected conversation</h1><article id="content">Loading...</article><textarea>UNSENT PROXY DRAFT</textarea></main><script>fetch('./data').then(r=>r.text()).then(t=>document.querySelector('#content').textContent=t)</script>'''
class Origin(BaseHTTPRequestHandler):
 def do_GET(self):
  route=self.path.split('?',1)[0];counts[route]=counts.get(route,0)+1
  if route=='/redirect':
   self.send_response(302);self.send_header('Location','./viewer');self.end_headers();return
  if route=='/empty' or route=='/transient' and counts[route]==1:
   self.send_response(204);self.end_headers();return
  data=(BODY if route=='/data' else '<script>location.replace("./viewer")</script>' if route=='/jump' else HTML).encode()
  self.send_response(503 if route=='/unavailable' else 200)
  self.send_header('Content-Type','text/plain' if route=='/data' else 'text/html; charset=utf-8')
  if route=='/download':self.send_header('Content-Disposition','attachment; filename=example.html')
  self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
origin=ThreadingHTTPServer(('127.0.0.1',0),Origin);threading.Thread(target=origin.serve_forever,daemon=True).start()
PREFIX='/session/proxy/viewer'
class Forward(BaseHTTPRequestHandler):
 def do_GET(self):
  connection=http.client.HTTPConnection('127.0.0.1',origin.server_port,timeout=5)
  try:
   connection.request('GET',self.path.removeprefix(PREFIX));response=connection.getresponse();self.send_response(response.status)
   for name,value in response.getheaders():
    if name.lower() not in ('connection','server','date'):self.send_header(name,value)
   self.end_headers();self.wfile.write(response.read())
  except OSError:pass
  finally:connection.close()
 def log_message(self,*args):pass
forward=ThreadingHTTPServer(('127.0.0.1',0),Forward);threading.Thread(target=forward.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{forward.server_port}'+PREFIX
try:
 with tempfile.TemporaryDirectory() as temp:
  profile=Path(temp)/'chrome';profile.mkdir();port=browser_reader.free_loopback_port()
  proc=subprocess.Popen([browser_reader.chrome_executable(),'--headless=new',f'--user-data-dir={profile}',f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   for _ in range(100):
    try:session=browser_reader.debug_info(f'http://127.0.0.1:{port}');break
    except OSError:time.sleep(.1)
   else:raise RuntimeError('Temporary Chrome did not start')
   browser_reader.save_session(profile,dict(session,confirmed=True))
   with sync_playwright() as pw:
    browser=pw.chromium.connect_over_cdp(session['websocket']);context=browser.contexts[0]
    page=context.new_page()
    # Reproduce the original raw exception with a real proxy's HTTP 204.
    try:page.goto(base+'/empty',wait_until='domcontentloaded')
    except Error as error:assert 'ERR_ABORTED' in str(error),str(error)
    else:raise AssertionError('Expected the original ERR_ABORTED failure')
    page.close()
    for route,message in (('/empty','204'),('/download','download'),('/unavailable','503')):
     page=context.new_page()
     try:web_reader.open_capture_page(page,base+route,threading.Event(),'en')
     except RuntimeError as error:assert message in str(error).lower(),(route,str(error))
     else:raise AssertionError('Must not capture an empty, download or error response')
     finally:page.close()
   def exercise():
    for route in ('/viewer','/transient','/redirect','/jump'):
     confirmation=threading.Event()
     def notify(state,message):
      if state=='waiting_login':
       with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(session['websocket'])
        current=next(p for p in browser.contexts[0].pages if p.url.startswith(base))
        current.locator('#content').filter(has_text=BODY.strip()).wait_for(timeout=10000)
       confirmation.set()
     target=base+route+'?selected=example#latest'
     result=capture_worker.run('web',target,profile,notify,threading.Event(),confirmation,background=True,close_new_tabs=True,language='en')
     assert result['url']==target and BODY.strip() in result['text'] and 'UNSENT PROXY DRAFT' not in result['text']
    assert counts['/transient']==2,'Retry the aborted empty navigation once, then capture normally'
    for route,message in (('/empty','204'),('/download','download'),('/unavailable','503')):
     try:capture_worker.run('web',base+route,profile,lambda *_:None,threading.Event(),threading.Event(),background=True,close_new_tabs=True,language='en')
     except RuntimeError as error:assert message in str(error).lower(),(route,str(error))
     else:raise AssertionError('Worker must not save an empty, download or error response')
   if '--frozen' in sys.argv:
    binary=str(Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary').resolve())
    with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',binary):exercise()
   else:exercise()
   print('PASS: '+('frozen' if '--frozen' in sys.argv else 'source')+' origin + loopback port forward; reproduced ERR_ABORTED on HTTP 204; transient retry recovered; confirmed same-origin redirect captured; dynamic body captured; persistent 204/download/503 rejected; drafts excluded; no accounts or AI calls')
  finally:proc.terminate();proc.wait(timeout=15)
finally:forward.shutdown();forward.server_close();origin.shutdown();origin.server_close()
