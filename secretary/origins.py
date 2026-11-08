"""Server-built source anchors; never accept model-generated filesystem locations."""
import json,re
from . import bundles,pdf_reading

def pages(text):
    return [(int(match[1]),match[2].strip()) for match in re.finditer(r'^\[第 (\d+) 页\](?:【[^\n]*】)?\n(.*?)(?=^\[第 \d+ 页\]|\Z)',text,re.M|re.S)]

def material(archive,db,item_id):
    row=db.execute('SELECT filename,digest,text,additions,pdf_reads FROM items WHERE id=?',(item_id,)).fetchone()
    if not row:return []
    outputs={};sources=[]
    if row['filename'] and not bundles.is_bundle(row['filename']):sources.append(('', '',row['filename'],row['digest'],row['text']))
    for batch_id in ([''] if bundles.is_bundle(row['filename']) else [])+[value['id'] for value in json.loads(row['additions'])]:
        try:
            archive_zip,manifest=bundles.load(archive.root/'files'/(batch_id or item_id))
            with archive_zip:
                for file in manifest['files']:sources.append((batch_id,file['id'],file['name'],file.get('sha256',''),file['text']))
        except (OSError,ValueError,KeyError):continue
    selected=pdf_reading.records(row['pdf_reads'])
    for batch,key,name,digest,text in sources:
        anchor={'batch_id':batch,'attachment_id':key,'name':name,'digest':digest}
        if name.lower().endswith('.pdf'):
            for page,content in pages(text):outputs[(batch,key,page)]=(content,{**anchor,'page':page,'method':'text'})
            entry=selected.get(pdf_reading.key(batch,key))
            if entry and (not digest or entry['digest']==digest):
                for number,value in entry['pages'].items():outputs[(batch,key,int(number))]=(value['text'],{**anchor,'page':int(number),'method':value['method']})
        elif text:outputs[(batch,key,0)]=(text,{**anchor,'method':'text'})
    return list(outputs.values())

def path(item_id,origin):
    base='/api/items/'+item_id;batch=origin.get('batch_id','');key=origin.get('attachment_id','')
    return base+('/additions/'+batch if batch else '')+('/attachments/'+key if key else '')
