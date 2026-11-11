"""Local HEIF decoding; compatible derivatives never replace original bytes."""
import io
from pathlib import Path
from PIL import Image,ImageOps
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)
HEIF_MEDIA={'HEIF':'image/heic'}

def is_heif(name):return Path(name).suffix.lower() in ('.heic','.heif','.hif')

def preview(data):
    if len(data)>50*1024**2:raise ValueError('图片原件超过 50 MB，无法生成预览')
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width*source.height>40_000_000:raise ValueError('图片尺寸超过 4000 万像素')
            image=ImageOps.exif_transpose(source)
            image.thumbnail((2560,2560))
            if image.mode in ('RGBA','LA'):
                rgba=image.convert('RGBA');image=Image.new('RGB',rgba.size,'white');image.paste(rgba,mask=rgba.getchannel('A'))
            else:image=image.convert('RGB')
            output=io.BytesIO();image.save(output,'JPEG',quality=90)
            return output.getvalue()
    except (OSError,Image.UnidentifiedImageError) as error:
        raise ValueError('HEIC/HEIF 图片无法解码，原件已保留') from error
