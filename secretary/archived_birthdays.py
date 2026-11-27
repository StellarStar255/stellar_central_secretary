"""Answer simple birthday lookups from matching original notes."""
import json
import re
from datetime import date

from .conversation_context import CONDITION_PREFIX
from .core import terms
from .note_dates import arrangement_text

QUESTION = re.compile(
    r'(?:请问\s*)?([\w·]{1,40}?)\s*(?:的\s*)?(?:生日|出生日期)'
    r'\s*(?:(?:是\s*)?(?:哪天|哪一天|几月几号|几月几日|什么时候)|呢)?[？?]?'
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


def depends_on_conversation(subject, item_ids, turns):
    related = False
    for turn in turns:
        statement = turn['question']
        mentions_subject = subject in statement
        cited = item_ids.intersection(turn['source_ids'])
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
    tokens = list(dict.fromkeys(token for token in terms(subject) if len(token) > 1))
    clauses = [f'"{token}"' for token in tokens]
    search = ' AND '.join(clauses + ['("生日" OR "出生")'])
    record = re.compile(re.escape(subject) + r'\s*(?:的\s*)?(?:生日|出生日期)\s*[是在为]?\s*[:：]?\s*([^\n]{1,64}?)[。！!]?')
    with archive.db() as db:
        db.execute('BEGIN')
        rows = db.execute(
            "SELECT id,kind,title,text,updated,user_context,note,note_images,additions FROM items "
            "WHERE trashed_at='' AND id IN (SELECT DISTINCT item_id FROM search WHERE search MATCH ?) "
            "ORDER BY updated DESC LIMIT 9", (search,)).fetchall()
        if not rows or len(rows) > 8:
            return None
        if depends_on_conversation(subject, {row['id'] for row in rows}, turns):
            return None
        dates = set()
        original_dates = []
        for row in rows:
            if row['kind'] != 'note' or row['user_context'] or row['note']:
                return None
            if row['note_images'] != '[]' or row['additions'] != '[]':
                return None
            fact = record.fullmatch(arrangement_text(row['text']))
            identity = date_identity(fact[1]) if fact else None
            if identity is None:
                return None
            dates.add(identity)
            original_dates.append(fact[1])
        if len(dates) != 1:
            return None
        item = rows[0]
        chunk = db.execute('SELECT * FROM chunks WHERE item_id=? AND position=0 LIMIT 1', (item['id'],)).fetchone()
        if not chunk:
            return None
    source = dict(chunk, title=item['title'], text=item['text'], revision=item['updated'],
                  origin=json.loads(chunk['origin']), url='', filename='')
    return f'{subject}的生日是{original_dates[0]}。[1]', [source]
