"""Resolve short, personal arrangements once, using their archive-local date."""
import re
from datetime import datetime, timedelta

MARKER = '【日期解析】'
TOKEN = re.compile(r'(?<![每上])(?:(本周|这周|下周|下下周|本星期|这星期|下星期|下下星期)([一二三四五六日天])|(?:周|星期|礼拜)([一二三四五六日天])|今天|明天|大后天|后天|昨天|前天)')


def date_summary(summary,context):
    """Display the fixed interpretation once; retain distinct model details."""
    if not summary.strip() or not context.startswith(MARKER) or len(context.split('\n',2))<3:return summary
    resolved=context.split('\n',2)[-1].strip()
    resolved=re.sub(r'^(?:建档|存档|归档|保存|记录|记住)\s*[:：]\s*','',resolved)
    def key(value):return re.sub(r'[\W_]+','',value)
    seen={key(resolved)};parts=[resolved]
    for part in re.split(r'\n\s*\n',summary.strip()):
        part=re.sub(r'^【日期解析】\s*','',part).strip()
        part=re.sub(r'^(?:建档|存档|归档|保存|记录|记住)\s*[:：]\s*','',part)
        normalized=key(part)
        if normalized and normalized not in seen:parts.append(part);seen.add(normalized)
    return '\n\n'.join(parts)


def resolve(text, reference):
    if not text or len(text) > 1000 or re.search(r'每(?:个)?(?:周|星期|礼拜)|每逢|每到|通常|一般|例如|比如|[？?]|[“”「」]|```|\d+月\d+日|\d{4}-\d{2}-\d{2}', text):
        return ''
    # Avoid interpreting quotations, imported articles and timeless descriptions.
    if not re.search(r'\d{1,2}[:：点时]|上午|下午|中午|晚上|早上|复查|开会|预约|出发|面试|就诊|看病|去|见面|提醒', text):
        return ''
    base = datetime.fromisoformat(reference)
    def replace(match):
        word = match.group(); day = match[2] or match[3]
        if day:
            weekday = '一二三四五六日'.index(day.replace('天', '日'))
            if match[1]:
                weeks = 2 if match[1].startswith('下下') else 1 if match[1].startswith('下') else 0
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
    return MARKER + f'\n按原消息本地日期 {base.date().isoformat()}（{base.strftime("%z")}）解析；未指定的周几按最近一个同名日（含当天）。\n' + resolved
