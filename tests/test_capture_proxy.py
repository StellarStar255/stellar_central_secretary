import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from secretary import browser_reader,network,capture_worker
from secretary.server import Service

class CaptureProxyTests(unittest.TestCase):
 def test_browser_supports_http_and_socks5_but_model_stays_http(self):
  for url in ('http://127.0.0.1:7897','socks5://127.0.0.1:1080'):
   value={'mode':'custom','url':url}
   self.assertEqual(network.capture_proxy_config(value),value)
   with patch.object(network,'local_proxy_alive',return_value=True):self.assertEqual(network.capture_proxy_route(value),url)
  for url in ('socks4://localhost:1080','socks5://u:p@localhost:1080','socks5://localhost:0','socks5://localhost:1080/a'):
   with self.assertRaises(ValueError):network.capture_proxy_config({'mode':'custom','url':url})
  with self.assertRaises(ValueError):network.proxy_config({'mode':'custom','url':'socks5://localhost:1080'})

 def test_browser_direct_and_shared_route_are_explicit_and_preserved(self):
  self.assertEqual(network.capture_proxy_route({'mode':'direct'}),'direct://')
  self.assertIsNone(network.capture_proxy_route({'mode':'system'}))
  self.assertEqual(network.capture_proxy_route({'mode':'model'},{'mode':'direct'}),'direct://')
  with patch.object(network,'local_proxy_alive',return_value=False):
   with self.assertRaisesRegex(RuntimeError,'端口'):network.capture_proxy_route({'mode':'custom','url':'socks5://127.0.0.1:1080'})
  with tempfile.TemporaryDirectory() as folder:
   service=Service(folder)
   try:
    value={'mode':'custom','url':'socks5://127.0.0.1:1080'}
    service.save_settings({'backend':'codex','auto_ai':False,'capture_proxy':value})
    self.assertEqual(service.archive.settings()['capture_proxy'],value)
    with self.assertRaises(ValueError):service.save_settings({'backend':'gemini','auto_ai':True,'capture_proxy':{'mode':'unknown'}})
    self.assertEqual(service.archive.settings()['backend'],'codex')
   finally:service.close()

 def test_browser_session_cannot_silently_reuse_a_different_proxy(self):
  with tempfile.TemporaryDirectory() as folder:
   profile=Path(folder);session={'endpoint':'http://127.0.0.1:1234','websocket':'ws://127.0.0.1:1234/devtools/browser/abc','confirmed':True,'proxy':'socks5://127.0.0.1:1080'}
   browser_reader.save_session(profile,session)
   with patch.object(browser_reader,'debug_info',return_value={k:session[k] for k in ('endpoint','websocket')}):
    self.assertEqual(browser_reader.existing_session(profile)['proxy'],session['proxy'])
    with self.assertRaisesRegex(RuntimeError,'关闭专用浏览器'):browser_reader.start_or_reuse_browser('about:blank',profile,threading.Event(),proxy='direct://')
    self.assertTrue(browser_reader.start_or_reuse_browser('about:blank',profile,threading.Event(),proxy=session['proxy'])['confirmed'])

 def test_direct_browser_launch_passes_no_proxy_flag(self):
  with tempfile.TemporaryDirectory() as folder:
   debug={'endpoint':'http://127.0.0.1:1234','websocket':'ws://127.0.0.1:1234/devtools/browser/abc'}
   with patch.object(browser_reader,'existing_session',return_value=None),patch.object(browser_reader,'chrome_executable',return_value='/fixture/chrome'),patch.object(browser_reader,'free_loopback_port',return_value=1234),patch.object(browser_reader,'debug_info',return_value=debug),patch.object(browser_reader.subprocess,'Popen',return_value=Mock(poll=lambda:None)) as launch:
    browser_reader.start_or_reuse_browser('about:blank',Path(folder),threading.Event(),proxy='direct://')
    self.assertIn('--no-proxy-server',launch.call_args.args[0])

 def test_startup_discovery_of_own_endpoint_keeps_the_requested_proxy(self):
  for port in (1234,4321):
   with self.subTest(discovered_port=port),tempfile.TemporaryDirectory() as folder:
    profile=Path(folder);proc=Mock(poll=lambda:None)
    current={'endpoint':f'http://127.0.0.1:{port}','websocket':f'ws://127.0.0.1:{port}/devtools/browser/fixture','confirmed':False,'process':None}
    route='socks5://127.0.0.1:1080'
    with patch.object(browser_reader,'existing_session',side_effect=[None,current]),patch.object(browser_reader,'chrome_executable',return_value='/fixture/chrome'),patch.object(browser_reader,'free_loopback_port',return_value=1234),patch.object(browser_reader,'debug_info',side_effect=OSError('still starting')),patch.object(browser_reader.time,'monotonic',side_effect=[0,0,2,2]),patch.object(browser_reader.subprocess,'Popen',return_value=proc):
     if port!=1234:
      with self.assertRaisesRegex(RuntimeError,'关闭专用浏览器'):browser_reader.start_or_reuse_browser('about:blank',profile,threading.Event(),proxy=route)
      continue
     session=browser_reader.start_or_reuse_browser('about:blank',profile,threading.Event(),proxy=route)
    self.assertEqual(session['proxy'],route);self.assertIs(session['process'],proc)
    import json
    self.assertEqual(json.loads((profile/'.reader-session.json').read_text())['proxy'],route)

 def test_port_check_does_not_call_a_model_and_reports_socket_failures(self):
  with patch.object(network,'local_proxy_alive',return_value=True),patch.object(network.socket,'create_connection') as connect:
   self.assertTrue(network.check_proxy_port({'mode':'custom','url':'socks5://127.0.0.1:1080'},browser=True)['proxied'])
   self.assertEqual(connect.call_args.args[0],('127.0.0.1',1080))
   connect.side_effect=ConnectionRefusedError()
   with self.assertRaisesRegex(RuntimeError,'核对'):network.check_proxy_port({'mode':'custom','url':'http://127.0.0.1:7897'})

 def test_capture_worker_receives_saved_browser_route_for_both_kinds(self):
  with tempfile.TemporaryDirectory() as folder:
   service=Service(folder)
   try:
    service.archive.configure('codex',False,capture_close_tabs=False,capture_proxy={'mode':'custom','url':'socks5://127.0.0.1:1080'})
    for url in ('https://chatgpt.com/c/fixture','https://example.com/material'):
     item,_=service.archive.add('Fixture','retained source',url=url);service.login_confirmations[item]=threading.Event()
     with patch.object(network,'local_proxy_alive',return_value=True),patch.object(capture_worker,'run',side_effect=RuntimeError('fixture stops before browser I/O')) as run:
      service.capture(item,threading.Event(),False)
     self.assertEqual(run.call_args.kwargs['proxy'],'socks5://127.0.0.1:1080')
     self.assertEqual(service.archive.get(item)['text'],'retained source')
   finally:service.close()
