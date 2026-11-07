import io
import json
import subprocess
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

from secretary import launcher
from secretary.desktop_qt import configure_rendering
from secretary.windows_instance import DesktopSlot, acquire_or_activate


class WindowsInstanceTest(unittest.TestCase):
    def test_secondary_launcher_waits_then_forwards_to_the_existing_window(self):
        slot=Mock();slot.acquire.return_value=False
        pending={'application':'stellar-central-secretary','desktop':{}}
        ready={**pending,'desktop':{'supports_window':True},'settings':{'interface_mode':'desktop'},'token':'fixture'}
        opener=Mock()
        opener.open.side_effect=[io.BytesIO(json.dumps(value).encode()) for value in (pending,ready,{'ok':True})]
        with patch.object(launcher.sys,'platform','win32'),patch.object(launcher.sys,'argv',['app']), \
             patch('secretary.windows_instance.DesktopSlot',return_value=slot), \
             patch('secretary.windows_instance.time.sleep'), \
             patch.object(launcher.urllib.request,'build_opener',return_value=opener), \
             patch.object(launcher,'_main') as start:
            launcher.main()
        start.assert_not_called();slot.close.assert_called_once()
        request=opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/api/interface'))
        self.assertEqual(json.loads(request.data),{'mode':'desktop'})

    def test_secondary_waits_for_desktop_without_creating_another_host(self):
        slot = Mock();slot.acquire.return_value = False
        activate = Mock(side_effect=[False, False, True])
        with patch('secretary.windows_instance.time.sleep'):
            self.assertFalse(acquire_or_activate(slot, activate))
        self.assertEqual(activate.call_count, 3)

    def test_exit_during_startup_allows_the_waiter_to_take_over(self):
        slot = Mock();slot.acquire.side_effect = [False, True]
        activate = Mock(return_value=False)
        with patch('secretary.windows_instance.time.sleep'):
            self.assertTrue(acquire_or_activate(slot, activate))
        activate.assert_called_once()

    def test_unresponsive_owner_does_not_spawn_a_duplicate(self):
        slot = Mock();slot.acquire.return_value = False
        with self.assertRaisesRegex(RuntimeError, '未创建重复窗口'):
            acquire_or_activate(slot, lambda:False, timeout=0)

    def test_launcher_closes_slot_when_starting_or_raising(self):
        for failure in (None, RuntimeError('startup failed')):
            slot = Mock()
            with patch.object(launcher.sys,'platform','win32'), patch.object(launcher.sys,'argv',['app']), \
                 patch('secretary.windows_instance.DesktopSlot',return_value=slot), \
                 patch('secretary.windows_instance.acquire_or_activate',return_value=True), \
                 patch.object(launcher.urllib.request,'build_opener'), \
                 patch.object(launcher,'_main',side_effect=failure) as start:
                if failure:
                    with self.assertRaises(RuntimeError):launcher.main()
                else:launcher.main()
                start.assert_called_once();slot.close.assert_called_once()

    def test_windows_rendering_covers_both_layers_and_preserves_debug_flags(self):
        env={'QTWEBENGINE_CHROMIUM_FLAGS':'--remote-allow-origins=http://127.0.0.1:9999'}
        configure_rendering('win32',env);configure_rendering('win32',env)
        self.assertEqual(env['QT_QUICK_BACKEND'],'software')
        self.assertEqual(env['QTWEBENGINE_CHROMIUM_FLAGS'].split().count('--disable-gpu'),1)
        self.assertIn('--remote-allow-origins=',env['QTWEBENGINE_CHROMIUM_FLAGS'])
        linux={};configure_rendering('linux',linux);self.assertEqual(linux,{})

    @unittest.skipUnless(sys.platform=='win32','Windows named mutex')
    def test_real_process_exclusion_release_and_abandoned_owner(self):
        name=uuid.uuid4().hex
        slot=DesktopSlot(name)
        code="from secretary.windows_instance import DesktopSlot; s=DesktopSlot(%r); print(s.acquire(),flush=True)" % name
        def child():
            return subprocess.check_output([sys.executable,'-c',code],text=True,
                creationflags=subprocess.CREATE_NO_WINDOW).strip()
        try:
            self.assertTrue(slot.acquire())
            self.assertEqual(child(),'False')
            slot.close();slot=DesktopSlot(name)
            # Retain our handle while a child acquires and exits without release.
            self.assertEqual(child(),'True')
            self.assertTrue(slot.acquire())
        finally:slot.close()
