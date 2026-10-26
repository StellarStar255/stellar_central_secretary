import json,tempfile,time,unittest
from unittest.mock import patch
from secretary import ai,links
from secretary.server import Service
from secretary.backup_import import import_backup

def wait(service):
    deadline=time.monotonic()+5
    while service.runtime()['processing'] and time.monotonic()<deadline:time.sleep(.01)
    assert service.runtime()['processing']==0,'Grouped link job did not finish'

def fetch(url):
    if url.endswith('/read'):return 'Synthetic readable link content about quantization.',''
    raise OSError('Synthetic sign-in required')

class GroupLinkTests(unittest.TestCase):
    def test_one_archive_partial_read_scoped_summary_append_and_backup(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                urls=['https://example.com/read','https://example.com/login']
                with patch('secretary.server.fetch_page',side_effect=fetch):
                    result=service.ingest({'text':'Related quantization material\n'+'\n'.join(urls),'attachments':[],'links':urls});wait(service)
                item_id=result['item']['id'];item=service.archive.get(item_id)
                self.assertEqual(len(service.archive.list()),1)
                self.assertEqual([v['state'] for v in item['group_links']],['read','unread'])
                self.assertIn('Synthetic readable link content',item['text'])
                self.assertEqual(service.archive.retrieve('quantization')[0]['item_id'],item_id)
                answer=json.dumps({'summary':'A grouped source summary','tags':[],'answer':'The accessible source supports this. [1]'})
                with patch.object(ai,'run',return_value=answer) as model:
                    response=service.ask('Compare these sources',[item_id])
                self.assertEqual(model.call_count,1);self.assertIn('未读取来源仅保存链接',model.call_args.args[0])
                self.assertEqual(response['sources'][0]['item_id'],item_id)
                old_summary=service.archive.get(item_id)['summary']
                with patch('secretary.server.fetch_page',side_effect=fetch):
                    service.append_material(item_id,{'text':'More related links\n'+'\n'.join(urls),'expected_updated':service.archive.get(item_id)['updated'],'summarize':False});wait(service)
                item=service.archive.get(item_id);self.assertEqual(len(item['additions'][0]['links']),2)
                self.assertEqual(item['summary'],old_summary);self.assertEqual(len(service.archive.list()),1)
                with tempfile.TemporaryDirectory() as destination:
                    other=Service(destination)
                    try:
                        import_backup(other.archive,service.backup());restored=other.archive.get(other.archive.list()[0]['id'])
                        self.assertEqual(restored['group_links'],item['group_links']);self.assertEqual(restored['additions'][0]['links'],item['additions'][0]['links'])
                    finally:other.close()
            finally:service.close()

    def test_reread_preserves_previous_content_edits_and_visual_description(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                with patch('secretary.server.fetch_page',side_effect=fetch):
                    item=service.ingest({'text':'Related source','attachments':[],'links':['https://example.com/read']})['item'];wait(service)
                service.archive.update(item['id'],text='My edited archive text',vision_text='Existing image analysis')
                with patch('secretary.server.fetch_page',side_effect=OSError('Synthetic refresh failure')):
                    service.read_group_links(item['id']);wait(service)
                saved=service.archive.get(item['id'])
                self.assertEqual(saved['text'],'My edited archive text');self.assertEqual(saved['vision_text'],'Existing image analysis')
                self.assertIn('Synthetic readable',saved['group_links'][0]['text'])
            finally:service.close()

    def test_limits_credentials_and_local_links(self):
        wall=links.read(links.prepare(['https://example.com/login']),lambda url:('Please sign in to continue. '+'Login options '*15,''),lambda:False)
        self.assertEqual(wall[0]['state'],'unread');self.assertEqual(wall[0]['text'],'')
        self.assertEqual(links.extract('https://example.com/a\nhttps://example.com/a'),['https://example.com/a'])
        with self.assertRaises(ValueError):links.prepare(['https://example.com/'+str(n) for n in range(21)])
        from urllib.parse import urlsplit
        credential_fixture=urlsplit('https://example.com/')._replace(netloc=':'.join(('test-user','test-password'))+'@example.com').geturl()
        with self.assertRaises(ValueError):links.prepare([credential_fixture])
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                with patch('secretary.server.fetch_page') as network:
                    item=service.ingest({'text':'Local sources','attachments':[],'links':['http://127.0.0.1:9999/a','http://localhost:9999/b']})['item'];wait(service)
                self.assertFalse(network.called)
                self.assertTrue(all(v['state']=='unread' for v in service.archive.get(item['id'])['group_links']))
            finally:service.close()
