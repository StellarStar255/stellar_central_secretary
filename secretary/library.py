"""Library result ranking, filters and bounded result pages."""
from datetime import datetime,timedelta,timezone

SORTS=('', 'relevance','created','updated','viewed')
STATES=('', 'ready','pending','active','error','needs_content','saved')

def rank(item,words):
    title=item['title'].casefold();tags=' '.join(item['tags']).casefold()
    return (100 if words and ' '.join(words) in title else 0)+sum(20*(word in title)+10*(word in tags)+4*(word in item.get('filename','').casefold())+2*(word in item['summary'].casefold()) for word in words)

def query(archive,q='',category='',kind='',state='',days='',sort='',offset=0,limit=100,active_ids=()):
    if state not in STATES or sort not in SORTS or str(days) not in ('','0','7','30','90'):raise ValueError('无效的知识库筛选选项')
    try:offset=int(offset);limit=int(limit)
    except (ValueError,TypeError):raise ValueError('无效的分页参数') from None
    if offset<0 or not 1<=limit<=100:raise ValueError('无效的分页参数')
    items=archive.list(q=q,category=category,kind=kind);cutoff=(datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat() if days and int(days) else ''
    if cutoff:items=[item for item in items if item['created']>=cutoff]
    active=set(active_ids)
    if state=='active':items=[item for item in items if item['id'] in active or item['state'] in ('processing','queued_capture','opening_browser','waiting_login','confirming_login','reading','waiting_browser_close')]
    elif state=='pending':items=[item for item in items if item['state'] in ('pending','saved') and item['id'] not in active]
    elif state:items=[item for item in items if item['state']==state]
    if sort in ('updated','viewed'):items.sort(key=lambda item:(item['updated'] if sort=='updated' else item['last_viewed'],item['created']),reverse=True)
    elif q.strip() and sort in ('','relevance'):items.sort(key=lambda item:rank(item,list(dict.fromkeys(q.casefold().split()))),reverse=True)
    return {'items':items[offset:offset+limit],'total':len(items),'offset':offset,'limit':limit}
