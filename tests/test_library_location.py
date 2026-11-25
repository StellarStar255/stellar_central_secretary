import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from secretary import library_location
from secretary.core import Archive
from secretary.local_backups import Backups
from secretary.server import Service


class LibraryLocationTest(unittest.TestCase):
    def setUp(self):
        work = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.preference = work/'settings'/'library-location.json'
        self.enterContext(patch.object(library_location, 'preference_file', return_value=self.preference))
        self.root, self.target, self.backup = (work/name for name in ('library', 'new library', 'backup'))
        self.target.mkdir()
        self.archive = Archive(self.root)
        self.backups = Backups(self.archive)

    def test_recovery_requires_an_existing_library_and_replaces_stale_preference(self):
        missing = self.root.parent/'unavailable'
        corrupt = self.root.parent/'corrupt'
        corrupt.mkdir()
        (corrupt/'archive.sqlite3').write_bytes(b'not SQLite')
        item, _ = self.archive.add('Existing memory', 'Original text')
        library_location.write({'active': str(missing), 'previous': [str(self.root)]})
        choices = iter((('existing', self.target), ('existing', corrupt), ('existing', self.root)))
        problems = []

        def recover(problem):
            problems.append(problem.root)
            return next(choices)

        with ExitStack() as stack:
            self.assertEqual(library_location.startup_directory(stack, None, recover), self.root)
        self.assertEqual(problems, [missing, self.target, corrupt])
        self.assertEqual(library_location.read(), {'active': str(self.root), 'previous': [str(missing)]})
        self.assertEqual(self.archive.get(item)['text'], 'Original text')
        self.assertFalse(missing.exists())
        self.assertFalse((self.target/'archive.sqlite3').exists())
        self.assertEqual((corrupt/'archive.sqlite3').read_bytes(), b'not SQLite')

    def test_new_recovery_library_is_empty_and_used_on_next_launch(self):
        old = self.root.parent/'unavailable'
        old.mkdir()
        leftover = old/'old attachment.txt'
        leftover.write_bytes(b'keep the old attachment')
        item, _ = self.archive.add('Existing memory', 'Keep this too')
        library_location.write({'active': str(old), 'previous': [str(self.root)]})
        choices = iter((('new', old), ('new', self.root), ('new', self.target)))
        errors = []

        def recover(problem):
            errors.append(problem.root)
            return next(choices)

        with ExitStack() as stack:
            self.assertEqual(library_location.startup_directory(stack, str(old), recover), self.target)
            self.assertTrue((self.target/'archive.sqlite3').is_file())
            fresh = Archive(self.target)
            self.assertEqual(fresh.list(), [])
            new_item, _ = fresh.add('Fresh memory', 'Survives restart')

        self.assertEqual(errors, [old, old, self.root])
        self.assertEqual(library_location.read(), {'active': str(self.target),
                                                  'previous': [str(self.root), str(old)]})
        self.assertEqual(leftover.read_bytes(), b'keep the old attachment')
        self.assertEqual(self.archive.get(item)['text'], 'Keep this too')
        with ExitStack() as stack:
            self.assertEqual(library_location.startup_directory(stack, str(old)), self.target)
            self.assertEqual(Archive(self.target).get(new_item)['text'], 'Survives restart')

    def test_new_recovery_library_does_not_save_location_when_creation_fails(self):
        old = self.root.parent/'unavailable'
        library_location.write({'active': str(old)})
        choices = iter((('new', self.target), None))

        with ExitStack() as stack, patch('secretary.core.Archive', side_effect=OSError('disk full')):
            self.assertIsNone(library_location.startup_directory(
                stack, None, lambda _: next(choices)))

        self.assertEqual(library_location.read(), {'active': str(old)})
        with library_location.lease(self.target):
            self.assertFalse((self.target/'archive.sqlite3').exists())

    def test_legacy_windows_location_without_database_is_not_recreated(self):
        with patch.object(library_location.paths, 'remembered_windows_data_dir', return_value=self.target), \
             patch.object(library_location.paths, 'FROZEN', True), \
             patch.object(library_location.sys, 'platform', 'win32'), ExitStack() as stack:
            self.assertIsNone(library_location.startup_directory(stack, str(self.target), lambda _: None))
        self.assertFalse((self.target/'archive.sqlite3').exists())

    def test_move_preserves_archive_and_independent_backup_location(self):
        item, _ = self.archive.add('Memory', 'A saved memory', filename='original.txt', data=b'original')
        (self.root/'conversations.json').write_text('{"conversations":[],"activeId":""}')
        old = self.backups.create()
        self.backups.configure({'folder':str(self.backup)})
        self.assertEqual(library_location.schedule(self.root, str(self.target), self.backups.folder)['pending'], str(self.target))
        self.archive.update(item, title='Edited before restart')

        with library_location.lease(self.root):
            self.assertEqual(library_location.migrate(self.root, library_location.read()), self.target)

        preference = library_location.read()
        self.assertEqual(library_location.selected(preference, None), self.target)
        self.assertEqual(library_location.selected(preference, str(self.root)), self.target)
        self.assertEqual(library_location.selected(preference, str(self.root.parent/'separate')), self.root.parent/'separate')
        result = library_location.status(self.target)
        self.assertNotIn('pending', result)
        self.assertEqual(result['result'], {'id': preference['completed_migration'],
                                            'state': 'completed', 'folder': str(self.target)})
        self.assertEqual(library_location.status(self.root), {})
        moved = Archive(self.target)
        self.assertEqual(moved.get(item)['title'], 'Edited before restart')
        self.assertEqual((self.target/'files'/item).read_bytes(), b'original')
        self.assertEqual((self.target/'conversations.json').read_text(), '{"conversations":[],"activeId":""}')
        self.assertTrue((self.root/'files'/item).exists())
        self.assertFalse((self.target/'local-backups').exists())
        moved_backups = Backups(moved)
        self.assertEqual(moved_backups.folder, self.backups.folder)
        self.assertIn(old['id'], {entry['id'] for entry in moved_backups.entries()})
        self.assertTrue(moved_backups.owns(old))
        self.assertFalse(Backups(self.archive).owns(old))
        moved_backups.restore(old['id'])
        self.assertEqual(moved.get(item)['title'], 'Memory')

    def test_move_rebinds_explicit_default_and_caps_old_locations(self):
        self.backups.configure({'folder':str(self.backups.default)})
        saved = self.backups.create()
        previous = [str(self.root.parent/str(i)) for i in range(6)]
        self.backups._save_config({**self.backups.config,'previous_folders':previous})
        library_location.schedule(self.root, str(self.target), self.backups.folder)
        with library_location.lease(self.root):
            self.assertEqual(library_location.migrate(self.root, library_location.read()), self.target)
        moved = Backups(Archive(self.target))
        self.assertEqual(moved.folder, self.target/'local-backups')
        self.assertEqual(moved.config['previous_folders'],[*previous[-4:],str(self.backups.default)])
        moved.restore(saved['id'], folder=str(self.backups.default))
        self.assertTrue(any(moved.folder.glob('*.zip')))

    def test_unavailable_destination_keeps_original_and_can_cancel(self):
        library_location.schedule(self.root, str(self.target), self.backups.folder)
        self.target.rmdir()
        self.assertEqual(library_location.migrate(self.root, library_location.read()), self.root)
        failed = library_location.status(self.root)
        self.assertIn('请检查硬盘连接', failed['error'])
        self.assertEqual(failed['result']['state'], 'failed')
        self.assertEqual(failed['result']['folder'], str(self.root))
        self.assertEqual(failed['result']['error'], failed['error'])
        self.assertFalse(self.target.exists())
        self.assertEqual(library_location.schedule(self.root, '', self.backups.folder), {})

    def test_migration_rejects_nonempty_and_overlapping_locations(self):
        self.backups.configure({'folder':str(self.target)})
        with self.assertRaises(ValueError):
            library_location.schedule(self.root, str(self.target), self.backups.folder)
        (self.backup/'existing').mkdir(parents=True)
        with self.assertRaises(ValueError):
            library_location.schedule(self.root, str(self.backup), self.backups.default)
        self.assertFalse(self.preference.exists())

    def test_preflight_checks_size_space_and_destination_without_scheduling(self):
        self.archive.add('Memory', 'Original bytes', filename='original.txt', data=b'original')
        result = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertGreater(result['estimated_bytes'], len(b'original'))
        self.assertGreater(result['free_bytes'], 0)
        self.assertEqual((result['empty'], result['writable']), (True, True))
        self.assertFalse(list(self.target.iterdir()))
        self.assertFalse(self.preference.exists())

        (self.root/'updates').mkdir()
        (self.root/'updates'/'installer').write_bytes(b'x'*1024)
        (self.target/'existing').touch()
        nonempty = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertEqual(nonempty['estimated_bytes'], result['estimated_bytes'])
        self.assertFalse(nonempty['empty'])
        self.assertTrue(nonempty['error'])
        (self.target/'existing').unlink()

        with patch.object(library_location.tempfile, 'TemporaryFile', side_effect=PermissionError):
            unwritable = library_location.preflight(self.root, str(self.target), self.backups.folder)
        self.assertFalse(unwritable['writable'])
        self.assertTrue(unwritable['error'])

        disk = type('Disk', (), {'free': 0})()
        with patch.object(library_location.shutil, 'disk_usage', return_value=disk):
            full = library_location.preflight(self.root, str(self.target), self.backups.folder)
            self.assertEqual(full['free_bytes'], 0)
            with self.assertRaisesRegex(ValueError, '空间不足'):
                library_location.schedule(self.root, str(self.target), self.backups.folder)
        self.assertTrue(full['error'])
        self.assertFalse(self.preference.exists())

    def test_restart_admission_checks_pending_destination_and_active_work(self):
        service = Service(self.root)
        self.addCleanup(service.close)
        service.restart_supported = True
        library_location.schedule(self.root, str(self.target), service.backups.folder)
        self.assertTrue(service.enter_post())
        with self.assertRaisesRegex(ValueError, '目录已更改'):
            service.request_library_restart(str(self.backup))
        with patch.object(service, 'runtime', return_value={'processing': 1}):
            with self.assertRaisesRegex(ValueError, '等待当前任务'):
                service.request_library_restart(str(self.target))
        with patch('secretary.server.updater.status', return_value={'phase': 'installing'}):
            with self.assertRaisesRegex(ValueError, '等待当前任务'):
                service.request_library_restart(str(self.target))
        self.assertTrue(service.enter_post())
        with self.assertRaisesRegex(ValueError, '等待当前任务'):
            service.request_library_restart(str(self.target))
        service.leave_post()
        with patch('secretary.server.updater.status', return_value={'phase': 'idle'}):
            service.request_library_restart(str(self.target))
        self.assertFalse(service.enter_post())
        self.assertTrue(service.backups.stop.is_set())
        service.leave_post()

    def test_upgrade_shutdown_waits_for_inflight_question_and_blocks_new_posts(self):
        import json, threading, urllib.request, urllib.error
        from concurrent.futures import ThreadPoolExecutor
        from secretary.server import LocalHTTPServer, handler
        service=Service(self.root)
        self.addCleanup(service.close)
        service.archive.configure('codex',False)
        service.archive.add('fixture','fixture text for testing shutdown')
        server=self.enterContext(LocalHTTPServer(('127.0.0.1',0),handler(service)))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base+'/api/status') as response:
            token=json.load(response)['token']
        def post(path,body):
            request=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'X-Knowledge-Token':token})
            with opener.open(request,timeout=5) as response:
                return json.load(response)
        entered,finish=threading.Event(),threading.Event()
        def answer(*args):
            entered.set()
            if not finish.wait(5):raise AssertionError('question timed out')
            return 'fixture answer [1]'
        with patch('secretary.ai.run',side_effect=answer), ThreadPoolExecutor(1) as pool:
            question=pool.submit(post,'/api/ask',{'question':'fixture'})
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    post('/api/update/shutdown',{})
                self.assertEqual(denied.exception.code,409)
                denied.exception.close()
            finally:
                finish.set()
            self.assertEqual(question.result()['answer'],'fixture answer [1]')
        self.assertTrue(post('/api/update/shutdown',{})['ok'])
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(service.enter_post())
        self.assertFalse(service.restart_requested)
