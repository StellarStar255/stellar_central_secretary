"""Compare two explicitly priced and timed plans using current original notes."""
import json
import re
from decimal import Decimal

from .core import terms
from .conversation_context import CONDITION_PREFIX

PRICE = r'[0-9]{1,10}(?:\.[0-9]{1,2})?'
DAYS = r'(?:[0-9]{1,3}|[一二两三四五六七八九十])'
NOTE = re.compile(
    rf'(?P<name>(?:[\w·-]{{1,20}}?方案|方案[甲乙丙丁AB]))(?:的|[:：]\s*)(?P<topic>[\u3400-\u9fff]{{1,12}}?)(?:费用|总价|报价)'
    rf'(?:为|是|[:：])?\s*(?P<cost>{PRICE})\s*元[，,。；;\s]+(?:现场)?工期(?:为|是|[:：])?\s*(?P<days>{DAYS})天[。.]?'
)
ASK = re.compile(
    rf'(?:请)?(?:比较|对比)(?:两|2)(?:种|个|套)(?P<topic>[\u3400-\u9fff]{{1,12}}?)方案[，,：:\s]+'
    rf'预算(?:(?:不超过|最多|上限为?)\s*(?P<cost>{PRICE})\s*元|(?P<within>{PRICE})\s*元以内)[，,\s]*(?:且|并且|和)?'
    rf'(?:只能用|最多用|工期不超过|工期最多|最多只有)\s*(?P<days>{DAYS})天[，,\s]*'
    r'(?:哪个|哪种|哪些)(?:方案)?(?:可行|能满足|符合条件)[？?]*'
)
CHANGE = re.compile(rf'(?:那|如果)?(?:预算(?:上限)?(?:改成|改为|换成)\s*(?P<cost>{PRICE})\s*元|工期(?:上限)?(?:改成|改为|换成)\s*(?P<days>{DAYS})天)(?:呢)?[？?]*')


def days(value):
    if value.isdecimal():return int(value)
    return '一二三四五六七八九十'.index(value.replace('两','二'))+1


def lookup(archive, question, turns):
    value=question.strip()
    ask=ASK.fullmatch(value)
    changes=[]
    reference_ids=set()
    if not ask:
        change=CHANGE.fullmatch(value)
        if not change:return None
        changes.append(change)
        for turn in reversed(turns):
            cited=set(turn['source_ids'])
            if len(cited)!=2 or reference_ids and cited!=reference_ids:return None
            reference_ids=cited
            earlier=turn['question'].strip()
            ask=ASK.fullmatch(earlier)
            if ask:break
            change=CHANGE.fullmatch(earlier)
            if not change:return None
            changes.append(change)
        if not ask:return None
    topic=ask['topic']
    budget=Decimal(ask['cost'] or ask['within'])
    deadline=days(ask['days'])
    for change in reversed(changes):
        if change['cost']:budget=Decimal(change['cost'])
        else:deadline=days(change['days'])
    search=' AND '.join('"'+word+'"' for word in dict.fromkeys(terms(topic)+['方案']))
    with archive.db() as db:
        db.execute('BEGIN')
        rows=db.execute("""SELECT id,title,text,updated,kind,note,user_context,note_images,additions
            FROM items WHERE trashed_at='' AND id IN (SELECT item_id FROM search WHERE search MATCH ?)
            ORDER BY created,id LIMIT 3""",(search,)).fetchall()
        if len(rows)!=2:return None
        ids={row['id'] for row in rows}
        if reference_ids and ids!=reference_ids:return None
        plans=[]
        sources=[]
        for row in rows:
            if (row['kind']!='note' or row['note'] or row['user_context'] or row['note_images']!='[]'
                    or row['additions']!='[]' or re.search(r'旧版|历史|草稿|作废|过期|取消|示例',row['title'])):return None
            plan=NOTE.fullmatch(row['text'].strip())
            if not plan or plan['topic']!=topic:return None
            plans.append(plan)
            chunk=db.execute('SELECT * FROM chunks WHERE item_id=? AND position=0',(row['id'],)).fetchone()
            if not chunk:return None
            sources.append(dict(chunk,title=row['title'],text=row['text'],revision=row['updated'],
                                origin=json.loads(chunk['origin']),filename='',url=''))
        names=[plan['name'] for plan in plans]
        if names[0]==names[1]:return None
        for turn in turns:
            statement=turn['question']
            if ASK.fullmatch(statement.strip()) or CHANGE.fullmatch(statement.strip()):continue
            if (not turn['source_ids'] or ids.intersection(turn['source_ids'])) and re.search(r'更正|有误|改为|改成|作废|为准',statement):return None
            if statement.startswith(CONDITION_PREFIX) or any(name in statement for name in names) or topic in statement:
                return None
        # Catch a separate revision that names a plan but omits the common topic.
        for name in names:
            named_query=' AND '.join('"'+word+'"' for word in dict.fromkeys(terms(name)))
            if db.execute("""SELECT 1 FROM items WHERE trashed_at='' AND id NOT IN (?,?)
                    AND (title IN (?,?) OR id IN (SELECT item_id FROM search WHERE search MATCH ?)) LIMIT 1""",
                    (*ids,rows[0]['title'],rows[1]['title'],named_query)).fetchone():return None
    eligible=[]
    details=[]
    for index,plan in enumerate(plans,1):
        reasons=[]
        if Decimal(plan['cost'])>budget:reasons.append('超出预算')
        if days(plan['days'])>deadline:reasons.append('超出工期')
        if not reasons:eligible.append(plan['name'])
        verdict='、'.join(reasons) if reasons else '满足两项条件'
        details.append(f"{plan['name']}费用 {plan['cost']} 元，工期{days(plan['days'])}天，{verdict}。[{index}]")
    conclusion='、'.join(eligible)+'可行' if eligible else '两个方案都不满足条件'
    return f'按预算上限 {budget} 元、工期上限 {deadline} 天，{conclusion}。\n\n'+'\n'.join(details),sources
