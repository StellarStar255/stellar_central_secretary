"""Opt-in macOS frozen-app test with a real Cocoa event loop and isolated data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0)); port=sock.getsockname()[1]
binary=Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary').resolve()
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory() as temp:
    proc=subprocess.Popen([str(binary), '--desktop', '--no-browser', '--port', str(port), '--data-dir', temp],
                          env={**os.environ,'SECRETARY_DATA_DIR':temp})
    try:
        for _ in range(80):
            if proc.poll() is not None:raise RuntimeError('Native app exited: '+(Path(temp)/'app.log').read_text())
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:status=json.load(response)
                if status['desktop'].get('state')=='ready':break
            except OSError:pass
            time.sleep(.25)
        else:raise RuntimeError('Native desktop did not become ready')
        desktop=status['desktop']
        assert desktop['menu_bar'] and desktop['dock'] and desktop['activation_policy']==0, desktop
        assert desktop['label']=='' and desktop['dock_badge']=='',desktop
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/interface',data=b'{"mode":"desktop"}',headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
        opener.open(request,timeout=3).close()
        for _ in range(120):
            with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:status=json.load(response)
            if status['desktop'].get('window_visible') and status['desktop'].get('window_loaded'):break
            time.sleep(.25)
        else:raise RuntimeError('Frozen WKWebView did not load: '+str(status['desktop']))
        assert status['settings']['interface_mode']=='desktop'
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/language',data=b'{"language":"en"}',headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
        opener.open(request,timeout=3).close()
        for _ in range(80):
            with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:status=json.load(response)
            if status['desktop'].get('language')=='en':break
            time.sleep(.25)
        else:raise RuntimeError('Native menu language did not change')
        assert status['settings']['ui_language']=='en'

        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/shutdown',data=b'{}',
                headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
        opener.open(request,timeout=3).close()
        assert proc.wait(timeout=15)==0
        print('PASS: frozen Cocoa menu bar, regular Dock application, loaded native WebKit window, persisted mode, English native menus and authenticated shutdown')
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        log=Path(temp)/'app.log'
        if log.exists():print(log.read_text())
