"""Disk-streamed local snapshots, bounded retention, and transactional local recovery."""
import hashlib,json,re,shutil,sqlite3,tempfile,threading,uuid,zipfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

class Backups:
    def __init__(self,archive):
        self.archive=archive;self.folder=archive.root/'local-backups';self.folder.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.error='';self.stop=threading.Event()
    def entries(self):
        result=[]
        for path in self.folder.glob('*.json'):
            try:
                value=json.loads(path.read_text());source=self.folder/(value['id']+'.zip')
                if re.fullmatch('[a-f0-9]{32}',value['id']) and source.is_file():result.append(value)
            except (OSError,ValueError,KeyError):pass
        return sorted(result,key=lambda value:value['created'],reverse=True)
    def create(self,reason='manual'):
        with self.lock:
            key=uuid.uuid4().hex;target=self.folder/(key+'.zip');temporary=target.with_suffix('.part')
            try:
                with self.archive.lock,tempfile.TemporaryDirectory(dir=self.folder) as temp:
                    snapshot=Path(temp)/'archive.sqlite3'
                    with closing(sqlite3.connect(snapshot)) as dst,self.archive.db() as src:src.backup(dst)
                    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as output:
                        output.write(snapshot,'archive.sqlite3');output.writestr('archive.json',json.dumps(self.archive.export(),ensure_ascii=False))
                        for source in (self.archive.root/'files').iterdir():
                            if source.is_file():output.write(source,'files/'+source.name)
                        chats=self.archive.root/'conversations.json'
                        if chats.exists():output.write(chats,'conversations.json')
                with temporary.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                temporary.replace(target)
                value={'id':key,'created':datetime.now(timezone.utc).isoformat(),'reason':reason,'size':target.stat().st_size,'sha256':digest}
                meta=self.folder/(key+'.json');meta.write_text(json.dumps(value))
                # Keep seven daily and three upgrade/manual/safety snapshots each.
                for kind in ('daily','upgrade','manual','before-restore'):
                    for old in [v for v in self.entries() if v['reason']==kind][7 if kind=='daily' else 3:]:
                        (self.folder/(old['id']+'.zip')).unlink(missing_ok=True);(self.folder/(old['id']+'.json')).unlink(missing_ok=True)
                self.error='';return value
            except Exception as error:
                temporary.unlink(missing_ok=True);self.error=str(error);raise
    def due(self):
        if not any(value['reason']=='daily' and value['created'][:10]==datetime.now(timezone.utc).isoformat()[:10] for value in self.entries()):self.create('daily')
    def start(self):
        def loop():
            while not self.stop.is_set():
                try:self.due()
                except Exception as error:self.error=str(error)
                self.stop.wait(3600)
        threading.Thread(target=loop,name='local-backups',daemon=True).start()
    def restore(self,key):
        with self.lock,self.archive.lock:
            entry=next((value for value in self.entries() if value['id']==key),None)
            if not entry:raise ValueError('本机备份不存在')
            source=self.folder/(key+'.zip')
            with source.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:raise ValueError('备份校验失败，未修改当前资料')
            with tempfile.TemporaryDirectory(dir=self.folder) as temp:
                stage=Path(temp);incoming=stage/'files';incoming.mkdir()
                with zipfile.ZipFile(source) as archive:
                    for info in archive.infolist():
                        name=info.filename
                        if name not in ('archive.sqlite3','archive.json','conversations.json') and not re.fullmatch(r'files/[a-f0-9]{32}',name):raise ValueError('备份包含无效文件')
                        target=stage/name
                        with archive.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
                database=stage/'archive.sqlite3'
                with closing(sqlite3.connect(database)) as db:
                    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库校验失败')
                    with self.archive.db() as current_db:
                        if db.execute('PRAGMA user_version').fetchone()[0]>current_db.execute('PRAGMA user_version').fetchone()[0]:raise ValueError('备份来自更新版本，请先更新程序')
                    db.execute('SELECT id,title,text FROM items LIMIT 1')
                    refs=[row[0] for row in db.execute("SELECT id FROM items WHERE filename!=''")]
                    if any(not (incoming/value).is_file() for value in refs):raise ValueError('备份缺少原件')
                self.create('before-restore')
                old=stage/'previous-files';current=self.archive.root/'files';current.replace(old)
                old_chats=self.archive.root/'conversations.json';chat_copy=old_chats.read_bytes() if old_chats.exists() else None
                try:
                    incoming.replace(current)
                    if (stage/'conversations.json').exists():shutil.copyfile(stage/'conversations.json',old_chats)
                    else:old_chats.unlink(missing_ok=True)
                    with closing(sqlite3.connect(database)) as src,closing(sqlite3.connect(self.archive.root/'archive.sqlite3')) as dst:src.backup(dst)
                except BaseException:
                    if current.exists():shutil.rmtree(current)
                    old.replace(current)
                    if chat_copy is not None:old_chats.write_bytes(chat_copy)
                    else:old_chats.unlink(missing_ok=True)
                    raise
            return {'ok':True,'restored':key}
