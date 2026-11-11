"""Pair photo originals with an unambiguous same-name MOV in the owned catalog."""
from pathlib import Path

PHOTO_SUFFIXES={'.heic','.heif','.hif','.jpg','.jpeg'}

def annotate(files):
    photos=[file for file in files if Path(file['name']).suffix.lower() in PHOTO_SUFFIXES]
    videos=[file for file in files if Path(file['name']).suffix.lower()=='.mov']
    def stem(file):return Path(file['name']).stem.casefold()
    for photo in photos:
        photo.pop('live_video',None)
        candidates=[file for file in videos if stem(file)==stem(photo)]
        local=[file for file in candidates if file['batch_id']==photo['batch_id']]
        siblings=[file for file in photos if stem(file)==stem(photo) and file['batch_id']==photo['batch_id']]
        if len(local)==1 and len(siblings)==1:match=local[0]
        elif not local and len(candidates)==1 and sum(stem(file)==stem(photo) for file in photos)==1:match=candidates[0]
        else:continue
        photo['live_video']={key:match[key] for key in ('name','preview_url','download_url','can_open')}
    return files
