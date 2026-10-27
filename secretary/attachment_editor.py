"""Managed local editing copies; explicit save-back updates the owned original and index."""
import base64,hashlib,io,json,os,re,secrets,sqlite3,subprocess,sys,zipfile
from datetime import datetime,timezone
from pathlib import Path
from . import additions,bundles

OPEN_EXTENSIONS={'.pdf','.txt','.md','.csv','.tsv','.xlsx','.xls','.docx','.doc','.pptx','.ppt','.odt','.ods','.odp','.rtf','.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.json','.yaml','.yml','.log'}
STALE='附件已修改，以下为修改前摘要；请重新整理后再使用。'
WARNING='文件修改已保存，已有摘要可能过期；可手动重新整理。'
def can_open(name):return Path(name).suffix.lower() in OPEN_EXTENSIONS
def digest(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
    temp=path.parent/(secrets.token_hex(16)+'.tmp')
    try:
        with os.fdopen(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as stream:stream.write(data)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)
def directory(archive,item_id,batch_id,key):
    if any(value and not re.fullmatch('[a-f0-9]{32}',value) for value in (item_id,batch_id,key)):raise ValueError('附件编号无效')
    target=archive.root/'open-files'/item_id/'edits'/(batch_id or 'original')/(key or 'file')
    current=archive.root
    for part in target.relative_to(archive.root).parts:
        current=current/part
        if current.is_symlink():raise ValueError('附件编辑目录无效')
    return target
def read(path):
    if path.is_symlink() or not path.is_file():raise ValueError('编辑文件不存在，请先打开附件并保存文件。')
    before=path.stat()
    if before.st_size>bundles.MAX_BYTES:raise ValueError('修改后的文件不能超过 50 MB')
    try:
        with path.open('rb') as stream:data=stream.read(bundles.MAX_BYTES+1)
    except PermissionError as error:raise ValueError('外部程序仍占用文件，请保存完成后重试；必要时关闭该文件。') from error
    after=path.stat()
    if len(data)>bundles.MAX_BYTES or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('文件仍在写入，请在外部程序保存完成后重试。')
    return data
def source(archive,item_id,batch_id='',key=''):
    item=archive.get(item_id);batch=additions.find(item,batch_id) if batch_id else None
    if batch_id and batch is None:raise KeyError('追加资料不存在')
    if batch_id and not key:raise ValueError('请选择本批附件')
    path=archive.root/'files'/(batch_id or item_id)
    if not path.is_file() or path.is_symlink():raise KeyError('附件原文件不存在')
    data=path.read_bytes()
    if key:
        if not batch_id and not bundles.is_bundle(item['filename']):raise ValueError('这份资料没有组合附件')
        file,content=bundles.attachment(data,key);name=file['name']
    else:
        name=item['filename'];content=data
        if not name or bundles.is_bundle(name):raise ValueError('请选择要打开的附件')
    if not can_open(name):raise ValueError('此文件类型请下载后自行选择查看程序。')
    name=Path(name.replace('\\','/')).name
    if not name or name in ('.','..'):raise ValueError('附件文件名无效')
    return item,batch,path,data,name,content
def has_copy(archive,item_id,batch_id='',key=''):
    try:return (directory(archive,item_id,batch_id,key)/'edit.json').is_file()
    except ValueError:return False
def local_copy(archive,item_id,batch_id='',key=''):
    item,batch,path,data,name,content=source(archive,item_id,batch_id,key)
    folder=directory(archive,item_id,batch_id,key);folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    working=folder/'content'
    if working.is_symlink():raise ValueError('附件编辑目录无效')
    working.mkdir(mode=0o700,exist_ok=True);target=working/name;meta_path=folder/'edit.json'
    if target.is_symlink() or meta_path.is_symlink():raise ValueError('附件编辑文件无效')
    if meta_path.exists():
        if meta_path.stat().st_size>4096:raise ValueError('附件编辑记录无效')
        meta=json.loads(meta_path.read_text(encoding='utf-8'))
        if meta.get('name')!=name or not re.fullmatch('[a-f0-9]{64}',str(meta.get('base_sha',''))):raise ValueError('附件编辑记录无效')
        # Reopening never discards edits made in the external application.
        if not target.exists():atomic(target,content);meta['base_sha']=digest(content);atomic(meta_path,json.dumps(meta).encode())
    else:
        if not target.exists():atomic(target,content)
        meta={'name':name,'base_sha':digest(content)};atomic(meta_path,json.dumps(meta,ensure_ascii=False).encode())
    return target,meta,digest(content)!=meta['base_sha']
def launch(path,reveal=False):
    path=str(path.resolve())
    if sys.platform=='darwin':subprocess.run(['/usr/bin/open',*(['-R'] if reveal else []),path],check=True,timeout=15)
    elif os.name=='nt':
        if reveal:subprocess.Popen(['explorer.exe','/select,'+path])
        else:os.startfile(path)
    else:subprocess.run(['xdg-open',str(Path(path).parent) if reveal else path],check=True,timeout=15)
def open_file(archive,item_id,batch_id='',key='',reveal=False):
    with archive.lock:target,meta,conflict=local_copy(archive,item_id,batch_id,key)
    launch(target,reveal)
    return {'ok':True,'conflict':conflict}

def replace_bundle(data,key,changed,link_values):
    original,manifest=bundles.load(data)
    with original:
        old=next((file for file in manifest['files'] if file['id']==key),None)
        if old is None:raise KeyError('组合附件不存在')
        if sum(file['size'] for file in manifest['files'])-old['size']+len(changed)>bundles.MAX_BYTES:raise ValueError('修改后本组附件总大小不能超过 50 MB')
        one,_=bundles.create('',[{'name':old['name'],'data':base64.b64encode(changed).decode()}])
        parsed,new=bundles.load(one)
        with parsed:replacement=dict(new['files'][0],id=old['id'],path=old['path'])
        if sum(file['media'].startswith('image/') for file in manifest['files'] if file['id']!=key)+replacement['media'].startswith('image/')>8:raise ValueError('每份组合资料最多包含 8 张图片')
        manifest['links']=link_values
        before=bundles.assemble(manifest)
        manifest['files']=[replacement if file['id']==key else file for file in manifest['files']]
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as result:
            result.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            for file in manifest['files']:result.writestr(file['path'],changed if file['id']==key else original.read(file['path']))
        if len(output.getbuffer())>bundles.MAX_BYTES:raise ValueError('修改后的组合归档超过 50 MB')
        return output.getvalue(),before,bundles.assemble(manifest),old['media'].startswith('image/') or replacement['media'].startswith('image/')

def save_file(archive,item_id,batch_id='',key=''):
    from .core import extract
    with archive.lock:
        item,batch,path,original,name,content=source(archive,item_id,batch_id,key)
        folder=directory(archive,item_id,batch_id,key);meta_path=folder/'edit.json'
        if not meta_path.is_file() or meta_path.is_symlink():raise ValueError('请先在默认程序中打开附件。')
        if meta_path.stat().st_size>4096:raise ValueError('附件编辑记录无效')
        meta=json.loads(meta_path.read_text(encoding='utf-8'))
        if meta.get('name')!=name:raise ValueError('附件编辑记录无效')
        if (folder/'content').is_symlink():raise ValueError('附件编辑目录无效')
        changed=read(folder/'content'/name)
        if digest(content)!=meta.get('base_sha'):raise ValueError('归档附件已被其他操作更新，未覆盖归档；本机编辑文件仍保留，可在文件夹中找回。')
        if changed==content:return {'ok':True,'changed':False}
        if key:
            updated,before,after,image=replace_bundle(original,key,changed,batch.get('links',[]) if batch else item['group_links'])
        else:
            updated=changed;image=Path(name).suffix.lower() in ('.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff')
            try:before,_=extract(name,content)
            except Exception:before=''
            try:after,warning=extract(name,changed)
            except Exception:after='';warning='文件修改已保存，但暂时无法提取正文。'
        if len(after)>2_000_000:raise ValueError('修改后可索引文字超过 200 万字符；原件未覆盖，本机修改文件仍保留。')
        # Preserve a directly openable previous version and its metadata locally.
        if (folder/'history').is_symlink():raise ValueError('附件历史目录无效')
        version=folder/'history'/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
        (version/'content').mkdir(mode=0o700,parents=True);atomic(version/'content'/name,content);atomic(version/'metadata.json',json.dumps({'item_id':item_id,'batch_id':batch_id,'attachment_id':key,'filename':name,'summary':batch['summary'] if batch else item['base_summary'],'vision_text':batch['vision_text'] if batch else item['vision_text']},ensure_ascii=False).encode())
        now=datetime.now(timezone.utc).isoformat();replaced=False
        try:
            with archive.db() as db:
                if batch:
                    batches=item['additions'];current=next(value for value in batches if value['id']==batch_id)
                    summary=current['summary']
                    if summary and not summary.startswith(STALE) and len(summary)+len(STALE)+1<=60000:summary=STALE+'\n'+summary
                    current.update(text=after[:200000],summary=summary,state='ready' if summary else 'saved',error=WARNING)
                    if image:current['vision_text']=''
                    additions.records(batches)
                    db.execute('UPDATE items SET additions=?,updated=? WHERE id=?',(json.dumps(batches,ensure_ascii=False),now,item_id))
                    text=item['text']
                else:
                    text=after if not item['text'] or item['text']==before else item['text'].replace(before,after,1) if before in item['text'] else item['text']+'\n\n【更新后的附件正文】\n'+after
                    if len(text)>2_000_000:raise ValueError('修改后可索引文字超过 200 万字符；原件未覆盖，本机修改文件仍保留。')
                    summary=item['base_summary'];summary=(STALE+'\n'+summary) if summary and not summary.startswith(STALE) else summary
                    db.execute('UPDATE items SET digest=?,text=?,summary=?,vision_text=?,state=?,error=?,updated=? WHERE id=?',(digest(updated),text,summary,'' if image else item['vision_text'],'ready' if summary else 'saved',WARNING,now,item_id))
                archive._index(db,item_id,text)
                atomic(path,updated);replaced=True
        except BaseException as error:
            if replaced:atomic(path,original)
            if isinstance(error,sqlite3.IntegrityError) and 'items.digest' in str(error):raise ValueError('修改后的文件已存在于另一份归档，未覆盖当前原件；本机编辑文件已保留。') from error
            raise
        meta['base_sha']=digest(changed);atomic(meta_path,json.dumps(meta,ensure_ascii=False).encode())
        return {'ok':True,'changed':True}
