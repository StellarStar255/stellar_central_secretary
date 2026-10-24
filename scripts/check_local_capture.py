"""Real local dynamic-page capture through source/frozen worker, without accounts."""
import json,os,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import browser_reader,capture_worker
from secretary.server import fetch_page

BODY='Synthetic selected conversation: the local training viewer has finished loading. Only this displayed conversation should be archived. '*3
requests=[]
class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  requests.append(self.path)
  text=BODY if self.path=='/data' else '''<!doctype html><title>Local conversation viewer</title><nav>OTHER CONVERSATION TITLES</nav><main><h1>Selected conversation</h1><article id="messages">Loading...</article><textarea>UNSENT LOCAL DRAFT</textarea></main><script>fetch('/data').then(r=>r.text()).then(t=>document.querySelector('#messages').textContent=t)</script>'''
  data=text.encode();self.send_response(200);self.send_header('Content-Type','text/plain' if self.path=='/data' else 'text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass

with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);profile=root/'browser';profile.mkdir()
 server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
 target=f'http://127.0.0.1:{server.server_port}/proxy/viewer?selected=example#latest'
 port=browser_reader.free_loopback_port()
 proc=subprocess.Popen([browser_reader.chrome_executable(),'--headless=new',f'--user-data-dir={profile}',f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1','--no-first-run','--no-default-browser-check','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  # Automatic server fetch must stay public-only, and must not contact the fixture.
  try:fetch_page(target)
  except ValueError:pass
  else:raise AssertionError('Server-side fetching unexpectedly accepted a local endpoint')
  assert not requests
  for _ in range(100):
   try:session=browser_reader.debug_info(f'http://127.0.0.1:{port}');break
   except OSError:time.sleep(.1)
  else:raise RuntimeError('Temporary headless Chrome did not start')
  browser_reader.save_session(profile,dict(session,confirmed=True))
  confirmation=threading.Event();states=[]
  def notify(state,message):
   states.append(state)
   if state=='waiting_login':confirmation.set()
  def exercise():
   result=capture_worker.run('web',target,profile,notify,threading.Event(),confirmation,background=True,close_new_tabs=True,language='en')
   assert 'waiting_login' in states and 'reading' in states
   assert result['url']==target and BODY.strip() in result['text']
   assert 'UNSENT LOCAL DRAFT' not in result['text'] and 'OTHER CONVERSATION TITLES' not in result['text']
   assert '/data' in requests
  if '--frozen' in sys.argv:
   binary=str(Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary').resolve())
   with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',binary):exercise()
  else:exercise()
  print('PASS: '+('frozen' if '--frozen' in sys.argv else 'source')+' worker captured confirmed loopback dynamic conversation; exact query/fragment; drafts excluded; automatic local fetch still blocked; no accounts or AI calls')
 finally:
  proc.terminate();proc.wait(timeout=15);server.shutdown();server.server_close()
