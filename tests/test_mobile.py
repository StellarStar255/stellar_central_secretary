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
 def approve_model(self):
  status,info=self.request('/model-privacy',credential=self.credential)
  self.assertEqual(status,200);self.assertFalse(info['approved'])
  status,info=self.request('/model-privacy',{'approved':True,'fingerprint':info['fingerprint']},self.credential)
  self.assertEqual(status,200);self.assertTrue(info['approved'])
  return info
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
 def test_multiple_phones_keep_independent_approval_and_revocation(self):
  first=self.approve();first_credential=self.credential
  self.credential=secrets.token_urlsafe(48);second=self.approve()
  self.assertEqual(len(self.m.status()['devices']),2)
  for credential in (first_credential,self.credential):
   self.assertEqual(self.request('/status',credential=credential)[0],200)
  self.m.revoke(first['id'])
  self.assertEqual(self.request('/status',credential=first_credential)[0],401)
  self.assertEqual(self.request('/status',credential=self.credential)[0],200)
  self.assertEqual(self.m.device(self.credential),second['id'])
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

 def test_binary_capture_replays_across_json_and_rejects_incomplete_body(self):
  from secretary.mobile import BINARY_UPLOAD_TYPE
  self.approve()
  self.assertTrue(self.request('/status',credential=self.credential)[1]['binary_attachments_v1'])
  blobs=[b'first fixture',b'second fixture']
  def body(values):
   return {'request_id':'mixed-wire-retry','content':{'attachments':[
    {'name':f'{index}.txt','data':value} for index,value in enumerate(values)]}}
  meta=json.dumps(body(map(len,blobs))).encode()
  packet=len(meta).to_bytes(4,'big')+meta+b''.join(blobs)
  def send(data,credential):
   req=urllib.request.Request(self.base+'/privacy-v1/ingest',data=data,
       headers={'Content-Type':BINARY_UPLOAD_TYPE,'Authorization':'Bearer '+credential})
   try:
    with self.http.open(req,timeout=5) as res:return res.status
   except urllib.error.HTTPError as error:return error.code
  self.assertEqual(send(packet,''),401)
  self.assertEqual(send(packet[:-1],self.credential),400)
  self.assertEqual(send(packet+b'x',self.credential),400)
  self.assertEqual(send(packet,self.credential),200)
  legacy=body(base64.b64encode(b).decode() for b in blobs)
  self.assertTrue(self.request('/privacy-v1/ingest',legacy,self.credential)[1]['duplicate'])
  self.assertEqual(len(self.s.archive.list()),1)

 def test_upload_progress_counts_received_tls_bytes_and_is_phone_scoped(self):
  from http.client import HTTPSConnection
  import time
  self.approve();phone=self.credential
  self.credential=secrets.token_urlsafe(48);self.approve()
  self.assertTrue(self.request('/status',credential=phone)[1]['upload_progress'])
  context=ssl.create_default_context(cafile=str(self.m.root/'certificate.pem'));context.check_hostname=False
  conn=HTTPSConnection('127.0.0.1',self.m.server.server_port,context=context,timeout=5)
  upload='e'*32;progress='/upload-progress/'+upload
  payload=json.dumps({'request_id':'progress','content':{'filename':'progress.txt',
                       'data':base64.b64encode(b'Progress fixture\n'*6000).decode()}}).encode()
  try:
   conn.putrequest('POST','/privacy-v1/ingest')
   conn.putheader('Authorization','Bearer '+phone);conn.putheader('X-Stellar-Upload',upload)
   conn.putheader('Content-Length',str(len(payload)));conn.endheaders()
   cut=32768;conn.send(payload[:cut])
   deadline=time.monotonic()+3
   while time.monotonic()<deadline:
    state=self.request(progress,credential=phone)[1]
    if state.get('received')==cut:break
    time.sleep(.02)
   self.assertEqual(state,{'received':cut,'total':len(payload)})
   self.assertEqual(self.request(progress,credential=self.credential),(200,{}))
   self.assertEqual(self.request(progress)[0],401)
   conn.send(payload[cut:])
   result=conn.getresponse();self.assertEqual(result.status,200);result.read()
   self.assertEqual(len(self.s.archive.list()),1)
   self.assertEqual(self.request(progress,credential=phone),(200,{}))
  finally:conn.close()
 def test_device_nickname_persists_without_changing_identity_or_model_consent(self):
  ident=self.approve()['id'];info=self.approve_model()
  before=dict(self.m.state['devices'][ident])
  status=self.m.rename_device({'id':ident,'nickname':'  试用版  '})
  self.assertEqual(status['devices'],[{'id':ident,'name':'Fixture phone','created':before['created'],'nickname':'试用版'}])
  self.assertEqual(self.m.state['devices'][ident],{**before,'nickname':'试用版'})
  self.assertEqual(json.loads(self.m.path.read_text())['devices'][ident]['nickname'],'试用版')
  self.assertEqual(self.request('/status',credential=self.credential)[0],200)
  self.assertEqual(self.request('/model-privacy',credential=self.credential)[1],info)
  self.assertEqual(self.request('/api/mobile/rename',{'id':ident,'nickname':'mobile change'},self.credential)[0],404)
  with self.assertRaises(ValueError):self.m.rename_device({'id':ident,'nickname':'x'*81})
  self.assertEqual(self.m.rename_device({'id':ident,'nickname':' '})['devices'][0]['nickname'],'')
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
   code,value=self.request('/ask',{'question':'Find fixture'},self.credential)
   self.assertEqual(code,403);self.assertTrue(value['model_consent_required']);ask.assert_not_called()
   self.approve_model()
   status,value=self.request('/ask',{'question':'Find fixture'},self.credential)
  self.assertEqual(status,200);self.assertEqual(value['answer'],'Synthetic answer');self.assertNotIn('private',value);ask.assert_called_once_with('Find fixture')
  self.assertEqual(self.s.runtime()['answering'],0)

 def test_alternate_addresses_exclude_public_ips_and_keep_lan_default(self):
  from types import SimpleNamespace
  from secretary.mobile import addresses
  ips=['100.83.1.2','169.254.1.2','172.23.1.2','8.8.8.8','127.0.0.1']
  adapter=SimpleNamespace(name='en0',ips=[SimpleNamespace(ip=ip) for ip in ips]+[SimpleNamespace(ip=('fe80::1234',0,1)),SimpleNamespace(ip=('2001:db8::1',0,1))])
  with patch('ifaddr.get_adapters',return_value=[adapter]):
   self.assertEqual(addresses(),['172.23.1.2'])
   self.assertEqual(addresses(include_alternates=True),['172.23.1.2','fe80::1234','100.83.1.2','169.254.1.2'])
 def test_invitation_contains_secure_alternate_endpoints(self):
  import qrcode
  original=qrcode.make
  with patch('secretary.mobile.addresses',return_value=['172.23.1.2','100.83.1.2','169.254.1.2']),patch('qrcode.make',wraps=original) as make:
   self.m.invitation()
  info=json.loads(make.call_args.args[0]);port=self.m.server.server_port
  self.assertEqual(info['url'],f'https://172.23.1.2:{port}')
  self.assertEqual(info['urls'],[f'https://{ip}:{port}' for ip in ['172.23.1.2','100.83.1.2','169.254.1.2']])
  self.assertEqual(info['fingerprint'],self.m.fingerprint)
 def test_phone_photo_ocr_archive_and_replay_never_auto_summarize(self):
  import io
  from PIL import Image
  self.approve();self.s.archive.configure('codex',True)
  self.s.chat_history({'activeId':'phone-chat','conversations':[{'id':'phone-chat','title':'Phone','updated':1,'messages':[]}]})
  stream=io.BytesIO();Image.new('RGB',(48,32),'white').save(stream,'JPEG');raw=stream.getvalue()
  body={'request_id':'photo-source','content':{'filename':'Photo.jpeg','data':base64.b64encode(raw).decode()}}
  with patch('secretary.local_ocr.recognize',return_value='Synthetic OCR text'),patch.object(self.s,'queue') as queue:
   status,result=self.request('/privacy-v1/ingest',body,self.credential);self.assertEqual(status,200);self.assertTrue(result['chat_synced'])
   ident=result['item']['id']
   item=self.s.archive.get(ident);self.assertEqual(item['state'],'saved');self.assertEqual(item['text'],'Synthetic OCR text')
   self.assertEqual((self.s.archive.root/'files'/ident).read_bytes(),raw)
   self.assertTrue(self.request('/ingest',body,self.credential)[1]['duplicate']);queue.assert_not_called()
   with patch.object(self.s,'process_addition') as addition:
    file={'filename':'note.txt','data':base64.b64encode(b'Privacy attachment').decode(),'request_id':'append','expected_updated':item['updated']}
    status,_=self.request('/privacy-v1/items/'+ident+'/attachments',file,self.credential)
    self.assertEqual(status,200);addition.assert_not_called();self.assertNotIn(ident,self.s.busy)
  messages=self.s.chat_history()['conversations'][0]['messages'];self.assertEqual(len(messages),1);self.assertEqual(messages[0]['items'],[ident])
 def test_phone_photo_respects_disabled_auto_ai(self):
  import io
  from PIL import Image
  self.approve();stream=io.BytesIO();Image.new('RGB',(16,16),'white').save(stream,'PNG')
  with patch('secretary.local_ocr.recognize',return_value='Local only'),patch('secretary.ai.analyze_material') as model:
   status,result=self.request('/ingest',{'request_id':'local-only','content':{'filename':'photo.png','data':base64.b64encode(stream.getvalue()).decode()}},self.credential)
   self.assertEqual(status,200);self.assertTrue(result['chat_synced']);model.assert_not_called()
   self.assertEqual(self.s.archive.get(result['item']['id'])['text'],'Local only')

 def test_recent_capture_receipts_are_device_scoped_and_show_live_summary_state(self):
  import io
  from PIL import Image
  self.approve()
  image=io.BytesIO();Image.new('RGB',(16,16),'white').save(image,'JPEG')
  body={'request_id':'status-image','content':{'filename':'Capture.jpeg','data':base64.b64encode(image.getvalue()).decode()}}
  with patch('secretary.local_ocr.recognize',return_value=''):
   code,response=self.request('/ingest',body,self.credential)
  self.assertEqual(code,200)
  receipt=response['capture'];ident=receipt['id']
  self.assertEqual(receipt['stage'],'archived')
  self.assertIn('原件已保存',receipt['message'])
  self.assertEqual(self.request('/captures')[0],401)
  self.assertEqual(self.request('/captures',credential=self.credential)[1]['captures'],[receipt])
  self.s.summary_jobs.enqueue(ident)
  self.assertEqual(self.request('/captures',credential=self.credential)[1]['captures'][0]['stage'],'processing')
  self.s.summary_jobs.finish(ident,'error')
  self.s.archive.update(ident,state='error',error='Model timed out')
  failed=self.request('/captures',credential=self.credential)[1]['captures'][0]
  self.assertEqual(failed['stage'],'error');self.assertIn('超时',failed['message'])
  self.s.archive.update(ident,state='ready',summary='Complete fixture summary',error='')
  self.assertEqual(self.request('/captures',credential=self.credential)[1]['captures'][0]['stage'],'ready')
  first=self.credential
  self.credential=secrets.token_urlsafe(48);self.approve()
  self.assertEqual(self.request('/captures',credential=self.credential)[1]['captures'],[])
  self.s.trash_item(ident)
  self.assertEqual(self.request('/captures',credential=first)[1]['captures'],[])
 def test_phone_auto_summary_requires_independent_grant_and_runs_once(self):
  import io,time
  from PIL import Image
  self.approve();info=self.approve_model();self.s.archive.configure('codex',True)
  self.assertFalse(info['summary_approved'])
  consent={'approved':True,'scope':'summary','fingerprint':info['fingerprint']}
  status,value=self.request('/model-privacy',consent,self.credential)
  self.assertEqual(status,200);self.assertTrue(value['approved']);self.assertTrue(value['summary_approved'])
  fixture=io.BytesIO();Image.new('RGB',(32,32),'white').save(fixture,'JPEG')
  body={'request_id':'summarize-photo','content':{'filename':'Fixture.jpeg','data':base64.b64encode(fixture.getvalue()).decode()}}
  fields={'title':'Fixture image','summary':'Fixture auto-summary','state':'ready','error':''}
  with patch('secretary.local_ocr.recognize',return_value=''),patch('secretary.ai.analyze_material',return_value=(fields,'')) as model:
   status,result=self.request('/privacy-v1/ingest',body,self.credential)
   self.assertEqual(status,200);ident=result['item']['id']
   deadline=time.monotonic()+5
   while ident in self.s.busy and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(self.s.archive.get(ident)['summary'],fields['summary'])
   self.assertTrue(self.request('/ingest',body,self.credential)[1]['duplicate']);model.assert_called_once()
   status,value=self.request('/model-privacy',{'scope':'summary','approved':False},self.credential)
   self.assertEqual(status,200);self.assertTrue(value['approved']);self.assertFalse(value['summary_approved'])
   self.request('/ingest',{'request_id':'after-revoke','content':{'text':'Unique after revoke fixture'}},self.credential)
   model.assert_called_once()

 def test_mobile_summary_revalidates_consent_in_worker(self):
  import threading,time
  self.approve();self.s.archive.configure('codex',True)
  info=self.request('/model-privacy',credential=self.credential)[1]
  self.request('/model-privacy',{'scope':'summary','approved':True,'fingerprint':info['fingerprint']},self.credential)
  started=threading.Event();resume=threading.Event()
  original=self.s.process
  def delayed(*args):
   started.set()
   if resume.wait(5):original(*args)
  with patch.object(self.s,'process',side_effect=delayed),patch('secretary.ai.summary_fields') as model:
   status,result=self.request('/ingest',{'request_id':'queued-summary','content':{'text':'Mobile queued fixture text'}},self.credential)
   self.assertEqual(status,200);ident=result['item']['id']
   try:
    self.assertTrue(started.wait(3))
    self.assertEqual(self.s.archive.get(ident)['state'],'saved')
    self.request('/model-privacy',{'scope':'summary','approved':False},self.credential)
   finally:resume.set()
   deadline=time.monotonic()+5
   while ident in self.s.busy and time.monotonic()<deadline:time.sleep(.01)
   model.assert_not_called()
   self.assertFalse(self.s.archive.get(ident)['summary'])
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
 def test_dual_stack_mobile_gateway_keeps_pinned_tls_on_ipv4_and_ipv6(self):
  import socket
  if not socket.has_dualstack_ipv6():self.skipTest('Dual stack unavailable')
  self.m.stop();self.m.enable(advertise=False)
  context=ssl.create_default_context(cafile=str(self.m.root/'certificate.pem'));context.check_hostname=False
  for host in ['127.0.0.1','::1']:
   with socket.create_connection((host,self.m.server.server_port),timeout=3) as raw:
    with context.wrap_socket(raw,server_hostname=host) as tls:
     tls.sendall(b'GET /status HTTP/1.0\r\nHost: fixture\r\n\r\n')
     self.assertIn(b'401',tls.recv(2048))
 def test_gateway_reuses_port_after_restart(self):
  port=self.m.server.server_port;self.m.stop();self.m.enable(advertise=False,bind='127.0.0.1')
  self.assertEqual(self.m.server.server_port,port)
 def test_gateway_chooses_new_port_if_saved_port_in_use(self):
  import socket
  port=self.m.server.server_port;self.m.stop()
  with socket.socket() as occupied:
   occupied.setsockopt(socket.SOL_SOCKET,getattr(socket,"SO_EXCLUSIVEADDRUSE",socket.SO_REUSEADDR),1);occupied.bind(('127.0.0.1',port));occupied.listen()
   self.m.enable(advertise=False,bind='127.0.0.1');self.assertNotEqual(self.m.server.server_port,port)
 def test_saved_port_falls_back_on_windows_exclusive_bind_error(self):
  import errno
  from http.server import ThreadingHTTPServer
  port=self.m.server.server_port;self.m.stop()
  original=ThreadingHTTPServer.server_bind;attempts=[]
  failure=PermissionError(errno.EACCES,'Exclusive port');failure.winerror=10013
  def bind(server):
   attempts.append(server.server_address[1])
   if len(attempts)==1:raise failure
   return original(server)
  with patch.object(ThreadingHTTPServer,'server_bind',bind):self.m.enable(advertise=False,bind='127.0.0.1')
  self.assertEqual(attempts,[port,0]);self.assertIsNotNone(self.m.server)
  self.m.stop()
  with patch.object(ThreadingHTTPServer,'server_bind',side_effect=failure):
   with self.assertRaises(PermissionError):self.m.enable(port=port,advertise=False,bind='127.0.0.1')
  with patch.object(ThreadingHTTPServer,'server_bind',side_effect=PermissionError(errno.EACCES,'Other permission error')):
   with self.assertRaises(PermissionError):self.m.enable(advertise=False,bind='127.0.0.1')
 def test_nearby_bridge_starts_only_with_discovery_and_stops_with_gateway(self):
  self.m.stop()
  with patch('secretary.mobile.addresses',return_value=[]),patch('secretary.peer_bridge.start') as start,patch('secretary.peer_bridge.stop') as stop:
   self.m.enable(advertise=False,bind='127.0.0.1');start.assert_not_called();self.m.stop()
   self.m.enable(advertise=True,bind='127.0.0.1');start.assert_called_once_with(self.m.state['server_id'],self.m.server.server_port)
   bridge=start.return_value;self.m.stop();stop.assert_called_with(bridge)
 def test_persistent_tls_requests_recheck_revocation(self):
  import http.client
  self.approve();context=ssl.create_default_context(cafile=str(self.m.root/'certificate.pem'));context.check_hostname=False
  connection=http.client.HTTPSConnection('127.0.0.1',self.m.server.server_port,context=context,timeout=3)
  try:
   for _ in range(3):
    connection.request('GET','/status',headers={'Authorization':'Bearer '+self.credential});response=connection.getresponse();self.assertEqual(response.status,200);response.read()
   original=connection.sock
   self.m.state['devices'].clear()
   connection.request('GET','/status',headers={'Authorization':'Bearer '+self.credential});response=connection.getresponse();self.assertEqual(response.status,401);self.assertEqual(response.getheader('Connection'),'close');response.read()
   self.assertIsNotNone(original)
  finally:connection.close()

 def test_phone_metadata_edit_is_validated_conflict_checked_and_indexed(self):
  self.approve();ident,_=self.s.archive.add('Old phone title','Metadata mobile fixture')
  old=self.s.archive.get(ident)
  body={'title':'Updated phone title','tags':['Phone','Review'],'expected_updated':old['updated']}
  self.assertEqual(self.request('/items/'+ident+'/metadata',body)[0],401)
  code,value=self.request('/items/'+ident+'/metadata',body,self.credential)
  self.assertEqual(code,200);self.assertEqual(value['item']['title'],body['title']);self.assertEqual(value['item']['tags'],body['tags'])
  self.assertEqual(self.s.archive.get(ident)['tags_manual'],1)
  self.assertEqual(self.s.archive.list(q='Updated phone title')[0]['id'],ident)
  self.assertEqual(self.request('/items/'+ident+'/metadata',{**body,'title':'Stale overwrite'},self.credential)[0],400)
  self.assertEqual(self.s.archive.get(ident)['title'],body['title'])
  fresh=self.s.archive.get(ident)
  self.assertEqual(self.request('/items/'+ident+'/metadata',{'title':'Must not save','tags':['x'*61],'expected_updated':fresh['updated']},self.credential)[0],400)
  self.assertEqual(self.s.archive.get(ident)['title'],body['title'])
  # The origin gate rejects before reading a body. Send an empty POST so
  # Linux does not reset TLS for unread request bytes before the 403 is read.
  browser=urllib.request.Request(self.base+'/items/'+ident+'/metadata',data=b'',headers={'Authorization':'Bearer '+self.credential,'Origin':'https://example.com'})
  with self.assertRaises(urllib.error.HTTPError) as denied:self.http.open(browser,timeout=5)
  self.assertEqual(denied.exception.code,403);denied.exception.close()
  self.assertEqual(self.s.archive.get(ident)["title"],body["title"])

 def test_phone_appends_and_downloads_only_parent_owned_originals(self):
  self.approve();ident,_=self.s.archive.add('Phone parent','Parent source preserved')
  item=self.s.archive.get(ident);raw=b'Appended mobile original bytes'
  body={'filename':'mobile.txt','data':base64.b64encode(raw).decode(),'expected_updated':item['updated'],'request_id':'append-fixture'}
  path='/items/'+ident+'/attachments'
  code,value=self.request(path,body,self.credential);self.assertEqual(code,200)
  self.assertEqual(len(self.s.archive.get(ident)['additions']),1)
  self.assertEqual(self.s.archive.get(ident)['text'],'Parent source preserved')
  self.assertTrue(self.request(path,body,self.credential)[1]['duplicate'])
  self.assertEqual(len(self.s.archive.get(ident)['additions']),1)
  self.assertEqual(self.request(path,{**body,'data':base64.b64encode(b'Changed').decode()},self.credential)[0],400)
  file=value['item']['attachments'][0];download=file['path']
  self.assertEqual(self.request(download)[0],401)
  request=urllib.request.Request(self.base+download,headers={'Authorization':'Bearer '+self.credential})
  with self.http.open(request,timeout=5) as response:
   self.assertEqual(response.read(),raw);self.assertIn('attachment',response.headers['Content-Disposition'])
  other,_=self.s.archive.add('Other parent','Not the owner')
  self.assertEqual(self.request(download.replace(ident,other),credential=self.credential)[0],400)
  self.assertNotIn(str(self.s.archive.root),json.dumps(value))
  self.s.trash_item(ident)
  self.assertEqual(self.request(download,credential=self.credential)[0],400)

 def test_mobile_image_preview_is_small_cached_and_original_stays_identical(self):
  import io,hashlib
  from PIL import Image
  self.approve();stream=io.BytesIO()
  Image.effect_noise((2400,1800),80).convert('RGB').save(stream,'PNG');raw=stream.getvalue()
  result=self.m.ingest(self.m.device(self.credential),{'request_id':'preview-original','content':{'filename':'original.png','data':base64.b64encode(raw).decode()}})
  ident=result['item']['id'];item=self.request('/items/'+ident,credential=self.credential)[1]['item'];file=item['attachments'][0]
  self.assertEqual(file['size'],len(raw));self.assertTrue(file['version']);self.assertTrue(file['preview_path'])
  self.assertEqual(self.request(file['preview_path'])[0],401)
  def download(path):
   request=urllib.request.Request(self.base+path,headers={'Authorization':'Bearer '+self.credential})
   with self.http.open(request,timeout=10) as response:return response.read(),response.headers['Content-Type']
  preview,media=download(file['preview_path'])
  self.assertEqual(media,'image/jpeg');self.assertLessEqual(len(preview),96*1024);self.assertLess(len(preview),len(raw)//5)
  with Image.open(io.BytesIO(preview)) as image:self.assertLessEqual(max(image.size),1280)
  with patch('secretary.mobile_preview.Image.open',side_effect=AssertionError('Must reuse generated derivative')):
   self.assertEqual(download(file['preview_path'])[0],preview)
  self.assertEqual(hashlib.sha256(download(file['path'])[0]).digest(),hashlib.sha256(raw).digest())

 def test_shared_chat_requires_pairing_and_uses_desktop_background_store(self):
  self.assertEqual(self.request('/chats')[0],401)
  self.approve()
  created=self.request('/chats',{'request_id':'shared-chat-fixture'},self.credential)[1]['chat_id']
  self.assertEqual(self.request('/chats',{'request_id':'shared-chat-fixture'},self.credential)[1]['chat_id'],created)
  self.assertEqual(self.request('/chats/'+created,credential=self.credential)[0],200)
  self.assertEqual(self.request('/chats/'+created+'/messages',{'request_id':'not-paired','text':'Hello'})[0],401)
  with patch.object(self.s,'ask_library',return_value={'answer':'A shared desktop answer','sources':[]}) as model:
   path='/chats/'+created+'/messages';body={'request_id':'shared-phone-message','text':'A chat message'}
   self.assertEqual(self.request(path,body,self.credential)[0],403);model.assert_not_called()
   self.approve_model()
   self.assertTrue(self.request(path,body,self.credential)[1]['accepted'])
   import time
   deadline=time.monotonic()+3
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(self.request(path,body,self.credential)[1]['accepted']);self.assertEqual(model.call_count,1)
  data=self.request('/chats/'+created,credential=self.credential)[1]
  self.assertEqual(data['messages'][-1]['text'],'A shared desktop answer')
  self.assertEqual(self.s.chat_history()['conversations'][0]['messages'][-1]['text'],'A shared desktop answer')
  self.assertNotIn('token',json.dumps(data));self.assertNotIn('fingerprint',json.dumps(data))
  ident=self.m.device(self.credential);self.m.revoke(ident)
  self.assertEqual(self.request('/chats/'+created,credential=self.credential)[0],401)

 def test_first_mobile_message_resolves_current_chat_or_creates_once(self):
  self.approve()
  first={'request_id':'first-from-composer','reuse_active':True}
  code,value=self.request('/chats',first,self.credential)
  self.assertEqual(code,200);initial=value['chat_id']
  self.assertEqual(self.request('/chats',first,self.credential)[1]['chat_id'],initial)
  self.assertEqual(len(self.s.chat_history()['conversations']),1)
  manual=self.request('/chats',{'request_id':'manual-new-chat'},self.credential)[1]['chat_id']
  self.assertNotEqual(initial,manual)
  self.assertEqual(self.request('/chats',{'request_id':'continue-current','reuse_active':True},self.credential)[1]['chat_id'],manual)
  self.assertEqual(len(self.s.chat_history()['conversations']),2)

 def test_chat_attachment_is_archived_and_passed_with_question_once(self):
  import time
  self.approve()
  chat=self.request('/chats',{'request_id':'attachment-chat'},self.credential)[1]['chat_id']
  path='/privacy-v2/chats/'+chat+'/messages'
  body={'request_id':'attachment-question','text':'What is in the file?','attachment':{'name':'fixture.txt','data':base64.b64encode(b'Phone chat attachment contents').decode()}}
  self.assertEqual(self.request(path,body,self.credential)[0],403)
  self.assertEqual(len(self.s.archive.list()),0)
  self.approve_model()
  fields={'title':'Fixture material','summary':'Test material summary','state':'ready','error':''}
  with patch('secretary.ai.analyze_material',return_value=(fields,'Fixture answer [1]')) as model:
   self.assertEqual(self.request(path,body,self.credential)[0],200)
   deadline=time.monotonic()+5
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
   self.assertTrue(self.request(path,body,self.credential)[1]['accepted'])
   model.assert_called_once()
   self.assertEqual(model.call_args.kwargs['question'],body['text'])
   self.assertIn('Phone chat attachment contents',model.call_args.args[0])
  messages=self.request('/chats/'+chat,credential=self.credential)[1]['messages']
  self.assertEqual(messages[0]['files'],['fixture.txt'])
  self.assertEqual(messages[-1]['text'],'Fixture answer [1]')
  self.assertEqual(len(self.s.archive.list()),1)
  item=messages[0]['sources'][0]['item_id']
  attachment=self.request('/items/'+item,credential=self.credential)[1]['item']['attachments'][0]
  self.assertEqual(attachment['name'],'fixture.txt')

 def test_chat_attachment_without_text_requests_summary(self):
  import time
  self.approve()
  self.approve_model()
  chat=self.request('/chats',{'request_id':'file-only-chat'},self.credential)[1]['chat_id']
  path='/privacy-v2/chats/'+chat+'/messages'
  body={'request_id':'file-only-question','text':'','attachment':{'name':'fixture.txt','data':base64.b64encode(b'File without caption').decode()}}
  fields={'title':'Fixture material','summary':'Test material summary','state':'ready','error':''}
  with patch('secretary.ai.analyze_material',return_value=(fields,'Fixture answer [1]')) as model:
   self.assertEqual(self.request(path,body,self.credential)[0],200)
   deadline=time.monotonic()+5
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
   model.assert_called_once()
   self.assertEqual(model.call_args.kwargs['question'],'请整理这份附件的主要内容。')
   self.assertIn('File without caption',model.call_args.args[0])
  messages=self.request('/chats/'+chat,credential=self.credential)[1]['messages']
  self.assertEqual(messages[0]['files'],['fixture.txt'])
  self.assertEqual(messages[-1]['text'],'Fixture answer [1]')

 def test_multiple_originals_stay_together_in_capture_and_chat(self):
  import io,time
  from PIL import Image
  self.approve()
  originals={}
  for color in ('red','blue'):
   stream=io.BytesIO()
   Image.new('RGB',(12,12),color).save(stream,'PNG')
   originals[color+'.png']=stream.getvalue()
  files=[{'name':name,'data':base64.b64encode(raw).decode()} for name,raw in originals.items()]
  self.assertTrue(self.request('/status',credential=self.credential)[1]['multi_attachments'])
  capture={'request_id':'multi-capture','content':{'text':'','attachments':files}}
  code,result=self.request('/privacy-v1/ingest',capture,self.credential)
  self.assertEqual(code,200)
  self.assertTrue(self.request('/privacy-v1/ingest',capture,self.credential)[1]['duplicate'])
  capture_id=result['item']['id']
  chat=self.request('/chats',{'request_id':'multi-chat'},self.credential)[1]['chat_id']
  path='/privacy-v2/chats/'+chat+'/messages'
  body={'request_id':'multi-question','text':'Compare these images','attachments':files}
  self.assertEqual(self.request(path,body,self.credential)[0],403)
  self.approve_model()
  fields={'title':'Comparison','summary':'Both images','state':'ready','error':''}
  with patch('secretary.ai.analyze_material',return_value=(fields,'Comparison result [1]')) as model:
   self.assertEqual(self.request(path,body,self.credential)[0],200)
   self.assertEqual(self.request(path,body,self.credential)[0],200)
   deadline=time.monotonic()+5
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
   model.assert_called_once()
  messages=self.request('/chats/'+chat,credential=self.credential)[1]['messages']
  self.assertEqual(messages[0]['files'],list(originals))
  chat_item=messages[0]['sources'][0]['item_id']
  for item_id in (capture_id,chat_item):
   detail=self.request('/items/'+item_id,credential=self.credential)[1]['item']
   self.assertEqual([file['name'] for file in detail['attachments']],list(originals))
   for file in detail['attachments']:
    _,original=self.m.attachment(item_id,'base',file['path'].rsplit('/',1)[-1])
    self.assertEqual(original.read_bytes(),originals[file['name']])
  self.assertEqual(len(self.s.archive.list()),2)

 def test_model_change_and_revocation_fence_already_admitted_worker(self):
  import threading
  self.approve();first=self.approve_model()
  chat=self.request('/chats',{'request_id':'privacy-fixture'},self.credential)[1]['chat_id']
  path='/privacy-v1/chats/'+chat+'/messages'
  started=threading.Event();resume=threading.Event()
  def answer(*args,**kwargs):
   started.set()
   if not resume.wait(5):raise RuntimeError('fixture timed out')
   self.s.model_backend()
   return {'answer':'must not reach answer','sources':[]}
  with patch.object(self.s,'ask_library',side_effect=answer):
   body={'request_id':'queued-with-consent','text':'Privacy fixture'}
   self.assertEqual(self.request(path,body,self.credential)[0],200)
   self.assertTrue(started.wait(3))
   try:
    self.s.archive.configure('claude',False)
    status,value=self.request('/model-privacy',credential=self.credential)
    self.assertEqual(status,200);self.assertFalse(value['approved']);self.assertNotEqual(value['fingerprint'],first['fingerprint'])
    self.assertEqual(self.request('/model-privacy',{'approved':True,'fingerprint':first['fingerprint']},self.credential)[0],403)
    self.assertEqual(self.request('/model-privacy',{'approved':False},self.credential)[0],200)
    self.approve_model()
   finally:resume.set()
   import time
   deadline=time.monotonic()+3
   while self.s.question_jobs.active_count() and time.monotonic()<deadline:time.sleep(.01)
   result=self.request('/chats/'+chat,credential=self.credential)[1]['messages'][-1]
   self.assertEqual(result['requestState'],'error');self.assertIn('隐私与 AI',result['text'])
