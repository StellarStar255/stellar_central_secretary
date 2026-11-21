"""Opt-in, paired LAN companion. Never exposes desktop routes or settings."""
import re,errno,base64,hashlib,io,ipaddress,json,os,secrets,socket,ssl,subprocess,sys,threading,time,uuid
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

from .shared_chat import ChatBusy, attachment_batch
from . import company_ai, mobile_privacy

SERVICE_TYPE='_stellar-sec._tcp.local.'
MAX_BODY=16*1024*1024

def addresses(include_alternates=False):
    import ifaddr
    found=[]
    for adapter in ifaddr.get_adapters():
        for item in adapter.ips:
            if isinstance(item.ip,str):
                ip=ipaddress.ip_address(item.ip)
                networks=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16') + (('100.64.0.0/10','169.254.0.0/16') if include_alternates else ())
                if ip.version==4 and not ip.is_loopback and any(ip in ipaddress.ip_network(net) for net in networks):found.append(str(ip))
            elif include_alternates and isinstance(item.ip,tuple):
                ip=ipaddress.ip_address(item.ip[0].split('%')[0])
                # Only local IPv6, never public Internet addresses. The client supplies its own interface scope.
                if ip.version==6 and ip.is_link_local and str(adapter.name).startswith(('en','wl','Wi-Fi','Ethernet')):found.append(str(ip))
    def rank(value):
        ip=ipaddress.ip_address(value)
        return (1 if ip.version==6 else 3 if ip.is_link_local else 2 if ip in ipaddress.ip_network('100.64.0.0/10') else 0,value)
    return sorted(set(found),key=rank)[:8]

def endpoint(ip,port):
    return f'https://[{ip}]:{port}' if ':' in ip else f'https://{ip}:{port}'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

