import tempfile,unittest,uuid
from unittest.mock import patch
from secretary.desktop_windows import local_navigation
from secretary.server import Service

class WindowsDesktopTest(unittest.TestCase):
    def test_only_the_application_origin_stays_inside_the_window(self):
        self.assertTrue(local_navigation('http://127.0.0.1:8768','http://127.0.0.1:8768/?desktop=1'))
        for url in ('https://example.com','http://127.0.0.1:9999/','file:///private/example','javascript:alert(1)'):
            self.assertFalse(local_navigation('http://127.0.0.1:8768',url))

    def test_headless_service_can_attach_one_native_host_and_expire_its_lease(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root)
            owner=uuid.uuid4().hex;other=uuid.uuid4().hex
            metadata={'mode':'desktop','state':'ready','tray':True,'window_visible':True,'window_loaded':True,'window_id':123,'browser_opens':0}
            try:
                service.desktop_heartbeat({'owner':owner,'desktop':metadata})
                self.assertTrue(service.desktop_status()['supports_window'])
                service.switch_interface('browser');self.assertEqual(service.archive.settings()['interface_mode'],'browser')
                with self.assertRaises(ValueError):service.desktop_heartbeat({'owner':other,'desktop':metadata})
                before=service.desktop_status()
                with self.assertRaises(ValueError):service.desktop_heartbeat({'owner':owner,'desktop':{**metadata,'window_loaded':'true'}})
                self.assertEqual(service.desktop_status(),before)
                with patch('secretary.server.time.monotonic',return_value=service.desktop_heartbeat_at+11):self.assertFalse(service.desktop_status()['enabled'])
                service.desktop_heartbeat({'owner':other,'desktop':metadata})
                service.desktop_heartbeat({'owner':owner,'detach':True});self.assertTrue(service.desktop_status()['enabled'])
                service.desktop_heartbeat({'owner':other,'detach':True});self.assertFalse(service.desktop_status()['enabled'])
            finally:service.close()
