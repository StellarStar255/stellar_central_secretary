"""Disk-streamed local snapshots, bounded retention, and transactional local recovery."""
import hashlib,json,re,shutil,sqlite3,tempfile,threading,uuid,zipfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import os

class Backups:
    def __init__(self,archive):
        self.archive=archive;self.default=archive.root/'local-backups';self.default.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.stop=threading.Event();self.config_path=archive.root/'backup-settings.json';self.state_path=archive.root/'backup-status.json'
        try:self.config=json.loads(self.config_path.read_text())
        except (OSError,ValueError):self.config={}
        self.folder=Path(self.config.get('folder',str(self.default)));self.limit=int(self.config.get('max_bytes',10*1024**3));self.daily_keep=int(self.config.get('daily_keep',7));self.other_keep=int(self.config.get('other_keep',3))
        try:self.state=json.loads(self.state_path.read_text())
        except (OSError,ValueError):self.state={}
        self.error=self.state.get('last_error','')
        if self.state.get('state')=='creating':self.error='上次备份未完成，请重新备份。';self.state.update(state='error',last_error=self.error)
    def _save_state(self,**values):
        self.state={**self.state,**values};temporary=self.state_path.with_suffix('.tmp');temporary.write_text(json.dumps(self.state));temporary.replace(self.state_path)
    def status(self):
        return {**self.state,'folder':str(self.folder),'max_bytes':self.limit,'daily_keep':self.daily_keep,'other_keep':self.other_keep,'last_error':self.error}
    def configure(self,body):
        limit=body.get('max_bytes',self.limit);daily=body.get('daily_keep',self.daily_keep);other=body.get('other_keep',self.other_keep)
        if type(limit) is not int or not 100*1024**2<=limit<=2000*1024**3 or type(daily) is not int or not 1<=daily<=30 or type(other) is not int or not 1<=other<=10:raise ValueError('备份容量或保留份数无效')
        requested=body.get('folder',str(self.folder))
        if not isinstance(requested,str) or not requested.strip():raise ValueError('请选择备份目录')
        folder=Path(requested).expanduser().resolve()
        if folder not in (self.default.resolve(),self.folder.resolve()) and folder.name!='Stellar Secretary Backups':folder=folder/'Stellar Secretary Backups'
        root=self.archive.root.resolve()
        if folder==root or any(folder.is_relative_to(root/name) for name in ('files','uploads','open-files')):raise ValueError('备份目录不能放在原件或工作文件目录内')
        with self.lock:
            folder.mkdir(parents=True,exist_ok=True)
            probe=folder/('.write-test-'+uuid.uuid4().hex)
            try:probe.write_bytes(b'');probe.unlink()
            except OSError as error:raise ValueError('备份目录不可写') from error
            known=list(dict.fromkeys([*self.config.get('previous_folders',[]),str(self.folder)]))[-5:]
            value={'folder':str(folder),'max_bytes':limit,'daily_keep':daily,'other_keep':other,'previous_folders':known}
            temporary=self.config_path.with_suffix('.tmp');temporary.write_text(json.dumps(value));temporary.replace(self.config_path)
            self.config=value;self.folder=folder;self.limit=limit;self.daily_keep=daily;self.other_keep=other
            return self.status()
    def entries(self):
        result=[]
        folders=list(dict.fromkeys([str(self.folder),str(self.default),*self.config.get('previous_folders',[])]))
        for location in folders:
            folder=Path(location)
            try:paths=list(folder.glob('*.json'))
            except OSError:continue
            for path in paths:
                try:
                    value=json.loads(path.read_text());source=folder/(value['id']+'.zip')
                    if re.fullmatch('[a-f0-9]{32}',value['id']) and source.is_file():result.append({**value,'folder':str(folder)})
                except (OSError,ValueError,KeyError):pass
        return sorted(result,key=lambda value:value['created'],reverse=True)
    def _prune(self,keep):
        active=[value for value in self.entries() if Path(value['folder'])==self.folder]
        remove=set()
        for kind in ('daily','upgrade','manual','before-restore'):
            remove.update(value['id'] for value in [entry for entry in active if entry['reason']==kind][self.daily_keep if kind=='daily' else self.other_keep:])
        total=sum(value['size'] for value in active if value['id'] not in remove)
        for value in reversed(active):
            if total<=self.limit:break
            if value['id']==keep or value['id'] in remove:continue
            remove.add(value['id']);total-=value['size']
        for key in remove:
            try:(self.folder/(key+'.zip')).unlink(missing_ok=True);(self.folder/(key+'.json')).unlink(missing_ok=True)
            except OSError:continue  # An open Windows download may temporarily hold an old backup.
        used=sum(value['size'] for value in self.entries() if Path(value['folder'])==self.folder)
        self._save_state(used_bytes=used,warning='部分旧备份被占用，暂时超过容量上限；关闭相关文件后可再次备份。' if used>self.limit else '')
    def create(self,reason='manual'):
        with self.lock:
            self._save_state(state='creating',last_attempt=datetime.now(timezone.utc).isoformat(),reason=reason)
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
                if temporary.stat().st_size>self.limit:raise ValueError('单份备份超过容量上限，请提高备份容量；已有备份保留。')
                temporary.replace(target)
                value={'id':key,'created':datetime.now(timezone.utc).isoformat(),'reason':reason,'size':target.stat().st_size,'sha256':digest}
                meta=self.folder/(key+'.json');meta.write_text(json.dumps(value))
                self._prune(key)
                self._save_state(state='ready',last_success=value['created'],last_error='')
                self.error='';return value
            except Exception as error:
                temporary.unlink(missing_ok=True);self.error=str(error);self._save_state(state='error',last_error=self.error);raise
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
            source=Path(entry['folder'])/(key+'.zip')
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
                # Upgrade the staged database, never the user's live library, before replacement.
                from .core import Archive
                Archive(stage,recover=False)
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
