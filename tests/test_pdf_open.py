import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service,handler
from pdf_fixture import pdf_bytes


class PdfOpenTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.service=Service(self.temp.name)
        self.content=pdf_bytes();self.item_id,_=self.service.archive.add('PDF','',filename='资料 example.pdf',data=self.content)
        self.handler=handler(self.service)
    def tearDown(self):self.service.close();self.temp.cleanup()
    def request(self,path,body=None,token=''):
        class Socket:
            def __init__(self,data):self.input=io.BytesIO(data);self.output=io.BytesIO()
            def makefile(self,*args):return self.input
            def sendall(self,data):self.output.write(data)
        class Server:server_port=8768
        data=json.dumps(body).encode() if body is not None else b''
        method='POST' if body is not None else 'GET'
        head=f'{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:8768\r\nContent-Length: {len(data)}\r\nX-Knowledge-Token: {token}\r\n\r\n'
        sock=Socket(head.encode()+data);self.handler(sock,('127.0.0.1',12345),Server())
        head,body=sock.output.getvalue().split(b'\r\n\r\n',1)
        return int(head.split()[1]),head.decode(),body
    def test_browser_preview_is_inline_pdf_and_download_stays_attachment(self):
        path='/api/items/'+self.item_id
        status,head,body=self.request(path+'/preview')
        self.assertEqual(status,200);self.assertEqual(body,self.content)
        self.assertIn('Content-Type: application/pdf',head)
        self.assertIn("Content-Disposition: inline; filename*=UTF-8''",head)
        self.assertIn("object-src 'self'",head)
        status,head,body=self.request(path+'/file')
        self.assertIn('Content-Disposition: attachment;',head);self.assertEqual(body,self.content)
    def test_system_open_requires_token_and_keeps_original_unchanged(self):
        path='/api/items/'+self.item_id+'/open-file'
        self.assertEqual(self.request(path,{} )[0],403)
        token=json.loads(self.request('/api/status')[2])['token']
        before=self.service.archive.get(self.item_id)
        self.service.busy.add(self.item_id)
        try:
            with patch('secretary.server.sys.platform','darwin'),patch('secretary.server.subprocess.run') as run:
                self.assertEqual(self.request(path,{},token)[0],200)
                args=run.call_args.args[0];self.assertEqual(args[0],'/usr/bin/open')
                copy=Path(args[1]);self.assertEqual(copy.name,'资料 example.pdf');self.assertEqual(copy.read_bytes(),self.content)
                copy.write_bytes(b'changed in viewer')
                self.service.open_pdf(self.item_id)
                self.assertEqual(copy.read_bytes(),self.content)
        finally:self.service.busy.discard(self.item_id)
        self.assertEqual((self.service.archive.root/'files'/self.item_id).read_bytes(),self.content)
        self.assertEqual(self.service.archive.get(self.item_id),before)
    def test_non_pdf_and_mislabeled_file_are_rejected(self):
        other,_=self.service.archive.add('Image','',filename='file.png',data=b'image')
        fake,_=self.service.archive.add('Fake','',filename='fake.pdf',data=b'not a pdf')
        for item in (other,fake):
            self.assertEqual(self.request('/api/items/'+item+'/preview')[0],400)
            with self.assertRaises(ValueError):self.service.open_pdf(item)
