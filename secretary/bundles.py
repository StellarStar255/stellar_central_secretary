"""One submission, one portable archive, with bounded visual-model inputs."""
import base64,hashlib,io,json,re,uuid,zipfile,tempfile,shutil
from pathlib import Path
from PIL import Image,ImageOps
from . import links
from .media import video_type

MAX_BYTES=2*1024**3
INLINE_MAX=50*1024**2
MAX_FILE=1024**3
IMAGE_MEDIA={'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif','WEBP':'image/webp'}

def is_bundle(name):return str(name).lower().endswith('.stellar.zip')

def assemble(manifest):
    parts=[f"【组合资料】同一次发送的文字与 {len(manifest['files'])} 个附件。"+(f"另有 {len(manifest['links'])} 个相关链接。" if manifest.get('links') else '')]
    if manifest['text']:parts.append('用户文字：\n'+manifest['text'])
    if manifest.get('links'):parts.append(links.source(manifest['links']))
    for index,file in enumerate(manifest['files'],1):
        parts.append(f"附件 {index}：{file['name']}\n"+(file['text'] or ('图片原件已保存，图像内容将在启用 AI 时进行视觉分析。' if file['media'].startswith('image/') else '原件已保存，未提取到可读文字。'))+(('\n'+file['warning']) if file['warning'] else ''))
    return '\n\n'.join(parts)[:2_000_000]

def create(text,files,urls=None,existing=None):
    from .core import extract
    if not isinstance(text,str) or len(text)>200000:raise ValueError('组合资料的说明文字不能超过 20 万字符')
    if not isinstance(files,list) or len(files)>20 or not files and not text.strip() and not urls:raise ValueError('请添加文字或最多 20 个附件')
    manifest={'version':1,'text':text,'files':[],'links':links.prepare(urls or [])};contents={};total=0;images=0;remaining=1_790_000;seen=set(existing or [])
    streamed=any(isinstance(file,dict) and isinstance(file.get('source'),Path) for file in files)
    for file in files:
        if not isinstance(file,dict):raise ValueError('组合附件格式无效')
        name=Path(str(file.get('name','')).replace('\\','/')).name
        if not name or name in ('.','..') or len(name)>300 or any(ord(char)<32 for char in name):raise ValueError('附件需要有效的文件名')
        data=file.get('source')
        if isinstance(data,Path):
            size=data.stat().st_size
            with data.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        else:
            encoded=file.get('data','')
            if not isinstance(encoded,str) or len(encoded)>INLINE_MAX*1.4:raise ValueError('大附件请使用分块上传')
            data=base64.b64decode(encoded,validate=True);size=len(data);digest=hashlib.sha256(data).hexdigest()
        if size>MAX_FILE:raise ValueError('单个附件最大 1 GB')
        if digest in seen:continue
        seen.add(digest);total+=size
        if total>MAX_BYTES:raise ValueError('每批附件总计不能超过 2 GB')
        key=uuid.uuid4().hex;media='application/octet-stream';source='';warning=''
        # Large originals are streamed; analysis has a separate 50 MB bound.
        if size<=INLINE_MAX:
            raw=data.read_bytes() if isinstance(data,Path) else data
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width*image.height>40_000_000:raise ValueError('图片尺寸超过 4000 万像素，请缩小后再上传')
                    media=IMAGE_MEDIA.get(image.format,media)
                    if getattr(image,'is_animated',False):warning='动态图的视觉分析仅使用首帧，原件完整保存。'
                    image.verify()
            except (Image.UnidentifiedImageError,OSError):pass
            if not media.startswith('image/'):
                try:source,warning=extract(name,raw)
                except Exception:warning='附件文字解析失败，原件已完整保存。'
        elif name.lower().endswith('.pdf'):
            from .pdf_preview import read
            source,warning=read(data)
        else:warning='大附件原件已完整保存；自动正文解析限 50 MB，可手动补充正文。'
        if media.startswith('image/'):
            images+=1
            if images>8:raise ValueError('每份组合资料最多包含 8 张图片')
        if video_type(name):media=video_type(name);warning='视频原件已保存，可直接播放；暂未提取字幕或音轨正文。'
        if len(source)>remaining:source=source[:remaining];warning+=' 正文超过组合资料索引上限，仅保存可索引的前部文字；原件完整保留。'
        remaining-=len(source)
        path=f'files/{len(manifest["files"])+1:02d}-{name}'
        manifest['files'].append({'id':key,'name':name,'path':path,'media':media,'size':size,'sha256':digest,'text':source,'warning':warning});contents[path]=data
    manifest['duplicates_skipped']=len(files)-len(manifest['files'])
    if not manifest['files'] and not text.strip() and not urls:raise ValueError('这些附件已存在，没有重复保存')
    output=tempfile.NamedTemporaryFile(suffix='.stellar.zip',delete=False) if streamed else io.BytesIO()
    target=Path(output.name) if streamed else None
    try:
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            for path,data in contents.items():
                if isinstance(data,Path):archive.write(data,path,compress_type=zipfile.ZIP_STORED)
                else:archive.writestr(path,data)
        if target:output.close();return target,assemble(manifest)
        return output.getvalue(),assemble(manifest)
    except BaseException:
        output.close()
        if target:target.unlink(missing_ok=True)
        raise

