import tempfile
import unittest
from datetime import date,timedelta
from unittest.mock import patch
from secretary.appointment_facts import lookup,initialize
from secretary.server import Service


class AppointmentTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.service=Service(folder.name)
        self.addCleanup(self.service.close)
        self.archive=self.service.archive
        self.day=(date.today()+timedelta(days=1)).isoformat()
        self.text='预约成功\n患者姓名：测试甲\n就诊时间：'+self.day+' 10:30-11:00'
        self.item,_=self.archive.add('门诊预约',self.text,filename='appointment.png',data=b'original')
        self.question='明天看病是几点？'

    def test_local_with_source_and_rebuild(self):
        with patch('secretary.ai.run',side_effect=AssertionError('unexpected model')):
            result=self.service.ask_library(self.question)
            self.assertIn('测试甲',result['answer'])
            self.assertIn('10:30-11:00',result['sources'][0]['text'])
            self.assertEqual(result['sources'][0]['origin']['name'],'appointment.png')
            with self.archive.db() as db:
                db.execute('DROP TRIGGER appointment_slot_removed')
                db.execute('DROP TABLE appointment_slots')
                initialize(db)
            self.assertEqual(self.service.ask_library(self.question)['timings']['model_calls'],0)
        self.archive.update(self.item,text=self.text.replace('10:30','10:45'))
        self.assertIn('10:45',lookup(self.archive,self.question,[])[0])
        self.archive.trash_item(self.item,self.archive.get(self.item)['updated'])
        self.assertIsNone(lookup(self.archive,self.question,[]))

    def test_single_explicit_time(self):
        self.archive.update(self.item,text=self.text.replace('10:30-11:00','10:45'))
        self.assertIn('10:45',lookup(self.archive,self.question,[])[0])
        self.archive.update(self.item,text=self.text.replace('10:30-11:00','10:30-29:45'))
        self.assertIsNone(lookup(self.archive,self.question,[]))

    def test_conflicting_date_correction_or_unresolved_owner(self):
        self.assertIsNone(lookup(self.archive,'今天看病是几点？',[]))
        from secretary.knowledge_chat import source_excerpts
        previews=source_excerpts(self.archive,'今天看病是几点？',self.archive.retrieve('就诊时间'))
        self.assertEqual(previews[0]['text'],self.day+' 10:30-11:00')
        self.assertIsNone(lookup(self.archive,'我明天看病是几点？',[]))
        self.assertIsNone(lookup(self.archive,self.question,[{'question':'以改期为准'}]))
        self.archive.update(self.item,text=self.text+'\n预约已取消')
        self.assertIsNone(lookup(self.archive,self.question,[]))
        self.archive.update(self.item,text=self.text)
        self.archive.add('改期','挂号时间待重新确认。')
        self.assertIsNone(lookup(self.archive,self.question,[]))
