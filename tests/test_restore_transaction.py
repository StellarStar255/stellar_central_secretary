import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from secretary.core import Archive
from secretary.local_backups import Backups
from secretary.restore_transaction import JOURNAL


# Exit without unwinding Python contexts, including the restore/rollback handler.
INTERRUPT = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from secretary import restore_transaction as tx
from secretary.core import Archive
from secretary.local_backups import Backups

root, key, point = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
replace = Path.replace
copyfile = tx.shutil.copyfile
install = tx.install

def moving(path, target):
    result = replace(path, target)
    if target.name == point:
        os._exit(73)
    return result

def copying(path, target):
    result = copyfile(path, target)
    if point == 'chats' and target == root/'conversations.json':
        os._exit(73)
    return result

def installing(*args):
    install(*args)
    if point == 'committed':
        os._exit(73)

with patch.object(Path, 'replace', moving), patch.object(tx.shutil, 'copyfile', copying), patch.object(tx, 'install', installing):
    archive = Archive(root)
    if point != 'discarded-files':
        Backups(archive).restore(key)
"""


class RestoreTransactionTest(unittest.TestCase):
    def test_process_exit_before_and_after_commit_and_during_rollback(self):
        for point in ('previous-files', 'files', 'chats', 'committed'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                archive = Archive(root)
                first, _ = archive.add('Snapshot', 'body', filename='first.txt', data=b'first')
                chats = root/'conversations.json'
                chats.write_text('["snapshot"]')
                snapshot = Backups(archive).create()
                latest, _ = archive.add('Live', 'other', filename='latest.txt', data=b'latest')
                chats.write_text('["live"]')
                args = [sys.executable, '-c', INTERRUPT, folder, snapshot['id']]
                self.assertEqual(subprocess.run([*args, point], timeout=30).returncode, 73)
                if point == 'chats':
                    self.assertEqual(subprocess.run([*args, 'discarded-files'], timeout=30).returncode, 73)
                reopened = Archive(root)
                self.assertEqual(reopened.get(first)['title'], 'Snapshot')
                self.assertEqual((root/'files'/first).read_bytes(), b'first')
                if point == 'committed':
                    with self.assertRaises(KeyError):
                        reopened.get(latest)
                    self.assertFalse((root/'files'/latest).exists())
                    self.assertEqual(chats.read_text(), '["snapshot"]')
                else:
                    self.assertEqual(reopened.get(latest)['title'], 'Live')
                    self.assertEqual((root/'files'/latest).read_bytes(), b'latest')
                    self.assertEqual(chats.read_text(), '["live"]')
                self.assertFalse((root/JOURNAL).exists())
                self.assertFalse(list(root.glob('.stellar-restore-*')))

    def test_locked_cleanup_after_commit_allows_startup_and_retries(self):
        from unittest.mock import patch
        from secretary import restore_transaction

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = Archive(root)
            key, _ = archive.add('Snapshot', 'test')
            backups = Backups(archive)
            snapshot = backups.create()
            archive.update(key, title='Latest')
            remove = restore_transaction.shutil.rmtree

            def locked(path, *args, **kwargs):
                if Path(path).name.startswith('.stellar-restore-'):
                    raise PermissionError('old file in use')
                return remove(path, *args, **kwargs)

            with patch.object(restore_transaction.shutil, 'rmtree', locked), self.assertLogs(restore_transaction.__name__, level='WARNING'):
                self.assertTrue(backups.restore(snapshot['id'])['ok'])
                self.assertEqual(Archive(root).get(key)['title'], 'Snapshot')
                self.assertTrue((root/JOURNAL).exists())
            reopened = Archive(root)
            self.assertEqual(reopened.get(key)['title'], 'Snapshot')
            self.assertFalse((root/JOURNAL).exists())
