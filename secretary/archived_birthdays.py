"""Answer simple birthday lookups from matching original notes."""
import json
import re
from datetime import date

from .conversation_context import CONDITION_PREFIX
from .core import terms
from .note_dates import arrangement_text

QUESTION = re.compile(
    r'(?:请问\s*)?([\w·]{1,40}?)\s*(?:的\s*)?(?:生日|出生日期)'
    r'\s*(?:(?:是\s*)?(?:哪天|哪一天|几月几号|几月几日|什么时候)|呢)?(?:\s*[？?])*'
)
NUMERALS = '零一二三四五六七八九'
CHINESE_YEAR = str.maketrans('〇' + NUMERALS, '00123456789')
MONTHS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
DAYS = ['初' + n for n in '一二三四五六七八九十'] + [
    '十' + n for n in '一二三四五六七八九'] + ['二十'] + [
    '廿' + n for n in '一二三四五六七八九'] + ['三十', '三十一']


def day_number(value):
    if value.isdecimal():
        return int(value)
    value = value.replace('二十', '廿') if value.startswith('二十') and len(value) > 2 else value
    if value in MONTHS[:10]:
        return MONTHS.index(value) + 1
    return DAYS.index(value) + 1 if value in DAYS else 0


def date_identity(value):
    value = re.sub(r'\s+', '', value)
    calendar = ''
    if value.startswith(('农历', '阴历')):
        calendar = 'lunar'
    elif value.startswith(('公历', '阳历', '新历')):
        calendar = 'solar'
    leap = False
    value = re.sub(r'^(?:农历|阴历|公历|阳历|新历)', '', value)
    iso = re.fullmatch(r'(\d{4})([-/.])(\d{1,2})\2(\d{1,2})', value)
    if iso:
        year, month, day = (int(iso[i]) for i in (1, 3, 4))
    else:
        fields = re.fullmatch(r'(?:([0-9〇零一二三四五六七八九]{4})年)?(闰?)([^月]+)月(.+?)[日号]?', value)
        if not fields:
            return None
        year_text, leap, month_text, day_text = fields.groups()
        month_text = {'正':'一', '冬':'十一', '腊':'十二'}.get(month_text, month_text)
        if month_text.isdecimal():
            month = int(month_text)
        elif month_text in MONTHS:
            month = MONTHS.index(month_text) + 1
        else:
            return None
        day = day_number(day_text)
        year = int(year_text.translate(CHINESE_YEAR)) if year_text else None
        if leap and calendar != 'lunar':
            return None
    if calendar == 'lunar':
        if year == 0 or not (1 <= month <= 12 and 1 <= day <= 30):
            return None
    else:
        try:
            date(2000 if year is None else year, month, day)
        except ValueError:
            return None
    return calendar, year, bool(leap), month, day


def depends_on_conversation(subject, item_ids, turns, record, archived_date):
    related = False
    for turn in turns:
        statement = turn['question']
        mentions_subject = subject in statement
        cited = item_ids.intersection(turn['source_ids'])
        fact = record and record.fullmatch(arrangement_text(statement.removeprefix(CONDITION_PREFIX)))
        if fact and date_identity(fact[1]) == archived_date:
            related = True
            continue
        if statement.startswith(CONDITION_PREFIX):
            if cited or mentions_subject or re.search(r'生日|出生日期|农历|阳历', statement):
                return True
            continue
        correction = re.search(r'更正|纠正|记错|说错|写错|不对|有误|改为|改成|不是|为准', statement)
        supplies_date = re.search(r'(?:农历|阴历|阳历|公历|[一二三四五六七八九十正冬腊0-9]+月)', statement)
        if (mentions_subject or cited or related) and (correction or supplies_date) and not QUESTION.fullmatch(statement.strip()):
            return True
        if turn['source_ids'] or mentions_subject:
            related = bool(cited or mentions_subject)
    return False


def lookup(archive, question, turns=()):
    match = QUESTION.fullmatch(question.strip())
    if not match:
        return None
    subject = match[1]
    if subject in ('他', '她', '他们', '她们', '那个人', '这个人'):
        return None
    # Read birthday candidates across material types so a correction in an
    # attachment or a separately worded note can prevent a stale direct answer.
    self_lookup = subject in ('我','本人')
    tokens = [] if self_lookup else list(dict.fromkeys(token for token in terms(subject) if len(token) > 1))
    clauses = [f'"{token}"' for token in tokens]
    search = ' AND '.join(clauses + ['("生日" OR "出生")'])
    record = re.compile((r'(?:我|本人)' if self_lookup else re.escape(subject)) + r'\s*(?:的\s*)?(?:生日|出生日期)\s*[是在为]?\s*[:：]?\s*([^\n]{1,64}?)[。！!]?')
    with archive.db() as db:
        db.execute('BEGIN')
        rows = db.execute(
            "SELECT id,kind,title,text,updated,user_context,note,note_images,additions FROM items "
            "WHERE trashed_at='' AND id IN (SELECT DISTINCT item_id FROM search WHERE search MATCH ?) "
            "ORDER BY updated DESC LIMIT 9", (search,)).fetchall()
        if not rows or len(rows) > 8:
            return None
        dates = set()
        original_dates = []
        matches = []
        for row in rows:
            if row['kind'] != 'note' or row['user_context'] or row['note']:
                return None
            if row['note_images'] != '[]' or row['additions'] != '[]':
                return None
            body = arrangement_text(row['text'])
            if self_lookup:
                # A standalone relative's birthday cannot describe the speaker.
                relative = re.fullmatch(r'(?:[\w·]{1,20})?(?:爸爸|妈妈|父亲|母亲|儿子|女儿)(?:的)?(?:生日|出生日期)\s*[是在为]?\s*[:：]?\s*(.+?)[。！!]?', body)
                if relative and date_identity(relative[1]):
                    continue
            fact = record.fullmatch(body)
            identity = date_identity(fact[1]) if fact else None
            if identity is None:
                return None
            matches.append(row)
            dates.add(identity)
            original_dates.append(fact[1])
        if len(dates) != 1:
            return None
        matched_date=dates.pop()
        subjects=('我','本人') if self_lookup else (subject,)
        if any(depends_on_conversation(name, {row['id'] for row in matches}, turns, record, matched_date) for name in subjects):
            return None
        item = matches[0]
        chunk = db.execute('SELECT * FROM chunks WHERE item_id=? AND position=0 LIMIT 1', (item['id'],)).fetchone()
        if not chunk:
            return None
    source = dict(chunk, title=item['title'], text=item['text'], revision=item['updated'],
                  origin=json.loads(chunk['origin']), url='', filename='')
    owner = '你' if self_lookup else subject
    return f'{owner}的生日是{original_dates[0]}。[1]', [source]


