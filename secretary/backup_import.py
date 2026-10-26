"""Merge exported knowledge backups; never extract arbitrary ZIP paths."""
import hashlib
import io
import json
import re
import stat
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from .notes import image_bytes,MAX_IMAGE,MAX_IMAGES
from . import additions,bundles

MAX_BACKUP = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def import_backup(archive, data):
    if len(data) > MAX_BACKUP:
        raise ValueError('备份不能超过 256 MB')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError('请选择知识秘书导出的 ZIP 备份') from exc
    with z:
        infos = z.infolist()
        if len(infos) > 10002 or sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise ValueError('备份展开后过大或文件数量过多')
        names = set()
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in info.filename
                    or info.filename in names or stat.S_ISLNK(info.external_attr >> 16)
                    or info.flag_bits & 1):
                raise ValueError('备份包含无效路径、重复文件或不支持的文件类型')
            names.add(info.filename)
        if 'archive.json' not in names or z.getinfo('archive.json').file_size > 64 * 1024 * 1024:
            raise ValueError('备份缺少有效的 archive.json')
        try:
            records = json.loads(z.read('archive.json'))
        except (ValueError, UnicodeError) as exc:
            raise ValueError('备份资料清单无法读取') from exc
        if not isinstance(records, list) or len(records) > 10000:
            raise ValueError('备份资料清单格式无效')
        prepared = []
        for item in records:
            if not isinstance(item, dict) or not re.fullmatch(r'[a-f0-9]{32}', str(item.get('id', ''))):
                raise ValueError('备份中存在无效的资料编号')
            for field in ('title', 'text', 'url', 'filename', 'summary', 'category', 'error', 'state', 'created', 'updated','note','vision_text','user_context'):
                if not isinstance(item.get(field, ''), str):
                    raise ValueError('备份中存在无效的资料字段')
            if len(item.get('text', '')) > 2_000_000:
                raise ValueError('备份单条正文超过 200 万字符')
            if len(item.get('user_context',''))>20000:raise ValueError('链接说明不能超过 20000 个字符')
            tags = item.get('tags', [])
            if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(t, str) for t in tags):
                raise ValueError('备份中的标签格式无效')
            if item.get('tags_manual',0) not in (0,1):raise ValueError('备份中的标签格式无效')
            filename = item.get('filename', '')
            if filename and (PurePosixPath(filename).name != filename or '\\' in filename or filename in ('.', '..')):
                raise ValueError('备份中的原文件名无效')
            url = item.get('url', '')
            parsed = urlsplit(url)
            if url and (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password):
                raise ValueError('备份包含无效的资料链接')
            original = 'files/' + item['id'] if filename else None
            if original and (original not in names or z.getinfo(original).is_dir()):
                raise ValueError('备份缺少资料原文件，未导入任何内容')
            # Read every original before mutation so corrupt ZIP entries fail atomically.
            content = z.read(original) if original else None
            url, text = item.get('url', ''), item.get('text', '')
            digest = hashlib.sha256(content if content is not None else (url or text).encode()).hexdigest()
            if len(item.get('note',''))>20000:raise ValueError('速记文字不能超过 20000 个字符。')
            note_images=item.get('note_images',[])
            if not isinstance(note_images,list) or len(note_images)>MAX_IMAGES:raise ValueError('备份中的速记图片无效')
            attachments=[];seen_images=set()
            for image in note_images:
                if not isinstance(image,dict) or not re.fullmatch('[a-f0-9]{32}',str(image.get('id',''))) or image['id'] in seen_images or not isinstance(image.get('name'),str):raise ValueError('备份中的速记图片无效')
                seen_images.add(image['id']);name='files/'+image['id']
                if name not in names or z.getinfo(name).file_size>MAX_IMAGE:raise ValueError('备份缺少速记图片或图片过大')
                image_data=z.read(name);media=image_bytes(image_data)
                attachments.append((image['name'][:180],media,image_data))
            batches=additions.records(item.get('additions',[]));batch_files=[]
            for batch in batches:
                name='files/'+batch['id']
                if name not in names or z.getinfo(name).file_size>bundles.MAX_BYTES:raise ValueError('备份缺少追加资料或文件过大')
                raw=z.read(name);bundles.metadata(raw);batch_files.append(raw)
            if not isinstance(item.get('base_summary',item.get('summary','')),str):raise ValueError('备份摘要字段无效')
            prepared.append((item, content, digest,attachments,batches,batch_files))
        imported = skipped = 0
        created_files = []
        try:
            with archive.lock, archive.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for item, content, digest,attachments,batches,batch_files in prepared:
                    url = item.get('url', '')
                    if db.execute("SELECT 1 FROM items WHERE digest=? OR (url=? AND ?!='')", (digest, url, url)).fetchone():
                        skipped += 1
                        continue
                    item_id = uuid.uuid4().hex
                    filename, text, summary = item.get('filename', ''), item.get('text', ''), item.get('base_summary',item.get('summary', ''))
                    if content is not None:
                        path = archive.root/'files'/item_id
                        with path.open('xb') as f:
                            created_files.append(path)
                            f.write(content)
                    note_images=[]
                    for name,media,image_data in attachments:
                        image_id=uuid.uuid4().hex;path=archive.root/'files'/image_id
                        with path.open('xb') as stream:created_files.append(path);stream.write(image_data)
                        note_images.append({'id':image_id,'name':name,'media':media})
                    now = datetime.now(timezone.utc).isoformat()
                    for batch,raw in zip(batches,batch_files):
                        batch['id']=uuid.uuid4().hex;path=archive.root/'files'/batch['id']
                        with path.open('xb') as stream:created_files.append(path);stream.write(raw)
                        if batch['state']=='processing':batch.update(state='error',error='上次追加整理被中断，可重新生成补充摘要')
                    state = item.get('state', 'pending')
                    if state not in ('ready', 'pending', 'error', 'needs_content'):
                        state = 'ready' if summary else ('pending' if text.strip() else 'needs_content')
                    db.execute('''INSERT INTO items(id,title,kind,url,filename,digest,text,summary,tags,category,state,error,created,updated,tags_manual,note,note_images,note_version)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (item_id, item.get('title') or filename or url or '未命名资料',
                                'file' if filename else ('link' if url else 'note'), url, filename, digest,
                                text, summary, json.dumps(item.get('tags', []), ensure_ascii=False),
                                item.get('category') or '未分类', state, item.get('error', ''),
                                item.get('created') or now, item.get('updated') or now,int(item.get('tags_manual',0)),item.get('note',''),json.dumps(note_images,ensure_ascii=False),0))
                    db.execute('UPDATE items SET vision_text=?,user_context=? WHERE id=?',(item.get('vision_text','')[:60000],item.get('user_context','')[:20000],item_id))
                    db.execute('UPDATE items SET additions=? WHERE id=?',(json.dumps(batches,ensure_ascii=False),item_id))
                    archive._index(db, item_id, text)
                    imported += 1
        except BaseException:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
    return {'imported': imported, 'skipped': skipped, 'total': len(prepared)}
