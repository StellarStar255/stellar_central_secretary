"""Bind a backup owner to a library directory, transferring it only on an explicit move."""
import hashlib
import json
import os
import plistlib
import socket
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _machine():
    try:
        if sys.platform == 'darwin':
            data = subprocess.check_output(
                ['/usr/sbin/ioreg', '-ard1', '-c', 'IOPlatformExpertDevice'],
                stderr=subprocess.DEVNULL, timeout=3)
            return plistlib.loads(data)[0]['IOPlatformUUID']
        if sys.platform == 'win32':
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return winreg.QueryValueEx(key, 'MachineGuid')[0]
        machine = Path('/etc/machine-id').read_text().strip()
        if machine:
            return machine
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, KeyError, IndexError):
        pass
    return socket.gethostname()


def binding(root):
    # Directory identity also distinguishes a replacement at the same pathname.
    location = [_machine(), os.path.normcase(str(root.resolve())), root.stat().st_ino]
    return hashlib.sha256(json.dumps(location).encode()).hexdigest()


def transfer(source, target):
    """Run with the source leased, after publication and before activating the target."""
    destination = target / 'backup-settings.json'
    if not destination.is_file():
        return
    settings = json.loads(destination.read_text())
    if not settings.get('library_id'):
        return
    old, new = binding(source), binding(target)
    if settings.get('library_binding') not in (old, new):
        # Unbound legacy ownership and settings from an independent copy stay unclaimed.
        return
    if settings['library_binding'] != new:
        settings['library_binding'] = new
        write(destination, settings)
    # Idempotent if publication succeeded but activation was interrupted.
    original = source / destination.name
    if original.is_file():
        previous = json.loads(original.read_text())
        if (previous.get('library_id') == settings['library_id']
                and previous.get('library_binding') == old):
            previous['library_binding'] = new
            write(original, previous)


def write(path, settings):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings))
    temporary.replace(path)
