import tempfile
import unittest
from unittest.mock import patch

from secretary.archived_birthdays import document_birthday
from secretary.server import Service


def fixture_number(serial):
    digits='00000120000229'+serial
    weights=(7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2)
    return digits+'10X98765432'[sum(int(d)*w for d,w in zip(digits,weights))%11]


class DocumentBirthdayTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s=Service(tmp.name)
        self.addCleanup(self.s.close)
        self.q='示例甲的生日呢？？'
        self.number=fixture_number('001')
        self.body='名  称 示例甲\n证件类型 身份证 证件号码 '+self.number
        self.item,_=self.s.archive.add('示例保单',self.body,filename='document.txt',data=b'fixture')

    def test_named_date_is_inferred_and_redacted(self):
        with patch('secretary.ai.run',side_effect=AssertionError('unexpected model')):
            r=self.s.ask_library(self.q,context=[dict(statement='按照这张课程表判断')])
        self.assertEqual(r['timings']['model_calls'],0)
        self.assertIn('2000 年 2 月 29 日',r['answer'])
        self.assertIn('推断',r['answer'])
        self.assertNotIn(self.number,str(r))
        self.assertEqual(r['sources'][0]['item_id'],self.item)
        self.assertIsNone(document_birthday(self.s.archive,'我的生日呢？',[]))

    def test_conflict_bad_checksum_and_other_owner(self):
        for body in (self.body[:-1]+'?',self.body.replace('示例甲','示例乙'),self.body+'\n更正：生日有误'):
            self.s.archive.update(self.item,text=body)
            self.assertIsNone(document_birthday(self.s.archive,self.q,[]))
        self.s.archive.update(self.item,text=self.body)
        with patch('secretary.ai.run',side_effect=AssertionError('full review')):
            with self.assertRaisesRegex(AssertionError,'full review'):
                self.s.ask_library(self.q,force_refresh=True)
        self.assertIsNone(document_birthday(self.s.archive,self.q,[dict(question='示例甲的生日有误',answer='',source_ids=[])]))
        other=self.body.replace(self.number,fixture_number('002'))
        self.s.archive.add('另一份保单',other,filename='other.txt',data=b'second')
        self.assertIsNone(document_birthday(self.s.archive,self.q,[]))
