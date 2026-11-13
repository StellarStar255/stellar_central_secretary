import tempfile
import unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.archived_arrangements import lookup


class ArchivedArrangementsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
        self.service.archive.configure('codex',False)
        self.text='周六上午11:00带测试对象去复查'
        self.item=self.service.ingest({'text':self.text,'archive_only':True})['item']

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def test_exact_arrangement_reads_live_record_without_any_model(self):
        with patch.object(self.service,'model_backend',side_effect=AssertionError('No model required')):
            for _ in range(2):
                result=self.service.ask_library(self.text,context=[{'statement':self.text}])
                self.assertEqual(result['timings']['model_calls'],0)
                self.assertTrue(result['timings']['archive_match'])
                self.assertIn(self.item['user_context'].split('\n',2)[-1],result['answer'])
                self.assertEqual(result['sources'][0]['item_id'],self.item['id'])
        self.service.archive.update(self.item['id'],title='Updated arrangement')
        result=self.service.ask_library(self.text)
        self.assertEqual(result['sources'][0]['title'],'Updated arrangement')
        self.service.archive.update(self.item['id'],text='下周一下午改期复查')
        self.assertIsNone(lookup(self.service.archive,self.text))
        self.assertIsNone(lookup(self.service.archive,'下周一下午改期复查'))

    def test_trash_force_refresh_conditions_and_uncertain_matches_do_not_shortcut(self):
        with patch.object(self.service,'model_backend',side_effect=ValueError('Normal model path')):
            with self.assertRaisesRegex(ValueError,'Normal model path'):self.service.ask_library(self.text,force_refresh=True)
        self.assertIsNone(lookup(self.service.archive,self.text+'吗？'))
        self.assertIsNone(lookup(self.service.archive,'周六上午10:00带测试对象去复查'))
        self.service.trash_item(self.item['id'],self.service.archive.get(self.item['id'])['updated'])
        self.assertIsNone(lookup(self.service.archive,self.text))

    def test_old_timetable_condition_does_not_expand_an_exact_record_confirmation(self):
        table,_=self.service.archive.add('Synthetic timetable','周六上午课程表内容')
        with patch.object(self.service,'model_backend',side_effect=AssertionError('No model or old timetable review')):
            result=self.service.ask_library(self.text,
                history=[{'question':'周六有课吗？','answer':'旧课程表需要按你指定的条件判断。[1]','source_ids':[table]}],
                context=[{'statement':'这个课程表就是她的，依据这张表判断','source_ids':[table]}])
        self.assertTrue(result['timings']['archive_match'])
        self.assertEqual([source['item_id'] for source in result['sources']],[self.item['id']])
        self.assertNotIn('课程',result['answer'])
        self.assertNotIn('冲突',result['answer'])

    def test_header_matching_and_conflicting_annotations_fall_back(self):
        text='建档：\n'+self.text+' header'
        item=self.service.ingest({'text':text,'archive_only':True})['item']
        self.assertIsNotNone(lookup(self.service.archive,self.text+' header'))
        from secretary.notes import set_note
        set_note(self.service.archive,item['id'],'后来修改了安排，需要核对',[],0)
        self.assertIsNone(lookup(self.service.archive,self.text+' header'))

    def test_identical_duplicates_are_fast_but_different_dates_are_not(self):
        from datetime import datetime
        from secretary.note_dates import resolve
        raw='建档：\n'+self.text
        duplicate_id,_=self.service.archive.add('Duplicate',raw)
        self.service.archive.save_context(duplicate_id,resolve(raw,datetime.fromisoformat(self.item['created']).astimezone().isoformat()))
        duplicate=self.service.archive.get(duplicate_id)
        self.assertIsNotNone(lookup(self.service.archive,self.text))
        with self.service.archive.db() as db:
            import re
            from datetime import datetime,timedelta
            from secretary.note_dates import resolve
            day=re.search(r'\d{4}-\d{2}-\d{2}',duplicate['user_context']).group()
            reference=datetime.fromisoformat(day+'T00:00:00+00:00')+timedelta(days=7)
            context=resolve(duplicate['text'],reference.isoformat())
            db.execute('UPDATE items SET user_context=? WHERE id=?',(context,duplicate['id']))
        self.assertIsNone(lookup(self.service.archive,self.text))
