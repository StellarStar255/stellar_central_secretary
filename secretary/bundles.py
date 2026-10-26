"""One submission, one portable archive, with bounded visual-model inputs."""
import base64,io,json,re,uuid,zipfile
from pathlib import Path
from PIL import Image,ImageOps

MAX_BYTES=50*1024*1024
IMAGE_MEDIA={'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif','WEBP':'image/webp'}

def is_bundle(name):return str(name).lower().endswith('.stellar.zip')

def assemble(manifest):
    parts=[f"【组合资料】同一次发送的文字与 {len(manifest['files'])} 个附件。"]
    if manifest['text']:parts.append('用户文字：\n'+manifest['text'])
    for index,file in enumerate(manifest['files'],1):
        parts.append(f"附件 {index}：{file['name']}\n"+(file['text'] or ('图片原件已保存，图像内容将在启用 AI 时进行视觉分析。' if file['media'].startswith('image/') else '原件已保存，未提取到可读文字。'))+(('\n'+file['warning']) if file['warning'] else ''))
    return '\n\n'.join(parts)[:2_000_000]

def create(text,files):
    from .core import extract
    if not isinstance(text,str) or len(text)>200000:raise ValueError('组合资料的说明文字不能超过 20 万字符')
    if not isinstance(files,list) or not 1<=len(files)<=20:raise ValueError('每份组合资料需要 1–20 个附件')
    manifest={'version':1,'text':text,'files':[]};contents={};total=0;images=0;remaining=1_790_000
    for file in files:
        if not isinstance(file,dict):raise ValueError('组合附件格式无效')
        name=Path(str(file.get('name','')).replace('\\','/')).name
        if not name or name in ('.','..') or len(name)>300 or any(ord(char)<32 for char in name):raise ValueError('附件需要有效的文件名')
        encoded=file.get('data','')
        if not isinstance(encoded,str) or len(encoded)>MAX_BYTES*1.4:raise ValueError('组合附件总大小不能超过 50 MB')
        data=base64.b64decode(encoded,validate=True);total+=len(data)
        if total>MAX_BYTES:raise ValueError('组合附件总大小不能超过 50 MB')
        key=uuid.uuid4().hex;media='application/octet-stream';source='';warning=''
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width*image.height>40_000_000:raise ValueError('图片尺寸超过 4000 万像素，请缩小后再上传')
                detected=IMAGE_MEDIA.get(image.format,media)
                if getattr(image,'is_animated',False):warning='动态图的视觉分析仅使用首帧，原件完整保存。'
                image.verify()
                media=detected
        except (Image.UnidentifiedImageError,OSError):pass
        if media.startswith('image/'):
            images+=1
            if images>8:raise ValueError('每份组合资料最多包含 8 张图片')
        else:
            try:source,warning=extract(name,data)
            except Exception:warning='附件文字解析失败，原件已完整保存。'
        if len(source)>remaining:source=source[:remaining];warning+=' 正文超过组合资料索引上限，仅保存可索引的前部文字；原件完整保留。'
        remaining-=len(source)
        manifest['files'].append({'id':key,'name':name,'path':f'files/{len(manifest["files"])+1:02d}-{name}','media':media,'size':len(data),'text':source,'warning':warning})
        contents[manifest['files'][-1]['path']]=data
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        for path,data in contents.items():archive.writestr(path,data)
    if len(output.getbuffer())>MAX_BYTES:raise ValueError('组合资料含清单后超过 50 MB，请减少附件大小')
    return output.getvalue(),assemble(manifest)

def load(data):
    if len(data)>72*1024*1024:raise ValueError('组合资料文件过大')
    archive=zipfile.ZipFile(io.BytesIO(data));infos=archive.infolist()
    if len(infos)>21 or len({info.filename for info in infos})!=len(infos) or any(info.flag_bits&1 for info in infos):raise ValueError('组合资料结构无效')
    if sum(info.file_size for info in infos)>MAX_BYTES+16*1024*1024 or archive.getinfo('manifest.json').file_size>16*1024*1024:raise ValueError('组合资料展开后过大')
    value=json.loads(archive.read('manifest.json'))
    if value.get('version')!=1 or not isinstance(value.get('text'),str) or len(value['text'])>200000 or not isinstance(value.get('files'),list) or not 1<=len(value['files'])<=20:raise ValueError('组合资料清单无效')
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

def model_material(data,current_text):
    archive,value=load(data);images=[];parts=[];limited=False
    allowance=max(1000,100000//max(1,len(value['files'])))
    with archive:
        for file in value['files']:
            source=file['text']
            if file['name'].lower().endswith('.pdf'):
                later=re.search(r'^\[第 (?:[6-9]|[1-9][0-9]+) 页\]$',source,re.M)
                if later:source=source[:later.start()];limited=True
            if len(source)>allowance:source=source[:allowance];limited=True
            parts.append(file['name']+'\n'+source+('\n'+file['warning'] if file['warning'] else ''))
            if file['media'].startswith('image/'):
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
    scope='【组合资料概览】图片以分析用缩略图读取，原件完整保留。' if images else '【组合资料概览】'
    if limited or len(current_text)>20000:scope+=' 附件长文仅分析有界片段，PDF 默认仅概览前 5 页；未覆盖全部文字。'
    return source,images,scope
