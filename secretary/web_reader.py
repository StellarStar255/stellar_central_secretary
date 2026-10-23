"""Task-owned browser capture for public HTTP(S) pages after manual confirmation."""
import ipaddress
import os
import socket
import threading
import time
import uuid
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from . import browser_reader as reader, network
from .capture_browser import create_task_page

PREFIX_ZH='【网页已加载内容归档】'
PREFIX_EN='[Loaded webpage capture]'
_SCRIPT=(Path(__file__).parent/'static/web_extract.js').read_text(encoding='utf-8')
SNAPSHOT_SCRIPT='options=>{'+_SCRIPT+';return extractWebPage(options);}'
FILE_SUFFIXES={'.pdf','.zip','.rar','.7z','.dmg','.exe','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.png','.jpg','.jpeg','.gif','.mp3','.mp4'}


def capture_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('请输入不含账号密码的 http 或 https 网页链接')
    parsed.port  # Validate malformed port syntax without altering query or fragment.
    if parsed.hostname.lower() in ('localhost','localhost.localdomain') or parsed.hostname.lower().endswith('.localhost'):
        raise ValueError('浏览器采集仅支持公开网页地址')
    try:address=ipaddress.ip_address(parsed.hostname)
    except ValueError:pass
    else:
        if not address.is_global:raise ValueError('浏览器采集仅支持公开网页地址')
    if Path(parsed.path).suffix.lower() in FILE_SUFFIXES:
        raise ValueError('文件链接请先下载原文件，再导入知识库')
    return url


_PROXY_CACHE=(0,None)
def browser_proxy():
    """Use a verified local HTTP proxy only, without changing system settings."""
    global _PROXY_CACHE
    if time.monotonic()-_PROXY_CACHE[0]<30:return _PROXY_CACHE[1]
    configured=urllib.request.getproxies()
    candidates=[configured.get('https'),configured.get('http'),*network.running_proxy_candidates()]
    for candidate in dict.fromkeys(filter(None,candidates)):
        try:
            p=urlsplit(candidate)
            if p.scheme!='http' or p.hostname not in ('localhost','127.0.0.1','::1') or p.username or p.password:continue
            if network.http_proxy_works(candidate):
                route='http://'+('['+p.hostname+']' if ':' in p.hostname else p.hostname)+':'+str(p.port or 80)
                _PROXY_CACHE=(time.monotonic(),route);return route
        except ValueError:continue
    _PROXY_CACHE=(time.monotonic(),None);return None


def validate_public_url(url):
    capture_url(url)
    parsed=urlsplit(url)
    answers=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))
    addresses=[ipaddress.ip_address(answer[4][0]) for answer in answers]
    # Some local proxy DNS modes return benchmark-range virtual addresses.
    # Permit these DNS answers only for a domain, via a verified local proxy.
    fake=ipaddress.ip_network('198.18.0.0/15')
    if addresses and all(address.version==4 and address in fake for address in addresses) and browser_proxy():return url
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('浏览器采集仅支持公开网页地址')
    return url


def same_page(actual,target):
    try:
        a,b=urlsplit(actual),urlsplit(target)
        return (a.scheme,a.hostname,a.port,a.path.rstrip('/'))==(b.scheme,b.hostname,b.port,b.path.rstrip('/'))
    except ValueError:return False


def capture_loaded_page(page,target,cancelled,language='zh',timeout=35):
    validate_public_url(page.url)
    if not same_page(page.url,target):raise RuntimeError('请先在浏览器返回目标网页，再确认读取')
    deadline=time.monotonic()+timeout;last=None;stable=0
    while time.monotonic()<deadline:
        if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
        if page.is_closed():raise RuntimeError('任务网页已关闭，请重新打开后再试')
        validate_public_url(page.url)
        if not same_page(page.url,target):raise RuntimeError('目标网页发生跳转，请返回原网页后重新读取')
        result=page.evaluate(SNAPSHOT_SCRIPT,{'language':language,'limit':120000})
        actual=result.get('url',page.url)
        validate_public_url(actual)
        if not same_page(actual,target):raise RuntimeError('目标网页发生跳转，请返回原网页后重新读取')
        if result['login']:raise RuntimeError('页面仍是登录界面，请完成登录并打开目标内容后再确认')
        if result['denied']:raise RuntimeError('网页提示没有访问权限，请确认当前账号有权查看目标内容')
        text=result['text'].strip();stable=stable+1 if text==last and len(text)>=80 and not result['busy'] and result['ready'] else 0;last=text
        if stable>=3:
            if language=='en':
                scope=PREFIX_EN+' Scope: content already loaded when you confirmed. Collapsed, paginated and unloaded content is not included.'
                if result['truncated']:scope+=' Only the first 120,000 characters are included.'
            else:
                scope=PREFIX_ZH+' 采集范围：确认时网页中已加载的可读内容；未展开、分页及尚未加载的内容不包含。'
                if result['truncated']:scope+=' 本次最多保留前 12 万字符。'
            return {'url':target,'title':result['title'] or urlsplit(target).hostname,'text':scope+'\n\n'+text,'web_capture':True,'capture_scope':'loaded_page'}
        if cancelled.wait(.8):raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
    raise RuntimeError('页面未取得稳定的可读正文，请等待加载完成、展开目标内容后重试；文件链接请下载后导入')


def read(url,profile_dir,notify,cancelled,timeout=600,login_complete=None,background=False,close_new_tabs=False,language='zh'):
    from playwright.sync_api import sync_playwright
    target=validate_public_url(url);profile=Path(profile_dir).resolve();profile.mkdir(parents=True,exist_ok=True)
    if os.name!='nt':profile.chmod(0o700)
    notify('opening_browser','正在打开浏览器以读取网页')
    marker='about:blank#stellar-web-capture-'+uuid.uuid4().hex
    session=reader.start_or_reuse_browser(marker,profile,cancelled,background=background,proxy=browser_proxy())
    confirmed=login_complete if login_complete is not None else threading.Event()
    page=None;completed=False
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(session['websocket'],timeout=15000)
        try:
            page=create_task_page(browser,session,background)
            # Do not route/intercept page requests. The user may spend minutes
            # signing in while this thread waits, without pumping Playwright's
            # event loop. Routing would pause ordinary fetch/iframe requests.
            page.goto(target,wait_until='domcontentloaded',timeout=45000)
            for attempt in range(3):
                if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
                confirmed.clear();page.bring_to_front()
                notify('waiting_login','请在浏览器完成登录，打开并展开要保存的内容，再点击「页面已打开，开始读取」')
                reader.wait_for_manual_login(session.get('process') or SimpleNamespace(poll=lambda:None),confirmed,cancelled,timeout)
                if not same_page(page.url,target):page.goto(target,wait_until='domcontentloaded',timeout=45000)
                notify('reading','正在采集网页中已加载的正文')
                try:result=capture_loaded_page(page,target,cancelled,language)
                except RuntimeError as exc:
                    if isinstance(exc,reader.CaptureCancelled):raise
                    if '登录界面' in str(exc) and attempt<2:continue
                    raise
                completed=True;session['confirmed']=True;reader.save_session(profile,session);return result
        finally:
            if page is not None:
                try:
                    if completed and close_new_tabs and not page.is_closed():page.close()
                except Exception:pass
            # Existing tabs and the browser process are never closed.
