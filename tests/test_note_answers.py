import tempfile
import unittest
from unittest.mock import patch
from secretary.server import Service
from secretary.note_answers import lookup


class NoteAnswerTest(unittest.TestCase):
    def test_short_text_file_can_answer_general_question_in_one_call(self):
        with tempfile.TemporaryDirectory() as folder:
            service=Service(folder)
            try:
                text='展签要在两位负责人共同签字后交给印厂。'
                key,_=service.archive.add('展签交付',text,filename='流程.txt',data=text.encode())
                with patch('secretary.ai.run',return_value='{"route":"grounded","answer":"两位负责人共同签字后交给印厂。[1]"}'):
                    r=service.ask_library('展签交给印厂之前要做什么？')
                self.assertEqual(r['timings']['model_calls'],1)
                self.assertEqual(r['sources'][0]['item_id'],key)
                self.assertEqual(r['answer_evidence']['passage_count'],1)
            finally:service.close()

    def test_new_topics_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Service(folder)
            try:
                previous=[]
                for question,note in [('画室备用钥匙放在哪里？','画室备用钥匙放在蓝柜第二层。'),
                                      ('临展门票多少钱？','临展门票为45元。'),
                                      ('样品保留期是多久？','样品保留期为14天。')]:
                    item,_=s.archive.add('手记',note)
                    old_context=[dict(statement='按上一份记录为准',source_ids=previous[0]['source_ids'])] if previous else []
                    with patch('secretary.ai.run',side_effect=AssertionError('unexpected model')):
                        answer=s.ask_library(question,previous,context=old_context)
                    self.assertEqual(answer['sources'][0]['item_id'],item)
                    self.assertEqual(answer['timings']['model_calls'],0)
                    self.assertIn(note,answer['answer'])
                    previous=[dict(question=question,answer=answer['answer'],source_ids=[item])]
                s.archive.add('修订','样品保留期为30天。')
                self.assertIsNone(lookup(s.archive,question,[]))
                self.assertIsNone(lookup(s.archive,'样品保留期为什么这么长？',[]))
            finally:s.close()
