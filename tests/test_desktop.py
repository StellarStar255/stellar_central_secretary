import tempfile
import threading
import os
import sys
import time
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch
from secretary.desktop_status import presentation
from secretary.server import Service


class DesktopStatusTest(unittest.TestCase):
    def test_start_ready_busy_error_and_update(self):
        self.assertEqual(presentation({})['title'], '启动中')
        state={'application':'stellar-central-secretary', 'runtime':{}}
        self.assertEqual(presentation(state)['badge'], None)
        state['runtime']={'reading':2,'processing':1,'answering':1}
        busy=presentation(state)
        self.assertIn('读取会话 2 项',busy['detail'])
        self.assertIn('整理资料 1 项',busy['detail'])
        self.assertIn('回答问题 1 项',busy['detail'])
        self.assertEqual(busy['badge'],'读取')
        self.assertEqual(presentation({**state,'error':'offline'})['icon'],'error')
        self.assertEqual(presentation({**state,'update':{'phase':'installing'}})['badge'],'升级')

    def test_question_counts_and_failures_clear_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            service.archive.add('天文','银河研究的完整正文')
            entered=threading.Event();finish=threading.Event();errors=[]
            def model(*args):
                entered.set();finish.wait(5);raise RuntimeError('model failure')
            def ask():
                try:service.ask('银河研究')
                except RuntimeError as exc:errors.append(str(exc))
            try:
                with patch('secretary.server.ai.run',side_effect=model):
                    worker=threading.Thread(target=ask);worker.start()
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(service.runtime()['answering'],1)
                    finish.set();worker.join(5)
                self.assertEqual(errors,['model failure'])
                self.assertEqual(service.runtime()['answering'],0)
            finally:
                finish.set();service.close()


@unittest.skipUnless(sys.platform=='darwin' and os.environ.get('SECRETARY_DESKTOP_TEST')=='1', 'Opt-in native macOS UI test')
class NativeDesktopTest(unittest.TestCase):
    def test_real_menu_dock_status_reopen_and_quit(self):
        from AppKit import NSApplication
        from secretary.desktop_macos import run
        from secretary.server import handler
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(service))
            address=f'http://127.0.0.1:{server.server_port}'
            errors=[]
            def wait_for(check):
                deadline=time.monotonic()+15
                while time.monotonic()<deadline:
                    if check():return
                    time.sleep(.1)
                raise AssertionError('Native UI state timeout: '+str(service.desktop))
            def verify():
                try:
                    wait_for(lambda:service.desktop.get('state')=='ready')
                    self.assertTrue(service.desktop['menu_bar'])
                    self.assertEqual(service.desktop['activation_policy'],0)
                    self.assertEqual(service.desktop['dock_badge'],'')
                    with service.lock:service.busy.add('fixture')
                    wait_for(lambda:service.desktop.get('dock_badge')=='整理')
                    self.assertEqual(service.desktop['label'],'')
                    with service.lock:service.busy.clear();service.captures['fixture']=threading.Event()
                    wait_for(lambda:service.desktop.get('dock_badge')=='读取')
                    with service.lock:service.captures.clear()
                    wait_for(lambda:service.desktop.get('state')=='ready')
                    delegate=NSApplication.sharedApplication().delegate()
                    delegate.performSelectorOnMainThread_withObject_waitUntilDone_('openMain:',None,True)
                    delegate.performSelectorOnMainThread_withObject_waitUntilDone_('requestQuit:',None,True)
                except BaseException as exc:
                    errors.append(exc)
                    server.shutdown()
            thread=threading.Thread(target=verify,daemon=True)
            try:
                with patch('secretary.desktop_macos.webbrowser.open') as opened:
                    thread.start();run(address,service=service,server=server,open_browser=False)
                    thread.join(5)
                    if errors:raise errors[0]
                    opened.assert_called_once_with(address)
            finally:
                server.server_close();service.close()
