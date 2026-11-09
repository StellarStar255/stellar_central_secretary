"""Owned local download routes and bounded, atomic saves for desktop web views."""
import json,os,re,tempfile,urllib.parse,urllib.request
from pathlib import Path

ITEM=r'[a-f0-9]{32}'
DOWNLOAD=re.compile(r'/api/items/('+ITEM+r')(?:(/file)|(/additions/('+ITEM+r')/file)|((?:/additions/('+ITEM+r'))?/attachments/('+ITEM+r')))')

def route(address,url):
    origin=urllib.parse.urlsplit(address);value=urllib.parse.urlsplit(url)
    if (origin.scheme,origin.netloc)!=(value.scheme,value.netloc) or value.query or value.fragment or value.username or value.password:return None
    if value.path=='/api/backup':return {'name':'stellar-knowledge-backup.zip'}
    if value.path=='/api/browser-extension/download':return {'name':'Stellar-Capture-Extension.zip'}
    match=DOWNLOAD.fullmatch(value.path)
    if not match:return None
    ident,original,batch_file,batch,attachment,attachment_batch,key=match.groups()
    if batch_file:return {'name':'additional-materials.stellar.zip'}
    return {'item':ident,'batch':attachment_batch or '', 'attachment':key or 'original'}

def opener(address):
    class LocalOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,request,fp,code,message,headers,url):
            if route(address,url) is None:raise ValueError('下载跳转地址无效，未保存文件')
            return super().redirect_request(request,fp,code,message,headers,url)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),LocalOnly())

def filename(address,url):
    value=route(address,url)
    if value is None:raise ValueError('下载地址无效')
    if 'name' in value:return value['name']
    request=address+'/api/download-info?'+urllib.parse.urlencode({'path':urllib.parse.urlsplit(url).path})
    with opener(address).open(request,timeout=15) as response:
        raw=response.read(4097)
        if len(raw)>4096:raise ValueError('附件下载信息无效')
        file=json.loads(raw)
    name=Path(file['name'].replace('\\','/')).name
    if name in ('','.','..') or any(ord(char)<32 for char in name):raise ValueError('附件文件名无效')
    return name

def save(address,url,destination,progress=None):
    if route(address,url) is None:raise ValueError('下载地址无效')
    destination=Path(destination);temporary=None
    try:
        with opener(address).open(url,timeout=120) as source:
            if source.status!=200:raise ValueError('附件下载未完成')
            length=source.headers.get('Content-Length');total=int(length) if length is not None else None;received=0
            with tempfile.NamedTemporaryFile(prefix='.stellar-download-',suffix='.part',dir=destination.parent,delete=False) as target:
                temporary=Path(target.name)
                while chunk:=source.read(1024*1024):
                    target.write(chunk);received+=len(chunk)
                    if progress:progress(received,total)
                if total is not None and received!=total:raise ValueError('附件下载不完整，原有文件已保留')
                target.flush();os.fsync(target.fileno())
        temporary.replace(destination);temporary=None
        return {'path':str(destination),'bytes':received}
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def info(archive,path):
    from . import additions,bundles
    value=route('http://127.0.0.1','http://127.0.0.1'+path)
    if value is None:raise ValueError('下载地址无效')
    if 'name' in value:return {'name':value['name']}
    item=archive.get(value['item']);batch=value['batch'];key=value['attachment']
    if key=='original':
        if not item['filename']:raise KeyError('没有原文件')
        return {'name':item['filename']}
    if batch:
        if additions.find(item,batch) is None:raise KeyError('追加资料不存在')
    elif not bundles.is_bundle(item['filename']):raise KeyError('组合附件不存在')
    file,_=bundles.member(archive.root/'files'/(batch or item['id']),key)
    return {'name':file['name']}
