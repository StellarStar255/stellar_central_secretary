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
  service=Service(folder);service.archive.configure('codex',False);mobile=service.mobile;mobile.enable(advertise=True,bind='0.0.0.0');port=mobile.server.server_port
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
    elif self.path=='/count':value={'count':len(service.archive.list())}
    else:self.send_error(404);return
    data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  control=ThreadingHTTPServer(('127.0.0.1',18769),Handler);threading.Thread(target=control.serve_forever,daemon=True).start()
  try:
   with patch.object(service,'ask_library',return_value={'answer':'Synthetic fixture answer [1]','sources':[{'number':1,'item_id':item,'title':'Reference fixture'}]}):
    env={**os.environ,'DEVELOPER_DIR':'/Applications/Xcode.app/Contents/Developer'}
    command=['xcodebuild','-project','ios/StellarSecretary.xcodeproj','-scheme','StellarSecretary','-configuration','Debug','-destination','platform=iOS Simulator,id='+sys.argv[1],'-derivedDataPath','build/ios','-resultBundlePath',str(Path('/tmp')/('stellar-ios-results-'+os.urandom(4).hex())),'CODE_SIGN_IDENTITY=-','CODE_SIGNING_ALLOWED=YES','test']
    result=subprocess.run(command,cwd=ROOT,env=env)
    if result.returncode:print('Fixture archive titles:',[item['title'] for item in service.archive.list()],flush=True)
    result.check_returncode()
    assert len(service.archive.list())==3
    print('PASS: native iOS pairing, Mac approval, pinned HTTPS, note capture, reference details, knowledge answer, offline queue across restart, automatic retry and no duplicate archives')
  finally:control.shutdown();control.server_close();mobile.stop(disable=True);service.close()
