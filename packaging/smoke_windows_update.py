"""Real installed Windows app -> verified setup -> automatic relaunch, isolated data."""
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import __version__
from secretary.core import Archive


def main():
    if sys.platform != 'win32':raise RuntimeError('Requires Windows')
    setup=Path(f'dist/Stellar-Secretary-{__version__}-windows-x64-setup.exe').resolve()
    sha=hashlib.sha256(setup.read_bytes()).hexdigest()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='stellar-update-',ignore_cleanup_errors=True) as temp:
        root=Path(temp);install=root/'安装 test';data=root/'资料 test';assets=root/'assets';assets.mkdir()
        logs=Path('test-results/windows-update');logs.mkdir(parents=True,exist_ok=True)
        # Serve synthetic release metadata; the installer itself remains real and checksum verified.
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/release':
                    self.send_response(200);self.end_headers()
                    self.wfile.write(json.dumps({'tag_name':'v99.0.0','assets':[
                        {'name':'Stellar-Secretary-99.0.0-windows-x64-setup.exe','browser_download_url':url+'/setup.exe'},
                        {'name':'SHA256SUMS.txt','browser_download_url':url+'/SHA256SUMS.txt'}]}).encode());return
                if self.path=='/setup.exe':
                    self.send_response(200);self.send_header('Content-Length',str(setup.stat().st_size));self.end_headers()
                    with setup.open('rb') as source:
                        import shutil
                        shutil.copyfileobj(source,self.wfile)
                    return
                super().do_GET()
        server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(assets)))
        url=f'http://127.0.0.1:{server.server_port}'
        (assets/'SHA256SUMS.txt').write_text(sha+'  Stellar-Secretary-99.0.0-windows-x64-setup.exe\n')
        threading.Thread(target=server.serve_forever,daemon=True).start()
        initial=subprocess.run([str(setup),'/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',f'/DIR={install}',f'/LOG={logs.resolve()/"initial.log"}'],timeout=180)
        assert initial.returncode==0,initial.returncode
        exe=install/'Stellar Secretary.exe'
        asset=install/'_internal/secretary/static/index.html'
        original=hashlib.sha256(asset.read_bytes()).hexdigest()
        asset.write_bytes(asset.read_bytes()+b'\n<!-- old installation probe -->')
        archive=Archive(data);archive.configure('codex',False)
        item_id,_=archive.add('Windows update fixture','Preserve this local reference during update.')
        with archive.db() as db:before=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')]
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        address=f'http://127.0.0.1:{port}'
        env=dict(os.environ,SECRETARY_UPDATE_API=url+'/release')
        proc=subprocess.Popen([str(exe),'--desktop','--no-browser','--port',str(port),'--data-dir',str(data)],env=env)
        status={}
        def request(path,body=None):
            req=urllib.request.Request(address+path,data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json','X-Knowledge-Token':status.get('token','')})
            with opener.open(req,timeout=3) as response:return json.load(response)
        def wait(check,seconds=120):
            deadline=time.monotonic()+seconds;last=None
            while time.monotonic()<deadline:
                try:
                    last=check()
                    if last:return last
                except (OSError,ValueError,KeyError):pass
                time.sleep(.25)
            raise AssertionError('Windows update timed out: '+repr(last))
        try:
            def native_status():
                value=request('/api/status')
                return value if value['desktop'].get('supports_window') else None
            status=wait(native_status)
            assert status['desktop']['platform']=='windows'
            assert request('/api/update/check',{})['available']
            request('/api/update/install',{})
            def original_exited():
                if proc.poll() is not None:return True
                update=request('/api/status')['update']
                if update['phase']=='error':raise AssertionError('Update failed: '+str(update['error']))
                return False
            wait(original_exited,180)
            assert proc.returncode==0,'Original application failed to exit'
            status=wait(lambda:request('/api/status'),240)
            wait(lambda:request('/api/status')['desktop'].get('supports_window'))
            result=data/'windows-update.json'
            wait(lambda:result.exists() and json.loads(result.read_text(encoding='utf-8-sig')).get('phase')=='rolled_back',180)
            assert b'old installation probe' in asset.read_bytes(),'Version mismatch did not restore previous program'
            status=wait(native_status)
            # Exercise the same frozen worker with the real expected version.
            from unittest.mock import patch
            from secretary import paths,update_transaction
            work=data/'updates'/'positive';work.mkdir(parents=True)
            pid=request('/api/update/health')['pid']
            argv=[str(exe),'--no-browser','--port',str(port),'--data-dir',str(data)]
            with patch.object(paths,'DATA_DIR',data),patch.object(paths,'FROZEN',True),patch.object(sys,'executable',str(exe)),patch.object(sys,'argv',argv):
                update_transaction.prepare(setup,work,sha,__version__,desktop=True,kind='windows',parent_pid=pid)
            request('/api/shutdown',{})
            wait(lambda:result.exists() and json.loads(result.read_text(encoding='utf-8-sig')).get('phase')=='complete',180)
            status=wait(native_status)
            assert status['version']==__version__,status.get('version')
            assert Path(status['data_dir']).resolve()==data.resolve()
            assert hashlib.sha256(asset.read_bytes()).hexdigest()==original,'Installer did not replace existing files'
            with archive.db() as db:after=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')]
            assert before==after,'Archived item columns changed'
            assert request('/api/items')[0]['id']==item_id
            request('/api/shutdown',{})
            wait(lambda:not listening(address))
            print('PASS: real Windows updater download/checksum, detached helper, clean desktop exit, Inno in-place install, native automatic restart, custom port/Unicode paths and every item column preserved')
        finally:
            for source in (data/'app.log',data/'update.log',data/'windows-update.json',data/'updates/99.0.0/installer.log',data/'updates/99.0.0/helper.log'):
                if source.exists():(logs/source.name).write_bytes(source.read_bytes())
            try:request('/api/shutdown',{'force':True})
            except OSError:pass
            if proc.poll() is None:proc.kill();proc.wait()
            server.shutdown();server.server_close()


def listening(address):
    try:
        with urllib.request.urlopen(address+'/api/status',timeout=1):return True
    except OSError:return False


if __name__=='__main__':main()
