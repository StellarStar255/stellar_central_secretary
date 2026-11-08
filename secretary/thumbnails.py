"""Small, local first-page/image previews; originals are never rewritten."""
import hashlib,io,re
from contextlib import ExitStack
from .pdf_preview import LOCK
from collections import OrderedDict
from pathlib import Path
from PIL import Image,ImageOps

_lock=LOCK
_cache=OrderedDict()

def render(name,data):
    suffix=Path(name).suffix.lower()
    if isinstance(data,bytes):key=(suffix,hashlib.sha256(data).digest())
    else:
        path=data if isinstance(data,Path) else data.path;info=path.stat()
        key=(suffix,str(path.resolve()),info.st_size,info.st_mtime_ns,getattr(data,'file',{}).get('id',''))
    # PDFium calls must be serialized even for separate documents.
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        try:
            if suffix=='.pdf':
                import pypdfium2 as pdfium
                with ExitStack() as stack:
                    source=data if isinstance(data,(bytes,Path)) else stack.enter_context(data.open('rb'))
                    doc=stack.enter_context(pdfium.PdfDocument(source))
                    page=doc[0]
                    width,height=page.get_size()
                    if min(width,height)<=0:raise ValueError('Invalid page size')
                    bitmap=page.render(scale=min(1,320/max(width,height)))
                    try:image=bitmap.to_pil().copy()
                    finally:bitmap.close()
            else:
                with Image.open(io.BytesIO(data)) as source:
                    if source.width*source.height>40_000_000:raise ValueError('Image too large')
                    source.thumbnail((320,320))
                    image=ImageOps.exif_transpose(source).convert('RGBA')
            output=io.BytesIO()
            with image:image.save(output,format='PNG')
            result=(output.getvalue(),'image/png')
        except Exception:
            label=re.sub('[^A-Z0-9]','',suffix.upper())[:6] or 'FILE'
            result=(('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160" viewBox="0 0 240 160"><rect width="240" height="160" rx="10" fill="#30383d"/><path d="M87 25h47l23 23v85H87z" fill="#e4e9ec"/><path d="M134 25v23h23" fill="none" stroke="#82939e" stroke-width="3"/><text x="122" y="98" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#30383d">'+label+'</text></svg>').encode(),'image/svg+xml')
        _cache[key]=result
        while len(_cache)>128:_cache.popitem(last=False)
        return result
