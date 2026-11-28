"""Resolve short, personal arrangements once, using their archive-local date."""
import hashlib
import re
from datetime import datetime, timedelta

MARKER = '【日期解析】'
WEEKDAY = r'(?:(?P<week>下下|下|本|这)个?)?(?:周|星期|礼拜)(?P<day>[一二三四五六日天])'
RELATIVE_DAY = r'今天|明天|大后天|后天|昨天|前天'
TOKEN = re.compile(r'(?<![每上下本这个大])(?:'+WEEKDAY+'|'+RELATIVE_DAY+')')
DATE_START = '(?:'+WEEKDAY+'|'+RELATIVE_DAY+r'|\d{4}年\d+月\d+日|\d{4}-\d{2}-\d{2}|\d+月\d+日)'

# A day can be definite even when an arrangement has no clock time.
SOCIAL_EVENT = r'吃饭|聚餐|聚会|聚一聚|请客|做客|做东|赴约|看电影|接机|送机|生日会'
def dated_digest(text,resolved):
    return hashlib.sha256(('dated-note\0'+text+'\0'+resolved).encode()).hexdigest()

def social_arrangement(text):
    return bool(re.search(SOCIAL_EVENT,text))

def arrangement_text(value):
    value=re.sub(r'^(?:建档|存档|归档|保存|记录|记住)\s*[:：]\s*','',value.strip())
    # Only the speaker immediately before a date is implicit. Never remove
    # 我老婆/我们/他/她, which can identify a different person or group.
    return re.sub(r'^我\s*(?='+DATE_START+')','',value)


def date_summary(summary,context):
    """Display the fixed interpretation once; retain distinct model details."""
    if not summary.strip() or not context.startswith(MARKER) or len(context.split('\n',2))<3:return summary
    resolved=context.split('\n',2)[-1].strip()
    resolved=arrangement_text(resolved)
    def key(value):return re.sub(r'[\W_]+','',value)
    seen={key(resolved)};parts=[resolved]
    for part in re.split(r'\n\s*\n',summary.strip()):
        part=re.sub(r'^【日期解析】\s*','',part).strip()
        part=arrangement_text(part)
        normalized=key(part)
        if normalized and normalized not in seen:parts.append(part);seen.add(normalized)
    return '\n\n'.join(parts)


def resolve(text, reference):
    if not text or len(text) > 1000 or re.search(r'每(?:个)?(?:周|星期|礼拜)|每逢|每到|通常|一般|例如|比如|如果|假如|要不要|能不能|要是|是不是|是否|怎么|为什么|吗[。！!]?$|[？?]|[“”「」]|```|\d+月\d+日|\d{4}-\d{2}-\d{2}', text):
        return ''
    # Avoid interpreting quotations, imported articles and timeless descriptions.
    if not social_arrangement(text) and not re.search(r'\d{1,2}[:：点时]|上午|下午|中午|晚上|早上|复查|开会|预约|出发|面试|就诊|看病|去|见面|提醒', text):
        return ''
    base = datetime.fromisoformat(reference)
    def replace(match):
        word = match.group(); day = match['day']
        if day:
            weekday = '一二三四五六日'.index(day.replace('天', '日'))
            if match['week']:
                weeks = 2 if match['week']=='下下' else 1 if match['week']=='下' else 0
                delta = weekday - base.weekday() + 7 * weeks
            else:
                delta = (weekday - base.weekday()) % 7
        else:
            delta = {'今天':0,'明天':1,'后天':2,'大后天':3,'昨天':-1,'前天':-2}[word]
        date = base.date() + timedelta(days=delta)
        return f'{date.year}年{date.month}月{date.day}日（周{"一二三四五六日"[date.weekday()]}）'
    resolved = TOKEN.sub(replace, text)
    if resolved == text:
        return ''
    resolved=re.sub(r'(?m)^我(?=\d{4}年\d+月\d+日)','',resolved)
    return MARKER + f'\n按原消息本地日期 {base.date().isoformat()}（{base.strftime("%z")}）解析；未指定的周几按最近一个同名日（含当天）。\n' + resolved
