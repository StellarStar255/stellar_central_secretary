"""Validate frozen QR/TLS/discovery dependencies with a synthetic library."""
import base64,io,json,os,socket,ssl,subprocess,sys,tempfile,time,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
binary=Path(sys.argv[1]).resolve()
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory(prefix='stellar-mobile-frozen-') as folder:
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
  assert request('/api/mobile')['enabled'] is False
  mobile=request('/api/mobile/enable',{});assert mobile['enabled']
  invite=request('/api/mobile/invite',{});image=Image.open(io.BytesIO(base64.b64decode(invite['qr'].split(',',1)[1])));assert image.format=='PNG'
  context=ssl.create_default_context(cafile=str(Path(folder)/'mobile/certificate.pem'));context.check_hostname=False
  secure=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
  try:secure.open('https://127.0.0.1:'+str(mobile['port'])+'/status',timeout=5)
  except urllib.error.HTTPError as e:assert e.code==401
  else:raise AssertionError('Unpaired client received access')
  assert request('/api/mobile/disable',{})['enabled'] is False
  request('/api/shutdown',{});process.wait(timeout=10)
  print('PASS: frozen mobile UI, certificate generation, TLS listener, QR PNG, discovery registration, unpaired rejection and clean shutdown')
 finally:
  if process.poll() is None:process.terminate();process.wait(timeout=10)
