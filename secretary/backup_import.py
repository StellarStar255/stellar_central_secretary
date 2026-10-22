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
            for field in ('title', 'text', 'url', 'filename', 'summary', 'category', 'error', 'state', 'created', 'updated'):
                if not isinstance(item.get(field, ''), str):
                    raise ValueError('备份中存在无效的资料字段')
            if len(item.get('text', '')) > 2_000_000:
                raise ValueError('备份单条正文超过 200 万字符')
            tags = item.get('tags', [])
            if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(t, str) for t in tags):
                raise ValueError('备份中的标签格式无效')
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
            prepared.append((item, content, digest))
        imported = skipped = 0
        created_files = []
        try:
            with archive.lock, archive.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for item, content, digest in prepared:
                    url = item.get('url', '')
                    if db.execute("SELECT 1 FROM items WHERE digest=? OR (url=? AND ?!='')", (digest, url, url)).fetchone():
                        skipped += 1
                        continue
                    item_id = uuid.uuid4().hex
                    filename, text, summary = item.get('filename', ''), item.get('text', ''), item.get('summary', '')
                    if content is not None:
                        path = archive.root/'files'/item_id
                        with path.open('xb') as f:
                            created_files.append(path)
                            f.write(content)
                    now = datetime.now(timezone.utc).isoformat()
                    state = item.get('state', 'pending')
                    if state not in ('ready', 'pending', 'error', 'needs_content'):
                        state = 'ready' if summary else ('pending' if text.strip() else 'needs_content')
                    db.execute('''INSERT INTO items(id,title,kind,url,filename,digest,text,summary,tags,category,state,error,created,updated)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                               (item_id, item.get('title') or filename or url or '未命名资料',
                                'file' if filename else ('link' if url else 'note'), url, filename, digest,
                                text, summary, json.dumps(item.get('tags', []), ensure_ascii=False),
                                item.get('category') or '未分类', state, item.get('error', ''),
                                item.get('created') or now, item.get('updated') or now))
                    archive._index(db, item_id, text)
                    imported += 1
        except BaseException:
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
    return {'imported': imported, 'skipped': skipped, 'total': len(prepared)}