def document_birthday(archive, question, turns):
    """Read a date from a name-bound ID field in original indexed documents."""
    match = QUESTION.fullmatch(question.strip())
    if not match or not re.fullmatch(r'[\u3400-\u9fff]{2,8}', match[1]):
        return None
    subject = match[1]
    if subject in ('本人','自己','他们','她们','那个人','这个人'):
        return None
    topic = ' AND '.join(f'"{token}"' for token in dict.fromkeys(terms(subject)))
    search = topic + ' AND (身份 OR 证件 OR 生日 OR 出生)'
    # Keep the boundaries between fields. A title or a nearby policyholder
    # name alone does not identify the owner of a number on a multi-person form.
    fields = re.compile(r'(?m)^[ \t]*(?:姓\s*名|名\s*称)[ \t:：]*' + re.escape(subject)
                        + r'\s+证件类型[\s:：]*(?:居民)?身份证\s+证件号码[\s:：]*([^\s，。；]+)')
    relative = re.compile(re.escape(subject)+r'(?:的)?(?:爸爸|妈妈|父亲|母亲|儿子|女儿)(?:的)?生日\s*[:：]?\s*(.+?)[。！!]?')
    sources = {}
    identity = None
    with archive.db() as db:
        db.execute('BEGIN')
        items = db.execute("""SELECT id,title,kind,updated,url,filename,text,note,user_context,note_images,additions
            FROM items WHERE trashed_at='' AND id IN (SELECT item_id FROM search WHERE search MATCH ?) LIMIT 17""",(search,)).fetchall()
        if len(items)>16:return None
        for item in items:
            if item['note'] or item['user_context'] or item['note_images']!='[]':
                return None
            batches=json.loads(item['additions'])
            if any(b.get('links') or re.search(r'更正|纠正|有误|生日|出生日期|身份证',b['text']+b['vision_text']+b['summary']) for b in batches):return None
            if item['kind']=='note':
                other = relative.fullmatch(arrangement_text(item['text']))
                if other and date_identity(other[1]):continue
                return None
            if item['kind']!='file' or re.search(r'更正|纠正|有误|出生日期|生日',item['title']+' '+item['text']):
                return None
            rows = db.execute("""SELECT c.* FROM chunks c WHERE c.item_id=? AND c.origin!='{}'
                AND c.id IN (SELECT chunk_id FROM search WHERE search MATCH ?) ORDER BY c.id LIMIT 65""",
                (item['id'],search)).fetchall()
            if len(rows)>64:return None
            found = False
            for row in rows:
                origin = json.loads(row['origin'])
                numbers=set(re.findall(r'(?<![0-9])[0-9]{17}[0-9Xx](?![0-9])',row['text'].upper()))
                if len(numbers)>1:return None
                for field in fields.finditer(row['text']):
                    number = field[1].upper()
                    if not re.fullmatch('[0-9]{17}[0-9X]',number):return None
                    weights = (7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2)
                    checksum = sum(int(d)*w for d,w in zip(number,weights))%11
                    if number[-1]!='10X98765432'[checksum] or (identity is not None and identity!=number):
                        return None
                    identity = number
                    found = True
                    key=(item['id'],origin.get('batch_id'),origin.get('attachment_id'),origin.get('page'))
                    sources[key]=dict(row,title=item['title'],revision=item['updated'],url=item['url'],
                        filename=item['filename'],origin=origin,text=field[0].replace(field[1],'〔已隐藏〕'))
            if not found:return None
    if not identity:return None
    try:born=date(int(identity[6:10]),int(identity[10:12]),int(identity[12:14]))
    except ValueError:return None
    if born>date.today() or born.year<1800:return None
    hits=list(sources.values())
    if depends_on_conversation(subject,{p['item_id'] for p in hits},turns,None,None):return None
    hits=hits[:4]
    for hit in hits:
        for data,key in ((hit,'title'),(hit,'filename'),(hit,'url'),(hit['origin'],'name')):
            if key in data:data[key]=re.sub(re.escape(identity),'〔已隐藏〕',data[key],flags=re.I)
    citations=' '.join(f'[{i+1}]' for i in range(len(hits)))
    return f'根据归档资料中与{subject}姓名对应的身份证出生日期字段，推断其生日为公历 {born.year} 年 {born.month} 月 {born.day} 日。{citations}',hits
