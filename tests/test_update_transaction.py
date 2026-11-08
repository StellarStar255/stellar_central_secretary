import hashlib,json,os,shutil,signal,socket,sys,tarfile,tempfile,unittest
from pathlib import Path
from secretary.update_transaction import run

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
