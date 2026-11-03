"""Real Chrome navigation through isolated HTTP and SOCKS5 fixture proxies."""
import socketserver,struct,tempfile,threading,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import browser_reader,network
from playwright.sync_api import sync_playwright,expect
BODY=b'<!doctype html><main>Browser proxy fixture reached successfully</main>'
seen=[]
def exact(sock,n):
 value=b''
 while len(value)<n:
  chunk=sock.recv(n-len(value))
  if not chunk:raise EOFError()
  value+=chunk
 return value

def response(sock):sock.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '+str(len(BODY)).encode()+b'\r\nConnection: close\r\n\r\n'+BODY)
class HTTP(socketserver.StreamRequestHandler):
 def handle(self):
  self.request.settimeout(5)
  try:
   line=self.rfile.readline(8192)
   while self.rfile.readline(8192) not in (b'\r\n',b''):pass
   if b'http://fixture.proxy.test/' in line:seen.append(('http',line));response(self.request)
   else:self.request.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
  except (OSError,EOFError):pass
class SOCKS(socketserver.BaseRequestHandler):
 def handle(self):
  sock=self.request;sock.settimeout(5)
  try:
   version,count=exact(sock,2);assert version==5;exact(sock,count);sock.sendall(b'\x05\x00')
   version,command,_,kind=exact(sock,4)
   host=exact(sock,exact(sock,1)[0]).decode() if kind==3 else exact(sock,4 if kind==1 else 16).hex()
   port=struct.unpack('!H',exact(sock,2))[0]
   if host!='fixture.proxy.test':sock.sendall(b'\x05\x04\x00\x01'+b'\x00'*6);return
   seen.append(('socks5',host,port));sock.sendall(b'\x05\x00\x00\x01'+b'\x00'*6)
   request=b''
   while b'\r\n\r\n' not in request:request+=exact(sock,1)
   response(sock)
  except (OSError,EOFError,AssertionError):pass
class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True

def main():
 chrome=browser_reader.chrome_executable();assert chrome,'Install Chrome to run this check'
 original=browser_reader.subprocess.Popen
 def launch(command,*args,**kwargs):
  if command[0]==chrome:command=[command[0],'--headless=new','--disable-gpu','--no-sandbox',*command[1:]]
  return original(command,*args,**kwargs)
 for scheme,handler in [('http',HTTP),('socks5',SOCKS)]:
  server=Server(('127.0.0.1',0),handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with tempfile.TemporaryDirectory(prefix='stellar-proxy-browser-') as folder:
    route=network.capture_proxy_route({'mode':'custom','url':f'{scheme}://127.0.0.1:{server.server_address[1]}'})
    with patch.object(browser_reader.subprocess,'Popen',side_effect=launch):session=browser_reader.start_or_reuse_browser('http://fixture.proxy.test/view',Path(folder),threading.Event(),proxy=route)
    try:
     with sync_playwright() as pw:
      browser=pw.chromium.connect_over_cdp(session['websocket']);page=browser.contexts[0].new_page();page.goto('http://fixture.proxy.test/view',wait_until='domcontentloaded');expect(page.locator('main')).to_have_text('Browser proxy fixture reached successfully')
      try:browser_reader.start_or_reuse_browser('about:blank',Path(folder),threading.Event(),proxy='direct://')
      except RuntimeError as error:assert '关闭专用浏览器' in str(error)
      else:raise AssertionError('Changed proxy must never silently reuse an old route')
      browser.new_browser_cdp_session().send('Browser.close')
    finally:
     proc=session['process']
     try:proc.wait(timeout=10)
     except Exception:proc.terminate();proc.wait(timeout=5)
    assert any(row[0]==scheme for row in seen)
    print('PASS: real Chrome through '+scheme+', session route persisted, changed route refuses silent reuse')
  finally:server.shutdown();server.server_close()
if __name__=='__main__':main()
