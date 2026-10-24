"""Task-owned HTTP(S) browser capture after manual confirmation."""
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
    try:literal=ipaddress.ip_address(parsed.hostname)
    except ValueError:literal=None
    if is_loopback_url(url) or literal is not None and not literal.is_global:
        raise ValueError('浏览器采集仅支持公开网页地址')
    answers=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))
    addresses=[ipaddress.ip_address(answer[4][0]) for answer in answers]
    # Some local proxy DNS modes return benchmark-range virtual addresses.
    # Permit these DNS answers only for a domain, via a verified local proxy.
    fake=ipaddress.ip_network('198.18.0.0/15')
    if addresses and all(address.version==4 and address in fake for address in addresses) and browser_proxy():return url
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('浏览器采集仅支持公开网页地址')
    return url


def is_loopback_url(url):
    host=(urlsplit(url).hostname or '').lower().rstrip('.')
    if host in ('localhost','localhost.localdomain') or host.endswith('.localhost'):return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False


def validate_browser_url(url,target=None):
    """Local reading requires an explicit loopback target and its exact origin.

    Server-side fetching stays public-only. Public pages cannot opt local frames
    or redirects into this exception, and no other local ports are scanned.
    """
    capture_url(url)
    target=target or url
    if not is_loopback_url(target):return validate_public_url(url)
    capture_url(target)
    origin=lambda value:(value.scheme,value.hostname,value.port or (443 if value.scheme=='https' else 80))
    if not is_loopback_url(url) or origin(urlsplit(url))!=origin(urlsplit(target)):
        raise ValueError('本地网页读取仅限你提交的原始地址，请返回原页面后重试')
    parsed=urlsplit(url)
    answers=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))
    if not answers or any(not ipaddress.ip_address(answer[4][0]).is_loopback for answer in answers):
        raise ValueError('本地网页地址必须指向本机回环地址')
    return url


def same_page(actual,target):
    try:
        a,b=urlsplit(actual),urlsplit(target)
        return (a.scheme,a.hostname,a.port,a.path.rstrip('/'))==(b.scheme,b.hostname,b.port,b.path.rstrip('/'))
    except ValueError:return False


def frame_allowed(url,parent_url):
    """Read only visible same-origin frames or Feishu/Lark's document family."""
    if url in ('about:blank','about:srcdoc'):return True
    try:
        frame,parent=urlsplit(url),urlsplit(parent_url)
        if frame.scheme not in ('http','https') or frame.username or frame.password:return False
        import re
        if re.search(r'(?:^|[./_-])(?:login|signin|passport|accounts?|captcha|verify)(?:[./_-]|$)',(frame.hostname or '')+frame.path,re.I):return False
        origin=lambda parsed:(parsed.scheme,parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))
        if origin(frame)==origin(parent):return True
        family=lambda host:any(host==domain or host.endswith('.'+domain) for domain in ('feishu.cn','feishu.link','larksuite.com','larkoffice.com'))
        return family(frame.hostname or '') and family(parent.hostname or '')
    except ValueError:return False


FRAME_VISIBILITY="""el=>{for(let n=el;n;n=n.parentElement||n.getRootNode()?.host){const s=getComputedStyle(n);if(n.hidden||n.getAttribute('aria-hidden')==='true'||s.display==='none'||['hidden','collapse'].includes(s.visibility)||s.opacity==='0')return false}const r=el.getBoundingClientRect();return r.width>=80&&r.height>=40}"""


def snapshot_page(page,language,target=None):
    result=dict(page.evaluate(SNAPSHOT_SCRIPT,{'language':language,'limit':120000}))
    actual=result.get('url',page.url)
    validate_browser_url(actual,target or page.url)
    if not same_page(actual,page.url):raise RuntimeError('目标网页发生跳转，请返回原网页后重新读取')
    texts=[result.get('text','')];readable=result.get('readable_characters',len(texts[0]));remaining=120000-len(texts[0]);captured=0
    frames=getattr(page,'frames',[])
    if not isinstance(frames,list):frames=[]
    for frame in frames[1:21]:
        if captured>=4 or remaining<200:break
        try:
            if not frame_allowed(frame.url,actual):continue
            if not frame.url.startswith('about:'):validate_browser_url(frame.url,actual)
            ancestor=frame;visible=True
            while ancestor.parent_frame is not None:
                if not ancestor.frame_element().evaluate(FRAME_VISIBILITY):visible=False;break
                ancestor=ancestor.parent_frame
            if not visible:continue
            child=frame.evaluate(SNAPSHOT_SCRIPT,{'language':language,'limit':min(40000,remaining)})
            if not frame_allowed(child.get('url',frame.url),actual):continue
            if not child.get('url',frame.url).startswith('about:'):validate_browser_url(child.get('url',frame.url),actual)
            text=child.get('text','').strip()
            if child.get('login') or child.get('denied') or len(text)<40 or text in texts:continue
            captured+=1;label=f'[Embedded content {captured}]' if language=='en' else f'【可见嵌入内容 {captured}】'
            texts.append(label+'\n'+text);readable+=child.get('readable_characters',len(text));remaining-=len(text)
            result['document']=result.get('document',False) or child.get('document',False)
            result['truncated']=result.get('truncated',False) or child.get('truncated',False)
        except reader.CaptureCancelled:raise
        except Exception:continue  # Detached, hidden, unrelated or inaccessible frames are skipped.
    result['text']='\n\n'.join(texts)[:120000];result['readable_characters']=readable;result['captured_frames']=captured
    if captured and readable>=80:result['busy']=False
    return result


