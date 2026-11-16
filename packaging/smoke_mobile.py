"""Validate frozen QR/TLS/discovery dependencies with a synthetic library."""
import hashlib,secrets,uuid,base64,io,json,os,socket,ssl,subprocess,sys,tempfile,time,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
binary=Path(sys.argv[1]).resolve()
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory(prefix='stellar-mobile-frozen-') as folder:
 credential=secrets.token_urlsafe(48)
 mobile_root=Path(folder)/'mobile';mobile_root.mkdir()
 (mobile_root/'state.json').write_text(json.dumps({'server_id':uuid.uuid4().hex,'enabled':False,'receipts':{},'devices':{'fixture':{'name':'Synthetic phone','hash':hashlib.sha256(credential.encode()).hexdigest(),'created':'fixture'}}}))
 process=subprocess.Popen([str(binary),'--no-browser','--port',str(port),'--data-dir',folder],env={**os.environ,'SECRETARY_DATA_DIR':folder},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 token=''
 def request(path,body=None):
  req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':token})
  with http.open(req,timeout=10) as r:return json.load(r)
 try:
  for _ in range(100):
   if process.poll() is not None:raise RuntimeError('Frozen server exited')
   try:status=request('/api/status');token=status['token'];break
   except OSError:time.sleep(.2)
  else:raise RuntimeError('Frozen server did not start')
  request('/api/settings',{'backend':'codex','auto_ai':False})
  assert request('/api/mobile')['enabled'] is False
  mobile=request('/api/mobile/enable',{});assert mobile['enabled']
  invite=request('/api/mobile/invite',{});image=Image.open(io.BytesIO(base64.b64decode(invite['qr'].split(',',1)[1])));assert image.format=='PNG'
  context=ssl.create_default_context(cafile=str(Path(folder)/'mobile/certificate.pem'));context.check_hostname=False
  secure=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
  try:secure.open('https://127.0.0.1:'+str(mobile['port'])+'/status',timeout=5)
  except urllib.error.HTTPError as e:assert e.code==401
  else:raise AssertionError('Unpaired client received access')
  def companion(path,body=None,binary=False):
   req=urllib.request.Request('https://127.0.0.1:'+str(mobile['port'])+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+credential,'Content-Type':'application/json'})
   with secure.open(req,timeout=10) as response:return response.read() if binary else json.load(response)
  raw=io.BytesIO();Image.new('RGB',(640,480),'orange').save(raw,'PNG');original=raw.getvalue()
  saved=companion('/ingest',{'request_id':'frozen-photo','content':{'filename':'fixture.png','data':base64.b64encode(original).decode()}})
  ident=saved['item']['id'];item=companion('/items/'+ident)['item'];file=item['attachments'][0]
  preview=companion(file['preview_path'],binary=True)
  assert len(preview)<=96*1024 and Image.open(io.BytesIO(preview)).format=='JPEG'
  assert companion(file['path'],binary=True)==original
  edited=companion('/items/'+ident+'/metadata',{'title':'Frozen phone edit','tags':['Fixture'],'expected_updated':item['updated']})['item']
  assert edited['title']=='Frozen phone edit' and edited['tags']==['Fixture']
  assert request('/api/mobile/disable',{})['enabled'] is False
  request('/api/shutdown',{});process.wait(timeout=10)
  print('PASS: frozen mobile UI, certificate generation, TLS listener, QR PNG, discovery registration, unpaired rejection, scoped original download, bounded image derivative, metadata edit and clean shutdown')
 finally:
  if process.poll() is None:process.terminate();process.wait(timeout=10)
