import tempfile
import unittest
from unittest.mock import patch

from secretary.plan_costs import lookup
from secretary.server import Service


class PlanCostsTest(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.s=Service(folder.name)
        self.addCleanup(self.s.close)
        self.a=self.s.archive
        self.ids=[self.a.add('方案甲','甲方案的搭建费用为600元，现场工期两天。')[0],
                  self.a.add('方案乙','乙方案的搭建费用为750.50元，现场工期一天。')[0]]
        self.q='比较两种搭建方案，预算不超过800元且只能用一天，哪个可行？'

    def test_boundaries_followup_and_changes(self):
        with patch('secretary.ai.run',side_effect=AssertionError('local calculation')):
            original=self.s.ask_library(self.q)
            self.assertIn('乙方案可行',original['answer'])
            history=[dict(question=self.q,answer=original['answer'],source_ids=self.ids)]
            for budget,expected in [('750.49','都不满足'),('750.50','乙方案可行')]:
                answer=self.s.ask_library('预算改成'+budget+'元呢？',history)
                self.assertIn(expected,answer['answer'])
                self.assertEqual(answer['timings']['model_calls'],0)
                self.assertEqual(set(self.ids),{h['item_id'] for h in answer['sources']})
            history.append(dict(question='预算改成700元呢？',answer='两者都不满足',source_ids=self.ids))
            adjusted=self.s.ask_library('那工期改成两天呢？',history)
            self.assertIn('甲方案可行',adjusted['answer'])
            self.assertIn('预算上限 700 元',adjusted['answer'])
            self.a.update(self.ids[0],text='甲方案的搭建费用为600元，现场工期一天。')
            self.assertIn('甲方案、乙方案可行',self.s.ask_library(self.q)['answer'])

    def test_labelled_note_and_inclusive_budget(self):
        self.a.update(self.ids[0],text='方案甲：搭建费用600元，现场工期2天。')
        question='对比两个搭建方案，预算600元以内，工期最多2天，哪个符合条件？'
        answer,sources=lookup(self.a,question,[])
        self.assertIn('方案甲可行',answer)
        self.assertEqual(len(sources),2)

    def test_uncertain_scope_or_units_fall_back(self):
        self.assertIsNone(lookup(self.a,self.q.replace('不超过','低于'),[]))
        self.assertIsNone(lookup(self.a,'预算改成700元呢？',[]))
        self.assertIsNone(lookup(self.a,self.q,[dict(question='刚才说错了，价格以新报价为准',source_ids=self.ids)]))
        for body in ('乙方案的搭建费用为750元。','乙方案的搭建费用为750美元，现场工期一天。',
                     '乙方案的搭建费用为750元，现场工期一个工作日。','乙方案的搭建费用为750元，现场工期一天，另收运费。'):
            self.a.update(self.ids[1],text=body)
            self.assertIsNone(lookup(self.a,self.q,[]))
        self.a.update(self.ids[1],text='乙方案的搭建费用为750元，现场工期一天。')
        self.a.add('方案乙','已撤回报价')
        self.assertIsNone(lookup(self.a,self.q,[]))
