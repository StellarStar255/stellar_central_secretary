import os
from pathlib import Path
import unittest
from unittest.mock import patch

from secretary import paths, updater


class LinuxPackagingTests(unittest.TestCase):
    def test_frozen_data_uses_xdg_and_home_fallback(self):
        with patch.object(paths, 'FROZEN', True), patch.object(paths.sys, 'platform', 'linux'), patch.object(Path, 'home', return_value=Path('/test-home')):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(paths.data_dir(), Path('/test-home/.local/share/stellar-secretary'))
            with patch.dict(os.environ, {'XDG_DATA_HOME': '/test-xdg'}, clear=True):
                self.assertEqual(paths.data_dir(), Path('/test-xdg/stellar-secretary'))
            with patch.dict(os.environ, {'SECRETARY_DATA_DIR': '/override', 'XDG_DATA_HOME': '/test-xdg'}, clear=True):
                self.assertEqual(paths.data_dir(), Path('/override'))

    def test_linux_update_check_never_selects_windows_installer(self):
        with patch.object(updater, 'MAC', False), patch.object(updater, 'WINDOWS', False), patch.object(updater.sys, 'platform', 'linux'), patch.object(paths, 'FROZEN', True):
            self.assertIsNone(updater._asset_pattern().search('Stellar-Secretary-0.1.50-windows-x64-setup.exe'))
            self.assertIsNotNone(updater._asset_pattern().search('Stellar-Secretary-0.1.50-linux-x64.deb'))
            self.assertFalse(updater.supported())

    def test_linux_tls_uses_system_roots_and_preserves_override(self):
        with patch.object(paths, 'FROZEN', True), patch.object(paths.sys, 'platform', 'linux'), patch.object(Path, 'is_file', return_value=True):
            with patch.dict(os.environ, {}, clear=True):
                paths.configure_tls()
                self.assertEqual(os.environ['SSL_CERT_FILE'], '/etc/ssl/certs/ca-certificates.crt')
            with patch.dict(os.environ, {'SSL_CERT_FILE': '/custom-roots'}, clear=True):
                paths.configure_tls()
                self.assertEqual(os.environ['SSL_CERT_FILE'], '/custom-roots')
