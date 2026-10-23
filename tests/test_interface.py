import tempfile
import unittest
from secretary.server import Service

class InterfaceTest(unittest.TestCase):
    def test_mode_switch_is_persistent_and_requires_native_host(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            try:
                with self.assertRaises(ValueError):service.switch_interface('desktop')
                service.desktop={'supports_window':True}
                self.assertTrue(service.switch_interface('browser')['ok'])
                first=service.interface_request['id']
                self.assertEqual(service.archive.settings()['interface_mode'],'browser')
                service.switch_interface('desktop');self.assertNotEqual(service.interface_request['id'],first)
                with self.assertRaises(ValueError):service.switch_interface('invalid')
            finally:service.close()
    def test_shared_conversations_merge_without_empty_or_stale_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp)
            def chat(name,updated,text):return {'id':name,'title':name,'updated':updated,'messages':[{'id':name+'-message','role':'user','text':text}]}
            try:
                first=chat('browser',1,'网页历史')
                service.chat_history({'conversations':[first],'activeId':'browser'})
                self.assertEqual(service.chat_history({'conversations':[],'activeId':''})['conversations'],[first])
                newer=chat('browser',3,'更新的问题')
                service.chat_history({'conversations':[newer,chat('desktop',2,'桌面历史')],'activeId':'desktop'})
                result=service.chat_history({'conversations':[first],'activeId':'browser'})
                self.assertEqual(len(result['conversations']),2)
                self.assertEqual(result['conversations'][0],newer)
                with self.assertRaises(ValueError):service.chat_history({'conversations':[{'id':'broken'}]})
                self.assertEqual(service.chat_history()['conversations'],result['conversations'])
            finally:service.close()
