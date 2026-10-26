import io,json,os,tempfile,unittest,uuid,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from secretary import ai,model_api
from secretary.server import Service

class APITests(unittest.TestCase):
    def config(self,root):return model_api.prepare(root,{'base_url':'https://example.com/v1','model':'test-model','api_key':uuid.uuid4().hex,'vision':True,'json_mode':True})

    def test_write_only_key_endpoint_change_and_backup_exclusion(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);model_api.write(root,config);public=model_api.public(root)
            self.assertTrue(public['has_key']);self.assertNotIn('api_key',public);self.assertNotIn(config['api_key'],json.dumps(public))
            if os.name!='nt':self.assertEqual((Path(root)/model_api.NAME).stat().st_mode&0o777,0o600)
            self.assertEqual(model_api.prepare(root,{})['api_key'],config['api_key'])
            with self.assertRaises(ValueError):model_api.prepare(root,{'base_url':'https://other.example.com/v1'})
            with self.assertRaises(ValueError):model_api.prepare(root,{'base_url':'http://remote.example.com'})
            service=Service(root)
            try:
                service.archive.add('Synthetic note','Synthetic body')
                service.save_settings({'backend':'api','auto_ai':False,'model_api':{}})
                self.assertEqual(service.model_backend()['api_key'],config['api_key'])
                with zipfile.ZipFile(io.BytesIO(service.backup())) as backup:
                    self.assertFalse(any(model_api.NAME in name for name in backup.namelist()))
                    self.assertTrue(all(config['api_key'].encode() not in backup.read(name) for name in backup.namelist()))
                before=(Path(root)/model_api.NAME).read_bytes()
                with self.assertRaises(ValueError):service.save_settings({'backend':'api','auto_ai':False,'capture_scope':'invalid','model_api':{'model':'different'}})
                self.assertEqual((Path(root)/model_api.NAME).read_bytes(),before)
            finally:service.close()

    def test_http_payload_images_json_mode_and_sanitized_errors(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);opener=Mock()
            response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'Synthetic answer'},'finish_reason':'stop'}]}).encode())
            opener.open.return_value=response
            with patch.object(model_api.urllib.request,'build_opener',return_value=opener):
                answer=model_api.complete(config,'仅输出 JSON',[{'media':'image/jpeg','data':'c3ludGhldGlj'}])
            self.assertEqual(answer,'Synthetic answer')
            request=opener.open.call_args.args[0];payload=json.loads(request.data)
            self.assertEqual(request.full_url,'https://example.com/v1/chat/completions')
            self.assertEqual(request.get_header('Authorization'),'Bearer '+config['api_key'])
            self.assertEqual(payload['messages'][1]['content'][1]['type'],'image_url');self.assertNotIn('tools',payload)
            self.assertEqual(payload['response_format'],{'type':'json_object'})
            opener.open.side_effect=HTTPError(request.full_url,401,'Unauthorized',{},io.BytesIO(config['api_key'].encode()))
            with patch.object(model_api.urllib.request,'build_opener',return_value=opener):
                with self.assertRaises(RuntimeError) as error:model_api.complete(config,'Test',[])
            self.assertNotIn(config['api_key'],str(error.exception))

    def test_worker_uses_stdin_for_keys_and_supports_cancellation(self):
        with tempfile.TemporaryDirectory() as root:
            config=self.config(root);proc=Mock();proc.communicate.return_value=(json.dumps({'answer':'OK'}),'')
            with patch.object(ai.subprocess,'Popen',return_value=proc) as popen:
                self.assertEqual(ai.run('Test',config),'OK')
            self.assertNotIn(config['api_key'],json.dumps(popen.call_args.args[0]));self.assertIn(config['api_key'],proc.communicate.call_args.args[0])
            def cancel(*args,**kwargs):ai.cancel_all();return json.dumps({'answer':'late'}),''
            proc.communicate.side_effect=cancel
            with patch.object(ai.subprocess,'Popen',return_value=proc),patch('secretary.capture_worker.terminate_job'):
                with self.assertRaisesRegex(RuntimeError,'停止'):ai.run('Test',config)

    def test_text_model_keeps_images_unread_without_erasing_previous_vision(self):
        config={**model_api.DEFAULT,'vision':False}
        with patch.object(ai,'run',return_value=json.dumps({'summary':'Based on supplied text only','tags':[]})) as run:
            fields,_=ai.analyze_material('Some user annotation','Title',config,[{'name':'example.png'}],'Scope')
        self.assertIn('未识别',fields['summary']);self.assertNotIn('vision_text',fields)
        self.assertFalse(run.call_args.kwargs.get('images'))
