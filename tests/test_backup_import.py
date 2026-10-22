import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from secretary.backup_import import import_backup
from secretary.core import Archive
from secretary.server import Service


class BackupImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Service(Path(self.temp.name) / 'source')
        self.target = Archive(Path(self.temp.name) / 'target')

    def tearDown(self):
        self.source.close()
        self.temp.cleanup()

    def backup(self):
        return self.source.backup()

    def test_round_trip_merge_original_search_and_duplicates(self):
        original = '资料原文件：火星气候'.encode()
        item, _ = self.source.archive.add('研究资料', '火星气候研究正文', filename='研究.txt', data=original)
        self.source.archive.update(item, summary='研究摘要', tags=['天文'], category='研究', state='ready')
        self.target.add('已有笔记', '已有知识保留')
        result = import_backup(self.target, self.backup())
        self.assertEqual(result, {'imported': 1, 'skipped': 0, 'total': 1})
        restored = next(i for i in self.target.export() if i['filename'])
        self.assertNotEqual(restored['id'], item)
        self.assertEqual(restored['summary'], '研究摘要')
        self.assertEqual(restored['tags'], ['天文'])
        self.assertEqual((self.target.root / 'files' / restored['id']).read_bytes(), original)
        self.assertTrue(self.target.retrieve('火星气候'))
        self.target.update(restored['id'], summary='本机修改保留')
        self.assertEqual(import_backup(self.target, self.backup())['skipped'], 1)
        self.assertEqual(self.target.get(restored['id'])['summary'], '本机修改保留')
        self.assertEqual(len(self.target.list()), 2)

    def test_invalid_archive_does_not_mutate(self):
        item, _ = self.source.archive.add('测试', '完整原件正文', filename='a.txt', data=b'original')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('archive.json', json.dumps(self.source.archive.export()))
        with self.assertRaisesRegex(ValueError, '缺少资料原文件'):
            import_backup(self.target, buffer.getvalue())
        self.assertEqual(self.target.list(), [])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('archive.json', '[]')
            z.writestr('../escape', 'bad')
        with self.assertRaisesRegex(ValueError, '无效路径'):
            import_backup(self.target, buffer.getvalue())

    def test_index_failure_rolls_back_rows_and_originals(self):
        self.source.archive.add('原件', '正文', filename='a.txt', data=b'original')
        with patch.object(self.target, '_index', side_effect=RuntimeError('index failure')):
            with self.assertRaisesRegex(RuntimeError, 'index failure'):
                import_backup(self.target, self.backup())
        self.assertEqual(self.target.list(), [])
        self.assertEqual(list((self.target.root / 'files').iterdir()), [])

    def test_browser_preferences_persist_and_legacy_settings_preserve_them(self):
        self.assertTrue(self.target.settings()['capture_background'])
        self.assertTrue(self.target.settings()['capture_close_tabs'])
        self.target.configure('codex', False, False, False)
        self.target.configure('codex', True)
        reopened = Archive(self.target.root)
        self.assertFalse(reopened.settings()['capture_background'])
        self.assertFalse(reopened.settings()['capture_close_tabs'])
