import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from secretary import backup_workspace
from secretary.core import Archive
from secretary.local_backups import Backups


class BackupWorkspaceTests(unittest.TestCase):
    def test_recovery_respects_live_writer_then_reclaims_interrupted_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backups = Backups(Archive(root))
            backups.configure({'folder':str(root/'shared')})
            good = backups.create()
            ready = root / 'writer-ready'
            child_script = """
import os, sys, zipfile
from pathlib import Path
from secretary.core import Archive
from secretary.local_backups import Backups
original = zipfile.ZipFile.writestr
def interrupt(output, name, data, *args, **kwargs):
    if name == 'manifest.json':
        output.fp.flush()
        Path(sys.argv[2]).touch()
        sys.stdin.buffer.read(1)
        os._exit(73)
    return original(output, name, data, *args, **kwargs)
zipfile.ZipFile.writestr = interrupt
Backups(Archive(sys.argv[1])).create()
"""
            with subprocess.Popen([sys.executable, '-c', child_script, temp, str(ready)],
                                  stdin=subprocess.PIPE) as writer:
                try:
                    deadline = time.monotonic() + 15
                    while not ready.exists() and time.monotonic() < deadline and writer.poll() is None:
                        time.sleep(.02)
                    self.assertTrue(ready.exists())
                    occupied = backups.status()['temporary_bytes']
                    self.assertGreater(occupied, 0)
                    backup_workspace.recover(backups.folder, root)
                    self.assertEqual(backups.status()['temporary_bytes'], occupied)
                    other = root / 'another-library'
                    other.mkdir()
                    other_backups = Backups(Archive(other))
                    other_backups.configure({'folder':str(backups.folder)})
                    self.assertEqual(other_backups.folder, backups.folder)
                    other_backups.create()
                    self.assertEqual(backups.status()['temporary_bytes'], occupied)
                    writer.communicate(b'x', timeout=15)
                    self.assertEqual(writer.returncode, 73)
                finally:
                    if writer.poll() is None:
                        writer.kill()
            legacy = backups.folder / ('1'*32+'.part')
            legacy.write_bytes(b'legacy')
            old_stage = backups.folder / 'tmp1234abcd'
            old_stage.mkdir()
            (old_stage/'archive.sqlite3').write_bytes(b'old')
            unrelated = backups.folder / 'other.part'
            unrelated.write_bytes(b'keep')
            restarted = Backups(Archive(root))
            restarted.start()
            try:
                deadline = time.monotonic()+10
                while restarted.status()['temporary_bytes'] != 9 and time.monotonic()<deadline:
                    time.sleep(.02)
            finally:
                restarted.close()
            status = restarted.status()
            self.assertEqual(status['temporary_bytes'], 9)
            self.assertEqual(status['used_bytes'], 9+sum(p.stat().st_size for p in backups.folder.glob('*.zip')))
            self.assertEqual(restarted.verify(good['id'])['verification']['state'], 'verified')
            self.assertEqual(unrelated.read_bytes(), b'keep')
