import json,tempfile,unittest
from unittest.mock import patch
from secretary import ai
from secretary.server import Service
from secretary.backup_import import import_backup

class LinkContextTests(unittest.TestCase):
    def test_failed_fetch_keeps_annotation_without_browser_or_cloud(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                with patch('secretary.server.fetch_page',side_effect=OSError('Synthetic inaccessible page')),patch.object(service,'start_capture') as browser,patch.object(ai,'run') as model:
                    item=service.ingest({'url':'https://example.com/private','context':'Quantization test machine link:'})['item']
                self.assertEqual(item['title'],'Quantization test machine link')
                self.assertEqual(item['text'],'');self.assertEqual(item['user_context'],'Quantization test machine link:')
                self.assertFalse(browser.called);self.assertFalse(model.called)
                self.assertEqual(service.archive.retrieve('Quantization machine')[0]['item_id'],item['id'])
                self.assertEqual(service.archive.list(q='machine Quantization')[0]['id'],item['id'])
                with patch.object(ai,'summarize',return_value={'summary':'A user-described test machine link.','tags':['Testing']}) as summarize:
                    fields=ai.summary_fields(item,'codex')
                self.assertIn('尚未读取网页正文',fields['summary']);self.assertIn('非网页正文',summarize.call_args.args[0])
                self.assertNotIn('Synthetic inaccessible page',summarize.call_args.args[0])
                service.archive.replace_capture(item['id'],'Loaded page','A real loaded webpage containing independently captured text.')
                self.assertEqual(service.archive.get(item['id'])['user_context'],item['user_context'])
                with tempfile.TemporaryDirectory() as restored_root:
                    restored=Service(restored_root)
                    try:
                        import_backup(restored.archive,service.backup())
                        self.assertEqual(restored.archive.list()[0]['user_context'],item['user_context'])
                    finally:restored.close()
            finally:service.close()

    def test_repeated_link_merges_annotations_without_replacing_page(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                with patch('secretary.server.fetch_page',return_value=('Existing page body','')):
                    first=service.ingest({'url':'https://example.com/repeat','context':'First context\n\nSecond paragraph'})['item']
                    service.ingest({'url':first['url'],'context':first['user_context']})
                    service.ingest({'url':first['url'],'context':'Another annotation'})
                self.assertEqual(len(service.archive.list()),1)
                saved=service.archive.get(first['id']);self.assertEqual(saved['text'],'Existing page body')
                self.assertEqual(saved['user_context'],first['user_context']+'\n\nAnother annotation')
                with self.assertRaises(ValueError):service.ingest({'url':first['url'],'context':'x'*20001})
                self.assertEqual(service.archive.get(first['id']),saved)
            finally:service.close()
