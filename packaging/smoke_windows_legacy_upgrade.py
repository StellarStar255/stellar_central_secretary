"""Upgrade a copy of a published Windows installation through its own updater."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secretary.core import Archive
from secretary.update_transaction import open_windows_parent, wait_windows_parent


# Acquire a real sharing lock after the published updater's file-open probe
# has passed. The installer gets a short period to observe and retry it.
LOCK_RESOURCE = """
using System;
using System.IO;
using System.Threading;
class LockResource {
    static void Main(string[] args) {
        while (!File.Exists(args[1])) Thread.Sleep(5);
        using (var file = new FileStream(args[0], FileMode.Open, FileAccess.Read, FileShare.Read)) {
            File.WriteAllText(args[2], "ready");
            Thread.Sleep(8000);
        }
    }
}
"""


def wait(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise AssertionError(f'Timed out waiting for {check.__name__}')


def run(root, legacy_dir, setup, version, logs):
    install = root / '旧版程序 test'
    data = root / '原知识库 test'
    shutil.copytree(legacy_dir, install, ignore=shutil.ignore_patterns(
        'unins*.exe', 'unins*.dat', 'log', '.stellar-installed-version'))
    exe = install / 'Stellar Secretary.exe'
    archive = Archive(data)
    archive.configure('codex', False)
    item, _ = archive.add('Published Windows update fixture', 'Preserve this knowledge base.')
    records = [data / name for name in ('windows-update.json', 'update-result.json')]
    old_log = data / 'updates' / '0.1.148' / 'installer.log'
    old_log.parent.mkdir(parents=True)
    old_log.write_text('DeleteFile failed; code 32.', encoding='utf-8')

    def seed_failure():
        failure = dict(phase='error', error='Legacy installer failed with exit code 5',
                       version='0.1.148', updated=time.time(), installer_log=str(old_log))
        for record in records:
            record.write_text(json.dumps(failure), encoding='utf-8')
        return failure

    seed_failure()
    with setup.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    name = f'Stellar-Secretary-{version}-windows-x64-setup.exe'

    class Releases(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/setup.exe':
                self.send_response(200)
                self.send_header('Content-Length', str(setup.stat().st_size))
                self.end_headers()
                with setup.open('rb') as stream:
                    shutil.copyfileobj(stream, self.wfile)
                return
            if self.path == '/release':
                content = json.dumps({'tag_name': 'v' + version, 'assets': [
                    {'name': name, 'browser_download_url': release_url + '/setup.exe'},
                    {'name': 'SHA256SUMS.txt', 'browser_download_url': release_url + '/sums'},
                ]}).encode()
            elif self.path == '/sums':
                content = f'{sha}  {name}\n'.encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    release = ThreadingHTTPServer(('127.0.0.1', 0), Releases)
    release_url = f'http://127.0.0.1:{release.server_port}'
    threading.Thread(target=release.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    address = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    env = dict(os.environ, SECRETARY_UPDATE_API=release_url + '/release')
    args = [str(exe), '--desktop', '--port', str(port), '--data-dir', str(data)]

    def request(path, body=None, token=''):
        req = urllib.request.Request(address + path, json.dumps(body).encode() if body is not None else None,
                                     {'Content-Type': 'application/json', 'X-Knowledge-Token': token})
        with opener.open(req, timeout=4) as response:
            return json.load(response)

    def ready(expected):
        health = request('/api/update/health')
        desktop = health['desktop']
        if (health['version'] == expected and health['database_ok']
                and desktop.get('window_loaded') and desktop.get('window_visible')):
            current = request('/api/status')
            assert Path(current['data_dir']).resolve() == data.resolve()
            return current

    def shutdown():
        current = request('/api/status')
        assert Path(current['data_dir']).resolve() == data.resolve()
        handle = open_windows_parent(request('/api/update/health')['pid'])
        try:
            request('/api/shutdown', {}, current['token'])
        finally:
            if handle is not None:
                wait_windows_parent(handle)

    source = root / 'LockResource.cs'
    source.write_text(LOCK_RESOURCE, encoding='ascii')
    fixture = root / 'LockResource.exe'
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/out:' + str(fixture), str(source)], check=True)
    snapshot = install / '_internal/PySide6/resources/v8_context_snapshot.bin'
    installer_log = data / 'updates' / version / 'installer.log'
    locked = root / 'locked'
    holder = None
    old = subprocess.Popen(args, env=env)
    try:
        status = wait(lambda: ready('0.1.148'))
        assert 'Legacy installer failed' in status['update']['error']
        holder = subprocess.Popen([str(fixture), str(snapshot), str(installer_log), str(locked)])
        assert request('/api/update/check', {}, status['token'])['available']
        request('/api/update/install', {}, status['token'])

        def old_exited():
            if old.poll() is not None:
                return True
            update = request('/api/update')
            if update['phase'] == 'error':
                raise AssertionError(update['error'])

        wait(old_exited)
        assert old.wait(timeout=180) == 0
        wait(locked.exists, 40)
        try:
            snapshot.unlink()
        except PermissionError as error:
            assert error.winerror == 32, error
        else:
            raise AssertionError('Expected the snapshot lock to prevent DeleteFile')
        assert holder.wait(timeout=20) == 0

        def upgraded():
            result = json.loads(records[0].read_text(encoding='utf-8-sig'))
            if result.get('version') == version and result['phase'] in ('error', 'rolled_back'):
                raise AssertionError(result['error'])
            if result['phase'] == 'complete':
                return ready(version)

        wait(upgraded, 240)
        log = installer_log.read_bytes().decode('utf-8-sig', errors='replace')
        assert 'Waiting for old WebEngine resource handles to close' in log
        assert 'Moved old WebEngine resources aside' in log and snapshot.is_file()
        assert request('/api/items')[0]['id'] == item
        print(f'PASS: published 0.1.148 upgraded to {version} after a real Windows error 32 on the old WebEngine snapshot', flush=True)
        failure = seed_failure()
        assert 'Legacy installer failed' in request('/api/update')['error']
        shutdown()

        manual_log = logs / 'legacy-manual-reinstall.log'
        subprocess.run([str(setup), '/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        '/NORESTARTAPPLICATIONS', f'/DIR={install}', f'/LOG={manual_log}'],
                       check=True, timeout=240)
        subprocess.Popen(args, env=env)
        status = wait(lambda: ready(version))
        assert not status['update'].get('error') and not status['update'].get('recovery'), status['update']
        assert not request('/api/update').get('error')
        assert request('/api/items')[0]['id'] == item
        assert all(json.loads(record.read_text(encoding='utf-8')) == failure for record in records)
        assert old_log.read_text(encoding='utf-8') == 'DeleteFile failed; code 32.'
        print('PASS: manual reinstall dismissed the stale warning after health verification and preserved the records', flush=True)
    finally:
        if holder is not None and holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=10)
        try:
            shutdown()
        except OSError:
            pass
        if old.poll() is None:
            old.terminate()
            old.wait(timeout=10)
        release.shutdown()
        release.server_close()
        for source in (data / 'app.log', data / 'updates' / version / 'installer.log',
                       data / 'updates' / version / 'relaunch.log', *records):
            if source.is_file():
                shutil.copy2(source, logs / ('legacy-' + source.name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-install', required=True, type=Path)
    parser.add_argument('--setup', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--work-root', type=Path, help='Short writable path for the published updater’s rollback copy')
    args = parser.parse_args()
    logs = Path('test-results/windows-update').resolve()
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ss-upgrade-', dir=args.work_root, ignore_cleanup_errors=True) as directory:
        run(Path(directory), args.legacy_install.resolve(), args.setup.resolve(), args.version, logs)


if __name__ == '__main__':
    main()
