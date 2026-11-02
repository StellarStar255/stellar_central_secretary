import json,os,signal,socket,subprocess,sys,tarfile,tempfile,time,unittest,urllib.request
from pathlib import Path


@unittest.skipUnless(os.name=='posix','Portable update helpers use POSIX processes')
class PortableUpdateTransactionTest(unittest.TestCase):
    def exercise(self,broken):
        with tempfile.TemporaryDirectory(prefix='stellar-update-test-',ignore_cleanup_errors=True) as temp:
            root=Path(temp);current=root/"Program's files";current.mkdir();(current/'_internal').mkdir()
            data=root/'data';data.mkdir();(data/'retained.txt').write_text('User material remains outside the application')
            work=data/'updates';work.mkdir()
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            def app(version):
                return '''#!/usr/bin/env python3
import argparse,json,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--data-dir');args=p.parse_args()
Path(args.data_dir,'fixture.pid').write_text(str(os.getpid()))
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  raw=json.dumps({'application':'stellar-central-secretary','fixture':VERSION}).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
'''.replace('VERSION',repr(version))
            executable=current/'Stellar Secretary';executable.write_text(app('old'));executable.chmod(0o755)
            new=root/'candidate'/'Stellar-Secretary';(new/'_internal').mkdir(parents=True)
            (new/'Stellar Secretary').write_text('#!/bin/sh\nexit 7\n' if broken else app('new'));(new/'Stellar Secretary').chmod(0o755)
            (new/'start.sh').write_text('#!/bin/sh\n');(new/'start.sh').chmod(0o755)
            archive=work/'update.tar.gz'
            with tarfile.open(archive,'w:gz') as out:out.add(new,arcname='Stellar-Secretary')
            worker='''from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,@@REPOSITORY@@)
from secretary import linux_update,paths
paths.DATA_DIR=Path(@@DATA@@)
sys.executable=@@EXECUTABLE@@
sys.argv=[@@EXECUTABLE@@,'--port',@@PORT@@,'--data-dir',@@DATA@@,'--no-browser']
with patch.object(linux_update,'install_kind',return_value='portable'):
 linux_update.install(Path(@@ARCHIVE@@),Path(@@WORK@@),'0'*64,'99.0.0')
'''
            for key,value in {'REPOSITORY':str(Path(__file__).resolve().parent.parent),'DATA':str(data),'EXECUTABLE':str(executable),'PORT':str(port),'ARCHIVE':str(archive),'WORK':str(work)}.items():worker=worker.replace('@@'+key+'@@',repr(value))
            process=subprocess.Popen([sys.executable,'-c',worker],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            output,error=process.communicate(timeout=15);self.assertEqual(process.returncode,0,error)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));value=None
            try:
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/status',timeout=.5) as response:value=json.load(response)
                        break
                    except OSError:time.sleep(.1)
                log=(data/'update.log').read_text() if (data/'update.log').exists() else ''
                self.assertIsNotNone(value,log)
                self.assertEqual(value['fixture'],'old' if broken else 'new',log)
                self.assertEqual((data/'retained.txt').read_text(),'User material remains outside the application')
                if not broken:
                    deadline=time.monotonic()+5
                    while list(root.glob('.stellar-update-*')) and time.monotonic()<deadline:time.sleep(.1)
                    self.assertFalse(list(root.glob('.stellar-update-*')))
            finally:
                if (data/'fixture.pid').exists():
                    try:os.kill(int((data/'fixture.pid').read_text()),signal.SIGTERM)
                    except ProcessLookupError:pass

    def test_successful_atomic_replacement_relaunches_without_touching_data(self):self.exercise(False)
    def test_failed_replacement_restores_previous_program_and_relaunches_it(self):self.exercise(True)
