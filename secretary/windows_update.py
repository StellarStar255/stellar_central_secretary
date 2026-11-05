"""Detached Windows installer handoff, outside the frozen app's DLL environment."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import paths


SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function Report($phase, $message) {
    $temp = $config.result + '.tmp'
    @{phase=$phase; error=$message} | ConvertTo-Json | Set-Content -LiteralPath $temp -Encoding UTF8
    Move-Item -LiteralPath $temp -Destination $config.result -Force
}
function Relaunch {
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath $config.exe -ArgumentList $config.arguments -WorkingDirectory (Split-Path $config.exe) -ErrorAction Stop | Out-Null
}
$exited = $false
$transcript = $false
try {
    Start-Transcript -Append -LiteralPath $config.log | Out-Null
    $transcript = $true
    # Retain the process handle: do not confuse an exited app with a reused PID.
    $parent = Get-Process -Id $config.pid -ErrorAction Stop
    Report 'ready' ''
    $deadline = (Get-Date).AddSeconds(25)
    while (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'proceed'))) {
        if ((Get-Date) -gt $deadline) { throw 'Update handoff was not acknowledged; installation canceled.' }
        Start-Sleep -Milliseconds 100
    }
    if (-not $parent.WaitForExit(120000)) { throw 'Application did not exit; installation canceled.' }
    $exited = $true
    Report 'installing' ''
    if ((Get-FileHash -LiteralPath $config.setup -Algorithm SHA256).Hash -ne $config.sha256) {
        throw 'Installer checksum changed after download; installation canceled.'
    }
    # ArgumentList arrays are joined by PowerShell, so quote paths explicitly.
    $installerArgs = '/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /RESTARTEXITCODE=3010 /DIR="' + (Split-Path $config.exe) + '" /LOG="' + $config.installer_log + '"'
    $installer = Start-Process -FilePath $config.setup -ArgumentList $installerArgs -WorkingDirectory $PSScriptRoot -PassThru -Wait
    if ($installer.ExitCode -ne 0) { throw ('Installer exit code: ' + $installer.ExitCode + '. See ' + $config.installer_log) }
    Relaunch
    Report 'complete' ''
} catch {
    $message = $_.Exception.Message
    Report 'error' $message
    Write-Output $message
    # Keep the failure visible in the app instead of silently leaving it closed.
    if ($exited) {
        try { Relaunch } catch { Write-Output $_.Exception.Message }
    }
    exit 1
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
}
'''


def last_result():
    try:
        value = json.loads((paths.DATA_DIR/'windows-update.json').read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def install(setup, work, expected_sha):
    exe = Path(sys.executable).resolve()
    work = Path(work).resolve()
    result = paths.DATA_DIR/'windows-update.json'
    arguments = [arg for arg in sys.argv[1:] if arg != '--desktop']
    # The launcher consumes --desktop; retain the resolved data root independently.
    if '--data-dir' not in arguments and not any(arg.startswith('--data-dir=') for arg in arguments):
        arguments += ['--data-dir', str(paths.DATA_DIR)]
    config = dict(pid=os.getpid(), exe=str(exe), setup=str(Path(setup).resolve()),
                  arguments=subprocess.list2cmdline(arguments), sha256=expected_sha,
                  result=str(result), log=str(paths.DATA_DIR/'update.log'),
                  installer_log=str(work/'installer.log'))
    (work/'install.json').write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    script = work/'install.ps1'
    script.write_text(SCRIPT, encoding='utf-8-sig')
    result.write_text(json.dumps({'phase':'starting','error':''}), encoding='utf-8')
    (work/'proceed').unlink(missing_ok=True)
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    # A launcher running under PowerShell 7 may export its incompatible module path.
    # Let Windows PowerShell initialize its own standard modules (e.g. Get-FileHash).
    for key in list(env):
        if key.upper() == 'PSMODULEPATH':env.pop(key)
    bundle = str(getattr(sys, '_MEIPASS', ''))
    if bundle:
        # Qt hooks also prepend bundle paths to PATH. Keep only external paths.
        env['PATH'] = os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep)
                                     if not os.path.normcase(p).startswith(os.path.normcase(bundle)))
        for key in ('QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QTWEBENGINEPROCESS_PATH'):
            if bundle.lower() in env.get(key,'').lower():env.pop(key,None)
    powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    kernel = ctypes.windll.kernel32
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    dll_path = ctypes.create_unicode_buffer(32768)
    kernel.GetDllDirectoryW(len(dll_path), dll_path)
    try:
        # PyInstaller's process-global DLL directory is inherited by child processes.
        if not kernel.SetDllDirectoryW(None):raise ctypes.WinError()
        with (work/'helper.log').open('ab') as log:
            process = subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive',
                                       '-ExecutionPolicy','Bypass','-File',str(script)],
                                      env=env, cwd=str(work), stdin=subprocess.DEVNULL,
                                      stdout=log, stderr=log, close_fds=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    finally:
        kernel.SetDllDirectoryW(dll_path.value or None)
    deadline = time.monotonic()+20
    while time.monotonic() < deadline:
        value = last_result()
        if value.get('phase') == 'ready':
            (work/'proceed').write_text('ready', encoding='ascii')
            return True
        if value.get('phase') == 'error' or process.poll() is not None:
            raise RuntimeError('Windows 更新助手启动失败：'+(value.get('error') or
                               f'PowerShell exit={process.poll()}；请查看 {work / "helper.log"}'))
        time.sleep(.1)
    # Parent remains running; a late helper can only time out, never replace live files.
    raise RuntimeError('Windows 更新助手未就绪，已保留当前程序；请查看 update.log')