def nearly_same_text(previous,current):
    if previous is None:return False
    if previous==current:return True
    size=max(len(previous),len(current))
    if size<80 or abs(len(previous)-len(current))>size*.03:return False
    prefix=0
    for left,right in zip(previous,current):
        if left!=right:break
        prefix+=1
    suffix=0
    for left,right in zip(previous[prefix:][::-1],current[prefix:][::-1]):
        if left!=right:break
        suffix+=1
    return (prefix+suffix)/size>=.97


def open_capture_page(page,target,cancelled,language='zh'):
    """Wait for navigation commit, not a DOM event a SPA can supersede.

    Observe only main-document response metadata. Never intercept requests or
    treat an aborted download, empty response or browser error as captured text.
    """
    from playwright.sync_api import Error,TimeoutError
    latest={};downloads=[];english=language=='en'
    def response_seen(response):
        try:
            if response.request.is_navigation_request() and response.request.frame==page.main_frame:
                latest.update(status=response.status,attachment=response.headers.get('content-disposition','').lower().startswith('attachment'))
        except Exception:pass
    def download_seen(download):
        downloads.append(True)
        try:download.cancel()
        except Exception:pass
    page.on('response',response_seen);page.on('download',download_seen)
    try:
        for attempt in range(2):
            if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
            latest.clear()
            try:
                response=page.goto(target,wait_until='commit',timeout=45000)
                if response is not None:response_seen(response)
                error=None
            except Error as exc:error=exc
            if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
            if page.is_closed():raise RuntimeError('任务网页已关闭，请重新打开后再试')
            status=latest.get('status',0)
            if downloads or latest.get('attachment') or error and 'Download is starting' in str(error):
                raise RuntimeError('The address returned a download instead of a webpage. Download and import the file, or submit the viewer page URL.' if english else '这个地址返回了下载文件，而不是网页。请下载后导入原文件，或提交实际查看器页面的链接。')
            if status>=400:
                raise RuntimeError(('The webpage service returned HTTP ' if english else '网页服务返回 HTTP ')+str(status)+(' . Check the service, proxy and sign-in, then retry.' if english else '，请检查服务、端口转发及登录状态后重试。'))
            if error is None and status not in (204,205):return
            interrupted=error is None or isinstance(error,TimeoutError) or 'ERR_ABORTED' in str(error)
            if interrupted and status not in (204,205) and same_page(page.url,target):
                # A committed document may have superseded the original DOM
                # event. Manual confirmation and extraction still validate it.
                return
            if interrupted and attempt==0:
                page.wait_for_timeout(600);continue
            if status in (204,205):
                raise RuntimeError(('The proxy returned an empty HTTP response (' if english else '代理地址返回空响应（HTTP ')+str(status)+('), with no webpage to read. Check that the forwarded port serves the viewer, then retry.' if english else '），没有可读取的网页。请确认端口转发指向已启动的查看器网页服务后重试。'))
            if interrupted:
                raise RuntimeError('Browser navigation was interrupted. Check the local service and port forwarding, or capture the working page with the browser extension.' if english else '浏览器打开网页被中断。请检查本地服务与端口转发，或在能正常显示内容的常用浏览器中使用采集扩展。')
            if error and 'ERR_CONNECTION_REFUSED' in str(error):
                raise RuntimeError('Cannot connect to the webpage service. Start the service and port forwarding on this computer, then retry.' if english else '无法连接网页服务。请在本机启动对应服务与端口转发，再重新读取。')
            raise error
    finally:
        page.remove_listener('response',response_seen);page.remove_listener('download',download_seen)


