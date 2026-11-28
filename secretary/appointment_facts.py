"""Index explicitly dated visit slots from original attachment text, including OCR."""
import json
import re
from datetime import date, timedelta

from . import archived_birthdays

VISIT = re.compile(r'就诊|挂号|门诊|看病|复诊|复查')
CHANGE = re.compile(r'取消|改期|改约|作废|失效|退号|更正|变更|预约失败|挂号失败|预约未成功|待确认|已过期')
DATE = r'(?P<y>20\d{2})[-年/.](?P<m>\d{1,2})[-月/.](?P<d>\d{1,2})日?'
CLOCK = r'(?:[01]?\d|2[0-3])[:：][0-5]\d'
SLOT = re.compile(DATE + r'[ \t]*(?:[（(]周(?P<weekday>[一二三四五六日天])[）)])?\s*(?:上午|下午|晚上)?\s*'
                  + r'(?P<start>' + CLOCK + r')(?:\s*[-~至—–～]\s*(?P<end>' + CLOCK + r'))?(?![\d:：]|\s*[-~至—–～])')
SUBJECT = re.compile(r'(?:就诊人|患者姓名)[：:][ \t]*([^\s，。；:：]{1,20})(?=\s|$)')
QUESTION = re.compile(r'(?:请问)?(今天|明天|后天)(?:的)?(?:看病|就诊|挂号|门诊|看医生|复诊)(?:时间)?(?:是|在)?(?:几点(?:钟)?|什么时候)[？?]?')


def index_source(db, chunks, text):
    if not VISIT.search(text):
        return
    if not re.search(r'就诊时间|挂号时间|预约时段|就诊时段|预约时间',text):
        return
    if len(re.findall(r"(?:就诊时间|挂号时间|预约时段|就诊时段|预约时间)[：:\s]*"+DATE,text))>1:
        return
    slots=list(SLOT.finditer(text))
    if len(slots)!=1:
        return
    slot=slots[0]
    try:
        day=date(*(int(slot[key]) for key in ('y','m','d')))
    except ValueError:
        return
    if slot['weekday'] and slot['weekday'].replace('天','日')!='一二三四五六日'[day.weekday()]:
        return
    start=slot['start'].replace('：',':').zfill(5)
    end=slot.groupdict().get('end')
    if (end and start>=end.replace('：',':').zfill(5)) or ('下午' in slot[0] or '晚上' in slot[0]) and int(start[:2])<12:
        return
    # A separate payment or booking timestamp must not become the visit slot.
    before=text[:slot.start()].rstrip()
    if not re.search(r'(?:就诊时间|挂号时间|预约时段|就诊时段|预约时间)[：:\s]*$',before):
        if not (end and '预约成功' in text and '挂号时间' in before[-100:] and
                not re.search('付款|缴费|下单|支付|签到|取号|候诊',before[before.rfind('挂号时间')+4:])):
            return
    subjects=set(SUBJECT.findall(text))
    if len(subjects)>1:return
    # Use the actual chunk containing the entire quote, including an overlap.
    for chunk,offset,length in chunks:
        if offset<=slot.start() and slot.end()<=offset+length:
            db.execute('INSERT OR REPLACE INTO appointment_slots VALUES (?,?,?,?,?)',
                       (chunk,day.isoformat(),slot[0],next(iter(subjects),''),slot.start()-offset))
            break