class Mobile:
    def __init__(self,service):
        self.service=service;self.root=service.archive.root/'mobile';self.path=self.root/'state.json'
        from .shared_chat import SharedChat
        self.chats=SharedChat(service)
        self.peer_bridge=None
        self.upload_progress={};self.upload_lock=threading.Lock()
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
            dual=bind=='0.0.0.0' and socket.has_dualstack_ipv6()
            class Gateway(ThreadingHTTPServer):
                address_family=socket.AF_INET6 if dual else socket.AF_INET
                def server_bind(server):
                    if dual:server.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
                    super().server_bind()
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
            requested=port or self.state.get('port',0)
            try:server=Gateway(('::' if dual else bind,requested),self.handler())
            except OSError as exc:
                # Winsock reports an exclusively occupied port as WSAEACCES.
                occupied=exc.errno==errno.EADDRINUSE or getattr(exc,'winerror',None)==10013
                if port or not requested or not occupied:raise
                server=Gateway(('::' if dual else bind,0),self.handler())
            self.server=server;self.state['port']=server.server_port
            threading.Thread(target=server.serve_forever,daemon=True,name='mobile-https').start()
            try:
                if advertise:
                    self.publish(addresses());self.monitor_stop=threading.Event()
                    from . import peer_bridge
                    self.peer_bridge=peer_bridge.start(self.state['server_id'],server.server_port)
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
                    from . import peer_bridge
                    if sys.platform=='darwin' and (self.peer_bridge is None or self.peer_bridge.poll() is not None):
                        self.peer_bridge=peer_bridge.start(self.state['server_id'],self.server.server_port)
                    ips=addresses()
                    if ips!=self.published_ips or (self.discovery and hasattr(self.discovery,'poll') and self.discovery.poll() is not None):self.publish(ips)
                    self.error=''
                except Exception:self.error='局域网发现暂不可用，请检查 Wi-Fi 与系统的本地网络权限'
    def stop(self,disable=False):
        with self.lock:
            self.monitor_stop.set()
            from . import peer_bridge
            peer_bridge.stop(self.peer_bridge);self.peer_bridge=None
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
            return {'nearby_active':self.peer_bridge is not None and self.peer_bridge.poll() is None,'enabled':self.server is not None,'server_id':self.state['server_id'],'name':socket.gethostname(),'port':self.server.server_port if self.server else None,'addresses':addresses(include_alternates=True) if self.server else [],'error':self.error,
                'pending':[{'id':key,'name':value['name'],'code':value['code']} for key,value in self.pending.items()],
                'devices':[{'id':key,'name':value['name'],'created':value['created'],'nickname':value.get('nickname','')} for key,value in self.state['devices'].items()]}
    def invitation(self):
        with self.lock:
            if not self.server:raise ValueError('请先开启手机连接')
            ips=addresses(include_alternates=True)
            if not ips:raise ValueError('未找到局域网地址，请先连接 Wi-Fi')
            self.invite={'secret':secrets.token_urlsafe(32),'expires':time.time()+300};self.pending.clear()
            payload={'v':1,'server_id':self.state['server_id'],'name':socket.gethostname(),'url':endpoint(ips[0],self.server.server_port),'fingerprint':self.fingerprint,'secret':self.invite['secret'],'urls':[endpoint(ip,self.server.server_port) for ip in ips]}
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

    def rename_device(self,body):
        key=body.get('id');nickname=body.get('nickname')
        if not isinstance(key,str) or not isinstance(nickname,str) or len(nickname.strip())>80:
            raise ValueError('设备备注名最多 80 个字符。')
        with self.lock:
            entry=self.state['devices'].get(key)
            if entry is None:raise ValueError('设备已移除，请刷新列表。')
            self.state['devices'][key]={**entry,'nickname':nickname.strip()}
            try:self.save()
            except OSError:
                self.state['devices'][key]=entry
                raise
            return self.status()

    def model_privacy(self, device):
        enabled=self.service.archive.settings()['auto_ai']
        try:
            info = mobile_privacy.destination(self.service.model_backend())
        except ValueError:
            return {'destination':'请先在电脑上完成模型配置','model':'','fingerprint':'','approved':False,'summary_approved':False,'desktop_auto_summary':enabled}
        entry=self.state['devices'].get(device,{})
        return {**info,'approved':entry.get('model_consent') == info['fingerprint'],
                'summary_approved':entry.get('summary_consent') == info['fingerprint'],'desktop_auto_summary':enabled}

    def set_model_privacy(self, device, body):
        with self.lock:
            entry = self.state['devices'].get(device)
            if entry is None:
                raise PermissionError('设备已解除配对')
            info = self.model_privacy(device)
            updated = dict(entry)
            scope=body.get('scope','chat')
            if scope not in ('chat','summary'):raise ValueError('无效的模型授权')
            consent,grant,flag=('summary_consent','summary_grant','summary_approved') if scope=='summary' else ('model_consent','consent_grant','approved')
            if body.get('approved') is True:
                if not info['fingerprint'] or body.get('fingerprint') != info['fingerprint']:
                    raise mobile_privacy.ApprovalRequired()
                # An in-flight job must not inherit a later grant after revocation.
                if not info[flag]:
                    updated.update({consent:info['fingerprint'],grant:secrets.token_hex(16)})
            elif body.get('approved') is False:
                updated.pop(consent,None)
                updated.pop(grant,None)
            else:
                raise ValueError('无效的模型授权')
            self.state['devices'][device] = updated
            try:
                self.save()
            except OSError:
                self.state['devices'][device] = entry
                raise
            return {**info,flag:body['approved']}

    def authorize_model(self, device, summary=False):
        # Capture the grant at request admission, then recheck it in each model
        # lookup on the worker. Reading the entry does not take the service lock.
        entry = dict(self.state['devices'].get(device, {}))
        grant_key,consent_key=('summary_grant','summary_consent') if summary else ('consent_grant','model_consent')
        grant = entry.get(grant_key)
        fingerprint = entry.get(consent_key)

        def authorize(config):
            current = self.state['devices'].get(device, {})
            if not grant or current.get(grant_key) != grant or mobile_privacy.destination(config)['fingerprint'] != fingerprint or (summary and not self.service.archive.settings()['auto_ai']):
                raise mobile_privacy.ApprovalRequired()

        info = self.model_privacy(device)
        if not info['summary_approved' if summary else 'approved']:
            raise mobile_privacy.ApprovalRequired()
        return authorize

    def queue_summary(self,device,item_id,batch_id=None):
        if not self.service.archive.settings()['auto_ai']:return
        try:authorize=self.authorize_model(device,summary=True)
        except mobile_privacy.ApprovalRequired:return
        token=mobile_privacy.active.set(authorize)
        try:
            if batch_id:self.service.retry_addition(item_id,batch_id)
            else:self.service.queue(item_id)
        except (ValueError,KeyError):
            # The archive is already saved. Consent may have changed or the
            # desktop may be working on the same record.
            pass
        finally:mobile_privacy.active.reset(token)
    def public_item(self,item,detail=False):
        result={key:item.get(key,'') for key in ('id','title','kind','state','summary','url','created','updated','tags')}
        if detail:
            result['text']=item.get('text','')[:100000]
            item=self.service.material_attachments(item)
            result['attachments']=[]
            from . import image_formats
            for file in item['all_attachments']:
                path='/items/'+item['id']+'/files/'+(file['batch_id'] or 'base')+'/'+file['id']
                source=self.service.archive.root/'files'/(file['batch_id'] or item['id'])
                stat=source.stat();version=digest(item['id']+file['batch_id']+file['id']+str(stat.st_mtime_ns)+str(stat.st_size))
                result['attachments'].append({'id':file['id'],'name':file['name'],'media':file.get('media','application/octet-stream'),
                    'path':path,'size':file.get('size',stat.st_size),'version':version,
                    'preview_path':path+'/preview' if image_formats.is_image(file['name']) else ''})
            result['links']=[{'title':link.get('title') or link['url'],'url':link['url']} for link in item.get('group_links',[])]
            for batch in item.get('additions',[]):
                result['links'] += [{'title':link.get('title') or link['url'],'url':link['url']} for link in batch.get('links',[])]
        return result

    def capture_receipt(self,item):
        progress=self.service.summary_jobs.snapshot(item['id'])
        state=item['state']
        message=''
        if (progress and progress['active']) or state=='processing':
            stage='processing'
        elif state=='error':
            from .task_status import explain
            stage='error';message=explain(item['error'])['message']
            if '隐私与 AI' in item['error'] or '当前模型未启用图片输入' in item['error']:message=item['error']
        elif item['summary']:
            stage='ready'
        else:
            stage='archived'
            if state=='needs_content':
                if item['filename']:message='原件已保存，可以直接打开。暂未提取到文字。'
                elif item['url']:message='链接已保存。可在电脑上读取网页正文。'
            if not message and (item['error']==company_ai.PENDING or item['error'].startswith('已停止整理')):
                message=item['error']
        return {'id':item['id'],'title':item['title'],'stage':stage,'message':message}

    def recent_captures(self,device):
        with self.lock:
            ids=list(dict.fromkeys(entry['id'] for key,entry in reversed(self.state['receipts'].items()) if key.startswith(device+':')))
        records=[]
        for item_id in ids:
            try:records.append(self.capture_receipt(self.service.archive.get(item_id)))
            except KeyError:continue
            if len(records)==8:break
        return records
    def edit_metadata(self,item_id,body):
        title=body.get('title');tags=body.get('tags')
        if not isinstance(title,str) or not title.strip() or len(title.strip())>300:raise ValueError('标题需为 1–300 个字符')
        if not isinstance(tags,list) or len(tags)>50 or any(not isinstance(tag,str) or not tag.strip() or len(tag.strip())>60 for tag in tags):raise ValueError('最多 50 个标签，每个标签需为 1–60 个字符')
        with self.service.lock,self.service.archive.lock:
            item=self.service.archive.get(item_id)
            if item_id in self.service.busy or item_id in self.service.captures:raise ValueError('资料正在处理，请稍后修改')
            if not body.get('expected_updated') or body['expected_updated']!=item['updated']:raise ValueError('资料已在其他位置更新，请重新加载后修改；本次草稿仍保留')
            self.service.archive.set_tags(item_id,tags,expected=item['tags'])
            self.service.archive.update(item_id,title=title.strip())
            return {'item':self.public_item(self.service.archive.get(item_id),True)}
    def append_attachment(self,device,item_id,body):
        key=body.get('request_id');name=body.get('filename');encoded=body.get('data')
        if not isinstance(key,str) or not 1<=len(key)<=80 or not isinstance(name,str) or not name or len(name)>300 or '/' in name or '\\' in name:raise ValueError('附件信息无效')
        if not isinstance(encoded,str) or len(encoded)>14*1024*1024:raise ValueError('手机附件最多 10 MB')
        try:raw=base64.b64decode(encoded,validate=True)
        except Exception:raise ValueError('附件编码无效')
        if len(raw)>10*1024*1024:raise ValueError('手机附件最多 10 MB')
        signature=digest(item_id+'\n'+name+'\n'+hashlib.sha256(raw).hexdigest());receipt=device+':'+key
        with self.lock:
            receipts=self.state.setdefault('attachment_receipts',{})
            previous=receipts.get(receipt)
            if previous:
                if previous['signature']!=signature:raise ValueError('这次附件内容已改变，请重新选择附件')
            else:
                result=self.service.append_material(item_id,{'expected_updated':body.get('expected_updated'),'attachments':[{'name':name,'data':encoded}],'read_links':False,'summarize':False})
                receipts[receipt]={'signature':signature,'id':item_id};self.save()
                self.queue_summary(device,item_id,result['batch_id'])
            return {'item':self.public_item(self.service.archive.get(item_id),True),'duplicate':previous is not None}
    def attachment(self,item_id,batch_id,key):
        from . import bundles
        item=self.service.material_attachments(self.service.archive.get(item_id))
        batch='' if batch_id=='base' else batch_id
        file=next((file for file in item['all_attachments'] if file['batch_id']==batch and file['id']==key),None)
        if not file:raise ValueError('附件不存在或已移除')
        source=self.service.archive.root/'files'/(batch or item_id)
        if key!='original':_,source=bundles.member(source,key)
        return file,source
    def ingest(self,device,body):
        key=body.get('request_id');content=body.get('content')
        if not isinstance(key,str) or not 1<=len(key)<=80 or not isinstance(content,dict):raise ValueError('归档请求格式无效')
        allowed={k:content[k] for k in ('text','url','filename','data','note_reference') if k in content};allowed['archive_only']=True
        if 'attachments' in content:
            if any(key in content for key in ('filename','data','url')):raise ValueError('附件格式无效')
            allowed['attachments'],_=attachment_batch(content['attachments'])
            allowed['title']=str(allowed.get('text') or '').strip()[:100] or allowed['attachments'][0]['name']
        signature=digest(json.dumps(allowed,sort_keys=True));receipt=device+':'+key
        with self.lock:
            previous=self.state['receipts'].get(receipt)
            if previous:
                if previous['signature']!=signature:raise ValueError('这条待发送内容已改变，请重新建档')
                result={'item':self.service.archive.get(previous['id']),'created':False,'updated':False}
                target=previous.get('chat_id',self.service.chat_history().get('activeId',''))
            else:
                target=self.service.chat_history().get('activeId','')
                result=self.service.ingest(allowed)
                self.state['receipts'][receipt]={'id':result['item']['id'],'signature':signature,'chat_id':target}
                # Identifiers only; no documents, invitation secrets or credentials.
                self.save()
                if result['created'] and not (allowed.get('url') and not allowed.get('text') and not allowed.get('filename')):
                    self.queue_summary(device,result['item']['id'])
            from .extension_chat import append_receipt
            text=('手机资料已归档。' if result['created'] else '这份手机资料已存在，可直接查看。')
            result=append_receipt(self.service,result,target,digest(receipt),text,namespace='mobile')
            item=self.service.archive.get(result['item']['id'])
            return {'item':self.public_item(item),'capture':self.capture_receipt(item),'duplicate':not result['created'],
                    'chat_synced':result.get('chat_synced',False),**({'chat_sync_error':result['chat_sync_error']} if result.get('chat_sync_error') else {})}
    def sync_receipt(self,item_id):
        """Repair a legacy mobile capture receipt when its original is reprocessed."""
        with self.lock:
            entry=next(((key,value) for key,value in reversed(list(self.state['receipts'].items())) if value['id']==item_id),None)
            if not entry:return
            key,record=entry
            target=record.get('chat_id',self.service.chat_history().get('activeId',''))
            from .extension_chat import append_receipt
            append_receipt(self.service,{'item':self.service.archive.get(item_id),'created':False},target,digest(key),
                           '手机资料已保存，正在按电脑设置整理。',namespace='mobile')

    def handler(self):
        manager=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version="HTTP/1.1"
            def log_message(self,*args):pass
            def setup(self):
                self.request.settimeout(10)
                self.request=manager.tls.wrap_socket(self.request,server_side=True)
                super().setup();self.connection.settimeout(20)
            def finish(self):
                try:super().finish()
                finally:self.connection.close()
            def send(self,status,value):
                if status>=400:self.close_connection=True
                data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close' if self.close_connection else 'keep-alive');self.end_headers()
                try:self.wfile.write(data)
                except OSError:pass
            def do_GET(self):self.route(False)
            def do_POST(self):self.route(True)
            def route(self,post):
                upload_key=None
                try:
                    if manager.server is None:
                        self.close_connection=True
                        return self.send(503,{'error':'手机连接已关闭'})
                    # Native clients only. Browser origins (including null) have no LAN API access.
                    if self.headers.get('Origin') is not None:return self.send(403,{'error':'请使用已配对的手机 App'})
                    parsed=urlsplit(self.path);body={}
                    if post and re.fullmatch(r'/privacy-v1/(?:ingest|chats/[^/]{1,100}/messages|items/[a-f0-9]{32}/attachments)|/privacy-v2/chats/[^/]{1,100}/messages',parsed.path):
                        parsed=parsed._replace(path='/' + parsed.path.split('/',2)[2])
                    credential=self.headers.get('Authorization','').removeprefix('Bearer ')
                    if post:
                        length=int(self.headers.get('Content-Length','0'))
                        if not 0<length<=MAX_BODY:return self.send(413,{'error':'单次发送不能超过 16 MB'})
                        upload_id=self.headers.get('X-Stellar-Upload')
                        if upload_id is not None:
                            if not re.fullmatch(r'[a-f0-9]{32}',upload_id) or not re.fullmatch(r'/ingest|/chats/[^/]{1,100}/messages',parsed.path):
                                return self.send(400,{'error':'上传标识无效'})
                            device=manager.device(credential)
                            if not device:return self.send(401,{'error':'设备未配对或已被移除，请重新扫码'})
                            key=(device,upload_id)
                            with manager.upload_lock:
                                active=key in manager.upload_progress
                                if not active:manager.upload_progress[key]=(0,length)
                            if active:return self.send(409,{'error':'本次上传正在进行'})
                            upload_key=key
                            raw=bytearray()
                            while len(raw)<length:
                                chunk=self.rfile.read1(min(64*1024,length-len(raw)))
                                if not chunk:break
                                raw.extend(chunk)
                                with manager.upload_lock:manager.upload_progress[key]=(len(raw),length)
                        else:
                            raw=self.rfile.read(length)
                        if len(raw)!=length:raise ValueError('上传中断')
                        body=json.loads(raw)
                        if not isinstance(body,dict):raise ValueError('请求格式无效')
                    if post and parsed.path=='/pair':return self.send(200,manager.pair(body))
                    device=manager.device(credential)
                    if parsed.path=='/pair/status' and not post:
                        if device:return self.send(200,{'approved':True,'server_id':manager.state['server_id']})
                        with manager.lock:pending=any(value['expires']>time.time() and secrets.compare_digest(value['hash'],digest(credential)) for value in manager.pending.values())
                        return self.send(202 if pending else 403,{'approved':False,'error':'' if pending else '配对未获批准或已失效'})
                    if not device:return self.send(401,{'error':'设备未配对或已被移除，请重新扫码'})
                    if not post and parsed.path=='/status':return self.send(200,{'connected':True,'server_id':manager.state['server_id'],'name':socket.gethostname(),'urls':[endpoint(ip,manager.server.server_port) for ip in addresses(include_alternates=True)],'privacy_version':1,'capture_receipts':True,'reuse_active_chat':True,'chat_attachments':True,'multi_attachments':True,'upload_progress':True})
                    progress_match=re.fullmatch(r'/upload-progress/([a-f0-9]{32})',parsed.path)
                    if not post and progress_match:
                        with manager.upload_lock:progress=manager.upload_progress.get((device,progress_match[1]))
                        return self.send(200,{'received':progress[0],'total':progress[1]} if progress else {})
                    if not post and parsed.path=='/captures':return self.send(200,{'captures':manager.recent_captures(device)})
                    if parsed.path=='/model-privacy':
                        return self.send(200,manager.set_model_privacy(device,body) if post else manager.model_privacy(device))
                    if not post and parsed.path=='/chats':return self.send(200,manager.chats.listing(parse_qs(parsed.query).get('revision',[''])[0]))
                    if post and parsed.path=='/chats':return self.send(200,manager.chats.create(device,body))
                    chat_match=re.fullmatch(r'/chats/([^/]{1,100})(?:/(messages|stop))?',parsed.path)
                    if chat_match:
                        from urllib.parse import unquote
                        chat_id=unquote(chat_match[1])
                        if post and chat_match[2]=='messages':
                            token=mobile_privacy.active.set(manager.authorize_model(device))
                            try:return self.send(200,manager.chats.send(device,chat_id,body))
                            finally:mobile_privacy.active.reset(token)
                        if post and chat_match[2]=='stop':return self.send(200,manager.chats.stop(chat_id,body))
                        if not post and chat_match[2] is None:
                            query=parse_qs(parsed.query)
                            return self.send(200,manager.chats.detail(chat_id,query.get('revision',[''])[0],query.get('before',[''])[0],query.get('partial_offset',['0'])[0],query.get('partial_id',[''])[0]))
                    file_match=re.fullmatch(r'/items/([a-f0-9]{32})/files/(base|[a-f0-9]{32})/(original|[a-f0-9]{32})(/preview)?',parsed.path)
                    if not post and file_match:
                        file,source=manager.attachment(*file_match.groups()[:3]);size=source.stat().st_size
                        if file_match[4]:
                            from . import mobile_preview,image_formats
                            if not image_formats.is_image(file['name']):raise ValueError('此附件请下载原件')
                            archive=manager.service.archive.root/'files'/(file_match[2] if file_match[2]!='base' else file_match[1])
                            stat=archive.stat();key=digest(file_match[1]+('' if file_match[2]=='base' else file_match[2])+file['id']+str(stat.st_mtime_ns)+str(stat.st_size))
                            data=mobile_preview.render(source,manager.root/'previews',key)
                            self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data);return
                        from urllib.parse import quote
                        self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(size));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(file['name'],safe=''));self.end_headers()
                        with source.open('rb') as stream:
                            while chunk:=stream.read(64*1024):self.wfile.write(chunk)
                        return
                    edit_match=re.fullmatch(r'/items/([a-f0-9]{32})/(metadata|attachments)',parsed.path)
                    if post and edit_match:
                        if edit_match[2]=='metadata':return self.send(200,manager.edit_metadata(edit_match[1],body))
                        if not manager.operations.acquire(blocking=False):return self.send(429,{'error':'电脑正在处理手机请求，请稍后重试'})
                        try:return self.send(200,manager.append_attachment(device,edit_match[1],body))
                        finally:manager.operations.release()
                    if not post and parsed.path=='/items':
                        query=parse_qs(parsed.query).get('q',[''])[0][:200];items=manager.service.archive.list(q=query)
                        return self.send(200,{'items':[manager.public_item(item) for item in items[:50]]})
                    if not post and re.fullmatch(r'/items/[a-f0-9]{32}',parsed.path):
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
                                token=mobile_privacy.active.set(manager.authorize_model(device))
                                try:result=manager.service.ask_library(question)
                                finally:mobile_privacy.active.reset(token)
                                result={key:result.get(key) for key in ('answer','sources','retrieval_notice')}
                            return self.send(200,result)
                        finally:
                            with manager.service.lock:manager.service.questions-=1
                            manager.operations.release()
                    return self.send(404,{'error':'不存在'})
                except ChatBusy as exc:return self.send(409,{'error':str(exc)})
                except mobile_privacy.ApprovalRequired as exc:return self.send(403,{'error':str(exc),'model_consent_required':True})
                except PermissionError as exc:self.send(403,{'error':str(exc)})
                except (ValueError,KeyError,TypeError) as exc:self.send(400,{'error':str(exc)})
                except Exception:self.send(500,{'error':'手机请求未完成，请在电脑端检查任务状态'})
                finally:
                    if upload_key is not None:
                        with manager.upload_lock:manager.upload_progress.pop(upload_key,None)
        return Handler
