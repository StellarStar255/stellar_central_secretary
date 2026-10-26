"""Bounded grouped-link fetching. Login-only URLs remain explicit unread sources."""
import re
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

def extract(text):
    return list(dict.fromkeys(re.findall(r'https?://[^\s<>"，。！？；）)]+',text)))

def records(values):
    if not isinstance(values,list) or len(values)>20:raise ValueError('每组最多包含 20 个链接')
    seen=set()
    for value in values:
        if not isinstance(value,dict) or any(not isinstance(value.get(key),str) for key in ('url','text','warning','state')):raise ValueError('组合链接字段无效')
        url=value['url'];parsed=urlsplit(url)
        if len(url)>8192 or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or url in seen:raise ValueError('组合链接地址无效或重复')
        if len(value['text'])>50000 or len(value['warning'])>1600 or value['state'] not in ('pending','read','unread'):raise ValueError('组合链接内容无效')
        seen.add(url)
    if sum(len(value['text']) for value in values)>500000:raise ValueError('组合链接文字超过概览上限')
    return values

def prepare(urls):
    if not isinstance(urls,list) or any(not isinstance(url,str) for url in urls):raise ValueError('组合链接格式无效')
    return records([{'url':url,'text':'','warning':'','state':'pending'} for url in dict.fromkeys(urls)])

def source(values):
    return '\n\n'.join('【来源链接 '+str(index)+' · '+('已读取' if value['state']=='read' else '尚未读取')+'】\n'+value['url']+'\n'+(value['text'] or '未取得正文，不能推断页面内容。')+('\n'+value['warning'] if value['warning'] else '') for index,value in enumerate(values,1))

def read(values,fetch,stopping):
    def one(value):
        result=dict(value)
        if stopping():return result
        try:
            text,warning=fetch(value['url'])
            if len(text)<3000 and re.search(r'(?:(?:sign|log) in to (?:continue|view|access)|请先登录|登录后(?:查看|访问)|需要登录)',text[:400],re.I):
                text='';warning='页面要求登录，链接已保留，可将页面正文追加到此档案。'
            if text.strip():result.update(text=text[:50000],state='read',warning=(warning+' 正文仅保留前 5 万字符用于概览。' if len(text)>50000 else warning)[:1600])
            else:result.update(state='read' if value['text'] else 'unread',warning=(warning or '未取得网页正文，可打开原链接后将内容追加到此档案。')[:1600])
        except Exception as error:result.update(state='read' if value['text'] else 'unread',warning=('读取失败：'+str(error))[:1600])
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:result=list(pool.map(one,values))
    remaining=500000
    for value in result:
        if len(value['text'])>remaining:value['text']=value['text'][:remaining];value['warning']=(value['warning']+' 本组正文已达到 50 万字符的概览上限。')[:1600]
        remaining-=len(value['text'])
    return records(result)
