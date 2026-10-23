"""Exercise real capture subprocess IPC, concurrency and hard cancellation."""
import json,os,sys,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import capture_worker,browser_reader
from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory() as temp:
 profile=Path(temp)/'profile';waiting=threading.Event();stop=threading.Event();errors=[]
 def notify_first(state,message):
  if state=='waiting_login':waiting.set()
 def first():
  try:capture_worker.run('web','https://www.python.org/',profile,notify_first,stop,threading.Event(),background=True,close_new_tabs=True,language='en')
  except browser_reader.CaptureCancelled:pass
  except Exception as error:errors.append(str(error))
 def exercise():
  thread=threading.Thread(target=first);thread.start()
  try:
   assert waiting.wait(50),'first capture did not reach confirmation'
   confirmation=threading.Event()
   def notify(state,message):
    if state=='waiting_login':confirmation.set()
   result=capture_worker.run('web','https://www.python.org/',profile,notify,threading.Event(),confirmation,background=True,close_new_tabs=True,language='en')
   assert 'Python' in result['text'] and result['url']=='https://www.python.org/';assert thread.is_alive(),'waiting capture should still be independent'
   started=time.monotonic();stop.set();thread.join(3);assert not thread.is_alive(),'stop must not wait for browser timeout'
   assert time.monotonic()-started<3;assert not errors,errors
   print('PASS: '+('frozen' if '--frozen' in sys.argv else 'source')+' worker IPC; shared browser startup; waiting page does not block capture; confirmed public webpage extracted; hard stop within 3 seconds')
  finally:
   stop.set();thread.join(4)
   session=profile/'.reader-session.json'
   if session.exists():
    with sync_playwright() as pw:
     browser=pw.chromium.connect_over_cdp(json.loads(session.read_text())['websocket'])
     session_cdp=browser.new_browser_cdp_session()
     pid=next(int(info['id']) for info in session_cdp.send('SystemInfo.getProcessInfo')['processInfo'] if info['type']=='browser')
     try:session_cdp.send('Browser.close')
     except Exception:pass
     deadline=time.monotonic()+8
     while time.monotonic()<deadline:
      try:os.kill(pid,0)
      except ProcessLookupError:break
      time.sleep(.1)
     else:raise RuntimeError('Temporary test browser did not exit')
 if '--frozen' in sys.argv:
  binary=str(Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary').resolve())
  with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',binary):exercise()
 else:exercise()
