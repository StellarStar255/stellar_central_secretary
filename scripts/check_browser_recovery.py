"""Restart a temporary Chrome and recover stale/missing connection records."""
import json,os,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import browser_reader as reader,browser_session,web_reader,capture_worker

class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  data=b'<main><h1>Recovery fixture</h1><p>This temporary page proves that content can be read after the browser restarts. It contains synthetic content only and does not use an account.</p></main>'
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass

with tempfile.TemporaryDirectory() as temp:
 profile=(Path(temp)/'profile with spaces').resolve();profile.mkdir();marker=profile/'fixture-marker.txt';marker.write_text('Preserve this profile')
 chrome=reader.chrome_executable();assert chrome
 sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close();endpoint='http://127.0.0.1:'+str(port)
 args=[chrome,'--headless=new','--user-data-dir='+str(profile),'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),'--no-first-run','--no-default-browser-check','about:blank']
 processes=[];real_popen=subprocess.Popen
 def launch():
  proc=real_popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);processes.append(proc)
  for _ in range(100):
   try:return proc,reader.debug_info(endpoint)
   except OSError:time.sleep(.1)
  raise RuntimeError('Fixture browser did not start')
 server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  original,first=launch();reader.save_session(profile,{**first,'confirmed':True});original.terminate();original.wait(timeout=15)
  current,fresh=launch();assert fresh['websocket']!=first['websocket']
  attempts=[]
  def monitor(command,*args,**kwargs):
   if command[0] in (chrome,'/usr/bin/open'):attempts.append(command)
   return real_popen(command,*args,**kwargs)
  with patch.object(reader.subprocess,'Popen',side_effect=monitor):
   recovered=reader.start_or_reuse_browser('about:blank#fixture',profile,threading.Event(),background=True)
   assert recovered['websocket']==fresh['websocket'] and not recovered['confirmed']
   (profile/'.reader-session.json').unlink()
   recovered=reader.start_or_reuse_browser('about:blank#fixture',profile,threading.Event(),background=True)
   assert recovered['websocket']==fresh['websocket'] and not attempts,'must reuse the live owned browser'
  assert marker.read_text()=='Preserve this profile'
  assert {p['pid'] for p in browser_session.owned_processes(profile,chrome)}=={current.pid}
  confirmation=threading.Event()
  def notify(state,message):
   if state=='waiting_login':confirmation.set()
  target=f'http://127.0.0.1:{server.server_port}/record'
  with patch.object(web_reader,'validate_public_url',side_effect=lambda url:url),patch.object(web_reader,'browser_proxy',return_value=None):
   result=web_reader.read(target,profile,notify,threading.Event(),login_complete=confirmation,background=True,close_new_tabs=True,language='en')
  if '--frozen' in sys.argv:
   reader.save_session(profile,{**first,'confirmed':True})
   confirmation.clear()
   binary=str(Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary').resolve())
   with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',binary):
    frozen=capture_worker.run('web','https://www.python.org/',profile,notify,threading.Event(),confirmation,background=True,close_new_tabs=True,language='en')
   assert 'Python' in frozen['text']
   assert {p['pid'] for p in browser_session.owned_processes(profile,chrome)}=={current.pid}
   print('PASS: frozen capture worker recovered the restarted browser and extracted a public page without another browser instance')
  assert 'Recovery fixture' in result['text'] and marker.read_text()=='Preserve this profile'
  print('PASS: actual Chrome restart, changed websocket nonce, missing connection record, exact profile with spaces, no duplicate browser launch, persistent profile preserved and real DOM text read after recovery; no accounts or AI calls')
 finally:
  for proc in processes:
   if proc.poll() is None:proc.terminate();proc.wait(timeout=15)
  server.shutdown();server.server_close()