def initialize(db):
    version='appointment_slots_version'
    db.execute('SAVEPOINT initialize_appointment_slots')
    db.execute('CREATE TABLE IF NOT EXISTS appointment_slots(chunk_id INTEGER PRIMARY KEY,day TEXT,quote TEXT,subject TEXT,offset INTEGER)')
    db.execute('CREATE TRIGGER IF NOT EXISTS appointment_slot_removed AFTER DELETE ON chunks BEGIN DELETE FROM appointment_slots WHERE chunk_id=old.id; END')
    had_index=db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='appointment_slots_day'").fetchone()
    db.execute('CREATE INDEX IF NOT EXISTS appointment_slots_day ON appointment_slots(day)')
    stored=db.execute('SELECT value FROM settings WHERE key=?',(version,)).fetchone()
    if had_index and stored and stored[0]=='3':
        db.execute('RELEASE initialize_appointment_slots')
        return
    db.execute('DELETE FROM appointment_slots')
    origins=db.execute("""SELECT DISTINCT item_id,origin FROM chunks WHERE origin!='{}'
                          AND (text LIKE '%时间%' OR text LIKE '%时段%')""")
    for item_id,origin in origins:
        rows=db.execute('SELECT id,text FROM chunks WHERE item_id=? AND origin=? ORDER BY id',(item_id,origin)).fetchall()
        # Original attachment chunks start every 1000 characters and overlap.
        parts=[row['text'][:1000] for row in rows[:-1]]+[rows[-1]['text']]
        chunks=[(row['id'],i*1000,len(row['text'])) for i,row in enumerate(rows)]
        index_source(db,chunks,''.join(parts))
    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(version,'3'))
    db.execute('RELEASE initialize_appointment_slots')


def requested_day(match):
    return date.today()+timedelta(days=('今天','明天','后天').index(match[1]))


def excerpts(db, question, passages):
    match=QUESTION.fullmatch(question.strip())
    if not match or not passages:return []
    ids=list(dict.fromkeys(p['item_id'] for p in passages))
    rows=db.execute("""SELECT c.item_id,i.title,c.origin,f.quote FROM appointment_slots f
        JOIN chunks c ON c.id=f.chunk_id JOIN items i ON i.id=c.item_id
        WHERE i.trashed_at='' AND c.item_id IN ("""+','.join('?' for _ in ids)+") ORDER BY abs(julianday(f.day)-julianday(?)),f.day DESC LIMIT 2",[*ids,requested_day(match).isoformat()])
    return [dict(item_id=row['item_id'],title=row['title'],text=row['quote'],origin=json.loads(row['origin'])) for row in rows]


def lookup(archive, question, turns):
    match=QUESTION.fullmatch(question.strip())
    if not match or any(not archived_birthdays.QUESTION.fullmatch(t['question']) for t in turns):
        return
    target=requested_day(match)
    with archive.db() as db:
        db.execute('BEGIN')
        rows=db.execute("""SELECT c.*,f.quote,f.subject,i.title,i.filename,i.url,i.updated AS revision,
                i.note,i.note_images,i.user_context,i.additions,i.text AS body,i.vision_text
            FROM appointment_slots f JOIN chunks c ON c.id=f.chunk_id JOIN items i ON i.id=c.item_id
            WHERE f.day=? AND i.trashed_at='' LIMIT 2""",(target.isoformat(),)).fetchall()
        if len(rows)!=1:return
        row=rows[0]
        if (row['note'] or row['note_images']!='[]' or row['additions']!='[]' or row['user_context']
                or len(set(SUBJECT.findall(row['body'])))>1 or CHANGE.search(row['body']+' '+row['vision_text']+' '+row['title'])):return
        # Other appointment records or separate corrections need the full search.
        conflict=db.execute("""SELECT 1 FROM search WHERE search MATCH ? AND item_id!=? LIMIT 1""",
            ('挂号 OR 就诊 OR 门诊 OR 复诊 OR 看病 OR 复查 OR 改期 OR 取消 OR 退号 OR 改约 OR 变更 OR 作废 OR 更正',row['item_id'])).fetchone()
        if conflict:return
    source={key:row[key] for key in ('id','item_id','position','title','filename','url','revision')}
    source.update(text=row['quote'],origin=json.loads(row['origin']))
    who=f"（就诊人：{row['subject']}）" if row['subject'] else ''
    return f"归档预约单{who}上的时段是 {row['quote']}。[1]",[source]
