import hashlib,json,os,shutil,signal,socket,sys,tarfile,tempfile,unittest
from pathlib import Path
from secretary.update_transaction import run


class UpdateRetentionTest(unittest.TestCase):
    def test_success_keeps_rollback_and_logs_and_leaves_newer_downloads(self):
        from secretary.update_retention import cache_artifacts, remove_artifacts
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            rollback={}
            packages={}
            logs=[]
            for version in ('0.1.9','0.1.10','0.1.11'):
                work=data/'updates'/version
                work.mkdir(parents=True)
                rollback[version]=work/('previous-program-'+'a'*32)
                rollback[version].mkdir()
                packages[version]=work/f'Stellar-Secretary-{version}-windows-x64-setup.exe'
                packages[version].touch()
                log=work/'installer.log'
                log.touch()
                logs.append(log)
            untouched=data/'updates'/'0.1.9'/'user-file.zip'
            untouched.touch()
            keep=rollback['0.1.10']
            removed=remove_artifacts(cache_artifacts(data,'0.1.10',keep_backup=keep))
            self.assertCountEqual(removed,[rollback['0.1.9'],packages['0.1.9'],packages['0.1.10']])
            for path in [*logs,keep,rollback['0.1.11'],packages['0.1.11'],untouched]:
                self.assertTrue(path.exists())


