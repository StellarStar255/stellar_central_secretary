import tempfile
import unittest
from unittest.mock import patch

from secretary.archived_birthdays import lookup, date_identity
from secretary.server import Service
from secretary.notes import set_note


class BirthdayTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = Service(temp.name)
        self.addCleanup(self.service.close)
        self.archive = self.service.archive
        self.item = self.service.ingest({'text': '小林妈妈生日 农历2001年8月12日', 'archive_only': True})['item']

    def test_source_and_explicit_recheck(self):
        with patch.object(self.service, 'model_backend', side_effect=ValueError('model path')):
            for question in ('小林妈妈生日', '小林妈妈的生日是哪天？', '请问小林妈妈出生日期'):
                answer = self.service.ask_library(question)
                self.assertEqual(answer['timings']['model_calls'], 0)
                self.assertEqual(answer['sources'][0]['item_id'], self.item['id'])
                self.assertIn('农历2001年8月12日', answer['answer'])
            with self.assertRaisesRegex(ValueError, 'model path'):
                self.service.ask_library('小林妈妈生日', force_refresh=True)

    def test_conflicts_trash_and_ambiguous_requests(self):
        for question in ('妈妈生日', '小林爸爸生日', '小林妈妈生日今年是阳历哪天？', '小林妈妈多大了？'):
            self.assertIsNone(lookup(self.archive, question))
        conflict = self.service.ingest({'text': '小林妈妈的出生日期是农历九月初二', 'archive_only': True})['item']
        self.assertIsNone(lookup(self.archive, '小林妈妈生日'))
        self.service.trash_item(conflict['id'], conflict['updated'])
        self.assertIsNotNone(lookup(self.archive, '小林妈妈生日'))
        set_note(self.archive, self.item['id'], '日期需要更正', [], 0)
        self.assertIsNone(lookup(self.archive, '小林妈妈生日'))

    def test_separate_corrections_and_attachments(self):
        for text, filename in (
            ('更正：小林妈妈 的生日改为农历九月初二', ''),
            ('小林妈妈的出生日期为农历九月初二', '核对表.txt'),
        ):
            with self.subTest(filename=filename):
                key, _ = self.archive.add('家庭资料', text, filename=filename)
                self.assertIsNone(lookup(self.archive, '小林妈妈生日'))
                self.service.trash_item(key, self.archive.get(key)['updated'])
                self.assertIsNotNone(lookup(self.archive, '小林妈妈生日'))

    def test_edited_dates_and_retained_corrections(self):
        context = [{'statement': '小林妈妈的出生日期需要更正，先以新资料为准'}]
        with patch.object(self.service, 'model_backend', side_effect=ValueError('model path')):
            with self.assertRaisesRegex(ValueError, 'model path'):
                self.service.ask_library('小林妈妈生日', context=context)
        self.archive.update(self.item['id'], text='小林妈妈 的生日：农历闰四月廿三')
        for question in ('小林妈妈 生日', '小林妈妈的生日几月几号', '小林妈妈出生日期什么时候？'):
            result = self.service.ask_library(question)
            self.assertEqual(result['timings']['model_calls'], 0)
            self.assertIn('农历闰四月廿三', result['answer'])
            self.assertNotIn('2001', result['sources'][0]['text'])

    def test_my_original_birthday_alongside_relative(self):
        mine=self.service.ingest({'text':'我的生日 公历2000年3月2日','archive_only':True})['item']
        result=self.service.ask_library('我的生日呢？')
        self.assertEqual(result['timings']['model_calls'],0)
        self.assertEqual(result['sources'][0]['item_id'],mine['id'])
        self.assertIn('你的生日是公历2000年3月2日',result['answer'])
        self.service.archive.add('纠正','我的生日其实是3月3日')
        self.assertIsNone(lookup(self.archive,'我的生日呢？'))

    def test_explicit_self_note_has_same_owner_for_my_question(self):
        self.service.ingest({'text':'本人生日 公历2000年3月2日','archive_only':True})
        result=self.service.ask_library('我的生日呢？')
        self.assertEqual(result['timings']['model_calls'],0)
        self.assertIn('你的生日是公历2000年3月2日',result['answer'])
        self.service.archive.add('另一条个人记录','我的生日 公历2000年3月3日')
        self.assertIsNone(lookup(self.archive,'本人的生日'))

    def test_date_boundaries(self):
        for value in ('2024-02-29', '农历二〇〇一年八月十二', '阴历闰四月二十三', '农历腊月初一', '11月30号'):
            self.assertTrue(date_identity(value), value)
        for value in ('2023-02-29', '4月31日', '13月1日', '农历十月三十一', '八月零日', '99月99日', '公历闰四月初九'):
            self.assertFalse(date_identity(value), value)

    def test_same_family_members_and_pronouns(self):
        self.service.ingest({'text':'建档：小林爸爸生日 阳历2000年1月1日', 'archive_only':True})
        self.service.ingest({'text':'她生日 农历十月初三', 'archive_only':True})
        for who, expected in [('小林妈妈', '农历2001年8月12日'), ('小林爸爸', '阳历2000年1月1日')]:
            answer, sources = lookup(self.archive, who + '生日')
            self.assertIn(expected, answer)
            self.assertEqual(len(sources), 1)
            self.assertIn(who, sources[0]['text'])
        self.assertIsNone(lookup(self.archive, '她生日'))

    def test_recent_correction_without_retained_condition(self):
        history = [
            {'question': '小林妈妈生日', 'answer': '八月十二。[1]', 'source_ids': [self.item['id']]},
            {'question': '刚才记错了，是八月十三', 'answer': '收到更正。', 'source_ids': []},
        ]
        with patch.object(self.service, 'model_backend', side_effect=ValueError('model path')):
            with self.assertRaisesRegex(ValueError, 'model path'):
                self.service.ask_library('小林妈妈生日', history=history)
            with self.assertRaisesRegex(ValueError, 'model path'):
                self.service.ask_library('小林妈妈生日', context=[
                    {'statement': '以后以新资料为准', 'source_ids': [self.item['id']]}])
            repeat = self.service.ask_library('小林妈妈生日', history=history[:1])
            self.assertEqual(repeat['timings']['model_calls'], 0)

    def test_equivalent_formats_preserve_cited_spelling(self):
        other = self.service.ingest({'text': '小林妈妈的出生日期：阴历二〇〇一年八月十二', 'archive_only': True})['item']
        answer, sources = lookup(self.archive, '小林妈妈生日')
        self.assertEqual(sources[0]['item_id'], other['id'])
        self.assertIn('阴历二〇〇一年八月十二', answer)
        for different in ('阳历2001年8月12日', '农历闰八月十二', '农历八月十二', '2001年8月12日'):
            with self.subTest(different=different):
                self.archive.update(other['id'], text='小林妈妈生日 ' + different)
                self.assertIsNone(lookup(self.archive, '小林妈妈生日'))

    def test_overlapping_names_never_use_another_persons_date(self):
        self.service.ingest({'text': '林妈妈生日 阳历3月2日', 'archive_only': True})
        exact = lookup(self.archive, '小林妈妈生日')
        self.assertEqual(exact[1][0]['item_id'], self.item['id'])
        self.assertNotIn('阳历3月2日', exact[0])
        # A shortened name matching multiple records requires disambiguation.
        self.assertIsNone(lookup(self.archive, '林妈妈生日'))

    def test_previous_statement_repeated_as_archive_is_not_a_correction(self):
        history = [{'question':'小林妈妈生日 阴历二〇〇一年八月十二', 'answer':'按你提供的信息。', 'source_ids':[]}]
        with patch.object(self.service, 'model_backend', side_effect=ValueError('model path')):
            answer = self.service.ask_library('小林妈妈生日', history=history)
            self.assertEqual(answer['timings']['model_calls'], 0)
            self.assertEqual(answer['sources'][0]['item_id'], self.item['id'])
            history[0]['question'] = '小林妈妈生日 农历2001年8月13日'
            with self.assertRaisesRegex(ValueError, 'model path'):
                self.service.ask_library('小林妈妈生日', history=history)
