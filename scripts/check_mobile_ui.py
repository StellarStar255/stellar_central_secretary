"""Validate desktop pairing controls against an isolated HTTPS companion."""
import json,os,secrets,ssl,sys,tempfile,threading,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
class FixtureServer(ThreadingHTTPServer):request_queue_size=128
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 server=FixtureServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();enable=service.mobile.enable
 try:
  with patch('secretary.mobile.addresses',return_value=['127.0.0.1']),patch.object(service.mobile,'enable',side_effect=lambda:enable(bind='127.0.0.1',advertise=False)),sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#settings-open').click();page.locator('#mobile-open').click();expect(page.locator('#mobile-state')).to_have_text('手机连接已关闭')
   page.locator('#mobile-enable').click();expect(page.locator('#mobile-qr')).to_be_visible();expect(page.locator('#mobile-state')).to_have_text('手机连接已开启')
   manager=service.mobile;credential=secrets.token_urlsafe(48);context=ssl.create_default_context(cafile=str(manager.root/'certificate.pem'));context.check_hostname=False
   http=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
   body={'secret':manager.invite['secret'],'name':'Fixture iPhone','credential':credential};url='https://127.0.0.1:'+str(manager.server.server_port)
   with http.open(urllib.request.Request(url+'/pair',data=json.dumps(body).encode()),timeout=5) as r:pending=json.load(r)
   expect(page.locator('#mobile-pending')).to_contain_text(pending['code']);expect(page.locator('#mobile-pending')).to_contain_text('Fixture iPhone')
   page.locator('[data-approve]').click();expect(page.locator('#mobile-devices')).to_contain_text('Fixture iPhone')
   assert manager.device(credential)
   page.screenshot(path='/tmp/stellar-mobile-desktop.png')
   page.locator('[data-revoke]').click();expect(page.locator('#mobile-devices')).to_contain_text('尚未配对手机');assert manager.device(credential) is None
   page.locator('#mobile-disable').click();expect(page.locator('#mobile-state')).to_have_text('手机连接已关闭');expect(page.locator('#mobile-qr')).not_to_be_visible()
   page.locator('#mobile-dialog .dialog-head button').click();page.locator('#ui-language').select_option('en');page.locator('#mobile-open').click();expect(page.locator('#mobile-state')).to_have_text('Phone connection is off')
   page.set_viewport_size({'width':390,'height':844});assert page.locator('#mobile-dialog').bounding_box()['width']<=390
   assert not errors,errors;browser.close()
  print('PASS: opt-in desktop mobile controls, QR, matching approval digits, device revocation, disable, language and narrow layout')
 finally:server.shutdown();server.server_close();service.mobile.stop(disable=True);service.close()
