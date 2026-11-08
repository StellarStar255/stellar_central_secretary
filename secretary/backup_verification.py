"""Verify a snapshot on disk without replacing or opening the live library."""
import hashlib,json,re,sqlite3,tempfile,zipfile
from contextlib import closing
from pathlib import Path

def verify(source,expected_sha,max_schema,allow_source_mismatch=False):
    with source.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=expected_sha:raise ValueError('备份 SHA256 校验失败，当前资料未修改')
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
            for ident,filename,digest,images,batches in db.execute('SELECT id,filename,digest,'+optional+' FROM items'):
                records+=1
                if not re.fullmatch('[a-f0-9]{32}',str(ident)):raise ValueError('备份资料编号无效')
                if filename:
                    name='files/'+ident;refs.add(name)
                    if name not in actual:
                        if not allow_source_mismatch:raise ValueError('备份缺少原件')
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
                if not allow_source_mismatch:raise ValueError('备份缺少附件或速记图片')
                anomalies.append('缺少附件或速记图片')
            if manifest and manifest.get('records')!=records:raise ValueError('备份资料数量与清单不一致')
        return {'state':'inconsistent' if anomalies else 'verified','anomalies':anomalies[:20],'mode':'manifest' if manifest else 'legacy','records':records,'files':len(names),'referenced_files':len(refs)}
