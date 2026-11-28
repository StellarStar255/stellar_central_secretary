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


def visit_time(archive, question, turns):
    """Quote a dated visit note only when all indexed visit candidates are simple originals."""
    from datetime import date, timedelta
    match = re.fullmatch(r'(?:请问)?(?:我(?:的)?)?(今天|明天|后天)(?:的)?(?:看病|就诊|复诊|挂号|看医生|门诊)(?:时间)?(?:是|在)?(?:几点(?:钟)?|什么时候)[？?]?', question.strip())
    if not match or turns:
        return None
    target = date.today() + timedelta(days=('今天', '明天', '后天').index(match[1]))
    date_text = rf'(?:{target.isoformat()}|{target.year}年0?{target.month}月0?{target.day}日)'
    clock = r'(?:(?:(?:上午|下午|中午|晚上|早上)(?:0?[1-9]|1[0-2])|[01]?\d|2[0-3])[:：][0-5]\d|(?:上午|下午|中午|晚上|早上)(?:1[0-2]|[1-9]|十[一二]?|[一二三四五六七八九两])点(?:半|[0-5]?\d分)?)'
    event = r'(?:看病|就诊|复诊|挂号|看医生|门诊|复查)'
    fact = re.compile(date_text + rf'(?:（周{"一二三四五六日"[target.weekday()]}）)?\s*(?:' + clock + r'\s*' + event + '|' + event + r'\s*' + clock + r')[。.]?')
    with archive.db() as db:
        db.execute('BEGIN')
        rows = db.execute("""SELECT * FROM items WHERE trashed_at='' AND id IN
            (SELECT item_id FROM search WHERE search MATCH ?) LIMIT 2""",
            ('看病 OR 就诊 OR 复诊 OR 挂号 OR 医生 OR 门诊 OR 复查 OR 医院 OR 预约 OR 改期 OR 取消',)).fetchall()
        if len(rows) != 1 or rows[0]['kind'] != 'note':
            return None
        item = dict(rows[0])
        value = content(item, arrangement_text(item['text']))
        if not value or not fact.fullmatch(value):
            return None
        chunk = db.execute('SELECT * FROM chunks WHERE item_id=? AND position=0', (item['id'],)).fetchone()
        if not chunk:
            return None
    source = dict(chunk, title=item['title'], revision=item['updated'], origin=json.loads(chunk['origin']),
                  text=item['text'] + ('\n' + item['user_context'] if item['user_context'] else ''), url='', filename='')
    return f'你归档的安排是「{value}」。[1]', [source]
