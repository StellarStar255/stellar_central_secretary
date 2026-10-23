"""User-owned quick notes and local image attachments; never sent to AI."""
import base64,io,re,uuid
from pathlib import Path
from PIL import Image

MAX_IMAGES=8
MAX_IMAGE=5*1024*1024

def image_bytes(data):
    if len(data)>MAX_IMAGE:raise ValueError('每张速记图片不能超过 5 MB。')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width*image.height>40_000_000:raise ValueError('速记图片尺寸过大。')
            kind=image.format;image.verify()
        media={'PNG':'image/png','JPEG':'image/jpeg','GIF':'image/gif','WEBP':'image/webp'}[kind]
    except (OSError,KeyError,Image.DecompressionBombError) as error:raise ValueError('速记仅支持 PNG、JPEG、GIF 和 WebP 图片。') from error
    return media


def set_note(archive,item_id,text,images,version):
    if not isinstance(text,str) or len(text)>20000:raise ValueError('速记文字不能超过 20000 个字符。')
    if not isinstance(images,list) or len(images)>MAX_IMAGES:raise ValueError('每份速记最多添加 8 张图片。')
    if not isinstance(version,int) or isinstance(version,bool):raise ValueError('速记版本无效，请刷新资料。')
    created=[];committed=False
    with archive.lock:
        item=archive.get(item_id)
        if version!=item['note_version']:raise ValueError('速记已在其他窗口更新，请重新打开资料后再编辑。')
        old={image['id']:image for image in item['note_images']};saved=[];seen=set()
        try:
            for image in images:
                if not isinstance(image,dict):raise ValueError('速记图片格式无效。')
                if image.get('id'):
                    if image['id'] not in old or image['id'] in seen:raise ValueError('速记图片不存在或重复。')
                    saved.append(old[image['id']]);seen.add(image['id']);continue
                encoded=image.get('data','')
                if not isinstance(encoded,str) or len(encoded)>MAX_IMAGE*1.4:raise ValueError('每张速记图片不能超过 5 MB。')
                try:data=base64.b64decode(encoded,validate=True)
                except ValueError as error:raise ValueError('速记图片格式无效。') from error
                media=image_bytes(data);key=uuid.uuid4().hex;target=archive.root/'files'/key
                with target.open('xb') as stream:created.append(target);stream.write(data)
                name=Path(str(image.get('name') or 'image').replace('\\','/')).name[:180]
                saved.append({'id':key,'name':name,'media':media})
            import json
            from datetime import datetime,timezone
            with archive.db() as db:
                db.execute('UPDATE items SET note=?,note_images=?,note_version=note_version+1,updated=? WHERE id=?',
                           (text,json.dumps(saved,ensure_ascii=False),datetime.now(timezone.utc).isoformat(),item_id))
            committed=True
            for key in old.keys()-{image['id'] for image in saved}:
                try:(archive.root/'files'/key).unlink(missing_ok=True)
                except OSError:pass
            return archive.get(item_id)
        except BaseException:
            if not committed:
                for target in created:target.unlink(missing_ok=True)
            raise


def note_image(archive,item_id,image_id):
    item=archive.get(item_id)
    if not re.fullmatch('[a-f0-9]{32}',image_id):raise KeyError('速记图片不存在')
    image=next((image for image in item['note_images'] if image['id']==image_id),None)
    target=archive.root/'files'/image_id
    if image is None or not target.is_file():raise KeyError('速记图片不存在')
    return image,target
