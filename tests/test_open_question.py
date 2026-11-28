import json
import unittest
from unittest.mock import patch

from secretary.knowledge_chat import plan


class OpenQuestionTest(unittest.TestCase):
    def test_analysis_checks_each_cited_original(self):
        passages = [
            {'title': '到访', 'text': '游客一般傍晚七点到达。'},
            {'title': '排班', 'text': '晚班人员工作到八点。'},
        ]
        question = '结合到访和排班记录，建议如何安排。'
        quotes = {str(i): p['text'] for i, p in enumerate(passages, 1)}
        for citations, evidence, accepted in [
            ('[1][2]', quotes, True),
            ('[1][2]', {'1': quotes['1']}, False),
            ('[1][2]', {'1': quotes['2'], '2': quotes['1']}, False),
            ('[1]', {'1': quotes['1']}, False),
            ('[3]', quotes, False),
        ]:
            with self.subTest(citations=citations, evidence=evidence):
                answer = '建议傍晚七点开始。' + citations
                output = json.dumps(dict(route='grounded', answer=answer, quotes=evidence))
                with patch('secretary.ai.run', return_value=output):
                    result = plan(question, [], 'codex', passages)
                self.assertEqual(getattr(result, 'grounded_answer', None), answer if accepted else None)

    def test_requested_sources_and_distractors(self):
        passages = [
            {'title': '交接记录', 'text': '库管下午三点到岗。'},
            {'title': '转运记录', 'text': '司机两点半要发车。'},
            {'title': '值日记录', 'text': '保洁下午两点到岗。'},
        ]
        for question, numbers, accepted in [
            ('结合交接记录和转运记录，建议怎样交接？', [1, 3], False),
            ('结合交接记录和转运记录，建议怎样交接？', [1, 2], True),
            ('结合交接记录，建议如何协调人力和时间？', [1], True),
            ('结合交接记录，建议如何协调人力和时间？', [3], False),
            ('结合交接记录和未归档的签收单，建议如何安排？', [1, 3], False),
            ('根据交接记录和转运记录，建议如何安排？', [1], False),
            ('结合交接记录和未归档的签收单，建议如何安排？', [1], False),
        ]:
            with self.subTest(question=question, numbers=numbers):
                answer = '建议提前协调。' + ''.join(f'[{n}]' for n in numbers)
                quotes = {str(n): passages[n-1]['text'] for n in numbers}
                output = json.dumps(dict(route='grounded', answer=answer, quotes=quotes))
                with patch('secretary.ai.run', return_value=output):
                    result = plan(question, [], 'codex', passages)
                self.assertEqual(getattr(result, 'grounded_answer', None), answer if accepted else None)
