import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from secretary import paths, updater, windows_update


class WindowsUpdateTest(unittest.TestCase):
    def test_handoff_preserves_install_location_arguments_and_resets_frozen_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();work = root/'更新 with spaces';work.mkdir()
            kernel = Mock();kernel.SetDllDirectoryW.return_value = 1
            def spawn(*args, **kwargs):
                (root/'windows-update.json').write_text('{"phase":"ready"}')
                return Mock()
            with patch.object(paths,'DATA_DIR',root), patch.object(windows_update.sys,'executable',str(root/'安装目录'/'Stellar Secretary.exe')), \
                 patch.object(windows_update.sys,'argv',['app','--port','9988','--desktop','--no-browser']), \
                 patch.object(windows_update.ctypes,'windll',Mock(kernel32=kernel),create=True), \
                 patch.dict(os.environ,{'SystemRoot':str(root/'Windows')}), \
                 patch.object(windows_update.subprocess,'DETACHED_PROCESS',8,create=True), \
                 patch.object(windows_update.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True), \
                 patch.object(windows_update.subprocess,'Popen',side_effect=spawn) as popen:
                self.assertTrue(windows_update.install(root/'setup.exe',work,'a'*64))
            config = json.loads((work/'install.json').read_text())
            self.assertEqual(config['exe'],str(root/'安装目录'/'Stellar Secretary.exe'))
            self.assertIn('--port 9988',config['arguments']);self.assertIn('--data-dir',config['arguments'])
            self.assertNotIn('--desktop',config['arguments']);self.assertIn('--no-browser',config['arguments'])
            self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            self.assertEqual(popen.call_args.kwargs['cwd'],str(work))
            self.assertTrue((work/'proceed').is_file())
            self.assertEqual(kernel.SetDllDirectoryW.call_count,2)

    def test_helper_failure_keeps_current_app_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);kernel=Mock();kernel.SetDllDirectoryW.return_value=1
            with patch.object(paths,'DATA_DIR',root), patch.object(windows_update.ctypes,'windll',Mock(kernel32=kernel),create=True), \
                 patch.dict(os.environ,{'SystemRoot':temp}), \
                 patch.object(windows_update.subprocess,'DETACHED_PROCESS',8,create=True), \
                 patch.object(windows_update.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True), \
                 patch.object(windows_update.subprocess,'Popen',return_value=Mock(poll=lambda:1)):
                with self.assertRaisesRegex(RuntimeError,'更新助手启动失败'):
                    windows_update.install(root/'setup.exe',root,'b'*64)
            self.assertFalse((root/'proceed').exists())

    def test_previous_install_failure_is_visible_after_restart(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(paths,'DATA_DIR',Path(temp)), \
             patch.object(updater,'WINDOWS',True), patch.dict(updater._state,phase='idle',error=None):
            (Path(temp)/'windows-update.json').write_text(json.dumps({'phase':'error','error':'Installer exit code: 5'}))
            self.assertIn('exit code: 5',updater.status()['error'])
            (Path(temp)/'windows-update.json').write_text('{broken')
            self.assertIsNone(updater.status()['error'])


if __name__=='__main__':unittest.main()