def capture_loaded_page(page,target,cancelled,language='zh',timeout=35):
    validate_browser_url(page.url,target)
    if not same_page(page.url,target):raise RuntimeError('请先在浏览器返回目标网页，再确认读取')
    deadline=time.monotonic()+timeout;last=None;stable=0;result={}
    while time.monotonic()<deadline:
        if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
        if page.is_closed():raise RuntimeError('任务网页已关闭，请重新打开后再试')
        validate_browser_url(page.url,target)
        if not same_page(page.url,target):raise RuntimeError('目标网页发生跳转，请返回原网页后重新读取')
        result=snapshot_page(page,language,target)
        actual=result.get('url',page.url)
        validate_browser_url(actual,target)
        if not same_page(actual,target):raise RuntimeError('目标网页发生跳转，请返回原网页后重新读取')
        if result['login']:raise RuntimeError('页面仍是登录界面，请完成登录并打开目标内容后再确认')
        if result['denied']:raise RuntimeError('网页提示没有访问权限，请确认当前账号有权查看目标内容')
        text=result['text'].strip();minimum=40 if result.get('document') else 80
        readable=result.get('readable_characters',len(text))>=minimum
        stable=stable+1 if nearly_same_text(last,text) and readable and not result['busy'] and result['ready'] else 0;last=text
        if stable>=3:
            if language=='en':
                scope=PREFIX_EN+' Scope: content already loaded when you confirmed. Collapsed, paginated and unloaded content is not included.'
                if result['truncated']:scope+=' Only the first 120,000 characters are included.'
            else:
                scope=PREFIX_ZH+' 采集范围：确认时网页中已加载的可读内容；未展开、分页及尚未加载的内容不包含。'
                if result['truncated']:scope+=' 本次最多保留前 12 万字符。'
            if result.get('captured_frames'):
                scope+=(' Includes visible embedded content from the same site or Feishu/Lark document domains.' if language=='en' else ' 包含同站点或飞书/Lark 文档域中可见嵌入页面的已加载文字。')
            return {'url':target,'title':result['title'] or urlsplit(target).hostname,'text':scope+'\n\n'+text,'web_capture':True,'capture_scope':'loaded_page'}
        if cancelled.wait(.8):raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
    counts=f"readable characters: {result.get('readable_characters',0)}, embedded pages: {result.get('captured_frames',0)}" if language=='en' else f"可读字符：{result.get('readable_characters',0)}，嵌入页面：{result.get('captured_frames',0)}"
    message='No stable readable document was found. Wait for loading or expand the content, then retry.' if language=='en' else '页面未取得稳定的可读正文，请等待加载完成、展开目标内容后重试。'
    raise RuntimeError(message+' ('+counts+')')


def read(url,profile_dir,notify,cancelled,timeout=600,login_complete=None,background=False,close_new_tabs=False,language='zh'):
    from playwright.sync_api import sync_playwright
    target=validate_browser_url(url);profile=Path(profile_dir).resolve();profile.mkdir(parents=True,exist_ok=True)
    if os.name!='nt':profile.chmod(0o700)
    notify('opening_browser','正在打开浏览器以读取网页')
    marker='about:blank#stellar-web-capture-'+uuid.uuid4().hex
    session=reader.start_or_reuse_browser(marker,profile,cancelled,background=background,proxy=None if is_loopback_url(target) else browser_proxy())
    confirmed=login_complete if login_complete is not None else threading.Event()
    page=None;completed=False
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(session['websocket'],timeout=15000)
        try:
            page=create_task_page(browser,session,background)
            # Do not route/intercept page requests. The user may spend minutes
            # signing in while this thread waits, without pumping Playwright's
            # event loop. Routing would pause ordinary fetch/iframe requests.
            open_capture_page(page,target,cancelled,language)
            for attempt in range(3):
                if cancelled.is_set():raise reader.CaptureCancelled('已停止网页采集，原链接与浏览器窗口保持不变')
                confirmed.clear();page.bring_to_front()
                notify('waiting_login','请在浏览器完成登录，打开并展开要保存的内容，再点击「页面已打开，开始读取」')
                reader.wait_for_manual_login(session.get('process') or SimpleNamespace(poll=lambda:None),confirmed,cancelled,timeout)
                confirmed_target=target
                if is_loopback_url(target):
                    # Local proxy viewers commonly redirect to an index or
                    # selected-conversation path. Accept that displayed page
                    # only after confirmation, within the submitted origin.
                    # Waiting for the user's event does not pump Playwright's
                    # cached URL updates. Ask the actual document after the
                    # confirmation so a completed script redirect is not stale.
                    confirmed_target=page.evaluate('location.href')
                    validate_browser_url(confirmed_target,target)
                elif not same_page(page.url,target):open_capture_page(page,target,cancelled,language)
                notify('reading','正在采集网页中已加载的正文')
                try:result=capture_loaded_page(page,confirmed_target,cancelled,language)
                except RuntimeError as exc:
                    if isinstance(exc,reader.CaptureCancelled):raise
                    if '登录界面' in str(exc) and attempt<2:continue
                    raise
                result['url']=target
                completed=True;session['confirmed']=True;reader.save_session(profile,session);return result
        finally:
            if page is not None:
                try:
                    if completed and close_new_tabs and not page.is_closed():page.close()
                except Exception:pass
            # Existing tabs and the browser process are never closed.
