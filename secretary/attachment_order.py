"""Presentation order for stable, item-owned attachment identities."""
import json,re
TOKEN=re.compile(r'(?:original|[a-f0-9]{32}):(?:original|[a-f0-9]{32})')

def records(value):
    if isinstance(value,str):value=json.loads(value)
    if not isinstance(value,list) or len(value)>10000 or any(not isinstance(token,str) or not TOKEN.fullmatch(token) or token.endswith(':original') and token!='original:original' for token in value) or len(value)!=len(set(value)):
        raise ValueError('附件排序格式无效')
    return value

def key(file):return (file.get('batch_id') or 'original')+':'+file['id']

def ordered(files,order):
    positions={token:index for index,token in enumerate(records(order))}
    return sorted(files,key=lambda file:positions.get(key(file),len(positions)))

def remap(order,batches):
    return [batches.get(token.split(':')[0],token.split(':')[0])+':'+token.split(':')[1] for token in records(order)]
