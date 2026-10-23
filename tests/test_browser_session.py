import json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from secretary import browser_reader,browser_session

class BrowserSessionTest(unittest.TestCase):
 def test_recovers_changed_nonce_only_from_exact_owned_profile(self):
  with tempfile.TemporaryDirectory() as root:
   profile=Path(root);old={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/old','confirmed':True}
   (profile/'.reader-session.json').write_text(json.dumps(old))
   fresh={**old,'websocket':'ws://127.0.0.1:9371/devtools/browser/fresh'};fresh.pop('confirmed')
   with patch.object(browser_session,'owned_processes',return_value=[{'pid':123,'endpoint':old['endpoint']}]),patch.object(browser_reader,'debug_info',return_value=fresh),patch.object(browser_reader,'subprocess') as processes:
    session=browser_reader.existing_session(profile)
    self.assertEqual(session['websocket'],fresh['websocket']);self.assertFalse(session['confirmed']);processes.Popen.assert_not_called()
   self.assertEqual(json.loads((profile/'.reader-session.json').read_text())['websocket'],fresh['websocket'])

 def test_recovers_missing_record_and_rejects_unrelated_port(self):
  with tempfile.TemporaryDirectory() as root:
   profile=Path(root);fresh={'endpoint':'http://127.0.0.1:9372','websocket':'ws://127.0.0.1:9372/devtools/browser/fresh'}
   with patch.object(browser_session,'owned_processes',return_value=[{'pid':123,'endpoint':fresh['endpoint']}]),patch.object(browser_reader,'debug_info',return_value=fresh):self.assertIsNotNone(browser_reader.existing_session(profile))
   (profile/'.reader-session.json').write_text(json.dumps({**fresh,'websocket':'old','confirmed':True}))
   with patch.object(browser_session,'owned_processes',return_value=[]),patch.object(browser_reader,'debug_info',return_value=fresh):self.assertIsNone(browser_reader.existing_session(profile))

 def test_process_discovery_requires_current_user_exact_profile_and_loopback(self):
  if os.name=='nt':self.skipTest('POSIX process fixture')
  with tempfile.TemporaryDirectory(prefix='profile with spaces ') as root:
   uid=os.getuid();chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
   base=f'{uid} 123 {chrome} --user-data-dir={root} --remote-debugging-address=127.0.0.1 --remote-debugging-port=9371'
   rows=[base,base.replace('123','124',1).replace(root,root+'-other'),base.replace(str(uid)+' ',str(uid+1)+' ',1),base.replace('127.0.0.1','0.0.0.0')]
   with patch.object(browser_session.subprocess,'run',side_effect=[Mock(stdout='123\n124\n'),Mock(stdout='\n'.join(rows))]):
    self.assertEqual(browser_session.owned_processes(root,chrome),[{'pid':123,'endpoint':'http://127.0.0.1:9371'}])

 def test_quoted_profile_arguments_and_active_port_nonce(self):
  self.assertEqual(browser_session.argument('--user-data-dir="C:\\Users\\Example Person\\profile" --remote-debugging-port=123','user-data-dir'),'C:\\Users\\Example Person\\profile')
  with tempfile.TemporaryDirectory() as root:
   profile=Path(root);(profile/'DevToolsActivePort').write_text('9371\n/devtools/browser/fresh\n')
   fresh={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/fresh'}
   self.assertEqual(browser_session.active_port_session(profile,Mock(return_value=fresh)),fresh)
   self.assertIsNone(browser_session.active_port_session(profile,Mock(return_value={**fresh,'websocket':fresh['websocket']+'-other'})))

 def test_start_reuses_recovered_browser_without_launching_another(self):
  with tempfile.TemporaryDirectory() as root:
   profile=Path(root);session={'endpoint':'http://127.0.0.1:9371','websocket':'ws://127.0.0.1:9371/devtools/browser/fresh','confirmed':False}
   with patch.object(browser_session,'discover',return_value=session),patch.object(browser_reader.subprocess,'Popen') as start:
    self.assertEqual(browser_reader.start_or_reuse_browser('about:blank',profile,threading.Event())['websocket'],session['websocket']);start.assert_not_called()

if __name__=='__main__':unittest.main()
