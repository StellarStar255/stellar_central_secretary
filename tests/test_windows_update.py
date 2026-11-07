import json
import os
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from secretary import paths, updater, windows_update


class WindowsUpdateTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Requires real Windows PowerShell')
    def test_powershell_console_launch_regression(self):
        powershell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        for name,flags,args in [('legacy',subprocess.DETACHED_PROCESS,['-WindowStyle','Hidden']),
                                ('fixed',subprocess.CREATE_NO_WINDOW,[])]:
            value=subprocess.run([powershell,'-NoProfile','-NonInteractive',*args,'-Command','Write-Output ready'],
                                 stdin=subprocess.DEVNULL,capture_output=True,creationflags=flags|subprocess.CREATE_NEW_PROCESS_GROUP,timeout=15)
            print('PowerShell console regression:',name,'exit=',value.returncode,'stdout=',repr(value.stdout),'stderr=',repr(value.stderr),flush=True)
            if name=='fixed':self.assertEqual(value.returncode,0,value.stderr)

    @unittest.skipUnless(sys.platform=='win32','Requires real Windows PowerShell')
    def test_real_helper_readiness_and_post_handoff_checksum_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            root=Path(temp);work=root/'更新 with spaces';work.mkdir()
            (work/'setup.exe').write_bytes(b'changed installer')
            script=root/'parent.py'
            script.write_text('''import sys
from pathlib import Path
from secretary import windows_update,paths
root=Path(sys.argv[1]);work=root/'更新 with spaces'
paths.DATA_DIR=root
sys.executable=str(root/'missing-app.exe')
assert windows_update.install(work/'setup.exe',work,'0'*64)
''',encoding='utf-8')
            process=subprocess.run([sys.executable,str(script),str(root)],env=dict(os.environ,PYTHONPATH=str(Path.cwd())),
                                   capture_output=True,text=True,timeout=40)
            helper=work/'helper.log'
            log=helper.read_bytes().decode('utf-8',errors='replace') if helper.exists() else ''
            self.assertEqual(process.returncode,0,process.stderr+'\n'+log)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:value=json.loads((root/'windows-update.json').read_text(encoding='utf-8-sig'))
                except (OSError,ValueError):value={}
                if value.get('phase')=='error':break
                time.sleep(.1)
            self.assertEqual(value.get('phase'),'error',value)
            self.assertIn('checksum changed',value['error'])
            # The result is written just before the detached host closes its log.
            deadline=time.monotonic()+5
            while helper.exists() and time.monotonic()<deadline:
                try:helper.unlink()
                except PermissionError:time.sleep(.1)

    @unittest.skipUnless(sys.platform=='win32','Windows PowerShell helper')
    def test_relaunch_is_idempotent_if_reporting_fails_after_start(self):
        # Execute the actual helper function; a failed completion report enters
        # the recovery path and must not start a second copy of the application.
        function=windows_update.SCRIPT.split('function Relaunch {',1)[1].split('$exited =',1)[0]
        script="function Relaunch {"+function+'''
$config = @{exe='fixture.exe'; arguments='--port 9999'}
$script:starts = 0
function Start-Process { $script:starts += 1 }
try { Relaunch; throw 'Report failed' } catch { Relaunch }
if ($script:starts -ne 1) { throw "Duplicate restart: $script:starts" }
'''
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'relaunch.ps1';path.write_text(script,encoding='utf-8-sig')
            powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(path)],
                           check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)

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
                 patch.dict(os.environ,{'SystemRoot':str(root/'Windows'),'PSMODULEPATH':'incompatible-powershell-7-modules'}), \
                 patch.object(windows_update.subprocess,'CREATE_NO_WINDOW',0x08000000,create=True), \
                 patch.object(windows_update.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True), \
                 patch.object(windows_update.subprocess,'Popen',side_effect=spawn) as popen:
                self.assertTrue(windows_update.install(root/'setup.exe',work,'a'*64,desktop=True))
            config = json.loads((work/'install.json').read_text())
            self.assertEqual(config['exe'],str(root/'安装目录'/'Stellar Secretary.exe'))
            self.assertIn('--port 9988',config['arguments']);self.assertIn('--data-dir',config['arguments'])
            self.assertIn('--desktop',config['arguments']);self.assertIn('--no-browser',config['arguments'])
            self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            self.assertFalse(any(key.upper()=='PSMODULEPATH' for key in popen.call_args.kwargs['env']))
            self.assertEqual(popen.call_args.kwargs['cwd'],str(work))
            self.assertTrue((work/'proceed').is_file())
            self.assertEqual(kernel.SetDllDirectoryW.call_count,2)

    def test_helper_failure_keeps_current_app_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);kernel=Mock();kernel.SetDllDirectoryW.return_value=1
            with patch.object(paths,'DATA_DIR',root), patch.object(windows_update.ctypes,'windll',Mock(kernel32=kernel),create=True), \
                 patch.dict(os.environ,{'SystemRoot':temp}), \
                 patch.object(windows_update.subprocess,'CREATE_NO_WINDOW',0x08000000,create=True), \
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
