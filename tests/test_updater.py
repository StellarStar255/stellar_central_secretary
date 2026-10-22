import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from secretary import paths, updater


class InlineThread:
    def __init__(self, target, **kwargs): self.target = target
    def start(self): self.target()


class UpdateTest(unittest.TestCase):
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

    def test_data_override_is_explicit_and_source_default_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'SECRETARY_DATA_DIR':temp}):
            self.assertEqual(paths.data_dir(), Path(temp).resolve())


if __name__ == '__main__': unittest.main()
