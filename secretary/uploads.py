"""Disk upload journals with verified prefixes and independent consumer leases."""
import hashlib,json,re,threading,time,uuid
from pathlib import Path
MAX_FILE=1024**3
MAX_BATCH=2*1024**3
CHUNK=4*1024**2
QUOTA=4*1024**3
class Uploads:
    def __init__(self,root):
        self.folder=Path(root)/'uploads';self.folder.mkdir(exist_ok=True);self.lock=threading.RLock();self.nonce=uuid.uuid4().hex
    def path(self,key):
        if not re.fullmatch('[a-f0-9]{32}',str(key)):raise ValueError('上传编号无效')
        return self.folder/key
    def _write(self,key,value):
        path=self.path(key).with_suffix('.json');temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.replace(path)
    def _read(self,key):
        path=self.path(key)
        try:value=json.loads(path.with_suffix('.json').read_text());size=path.stat().st_size
        except (OSError,ValueError) as error:raise ValueError('上传暂存已过期，请重新开始') from error
        value.setdefault('chunks',{});value.setdefault('leases',{});value.setdefault('offset',size)
        offset=value.get('offset',size)
        if size<offset:raise ValueError('上传暂存不完整，请重新开始')
        if size>offset:
            with path.open('ab') as stream:stream.truncate(offset)
        if value.get('server')!=self.nonce:value.update(server=self.nonce,leases={});self._write(key,value)
        return value
    def _lease(self,value,lease):
        if value.get('leases') and lease not in value['leases']:raise ValueError('上传任务已失效，请重新选择文件继续')
    def cleanup(self):
        for path in self.folder.glob('*.json'):
            try:
                value=json.loads(path.read_text())
                if time.time()-value.get('updated',path.stat().st_mtime)>86400:self.path(path.stem).unlink(missing_ok=True);path.unlink(missing_ok=True)
            except (OSError,ValueError):continue
    def start(self,name,size,fingerprint=None,owner=None,fresh=False):
        with self.lock:
            self.cleanup()
            if type(size) is not int or not 0<=size<=MAX_FILE:raise ValueError('单个附件最大 1 GB')
            if not isinstance(name,str) or Path(name).name!=name or not name or len(name)>300:raise ValueError('附件文件名无效')
            if fingerprint is not None and (not isinstance(fingerprint,str) or len(fingerprint)>1200):raise ValueError('文件标识无效')
            if owner is not None and (not isinstance(owner,str) or len(owner)>150):raise ValueError('上传任务标识无效')
            key=None
            if fingerprint and not fresh:
                for path in self.folder.glob('*.json'):
                    value=self._read(path.stem)
                    if value.get('fingerprint')==fingerprint and value['name']==name and value['size']==size:key=path.stem;break
            if key is None:
                used=sum(json.loads(path.read_text())['size'] for path in self.folder.glob('*.json'))
                if used+size>QUOTA:raise ValueError('待提交附件超过本机 4 GB 暂存上限，请先提交或移除附件')
                key=uuid.uuid4().hex;self.path(key).touch();value={'name':name,'size':size,'fingerprint':fingerprint,'offset':0,'chunks':{},'leases':{},'server':self.nonce}
            lease=''
            if owner:
                lease=next((key for key,value in value['leases'].items() if value==owner),None) or uuid.uuid4().hex
                value['leases'][lease]=owner
            value['updated']=time.time();self._write(key,value)
            return {'id':key,'offset':value.get('offset',self.path(key).stat().st_size),'chunks':value.get('chunks',{}),'lease':lease}
    def status(self,key,lease=None):
        with self.lock:
            value=self._read(key);self._lease(value,lease)
            return {'id':key,'offset':value.get('offset',self.path(key).stat().st_size),'chunks':value.get('chunks',{}),'size':value['size']}
    def chunk(self,key,offset,stream,length,lease=None,verify=False):
        with self.lock:
            value=self._read(key);self._lease(value,lease);path=self.path(key)
            if type(offset) is not int or not 0<length<=CHUNK:raise ValueError('分块位置或大小无效，请重试上传')
            if not verify and (offset!=value.get('offset',path.stat().st_size) or offset+length>value['size']):raise ValueError('上传进度已更新，请重试继续')
            if verify and str(offset) not in value.get('chunks',{}):raise ValueError('待核对分块不存在')
            digest=hashlib.sha256()
            try:
                with path.open('ab') as output:
                    remaining=length
                    while remaining:
                        data=stream.read(min(65536,remaining))
                        if not data:raise ValueError('附件上传中断')
                        digest.update(data)
                        if not verify:output.write(data)
                        remaining-=len(data)
                if verify:
                    if value['chunks'][str(offset)]!=digest.hexdigest():raise ValueError('所选文件与已上传部分不同，请重新开始')
                    return {'verified':True}
                value['chunks'][str(offset)]=digest.hexdigest();value['offset']=offset+length;value['updated']=time.time();self._write(key,value)
            except BaseException:
                if not verify:
                    with path.open('ab') as output:output.truncate(offset)
                raise
            return {'id':key,'offset':offset+length}
    def resolve(self,files):
        if not isinstance(files,list):raise ValueError('附件列表无效')
        result=[]
        with self.lock:
            for file in files:
                if not isinstance(file,dict):raise ValueError('附件格式无效')
                if 'upload_id' not in file:result.append(file);continue
                value=self._read(file['upload_id']);self._lease(value,file.get('lease'));path=self.path(file['upload_id'])
                if file.get('name')!=value['name'] or path.stat().st_size!=value['size']:raise ValueError('附件尚未完整上传')
                result.append({'name':value['name'],'source':path})
        return result
    def discard(self,key,lease=None):
        with self.lock:
            path=self.path(key)
            if not path.exists():return
            value=self._read(key);self._lease(value,lease)
            if lease:value['leases'].pop(lease,None)
            if value.get('leases'):value['updated']=time.time();self._write(key,value);return
            path.unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)
