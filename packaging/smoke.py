"""Exercise the frozen server, static assets, archive and authenticated shutdown."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

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
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type':'application/json', 'X-Knowledge-Token':token or ''})
        with opener.open(req, timeout=3) as response:
            return response.read()
    try:
        for _ in range(60):
            if proc.poll() is not None: raise RuntimeError('Frozen app exited before startup')
            try:
                status = json.loads(request('/api/status'))
                break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('Frozen app did not start')
        for path in ('/', '/app.js', '/style.css'):
            assert request(path), path
        request('/api/settings', {'backend':'codex', 'auto_ai':False}, status['token'])
        request('/api/ingest', {'text':'安装包测试资料，可供检索。'}, status['token'])
        assert len(json.loads(request('/api/items'))) == 1
        request('/api/shutdown', {}, status['token'])
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log = Path(data)/'app.log'
        if log.exists(): print(log.read_text(encoding='utf-8'))
