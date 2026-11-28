import json
import tempfile
import unittest
from unittest.mock import patch

from secretary.server import Service


class ComparisonTest(unittest.TestCase):
    def test_both_originals_and_quotes_required(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(folder)
            self.addCleanup(service.close)
            texts=['甲班周六上课，学费600元。','乙班周日上课，学费450元。']
            for text in texts:service.archive.add('课程安排',text)
            question='比较两种课程安排，预算500元，哪个可行？'
            for invalid in ('', 'missing', 'wrong_quote', 'missing_citation'):
                def model(prompt,*args,**kwargs):
                    data=json.loads(prompt.split('\n',1)[1])
                    if '先用一两句话' in prompt:return '乙班可行。[1] [2]'
                    quotes=[p['text'] for p in data['passages']]
                    answer='乙班可行。[1] [2]'
                    if invalid=='missing':quotes.pop()
                    if invalid=='wrong_quote':quotes[0]='资料里没有的句子'
                    if invalid=='missing_citation':answer='乙班可行。[1]'
                    return json.dumps(dict(route='grounded',answer=answer,quotes=quotes,queries=['课程安排']))
                with self.subTest(invalid=invalid),patch('secretary.ai.run',side_effect=model):
                    service.answer_cache.entries.clear()
                    result=service.ask_library(question)
                    self.assertEqual(result['timings']['model_calls'],2 if invalid else 1)
                    self.assertEqual(len(result['sources']),2)