def hashes(data):
    archive,value=load(data)
    with archive:
        result=set()
        for file in value['files']:
            with archive.open(file['path']) as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            result.add(digest)
        return result

def copy_data(source,target):
    if isinstance(source,Path):
        with source.open('rb') as src,Path(target).open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
    else:Path(target).write_bytes(source)

def cleanup(data):
    if isinstance(data,Path):data.unlink(missing_ok=True)


def load(data):
    size=data.stat().st_size if isinstance(data,Path) else len(data)
    if size>MAX_BYTES+16*1024*1024:raise ValueError('组合资料文件过大')
    archive=zipfile.ZipFile(data if isinstance(data,Path) else io.BytesIO(data));infos=archive.infolist()
    if len(infos)>21 or len({info.filename for info in infos})!=len(infos) or any(info.flag_bits&1 for info in infos):raise ValueError('组合资料结构无效')
    if sum(info.file_size for info in infos)>MAX_BYTES+16*1024*1024 or archive.getinfo('manifest.json').file_size>16*1024*1024:raise ValueError('组合资料展开后过大')
    value=json.loads(archive.read('manifest.json'))
    links.records(value.get('links',[]))
    if value.get('version')!=1 or not isinstance(value.get('text'),str) or len(value['text'])>200000 or not isinstance(value.get('files'),list) or len(value['files'])>20 or not value['files'] and not value['text'].strip() and not value.get('links'):raise ValueError('组合资料清单无效')
    names={'manifest.json'}
    for index,file in enumerate(value['files'],1):
        if not isinstance(file,dict) or not re.fullmatch('[a-f0-9]{32}',str(file.get('id',''))):raise ValueError('组合附件编号无效')
        if any(not isinstance(file.get(field),str) for field in ('name','media','text','warning')) or len(file['text'])>2_000_000:raise ValueError('组合附件字段无效')
        if Path(file['name']).name!=file['name'] or '\\' in file['name'] or file['name'] in ('','.','..'):raise ValueError('组合附件文件名无效')
        path=f'files/{index:02d}-'+file['name']
        if file.get('path')!=path:raise ValueError('组合附件路径无效')
        if path in names or type(file.get('size')) is not int or file['size']<0 or archive.getinfo(path).file_size!=file['size']:raise ValueError('组合附件大小无效')
        names.add(path)
    if names!={info.filename for info in infos}:raise ValueError('组合资料包含未知文件')
    return archive,value

def metadata(data):
    archive,value=load(data)
    with archive:return [{key:file[key] for key in ('id','name','media','size','warning')} for file in value['files']]

def attachment(data,key):
    archive,value=load(data)
    with archive:
        file=next((file for file in value['files'] if file['id']==key),None)
        if file is None:raise KeyError('组合附件不存在')
        return file,archive.read(file['path'])

