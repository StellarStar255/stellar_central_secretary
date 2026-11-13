import tempfile
import unittest
from unittest.mock import patch
from secretary.note_dates import resolve
from secretary.server import Service
from secretary import ai


class NoteDatesTests(unittest.TestCase):
    def test_weekdays_and_year_boundary(self):
        base='2026-11-13T16:20:00+08:00'
        for phrase,expected in [('周六','2026年11月14日'),('本周一','2026年11月9日'),('下周六','2026年11月21日'),('下下星期六','2026年11月28日'),('明天','2026年11月14日')]:
            with self.subTest(phrase=phrase):self.assertIn(expected,resolve(phrase+'上午11:00去复查',base))
        self.assertIn('2027年1月1日',resolve('明天上午去复查','2026-12-31T23:59:00+08:00'))
        self.assertIn('2026年11月14日',resolve('周六上午去复查','2026-11-14T00:01:00+08:00'))

    def test_ambiguous_recurring_and_explicit_dates_are_preserved(self):
        for text in ['每周六上午去复查','每个星期六上午去复查','上周六上午去复查','比如周六上午去复查','周六上午去复查？','2026年11月14日周六上午复查','周六的含义','“周六上午复查”']:
            with self.subTest(text=text):self.assertEqual(resolve(text,'2026-11-13T16:20:00+08:00'),'')

    def test_archive_preserves_original_and_indexes_fixed_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                text='建档：\n周六上午11:00带测试对象去复查'
                item=service.ingest({'text':text,'title':text.splitlines()[1],'archive_only':True})['item']
                self.assertEqual(item['text'],text)
                self.assertIn('【日期解析】',item['user_context'])
                dated=item['user_context'].split('\n',2)[-1]
                self.assertIn('年',item['title']);self.assertEqual(item['state'],'saved')
                self.assertTrue(service.archive.retrieve(dated.split('（')[0].splitlines()[-1]))
                with patch.object(ai,'summarize',return_value={'summary':'安排复查。','tags':[]}) as summarize:
                    fields=ai.summary_fields(item,'codex')
                self.assertIn(dated.split('\n')[-1],fields['summary']);self.assertIn(dated,summarize.call_args.args[0])
                self.assertNotIn('网页正文',fields['summary'])
                repeated=service.ingest({'text':text,'title':'Other title','archive_only':True})['item']
                self.assertEqual(repeated['user_context'],item['user_context'])
                self.assertEqual(repeated['created'],item['created'])
            finally:service.close()

    def test_summary_deduplicates_date_interpretation_without_losing_extra_details(self):
        from secretary.note_dates import date_summary
        context=resolve('建档：\n明天上午11:00带测试对象去复查','2026-11-13T08:00:00+08:00')
        resolved=context.split('\n')[-1]
        generated=resolved.replace('11:00带','11:00，带')+'。'
        legacy='【日期解析】\n'+resolved+'\n\n'+generated+'\n\n地点：测试门诊。'
        cleaned=date_summary(legacy,context)
        self.assertEqual(cleaned.count('2026年11月14日'),1)
        self.assertIn('地点：测试门诊。',cleaned)
        self.assertNotIn('【日期解析】',cleaned)
        self.assertEqual(date_summary(cleaned,context),cleaned)
        self.assertEqual(date_summary('普通摘要',''),'普通摘要')

    def test_legacy_summary_is_cleaned_on_read_without_rewriting_stored_record(self):
        from secretary.library import dashboard,query
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                item=service.ingest({'text':'建档：\n周六上午11:00测试对象复查','archive_only':True})['item']
                resolved=item['user_context'].split('\n')[-1]
                legacy='【日期解析】\n'+resolved+'\n\n'+resolved+'。'
                service.archive.update(item['id'],state='ready',summary=legacy)
                for record in [service.archive.get(item['id']),service.archive.list()[0],query(service.archive)['items'][0],dashboard(service.archive,[item['id']])['items'][0]]:
                    self.assertEqual(record['summary'].count(resolved),1)
                    self.assertEqual(record['created'],item['created'])
                with service.archive.db() as db:self.assertEqual(db.execute('SELECT summary FROM items WHERE id=?',(item['id'],)).fetchone()[0],legacy)
                with patch.object(ai,'summarize',return_value={'summary':resolved+'。','tags':[]}):fields=ai.summary_fields(service.archive.get(item['id']),'codex')
                self.assertEqual(fields['summary'].count(resolved),1)
            finally:service.close()

    def test_optional_speaker_does_not_duplicate_summary_or_break_date_order(self):
        from secretary.note_dates import date_summary,arrangement_text
        original='我周六上午11:00带测试对象去复查'
        context=resolve(original,'2026-11-13T08:00:00+08:00')
        resolved=context.split('\n',2)[-1]
        self.assertNotIn('我2026年',resolved)
        legacy_context=context[:context.rfind('\n')+1]+'我'+resolved
        cleaned=date_summary('我'+resolved+'\n\n'+resolved+'。',legacy_context)
        self.assertEqual(cleaned.count('2026年11月14日'),1)
        self.assertEqual(arrangement_text('我老婆周六上午复查'),'我老婆周六上午复查')
        self.assertEqual(arrangement_text('我们周六上午复查'),'我们周六上午复查')

    def test_contextual_save_uses_original_message_date_and_rejects_bad_reference(self):
        with tempfile.TemporaryDirectory() as root:
            service=Service(root);service.archive.configure('codex',False)
            try:
                reference='2025-12-31T23:30:00+00:00'
                item=service.ingest({'text':'明天上午去复查 contextual','archive_only':True,'note_reference':reference})['item']
                from datetime import datetime, timedelta
                expected=datetime.fromisoformat(reference).astimezone().date()+timedelta(days=1)
                self.assertIn(f'{expected.year}年{expected.month}月{expected.day}日',item['user_context'])
                before=len(service.archive.list())
                for invalid in ['broken','2025-12-31',{},'9999-01-01T00:00:00+00:00']:
                    with self.assertRaises(ValueError):service.ingest({'text':'明天上午去复查 invalid','note_reference':invalid})
                self.assertEqual(len(service.archive.list()),before)
            finally:service.close()
