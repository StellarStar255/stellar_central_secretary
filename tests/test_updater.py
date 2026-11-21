import io
import os
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch
from secretary import paths, updater


class InlineThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()


class UpdateTest(unittest.TestCase):
    def test_frozen_mac_uses_system_ca_and_preserves_explicit_trust(self):
        with patch.object(paths,'FROZEN',True), patch.object(paths.sys,'platform','darwin'), patch.object(Path,'is_file',return_value=True):
            with patch.dict(os.environ,{},clear=True):
                paths.configure_tls()
                self.assertEqual(os.environ['SSL_CERT_FILE'],str(Path('/etc/ssl/cert.pem')))
            with patch.dict(os.environ,{'SSL_CERT_FILE':'/custom/trusted.pem'}):
                paths.configure_tls()
                self.assertEqual(os.environ['SSL_CERT_FILE'],'/custom/trusted.pem')

    def setUp(self):
        self.previous = updater.status()
        self.addCleanup(lambda: updater._set(**self.previous))

    def release(self, **changes):
        rel = {'tag_name':'v99.0.0', 'assets':[
            {'name':'Stellar-Secretary-99.0.0-macos-arm64.dmg', 'browser_download_url':'https://example.com/app'},
            {'name':'SHA256SUMS.txt', 'browser_download_url':'https://example.com/sums'}]}
        rel.update(changes)
        return io.BytesIO(json.dumps(rel).encode())

    def test_check_architecture_checksums_and_failure_clear_availability(self):
        with patch.object(updater, 'MAC', True), patch.object(updater.platform, 'machine', return_value='arm64'):
            with patch.object(updater, '_get', return_value=self.release()):
                self.assertTrue(updater.check()['available'])
            with patch.object(updater, '_get', return_value=self.release(assets=[])):
                self.assertFalse(updater.check()['available'])
            with patch.object(updater, '_get', side_effect=OSError('offline')):
                self.assertFalse(updater.check()['available'])
            with patch.object(updater, '_get', return_value=self.release(prerelease=True)):
                self.assertFalse(updater.check()['available'])

    def test_missing_checksum_and_mismatch_never_install_or_quit(self):
        for checksum in (None, '0'*64):
            with self.subTest(checksum=checksum), tempfile.TemporaryDirectory() as temp:
                updater._set(available=True, phase='idle', latest='99.0.0', installer='https://example.com/app',
                             installer_name='app.dmg', sums='https://example.com/sums')
                quit_app = Mock()
                with patch.object(updater, 'supported', return_value=True), patch.object(paths, 'DATA_DIR', Path(temp)), \
                     patch.object(updater.threading, 'Thread', InlineThread), \
                     patch.object(updater, '_download', side_effect=lambda url, dest: dest.write_bytes(b'bad')), \
                     patch.object(updater, '_expected_sha', return_value=checksum), \
                     patch.object(updater, '_mac_install') as install:
                    updater.start(quit_app)
                install.assert_not_called()
                quit_app.assert_not_called()
                self.assertEqual(updater.status()['phase'], 'error')

    def test_source_install_is_refused_and_bundle_detection_is_safe(self):
        with patch.object(updater, 'supported', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '安装版'): updater.start(Mock())
        self.assertFalse(updater._can_replace_in_place(None))
        self.assertFalse(updater._can_replace_in_place(Path('/Volumes/Installer/Test.app')))

    def test_windows_recovery_copy_reports_original_directory_and_opens_only_update_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            data = root / 'library'
            log = data / 'updates' / '99.0.0' / 'installer.log'
            log.parent.mkdir(parents=True)
            log.touch()
            copy = root / ('Stellar Secretary.restore-' + 'a' * 32)
            copy.mkdir()
            (copy / '.stellar-recovery').touch()
            state = data / 'windows-update.json'
            state.write_text(json.dumps({'phase': 'error', 'error': 'WinError 32', 'version': '99.0.0'}))
            updater._set(phase='idle', error=None)
            with patch.object(updater, 'WINDOWS', True), patch.object(paths, 'DATA_DIR', data), \
                 patch.object(paths, 'FROZEN', True), patch.object(updater.sys, 'executable', str(copy/'Stellar Secretary.exe')), \
                 patch.object(updater.os, 'startfile', create=True) as open_file:
                result = updater.status()
                self.assertIsNone(result['error'])
                self.assertEqual(result['recovery'], {'kind': 'copy', 'has_log': True,
                                                      'original_install_dir': str(root/'Stellar Secretary')})
                with self.assertRaisesRegex(ValueError, '修复原安装'):
                    updater.start(Mock())
                self.assertEqual(updater.open_windows_update_log(), {'ok': True})
                open_file.assert_called_once_with(str(log))
                outside_log = root / 'installer.log'
                outside_log.touch()
                state.write_text(json.dumps({'phase': 'error', 'installer_log': str(outside_log)}))
                self.assertFalse(updater.status()['recovery']['has_log'])
                with self.assertRaisesRegex(ValueError, '找不到更新日志'):
                    updater.open_windows_update_log()
                open_file.assert_called_once()

    def test_windows_previous_installation_rollback_keeps_regular_update_available(self):
        with patch.object(updater, 'WINDOWS', True), patch.object(updater, '_windows_recovery_copy', return_value=None), \
             patch('secretary.windows_update.last_result', return_value={'phase': 'rolled_back'}):
            updater._set(phase='idle', error=None)
            result = updater.status()
            self.assertEqual(result['recovery']['kind'], 'rolled_back')
            self.assertIsNone(result['error'])

    def test_install_endpoint_releases_service_lock_and_defers_backup(self):
        from secretary.server import Service, handler
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            service.desktop['enabled'] = True
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler(service))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            address = f'http://127.0.0.1:{server.server_port}'
            with urlopen(address+'/api/status', timeout=3) as response:
                token = json.load(response)['token']
            request = Request(address+'/api/update/install', data=b'{}', headers={
                'Content-Type': 'application/json', 'X-Knowledge-Token': token})
            native_status = service.desktop_status
            def require_unlocked_status():
                self.assertFalse(service.lock.locked())
                return native_status()
            try:
                with patch.object(service, 'desktop_status', side_effect=require_unlocked_status), \
                     patch.object(service.backups, 'create') as backup, patch.object(updater, 'start') as start:
                    with urlopen(request, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                    self.assertIs(start.call_args.kwargs['desktop'], True)
                    backup.assert_not_called()
                    start.call_args.kwargs['before_install']()
                    backup.assert_called_once_with('upgrade')
                    service.busy.add('active-summary')
                    with self.assertRaisesRegex(ValueError, '请等待'):
                        start.call_args.kwargs['before_install']()
                    with self.assertRaisesRegex(ValueError, '请等待'):
                        start.call_args.kwargs['before_handoff']()
            finally:
                server.shutdown()
                server.server_close()
                service.close()

    def test_mac_handoff_uses_the_release_checksum(self):
        with patch.object(updater, '_can_replace_in_place', return_value=True), \
             patch('secretary.update_transaction.prepare', return_value=True) as prepare:
            updater._set(latest='99.0.0')
            self.assertTrue(updater._mac_install(Path('app.dmg'), Path('work'), 'a'*64))
            prepare.assert_called_once_with(Path('app.dmg'), Path('work'), 'a'*64, '99.0.0', desktop=True, kind='mac', before_handoff=None)

    def test_data_override_is_explicit_and_source_default_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'SECRETARY_DATA_DIR':temp}):
            self.assertEqual(paths.data_dir(), Path(temp).resolve())

    def test_windows_prefers_writable_secondary_drive_for_new_library(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            legacy=base/'system'/'Stellar Secretary'
            secondary=base/'secondary'
            blocked=base/'blocked'
            blocked.touch()
            with patch.object(paths,'_windows_metadata',return_value=legacy), \
                 patch.object(paths,'_windows_fixed_drives',return_value=[blocked,secondary]):
                self.assertEqual(paths._windows_data_dir(),secondary/'Stellar Secretary Data'/Path.home().name)
                legacy.mkdir(parents=True)
                (legacy/'archive.sqlite3').touch()
                self.assertEqual(paths._windows_data_dir(),legacy)
            with patch.object(paths,'_windows_metadata',return_value=base/'fresh-system'), \
                 patch.object(paths,'_windows_fixed_drives',return_value=[blocked]):
                self.assertEqual(paths._windows_data_dir(),base/'fresh-system')

    def test_windows_remembers_explicit_library_over_legacy_default(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            legacy=base/'system'
            legacy.mkdir()
            (legacy/'archive.sqlite3').touch()
            custom=base/'custom library'
            with patch.object(paths,'_windows_metadata',return_value=legacy), \
                 patch.object(paths.sys,'platform','win32'),patch.object(paths,'FROZEN',True):
                paths.remember_windows_data_dir(custom)
                self.assertEqual(paths._windows_data_dir(),custom.resolve())


if __name__ == '__main__': unittest.main()