class Member:
    def __init__(self,path,file):self.path=path;self.file=file
    def stat(self):
        from types import SimpleNamespace
        return SimpleNamespace(st_size=self.file['size'])
    def open(self,mode='rb'):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            with zipfile.ZipFile(self.path) as archive:
                info=archive.getinfo(self.file['path'])
                if info.compress_type==zipfile.ZIP_STORED:
                    import struct
                    with Path(self.path).open('rb') as raw:
                        raw.seek(info.header_offset);header=raw.read(30)
                        if len(header)!=30 or header[:4]!=b'PK\x03\x04':raise ValueError('附件归档头部无效')
                        name_length,extra_length=struct.unpack('<HH',header[26:30]);start=info.header_offset+30+name_length+extra_length
                        class Region:
                            def __init__(self):self.position=0;raw.seek(start)
                            def seek(self,offset,whence=0):
                                value=offset if whence==0 else self.position+offset if whence==1 else info.file_size+offset
                                if value<0:raise ValueError('Invalid seek')
                                self.position=min(value,info.file_size);raw.seek(start+self.position);return self.position
                            def tell(self):return self.position
                            def readinto(self,buffer):
                                data=self.read(len(buffer));buffer[:len(data)]=data;return len(data)
                            def read(self,size=-1):
                                length=info.file_size-self.position
                                value=raw.read(length if size<0 else min(length,size));self.position+=len(value);return value
                        yield Region()
                else:
                    with archive.open(info) as stream:yield stream
        return opened()
    def read_bytes(self):
        with self.open() as stream:return stream.read()

def member(data,key):
    archive,value=load(data)
    with archive:
        file=next((file for file in value['files'] if file['id']==key),None)
        if file is None:raise KeyError('组合附件不存在')
        return file,Member(data,file)

def model_material(data,current_text,link_values=None):
    archive,value=load(data);images=[];parts=[];limited=False;pdf_scopes=[]
    allowance=max(1000,100000//max(1,len(value['files'])))
    with archive:
        for file in value['files']:
            source=file['text']
            if file['name'].lower().endswith('.pdf'):
                if file['size']>INLINE_MAX:pdf_scopes.append(file['name']+'：'+file['warning'])
                later=re.search(r'^\[第 (?:[6-9]|[1-9][0-9]+) 页\]$',source,re.M)
                if later:source=source[:later.start()];limited=True
            if len(source)>allowance:source=source[:allowance];limited=True
            parts.append(file['name']+'\n'+source+('\n'+file['warning'] if file['warning'] else ''))
            if file['media'].startswith('image/') and file['size']<=INLINE_MAX:
                if len(images)>=8:raise ValueError('每份组合资料最多分析 8 张图片')
                with Image.open(io.BytesIO(archive.read(file['path']))) as original:
                    if original.width*original.height>40_000_000:raise ValueError('图片尺寸过大，原件已保存')
                    image=ImageOps.exif_transpose(original);image.thumbnail((1600,1600))
                    if image.mode in ('RGBA','LA'):
                        rgba=image.convert('RGBA');image=Image.new('RGB',rgba.size,'white');image.paste(rgba,mask=rgba.getchannel('A'))
                    else:image=image.convert('RGB')
                    output=io.BytesIO();image.save(output,format='JPEG',quality=88)
                    if output.tell()>700000:
                        image.thumbnail((1200,1200));output=io.BytesIO();image.save(output,format='JPEG',quality=78)
                    images.append({'name':file['name'],'media':'image/jpeg','data':output.getvalue()})
    # Keep user edits to the archived text in scope as well as attachment order.
    source=(value['text'] if current_text==assemble(value) else current_text)[:20000]+'\n\n附件文字概览：\n'+'\n\n'.join(parts)
    link_values=links.records(value.get('links',[]) if link_values is None else link_values)
    if link_values:
        budget=max(1000,100000//len(link_values));selected=[dict(link,text=link['text'][:budget]) for link in link_values]
        source+='\n\n'+links.source(selected)
        limited=limited or any(len(link['text'])>budget for link in link_values)
    scope='【组合资料概览】图片以分析用缩略图读取，原件完整保留。' if images else '【组合资料概览】'
    if pdf_scopes:scope+='\n'+'\n'.join(pdf_scopes)
    if limited or len(current_text)>20000:scope+=' 附件长文仅分析有界片段，PDF 默认仅概览前 5 页；未覆盖全部文字。'
    if link_values:scope+=' 本组 '+str(len(link_values))+' 个链接，已读取 '+str(sum(link['state']=='read' for link in link_values))+' 个；未读取来源仅保存链接，不推断正文。'
    return source,images,scope
