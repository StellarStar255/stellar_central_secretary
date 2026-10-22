import tempfile
import unittest
import uuid
from urllib.parse import urlunsplit
from unittest.mock import Mock, patch
from secretary import network
from secretary.core import Archive
from secretary.retry_summary import retry


def authenticated_proxy(port):
    # Generate a throwaway credential solely to test redaction; never connects.
    return urlunsplit(('http', 'test-user:'+uuid.uuid4().hex+'@127.0.0.1:'+str(port), '', '', ''))


class NetworkTest(unittest.TestCase):
    def test_preserves_explicit_live_proxy_and_redacts_password(self):
        with patch.object(network, 'local_proxy_alive', return_value=True), patch.object(network, 'running_proxy_candidates') as discover:
            env = network.child_env({'https_proxy':authenticated_proxy(1234), 'CLAUDECODE':'1'})
        discover.assert_not_called()
        self.assertNotIn('CLAUDECODE', env)
        self.assertEqual(env['HTTPS_PROXY'], env['http_proxy'])
        self.assertEqual(network.describe(env), 'http://127.0.0.1:1234')
        self.assertIn('127.0.0.1', env['NO_PROXY'])

    def test_replaces_refused_proxy_only_with_verified_candidate(self):
        with patch.object(network, 'local_proxy_alive', return_value=False), patch.object(network.urllib.request, 'getproxies', return_value={}), patch.object(network, 'running_proxy_candidates', return_value=['http://127.0.0.1:1000','http://127.0.0.1:10808']), patch.object(network, 'http_proxy_works', side_effect=[False,True]):
            env = network.child_env({'https_proxy':'http://127.0.0.1:7897','ALL_PROXY':'socks5://127.0.0.1:7897'})
        self.assertEqual(env['https_proxy'], 'http://127.0.0.1:10808')
        self.assertNotIn('ALL_PROXY', env)

    def test_refused_proxy_without_replacement_is_actionable(self):
        with patch.object(network, 'local_proxy_alive', return_value=False), patch.object(network.urllib.request, 'getproxies', return_value={}), patch.object(network, 'running_proxy_candidates', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, '127.0.0.1:7897.*没有运行'):
                network.child_env({'https_proxy':authenticated_proxy(7897)})

    def test_permission_denial_is_not_dead_proxy(self):
        with patch.object(network.socket, 'create_connection', side_effect=PermissionError()):
            self.assertTrue(network.local_proxy_alive('http://127.0.0.1:7897'))

    def test_discovery_excludes_other_services(self):
        output='p1\ncPython\nf3\nn127.0.0.1:8768\np2\ncxray\nf4\nn127.0.0.1:10808\np3\ncGoogle Chrome\nf5\nn127.0.0.1:5432\n'
        with patch.object(network.subprocess, 'run', return_value=Mock(stdout=output)):
            self.assertEqual(network.running_proxy_candidates(), ['http://127.0.0.1:10808'])


class SummaryRetryTest(unittest.TestCase):
    def test_uses_stored_text_and_preserves_it_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            item_id,_=archive.add('原始标题','正文应当完整保留用于全文检索。')
            archive.update(item_id,state='error',error='旧错误')
            with patch('secretary.ai.summarize',side_effect=RuntimeError('模型未连接')) as summarize:
                with self.assertRaisesRegex(RuntimeError,'模型未连接'):retry(archive,item_id)
            self.assertEqual(summarize.call_args.args[0],archive.get(item_id)['text'])
            self.assertEqual(archive.get(item_id)['state'],'error')
            with patch('secretary.ai.summarize',return_value={'summary':'已生成摘要','tags':['检索'],'category':'研究'}):
                result=retry(archive,item_id)
            self.assertEqual(result['state'],'ready')
            self.assertEqual(result['summary'],'已生成摘要')
            self.assertTrue(archive.retrieve('全文检索'))

    def test_busy_source_does_not_start_duplicate_model(self):
        with tempfile.TemporaryDirectory() as root:
            archive=Archive(root)
            item_id,_=archive.add('标题','正在处理的正文')
            archive.update(item_id,state='processing')
            with patch('secretary.ai.summarize') as summarize:
                with self.assertRaisesRegex(RuntimeError,'正在处理'):retry(archive,item_id)
            summarize.assert_not_called()


if __name__=='__main__':unittest.main()
