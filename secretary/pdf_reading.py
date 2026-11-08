"""Owned PDF page selections, retained per source digest and included in exports."""
import hashlib,json,re
from pathlib import Path
from . import additions,bundles,pdf_preview

def key(batch_id='',attachment_id=''):return (batch_id or 'original')+':'+(attachment_id or 'original')
def records(value):
    if isinstance(value,str):value=json.loads(value)
    if not isinstance(value,dict) or len(value)>200:raise ValueError('PDF 选读记录无效')
    count=0
    for token,entry in value.items():
        if not re.fullmatch(r'(?:original|[a-f0-9]{32}):(?:original|[a-f0-9]{32})',token) or not isinstance(entry,dict) or not re.fullmatch('[a-f0-9]{64}',str(entry.get('digest',''))):raise ValueError('PDF 选读记录无效')
        if not isinstance(entry.get('name'),str) or len(entry['name'])>300 or type(entry.get('total')) is not int or entry['total']<1 or not isinstance(entry.get('pages'),dict):raise ValueError('PDF 选读记录无效')
        covered=entry.get('summary_pages',{})
        if not isinstance(covered,dict) or len(covered)>200 or any(not re.fullmatch('[1-9][0-9]*',str(n)) or not 1<=int(n)<=entry['total'] or not re.fullmatch('[a-f0-9]{64}',str(h)) for n,h in covered.items()):raise ValueError('PDF 摘要范围记录无效')
        for number,page in entry['pages'].items():
            if not re.fullmatch('[1-9][0-9]*',str(number)) or not 1<=int(number)<=entry['total'] or not isinstance(page,dict) or not isinstance(page.get('text'),str) or len(page['text'])>8000 or page.get('method') not in ('text','ocr'):raise ValueError('PDF 页面记录无效')
            count+=1
    if count>200:raise ValueError('每份档案最多保存 200 页选读文字，请另建档案')
    return value

def owned(archive,item_id,batch_id='',attachment_id=''):
    item=archive.get(item_id);path=archive.root/'files'/(batch_id or item_id)
    if batch_id and additions.find(item,batch_id) is None:raise KeyError('追加资料不存在')
    if attachment_id:
        if not batch_id and not bundles.is_bundle(item['filename']):raise KeyError('附件不存在')
        file,source=bundles.member(path,attachment_id)
        digest=file.get('sha256')
        if not digest:
            with source.open() as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        name=file['name'];initial=file['text']
    else:name=item['filename'];source=path;digest=item['digest'];initial=item['text']
    if not name.lower().endswith('.pdf'):raise ValueError('请选择 PDF 附件')
    return item,source,name,digest,initial

def read(archive,item_id,batch_id,attachment_id,body,cancel=None,progress=None):
    item,source,name,digest,initial=owned(archive,item_id,batch_id,attachment_id)
    result=pdf_preview.inspect(source,body.get('start',1),body.get('end',5),body.get('ocr') is True,cancel,progress)
    with archive.lock:
        current,_,_,now_digest,_=owned(archive,item_id,batch_id,attachment_id)
        if digest!=now_digest:raise ValueError('附件已更新，请重新读取')
        values=records(current.get('pdf_reads',{}));token=key(batch_id,attachment_id);entry=values.get(token)
        if not entry or entry['digest']!=digest:entry={'digest':digest,'name':name,'total':result['total'],'pages':{}}
        if not entry['pages']:
            for match in re.finditer(r'^\[第 (\d+) 页\]\n(.*?)(?=^\[第 \d+ 页\]|\Z)',initial,re.M|re.S):
                number=int(match[1])
                if number<=5:entry['pages'][str(number)]={'text':match[2].strip()[:8000],'method':'text'}
        for page in result['pages']:entry['pages'][str(page['page'])]={'text':page['text'],'method':page['method']}
        values[token]=entry;records(values)
        if cancel and cancel():raise ValueError('页面读取已停止')
        archive.update(item_id,pdf_reads=values,error='PDF 读取范围已更新，已有摘要可能过期；可重新整理。')
    return {**result,'read_pages':sorted(map(int,entry['pages'])),'name':name}

