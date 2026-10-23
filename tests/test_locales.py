import tempfile
import unittest
from secretary.server import Service
from secretary.i18n import translate
from secretary.desktop_status import presentation

class LanguageTest(unittest.TestCase):
    def test_preference_validation_and_data_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            try:
                service.archive.add('知识库','模型与设置，原文不能改变。')
                before=service.archive.export();settings=service.archive.settings()
                service.archive.set_language('en')
                self.assertEqual(service.archive.settings()['ui_language'],'en')
                self.assertEqual(service.archive.export(),before)
                for key,value in settings.items():
                    if key!='ui_language':self.assertEqual(service.archive.settings()[key],value)
                for invalid in ('fr','en-US','',None):
                    with self.assertRaises(ValueError):service.archive.set_language(invalid)
                self.assertEqual(service.archive.settings()['ui_language'],'en')
            finally:service.close()
    def test_native_status_and_labels_use_selected_language(self):
        self.assertEqual(translate('模型与设置','en'),'Models & settings')
        self.assertEqual(translate('模型与设置','zh'),'模型与设置')
        status={'application':'stellar-central-secretary','settings':{'ui_language':'en'},'runtime':{'processing':2}}
        value=presentation(status)
        self.assertEqual(value['detail'],'Summarizing: 2')
        self.assertEqual(value['badge'],'AI')
