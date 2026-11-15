import copy,tempfile,unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.extension_chat import ingest

class ExtensionChatTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Service(self.temp.name);self.s.archive.configure('codex',False)
        self.chat={'id':'current','title':'Current','updated':1,'messages':[{'id':'question','role':'user','text':'Existing question'}]}
        self.s.chat_history({'conversations':[self.chat],'activeId':'current'})
        self.body={'url':'https://example.com/article','title':'Synthetic article','text':'Synthetic captured body','extension_event_id':'a'*32,'browser_extension':True}
    def tearDown(self):self.s.close();self.temp.cleanup()
    def messages(self):return self.s.chat_history()['conversations'][0]['messages']
    def test_capture_and_retry_persist_one_receipt_in_current_chat(self):
        result=ingest(self.s,self.body);self.assertTrue(result['created']);messages=self.messages()
        self.assertEqual(len(messages),2);self.assertEqual(messages[-1]['items'],[result['item']['id']]);self.assertTrue(messages[-1]['externalArchive'])
        ingest(self.s,self.body);self.assertEqual(len(self.messages()),2)
        # A later capture of the same saved page gives an explicit duplicate receipt.
        result=ingest(self.s,{**self.body,'extension_event_id':'b'*32})
        self.assertFalse(result['created']);self.assertIn('已存在',self.messages()[-1]['text'])
    def test_stale_client_save_cannot_drop_receipt(self):
        ingest(self.s,self.body)
        stale=copy.deepcopy(self.chat);stale['updated']=10**14;stale['messages'].append({'id':'new-question','role':'user','text':'Follow-up'})
        self.s.chat_history({'activeId':'current','conversations':[stale]})
        self.assertTrue(any(m.get('externalArchive') for m in self.messages()))
        self.assertTrue(any(m['id']=='new-question' for m in self.messages()))
    def test_different_body_is_not_announced_as_saved(self):
        self.s.ingest({**self.body,'text':'Old content'})
        result=ingest(self.s,self.body);self.assertEqual(result['item']['text'],'Old content');self.assertEqual(len(self.messages()),1)
    def test_no_active_chat_creates_a_persisted_capture_chat(self):
        self.s.chat_history({'activeId':'','conversations':[]})
        ingest(self.s,self.body);saved=self.s.chat_history()
        new=next(c for c in saved['conversations'] if c['id']==saved['activeId'])
        self.assertEqual(new['messages'][0]['items'],[self.s.archive.list()[0]['id']])
    def test_switching_chat_during_ingest_keeps_original_target(self):
        original=self.s.ingest
        def switch(body):
            self.s.chat_history({'activeId':'other','conversations':[{'id':'other','title':'Other','messages':[],'updated':2}]})
            return original(body)
        with patch.object(self.s,'ingest',side_effect=switch):ingest(self.s,self.body)
        saved=self.s.chat_history();self.assertEqual(saved['activeId'],'other')
        self.assertEqual(len(next(c for c in saved['conversations'] if c['id']=='current')['messages']),2)
        self.assertEqual(len(next(c for c in saved['conversations'] if c['id']=='other')['messages']),0)
    def test_receipt_write_error_does_not_report_archive_failure(self):
        original=self.s.clean_chat_history
        def fail_new(result,*args):
            if any(m.get('externalArchive') for c in result['conversations'] for m in c['messages']):raise OSError('disk full')
            return original(result,*args)
        with patch.object(self.s,'clean_chat_history',side_effect=fail_new):result=ingest(self.s,self.body)
        self.assertTrue(result['created']);self.assertIn('chat_sync_error',result);self.assertEqual(self.s.archive.get(result['item']['id'])['text'],self.body['text'])

    def test_removing_receipt_preserves_unrelated_previous_question(self):
        from secretary.chat_cleanup import clean_chats
        result=ingest(self.s,self.body)
        cleaned,_=clean_chats(self.s.chat_history()['conversations'],[result['item']['id']],[])
        self.assertEqual(cleaned[0]['messages'],self.chat['messages'])

    def test_bookmark_saves_url_without_fetch_or_model_and_syncs_receipt(self):
        body={**self.body,'url':'https://excalidraw.com/','text':'','archive_only':True}
        with patch('secretary.server.fetch_page',side_effect=AssertionError('Must not fetch')),patch.object(self.s,'start_capture',side_effect=AssertionError('Must not capture')),patch.object(self.s,'queue',side_effect=AssertionError('Must not run model')):
            result=ingest(self.s,body)
        self.assertTrue(result['created']);self.assertTrue(result['chat_synced']);self.assertEqual(result['item']['text'],'')
        self.assertIn('链接已收藏',self.messages()[-1]['text'])
        # Bookmarking an existing full article preserves its content and summary.
        existing=self.s.ingest({'url':self.body['url'],'text':'Full original article','title':'Original'})['item']
        result=ingest(self.s,{**body,'url':existing['url'],'extension_event_id':'b'*32})
        self.assertTrue(result['chat_synced']);self.assertEqual(result['item']['text'],'Full original article');self.assertIn('已存在',self.messages()[-1]['text'])
    def test_exported_link_only_capture_imports_without_fetch(self):
        import base64,json
        capture={'url':'https://example.com/bookmark','title':'Bookmark','text':'','archive_only':True}
        with patch('secretary.server.fetch_page',side_effect=AssertionError('Must not fetch')),patch.object(self.s,'start_capture',side_effect=AssertionError('Must not capture')):
            result=self.s.ingest({'filename':'bookmark.knowledge.json','data':base64.b64encode(json.dumps(capture).encode()).decode()})
        self.assertEqual(result['item']['url'],capture['url']);self.assertEqual(result['item']['text'],'')

    def test_recapture_creates_new_record_and_leaves_trash_untouched(self):
        old=self.s.ingest({'url':self.body['url'],'text':'Unwanted old body','title':'Old'})['item']
        self.s.archive.trash_item(old['id'],old['updated'])
        before=self.s.archive.get(old['id'],include_trashed=True)
        result=ingest(self.s,self.body)
        self.assertTrue(result['created']);self.assertTrue(result['chat_synced'])
        self.assertNotEqual(result['item']['id'],old['id']);self.assertEqual(result['item']['text'],self.body['text'])
        self.assertEqual(self.s.archive.get(old['id'],include_trashed=True),before)
        repeated=ingest(self.s,{**self.body,'extension_event_id':'b'*32})
        self.assertFalse(repeated['created']);self.assertEqual(repeated['item']['id'],result['item']['id'])
        self.assertEqual(len(self.s.archive.list()),1);self.assertEqual(len(self.s.archive.trash_items()),1)

    def test_repeated_bookmark_delete_and_recapture_keeps_all_trashed_rows(self):
        body={**self.body,'text':'','archive_only':True}
        for n in range(3):
            result=ingest(self.s,{**body,'extension_event_id':str(n)*32})
            self.assertTrue(result['created'])
            item=result['item'];self.s.archive.trash_item(item['id'],item['updated'])
        self.assertEqual(len(self.s.archive.trash_items()),3)
        self.assertEqual(len({i['id'] for i in self.s.archive.trash_items()}),3)
        self.assertEqual(len(self.s.archive.list()),0)
