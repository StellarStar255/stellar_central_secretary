"""Local media types and single byte ranges for native HTML video playback."""
import re
from pathlib import Path

VIDEO_MEDIA={'.mp4':'video/mp4','.m4v':'video/mp4','.mov':'video/quicktime',
             '.webm':'video/webm','.ogv':'video/ogg','.mkv':'video/x-matroska',
             '.avi':'video/x-msvideo','.wmv':'video/x-ms-wmv','.mpeg':'video/mpeg','.mpg':'video/mpeg'}

def video_type(name):return VIDEO_MEDIA.get(Path(name).suffix.lower())

def byte_range(value,size):
    """Inclusive bounds; invalid/unsatisfiable requests raise ValueError (HTTP 416)."""
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value.strip())
    if not match or not any(match.groups()) or not size:raise ValueError('Invalid byte range')
    first,last=match.groups()
    if not first:
        length=int(last)
        if length<=0:raise ValueError('Invalid suffix range')
        return max(0,size-length),size-1
    start=int(first);end=min(int(last),size-1) if last else size-1
    if start>=size or end<start:raise ValueError('Unsatisfiable byte range')
    return start,end
