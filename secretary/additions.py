"""Append-only material batches; each original ZIP is owned by its parent archive."""
import json,re,uuid
from datetime import datetime,timezone
from . import bundles

def records(value):
    result=json.loads(value) if isinstance(value,str) else value
    if not isinstance(result,list) or len(result)>100:raise ValueError('追加记录无效或超过 100 批')
    seen=set()
    for batch in result:
        if not isinstance(batch,dict) or not re.fullmatch('[a-f0-9]{32}',str(batch.get('id',''))) or batch['id'] in seen:raise ValueError('追加资料编号无效')
        seen.add(batch['id'])
        if any(not isinstance(batch.get(key),str) for key in ('text','summary','vision_text','created','state','error')):raise ValueError('追加资料字段无效')
        if len(batch['text'])>200000 or len(batch['summary'])>60000 or len(batch['vision_text'])>60000:raise ValueError('追加资料文字过长')
    if sum(len(batch['text']) for batch in result)>2_000_000:raise ValueError('追加资料可索引文字总量超过 200 万字符')
    return result

def combined_summary(base,batches):
    return '\n\n'.join([base]+['【追加摘要 · '+batch['created'][:10]+'】\n'+batch['summary'] for batch in batches if batch['summary']]).strip()

def index_text(batches):
    return '\n\n'.join('【追加资料 · '+batch['created']+'】\n'+batch['text']+'\n'+batch['summary']+'\n【AI 图片解读，需核对原图】\n'+batch['vision_text'] for batch in batches)

def find(item,batch_id):
    return next((batch for batch in item['additions'] if batch['id']==batch_id),None)

def save(archive,item_id,text,files,expected):
    data,source=bundles.create(text,files)
    batch={'id':uuid.uuid4().hex,'created':datetime.now(timezone.utc).isoformat(),'text':source[:200000],'summary':'','vision_text':'','state':'pending','error':''}
    if len(source)>200000:batch['text']+='\n【追加索引仅保留前部文字；完整原件已保存。】';batch['text']=batch['text'][:199940]+'\n【追加索引仅保留前部文字；完整原件已保存。】'
    with archive.lock:
        item=archive.get(item_id)
        if expected!=item['updated']:raise ValueError('资料已更新，请重新打开后再追加；本次草稿仍保留')
        batches=item['additions']+[batch];records(batches)
        target=archive.root/'files'/batch['id'];created=False
        try:
            with target.open('xb') as stream:created=True;stream.write(data)
            with archive.db() as db:
                db.execute('UPDATE items SET additions=?,updated=? WHERE id=?',(json.dumps(batches,ensure_ascii=False),batch['created'],item_id))
                archive._index(db,item_id,item['text'])
        except BaseException:
            if created:target.unlink(missing_ok=True)
            raise
    return batch['id']

def update(archive,item_id,batch_id,**fields):
    with archive.lock,archive.db() as db:
        row=db.execute('SELECT additions,text FROM items WHERE id=?',(item_id,)).fetchone()
        if not row:raise KeyError('资料不存在')
        batches=records(row['additions']);batch=next((b for b in batches if b['id']==batch_id),None)
        if batch is None:raise KeyError('追加资料不存在')
        batch.update(fields);records(batches)
        db.execute('UPDATE items SET additions=?,updated=? WHERE id=?',(json.dumps(batches,ensure_ascii=False),datetime.now(timezone.utc).isoformat(),item_id))
        archive._index(db,item_id,row['text'])
