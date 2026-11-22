"""Exercise recovery in the Windows executable when a saved folder has no database."""
import ctypes
from ctypes import wintypes
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secretary.core import Archive


def wait_for(process, check, description):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Windows process exited while waiting for {description}: {process.returncode}')
        try:
            if value := check():
                return value
        except OSError:
            pass
        time.sleep(.15)
    raise RuntimeError(f'Timed out waiting for {description}')


def recovery_window(process):
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    for title in ('Recover library location', '恢复记忆目录'):
        window = user32.FindWindowW(None, title)
        if window and user32.IsWindowVisible(window):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == process.pid:
                return window
    return None


def retry(window):
    post = ctypes.windll.user32.PostMessageW
    post.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    post.restype = wintypes.BOOL
    assert post(window, 0x0100, 0x0D, 0x001C0001), 'Could not press Enter in the recovery dialog'
    assert post(window, 0x0101, 0x0D, 0xC01C0001), 'Could not release Enter in the recovery dialog'


def main():
    executable = Path('dist/Stellar Secretary/Stellar Secretary.exe').resolve(strict=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'

    def request(path, body=None, token=''):
        req = urllib.request.Request(base_url+path, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Knowledge-Token': token})
        with opener.open(req, timeout=2) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix='stellar-win-library-', ignore_cleanup_errors=True) as temp:
        root = Path(temp).resolve()
        library = root/'记忆目录'
        library.mkdir()
        fixture = Archive(root/'fixture')
        item, _ = fixture.add('Startup recovery fixture', 'The original record must survive.')
        settings = root/'Stellar Secretary Settings'
        settings.mkdir()
        preference = settings/'library-location.json'
        saved = json.dumps({'active': str(library)}).encode()
        preference.write_bytes(saved)
        env = {**os.environ, 'LOCALAPPDATA': str(root)}
        env.pop('SECRETARY_DATA_DIR', None)
        process = subprocess.Popen([str(executable), '--desktop', '--no-browser', '--port', str(port)], env=env)
        try:
            window = wait_for(process, lambda: recovery_window(process), 'missing-database recovery dialog')
            database = library/'archive.sqlite3'
            assert not database.exists()
            # Simulate restoring access to the original database while the dialog is open.
            with fixture.db() as source, closing(sqlite3.connect(database)) as destination:
                source.backup(destination)
            retry(window)

            def ready():
                status = request('/api/status')
                if status['desktop'].get('window_loaded') and status['desktop'].get('window_visible'):
                    return status

            status = wait_for(process, ready, 'loaded Windows desktop')
            assert Path(status['data_dir']) == library and not status['temporary_library']
            assert any(row['id'] == item for row in request('/api/items'))
            assert preference.read_bytes() == saved
            request('/api/shutdown', {}, status['token'])
            assert process.wait(timeout=20) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        print('PASS: packaged Windows startup recovered from a missing database and opened the original archive')


if __name__ == '__main__':
    main()
