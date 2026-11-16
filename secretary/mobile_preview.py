"""Small, metadata-free phone image previews; originals remain byte-identical."""
import io,os,uuid
from PIL import Image,ImageOps
from . import image_formats

MAX_PREVIEW=96*1024

def render(source,cache,key):
    target=cache/(key+'.jpg')
    if target.exists():return target.read_bytes()
    if source.stat().st_size>50*1024*1024:raise ValueError('图片超过 50 MB，请下载原件')
    with Image.open(io.BytesIO(source.read_bytes())) as original:
        if original.width*original.height>40_000_000:raise ValueError('图片尺寸过大，请下载原件')
        image=ImageOps.exif_transpose(original).convert('RGB');image.thumbnail((1280,1280))
        while True:
            output=io.BytesIO();image.save(output,'JPEG',quality=65,optimize=True)
            data=output.getvalue()
            if len(data)<=MAX_PREVIEW:break
            image.thumbnail((max(1,int(image.width*.8)),max(1,int(image.height*.8))))
    cache.mkdir(parents=True,exist_ok=True)
    temporary=cache/(uuid.uuid4().hex+'.tmp')
    try:temporary.write_bytes(data);os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)
    # Bounded derivatives only; never prune any original archive.
    for stale in sorted(cache.glob('*.jpg'),key=lambda p:p.stat().st_mtime,reverse=True)[128:]:stale.unlink(missing_ok=True)
    return data
