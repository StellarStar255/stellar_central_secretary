"""Local playback metadata. Cache identity follows the original, never its title."""
import base64,hashlib,io,json,math,threading,uuid
from pathlib import Path
from PIL import Image

_lock=threading.RLock()

def identity(root,source,key=''):
    info=Path(source).stat()
    return hashlib.sha256(f'{Path(source).name}:{info.st_size}:{info.st_mtime_ns}:{key}'.encode()).hexdigest()

def read(root,key):
    with _lock:
        try:return json.loads((Path(root)/'video-cache'/(key+'.json')).read_text())
        except (OSError,ValueError):return {}

def save(root,key,body):
    with _lock:
        value=read(root,key)
        for field in ('position','duration'):
            if field in body:
                number=body[field]
                if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not 0<=number<=604800:raise ValueError('视频播放时间无效')
                value[field]=number
        if value.get('duration') and value.get('position',0)>=value['duration']-min(2,value['duration']*.05):value['position']=0
        folder=Path(root)/'video-cache';folder.mkdir(exist_ok=True)
        if body.get('poster'):
            raw=base64.b64decode(body['poster'],validate=True)
            if len(raw)>500000:raise ValueError('视频封面过大')
            with Image.open(io.BytesIO(raw)) as image:
                if image.width*image.height>1000000:raise ValueError('视频封面尺寸过大')
                image.thumbnail((480,320));output=io.BytesIO();image.convert('RGB').save(output,'JPEG',quality=82)
            temporary=folder/(key+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(output.getvalue());temporary.replace(folder/(key+'.jpg'))
            value['poster']=True
        temporary=folder/(key+'.'+uuid.uuid4().hex+'.tmp');temporary.write_text(json.dumps(value));temporary.replace(folder/(key+'.json'))
        return value
