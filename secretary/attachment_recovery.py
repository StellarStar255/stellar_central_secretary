"""Restore one deleted leaf into the current archive, keeping later edits intact."""
import hashlib,json,re,shutil,tempfile,uuid,zipfile
from pathlib import Path
from datetime import datetime,timezone
from . import additions,bundles,pdf_reading
from .attachment_editor import atomic,digest
from .attachment_delete import EMPTY,STALE

WARNING='附件已恢复，已有摘要可能过期；可重新整理。'
def restored_summary(value):return (WARNING+'\n'+value.removeprefix(STALE+'\n'))[:60000] if value else ''

def entries(archive,item_id):
    archive.get(item_id);root=archive.root/'open-files'/item_id/'edits';result=[]
    if not root.exists():return result
    for path in root.glob('*/history/*-deleted-*/state/metadata.json'):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=archive.root and archive.root in parent.parents):continue
        try:
            value=json.loads(path.read_text());file=value['attachment'];folder=path.parent.parent
            if value.get('kind')!='attachment-deletion' or value.get('item_id')!=item_id or value.get('restored'):continue
            name=Path(file['name']).name
            if name!=file['name'] or name in ('','.','..') or not (folder/name).is_file():continue
            key=hashlib.sha256(str(path.relative_to(archive.root)).encode()).hexdigest()[:32]
            result.append({'id':key,'name':name,'batch_id':value.get('batch_id') or '','attachment_id':file['id'],'created':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),'_path':path,'_value':value})
        except (ValueError,KeyError,OSError):continue
    return sorted(result,key=lambda value:value['created'],reverse=True)

def public(archive,item_id):return [{key:value for key,value in entry.items() if not key.startswith('_')} for entry in entries(archive,item_id)]

def restore(archive,item_id,recovery_id):
    if not re.fullmatch('[a-f0-9]{32}',str(recovery_id)):raise ValueError('恢复编号无效')
    with archive.lock:
        entry=next((entry for entry in entries(archive,item_id) if entry['id']==recovery_id),None)
        if not entry:raise KeyError('已删附件不存在或已经恢复')
        item=archive.get(item_id);metadata=entry['_value'];file=dict(metadata['attachment']);batch_id=entry['batch_id'];key=entry['attachment_id']
        source=entry['_path'].parent.parent/file['name'];target=archive.root/'files'/(batch_id or item_id)
        batch=additions.find(item,batch_id) if batch_id else None
        if batch_id and not batch:raise ValueError('原追加批次已不存在，无法恢复到该位置')
        with tempfile.TemporaryDirectory(prefix='stellar-restore-attachment-') as temp:
            temp=Path(temp);previous=temp/'previous';existed=target.exists()
            if existed:shutil.copyfile(target,previous)
            if key=='original':
                if item['filename']:raise ValueError('当前原附件已存在，未覆盖。')
                updated=source;before='';after=item['text']
            else:
                if not batch_id and not bundles.is_bundle(item['filename']):raise ValueError('原组合档案已不存在')
                original,manifest=bundles.load(target)
                with original:
                    if any(value['id']==key for value in manifest['files']):raise ValueError('附件已经存在，未重复恢复')
                    if len(manifest['files'])>=20:raise ValueError('本批已有 20 个附件，请先移除其他附件')
                    if sum(value['size'] for value in manifest['files'])+source.stat().st_size>bundles.MAX_BYTES:raise ValueError('恢复后本批附件超过 2 GB')
                    before=bundles.assemble(manifest)
                    if manifest['text']==EMPTY:manifest['text']=''
                    file['path']=f'files/{len(manifest["files"])+1:02d}-'+file['name'];manifest['files'].append(file)
                    updated=temp/'restored.stellar.zip'
                    with zipfile.ZipFile(updated,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as output:
                        output.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
                        for value in manifest['files']:
                            if value['id']==key:output.write(source,value['path'],compress_type=zipfile.ZIP_STORED)
                            else:
                                with original.open(value['path']) as src,output.open(value['path'],'w',force_zip64=True) as dst:shutil.copyfileobj(src,dst,1024*1024)
                    after=bundles.assemble(manifest)
            replaced=False
            try:
                with archive.db() as db:
                    reads=item['pdf_reads'];selected=metadata.get('pdf_read')
                    if selected:reads[pdf_reading.key(batch_id,'' if key=='original' else key)]=selected
                    if batch:
                        batch.update(text=after[:200000],summary=restored_summary(batch['summary']),error=WARNING,state='ready' if batch['summary'] else 'saved');additions.records(item['additions'])
                        db.execute('UPDATE items SET additions=? WHERE id=?',(json.dumps(item['additions'],ensure_ascii=False),item_id))
                        text=item['text']
                    else:
                        text=item['text'] if key=='original' else after if item['text']==before else item['text'].replace(before,after,1) if before and before in item['text'] else item['text']
                        db.execute('UPDATE items SET filename=?,digest=?,text=?,summary=? WHERE id=?',(file['name'] if key=='original' else item['filename'],digest(updated),text,restored_summary(item['base_summary']),item_id))
                    db.execute('UPDATE items SET pdf_reads=?,error=?,updated=? WHERE id=?',(json.dumps(reads,ensure_ascii=False),WARNING,datetime.now(timezone.utc).isoformat(),item_id))
                    atomic(target,updated);replaced=True;archive._index(db,item_id,text)
            except BaseException:
                if replaced:
                    if existed:atomic(target,previous)
                    else:target.unlink(missing_ok=True)
                raise
        metadata['restored']=True
        try:atomic(entry['_path'],json.dumps(metadata,ensure_ascii=False).encode())
        except OSError:pass
        return {'ok':True,'name':file['name'],'restored_attachment':key}
