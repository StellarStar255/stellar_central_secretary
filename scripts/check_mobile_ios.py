"""Run real iOS simulator UI tests against an isolated synthetic library."""
import base64,json,os,subprocess,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlencode
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service

ROOT=Path(__file__).resolve().parent.parent
if __name__=='__main__':
 with tempfile.TemporaryDirectory(prefix='stellar-ios-fixture-') as folder:
  service=Service(folder);service.archive.configure('codex',False);mobile=service.mobile
  connections={'tls':0,'status':0,'items':0,'files':0};connection_changed=threading.Condition()
  list_gate=threading.Event();list_gate.set()
  file_gate=threading.Event();file_gate.set()
  original_handler=mobile.handler
  def counted_handler():
   base=original_handler()
   class Counting(base):
    def setup(self):
     super().setup()
     with connection_changed:connections['tls']+=1
    def do_GET(self):
     if self.path=='/status':
      with connection_changed:connections['status']+=1;connection_changed.notify_all()
     if self.path.startswith('/items?'):
      with connection_changed:connections['items']+=1;connection_changed.notify_all()
      list_gate.wait(timeout=10)
     if '/files/' in self.path:
      with connection_changed:connections['files']+=1;connection_changed.notify_all()
      file_gate.wait(timeout=15)
     super().do_GET()
   return Counting
  mobile.handler=counted_handler
  mobile.enable(advertise=True,bind='0.0.0.0');port=mobile.server.server_port
  item,_=service.archive.add('Reference fixture','Reference fixture body')
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    if self.path=='/pair.json':
     with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):mobile.invitation()
     info={'v':1,'server_id':mobile.state['server_id'],'name':'Fixture Mac','url':f'https://127.0.0.1:{port}','fingerprint':mobile.fingerprint,'secret':mobile.invite['secret']}
     value={'url':'stellar-secretary://pair?'+urlencode({'data':base64.b64encode(json.dumps(info).encode()).decode()})}
    elif self.path=='/approve':
     pending=mobile.status()['pending'];assert len(pending)==1
     mobile.decide({'id':pending[0]['id'],'approve':True});value={'ok':True}
    elif self.path=='/offline':mobile.stop();value={'ok':True}
    elif self.path=='/online':mobile.enable(advertise=True,bind='0.0.0.0');value={'ok':True}
    elif self.path=='/connections':
     with connection_changed:value=dict(connections)
    elif self.path.startswith('/wait-status?after='):
     previous=int(self.path.split('=',1)[1])
     with connection_changed:
      connection_changed.wait_for(lambda:connections['status']>previous,timeout=8);value=dict(connections)
    elif self.path=='/hold-files':file_gate.clear();value={'ok':True}
    elif self.path=='/release-files':file_gate.set();value={'ok':True}
    elif self.path=='/hold-items':list_gate.clear();value={'ok':True}
    elif self.path=='/release-items':list_gate.set();value={'ok':True}
    elif self.path=='/prepare-detail':
     item=next(item for item in service.archive.list() if item['title']=='Mobile fixture unique note')
     with service.archive.db() as db:db.execute('UPDATE items SET url=? WHERE id=?',('https://example.com/phone-original',item['id']))
     service.append_material(item['id'],{'expected_updated':service.archive.get(item['id'])['updated'],'attachments':[{'name':'fixture.txt','data':base64.b64encode(b'Phone original fixture').decode()},{'name':'slow.txt','data':base64.b64encode(b'Cancellation fixture').decode()}],'summarize':False,'read_links':False})
     value={'ok':True}
    elif self.path=='/metadata':
     item=next(item for item in service.archive.list() if item['title']=='Edited mobile fixture title')
     value={'title':item['title'],'tags':item['tags']}
    elif self.path=='/count':value={'count':len(service.archive.list())}
    else:self.send_error(404);return
    data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  control=ThreadingHTTPServer(('127.0.0.1',18769),Handler);threading.Thread(target=control.serve_forever,daemon=True).start()
  try:
   with patch.object(service,'ask_library',return_value={'answer':'Synthetic fixture answer [1]','sources':[{'number':1,'item_id':item,'title':'Reference fixture'}]}):
    env={**os.environ,'DEVELOPER_DIR':'/Applications/Xcode.app/Contents/Developer'}
    command=['xcodebuild','-project','ios/StellarSecretary.xcodeproj','-scheme','StellarSecretary','-configuration','Debug','-destination','platform=iOS Simulator,id='+sys.argv[1],'-derivedDataPath','build/ios','-resultBundlePath',str(Path('/tmp')/('stellar-ios-results-'+os.urandom(4).hex())),'CODE_SIGN_IDENTITY=-','CODE_SIGNING_ALLOWED=YES','test']
    # Each run owns a synthetic simulator library and outbox. A previous failed
    # run must not leave drafts scoped to an unrelated fixture server ID.
    inventory=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','--json'],env=env))
    device=next(d for values in inventory['devices'].values() for d in values if d['udid']==sys.argv[1])
    assert device['name']=='Stellar Secretary Trial','Use the dedicated trial simulator only'
    subprocess.run(['xcrun','simctl','uninstall',sys.argv[1],'io.github.stellarstar255.secretary.companion'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    result=subprocess.run(command,cwd=ROOT,env=env)
    if result.returncode:print('Fixture archive titles:',[item['title'] for item in service.archive.list()],flush=True)
    result.check_returncode()
    assert len(service.archive.list())==3
    print('PASS: native iOS pairing, Mac approval, pinned HTTPS, short foreground TLS reuse, long-background transport rebuild, suspended offline-attempt recovery, cached list reuse, nonblocking refresh, offline cache across restart, phone metadata editing, top original links and attachment controls, original file cache and download cancellation, note capture, reference details, knowledge answer, offline queue across restart, automatic retry and no duplicate archives')
  finally:control.shutdown();control.server_close();mobile.stop(disable=True);service.close()