def text(entry):
    numbers=sorted(map(int,entry['pages']))
    scope='【PDF 选读：'+entry['name']+'；已读取第 '+','.join(map(str,numbers))+' 页 / 共 '+str(entry['total'])+' 页】'
    return scope+'\n'+'\n\n'.join(f'[第 {number} 页]'+('【本机 OCR，请核对原件】' if entry['pages'][str(number)]['method']=='ocr' else '')+'\n'+entry['pages'][str(number)]['text'] for number in numbers)
def index_text(value):return '\n\n'.join(text(entry) for entry in records(value).values())


def info(archive,item_id,batch_id='',attachment_id=''):
    item,source,name,digest,initial=owned(archive,item_id,batch_id,attachment_id)
    entry=item.get('pdf_reads',{}).get(key(batch_id,attachment_id),{})
    if entry.get('digest')!=digest:entry={}
    total=entry.get('total') or pdf_preview.info(source)
    pages=entry.get('pages',{}).copy()
    if not pages:
        for match in re.finditer(r'^\[第 (\d+) 页\]\n(.*?)(?=^\[第 \d+ 页\]|\Z)',initial,re.M|re.S):
            number=int(match[1])
            if number<=5:pages[str(number)]={'text':match[2].strip()[:8000],'method':'text'}
    return {'name':name,'total':total,'pages':[{'page':int(number),**value} for number,value in pages.items()],'read_pages':sorted(map(int,pages))}


def page_hash(page):return hashlib.sha256((page['method']+'\n'+page['text']).encode()).hexdigest()

def summary_material(archive,item,new_only=False,budget=100000):
    parts=[];used={};labels=[]
    for token,entry in item.get('pdf_reads',{}).items():
        batch,attachment=token.split(':')
        try:
            _,_,_,digest,_=owned(archive,item['id'],'' if batch=='original' else batch,'' if attachment=='original' else attachment)
        except (KeyError,ValueError):continue
        if digest!=entry['digest']:continue
        pages={}
        for number in sorted(entry['pages'],key=int):
            page=entry['pages'][number]
            if not page['text'].strip() or new_only and entry.get('summary_pages',{}).get(number)==page_hash(page):continue
            value=f'[第 {number} 页]\n'+page['text']
            if len(value)>budget:continue
            budget-=len(value);pages[number]=page;parts.append(entry['name']+'\n'+value)
        if pages:
            used[token]={number:page_hash(page) for number,page in pages.items()}
            labels.append(entry['name']+'：'+page_ranges(map(int,pages))+' / '+str(entry['total']))
    scope='【PDF 摘要覆盖页码】\n'+'\n'.join(labels)+'\n仅覆盖列出的已提取文字；未列出页面不作推断。' if parts else ''
    return '\n\n'.join(parts),scope,used

def mark_summary(item,used,merge=False):
    values=json.loads(json.dumps(item.get('pdf_reads',{})))
    for token,entry in values.items():entry['summary_pages']={**(entry.get('summary_pages',{}) if merge else {}),**used.get(token,{})}
    return values

def page_ranges(numbers):
    values=sorted(set(numbers));groups=[]
    for number in values:
        if groups and number==groups[-1][-1]+1:groups[-1].append(number)
        else:groups.append([number])
    return ', '.join(str(group[0]) if len(group)==1 else str(group[0])+'–'+str(group[-1]) for group in groups)

def coverage(item):
    result=[]
    for token,entry in item.get('pdf_reads',{}).items():
        covered=[int(n) for n,p in entry['pages'].items() if entry.get('summary_pages',{}).get(n)==page_hash(p)]
        pending=[int(n) for n,p in entry['pages'].items() if p['text'].strip() and int(n) not in covered]
        result.append({'key':token,'name':entry['name'],'total':entry['total'],'read':page_ranges(map(int,entry['pages'])),'summarized':page_ranges(covered),'pending':page_ranges(pending),'known':bool(entry.get('summary_pages'))})
    return result
