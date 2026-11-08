"""Authenticated sequential disk uploads; browser requests never supply local paths."""
import json,re,threading,time,uuid
from pathlib import Path

MAX_FILE=1024**3
MAX_BATCH=2*1024**3
CHUNK=4*1024**2
QUOTA=4*1024**3
class Uploads:
    def __init__(self,root):self.folder=Path(root)/'uploads';self.folder.mkdir(exist_ok=True);self.lock=threading.RLock()
    def path(self,key):
        if not re.fullmatch('[a-f0-9]{32}',str(key)):raise ValueError('上传编号无效')
        return self.folder/key
    def cleanup(self):
        for path in self.folder.iterdir():
            if time.time()-path.stat().st_mtime>86400:path.unlink(missing_ok=True)
    def start(self,name,size):
        with self.lock:
            self.cleanup()
            if type(size) is not int or not 0<=size<=MAX_FILE:raise ValueError('单个附件最大 1 GB')
            if not isinstance(name,str) or Path(name).name!=name or not name or len(name)>300:raise ValueError('附件文件名无效')
            used=sum(json.loads(path.read_text())['size'] for path in self.folder.glob('*.json'))
            if used+size>QUOTA:raise ValueError('待提交附件超过本机 4 GB 暂存上限，请先提交或移除附件')
            key=uuid.uuid4().hex;path=self.path(key);path.touch();path.with_suffix('.json').write_text(json.dumps({'name':name,'size':size}))
            return {'id':key,'offset':0}
    def chunk(self,key,offset,stream,length):
        with self.lock:
            path=self.path(key);meta=json.loads(path.with_suffix('.json').read_text())
            if type(offset) is not int or offset!=path.stat().st_size or not 0<length<=CHUNK or offset+length>meta['size']:raise ValueError('分块位置或大小无效，请重试上传')
            try:
                with path.open('ab') as output:
                    remaining=length
                    while remaining:
                        data=stream.read(min(65536,remaining))
                        if not data:raise ValueError('附件上传中断')
                        output.write(data);remaining-=len(data)
            except BaseException:
                with path.open('ab') as output:output.truncate(offset)
                raise
            return {'id':key,'offset':offset+length}
    def resolve(self,files):
        if not isinstance(files,list):raise ValueError('附件列表无效')
        result=[]
        for file in files:
            if not isinstance(file,dict):raise ValueError('附件格式无效')
            if 'upload_id' not in file:result.append(file);continue
            path=self.path(file['upload_id']);meta=json.loads(path.with_suffix('.json').read_text())
            if file.get('name')!=meta['name'] or path.stat().st_size!=meta['size']:raise ValueError('附件尚未完整上传')
            result.append({'name':meta['name'],'source':path})
        return result
    def discard(self,key):
        with self.lock:
            path=self.path(key);path.unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)
