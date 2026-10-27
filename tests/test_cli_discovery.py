import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretary.ai import executable


class CliDiscoveryTest(unittest.TestCase):
    def test_windows_install_found_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            cli = Path(folder)/'Programs/OpenAI/Codex/bin/codex.exe'
            cli.parent.mkdir(parents=True)
            cli.touch()
            with patch('secretary.ai.shutil.which', return_value=None), patch('secretary.ai.sys.platform', 'win32'), patch.dict(os.environ, LOCALAPPDATA=folder):
                self.assertEqual(executable('codex'), str(cli))

    def test_path_takes_priority(self):
        with patch('secretary.ai.shutil.which', return_value='custom/codex.exe'):
            self.assertEqual(executable('codex'), 'custom/codex.exe')

    def test_windows_npm_install_found_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            cli = Path(folder)/'npm/codex.cmd'
            cli.parent.mkdir()
            cli.touch()
            with patch('secretary.ai.shutil.which', return_value=None), patch('secretary.ai.sys.platform', 'win32'), patch('secretary.ai.Path.home', return_value=Path(folder)), patch.dict(os.environ, {'APPDATA':folder, 'LOCALAPPDATA':folder}):
                self.assertEqual(executable('codex'), str(cli))
