"""Synthetic rich document, shadow DOM and visible-frame extraction regression."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import web_reader
from playwright.sync_api import sync_playwright
PUBLISHED='Published record: synthetic project update, discussion decisions and next steps. This is a saved document paragraph, not a comment draft.'
DOC='''<!doctype html><title>Example rich document</title><main style="display:contents"><div class="zone-container" contenteditable="true" role="document" aria-busy="true"><div class="ace-line" data-block-id="first">'''+PUBLISHED+'''</div><div class="ace-line" data-block-id="second">Another published paragraph contains the final decision and a follow-up action for the next review.</div><div class="comment-editor" contenteditable="true" aria-label="Comment"><div data-block-id="draft-one">UNSUBMITTED COMMENT SECRET</div><div data-block-id="draft-two">SECOND DRAFT SECRET</div></div><div role="progressbar">Saving</div></div><textarea>TEXTAREA SECRET</textarea><div contenteditable="true">GENERIC DRAFT SECRET</div><div contenteditable="plaintext-only">PLAIN DRAFT SECRET</div><div hidden>HIDDEN SECRET</div></main>'''
FRAME='''<!doctype html><title>Embedded document</title><main><iframe src="/document" width="900" height="550"></iframe><iframe src="/hidden" width="900" height="550" style="display:none"></iframe><iframe src="/small" width="20" height="20"></iframe></main>'''
SHADOW='''<!doctype html><title>Shadow document</title><main style="display:contents"><published-document></published-document></main><script>const root=document.querySelector('published-document').attachShadow({mode:'open'});root.innerHTML='<article role="document"><div style="display:contents"><p>'''+PUBLISHED+'''</p><p>The document is inside an open shadow root and its wrapper has no layout box.</p></div><div contenteditable="true">SHADOW DRAFT SECRET</div></article>'</script>'''
CLOCK='''<!doctype html><title>Updating document</title><main><article role="document"><p>'''+PUBLISHED*8+'''</p><span id="clock">revision 0</span><div role="progressbar">Saving</div></article></main><script>let revision=0;setInterval(()=>document.querySelector('#clock').textContent='revision '+(++revision),250)</script>'''
PROGRESS='''<!doctype html><title>Synthetic progress monitor</title><main aria-busy="true"><h1>进度监控</h1><p>示例模型 下载中</p><div role="progressbar" aria-valuenow="35"><span id="value">35.8%</span></div><p>48.0GB / 134.2GB 速度 23.5MB/s</p></main><script>let n=358;setInterval(()=>{document.querySelector('#value').textContent=((++n)%1000/10).toFixed(1)+'%';document.querySelector('[role=progressbar]').setAttribute('aria-valuenow',n/10)},20)</script>'''
class Fixture(BaseHTTPRequestHandler):
 def do_GET(self):
  value=DOC if self.path.startswith('/document') else FRAME if self.path=='/embedded' else SHADOW if self.path=='/shadow' else CLOCK if self.path=='/clock' else PROGRESS if self.path=='/progress' else '<main>HIDDEN FRAME SECRET AND UNRELATED CONTENT</main>'
  data=value.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
  try:
   page=browser.new_page()
   with patch.object(web_reader,'validate_public_url',side_effect=lambda url:url):
    for route in ('/document','/shadow','/embedded','/clock'):
     page.goto(base+route);page.wait_for_load_state('load')
     if route=='/document':page.locator('.zone-container').focus()
     snapshot=web_reader.snapshot_page(page,'en')
     assert PUBLISHED in snapshot['text'],(route,snapshot['text'])
     for secret in ('UNSUBMITTED COMMENT SECRET','SECOND DRAFT SECRET','TEXTAREA SECRET','GENERIC DRAFT SECRET','PLAIN DRAFT SECRET','HIDDEN SECRET','SHADOW DRAFT SECRET','HIDDEN FRAME SECRET'):
      assert secret not in snapshot['text'],(route,secret)
     result=web_reader.capture_loaded_page(page,base+route,threading.Event(),language='en',timeout=10)
     assert PUBLISHED in result['text'],route
     if route=='/embedded':assert 'visible embedded content' in result['text'] and snapshot['captured_frames']==1
     assert page.locator('textarea').count()==0 or page.locator('textarea').input_value()=='TEXTAREA SECRET','capture must not alter form values'
    # A short continuously changing dashboard must not wait for the indicator.
    page.goto(base+'/progress');snapshot=web_reader.snapshot_page(page,'zh')
    assert 0<snapshot['readable_characters']<80 and not snapshot['busy'] and snapshot['progress'],snapshot
    result=web_reader.capture_loaded_page(page,base+'/progress',threading.Event(),language='zh',timeout=1)
    assert '48.0GB / 134.2GB' in result['text'] and '23.5MB/s' in result['text'] and '文字快照' in result['text'] and result['capture_mode']=='text_snapshot'
    page.screenshot(path='/tmp/secretary-live-progress-snapshot.png')
    # Numbers alone are useful displayed text too, rather than a loading shell.
    page.set_content('<main><span role="progressbar">35.8%</span></main>')
    snapshot=web_reader.snapshot_page(page,'en');assert not snapshot['busy'] and snapshot['readable_characters']>0
    # A loading shell must not be accepted as a completed document.
    page.set_content('<main><div class="zone-container" contenteditable="true" aria-busy="true"><div role="progressbar">Loading...</div></div></main>')
    snapshot=web_reader.snapshot_page(page,'en');assert snapshot['busy'] and snapshot['readable_characters']<40
    # An article wrapper alone must not turn a login prompt into a document.
    page.set_content('<article><p>登录飞书，请先登录查看文档</p><button>登录</button></article>')
    snapshot=web_reader.snapshot_page(page,'en');assert snapshot['login'] and not snapshot['document']
   print('PASS: structured editable document, focused document, display:contents wrappers, open shadow DOM, visible same-origin iframe, hidden/small frame exclusion, comment/input/ordinary draft exclusion, short live progress snapshot, numeric-only progress, harmless live counter and saving spinner, loading-shell rejection; no accounts or AI calls')
  finally:browser.close()
finally:server.shutdown();server.server_close()
