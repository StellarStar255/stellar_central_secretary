"""Opt-in, paired LAN companion. Never exposes desktop routes or settings."""
import base64,hashlib,io,ipaddress,json,os,secrets,socket,ssl,subprocess,sys,threading,time,uuid
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

SERVICE_TYPE='_stellar-sec._tcp.local.'
MAX_BODY=16*1024*1024

def addresses():
    import ifaddr
    found=[]
    for adapter in ifaddr.get_adapters():
        for item in adapter.ips:
            if not isinstance(item.ip,str):continue
            ip=ipaddress.ip_address(item.ip)
            if ip.version==4 and not ip.is_loopback and any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):found.append(str(ip))
    return sorted(set(found))

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

class Mobile:
    def __init__(self,service):
        self.service=service;self.root=service.archive.root/'mobile';self.path=self.root/'state.json'
        self.lock=threading.RLock();self.server=None;self.discovery=None;self.info=None;self.pending={};self.invite=None;self.error='';self.operations=threading.BoundedSemaphore(2);self.monitor_stop=threading.Event();self.published_ips=[]
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'server_id':uuid.uuid4().hex,'devices':{},'receipts':{},'enabled':False}
        if self.state.get('enabled'):
            try:self.enable()
            except Exception as exc:self.error=str(exc)
    def save(self):
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state,ensure_ascii=False));temp.chmod(0o600);os.replace(temp,self.path)
    def certificate(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        cert=self.root/'certificate.pem';key=self.root/'private-key.pem'
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if not cert.exists() or not key.exists():
            private=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.now(timezone.utc)
            name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Stellar Secretary '+self.state['server_id'])])
            value=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=3650)).add_extension(x509.SubjectAlternativeName([x509.DNSName('stellar-'+self.state['server_id']+'.local')]),critical=False).sign(private,hashes.SHA256())
            key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
            cert.write_bytes(value.public_bytes(serialization.Encoding.PEM));cert.chmod(0o600)
        value=x509.load_pem_x509_certificate(cert.read_bytes());self.fingerprint=value.fingerprint(hashes.SHA256()).hex()
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key)
        return context
    def enable(self,port=0,advertise=True,bind='0.0.0.0'):
        with self.lock:
            if self.server:return self.status()
            self.tls=self.certificate()
            class Gateway(ThreadingHTTPServer):
                daemon_threads=True
                request_queue_size=32
                slots=threading.BoundedSemaphore(32)
                def process_request(server,request,address):
                    if not server.slots.acquire(blocking=False):request.close();return
                    try:super().process_request(request,address)
                    except BaseException:server.slots.release();raise
                def process_request_thread(server,request,address):
                    try:super().process_request_thread(request,address)
                    finally:server.slots.release()
                def handle_error(server,request,address):pass
            server=Gateway((bind,port),self.handler());self.server=server
            threading.Thread(target=server.serve_forever,daemon=True,name='mobile-https').start()
            try:
                if advertise:
                    self.publish(addresses());self.monitor_stop=threading.Event()
                    threading.Thread(target=self.watch_network,args=(self.monitor_stop,),daemon=True,name='mobile-discovery').start()
                self.state['enabled']=True;self.error='';self.save()
            except Exception:
                self.stop();raise
            return self.status()
    def clear_discovery(self):
        if self.discovery and hasattr(self.discovery,'terminate'):
            self.discovery.terminate()
            try:self.discovery.wait(timeout=5)
            except subprocess.TimeoutExpired:self.discovery.kill();self.discovery.wait(timeout=5)
            self.discovery=None;self.info=None
    def publish(self,ips):
        self.clear_discovery()
        if self.discovery:
            try:
                if self.info:self.discovery.unregister_service(self.info)
            finally:self.discovery.close();self.discovery=None;self.info=None
        self.published_ips=[]
        if not ips or not self.server:return
        if sys.platform=='darwin':
            self.discovery=subprocess.Popen(['/usr/bin/dns-sd','-R','Stellar '+self.state['server_id'][:8],'_stellar-sec._tcp','local',str(self.server.server_port),'id='+self.state['server_id'],'v=1'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.published_ips=list(ips);return
        from zeroconf import Zeroconf,ServiceInfo,IPVersion
        self.discovery=Zeroconf(interfaces=ips,ip_version=IPVersion.V4Only)
        self.info=ServiceInfo(SERVICE_TYPE,'Stellar '+self.state['server_id'][:8]+'.'+SERVICE_TYPE,addresses=[socket.inet_aton(ip) for ip in ips],port=self.server.server_port,properties={'id':self.state['server_id'],'v':'1'},server='stellar-'+self.state['server_id']+'.local.')
        self.discovery.register_service(self.info);self.published_ips=list(ips)
    def watch_network(self,stop):
        while not stop.wait(5):
            with self.lock:
                if stop.is_set() or not self.server:return
                try:
                    ips=addresses()
                    if ips!=self.published_ips or (self.discovery and hasattr(self.discovery,'poll') and self.discovery.poll() is not None):self.publish(ips)
                    self.error=''
                except Exception:self.error='局域网发现暂不可用，请检查 Wi-Fi 与系统的本地网络权限'
    def stop(self,disable=False):
        with self.lock:
            self.monitor_stop.set()
            server,self.server=self.server,None
            self.clear_discovery()
            if self.discovery:
                try:
                    if self.info:self.discovery.unregister_service(self.info)
                finally:self.discovery.close();self.discovery=None;self.info=None
            self.invite=None;self.pending.clear()
            if disable:self.state['enabled']=False;self.save()
        if server:server.shutdown();server.server_close()
    def status(self):
        with self.lock:
            now=time.time();self.pending={key:value for key,value in self.pending.items() if value['expires']>now}
            return {'enabled':self.server is not None,'server_id':self.state['server_id'],'name':socket.gethostname(),'port':self.server.server_port if self.server else None,'addresses':addresses() if self.server else [],'error':self.error,
                'pending':[{'id':key,'name':value['name'],'code':value['code']} for key,value in self.pending.items()],
                'devices':[{'id':key,'name':value['name'],'created':value['created']} for key,value in self.state['devices'].items()]}
    def invitation(self):
        with self.lock:
            if not self.server:raise ValueError('请先开启手机连接')
            ips=addresses()
            if not ips:raise ValueError('未找到局域网地址，请先连接 Wi-Fi')
            self.invite={'secret':secrets.token_urlsafe(32),'expires':time.time()+300};self.pending.clear()
            payload={'v':1,'server_id':self.state['server_id'],'name':socket.gethostname(),'url':f'https://{ips[0]}:{self.server.server_port}','fingerprint':self.fingerprint,'secret':self.invite['secret']}
            import qrcode
            image=qrcode.make(json.dumps(payload,separators=(',',':')));buffer=io.BytesIO();image.save(buffer,format='PNG')
            return {'qr':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),'expires':self.invite['expires']}
    def pair(self,body):
        with self.lock:
            if not self.invite or self.invite['expires']<=time.time() or not secrets.compare_digest(str(body.get('secret','')),self.invite['secret']):raise PermissionError('配对码已失效，请在电脑上刷新二维码')
            credential=body.get('credential','');name=body.get('name','')
            if not isinstance(credential,str) or not 40<=len(credential)<=100 or not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('配对信息格式无效')
            key=uuid.uuid4().hex;self.pending[key]={'name':name.strip(),'hash':digest(credential),'code':str(secrets.randbelow(1000000)).zfill(6),'expires':time.time()+300}
            self.invite=None
            return {'id':key,'code':self.pending[key]['code'],'server_id':self.state['server_id']}
    def decide(self,body):
        with self.lock:
            key=body.get('id');pending=self.pending.pop(key,None)
            if not pending or pending['expires']<=time.time():raise ValueError('配对请求已失效，请重新扫码')
            if body.get('approve') is True:
                if len(self.state['devices'])>=10:raise ValueError('最多配对 10 台设备，请先移除旧设备')
                self.state['devices'][key]={'name':pending['name'],'hash':pending['hash'],'created':datetime.now(timezone.utc).isoformat()};self.save()
            return self.status()
    def device(self,credential):
        if not credential:return None
        hashed=digest(credential)
        with self.lock:return next((key for key,value in self.state['devices'].items() if secrets.compare_digest(value['hash'],hashed)),None)
    def revoke(self,key):
        with self.lock:self.state['devices'].pop(key,None);self.save()
        return self.status()
    def public_item(self,item,detail=False):
        result={key:item.get(key,'') for key in ('id','title','kind','state','summary','url','created')}
        if detail:result['text']=item.get('text','')[:100000]
        return result
    def ingest(self,device,body):
        key=body.get('request_id');content=body.get('content')
        if not isinstance(key,str) or not 1<=len(key)<=80 or not isinstance(content,dict):raise ValueError('归档请求格式无效')
        allowed={k:content[k] for k in ('text','url','filename','data','note_reference') if k in content};allowed['archive_only']=True
        signature=digest(json.dumps(allowed,sort_keys=True));receipt=device+':'+key
        with self.lock:
            previous=self.state['receipts'].get(receipt)
            if previous:
                if previous['signature']!=signature:raise ValueError('这条待发送内容已改变，请重新建档')
                return {'item':self.public_item(self.service.archive.get(previous['id'])),'duplicate':True}
            result=self.service.ingest(allowed);self.state['receipts'][receipt]={'id':result['item']['id'],'signature':signature}
            # Keep identifiers only. No documents or credentials in receipts.
            self.save();return {'item':self.public_item(result['item']),'duplicate':not result['created']}
    def handler(self):
        manager=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def setup(self):
                self.request.settimeout(10)
                self.request=manager.tls.wrap_socket(self.request,server_side=True)
                super().setup();self.connection.settimeout(20)
            def finish(self):
                try:super().finish()
                finally:self.connection.close()
            def send(self,status,value):
                data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                try:self.wfile.write(data)
                except OSError:pass
            def do_GET(self):self.route(False)
            def do_POST(self):self.route(True)
            def route(self,post):
                try:
                    # Native clients only. Browser origins (including null) have no LAN API access.
                    if self.headers.get('Origin') is not None:return self.send(403,{'error':'请使用已配对的手机 App'})
                    parsed=urlsplit(self.path);body={}
                    if post:
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=MAX_BODY:return self.send(413,{'error':'单次发送不能超过 16 MB'})
                        raw=self.rfile.read(length)
                        if len(raw)!=length:raise ValueError('上传中断')
                        body=json.loads(raw)
                        if not isinstance(body,dict):raise ValueError('请求格式无效')
                    credential=self.headers.get('Authorization','').removeprefix('Bearer ')
                    if post and parsed.path=='/pair':return self.send(200,manager.pair(body))
                    device=manager.device(credential)
                    if parsed.path=='/pair/status' and not post:
                        if device:return self.send(200,{'approved':True,'server_id':manager.state['server_id']})
                        with manager.lock:pending=any(value['expires']>time.time() and secrets.compare_digest(value['hash'],digest(credential)) for value in manager.pending.values())
                        return self.send(202 if pending else 403,{'approved':False,'error':'' if pending else '配对未获批准或已失效'})
                    if not device:return self.send(401,{'error':'设备未配对或已被移除，请重新扫码'})
                    if not post and parsed.path=='/status':return self.send(200,{'connected':True,'server_id':manager.state['server_id'],'name':socket.gethostname()})
                    if not post and parsed.path=='/items':
                        query=parse_qs(parsed.query).get('q',[''])[0][:200];items=manager.service.archive.list(q=query)
                        return self.send(200,{'items':[manager.public_item(item) for item in items[:50]]})
                    if not post and parsed.path.startswith('/items/'):
                        return self.send(200,{'item':manager.public_item(manager.service.archive.get(parsed.path.split('/')[-1]),True)})
                    if post and parsed.path in ('/ingest','/ask'):
                        if not manager.operations.acquire(blocking=False):return self.send(429,{'error':'电脑正在处理手机请求，请稍后重试'})
                        with manager.service.lock:
                            if manager.service.stopping:
                                manager.operations.release();raise ValueError('电脑服务正在退出')
                            manager.service.questions+=1
                        try:
                            if parsed.path=='/ingest':result=manager.ingest(device,body)
                            else:
                                question=body.get('question','')
                                if not isinstance(question,str) or not question.strip() or len(question)>4000:raise ValueError('问题需为 1–4000 个字符')
                                result=manager.service.ask_library(question)
                                result={key:result.get(key) for key in ('answer','sources','retrieval_notice')}
                            return self.send(200,result)
                        finally:
                            with manager.service.lock:manager.service.questions-=1
                            manager.operations.release()
                    return self.send(404,{'error':'不存在'})
                except PermissionError as exc:self.send(403,{'error':str(exc)})
                except (ValueError,KeyError,TypeError) as exc:self.send(400,{'error':str(exc)})
                except Exception:self.send(500,{'error':'手机请求未完成，请在电脑端检查任务状态'})
        return Handler
