"""Answer a single explicit field from a short original note."""
import json
import re
from .core import terms
from .conversation_context import CONDITION_PREFIX


# Bind the entire subject in the question to the subject in the original.
# Constrain each value to the type of answer requested.
MONEY = r'(?:人民币\s*)?[￥¥]?\s*\d+(?:\.\d{1,2})?\s*(?:元|块钱)(?:/[天月年人次])?'
DURATION = r'\d+(?:\.\d+)?\s*(?:个工作日|个自然日|工作日|天|小时|分钟|个月|年)'
FIELDS = (
    (r'(?:是|为)?多少钱', r'(?:是|为|定为|[：:])', MONEY),
    (r'(?:是|为)?多久', r'(?:是|为|需要|[：:])', DURATION),
    (r'(?:放在|位于|在)(?:哪里|哪儿)', r'(?:放在|放置在|存放在|位于|在)', r'[^。！？？?；;，,：:\n]{2,50}'),
)


def lookup(archive, question, turns):
    value=question.strip().rstrip('？?').strip().removeprefix('请问').strip()
    for ending, relation, field_value in FIELDS:
        match=re.fullmatch(r'([\w· -]{3,48}?)'+ending,value)
        if match:break
    else:return None
    subject=match[1].strip()
    if re.search(r'它|这个|那个|上述|刚才|上次|之前|目前|现在|最新|如果|假如|或者|还是|分别|对比|你觉得',subject):
        return None
    words=list(dict.fromkeys(terms(subject)))
    if not words:return None
    query=' AND '.join('"'+w+'"' for w in words)
    field=re.compile(re.escape(subject)+r'\s*'+relation+r'\s*('+field_value+r')[。.]?')
    with archive.db() as db:
        db.execute('BEGIN')
        rows=db.execute("""SELECT i.id,i.title,i.text,i.updated,i.kind,i.note,i.note_images,i.additions,i.user_context
            FROM items i WHERE i.trashed_at='' AND i.id IN (SELECT item_id FROM search WHERE search MATCH ?)
            LIMIT 9""",(query,)).fetchall()
        if not rows or len(rows)>8:return None
        ids={row['id'] for row in rows}
        for turn in turns:
            statement=turn['question']
            if subject in statement:return None
            if turn['source_ids'] and ids.isdisjoint(turn['source_ids']):continue
            if statement.startswith(CONDITION_PREFIX) or re.search(r'更正|纠正|改为|改成|为准|说错|不是|记错',statement):
                return None
        answers=set()
        for row in rows:
            if row['kind']!='note' or row['note'] or row['user_context'] or row['note_images']!='[]' or row['additions']!='[]':
                return None
            if re.search(r'过期|作废|旧版|已取消|更正|草稿|示例|历史价格',row['title']):return None
            found=field.fullmatch(row['text'].strip())
            if not found or re.search(r'不详|不在|未知|待定|可能|如果|原来|以前|曾经|尚未|改为|[\[\]<>]',found[1]):
                return None
            answers.add(found[1])
        if len(answers)!=1:return None
        row=rows[0]
        chunk=db.execute('SELECT * FROM chunks WHERE item_id=? AND position=0',(row['id'],)).fetchone()
        if not chunk:return None
    source=dict(chunk,title=row['title'],text=row['text'],origin=json.loads(chunk['origin']),revision=row['updated'],url='',filename='')
    return row['text'].strip()+' [1]',[source]
