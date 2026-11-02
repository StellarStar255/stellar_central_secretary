"""Real Ubuntu Qt/tray/dock lifecycle checks with isolated data and a local update feed."""
import argparse,base64,json,os,signal,socket,subprocess,sys,tempfile,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.core import Archive

def port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def main():
    if not sys.platform.startswith('linux'):raise SystemExit('Linux graphical session required')
    import websocket
    from playwright.sync_api import sync_playwright,expect
    parser=argparse.ArgumentParser();parser.add_argument('--source',action='store_true');parser.add_argument('--binary');args=parser.parse_args()
    folder=Path('test-results');folder.mkdir(exist_ok=True)
    manager=subprocess.Popen(['openbox','--sm-disable'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    tray_manager=subprocess.Popen(['stalonetray','--geometry','1x1+0+0','--icon-size','24','--window-type','dock'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    class Feed(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            value={'tag_name':'v99.0.0','assets':[{'name':'Stellar-Secretary-99.0.0-linux-x64'+suffix,'browser_download_url':'http://127.0.0.1/fixture'} for suffix in ('.deb','.tar.gz')]+[{'name':'SHA256SUMS.txt','browser_download_url':'http://127.0.0.1/sums'}]}
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    feed=ThreadingHTTPServer(('127.0.0.1',0),Feed);threading.Thread(target=feed.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='stellar-linux-ui-',ignore_cleanup_errors=True) as root:
            root=Path(root);archive=Archive(root);archive.configure('codex',False);archive.set_language('en')
            item,_=archive.add('Linux fixture','Shared desktop/browser library fixture')
            (root/'conversations.json').write_text(json.dumps({'conversations':[{'id':'fixture','title':'Shared Linux history','updated':1,'messages':[{'id':'message','role':'user','text':'Shared Linux history fixture'}]}],'activeId':'fixture'}))
            app_port,debug_port=port(),port();address=f'http://127.0.0.1:{app_port}'
            command=[sys.executable,'-c',"import faulthandler,runpy,signal; faulthandler.register(signal.SIGUSR1,all_threads=True); runpy.run_module('secretary.launcher',run_name='__main__')"] if args.source else [str(Path(args.binary or 'dist/Stellar Secretary/Stellar Secretary').resolve())]
            common=['--desktop','--port',str(app_port),'--data-dir',str(root)]
            browser_port=port();browser_profile=root/'system-browser';browser_wrapper=root/'open-browser'
            browser_wrapper.write_text('#!/bin/sh\nexec /usr/bin/google-chrome --no-sandbox --no-first-run --no-default-browser-check --disable-dev-shm-usage --user-data-dir='+str(browser_profile)+' --remote-debugging-port='+str(browser_port)+' \"$@\"\n');browser_wrapper.chmod(0o755)
            env={**os.environ,'BROWSER':str(browser_wrapper),'XDG_CURRENT_DESKTOP':'openbox','SECRETARY_DATA_DIR':str(root),'SECRETARY_UPDATE_API':f'http://127.0.0.1:{feed.server_port}/latest','QTWEBENGINE_REMOTE_DEBUGGING':f'127.0.0.1:{debug_port}','QTWEBENGINE_CHROMIUM_FLAGS':f'--disable-gpu --no-sandbox --disable-dev-shm-usage --remote-allow-origins=http://127.0.0.1:{debug_port}'}
            browser_profile.mkdir()
            applications=root/'xdg-data'/'applications';applications.mkdir(parents=True)
            config=root/'xdg-config';config.mkdir()
            (applications/'stellar-browser-probe.desktop').write_text('[Desktop Entry]\nType=Application\nName=Stellar browser launch probe\nExec='+str(browser_wrapper)+' %U\nMimeType=x-scheme-handler/http;x-scheme-handler/https;\n')
            env.update(XDG_DATA_HOME=str(applications.parent),XDG_CONFIG_HOME=str(config));env.pop('BROWSER',None)
            for scheme in ('http','https'):subprocess.run(['xdg-mime','default','stellar-browser-probe.desktop','x-scheme-handler/'+scheme],env=env,check=True)
            proc=subprocess.Popen(command+common+['--no-browser'],env=env);channel=None;serial=0;status={} 
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path,body=None):
                req=urllib.request.Request(address+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Knowledge-Token':status.get('token','')})
                with opener.open(req,timeout=5) as response:return json.load(response)
            def wait(check,seconds=45):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    if proc.poll() is not None:raise RuntimeError('Desktop process exited')
                    try:
                        value=check()
                        if value:return value
                    except (OSError,ValueError,KeyError):pass
                    time.sleep(.15)
                raise AssertionError('Desktop state timed out')
            def rpc(method,params):
                nonlocal serial
                serial+=1;channel.send(json.dumps({'id':serial,'method':method,'params':params}))
                while True:
                    reply=json.loads(channel.recv())
                    if reply.get('id')!=serial:continue
                    if reply.get('error'):raise AssertionError(reply['error'])
                    return reply.get('result',{})
            def js(expression):
                result=rpc('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                if result.get('exceptionDetails'):raise AssertionError(result['exceptionDetails'])
                return result.get('result',{}).get('value')
            def tray_action(index):
                tray_window=subprocess.check_output(['xdotool','search','--onlyvisible','--class','stalonetray'],text=True).splitlines()[0]
                subprocess.run(['xdotool','mousemove','--window',tray_window,'12','12','click','3'],check=True);time.sleep(.5)
                subprocess.run(['xdotool','key','Home',*(['Down']*(index+1)),'Return'],check=True)
            try:
                status=wait(lambda:(lambda s:s if s['desktop'].get('tray') else None)(request('/api/status')))
                assert status['desktop']['platform']=='linux'
                request('/api/interface',{'mode':'desktop'})
                status=wait(lambda:(lambda s:s if s['desktop'].get('window_visible') and s['desktop'].get('window_loaded') else None)(request('/api/status')))
                window=status['desktop']['window_id']
                wm=subprocess.check_output(['xprop','-id',str(window),'WM_CLASS'],text=True);assert 'stellar-secretary' in wm,wm
                def target():
                    with opener.open(f'http://127.0.0.1:{debug_port}/json/list') as response:pages=json.load(response)
                    return next((p for p in pages if p.get('type')=='page' and p.get('url','').startswith(address)),None)
                page=wait(target);channel=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=15,origin=f'http://127.0.0.1:{debug_port}')
                wait(lambda:js("document.querySelector('#messages')?.textContent.includes('Shared Linux history fixture')"))
                tray_action(2);wait(lambda:js("document.querySelector('#settings-dialog').open"))
                assert request('/api/status')['interface_request']['panel']=='settings'
                tray_action(3);wait(lambda:request('/api/update').get('latest')=='99.0.0')
                wait(lambda:js("document.querySelector('#update-status').textContent.includes('99.0.0')"))
                js("document.querySelector('#interface-toggle').click();true")
                status=wait(lambda:(lambda s:s if s['desktop']['mode']=='browser' and s['desktop']['window_minimized'] and s['desktop']['browser_opens'] else None)(request('/api/status')))
                assert status['desktop']['dock'] and status['desktop']['tray']
                def browser_opened():
                    with opener.open(f'http://127.0.0.1:{browser_port}/json/list',timeout=2) as response:return any(tab.get('url','').startswith(address) for tab in json.load(response))
                wait(browser_opened)
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True)
                    try:
                        tab=browser.new_page();tab.goto(address);expect(tab.locator('#messages')).to_contain_text('Shared Linux history fixture')
                        tab.locator('#settings-open').click();expect(tab.locator('#interface-toggle')).to_have_text('Switch to desktop mode');tab.locator('#interface-toggle').click()
                        wait(lambda:request('/api/status')['desktop']['mode']=='desktop')
                    finally:browser.close()
                js("document.querySelector('#settings-dialog').close();true")
                subprocess.run(['wmctrl','-ic',hex(window)],check=True);wait(lambda:request('/api/status')['desktop']['window_minimized'])
                reopened=subprocess.Popen(command+common,env=env);assert reopened.wait(timeout=20)==0
                wait(lambda:not request('/api/status')['desktop']['window_minimized'])
                assert request('/api/status')['desktop']['window_id']==window and request('/api/items')[0]['id']==item
                png=rpc('Page.captureScreenshot',{'format':'png'})['data'];(folder/('linux-desktop-source.png' if args.source else 'linux-desktop-frozen.png')).write_bytes(base64.b64decode(png))
                tray_action(6);assert proc.wait(timeout=20)==0
                channel.close();channel=None
                tray_manager.terminate();tray_manager.wait(timeout=5)
                proc=subprocess.Popen(command+common,env=env)
                status=wait(lambda:(lambda s:s if s['desktop'].get('window_loaded') and not s['desktop'].get('tray') else None)(request('/api/status')))
                window=status['desktop']['window_id']
                request('/api/interface',{'mode':'browser'})
                wait(lambda:request('/api/status')['desktop'].get('window_minimized'))
                subprocess.run(['wmctrl','-ia',hex(window)],check=True)
                wait(lambda:(lambda s:s['desktop']['mode']=='desktop' and not s['desktop']['window_minimized'])(request('/api/status')))
                subprocess.run(['xdotool','key','ctrl+q'],check=True);assert proc.wait(timeout=20)==0
                print('PASS: Linux native window, tray menu settings/updates/quit, dock identity and minimized recovery, desktop/browser switching, shared history/library, close and relaunch reuse, no-tray Dock restore and native quit')
            except BaseException:
                if args.source and proc.poll() is None:proc.send_signal(signal.SIGUSR1);time.sleep(.3)
                try:print('LAST DESKTOP STATUS:',request('/api/status'),flush=True)
                except Exception as error:print('STATUS UNAVAILABLE:',error,flush=True)
                subprocess.run(['xwininfo','-root','-tree'],check=False)
                screenshot=folder/('linux-desktop-source-failure.png' if args.source else 'linux-desktop-frozen-failure.png')
                subprocess.run([sys.executable,'-c',"from PySide6.QtWidgets import QApplication; from PySide6.QtGui import QGuiApplication; app=QApplication([]); QGuiApplication.primaryScreen().grabWindow(0).save("+repr(str(screenshot))+")"],check=False)
                raise
            finally:
                if channel:channel.close()
                if proc.poll() is None:
                    try:request('/api/shutdown',{'force':True});proc.wait(timeout=10)
                    except Exception:proc.kill();proc.wait()
                subprocess.run(['pkill','-f',str(browser_profile)],check=False)
                if (root/'app.log').exists():print((root/'app.log').read_text())
    finally:
        feed.shutdown();feed.server_close()
        for child in (tray_manager,manager):
            if child.poll() is None:child.terminate();child.wait(timeout=5)

if __name__=='__main__':main()
