"""Run an OS folder picker without blocking the desktop host's event loop."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from . import paths


_picker_lock = threading.Lock()


def choose(title, initial):
    if not _picker_lock.acquire(blocking=False):
        raise ValueError('已有一个文件夹选择窗口打开。')
    try:
        with tempfile.TemporaryDirectory(prefix='stellar-folder-') as directory:
            result = Path(directory) / 'selection.json'
            command = [sys.executable, '--choose-directory'] if paths.FROZEN else [
                sys.executable, '-m', 'secretary.directory_picker',
            ]
            try:
                subprocess.run(
                    [*command, str(result), title, str(initial)],
                    env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
                    check=True,
                    timeout=240,
                )
                selected = json.loads(result.read_text(encoding='utf-8'))
                if selected is None:
                    return None
                if isinstance(selected, str) and Path(selected).is_absolute() and Path(selected).is_dir():
                    return selected
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            raise ValueError('无法打开文件夹选择器，请手动输入路径。')
    finally:
        _picker_lock.release()


def main():
    result, title, initial = sys.argv[-3:]
    folder = Path(initial)
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    if not folder.is_dir():
        folder = Path.home()
    if sys.platform == 'darwin':
        from AppKit import NSApplication, NSModalResponseOK, NSOpenPanel
        from Foundation import NSURL

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(1)
        app.activateIgnoringOtherApps_(True)
        panel = NSOpenPanel.openPanel()
        panel.setTitle_(title)
        panel.setCanChooseFiles_(False)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        panel.setCanCreateDirectories_(True)
        panel.setDirectoryURL_(NSURL.fileURLWithPath_isDirectory_(str(folder), True))
        selected = str(panel.URL().path()) if panel.runModal() == NSModalResponseOK else None
    else:
        if sys.platform.startswith('linux') and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            raise SystemExit(1)
        from PySide6.QtWidgets import QApplication, QFileDialog

        app = QApplication([sys.argv[0]])
        selected = QFileDialog.getExistingDirectory(None, title, str(folder)) or None
    Path(result).write_text(json.dumps(selected, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
