"""Disk-streamed local snapshots, bounded retention, and transactional local recovery."""
import hashlib,json,logging,re,shutil,sqlite3,threading,uuid,zipfile
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
from . import backup_identity, backup_index, backup_workspace, paths, restore_transaction

class Backups:
    def __init__(self,archive):
        self.archive=archive;self.default=archive.root/'local-backups';self.default.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.stop=threading.Event();self.config_path=archive.root/'backup-settings.json';self.state_path=archive.root/'backup-status.json'
        try:self.config=json.loads(self.config_path.read_text())
        except (OSError,ValueError):self.config={}
        self.binding=backup_identity.binding(archive.root)
        self.library_id=self.config.get('library_id') if self.config.get('library_binding')==self.binding else None
        if not isinstance(self.library_id,str) or not re.fullmatch('[0-9a-f]{32}',self.library_id):
            self.library_id=None
        self.folder=Path(self.config.get('folder',str(self.default)));self.limit=int(self.config.get('max_bytes',10*1024**3));self.daily_keep=int(self.config.get('daily_keep',7));self.other_keep=int(self.config.get('other_keep',3))
        try:self.state=json.loads(self.state_path.read_text())
        except (OSError,ValueError):self.state={}
        if self.library_id is None or self.state.get('library_id')!=self.library_id:
            self.state={}
        self.error=self.state.get('last_error','')
        if self.state.get('state')=='creating':self.error='上次备份未完成，请重新备份。';self.state.update(state='error',last_error=self.error)
    def _save_config(self,value):
        value['library_id']=self.library_id or uuid.uuid4().hex
        value['library_binding']=self.binding
        backup_identity.write(self.config_path,value)
        self.config=value
        self.library_id=value['library_id']

    def _save_state(self,**values):
        if 'state' in values:
            values['state_folder']=str(self.folder)
        self.state={**self.state,**values,'library_id':self.library_id,'revision':self.state.get('revision',0)+1};temporary=self.state_path.with_suffix('.tmp');temporary.write_text(json.dumps(self.state));temporary.replace(self.state_path)
    def status(self):
        folder,config,state=self.folder,self.config,self.state
        entries=self._entries(folder)
        try:available=folder.is_dir()
        except OSError:available=False
        owned=[entry for entry in entries if self.owns(entry)]
        verified=[entry for entry in owned if entry.get('verification',{}).get('state')=='verified']
        verification=max((entry['verification'] for entry in owned if entry.get('verification')),
                         key=lambda check:check.get('checked_at',''),default=None)
        live=state.get('last_verification') or {}
        if live.get('state')=='checking' and live.get('folder')==str(folder):
            verification=live
        current=state.get('state_folder',str(self.default))==str(folder)
        temporary_size=backup_workspace.temporary_bytes(folder)
        return {'library_id':self.library_id,'folder':str(folder),'folder_available':available,'max_bytes':self.limit,'daily_keep':self.daily_keep,'other_keep':self.other_keep,
                'state':state.get('state','ready') if current else 'ready',
                'last_error':self.error if current else '',
                'daily_retry':state.get('daily_retry') if (state.get('daily_retry') or {}).get('folder')==str(folder) else None,
                'last_attempt':state.get('last_attempt') if current else None,
                'warning':state.get('warning','') if current else '',
                'owned_bytes':sum(entry['size'] for entry in owned),'temporary_bytes':temporary_size,'used_bytes':temporary_size+sum(entry['size'] for entry in entries),'snapshot_count':sum(e.get('index_issue')!='missing_zip' for e in entries),
                'index_issue_count':sum('index_issue' in e for e in entries),
                'last_success':max((entry['created'] for entry in verified),default=None),
                'last_verification':verification,
                'config_revision':config.get('revision',0),'state_revision':state.get('revision',0)}
    def configure(self,body):
        limit=body.get('max_bytes',self.limit);daily=body.get('daily_keep',self.daily_keep);other=body.get('other_keep',self.other_keep)
        if type(limit) is not int or not 100*1024**2<=limit<=2000*1024**3 or type(daily) is not int or not 1<=daily<=30 or type(other) is not int or not 1<=other<=10:raise ValueError('备份容量或保留份数无效')
        requested=body.get('folder',str(self.folder))
        if not isinstance(requested,str) or not requested.strip():raise ValueError('请选择备份目录')
        selected=Path(requested.strip()).expanduser()
        if not selected.is_absolute():raise ValueError('请输入备份目录的完整路径。')
        folder=selected.resolve()
        if sys.platform == 'darwin':
            volumes = Path('/Volumes')
            if folder.is_relative_to(volumes) and folder != volumes:
                volume = volumes/folder.relative_to(volumes).parts[0]
                if not volume.is_dir():raise ValueError('备份目录所在位置不可用，请检查硬盘连接。')
        if folder not in (self.default.resolve(),self.folder.resolve()) and folder.name!='Stellar Secretary Backups':folder=(folder/'Stellar Secretary Backups').resolve()
        if paths.inside_program(folder):raise ValueError('备份目录不能位于程序安装目录中。')
        root=self.archive.root.resolve()
        if folder==root or any(folder.is_relative_to(root/name) for name in ('files','uploads','open-files')):raise ValueError('备份目录不能放在原件或工作文件目录内')
        with self.lock:
            probe=folder/('.write-test-'+uuid.uuid4().hex)
            try:folder.mkdir(parents=True,exist_ok=True);probe.write_bytes(b'');probe.unlink()
            except OSError as error:raise ValueError('备份目录不可写') from error
            known=list(dict.fromkeys([*self.config.get('previous_folders',[]),str(self.folder)]))[-5:]
            value={'revision':self.config.get('revision',0)+1,'folder':str(folder),'max_bytes':limit,'daily_keep':daily,'other_keep':other,'previous_folders':known}
            self._save_config(value)
            self.folder=folder;self.limit=limit;self.daily_keep=daily;self.other_keep=other
            return self.status()
    def entries(self):
        folders=list(dict.fromkeys([str(self.folder),str(self.default),*self.config.get('previous_folders',[])]))
        result=[entry for location in folders for entry in self._entries(Path(location))]
        return sorted(result,key=lambda value:value['created'],reverse=True)
    def owns(self,entry):
        return self.library_id is not None and entry.get('library_id')==self.library_id

    _entries = staticmethod(backup_index.entries)

    def _repair_index(self, entry):
        from . import backup_verification
        if entry['index_issue'] in ('unreadable_index', 'missing_zip'):
            raise ValueError('无法读取备份索引或找不到对应的 ZIP 文件。')
        source=Path(entry['folder'])/(entry['id']+'.zip')
        expected=entry.get('sha256')
        with self.archive.db() as db:
            schema=db.execute('PRAGMA user_version').fetchone()[0]
        check=backup_verification.verify(source,expected,schema)
        digest=check.pop('sha256')
        snapshot=check.pop('snapshot',None)
        checked=datetime.now(timezone.utc).isoformat()
        value={k:v for k,v in entry.items() if k not in ('folder','index_issue')}
        value.pop('library_id',None)
        if (isinstance(snapshot,dict) and snapshot.get('id')==entry['id']
                and snapshot.get('reason') in backup_index.REASONS and backup_index.valid_date(snapshot.get('created'))):
            owner=snapshot.get('library_id')
            if isinstance(owner,str) and re.fullmatch('[0-9a-f]{32}',owner):
                value['library_id']=owner
            value.update(created=snapshot['created'],reason=snapshot['reason'])
        value.update(sha256=digest,verification={**check,'id':entry['id'],'checked_at':checked})
        backup_index.save(source.with_suffix('.json'),value)
        return value

    def repair_indexes(self):
        for candidate in self.entries():
            if self.stop.is_set():
                return
            if candidate.get('index_issue') in ('missing_index','invalid_index'):
                with self.lock:
                    folder=Path(candidate['folder'])
                    entry=backup_index.read_entry(folder,candidate['id'])
                    if entry and entry.get('index_issue'):
                        try:
                            self._repair_index(entry)
                        except Exception as error:
                            # Leave the original files intact and continue checking other snapshots.
                            logging.getLogger(__name__).warning('Backup index %s: %s',entry['id'],error)

    def restore_protected(self):
        return set(self.state.get('restore_protected', []))

    def _prune(self,keep):
        protected=self.restore_protected() | {keep}
        active=[value for value in self.entries() if Path(value['folder'])==self.folder and self.owns(value)]
        remove=set()
        for kind in ('daily','upgrade','manual','before-restore'):
            remove.update(value['id'] for value in [entry for entry in active if not entry.get('index_issue') and entry['reason']==kind][self.daily_keep if kind=='daily' else self.other_keep:])
        remove.difference_update(protected)
        total=sum(value['size'] for value in active if value['id'] not in remove)
        for value in reversed(active):
            if total<=self.limit:break
            if value.get('index_issue') or value['id'] in protected or value['id'] in remove:continue
            remove.add(value['id']);total-=value['size']
        for key in remove:
            try:(self.folder/(key+'.zip')).unlink(missing_ok=True);(self.folder/(key+'.json')).unlink(missing_ok=True)
            except OSError:continue  # An open Windows download may temporarily hold an old backup.
        used=sum(value['size'] for value in self.entries() if Path(value['folder'])==self.folder and self.owns(value))
        if used>self.limit and self.restore_protected():
            self._save_state(warning='为保留恢复所需的备份，暂时超过容量上限。')
            return
        self._save_state(warning='部分旧备份被占用，暂时超过容量上限；关闭相关文件后可再次备份。' if used>self.limit else '')
    def _limit_failed_snapshots(self, newest):
        # Rotate diagnostics across automatic, manual and pre-upgrade attempts.
        entries=[entry for entry in self._entries(self.folder) if self.owns(entry)]
        current=next((entry for entry in entries if entry['id']==newest),None)
        if not current or current.get('verification',{}).get('state')!='failed':
            return
        used=sum(entry['size'] for entry in entries)
        for entry in entries:
            if entry['id']==newest or entry.get('verification',{}).get('state')!='failed':
                continue
            payload=self.folder/(entry['id']+'.zip')
            try:
                payload.unlink()
                used-=entry['size']
                payload.with_suffix('.json').unlink()
            except OSError:
                continue  # A later attempt retries files locked by another process.
        if used>self.limit:
            payload=self.folder/(newest+'.zip')
            payload.unlink()
            payload.with_suffix('.json').unlink()

    def create(self,reason='manual',*,expected_folder=None,restore_source=None,transaction=None):
        with self.lock:
            if expected_folder is not None and expected_folder!=str(self.folder):
                raise ValueError('备份目录已更改，请刷新设置后重试。')
            if self.library_id is None:
                self._save_config(dict(self.config))
            key=uuid.uuid4().hex;target=self.folder/(key+'.zip')
            previous=self.restore_protected()
            protection={'restore_protected':sorted(previous | {restore_source,key}),
                        'restore_transaction':transaction} if restore_source else {}
            self._save_state(state='creating',last_attempt=datetime.now(timezone.utc).isoformat(),reason=reason,**protection)
            snapshot_info={'library_id':self.library_id,'id':key,'reason':reason,'created':datetime.now(timezone.utc).isoformat()}
            try:
                if not self.folder.is_dir():raise ValueError('备份目录所在位置不可用，请检查硬盘连接。')
                with backup_workspace.workspace(self.folder,self.archive.root) as work:
                    temporary=work/backup_workspace.PART
                    snapshot=work/backup_workspace.DATABASE
                    with self.archive.lock:
                        with closing(sqlite3.connect(snapshot)) as dst,self.archive.db() as src:src.backup(dst)
                        with closing(sqlite3.connect(snapshot)) as db:record_count=db.execute('SELECT count(*) FROM items').fetchone()[0]
                        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as output:
                            manifest={}
                            def write_file(path,name):
                                hasher=hashlib.sha256();size=0
                                with path.open('rb') as src,output.open(name,'w',force_zip64=True) as dst:
                                    while chunk:=src.read(1024*1024):hasher.update(chunk);size+=len(chunk);dst.write(chunk)
                                manifest[name]={'sha256':hasher.hexdigest(),'size':size}
                            def write_bytes(name,value):
                                raw=value.encode();output.writestr(name,raw);manifest[name]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
                            write_file(snapshot,'archive.sqlite3');write_bytes('archive.json',json.dumps(self.archive.export(),ensure_ascii=False))
                            for source in (self.archive.root/'files').iterdir():
                                if source.is_file():write_file(source,'files/'+source.name)
                            chats=self.archive.root/'conversations.json'
                            if chats.exists():write_file(chats,'conversations.json')
                            output.writestr('manifest.json',json.dumps({'version':1,'records':record_count,'files':manifest,'snapshot':snapshot_info}))
                    snapshot.unlink()
                    with temporary.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                    if temporary.stat().st_size>self.limit:raise ValueError('单份备份超过容量上限，请提高备份容量；已有备份保留。')
                    temporary.replace(target)
                value={**snapshot_info,'size':target.stat().st_size,'sha256':digest}
                meta=self.folder/(key+'.json')
                backup_index.save(meta,value)
                try:
                    value=self.verify(key,allow_source_mismatch=reason=='before-restore')
                except Exception:
                    self._limit_failed_snapshots(key)
                    raise
                if restore_source:
                    self._save_state(restore_protected=[restore_source,key])
                if value['verification']['state']!='verified':
                    self._save_state(state='ready',warning='恢复前现场副本已保留，但原件与索引不一致；该副本未标记为验证通过。')
                    return value
                if not restore_source:
                    self._prune(key)
                self._save_state(state='ready',last_error='',daily_retry=None)
                self.error='';return {**value,'folder':str(self.folder)}
            except Exception as error:
                if restore_source:
                    self._save_state(restore_protected=sorted(previous | {restore_source}))
                self.error=str(error);self._save_state(state='error',last_error=self.error);raise
    def _find_entry(self,key):
        matches=[entry for entry in self.entries() if entry['id']==key]
        if not matches:
            raise ValueError('本机备份不存在')
        # The same snapshot can also exist in a previously configured folder.
        return next((entry for entry in matches if not entry.get('index_issue')),matches[0])

    def verify(self,key,allow_source_mismatch=False):
        from . import backup_verification
        with self.lock:
            entry=self._find_entry(key)
            if entry.get('index_issue'):
                return self._repair_index(entry)
            meta=Path(entry['folder'])/(key+'.json');checked=datetime.now(timezone.utc).isoformat()
            def save(value):
                entry['verification']=value
                encoded={name:value for name,value in entry.items() if name!='folder'}
                backup_index.save(meta,encoded)
                self._save_state(last_verification=value)
            self._save_state(last_verification={'state':'checking','id':key,'checked_at':checked,'folder':entry['folder']})
            try:
                with self.archive.db() as db:max_schema=db.execute('PRAGMA user_version').fetchone()[0]
                result=backup_verification.verify(Path(entry['folder'])/(key+'.zip'),entry['sha256'],max_schema,allow_source_mismatch)
                result.pop('sha256',None)
                result.pop('snapshot',None)
                value={**result,'id':key,'checked_at':datetime.now(timezone.utc).isoformat()};save(value)
                return {name:value for name,value in entry.items() if name!='folder'}
            except Exception as error:
                save({'state':'failed','id':key,'checked_at':datetime.now(timezone.utc).isoformat(),'error':str(error)[:1000]});raise
    def due(self):
        with self.lock:
            if self.stop.is_set():return
            now=datetime.now(timezone.utc)
            retry=self.state.get('daily_retry') or {}
            if retry.get('folder')!=str(self.folder):
                retry={}
            if retry and now.isoformat()<retry['next_attempt']:
                return
            if any(self.owns(value) and value['reason']=='daily' and value.get('verification',{}).get('state')=='verified'
                   and value['created'][:10]==now.date().isoformat() for value in self._entries(self.folder)):
                return
            try:
                self.create('daily')
            except Exception as error:
                count=retry.get('attempts',0)+1
                delay=timedelta(hours=min(24,2**min(count,5)))
                self._save_state(daily_retry={'folder':str(self.folder),'attempts':count,
                                              'next_attempt':(now+delay).isoformat(),'error':str(error)})
                raise
    def _finish_restore_retention(self):
        protected=self.state.get('restore_protected',[])
        self._save_state(restore_protected=[],restore_transaction=None)
        if len(protected)!=2 or self.state.get('state_folder')!=str(self.folder):
            return
        # Once the restore has committed, missing files must not keep it pending.
        owned=[entry for entry in self.entries()
               if entry['folder']==str(self.folder) and self.owns(entry)]
        rollback=next((entry for entry in owned if entry['id']==protected[1]),None)
        if rollback is None or rollback.get('index_issue')=='missing_zip':
            rollback=next((entry for entry in owned
                           if entry.get('verification',{}).get('state')=='verified'),None)
        if rollback and rollback.get('verification',{}).get('state')=='verified':
            self._prune(rollback['id'])

    def start(self):
        def loop():
            for folder in {self.folder,self.default,*map(Path,self.config.get('previous_folders',[]))}:
                backup_workspace.recover(folder,self.archive.root)
            self.repair_indexes()
            with self.lock:
                transaction=self.state.get('restore_transaction')
                if transaction:
                    with self.archive.db() as db:
                        committed=db.execute('SELECT value FROM settings WHERE key=?',
                                             (restore_transaction.COMMIT_KEY,)).fetchone()
                    if committed and committed[0]==transaction:
                        try:self._finish_restore_retention()
                        except (ValueError,OSError):
                            logging.getLogger(__name__).warning('Post-restore backup cleanup deferred',exc_info=True)
            while not self.stop.is_set():
                try:self.due()
                except Exception as error:self.error=str(error)
                self.stop.wait(3600)
        self.worker=threading.Thread(target=loop,name='local-backups',daemon=True)
        self.worker.start()
    def close(self):
        self.stop.set()
        if getattr(self,'worker',None):self.worker.join()
    def restore(self,key):
        with self.lock,self.archive.lock:
            entry=self._find_entry(key)
            checked=self.verify(key)
            source=Path(entry['folder'])/(key+'.zip')
            with source.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=checked['sha256']:raise ValueError('备份校验失败，未修改当前资料')
            with restore_transaction.workspace(self.archive.root,self._save_state) as (stage,transaction):
                incoming=stage/'files';incoming.mkdir()
                with zipfile.ZipFile(source) as archive:
                    for info in archive.infolist():
                        name=info.filename
                        if name not in ('archive.sqlite3','archive.json','conversations.json','manifest.json') and not re.fullmatch(r'files/[a-f0-9]{32}',name):raise ValueError('备份包含无效文件')
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
                self.create('before-restore',restore_source=key,transaction=transaction)
                restore_transaction.install(self.archive.root,stage,transaction)
                try:self._finish_restore_retention()
                except (ValueError,OSError):
                    logging.getLogger(__name__).warning('Post-restore backup cleanup deferred',exc_info=True)
            return {'ok':True,'restored':key}
