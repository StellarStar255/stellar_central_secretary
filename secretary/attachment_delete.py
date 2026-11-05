"""Remove one owned attachment while retaining the item and a local recovery copy."""
import io,json,re,sqlite3,zipfile
from datetime import datetime,timezone
from pathlib import Path
from . import additions,bundles
from .attachment_editor import atomic,digest,directory

STALE='附件已删除，以下为删除前摘要；请重新整理后再使用。'
WARNING='单个附件已删除，已有摘要可能过期；可手动重新整理。'
EMPTY='本批附件已删除。'

def stale(summary):
    if not summary or summary.startswith(STALE):return summary
    return (STALE+'\n'+summary)[:60000]

def remove_bundle(data,key,link_values):
    original,manifest=bundles.load(data)
    with original:
        manifest['links']=link_values
        before=bundles.assemble(manifest)
        removed=next((f for f in manifest['files'] if f['id']==key),None)
        if removed is None:raise KeyError('附件不存在或已删除')
        content=original.read(removed['path'])
        remaining=[file for file in manifest['files'] if file['id']!=key]
        contents={file['id']:original.read(file['path']) for file in remaining}
        # IDs remain stable; bundle paths use consecutive indices.
        for index,file in enumerate(remaining,1):file['path']=f'files/{index:02d}-'+file['name']
        manifest['files']=remaining
        if not remaining and not manifest['text'].strip() and not manifest.get('links'):manifest['text']=EMPTY
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as result:
            result.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            for file in remaining:result.writestr(file['path'],contents[file['id']])
        return output.getvalue(),before,bundles.assemble(manifest),removed,content

def remove(archive,item_id,batch_id,key,body):
    from .core import extract
    if body.get('confirmed') is not True:raise ValueError('请确认删除这个附件。')
    if any(value and not re.fullmatch('[a-f0-9]{32}',value) for value in (item_id,batch_id,key)):raise ValueError('附件编号无效')
    if batch_id and not key:raise ValueError('请选择要删除的附件。')
    with archive.lock:
        item=archive.get(item_id)
        if body.get('expected_updated')!=item['updated']:raise ValueError('资料已更新，请刷新后重新选择附件。')
        batch=additions.find(item,batch_id) if batch_id else None
        if batch_id and batch is None:raise KeyError('追加资料不存在')
        path=archive.root/'files'/(batch_id or item_id)
        if not path.is_file() or path.is_symlink():raise KeyError('附件原文件不存在')
        original=path.read_bytes()
        if key:
            if not batch_id and not bundles.is_bundle(item['filename']):raise KeyError('组合附件不存在')
            updated,before,after,file,content=remove_bundle(original,key,batch.get('links',[]) if batch else item['group_links'])
        else:
            if not item['filename'] or bundles.is_bundle(item['filename']):raise KeyError('请选择单个附件')
            file={'name':item['filename'],'id':'original'};content=original;updated=None;after=''
            try:before,_=extract(item['filename'],content)
            except Exception:before=''
        folder=directory(archive,item_id,batch_id,key)
        history=folder/'history'
        if history.is_symlink():raise ValueError('附件历史目录无效')
        import secrets
        recovery=history/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-deleted-'+secrets.token_hex(4))
        (recovery/'state').mkdir(mode=0o700,parents=True)
        backup_name=Path(file['name'].replace('\\','/')).name
        if not backup_name or backup_name in ('.','..'):raise ValueError('附件文件名无效')
        atomic(recovery/backup_name,content)
        atomic(recovery/'state/metadata.json',json.dumps({'kind':'attachment-deletion','item_id':item_id,'batch_id':batch_id,'attachment':file,'summary':batch['summary'] if batch else item['base_summary']},ensure_ascii=False).encode())
        now=datetime.now(timezone.utc).isoformat();replaced=False
        try:
            with archive.db() as db:
                if batch:
                    batches=item['additions'];current=next(value for value in batches if value['id']==batch_id)
                    summary=stale(current['summary'])
                    current.update(text=after[:200000],summary=summary,vision_text='',state='ready' if summary else 'saved',error=WARNING)
                    additions.records(batches)
                    db.execute('UPDATE items SET additions=?,error=?,updated=? WHERE id=?',(json.dumps(batches,ensure_ascii=False),WARNING,now,item_id))
                    text=item['text']
                else:
                    # Keep separately edited prose, replacing derived source text when present.
                    text=after if item['text']==before else item['text'].replace(before,after,1) if before and before in item['text'] else item['text']
                    summary=stale(item['base_summary'])
                    new_digest=digest(updated) if updated is not None else digest(('removed-original:'+item_id).encode())
                    db.execute('UPDATE items SET filename=?,digest=?,text=?,summary=?,vision_text=?,state=?,error=?,updated=? WHERE id=?',(item['filename'] if key else '',new_digest,text,summary,'','ready' if summary else 'saved',WARNING,now,item_id))
                archive._index(db,item_id,text)
                if updated is None:path.unlink()
                else:atomic(path,updated)
                replaced=True
        except BaseException as error:
            if replaced:atomic(path,original)
            if isinstance(error,sqlite3.IntegrityError):raise ValueError('删除后的资料与另一份归档冲突，原附件未删除。') from error
            raise
        return {'ok':True,'deleted_attachment':file['id'],'name':file['name'],'recovery_saved':True}
