"""Real Windows native/Chromium integration test with synthetic, isolated data."""
import argparse,base64,ctypes,json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.core import Archive

def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def main():
    if sys.platform!='win32':raise RuntimeError('This test needs a Windows desktop session')
    import websocket
    from playwright.sync_api import sync_playwright,expect
    parser=argparse.ArgumentParser();parser.add_argument('--source',action='store_true');args=parser.parse_args()
    port=free_port();debug_port=free_port();address=f'http://127.0.0.1:{port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory() as root:
        archive=Archive(root);archive.configure('codex',False);archive.set_language('en')
        item_id,_=archive.add('Synthetic Windows reference','Desktop and browser share this synthetic reference.')
        (Path(root)/'conversations.json').write_text(json.dumps({'conversations':[{'id':'shared-fixture','title':'Shared Windows history','updated':1,'messages':[{'id':'fixture-message','role':'user','text':'Shared Windows history fixture'}]}],'activeId':'shared-fixture'}),encoding='utf-8')
        command=[sys.executable,'-m','secretary.launcher'] if args.source else [str(Path('dist/Stellar Secretary/Stellar Secretary.exe').resolve())]
        common=['--desktop','--port',str(port),'--data-dir',root]
        env={**os.environ,'SECRETARY_DATA_DIR':root,'QTWEBENGINE_REMOTE_DEBUGGING':f'127.0.0.1:{debug_port}','QTWEBENGINE_CHROMIUM_FLAGS':f'--disable-gpu --remote-allow-origins=http://127.0.0.1:{debug_port}'}
        proc=subprocess.Popen(command+common+['--no-browser'],env=env);channel=None;serial=0
        def request(path,body=None):
            headers={'Content-Type':'application/json'}
            if body is not None:headers['X-Knowledge-Token']=status['token']
            req=urllib.request.Request(address+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            with opener.open(req,timeout=5) as response:return json.load(response)
        def wait(check,seconds=40):
            deadline=time.monotonic()+seconds;last=None
            while time.monotonic()<deadline:
                if proc.poll() is not None:raise RuntimeError('Native process exited unexpectedly')
                try:
                    last=check()
                    if last:return last
                except (OSError,ValueError,KeyError):pass
                time.sleep(.15)
            raise AssertionError('Native state timed out: '+repr(last))
        def rpc(method,params):
            nonlocal serial
            serial+=1;channel.send(json.dumps({'id':serial,'method':method,'params':params}))
            while True:
                value=json.loads(channel.recv())
                if value.get('id')!=serial:continue
                if value.get('error'):raise AssertionError(value['error'])
                return value.get('result',{})
        def js(expression):
            value=rpc('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
            if value.get('exceptionDetails'):raise AssertionError(value['exceptionDetails'])
            return value.get('result',{}).get('value')
        try:
            status=wait(lambda:(lambda value:value if value['desktop'].get('supports_window') else None)(request('/api/status')))
            assert status['desktop']['platform']=='windows'
            request('/api/interface',{'mode':'desktop'})
            status=wait(lambda:(lambda value:value if value['desktop'].get('window_visible') and value['desktop'].get('window_loaded') else None)(request('/api/status')))
            window_id=status['desktop']['window_id']
            def target():
                with opener.open(f'http://127.0.0.1:{debug_port}/json/list',timeout=3) as response:targets=json.load(response)
                return next((value for value in targets if value.get('type')=='page' and value.get('url','').startswith(address)),None)
            page=wait(target);channel=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=15,origin=f'http://127.0.0.1:{debug_port}')
            wait(lambda:js("document.querySelector('#model-label')?.textContent==='ChatGPT · Codex'"))
            wait(lambda:js("document.querySelector('#messages')?.textContent.includes('Shared Windows history fixture')"))
            js("document.querySelector('#settings-open').click();true")
            wait(lambda:js("!document.querySelector('#interface-toggle').hidden && document.querySelector('#interface-toggle').textContent==='Switch to browser mode'"))
            js("document.querySelector('#interface-toggle').click();true")
            status=wait(lambda:(lambda value:value if value['desktop'].get('mode')=='browser' and not value['desktop'].get('window_visible') else None)(request('/api/status')))
            assert status['settings']['interface_mode']=='browser' and status['desktop']['browser_opens']>=1
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                try:
                    browser_page=browser.new_page();browser_page.goto(address)
                    expect(browser_page.locator('#messages')).to_contain_text('Shared Windows history fixture',timeout=15000)
                    browser_page.locator('#settings-open').click();expect(browser_page.locator('#interface-toggle')).to_have_text('Switch to desktop mode')
                    browser_page.locator('#interface-toggle').click()
                    status=wait(lambda:(lambda value:value if value['desktop'].get('mode')=='desktop' and value['desktop'].get('window_visible') else None)(request('/api/status')))
                    assert status['desktop']['window_id']==window_id and status['settings']['interface_mode']=='desktop'
                    js("document.querySelector('#settings-dialog').close();true")
                    png=rpc('Page.captureScreenshot',{'format':'png'})['data'];folder=Path('test-results');folder.mkdir(exist_ok=True);(folder/('windows-desktop-source.png' if args.source else 'windows-desktop-frozen.png')).write_bytes(base64.b64decode(png))
                    from ctypes import wintypes
                    close=ctypes.windll.user32.PostMessageW;close.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];close.restype=wintypes.BOOL
                    assert close(window_id,0x0010,0,0)
                    wait(lambda:(lambda value:not value['desktop'].get('window_visible') or value['desktop'].get('window_minimized'))(request('/api/status')))
                    reopened=subprocess.Popen(command+common,env=env);assert reopened.wait(timeout=20)==0
                    status=wait(lambda:(lambda value:value if value['desktop'].get('window_visible') and not value['desktop'].get('window_minimized') else None)(request('/api/status')))
                    assert status['desktop']['window_id']==window_id
                    assert request('/api/items')[0]['id']==item_id
                    request('/api/shutdown',{});assert proc.wait(timeout=20)==0
                    print('PASS: real Windows desktop, Chromium UI, tray/taskbar lifecycle, settings switches desktop→browser→desktop, shared chat/library, close/relaunch reuses window, persistence and clean shutdown')
                finally:browser.close()
        finally:
            if channel:channel.close()
            if proc.poll() is None:
                try:request('/api/shutdown',{'force':True});proc.wait(timeout=10)
                except Exception:proc.kill();proc.wait()
            log=Path(root)/'app.log'
            if log.exists():print(log.read_text(encoding='utf-8'))

if __name__=='__main__':main()
