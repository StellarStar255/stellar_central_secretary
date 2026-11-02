import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from secretary import ai,model_api,network
from secretary.server import Service


class ModelProxyTest(unittest.TestCase):
    def test_custom_proxy_overrides_inherited_route_and_never_discovers_a_fallback(self):
        source={'HTTP_PROXY':'http://old.invalid:1234','ALL_PROXY':'socks5://old.invalid:12','NO_PROXY':'*'}
        with patch.object(network,'local_proxy_alive',return_value=True),patch.object(network,'running_proxy_candidates') as discover:
            env=network.child_env(source,{'mode':'custom','url':'http://127.0.0.1:4567/'})
        self.assertEqual(env['HTTPS_PROXY'],'http://127.0.0.1:4567')
        self.assertNotIn('ALL_PROXY',env);self.assertNotEqual(env['NO_PROXY'],'*')
        self.assertEqual(source['HTTP_PROXY'],'http://old.invalid:1234');discover.assert_not_called()
        with patch.object(network,'local_proxy_alive',return_value=False),patch.object(network,'running_proxy_candidates') as discover:
            with self.assertRaisesRegex(RuntimeError,'不会改用直连'):network.child_env(source,{'mode':'custom','url':'http://127.0.0.1:4567'})
            discover.assert_not_called()

    def test_direct_clears_all_proxy_variables_without_discovery(self):
        with patch.object(network.urllib.request,'getproxies') as system,patch.object(network,'running_proxy_candidates') as discover:
            env=network.child_env({key:'http://old.invalid:12' for key in network.PROXY_KEYS},{'mode':'direct'})
        self.assertTrue(all(key not in env for key in network.PROXY_KEYS));self.assertEqual(env['NO_PROXY'],'*')
        system.assert_not_called();discover.assert_not_called()

    def test_proxy_validation_rejects_unsupported_protocols_and_credentials(self):
        for url in ('','socks5://localhost:1080','https://localhost:7897','http://user:secret@localhost:1','http://localhost:0','http://localhost:65536','http://localhost:1/path','http://localhost:1?q=1','http://local host:1','http://localhost:1\nX'):
            with self.subTest(url=url),self.assertRaises(ValueError):network.proxy_config({'mode':'custom','url':url})
        self.assertEqual(network.proxy_config({'mode':'custom','url':'http://[::1]:7897/'}),{'mode':'custom','url':'http://[::1]:7897'})
        self.assertEqual(network.proxy_config({'mode':'direct','url':'ignored'}),{'mode':'direct','url':''})

    def test_settings_persist_and_unsaved_connection_test_does_not_change_them(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root)
            try:
                stored={'mode':'custom','url':'http://127.0.0.1:4567'}
                service.save_settings({'backend':'gemini','auto_ai':False,'model_proxy':stored})
                backend=service.model_backend();self.assertEqual(backend,'gemini');self.assertEqual(backend.proxy,stored)
                with patch.object(ai,'run',return_value='OK') as run:
                    self.assertTrue(service.test_model_connection({'backend':'claude','model_proxy':{'mode':'direct'}})['ok'])
                self.assertEqual(run.call_args.args[1].proxy,{'mode':'direct','url':''})
                self.assertLessEqual(run.call_args.kwargs['timeout'],60)
                self.assertEqual(service.archive.settings()['model_proxy'],stored)
                self.assertEqual(service.archive.settings()['backend'],'gemini')
                with patch.object(ai,'run',side_effect=RuntimeError('test failure')):
                    with self.assertRaisesRegex(RuntimeError,'test failure'):service.test_model_connection({'backend':'codex'})
                self.assertEqual(service.runtime()['answering'],0)
                with self.assertRaises(ValueError):service.save_settings({'backend':'codex','auto_ai':True,'model_proxy':{'mode':'custom','url':'socks5://localhost:1'}})
                self.assertEqual(service.archive.settings()['backend'],'gemini')
            finally:service.close()
            other=Service(root)
            try:self.assertEqual(other.archive.settings()['model_proxy'],stored)
            finally:other.close()

    def test_all_cli_backends_receive_the_selected_route_without_global_env_changes(self):
        for name in ai.CLI_BACKENDS:
            output={'codex':{'type':'item.completed','item':{'type':'agent_message','text':'OK'}},'claude':{'result':'OK'},'gemini':{'response':'OK'}}[name]
            proc=Mock(returncode=0);proc.communicate.return_value=(json.dumps(output),'')
            with self.subTest(backend=name),patch.object(ai,'executable',return_value='synthetic-cli'),patch.object(network,'local_proxy_alive',return_value=True),patch.object(ai.subprocess,'Popen',return_value=proc) as popen:
                self.assertEqual(ai.run('Connection test',ai.CLIBackend(name,{'mode':'custom','url':'http://127.0.0.1:4567'})),'OK')
                self.assertEqual(popen.call_args.kwargs['env']['HTTPS_PROXY'],'http://127.0.0.1:4567')

    def test_api_explicit_proxy_handler_and_local_endpoint_bypass(self):
        for base,mode,expected in [('https://example.com/v1','custom',{'http':'http://127.0.0.1:4567','https':'http://127.0.0.1:4567'}),('https://example.com/v1','direct',{}),('http://127.0.0.1:9999/v1','custom',{})]:
            config={**model_api.DEFAULT,'base_url':base,'use_key':False,'_proxy':{'mode':mode,'url':'http://127.0.0.1:4567'}}
            opener=Mock();opener.open.return_value=io.BytesIO(json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode())
            with self.subTest(base=base,mode=mode),patch.object(model_api.urllib.request,'build_opener',return_value=opener) as build:
                self.assertEqual(model_api.complete(config,'Test',[]),'OK')
                handlers=[handler for handler in build.call_args.args if isinstance(handler,model_api.urllib.request.ProxyHandler)]
                self.assertEqual(handlers[0].proxies,expected)

    def test_local_api_worker_ignores_an_unavailable_custom_proxy(self):
        proc=Mock();proc.communicate.return_value=(json.dumps({'answer':'OK'}),'')
        config={**model_api.DEFAULT,'base_url':'http://127.0.0.2:9999/v1','_proxy':{'mode':'custom','url':'http://127.0.0.1:1'}}
        with patch.object(network,'local_proxy_alive',return_value=False) as alive,patch.object(ai.subprocess,'Popen',return_value=proc) as popen:
            self.assertEqual(ai.run('Local test',config),'OK')
        alive.assert_not_called();self.assertEqual(popen.call_args.kwargs['env']['NO_PROXY'],'*')
