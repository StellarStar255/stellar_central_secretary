import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from secretary import local_paths
from secretary.server import Service


class LocalPathsTest(unittest.TestCase):
    def test_recognizes_paths_without_web_urls(self):
        text = '代码路径：\n/Users/admin/Documents/Example_Mac/rapid_test_code\n项目：/Users/me/中文 Project\n参考 `/tmp/a b` 和 "/tmp/c d"\n~/Documents/work\nC:\\Users\\me\\My Project\nhttps://example.com/path\nfile:///tmp/private\n<script>alert(1)</script>'
        self.assertEqual(local_paths.extract(text), [
            '/Users/admin/Documents/Example_Mac/rapid_test_code', '/Users/me/中文 Project',
            '/tmp/a b', '/tmp/c d', '~/Documents/work', 'C:\\Users\\me\\My Project'])

    def test_open_is_scoped_to_current_source_and_does_not_modify_archive(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            try:
                folder = Path(root)/'中文 Folder $(must-not-run).app'
                folder.mkdir()
                file = folder/'script.command'
                file.write_text('must never execute')
                missing = folder/'missing'
                item, _ = service.archive.add('Local paths', f'{folder}\n{file}\n{missing}')
                before = service.archive.get(item)
                self.assertEqual(service.item_detail(item)['local_paths'], [str(folder), str(file), str(missing)])
                with patch.object(local_paths.sys, 'platform', 'darwin'), patch.object(local_paths.subprocess, 'run') as run:
                    self.assertTrue(local_paths.open_location(service.archive, item, str(folder))['directory'])
                    self.assertEqual(run.call_args.args[0], ['/usr/bin/open', '-a', 'Finder', str(folder.resolve())])
                    self.assertFalse(local_paths.open_location(service.archive, item, str(file))['directory'])
                    self.assertEqual(run.call_args.args[0], ['/usr/bin/open', '-R', str(file.resolve())])
                    count = run.call_count
                    for invalid in (None, 42, str(Path(root)), '/tmp/unrecorded'):
                        with self.assertRaisesRegex(ValueError, '正文'): local_paths.open_location(service.archive, item, invalid)
                    with self.assertRaisesRegex(ValueError, '不存在'): local_paths.open_location(service.archive, item, str(missing))
                    self.assertEqual(run.call_count, count)
                with patch.object(local_paths.subprocess, 'run', side_effect=subprocess.TimeoutExpired('open', 15)):
                    with self.assertRaisesRegex(ValueError, '无法打开'): local_paths.open_location(service.archive, item, str(folder))
                self.assertEqual(service.archive.get(item), before)
                service.archive.update(item, text='Path removed')
                with self.assertRaisesRegex(ValueError, '正文'): local_paths.open_location(service.archive, item, str(folder))
            finally:
                service.close()

    def test_home_and_foreign_paths(self):
        with tempfile.TemporaryDirectory() as root:
            service = Service(root)
            try:
                item, _ = service.archive.add('Paths', '~/\nC:\\Users\\someone\\Project')
                with patch.object(local_paths.sys, 'platform', 'darwin'), patch.object(local_paths.subprocess, 'run') as run:
                    local_paths.open_location(service.archive, item, '~/')
                    self.assertEqual(run.call_args.args[0][-1], str(Path.home().resolve()))
                    if os.name != 'nt':
                        with self.assertRaisesRegex(ValueError, '当前电脑'):
                            local_paths.open_location(service.archive, item, 'C:\\Users\\someone\\Project')
            finally:
                service.close()
