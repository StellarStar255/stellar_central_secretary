"""Verify a snapshot on disk without replacing or opening the live library."""
import hashlib,json,re,sqlite3,tempfile,zipfile
from contextlib import closing
from pathlib import Path
from .chat_cleanup import validate_chat_history, clean_chats

def verify(source,expected_sha,max_schema,allow_source_mismatch=False):
    with source.open('rb') as stream:
        digest_sum=hashlib.file_digest(stream,'sha256').hexdigest()
        if expected_sha is not None and digest_sum!=expected_sha:raise ValueError('备份 SHA256 校验失败，当前资料未修改')
    with tempfile.TemporaryDirectory(prefix='stellar-backup-check-') as temp,zipfile.ZipFile(source) as archive:
        entries=archive.infolist();names={entry.filename for entry in entries}
        if len(names)!=len(entries) or len(names)>200000 or not {'archive.sqlite3','archive.json'}<=names:raise ValueError('备份文件清单无效')
        if any(name not in ('archive.sqlite3','archive.json','conversations.json','manifest.json') and not re.fullmatch(r'files/[a-f0-9]{32}',name) for name in names):raise ValueError('备份包含无效文件')
        manifest=None
        if 'manifest.json' in names:
            if archive.getinfo('manifest.json').file_size>32*1024**2:raise ValueError('备份清单过大')
            manifest=json.loads(archive.read('manifest.json'));values=manifest.get('files')
            if manifest.get('version')!=1 or not isinstance(values,dict) or set(values)!=names-{'manifest.json'}:raise ValueError('备份文件清单不完整')
            if any(not isinstance(value,dict) or type(value.get('size')) is not int or value['size']<0 or not re.fullmatch('[a-f0-9]{64}',str(value.get('sha256',''))) for value in values.values()):raise ValueError('备份文件清单无效')
        if manifest is None and expected_sha is None:
            raise ValueError('缺少备份校验值和逐文件清单，无法重建索引。')
        database=Path(temp)/'archive.sqlite3';actual={}
        for entry in entries:
            hasher=hashlib.sha256();size=0;output=database.open('wb') if entry.filename=='archive.sqlite3' else None
            try:
                with archive.open(entry) as stream:
                    while chunk:=stream.read(1024*1024):
                        hasher.update(chunk);size+=len(chunk)
                        if output:output.write(chunk)
            finally:
                if output:output.close()
            value={'sha256':hasher.hexdigest(),'size':size};actual[entry.filename]=value
            if manifest and entry.filename!='manifest.json' and value!=manifest['files'][entry.filename]:raise ValueError('备份文件校验失败：'+entry.filename)
        with closing(sqlite3.connect(database)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库校验失败')
            if db.execute('PRAGMA user_version').fetchone()[0]>max_schema:raise ValueError('备份来自更新版本，请先更新程序')
            columns={row[1] for row in db.execute('PRAGMA table_info(items)')}
            if not {'id','filename','digest'}<=columns:raise ValueError('备份数据库缺少必要字段')
            optional=','.join(name if name in columns else "'[]' AS "+name for name in ('note_images','additions'))
            records=0;refs=set();anomalies=[]
            if 'conversations.json' in names:
                try:
                    if archive.getinfo('conversations.json').file_size > 8_000_000:
                        raise ValueError('对话记录超过 8 MB')
                    history=json.loads(archive.read('conversations.json').decode('utf-8'))
                    validate_chat_history(history)
                    # Exercise the same deletion cleanup that runs when opening history.
                    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    deleted=db.execute('SELECT id FROM deleted_items') if 'deleted_items' in tables else ()
                    messages=db.execute('SELECT chat_id,message_id FROM deleted_messages') if 'deleted_messages' in tables else ()
                    chats,_=clean_chats(history['conversations'],(row[0] for row in deleted),messages)
                    active=history.get('activeId','')
                    cleaned={'conversations':chats,'activeId':active if any(chat['id']==active for chat in chats) else ''}
                    if len(json.dumps(cleaned,ensure_ascii=False).encode())>8_000_000:
                        raise ValueError('对话记录超过 8 MB')
                except (ValueError,KeyError,TypeError,AttributeError,RecursionError) as error:
                    message='备份中的对话记录无法读取'
                    if not allow_source_mismatch:
                        raise ValueError(message) from error
                    anomalies.append(message)
            for ident,filename,digest,images,batches in db.execute('SELECT id,filename,digest,'+optional+' FROM items'):
                records+=1
                if not re.fullmatch('[a-f0-9]{32}',str(ident)):raise ValueError('备份资料编号无效')
                if filename:
                    name='files/'+ident;refs.add(name)
                    if name not in actual:
                        if not allow_source_mismatch:raise ValueError('备份缺少原件：'+filename)
                        anomalies.append('缺少原件：'+filename)
                    elif actual[name]['sha256']!=digest:
                        if not allow_source_mismatch:raise ValueError('备份原件与数据库校验值不一致：'+filename)
                        anomalies.append('校验值不一致：'+filename)
                for values in (json.loads(images),json.loads(batches)):
                    if not isinstance(values,list):raise ValueError('备份附件记录无效')
                    for value in values:
                        key=value.get('id') if isinstance(value,dict) else None
                        if not re.fullmatch('[a-f0-9]{32}',str(key)):raise ValueError('备份附件编号无效')
                        refs.add('files/'+key)
            if not refs<=names:
                if not allow_source_mismatch:raise ValueError('备份缺少附件或速记图片：'+', '.join(sorted(refs-names)[:3]))
                anomalies.append('缺少附件或速记图片')
            if manifest and manifest.get('records')!=records:raise ValueError('备份资料数量与清单不一致')
        return {'sha256':digest_sum,'snapshot':manifest.get('snapshot') if manifest else None,'state':'inconsistent' if anomalies else 'verified','anomalies':anomalies[:20],'mode':'manifest' if manifest else 'legacy','records':records,'chat_history_checked':'conversations.json' in names and not anomalies,'files':len(names),'referenced_files':len(refs)}
