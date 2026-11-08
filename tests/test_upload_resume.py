import hashlib,io,json,tempfile,unittest
from secretary.uploads import Uploads
class ResumeUploadTest(unittest.TestCase):
 def test_restart_resume_prefix_and_shared_consumers(self):
  with tempfile.TemporaryDirectory() as temp:
   uploads=Uploads(temp);first=uploads.start('file.bin',8,'identity','first')
   uploads.chunk(first['id'],0,io.BytesIO(b'1234'),4,first['lease'])
   second=uploads.start('file.bin',8,'identity','second');self.assertEqual(first['id'],second['id']);self.assertEqual(second['offset'],4)
   self.assertTrue(uploads.chunk(second['id'],0,io.BytesIO(b'1234'),4,second['lease'],True)['verified'])
   with self.assertRaisesRegex(ValueError,'不同'):uploads.chunk(second['id'],0,io.BytesIO(b'ABCD'),4,second['lease'],True)
   uploads.discard(first['id'],first['lease']);self.assertTrue(uploads.path(first['id']).exists())
   uploads.chunk(second['id'],4,io.BytesIO(b'5678'),4,second['lease'])
   self.assertEqual(uploads.resolve([{'name':'file.bin','upload_id':second['id'],'lease':second['lease']}])[0]['source'].read_bytes(),b'12345678')
   restarted=Uploads(temp);again=restarted.start('file.bin',8,'identity','new-process');self.assertEqual(again['offset'],8)
   self.assertEqual(again['chunks']['0'],hashlib.sha256(b'1234').hexdigest())
   restarted.discard(again['id'],again['lease']);self.assertFalse(restarted.path(again['id']).exists())
 def test_partial_body_and_unjournaled_tail_are_rolled_back(self):
  with tempfile.TemporaryDirectory() as temp:
   uploads=Uploads(temp);entry=uploads.start('file.bin',8,'id','owner')
   with self.assertRaises(ValueError):uploads.chunk(entry['id'],0,io.BytesIO(b'12'),4,entry['lease'])
   self.assertEqual(uploads.path(entry['id']).stat().st_size,0)
   uploads.chunk(entry['id'],0,io.BytesIO(b'1234'),4,entry['lease'])
   with uploads.path(entry['id']).open('ab') as stream:stream.write(b'CRASH')
   self.assertEqual(uploads.status(entry['id'],entry['lease'])['offset'],4);self.assertEqual(uploads.path(entry['id']).read_bytes(),b'1234')
