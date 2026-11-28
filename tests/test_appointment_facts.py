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

    def test_ambiguous_or_inactive_receipts(self):
        wrong_day='一二三四五六日'[(date.fromisoformat(self.day).weekday()+1)%7]
        for text in (self.text.replace(self.day,self.day+'（周'+wrong_day+'）'),
                     self.text+'\n就诊时间：'+self.day+' 14:00',
                     self.text.replace('预约成功','预约失败'),
                     self.text+'\n患者姓名：测试乙'):
            with self.subTest(text=text):
                self.archive.update(self.item,text=text)
                self.assertIsNone(lookup(self.archive,self.question,[]))
        self.archive.update(self.item,text=self.text)
        self.archive.add('另一份门诊预约',self.text.replace('10:30','10:40'),filename='other.png',data=b'other')
        self.assertIsNone(lookup(self.archive,self.question,[]))

    def test_overlapping_chunks_preserve_one_source_after_migration(self):
        self.archive.update(self.item,text='说明'*510+'\n'+self.text)
        for rebuild in (False,True):
            if rebuild:
                with self.archive.db() as db:
                    db.execute("UPDATE settings SET value='2' WHERE key='appointment_slots_version'")
                    initialize(db)
            result=lookup(self.archive,self.question,[])
            self.assertIsNotNone(result)
            source=result[1][0]
            with self.archive.db() as db:
                chunk=db.execute("SELECT text FROM chunks WHERE id=?",(source['id'],)).fetchone()
                self.assertIn(source['text'],chunk['text'])

    def test_separate_withdrawal_note(self):
        self.archive.add('状态更新','已退号。')
        self.assertIsNone(lookup(self.archive,self.question,[]))

    def test_time_fields_on_different_chunks(self):
        self.archive.update(self.item,text=self.text+'\n'+'须知'*700+'\n就诊时间：'+self.day+' 14:75')
        self.assertIsNone(lookup(self.archive,self.question,[]))

    def test_preview_prioritizes_requested_date(self):
        for days in (2,3):
            later=(date.today()+timedelta(days=days)).isoformat()
            self.archive.add('门诊预约',self.text.replace(self.day,later),filename='other.png',data=later.encode())
        from secretary.knowledge_chat import source_excerpts
        previews=source_excerpts(self.archive,self.question,self.archive.retrieve('就诊时间'))
        self.assertTrue(previews[0]['text'].startswith(self.day))

    def test_previous_index_is_revalidated(self):
        self.archive.update(self.item,text=self.text.replace('10:30','13:30'))
        with self.archive.db() as db:
            chunk=db.execute("SELECT id FROM chunks WHERE origin!='{}' LIMIT 1").fetchone()[0]
            db.execute("INSERT INTO appointment_slots VALUES (?,?,?,?,?)",(chunk,self.day,'错误时段','',0))
            db.execute("DELETE FROM settings WHERE key='appointment_slots_version'")
            initialize(db)
            self.assertFalse(db.execute('SELECT 1 FROM appointment_slots').fetchone())

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
