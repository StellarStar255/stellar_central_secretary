"""Run real iOS simulator UI tests against an isolated synthetic library."""
import base64,json,os,time,subprocess,sys,tempfile,threading
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
  ingest_gate=threading.Event();ingest_gate.set()
  ingest_failure=threading.Event()
  original_ingest=mobile.ingest
  def controlled_ingest(device,body):
   ingest_gate.wait(timeout=20)
   if ingest_failure.is_set():
    ingest_failure.clear()
    raise ValueError('Fixture upload rejected once')
   return original_ingest(device,body)
  mobile.ingest=controlled_ingest
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
  shared_id='shared-chat-fixture'
  service.chat_history({'activeId':shared_id,'conversations':[{'id':shared_id,'title':'Shared fixture chat','updated':1,'messages':[
   {'id':'desktop-q','role':'user','text':'Desktop question fixture','knowledgeQuestion':True},
   {'id':'desktop-a','role':'assistant','text':'Desktop context fixture','sources':[]}]}]})
  seeded_chats=service.chat_history()
  second=Service(Path(folder)/'second');second.archive.configure('codex',False);other=second.mobile
  other.enable(advertise=False,bind='127.0.0.1')
  third=Service(Path(folder)/'third');third.archive.configure('codex',False);third.mobile.enable(advertise=False,bind='127.0.0.1')
  home_item,_=second.archive.add('Home-only reference','Only the home computer has this record.')
  second.chat_history({'activeId':shared_id,'conversations':[{'id':shared_id,'title':'Home fixture chat','updated':1,'messages':[
   {'id':'desktop-q','role':'user','text':'Home question fixture','knowledgeQuestion':True},
   {'id':'desktop-a','role':'assistant','text':'Home private reply','sources':[]}]}]})
  chat_calls=[];background_started=threading.Event();background_release=threading.Event()
  def synthetic_answer(question,history=None,progress=None,**kwargs):
   if question in ('Mobile shared question','Offline shared follow-up','Background shared question'):
    chat_calls.append(question)
    assert any(turn['question']=='Desktop question fixture' for turn in (history or [])),'Desktop context missing from phone request'
    if question=='Background shared question':
     if progress:progress('partial','Shared partial reply')
     background_started.set();background_release.wait(timeout=15)
    answer={'Mobile shared question':'Shared phone reply','Offline shared follow-up':'Offline shared answer','Background shared question':'Background shared answer'}[question]
    return {'answer':answer,'sources':[]}
   return {'answer':'Synthetic fixture answer [1]',
           'sources':[{'number':1,'item_id':item,'title':'Reference fixture','text':'Reference fixture body'}],
           'answer_evidence':{'kind':'library','passage_count':1,'history_turns':0,'conditions':[],'pdf_pages':[]}}

  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    if self.path=='/pair.json':
     with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):mobile.invitation()
     info={'v':1,'server_id':mobile.state['server_id'],'name':'Fixture Mac','url':f'https://127.0.0.1:{port}','fingerprint':mobile.fingerprint,'secret':mobile.invite['secret']}
     value={'url':'stellar-secretary://pair?'+urlencode({'data':base64.b64encode(json.dumps(info).encode()).decode()})}
    elif self.path=='/second/pair.json':
     with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):other.invitation()
     info={'v':1,'server_id':other.state['server_id'],'name':'Home Mac','url':f'https://127.0.0.1:{other.server.server_port}','fingerprint':other.fingerprint,'secret':other.invite['secret']}
     value={'url':'stellar-secretary://pair?'+urlencode({'data':base64.b64encode(json.dumps(info).encode()).decode()})}
    elif self.path=='/third/pair.json':
     with patch('secretary.mobile.addresses',return_value=['192.168.1.20']):third.mobile.invitation()
     info={'v':1,'server_id':third.mobile.state['server_id'],'name':'Unapproved Mac','url':f'https://127.0.0.1:{third.mobile.server.server_port}','fingerprint':third.mobile.fingerprint,'secret':third.mobile.invite['secret']}
     value={'url':'stellar-secretary://pair?'+urlencode({'data':base64.b64encode(json.dumps(info).encode()).decode()})}
    elif self.path=='/second/approve':
     pending=other.status()['pending'];assert len(pending)==1
     other.decide({'id':pending[0]['id'],'approve':True});value={'ok':True}
    elif self.path=='/computers':value={'first':mobile.state['server_id'],'second':other.state['server_id']}
    elif self.path=='/second/inspect':value={'titles':[i['title'] for i in second.archive.list()],'devices':len(other.state['devices'])}
    elif self.path=='/first/inspect':value={'titles':[i['title'] for i in service.archive.list()]}
    elif self.path=='/second/offline':other.stop();value={'ok':True}
    elif self.path=='/second/online':other.enable(advertise=False,bind='127.0.0.1');value={'ok':True}
    elif self.path=='/approve':
     pending=mobile.status()['pending'];assert len(pending)==1
     mobile.decide({'id':pending[0]['id'],'approve':True});value={'ok':True}
    elif self.path=='/offline':mobile.stop();value={'ok':True}
    elif self.path=='/online':mobile.enable(advertise=True,bind='0.0.0.0');value={'ok':True}
    elif self.path in ('/empty-chats','/restore-chats'):
     with service.lock:
      history=service.question_jobs.read()
      target=seeded_chats if self.path=='/restore-chats' else {'conversations':[],'activeId':''}
      service.clean_chat_history(target,service.archive.root/'conversations.json',history)
     value={'ok':True}
    elif self.path=='/chat-count':value={'count':len(service.chat_history()['conversations'])}
    elif self.path=='/connections':
     with connection_changed:value=dict(connections)
    elif self.path.startswith('/wait-status?after='):
     previous=int(self.path.split('=',1)[1])
     with connection_changed:
      connection_changed.wait_for(lambda:connections['status']>previous,timeout=8);value=dict(connections)
    elif self.path=='/hold-files':file_gate.clear();value={'ok':True}
    elif self.path=='/release-files':file_gate.set();value={'ok':True}
    elif self.path=='/hold-ingest':ingest_gate.clear();ingest_failure.set();value={'ok':True}
    elif self.path=='/release-ingest':ingest_gate.set();value={'ok':True}
    elif self.path=='/hold-items':list_gate.clear();value={'ok':True}
    elif self.path=='/release-items':list_gate.set();value={'ok':True}
    elif self.path=='/prepare-multiple-photos':
     from PIL import Image
     images=[]
     seed=os.urandom(3)
     for index in range(3):
      path=Path(folder)/(f'photo-{seed.hex()}-{index}.png')
      Image.new('RGB',(64,64),(seed[0],seed[1],(seed[2]+index)%256)).save(path)
      images.append(str(path))
     subprocess.run(['xcrun','simctl','addmedia',sys.argv[1],*images],env=env,check=True)
     value={'ok':True}
    elif self.path=='/prepare-original-export':
     import io
     from PIL import Image
     image=io.BytesIO();Image.new('RGB',(120,80),'orange').save(image,'PNG')
     name='stellar-original-'+os.urandom(4).hex()
     export_item=next(entry for entry in service.archive.list() if entry['title']=='Reference fixture')
     service.append_material(export_item['id'],{'expected_updated':export_item['updated'],'attachments':[
      {'name':name+'.txt','data':base64.b64encode(b'Stellar original export fixture').decode()},
      {'name':name+'.png','data':base64.b64encode(image.getvalue()).decode()},
     ],'summarize':False,'read_links':False})
     subprocess.run(['xcrun','simctl','privacy',sys.argv[1],'grant','photos-add','io.github.stellarstar255.secretary.companion'],env=env,check=True)
     value={'name':name}
    elif self.path=='/prepare-detail':
     item=next(item for item in service.archive.list() if item['title']=='Mobile fixture unique note')
     with service.archive.db() as db:db.execute('UPDATE items SET url=? WHERE id=?',('https://example.com/phone-original',item['id']))
     import io
     from PIL import Image
     image=io.BytesIO();Image.new('RGB',(120,80),'orange').save(image,'PNG')
     service.append_material(item['id'],{'expected_updated':service.archive.get(item['id'])['updated'],'attachments':[{'name':'fixture.txt','data':base64.b64encode(b'Phone original fixture').decode()},{'name':'slow.txt','data':base64.b64encode(b'Cancellation fixture').decode()},{'name':'fixture.png','data':base64.b64encode(image.getvalue()).decode()}],'summarize':False,'read_links':False})
     value={'ok':True}
    elif self.path=='/metadata':
     item=next(item for item in service.archive.list() if item['title']=='Edited mobile fixture title')
     value={'title':item['title'],'tags':item['tags']}
    elif self.path=='/desktop-chat-append':
     with service.lock:
      saved=service.question_jobs.read();data=json.loads(json.dumps(saved));chat=next(c for c in data['conversations'] if c['id']==shared_id)
      chat['messages'] += [{'id':'desktop-extra-q','role':'user','text':'Desktop next question','knowledgeQuestion':True},{'id':'desktop-extra-a','role':'assistant','text':'Desktop updated reply','sources':[]}]
      chat['updated']=max(int(time.time()*1000),chat['updated']+1);service.clean_chat_history(data,service.archive.root/'conversations.json',saved)
     value={'ok':True}
    elif self.path=='/chat-inspect':
     chat=next(c for c in service.chat_history()['conversations'] if c['id']==shared_id)
     value={'phone_count':sum(m.get('text')=='Mobile shared question' for m in chat['messages']),'offline_count':sum(m.get('text')=='Offline shared follow-up' for m in chat['messages']),'background_calls':chat_calls.count('Background shared question')}
    elif self.path=='/wait-background':value={'started':background_started.wait(timeout=5)}
    elif self.path=='/finish-background':background_release.set();value={'ok':True}
    elif self.path=='/count':value={'count':len(service.archive.list())}
    else:self.send_error(404);return
    data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  control=ThreadingHTTPServer(('127.0.0.1',18769),Handler);threading.Thread(target=control.serve_forever,daemon=True).start()
  try:
   with patch.object(service,'ask_library',side_effect=synthetic_answer):
    env={**os.environ,'DEVELOPER_DIR':'/Applications/Xcode.app/Contents/Developer'}
    command=['xcodebuild','-project','ios/StellarSecretary.xcodeproj','-scheme','StellarSecretary','-configuration','Debug','-destination','platform=iOS Simulator,id='+sys.argv[1],'-derivedDataPath','build/ios','-resultBundlePath',str(Path('/tmp')/('stellar-ios-results-'+os.urandom(4).hex())),'CODE_SIGN_IDENTITY=-','CODE_SIGNING_ALLOWED=YES','test']
    # Each run owns a synthetic simulator library and outbox. A previous failed
    # run must not leave drafts scoped to an unrelated fixture server ID.
    command += sys.argv[2:]
    inventory=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','--json'],env=env))
    device=next(d for values in inventory['devices'].values() for d in values if d['udid']==sys.argv[1])
    assert device['name']=='Stellar Secretary Trial','Use the dedicated trial simulator only'
    subprocess.run(['xcrun','simctl','uninstall',sys.argv[1],'io.github.stellarstar255.secretary.companion'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    result=subprocess.run(command,cwd=ROOT,env=env)
    if result.returncode:
     print('Fixture archive titles:',[item['title'] for item in service.archive.list()],flush=True)
     print('Fixture chat calls:',chat_calls,flush=True)
     print('Fixture shared messages:',[(m.get('role'),m.get('text'),m.get('requestState')) for c in service.chat_history()['conversations'] if c['id']==shared_id for m in c['messages']],flush=True)
    result.check_returncode()
    if len(sys.argv)==2:assert len(service.archive.list())==6
    assert 'Company queued note' not in [i['title'] for i in second.archive.list()]
    if len(sys.argv)>2:
     print('PASS: selected native iOS scenarios: '+', '.join(sys.argv[2:]))
    else:
     print('PASS: native iOS pairing, Mac approval, pinned HTTPS, short foreground TLS reuse, long-background transport rebuild, suspended offline-attempt recovery, cached list reuse, nonblocking refresh, offline cache across restart, phone metadata editing, tag chips with add and confirmed deletion, automatic inline image previews, top original links and attachment controls, original file cache and download cancellation, note capture, reference details, knowledge answer, offline queue across restart, automatic retry and no duplicate archives, shared desktop chat context, bidirectional messages and offline chat retry')
     print('PASS: multiple approved computers, local names, explicit switching, cache/chat ID isolation, offline queues scoped to original computer, editor restoration, cancelled additions and independent removal')
  finally:background_release.set();control.shutdown();control.server_close();mobile.stop(disable=True);service.close();second.close();third.close()