class WindowsRollbackTest(unittest.TestCase):
    def exercise(self,persistent):
        from unittest.mock import Mock,patch
        from secretary import update_transaction as transaction
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'D'/'Stellar Secretary';root.mkdir(parents=True)
            data=base/'D'/'知识库';data.mkdir()
            work=data/'updates';work.mkdir()
            backup=work/'previous-program';backup.mkdir()
            executable=root/'Stellar Secretary.exe';executable.write_bytes(b'new')
            (backup/executable.name).write_bytes(b'old')
            (data/'archive.sqlite3').write_bytes(b'library must stay intact')
            package=work/'setup.exe';package.write_bytes(b'installer')
            (work/'proceed').touch()
            launches=[];attempts=0
            rename=Path.rename
            def locked_rename(source,destination):
                nonlocal attempts
                if source==root:
                    attempts+=1
                    if persistent or attempts<3:
                        error=PermissionError('fixture sharing violation');error.winerror=32
                        raise error
                return rename(source,destination)
            def spawn(command,**kwargs):
                if command[0]==str(package):return Mock(wait=Mock(return_value=5))
                launches.append(command)
                return Mock(pid=12)
            config=dict(root=str(root),backup=str(backup),executable=str(executable),package=str(package),
                        sha=hashlib.sha256(package.read_bytes()).hexdigest(),version='new',old_version='old',
                        data=str(data),work=str(work),kind='windows',parent=0,args=['--data-dir',str(data)])
            with patch('secretary.windows_update_files.release'),patch.object(Path,'rename',locked_rename), \
                 patch.object(transaction,'spawn',side_effect=spawn),patch.object(transaction,'healthy',return_value=True), \
                 patch.object(transaction.time,'sleep'):
                self.assertFalse(run(config))
            launched=Path(launches[0][0])
            self.assertEqual(launched.read_bytes(),b'old')
            self.assertEqual(launches[0][1:],config['args'])
            self.assertEqual((data/'archive.sqlite3').read_bytes(),b'library must stay intact')
            result=json.loads((data/'update-result.json').read_text())
            self.assertEqual(result['phase'],'error' if persistent else 'rolled_back')
            self.assertTrue((backup/executable.name).exists())
            if persistent:
                self.assertEqual(attempts,25)
                self.assertIn(str(launched.parent),result['error'])
                self.assertTrue((launched.parent/'.stellar-recovery').exists())
            else:
                self.assertEqual(attempts,3)
                self.assertEqual(launched,executable)

    def test_transient_directory_lock_restores_original_installation(self):self.exercise(False)
    def test_persistent_directory_lock_launches_recovery_copy(self):self.exercise(True)

    @unittest.skipUnless(os.name=='nt','Requires Windows directory sharing modes')
    def test_native_directory_lock_keeps_a_runnable_recovery_copy(self):
        import ctypes
        from unittest.mock import patch
        from secretary.update_transaction import restore_windows_program
        from secretary.windows_update_files import kernel
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'Stellar Secretary';backup=base/'previous-program'
            root.mkdir();backup.mkdir()
            executable='Stellar Secretary.exe'
            (root/executable).write_bytes(b'failed version')
            (backup/executable).write_bytes(b'previous version')
            api=kernel()
            handle=api.CreateFileW(str(root),0x80000000,3,None,3,0x02000000,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                with patch('secretary.update_transaction.time.sleep'):
                    recovered,reason=restore_windows_program(root,backup)
                self.assertNotEqual(recovered,root)
                self.assertTrue(reason)
                self.assertEqual((recovered/executable).read_bytes(),b'previous version')
                self.assertEqual((root/executable).read_bytes(),b'failed version')
            finally:api.CloseHandle(handle)

class AtomicStatusTest(unittest.TestCase):
    def test_mac_update_helper_keeps_app_bundle_suffix(self):
        from unittest.mock import Mock, patch
        from secretary import paths, update_transaction
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            app=base/'Stellar Secretary.app'
            executable=app/'Contents/MacOS/Stellar Secretary'
            executable.parent.mkdir(parents=True)
            executable.touch()
            work=base/'library/updates/new'
            work.mkdir(parents=True)
            def spawn(command, **kwargs):
                copied=Path(command[0])
                self.assertEqual(copied.parents[2].suffix,'.app')
                self.assertTrue(copied.is_file())
                (work/'worker-ready').touch()
                return Mock()
            with patch.object(paths,'FROZEN',True),patch.object(paths,'DATA_DIR',base/'library'), \
                 patch.object(sys,'executable',str(executable)),patch.object(sys,'argv',['stellar','--data-dir=relative','--port','8771']), \
                 patch.object(update_transaction,'spawn',side_effect=spawn):
                self.assertTrue(update_transaction.prepare(base/'release.dmg',work,'sha','new',kind='mac'))
            self.assertTrue((work/'proceed').is_file())
            config=json.loads((work/'transaction.json').read_text(encoding='utf-8'))
            self.assertEqual(config['args'],['--port','8771','--data-dir',str((base/'library').resolve())])

    def test_windows_reader_lock_retries_and_publishes_complete_json(self):
        from unittest.mock import patch
        from secretary.update_transaction import atomic
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.json';path.write_text('{"phase":"old"}')
            original=Path.replace;attempts=[]
            def replace(source,target):
                attempts.append(source)
                if len(attempts)<3:
                    self.assertEqual(json.loads(path.read_text())['phase'],'old')
                    error=PermissionError('Synthetic Windows reader lock');error.winerror=5;raise error
                return original(source,target)
            with patch('secretary.update_transaction.sys.platform','win32'),patch.object(Path,'replace',replace),patch('secretary.update_transaction.time.sleep') as sleep:
                atomic(path,{'phase':'complete','message':'资料保留'})
            self.assertEqual(sleep.call_count,2);self.assertEqual(json.loads(path.read_text())['phase'],'complete')
            self.assertEqual(list(Path(root).iterdir()),[path])
            self.assertNotEqual(attempts[0].name,'state.json.tmp')

    def test_persistent_windows_lock_is_bounded_and_keeps_previous_status(self):
        from unittest.mock import patch
        from secretary.update_transaction import atomic
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.json';path.write_text('{"phase":"old"}')
            error=PermissionError('Synthetic persistent lock');error.winerror=32
            with patch('secretary.update_transaction.sys.platform','win32'),patch.object(Path,'replace',side_effect=error) as replace,patch('secretary.update_transaction.time.sleep'):
                with self.assertRaises(PermissionError):atomic(path,{'phase':'complete'})
            self.assertEqual(replace.call_count,20);self.assertEqual(json.loads(path.read_text())['phase'],'old')
            self.assertEqual(list(Path(root).iterdir()),[path])

    def test_other_errors_are_not_retried(self):
        from unittest.mock import patch
        from secretary.update_transaction import atomic
        with tempfile.TemporaryDirectory() as root:
            with patch.object(Path,'replace',side_effect=OSError('Synthetic disk error')),patch('secretary.update_transaction.time.sleep') as sleep:
                with self.assertRaises(OSError):atomic(Path(root)/'state.json',{})
            sleep.assert_not_called();self.assertEqual(list(Path(root).iterdir()),[])

@unittest.skipUnless(os.name=='posix','Real portable process transaction')
class UpdateTransactionTest(unittest.TestCase):
    def exercise(self,broken=False,wrong_version=False,rollback_broken=False):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            base=Path(temp);root=base/'Program';root.mkdir();(root/'_internal').mkdir();data=base/'data';data.mkdir();work=data/'updates';work.mkdir()
            (data/'retained.txt').write_text('Never restore or overwrite library data')
            script='''#!PYTHON
import argparse,json,os
from http.server import HTTPServer,BaseHTTPRequestHandler
from socketserver import TCPServer
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--data-dir');a=p.parse_args()
Path(a.data_dir,'fixture.pid').write_text(str(os.getpid()))
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  value={'application':'stellar-central-secretary','version':VERSION,'database_ok':True,'pid':os.getpid(),'data_dir':str(Path(a.data_dir).resolve())}
  raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
class S(HTTPServer):
 def server_bind(self):TCPServer.server_bind(self);self.server_name='127.0.0.1';self.server_port=self.server_address[1]
S(('127.0.0.1',a.port),H).serve_forever()
'''.replace('PYTHON',sys.executable)
            old=root/'Stellar Secretary';old.write_text("#!/bin/sh\n# 'old'\nexit 8\n" if rollback_broken else script.replace('VERSION',repr('old')));old.chmod(0o755)
            backup=base/'backup';shutil.copytree(root,backup)
            candidate=base/'candidate'/'Stellar-Secretary';candidate.mkdir(parents=True);(candidate/'_internal').mkdir();(candidate/'start.sh').write_text('#!/bin/sh\n')
            target=candidate/'Stellar Secretary';target.write_text('#!/bin/sh\nexit 7\n' if broken else script.replace('VERSION',repr('wrong' if wrong_version else 'new')));target.chmod(0o755)
            package=work/'candidate.tar.gz'
            with tarfile.open(package,'w:gz') as archive:archive.add(candidate,arcname='Stellar-Secretary')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            (work/'proceed').write_text('ready')
            config=dict(root=str(root),backup=str(backup),executable=str(old),package=str(package),sha=hashlib.sha256(package.read_bytes()).hexdigest(),version='new',old_version='old',data=str(data),work=str(work),kind='portable',parent=0,args=['--port',str(port),'--data-dir',str(data)],desktop=False,address=f'http://127.0.0.1:{port}',timeout=2)
            try:
                self.assertEqual(run(config),not (broken or wrong_version))
                result=json.loads((data/'update-result.json').read_text())
                self.assertEqual(result['phase'],'error' if rollback_broken else 'rolled_back' if broken or wrong_version else 'complete')
                if rollback_broken:self.assertIn('健康检查失败',result['error'])
                self.assertEqual((data/'retained.txt').read_text(),'Never restore or overwrite library data')
                self.assertIn("'old'" if broken or wrong_version else "'new'",old.read_text())
                self.assertTrue(backup.is_dir())
            finally:
                if (data/'fixture.pid').exists():
                    try:os.kill(int((data/'fixture.pid').read_text()),signal.SIGTERM)
                    except ProcessLookupError:pass
    def test_failed_recovery_is_reported_as_error(self):self.exercise(broken=True,rollback_broken=True)
    def test_success_keeps_old_program_until_health_passes(self):self.exercise()
    def test_failed_start_rolls_back_program_without_touching_data(self):self.exercise(broken=True)
    def test_wrong_version_rolls_back_even_if_process_serves_http(self):self.exercise(wrong_version=True)

class HealthModeTest(unittest.TestCase):
    def test_desktop_requires_loaded_window_but_browser_mode_is_intentional(self):
        import io
        from unittest.mock import patch,Mock
        from secretary.update_transaction import healthy
        with tempfile.TemporaryDirectory() as temp:
            config={'address':'http://127.0.0.1:1','data':temp,'desktop':True,'child_pid':123}
            value={'application':'stellar-central-secretary','version':'new','database_ok':True,'pid':123,'data_dir':temp,'desktop':{'supports_window':True,'window_loaded':False,'mode':'desktop'}}
            def check():
                opener=Mock();opener.open.return_value.__enter__=lambda *_:io.BytesIO(json.dumps(value).encode());opener.open.return_value.__exit__=lambda *_:None
                with patch('secretary.update_transaction.urllib.request.build_opener',return_value=opener):return healthy(config,'new')
            self.assertFalse(check());value['desktop']['mode']='browser';self.assertTrue(check())
            value['pid']=124;self.assertFalse(check())

    def test_windows_health_requires_interface_to_open(self):
        import io
        from unittest.mock import Mock,patch
        from secretary.update_transaction import healthy
        with tempfile.TemporaryDirectory() as temp:
            config={'address':'http://127.0.0.1:1','data':temp,'desktop':True,'kind':'windows','child_pid':123}
            desktop={'supports_window':True,'window_loaded':True,'window_visible':False,'mode':'desktop'}
            value={'application':'stellar-central-secretary','version':'new','database_ok':True,'pid':123,'data_dir':temp,'desktop':desktop}
            opener=Mock()
            opener.open.return_value.__enter__=lambda *_:io.BytesIO(json.dumps(value).encode())
            opener.open.return_value.__exit__=lambda *_:None
            with patch('secretary.update_transaction.urllib.request.build_opener',return_value=opener):
                self.assertFalse(healthy(config,'new'))
                desktop['window_visible']=True
                self.assertTrue(healthy(config,'new'))
                desktop.update(mode='browser',browser_opens=0)
                self.assertFalse(healthy(config,'new'))
                desktop['browser_opens']=1
                self.assertTrue(healthy(config,'new'))

    @unittest.skipUnless(os.name=='nt','Windows process handle')
    def test_windows_wait_does_not_terminate_parent(self):
        import subprocess,threading
        from secretary.update_transaction import open_windows_parent,wait_windows_parent
        with subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.buffer.read(); raise SystemExit(17)'],
                              stdin=subprocess.PIPE) as child:
            handle=open_windows_parent(child.pid)
            finished=threading.Event()
            def wait():
                wait_windows_parent(handle)
                finished.set()
            waiter=threading.Thread(target=wait,daemon=True)
            waiter.start()
            try:
                self.assertFalse(finished.wait(.3))
                self.assertIsNone(child.poll())
            finally:
                child.stdin.close()
                waiter.join(5)
                if child.poll() is None:child.kill()
            self.assertTrue(finished.is_set())
            self.assertEqual(child.wait(),17)
