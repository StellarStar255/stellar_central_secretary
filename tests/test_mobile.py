import base64,json,os,secrets,ssl,tempfile,unittest,urllib.request,urllib.error
from unittest.mock import patch
from secretary.server import Service
from secretary.mobile import digest

class MobileTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.s=Service(self.temp.name);self.s.archive.configure('codex',False)
  self.m=self.s.mobile;self.m.enable(advertise=False,bind='127.0.0.1')
  context=ssl.create_default_context(cafile=str(self.m.root/'certificate.pem'));context.check_hostname=False
  self.http=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
  self.base='https://127.0.0.1:'+str(self.m.server.server_port);self.credential=secrets.token_urlsafe(48)
 def tearDown(self):self.m.stop(disable=True);self.s.close();self.temp.cleanup()
 def request(self,path,body=None,credential=None,origin=None):
  headers={}
  if credential:headers['Authorization']='Bearer '+credential
  if origin:headers['Origin']=origin
  request=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
  try:
   with self.http.open(request,timeout=5) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as r:return r.code,json.load(r)
 def pair(self):
  with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):self.m.invitation()
  status,pending=self.request('/pair',{'secret':self.m.invite['secret'],'name':'Fixture phone','credential':self.credential})
  self.assertEqual(status,200);return pending
 def approve(self):
  pending=self.pair();self.m.decide({'id':pending['id'],'approve':True});return pending
 def test_only_local_confirmation_grants_access_and_revoke_is_immediate(self):
  self.assertEqual(self.request('/items')[0],401)
  pending=self.pair();self.assertEqual(self.request('/pair/status',credential=self.credential)[0],202)
  self.assertEqual(self.request('/items',credential=self.credential)[0],401)
  self.assertNotIn('hash',json.dumps(self.m.status()))
  self.m.decide({'id':pending['id'],'approve':True})
  self.assertEqual(self.request('/pair/status',credential=self.credential)[1]['approved'],True)
  self.assertEqual(self.request('/status',credential=self.credential)[0],200)
  self.assertEqual(self.request('/api/status',credential=self.credential)[0],404)
  self.assertEqual(self.request('/items',credential=self.credential,origin='https://example.com')[0],403)
  self.m.revoke(pending['id']);self.assertEqual(self.request('/status',credential=self.credential)[0],401)
 def test_expired_one_time_invites_and_rejected_pair(self):
  pending=self.pair()
  self.assertEqual(self.request('/pair',{'secret':'wrong','credential':self.credential,'name':'Phone'})[0],403)
  self.m.decide({'id':pending['id'],'approve':False});self.assertEqual(self.request('/pair/status',credential=self.credential)[0],403)
  with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):self.m.invitation()
  self.m.invite['expires']=0
  self.assertEqual(self.request('/pair',{'secret':self.m.invite['secret'],'credential':self.credential,'name':'Phone'})[0],403)
 def test_offline_replay_and_attachment_use_existing_archive_without_duplicate(self):
  self.approve();body={'request_id':'offline-1','content':{'text':'Fixture arrangement tomorrow 11:00'}}
  code,result=self.request('/ingest',body,self.credential);self.assertEqual(code,200)
  ident=result['item']['id'];self.assertEqual(self.s.archive.get(ident)['text'],body['content']['text'])
  self.assertTrue(self.request('/ingest',body,self.credential)[1]['duplicate'])
  changed={'request_id':'offline-1','content':{'text':'Different'}};self.assertEqual(self.request('/ingest',changed,self.credential)[0],400)
  attachment={'request_id':'file-1','content':{'filename':'example.txt','data':base64.b64encode(b'Unique mobile attachment').decode()}}
  self.assertEqual(self.request('/ingest',attachment,self.credential)[0],200)
  self.assertEqual(len(self.s.archive.list()),2)
  self.assertEqual(self.request('/items?q=arrangement',credential=self.credential)[1]['items'][0]['id'],ident)
  self.assertEqual(self.request('/items/'+ident,credential=self.credential)[1]['item']['text'],body['content']['text'])
  self.s.trash_item(ident);self.assertEqual(self.request('/items/'+ident,credential=self.credential)[0],400)
 def test_credentials_receipts_and_certificate_survive_restart(self):
  self.approve();self.request('/ingest',{'request_id':'persist','content':{'text':'Persist unique note'}},self.credential)
  fingerprint=self.m.fingerprint;self.m.stop(disable=True);self.s.close();self.s=Service(self.temp.name);self.m=self.s.mobile
  self.assertIsNotNone(self.m.device(self.credential));self.m.certificate();self.assertEqual(self.m.fingerprint,fingerprint)
  self.assertTrue(self.m.ingest(self.m.device(self.credential),{'request_id':'persist','content':{'text':'Persist unique note'}})['duplicate'])
  self.assertNotIn(self.credential,self.m.path.read_text())
  if os.name!='nt':self.assertEqual(self.m.path.stat().st_mode&0o777,0o600)
 def test_ask_returns_citations_without_settings_or_credentials(self):
  self.approve()
  with patch.object(self.s,'ask_library',return_value={'answer':'Synthetic answer','sources':[],'private':'no'}) as ask:
   status,value=self.request('/ask',{'question':'Find fixture'},self.credential)
  self.assertEqual(status,200);self.assertEqual(value['answer'],'Synthetic answer');self.assertNotIn('private',value);ask.assert_called_once_with('Find fixture')
  self.assertEqual(self.s.runtime()['answering'],0)

 def test_alternate_addresses_exclude_public_ips_and_keep_lan_default(self):
  from types import SimpleNamespace
  from secretary.mobile import addresses
  ips=['100.83.1.2','169.254.1.2','172.23.1.2','8.8.8.8','127.0.0.1']
  adapter=SimpleNamespace(ips=[SimpleNamespace(ip=ip) for ip in ips])
  with patch('ifaddr.get_adapters',return_value=[adapter]):
   self.assertEqual(addresses(),['172.23.1.2'])
   self.assertEqual(addresses(include_alternates=True),['172.23.1.2','100.83.1.2','169.254.1.2'])
 def test_invitation_contains_secure_alternate_endpoints(self):
  import qrcode
  original=qrcode.make
  with patch('secretary.mobile.addresses',return_value=['172.23.1.2','100.83.1.2','169.254.1.2']),patch('qrcode.make',wraps=original) as make:
   self.m.invitation()
  info=json.loads(make.call_args.args[0]);port=self.m.server.server_port
  self.assertEqual(info['url'],f'https://172.23.1.2:{port}')
  self.assertEqual(info['urls'],[f'https://{ip}:{port}' for ip in ['172.23.1.2','100.83.1.2','169.254.1.2']])
  self.assertEqual(info['fingerprint'],self.m.fingerprint)
 def test_phone_photo_ocr_summary_chat_and_replay(self):
  import io,time
  from PIL import Image
  self.approve();self.s.archive.configure('codex',True)
  self.s.chat_history({'activeId':'phone-chat','conversations':[{'id':'phone-chat','title':'Phone','updated':1,'messages':[]}]})
  stream=io.BytesIO();Image.new('RGB',(48,32),'white').save(stream,'JPEG');raw=stream.getvalue()
  body={'request_id':'photo-source','content':{'filename':'Photo.jpeg','data':base64.b64encode(raw).decode()}}
  fields={'title':'Fixture image','summary':'Synthetic image summary','category':'Test','tags':['Photo'],'vision_text':'Synthetic visible text','state':'ready','error':''}
  with patch('secretary.local_ocr.recognize',return_value='Synthetic OCR text'),patch('secretary.ai.analyze_material',return_value=(fields,'')) as model:
   status,result=self.request('/ingest',body,self.credential);self.assertEqual(status,200);self.assertTrue(result['chat_synced'])
   ident=result['item']['id'];deadline=time.monotonic()+3
   while self.s.archive.get(ident)['state']!='ready' and time.monotonic()<deadline:time.sleep(.01)
   item=self.s.archive.get(ident);self.assertEqual(item['summary'],fields['summary']);self.assertEqual(item['text'],'Synthetic OCR text')
   self.assertEqual(model.call_count,1);self.assertEqual(len(model.call_args.args[3]),1)
   self.assertEqual((self.s.archive.root/'files'/ident).read_bytes(),raw)
   self.assertTrue(self.request('/ingest',body,self.credential)[1]['duplicate']);self.assertEqual(model.call_count,1)
  messages=self.s.chat_history()['conversations'][0]['messages'];self.assertEqual(len(messages),1);self.assertEqual(messages[0]['items'],[ident])
 def test_phone_photo_respects_disabled_auto_ai(self):
  import io
  from PIL import Image
  self.approve();stream=io.BytesIO();Image.new('RGB',(16,16),'white').save(stream,'PNG')
  with patch('secretary.local_ocr.recognize',return_value='Local only'),patch('secretary.ai.analyze_material') as model:
   status,result=self.request('/ingest',{'request_id':'local-only','content':{'filename':'photo.png','data':base64.b64encode(stream.getvalue()).decode()}},self.credential)
   self.assertEqual(status,200);self.assertTrue(result['chat_synced']);model.assert_not_called()
   self.assertEqual(self.s.archive.get(result['item']['id'])['text'],'Local only')
 def test_reextract_legacy_phone_photo_repairs_chat_once(self):
  import io
  from PIL import Image
  stream=io.BytesIO();Image.new('RGB',(16,16),'white').save(stream,'JPEG');raw=stream.getvalue()
  ident,_=self.s.archive.add('Photo.jpeg',filename='Photo.jpeg',data=raw)
  self.m.state['receipts']['legacy-device:legacy-photo']={'id':ident,'signature':'legacy'};self.m.save()
  self.s.chat_history({'activeId':'current','conversations':[{'id':'current','title':'Current','updated':1,'messages':[{'id':'unrelated','role':'user','text':'Keep this message'}]}]})
  with patch('secretary.local_ocr.recognize',return_value='Reparsed fixture'):
   self.s.reextract(ident);self.s.reextract(ident)
  messages=self.s.chat_history()['conversations'][0]['messages']
  self.assertEqual(len(messages),2);self.assertEqual(messages[-1]['items'],[ident]);self.assertEqual(messages[0]['text'],'Keep this message')
  self.assertEqual((self.s.archive.root/'files'/ident).read_bytes(),raw)
