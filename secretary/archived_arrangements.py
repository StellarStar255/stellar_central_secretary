"""Confirm an exact archived arrangement from live records, without a model."""
import json
import re
from .note_dates import arrangement_text,DATE_START


def content(item,value):
    if item['note'].strip() or item['note_images'] not in ('[]',[]) or item['additions'] not in ('[]',[]):return None
    context=item.get('user_context','')
    if context and not context.startswith('【日期解析】'):return None
    if context:
        reference=re.search(r'(\d{4}-\d{2}-\d{2})（([+-]\d{4})）',context)
        if not reference:return None
        from .note_dates import resolve
        day,zone=reference.groups()
        parsed=resolve(item['text'],day+'T00:00:00'+zone[:3]+':'+zone[3:])
        if not parsed or arrangement_text(parsed.split('\n',2)[-1])!=arrangement_text(context.split('\n',2)[-1]):return None
    result=context.split('\n',2)[-1] if context else value
    return arrangement_text(result)


def lookup(archive, question):
    value=arrangement_text(question)
    if not 4<=len(value)<=1000 or re.search(r'[?？]|```|https?://|\[\d+\]|吗|是否|为什么|怎么|如何|提醒我|改为|取消',value):return None
    if not re.search(r'今天|明天|后天|(?:周|星期|礼拜)[一二三四五六日天]|\d+月\d+日|\d{4}-\d{2}-\d{2}',value):return None
    if not re.search(r'\d{1,2}[:：点时]|上午|下午|中午|晚上|早上|复查|开会|预约|出发|面试|就诊|看病|见面',value):return None
    bodies=[value,'我'+value] if re.match(DATE_START,value) else [value]
    variants=list(bodies)
    for command in ('建档','存档','归档','保存','记录','记住'):
        for separator in ('：\n',':\n','：',':'):
            variants.extend(command+separator+body for body in bodies)
    with archive.db() as db:
        rows=db.execute("SELECT * FROM items WHERE kind='note' AND trashed_at='' AND text IN ("+','.join('?' for _ in variants)+") ORDER BY updated DESC LIMIT 9",variants).fetchall()
        if not rows or len(rows)>8:return None
        item=dict(rows[0])
        versions=[content(dict(row),value) for row in rows]
        # Equivalent duplicates are safe; conflicting dates or annotations are not.
        if None in versions or len(set(versions))!=1:return None
        chunk=db.execute('SELECT * FROM chunks WHERE item_id=? ORDER BY position LIMIT 1',(item['id'],)).fetchone()
        if chunk is None:return None
    context=item.get('user_context','')
    source=dict(chunk,title=item['title'],url=item['url'],filename='',revision=item['updated'])
    source['origin']=json.loads(source['origin'])
    source['text']=item['text']+('\n\n'+context if context else '')
    return '这条安排已归档：\n\n'+versions[0]+' [1]',[source]
