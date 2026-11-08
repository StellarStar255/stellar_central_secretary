"""Read-only accounting and explicit, expiring cleanup plans for managed files."""
import hashlib,json,os,re,shutil,threading,time,uuid
from pathlib import Path

KINDS=('originals','backups','deleted_attachments','uploads','working_files','video_cache','database','other')
def files(root):
    if root.is_symlink():return []
    if root.is_file():return [] if root.is_symlink() else [root]
    result=[]
    for directory,folders,names in os.walk(root,followlinks=False):
        folders[:]=[name for name in folders if not (Path(directory)/name).is_symlink()]
        for name in names:
            path=Path(directory)/name
            if not path.is_symlink() and path.is_file():result.append(path)
    return result

def fingerprint(paths):
    values=[]
    for path in paths:
        if path.is_symlink():raise ValueError('文件已变化，请重新预览清理内容')
        stat=path.stat();values.append((str(path),stat.st_size,stat.st_mtime_ns,stat.st_ino))
    return hashlib.sha256(json.dumps(sorted(values)).encode()).hexdigest()

class Storage:
    def __init__(self,service):self.service=service;self.lock=threading.RLock();self.plans={}
    def folders(self):return list(dict.fromkeys([self.service.backups.folder,self.service.backups.default,*map(Path,self.service.backups.config.get('previous_folders',[]))]))
    def overview(self):
        root=self.service.archive.root;totals={key:{'bytes':0,'files':0} for key in KINDS};backup_folders=self.folders()
        locations=list(dict.fromkeys([root,*[folder for folder in backup_folders if not folder.is_relative_to(root)]]))
        for location in locations:
            for path in files(location):
                try:
                    relative=path.relative_to(root) if path.is_relative_to(root) else None
                    if any(path.is_relative_to(folder) for folder in backup_folders):kind='backups'
                    elif relative and relative.parts[0]=='files':kind='originals'
                    elif relative and relative.parts[0]=='uploads':kind='uploads'
                    elif relative and relative.parts[0]=='open-files':kind='deleted_attachments' if any('-deleted-' in part for part in relative.parts) else 'working_files'
                    elif relative and relative.parts[0]=='video-cache':kind='video_cache'
                    elif relative and relative.name.startswith('archive.sqlite3'):kind='database'
                    else:kind='other'
                    totals[kind]['bytes']+=path.stat().st_size;totals[kind]['files']+=1
                except OSError:continue
        return {'groups':totals,'total_bytes':sum(value['bytes'] for value in totals.values()),'scanned_at':time.time()}
    def candidates(self):
        service=self.service;root=service.archive.root;result=[]
        def add(kind,name,paths,directory=None):
            if len(result)>=500 or not paths:return
            try:
                base=root if paths[0].is_relative_to(root) else next((folder for folder in self.folders() if paths[0].is_relative_to(folder)),None)
                if base is None or any(path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent==base or base in parent.parents) for path in paths):return
                result.append({'id':uuid.uuid4().hex,'kind':kind,'name':name,'bytes':sum(path.stat().st_size for path in paths),'files':len(paths),'paths':paths,'directory':directory,'fingerprint':fingerprint(paths)})
            except OSError:return
        for meta in service.uploads.folder.glob('*.json'):
            try:
                value=json.loads(meta.read_text())
                if re.fullmatch('[a-f0-9]{32}',meta.stem) and time.time()-value.get('updated',meta.stat().st_mtime)>86400:add('uploads',str(value.get('name',''))[:300],[meta,service.uploads.path(meta.stem)])
            except (OSError,ValueError,TypeError):continue
        for meta in (root/'open-files').glob('*/edits/*/history/*-deleted-*/state/metadata.json'):
            try:
                value=json.loads(meta.read_text());directory=meta.parent.parent
                if value.get('kind')=='attachment-deletion' and re.fullmatch('[a-f0-9]{32}',str(value.get('item_id',''))):add('deleted_attachments',str(value['attachment']['name'])[:300],files(directory),directory)
            except (OSError,ValueError,KeyError):continue
        entries=service.backups.entries();protected=set()
        for folder in self.folders():
            values=[entry for entry in entries if Path(entry['folder'])==folder]
            if values:protected.add(values[0]['id'])
            verified=next((entry for entry in values if entry.get('verification',{}).get('state')=='verified'),None)
            if verified:protected.add(verified['id'])
        for entry in entries:
            if entry['id'] not in protected:
                folder=Path(entry['folder']);add('backups',entry['created'],[folder/(entry['id']+'.zip'),folder/(entry['id']+'.json')])
        return result
    def preview(self):
        with self.lock:
            self.plans={key:value for key,value in self.plans.items() if time.time()-value['created']<600}
            while len(self.plans)>=8:self.plans.pop(next(iter(self.plans)))
            token=uuid.uuid4().hex;items=self.candidates();self.plans[token]={'created':time.time(),'items':{item['id']:item for item in items}}
            return {'token':token,'expires_in':600,'items':[{key:value for key,value in item.items() if key not in ('paths','directory','fingerprint')} for item in items],'overview':self.overview()}
    def clean(self,body):
        ids=body.get('ids');token=body.get('token')
        if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token) or body.get('confirmed') is not True or not isinstance(ids,list) or not ids or len(ids)>500 or len(set(map(str,ids)))!=len(ids):raise ValueError('请选择并确认具体清理项目')
        with self.lock,self.service.lock,self.service.backups.lock,self.service.uploads.lock,self.service.archive.lock:
            if self.service.busy or self.service.captures or self.service.questions:raise ValueError('请等待当前任务结束后清理')
            plan=self.plans.get(token)
            if not plan or time.time()-plan['created']>=600 or any(not isinstance(key,str) or key not in plan['items'] for key in ids):raise ValueError('清理预览已失效，请重新预览')
            chosen=[plan['items'][key] for key in ids]
            # Recompute eligibility as well as file identity before deleting anything.
            eligible={item['fingerprint'] for item in self.candidates()}
            for item in chosen:
                if item['fingerprint'] not in eligible or fingerprint(files(item['directory']) if item['directory'] else item['paths'])!=item['fingerprint']:raise ValueError('文件已变化，请重新预览清理内容')
            del self.plans[token];removed=[];failed=[]
            for item in chosen:
                try:
                    if item['directory']:shutil.rmtree(item['directory'])
                    else:
                        # Remove backup/upload payload before metadata so a failed unlink keeps its record.
                        for path in sorted(item['paths'],key=lambda path:path.suffix=='.json'):path.unlink()
                    removed.append(item['id'])
                except OSError:failed.append(item['name'])
            return {'removed':removed,'failed':failed,'overview':self.overview()}
