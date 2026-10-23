"""Exercise the frozen server, static assets, archive and authenticated shutdown."""
import json
import base64
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tests'))
from pdf_fixture import pdf_bytes

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
binary = (Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary') if sys.platform == 'darwin'
          else Path('dist/Stellar Secretary/Stellar Secretary.exe')).resolve()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory() as data:
    proc = subprocess.Popen([str(binary), '--no-browser', '--port', str(port), '--data-dir', data],
                            env={**os.environ, 'SECRETARY_DATA_DIR': data})
    def request(path, body=None, token=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                                     data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type':'application/json', 'X-Knowledge-Token':token or ''})
        with opener.open(req, timeout=30 if path=='/api/update/check' else 3) as response:
            return response.read()
    try:
        for _ in range(60):
            if proc.poll() is not None: raise RuntimeError('Frozen app exited before startup')
            try:
                status = json.loads(request('/api/status'))
                break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('Frozen app did not start')
        for path in ('/', '/app.js', '/style.css', '/tutorial', '/tutorial.js', '/tutorial.css', '/i18n.js', '/i18n-data.js'):
            assert request(path), path
        assert b'tutorial-open' in request('/')
        request('/api/language',{'language':'en'},status['token'])
        assert json.loads(request('/api/status'))['settings']['ui_language']=='en'
        request('/api/language',{'language':'zh'},status['token'])
        request('/api/settings', {'backend':'codex', 'auto_ai':False, 'capture_scope':'loaded'}, status['token'])
        assert json.loads(request('/api/status'))['settings']['capture_scope'] == 'loaded'
        request('/api/ingest', {'text':'安装包测试资料，可供检索。'}, status['token'])
        assert len(json.loads(request('/api/items'))) == 1
        backup = request('/api/backup')
        imported = json.loads(request('/api/import', backup, status['token']))
        assert imported == {'imported': 0, 'skipped': 1, 'total': 1}, imported
        assert b'import-backup' in request('/')
        pdf = json.loads(request('/api/ingest', {'filename':'aes-fixture.pdf', 'data':base64.b64encode(pdf_bytes(password='')).decode()}, status['token']))['item']
        assert 'Encrypted PDF extraction fixture' in pdf['text'] and not pdf['error'], pdf
        for query in ('Encrypted%20readable','readable%20Encrypted'):
            matches=json.loads(request('/api/items?q='+query+'&kind=file'))
            assert [item['id'] for item in matches]==[pdf['id']], matches
        assert json.loads(request('/api/items?q=Encrypted%20nonexistent'))==[]
        reparsed = json.loads(request('/api/items/'+pdf['id']+'/reextract', {}, status['token']))
        assert reparsed['parsed'] and reparsed['item']['id'] == pdf['id'], reparsed
        if os.environ.get('SECRETARY_TLS_TEST') == '1':
            update = json.loads(request('/api/update/check', {}, status['token']))
            assert not update.get('error'), update
            print('PASS: frozen HTTPS update check with certificate verification enabled')
        request('/api/shutdown', {}, status['token'])
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log = Path(data)/'app.log'
        if log.exists(): print(log.read_text(encoding='utf-8'))
