"""Real installed Windows app -> verified setup -> automatic relaunch, isolated data."""
import functools
import ctypes
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
    test_drive=Path('D:/') if os.environ.get('GITHUB_ACTIONS')=='true' and Path('D:/').is_dir() else None
    with tempfile.TemporaryDirectory(prefix='stellar-update-',dir=test_drive,ignore_cleanup_errors=True) as temp:
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
        from secretary.local_backups import Backups
        backup_dir=root/'custom snapshots'/'Stellar Secretary Backups'
        Backups(archive).configure({'folder':str(backup_dir)})
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
            assert 'Desktop shutdown: disposing browser profile' in (data/'app.log').read_text(encoding='utf-8'), 'Upgrade bypassed orderly desktop shutdown'
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
            wait(lambda:request('/api/status')['desktop'].get('window_visible'))
            assert Path(status['data_dir']).resolve()==data.resolve()
            assert Path(status['backup']['folder']).resolve()==backup_dir.resolve()
            assert any(backup_dir.glob('*.zip')),'Upgrade backup did not use the custom backup directory'
            assert hashlib.sha256(asset.read_bytes()).hexdigest()==original,'Installer did not replace existing files'
            with archive.db() as db:after=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')]
            assert before==after,'Archived item columns changed'
            assert request('/api/items')[0]['id']==item_id
            request('/api/shutdown',{})
            wait(lambda:not listening(address))
            # Reproduce the reported resource-only lock, with no app executable lock.
            # Direct installer invocation also covers handoffs from older releases.
            fixture_dir=install/'_internal'/'update-lock-fixture';fixture_dir.mkdir(exist_ok=True)
            fixture_source=root/'Lock.cs';fixture_source.write_text('using System;using System.IO;using System.Threading;class Lock {static void Main(string[] a){using(var f=new FileStream(a[0],FileMode.Open,FileAccess.Read,FileShare.Read)){File.WriteAllText(a[1],"ready");Thread.Sleep(Timeout.Infinite);}}}')
            fixture_exe=fixture_dir/'QtWebEngineProcess.exe';compiler=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler),'/nologo','/out:'+str(fixture_exe),str(fixture_source)],check=True,capture_output=True)
            snapshot=install/'_internal/PySide6/resources/v8_context_snapshot.bin';ready=root/'locked-ready'
            holder=subprocess.Popen([str(fixture_exe),str(snapshot),str(ready)])
            try:
                wait(lambda:ready.exists(),15)
                try:snapshot.unlink()
                except PermissionError:pass
                else:raise AssertionError('Expected a real Windows sharing violation')
                locked=subprocess.run([str(setup),'/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS','/LOGCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS',f'/LOG={logs.resolve()/"locked-resource.log"}'],timeout=180)
                assert locked.returncode==0,locked.returncode
                holder.wait(timeout=10);assert snapshot.exists()
                print('PASS: real Inno installer releases orphan WebEngine v8 snapshot lock, including legacy handoff path')
            finally:
                if holder.poll() is None:holder.terminate();holder.wait(timeout=10)

            # A direct silent upgrade without /DIR or an update helper should
            # reuse the registered path and reopen the app itself.
            manual_address='http://127.0.0.1:8768'
            assert not listening(manual_address)
            manual_env={**env,'SECRETARY_DATA_DIR':str(data)}
            try:
                manual=subprocess.run([str(setup),'/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                                       f'/LOG={logs.resolve()/"manual-relaunch.log"}'],env=manual_env,timeout=180)
                assert manual.returncode==0,manual.returncode
                def manual_window():
                    with opener.open(manual_address+'/api/status',timeout=3) as response:
                        value=json.load(response)
                    return value if value['desktop'].get('window_visible') and value['desktop'].get('window_loaded') else None
                reopened=wait(manual_window)
                assert Path(reopened['data_dir']).resolve()==data.resolve()
                assert Path(reopened['backup']['folder']).resolve()==backup_dir.resolve()
                print('PASS: direct silent upgrade reopens the existing installation and library')
            finally:
                try:
                    with opener.open(manual_address+'/api/status',timeout=3) as response:
                        current=json.load(response)
                    assert Path(current['data_dir']).resolve()==data.resolve()
                    closing=urllib.request.Request(manual_address+'/api/shutdown',data=b'{}',
                        headers={'Content-Type':'application/json','X-Knowledge-Token':current['token']})
                    opener.open(closing,timeout=5).close()
                except OSError:pass

            wait(lambda:not listening(manual_address))
            # Use a deterministic exit-code fixture alongside the real Inno tests above.
            # The sharing violation and the frozen worker and recovery window are native.
            failure_source=root/'InstallerFailure.cs'
            failure_source.write_text('class InstallerFailure {static int Main(){return 5;}}')
            failure_setup=root/'InstallerFailure.exe'
            subprocess.run([str(compiler),'/nologo','/out:'+str(failure_setup),str(failure_source)],check=True,capture_output=True)
            failure_sha=hashlib.sha256(failure_setup.read_bytes()).hexdigest()
            probe=install/'before-locked-update.txt'
            probe.write_text('unchanged previous installation')
            from secretary.windows_update_files import image,kernel
            api=kernel()
            # FILE_SHARE_READ | FILE_SHARE_WRITE, with no FILE_SHARE_DELETE.
            directory_handle=api.CreateFileW(str(install),0x80000000,3,None,3,0x02000000,None)
            if directory_handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            locked_work=data/'updates'/'persistent-lock';locked_work.mkdir(parents=True)
            try:
                try:install.rename(root/'unexpected-directory-rename')
                except OSError as error:assert error.winerror in (5,32,33),error
                else:raise AssertionError('Expected a native directory lock')
                with patch.object(paths,'DATA_DIR',data),patch.object(paths,'FROZEN',True),patch.object(sys,'executable',str(exe)),patch.object(sys,'argv',argv):
                    update_transaction.prepare(failure_setup,locked_work,failure_sha,'99.0.1',desktop=True,kind='windows',parent_pid=0)
                def locked_result():
                    info=json.loads(result.read_text(encoding='utf-8-sig'))
                    return info if info.get('phase')=='error' and info.get('version')=='99.0.1' else None
                final=wait(locked_result,180)
                assert '退出码 5' in final['error'] and '已从恢复副本启动旧版' in final['error'],final
                status=wait(native_status)
                wait(lambda:request('/api/status')['desktop'].get('window_visible') and request('/api/status')['desktop'].get('window_loaded'))
                active_pid=request('/api/update/health')['pid']
                active_handle=api.OpenProcess(0x1000,False,active_pid)
                assert active_handle,active_pid
                try:active=image(api,active_handle)
                finally:api.CloseHandle(active_handle)
                assert active and active.parent.name.startswith(install.name+'.restore-'),active
                assert active.parent.parent==install.parent and (active.parent/'.stellar-recovery').is_file(),active
                assert (active.parent/probe.name).read_bytes()==probe.read_bytes()
                assert status['version']==__version__ and Path(status['data_dir']).resolve()==data.resolve()
                assert Path(status['backup']['folder']).resolve()==backup_dir.resolve()
                with archive.db() as db:after=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')]
                assert before==after,'Recovery modified archived items'
                assert request('/api/items')[0]['id']==item_id
                print(f'PASS: native lock at {install.drive}, installer exit 5, visible recovery window, original library and custom backup path')
                request('/api/shutdown',{})
                wait(lambda:not listening(address))
            finally:
                api.CloseHandle(directory_handle)
                for name in ('transaction.log','relaunch.log'):
                    source=locked_work/name
                    if source.exists():(logs/('locked-'+name)).write_bytes(source.read_bytes())

            print('PASS: real Windows updater download/checksum, detached helper, clean desktop exit, Inno in-place install, native automatic restart, custom port/Unicode paths and every item column preserved')
        finally:
            for source in (data/'app.log',data/'update.log',data/'windows-update.json',data/'updates/99.0.0/installer.log',data/'updates/99.0.0/helper.log',data/'updates/99.0.0/transaction.log',data/'updates/99.0.0/relaunch.log'):
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
