import io,json,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from secretary import ai,background_process,capture_worker

class BackgroundProcessTest(unittest.TestCase):
 def test_windows_hides_console_and_wrapper_windows_without_using_a_shell(self):
  with patch.object(background_process.sys,'platform','win32'),patch.multiple(subprocess,STARTUPINFO=lambda:SimpleNamespace(dwFlags=0),STARTF_USESHOWWINDOW=1,SW_HIDE=0,CREATE_NO_WINDOW=0x08000000,create=True):
   options=background_process.hidden_console()
  self.assertEqual(options['creationflags'],0x08000000)
  self.assertEqual(options['startupinfo'].dwFlags,1);self.assertEqual(options['startupinfo'].wShowWindow,0)
  self.assertNotIn('shell',options)
 def test_other_platforms_keep_their_process_session_behavior(self):
  for platform in ('darwin','linux'):
   with patch.object(background_process.sys,'platform',platform):self.assertEqual(background_process.hidden_console(),{})
 def process(self,output):
  proc=Mock();proc.returncode=0;proc.poll.return_value=0;proc.communicate.return_value=(output,'');proc.stdin=io.StringIO();proc.stdout=io.StringIO();proc.stderr=io.StringIO();return proc
 def test_cli_model_launch_preserves_prompt_and_captures_output_in_background(self):
  output=json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Fixture answer'}})
  proc=self.process(output)
  with patch.object(ai.network,'child_env',return_value={}),patch.object(ai,'executable',return_value='fixture-codex'),patch.object(ai,'hidden_console',return_value={'creationflags':123}),patch.object(ai.subprocess,'Popen',return_value=proc) as launch:
   self.assertEqual(ai.run('Private fixture prompt','codex'),'Fixture answer')
  self.assertEqual(launch.call_args.kwargs['creationflags'],123);self.assertIs(launch.call_args.kwargs['stdout'],subprocess.PIPE)
  proc.communicate.assert_called_once_with('Private fixture prompt',timeout=240)
 def test_api_worker_uses_same_hidden_console_policy(self):
  proc=self.process('{"answer":"API fixture"}')
  with patch.object(ai,'hidden_console',return_value={'creationflags':123}),patch.object(ai.subprocess,'Popen',return_value=proc) as launch:
   self.assertEqual(ai.run('Fixture prompt',{'base_url':'https://example.com','model':'fixture'}),'API fixture')
  self.assertEqual(launch.call_args.kwargs['creationflags'],123)
 def test_capture_worker_launch_uses_hidden_policy_and_keeps_result_channel(self):
  proc=self.process('');proc.stdout=io.StringIO('{"type":"result","result":{"text":"Fixture capture"}}\n')
  with patch.object(capture_worker,'hidden_console',return_value={'creationflags':123}),patch.object(capture_worker.subprocess,'Popen',return_value=proc) as launch:
   result=capture_worker.run('generic','https://example.com',Path('fixture-profile'),lambda *args:None,threading.Event(),threading.Event())
  self.assertEqual(result,{'text':'Fixture capture'});self.assertEqual(launch.call_args.kwargs['creationflags'],123)
 @unittest.skipUnless(sys.platform=='win32','Requires actual Windows process creation')
 def test_real_windows_console_and_cmd_wrapper_remain_consoleless(self):
  with tempfile.TemporaryDirectory(prefix='stellar background ') as root:
   script=Path(root)/'probe.py';script.write_text("import ctypes,json,sys\nprint(json.dumps({'console':bool(ctypes.windll.kernel32.GetConsoleWindow()),'input':sys.stdin.read()},ensure_ascii=False))\n",encoding='utf-8')
   wrapper=Path(root)/'probe.cmd';wrapper.write_text('@echo off\r\n"'+sys.executable+'" "'+str(script)+'"\r\n',encoding='utf-8')
   for command in ([sys.executable,str(script)],[str(wrapper)]):
    result=subprocess.run(command,input='Fixture 中文 input',text=True,encoding='utf-8',capture_output=True,timeout=15,env={**__import__('os').environ,'PYTHONIOENCODING':'utf-8'},**background_process.hidden_console())
    self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout)
    self.assertFalse(value['console']);self.assertEqual(value['input'],'Fixture 中文 input')
