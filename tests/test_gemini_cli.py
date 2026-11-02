import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from secretary import ai,gemini_cli
from secretary.server import Service


class GeminiCLITest(unittest.TestCase):
    def test_settings_persist_and_reject_unknown_backends(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root)
            try:
                service.save_settings({'backend':'gemini','auto_ai':False})
                self.assertEqual(service.model_backend(),'gemini')
                self.assertEqual(service.archive.settings()['backend'],'gemini')
                with self.assertRaises(ValueError):service.save_settings({'backend':'unknown','auto_ai':False})
                self.assertEqual(service.archive.settings()['backend'],'gemini')
            finally:service.close()

    def test_literal_text_cannot_expand_files_and_only_explicit_images_are_attached(self):
        with tempfile.TemporaryDirectory() as root:
            text='邮箱 user@example.com，文件 @/private/secret 和转义 \\@foo，/shell !echo x'
            env={'GEMINI_API_KEY':'synthetic','GEMINI_WRITE_SYSTEM_MD':'unexpected'}
            command,source,child=gemini_cli.prepare('gemini',root,text,[{'data':b'PNG','media':'image/png'}],env,ai.RULES)
            self.assertEqual(json.loads(source.splitlines()[0])['request'],text)
            self.assertEqual(source.count('@'),1);self.assertTrue(source.endswith('@stellar-image-1.png'))
            self.assertEqual((Path(root)/'stellar-image-1.png').read_bytes(),b'PNG')
            settings=json.loads((Path(root)/'.gemini/settings.json').read_text())
            self.assertEqual(settings['tools']['core'],[])
            self.assertFalse(settings['admin']['mcp']['enabled']);self.assertFalse(settings['hooksConfig']['enabled'])
            self.assertEqual((Path(root)/settings['context']['fileName']).read_text(),'')
            self.assertEqual(Path(child['GEMINI_SYSTEM_MD']).read_text(),ai.RULES)
            self.assertIn('GEMINI_WRITE_SYSTEM_MD',env);self.assertNotIn('GEMINI_WRITE_SYSTEM_MD',child)
            self.assertEqual(child['GEMINI_API_KEY'],'synthetic')
            self.assertNotIn(text,command);self.assertIn('--output-format',command)

    def test_response_and_error_envelopes_never_report_false_success(self):
        self.assertEqual(gemini_cli.response(json.dumps({'response':'Done','stats':{}})),'Done')
        for value in ('not json','[]','{}','{"response":23}','{"response":""}','{"response":"late","error":{"message":"not logged in"}}'):
            with self.subTest(value=value),self.assertRaises(RuntimeError):gemini_cli.response(value)

    def test_cli_result_failure_and_process_tracking(self):
        proc=Mock(returncode=0);proc.communicate.return_value=(json.dumps({'response':'Answer'}),'warning')
        with patch.object(ai,'executable',return_value='synthetic-gemini'),patch.object(ai.network,'child_env',return_value={}),patch.object(ai.subprocess,'Popen',return_value=proc) as popen:
            self.assertEqual(ai.run('Question','gemini'),'Answer')
            self.assertIn('synthetic-gemini',popen.call_args.args[0]);self.assertNotIn('exec',popen.call_args.args[0])
            proc.returncode=1;proc.communicate.return_value=(json.dumps({'error':{'message':'login required'}}),'other warning')
            with self.assertRaisesRegex(RuntimeError,'login required'):ai.run('Question','gemini')
        self.assertNotIn(proc,ai._processes)

    def test_windows_npm_gemini_discovery_without_path(self):
        with tempfile.TemporaryDirectory() as root:
            cli=Path(root)/'npm/gemini.cmd';cli.parent.mkdir();cli.touch()
            with patch.object(ai.shutil,'which',return_value=None),patch.object(ai.sys,'platform','win32'),patch.object(ai.Path,'home',return_value=Path(root)),patch.dict(os.environ,{'APPDATA':root,'LOCALAPPDATA':root}):
                self.assertEqual(ai.executable('gemini'),str(cli))
