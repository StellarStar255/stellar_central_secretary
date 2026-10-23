"""Read a ChatGPT conversation after the user signs in in a dedicated browser.

No cookie export, password input, login clicks or default-profile access. The
browser session lives in data/browser-live-profile and is excluded from backups.
"""
import os
import sys
import json
import socket
import urllib.request
from types import SimpleNamespace
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


class CaptureCancelled(RuntimeError):
    pass


def conversation_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('chatgpt.com', 'chat.openai.com')
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not re.fullmatch(r'/(c|share)/[a-zA-Z0-9_-]+/?', parsed.path)):
        raise ValueError('登录读取目前支持 ChatGPT 的 /c/ 或 /share/ 会话链接。')
    return 'https://chatgpt.com' + parsed.path.rstrip('/')


_EXTRACTOR = (Path(__file__).parent/'static'/'extract.js').read_text()
SNAPSHOT_SCRIPT = '() => {'+_EXTRACTOR+';return extractKnowledgeConversation();}'
MESSAGES_SCRIPT = '() => {'+_EXTRACTOR+';return extractKnowledgeConversation().messages;}'


def snapshot(page):
    value=page.evaluate(SNAPSHOT_SCRIPT)
    if isinstance(value,list):
        # Also accepts legacy extractor responses; useful for saved fixtures.
        return {'messages':value,'diagnostics':{'messages':len(value),'generating':False,'method':'legacy'}}
    if not isinstance(value,dict) or not isinstance(value.get('messages'),list):
        raise RuntimeError('页面提取器没有返回有效结果')
    return value


def validate_messages(messages):
    valid = [m for m in messages if isinstance(m, dict) and m.get('role') in ('user', 'assistant') and isinstance(m.get('text'), str) and m['text'].strip()]
    if not any(m['role'] == 'assistant' for m in valid): return []
    if sum(len(m['text']) for m in valid) < 20: return []
    return valid


def message_text(messages):
    return '\n\n'.join(('用户' if m['role'] == 'user' else 'ChatGPT') + '：\n' + m['text'] for m in messages)


def same_conversation(actual, expected):
    try: return conversation_url(actual) == conversation_url(expected)
    except (ValueError, TypeError): return False


def chrome_executable():
    candidates = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if os.environ.get(variable): candidates.append(Path(os.environ[variable])/'Google/Chrome/Application/chrome.exe')
    for candidate in candidates:
        if candidate.is_file(): return str(candidate)
    return shutil.which('google-chrome') or shutil.which('google-chrome-stable') or shutil.which('chromium')


def wait_for_manual_login(proc, confirmed, cancelled, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled.is_set(): raise CaptureCancelled('已停止读取。原链接仍保留。')
        code = proc.poll()
        if code not in (None, 0): raise RuntimeError('普通 Chrome 未能启动，请使用常用浏览器中的采集扩展。')
        if confirmed.wait(0.25):
            if cancelled.is_set(): raise CaptureCancelled('已停止读取。')
            return
    raise RuntimeError('等待登录超时。请在普通 Chrome 中打开目标会话，然后点击知识秘书里的「我已登录，开始读取」；也可使用浏览器采集扩展。')


def debug_info(endpoint):
    """Loopback only; ignore proxy settings and do not follow redirects."""
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port:
        raise ValueError('无效的本地浏览器连接地址')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(endpoint+'/json/version', timeout=1) as response:
        info = json.loads(response.read(65536))
    ws = urlsplit(info.get('webSocketDebuggerUrl', ''))
    if ws.scheme != 'ws' or ws.hostname != '127.0.0.1' or ws.port != parsed.port or not ws.path.startswith('/devtools/browser/'):
        raise ValueError('浏览器返回了无效的连接信息')
    return {'endpoint':endpoint, 'websocket':info['webSocketDebuggerUrl']}


def save_session(profile, session):
    path = profile/'.reader-session.json'
    temporary = profile/f'.reader-session-{os.getpid()}-{threading.get_ident()}.tmp'
    temporary.write_text(json.dumps({k:session[k] for k in ('endpoint','websocket','confirmed')}))
    if os.name != 'nt': temporary.chmod(0o600)
    temporary.replace(path)


def existing_session(profile):
    try:
        saved = json.loads((profile/'.reader-session.json').read_text())
        actual = debug_info(saved['endpoint'])
        if actual['websocket'] == saved['websocket']:
            return dict(actual,confirmed=bool(saved.get('confirmed')),process=None)
    except (OSError,ValueError,KeyError,TypeError):pass
    # A restarted Chrome has a new websocket nonce. Rebind only after verifying
    # the exact dedicated profile and loopback port, never an arbitrary browser.
    from .browser_session import discover
    current=discover(profile,chrome_executable(),debug_info)
    if current:
        current=dict(current,confirmed=False,process=None)
        save_session(profile,current)
        return current
    return None


def free_loopback_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def start_or_reuse_browser(target, profile, cancelled, timeout=20, background=False, proxy=None):
    # Capture workers share a profile, but Chrome startup must be serialized.
    profile=Path(profile);profile.mkdir(parents=True,exist_ok=True)
    with (profile/'.reader-start.lock').open('a+b') as lock:
        if os.name=='nt':
            import msvcrt
            lock.write(b'0');lock.flush();lock.seek(0)
        else:import fcntl
        while True:
            if cancelled.is_set():raise CaptureCancelled('已停止读取，已有资料保持不变。')
            try:
                if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                else:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:cancelled.wait(.1)
        try:return _start_or_reuse_browser(target,profile,cancelled,timeout,background,proxy)
        finally:
            if os.name=='nt':lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_UN)


def _start_or_reuse_browser(target, profile, cancelled, timeout=20, background=False, proxy=None):
    current = existing_session(profile)
    if current: return current
    chrome = chrome_executable()
    if not chrome: raise RuntimeError('没有找到 Google Chrome，请安装 Chrome 或使用常用浏览器采集扩展。')
    port = free_loopback_port()
    endpoint = f'http://127.0.0.1:{port}'
    # This browser remains alive throughout manual sign-in, extraction and later
    # imports. The debugging endpoint is local and uses this dedicated profile.
    args = ['--user-data-dir='+str(profile), '--no-first-run',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port='+str(port),
            *(['--no-startup-window'] if background else ['--new-window', target])]
    if proxy: args.append('--proxy-server='+proxy)
    options = {}
    if background and sys.platform == 'darwin':
        command = ['/usr/bin/open', '-g', '-n', '-a', str(Path(chrome).parents[2]), '--args', *args]
    else:
        command = [chrome, *args]
        if background and os.name == 'nt':
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 7  # SW_SHOWMINNOACTIVE
            options['startupinfo'] = startup
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, **options)
    deadline = time.monotonic()+timeout
    rediscover_at=time.monotonic()+1
    while time.monotonic()<deadline:
        if cancelled.is_set(): raise CaptureCancelled('已停止连接。浏览器窗口保持打开。')
        if proc.poll() not in (None,0): raise RuntimeError('Chrome 启动失败，请使用常用浏览器采集扩展。')
        try:
            session = dict(debug_info(endpoint),confirmed=False,process=proc)
            if not background: session['startup_url'] = target
            save_session(profile,session)
            return session
        except (OSError,ValueError): pass
        if time.monotonic()>=rediscover_at:
            current=existing_session(profile)
            if current:return current
            rediscover_at=time.monotonic()+1
        if cancelled.wait(0.25): raise CaptureCancelled('已停止连接。浏览器窗口保持打开。')
    raise RuntimeError('浏览器已请求打开，但未能建立本地连接。请使用常用浏览器采集扩展；程序不会关闭你的登录窗口。')


def manual_login(target, profile, notify, cancelled, confirmed, timeout):
    session = start_or_reuse_browser(target,profile,cancelled)
    if not session['confirmed']:
        notify('waiting_login','请在已打开的 Chrome 中登录并打开目标会话，再点「我已登录，开始读取」。程序会直接读取这个实例，整个过程保持窗口打开。')
        proc = session.get('process') or SimpleNamespace(poll=lambda:None)
        wait_for_manual_login(proc,confirmed,cancelled,timeout)
    notify('confirming_login','正在连接同一个浏览器实例，登录窗口保持打开。')
    return session


def login_rejected(page):
    if urlsplit(page.url).hostname != 'accounts.google.com': return False
    for text in ("Couldn’t sign you in", "Couldn't sign you in", 'This browser or app may not be secure', '此浏览器或应用可能不安全'):
        if page.get_by_text(text, exact=False).count(): return True
    return False


SCROLL_SCRIPT = r"""() => {
  const main=document.querySelector('main')||document.body;
  const candidates=new Set([document.scrollingElement]);
  for(let n=main;n;n=n.parentElement)candidates.add(n);
  for(const n of main.querySelectorAll('[class*="overflow-y"],[data-radix-scroll-area-viewport]'))candidates.add(n);
  const scrolls=[...candidates].filter(n=>n&&n.clientHeight>100&&n.scrollHeight>n.clientHeight+40&&
    (n===document.scrollingElement||/auto|scroll/.test(getComputedStyle(n).overflowY)));
  const node=scrolls.sort((a,b)=>(b.scrollHeight-b.clientHeight)-(a.scrollHeight-a.clientHeight))[0]||document.scrollingElement;
  const max=Math.max(0,node.scrollHeight-node.clientHeight);
  const step=Math.max(200,node.clientHeight*.75);
  node.scrollTop=DIRECTION==='top'?0:DIRECTION==='bottom'?max:DIRECTION==='up'?Math.max(0,node.scrollTop-step):Math.min(max,node.scrollTop+step);
  return {top:node.scrollTop,max,bottom:node.scrollTop>=max-3};
}"""


PARTIAL_PREFIX = '【部分对话归档】'


def recent_turns(messages, limit=20):
    users=0
    for index in range(len(messages)-1,-1,-1):
        if messages[index]['role']=='user':
            users+=1
            if users==limit:return messages[index:]
    return messages


def collect_messages(page, cancelled, notify=None, scope='full'):
    if scope not in ('full','recent','loaded'):raise ValueError('无效的会话读取范围')
    collected = {}; ordered = []
    def merge(messages, prepend=False):
        new = []
        for m in messages:
            if not isinstance(m,dict) or not m.get('text'): continue
            key = m['role']+'\0'+(m.get('id') or m['text'])
            if key not in collected: new.append(key)
            collected[key] = m
        if prepend: ordered[:0] = new
        else: ordered.extend(new)
    def check():
        if cancelled.is_set(): raise CaptureCancelled('已停止读取。登录窗口保持打开。')
    if scope=='loaded':
        check()
        return validate_messages(page.evaluate(MESSAGES_SCRIPT))
    if scope=='recent':
        # Start at the latest messages and walk back only a bounded distance.
        # Reaching the beginning of the entire history is deliberately unnecessary.
        for _ in range(3):
            check()
            page.evaluate(SCROLL_SCRIPT.replace('DIRECTION',"'bottom'"))
            page.wait_for_timeout(350)
            merge(page.evaluate(MESSAGES_SCRIPT))
        last=None;stable=0
        for step in range(24):
            check()
            current=[collected[k] for k in ordered]
            if sum(m['role']=='user' for m in current)>=20:break
            position=page.evaluate(SCROLL_SCRIPT.replace('DIRECTION',"'up'"))
            page.wait_for_timeout(450)
            merge(page.evaluate(MESSAGES_SCRIPT),prepend=True)
            signature=tuple(ordered)
            at_top=isinstance(position,dict) and position.get('top',1)<=3
            stable=stable+1 if at_top and signature==last else 0;last=signature
            if notify and step%4==0:notify('reading',f'正在读取最近对话，已收集 {len(ordered)} 条消息；无需加载全部历史。')
            if stable>=2:break
        return validate_messages(recent_turns([collected[k] for k in ordered]))
    # Reach the top first, including asynchronously loaded history. Do not depend
    # on the legacy data-message-author-role node to find the scroll container.
    last=None;stable=0
    for _ in range(20):
        check()
        page.evaluate(SCROLL_SCRIPT.replace('DIRECTION',"'top'"))
        page.wait_for_timeout(900)
        messages=page.evaluate(MESSAGES_SCRIPT);merge(messages,prepend=True)
        signature=message_text(messages)
        stable=stable+1 if signature==last else 0;last=signature
        if stable>=3:break
    else:raise RuntimeError('历史消息仍在加载，未确认到达顶部；已保存的正文保持不变，请稍后重试。')
    stable=0;last=None
    for step in range(160):
        check()
        position=page.evaluate(SCROLL_SCRIPT.replace('DIRECTION',"'down'"))
        page.wait_for_timeout(600)
        messages=page.evaluate(MESSAGES_SCRIPT);merge(messages)
        if notify and step%5==0:notify('reading',f'正在逐段补读会话，已收集 {len(ordered)} 条消息…')
        signature=message_text(messages)
        # Legacy test snapshots have no geometry; actual pages return a dict.
        bottom=position.get('bottom',False) if isinstance(position,dict) else True
        stable=stable+1 if bottom and signature==last else 0;last=signature
        if stable>=3:return validate_messages([collected[k] for k in ordered])
    raise RuntimeError('会话超过本次滚动读取范围，尚未确认到达底部；旧正文保持不变。请分段导入。')


def read_from_browser(pw, session, target, notify, cancelled, timeout=90, diagnose=None, capture_page=None, on_login_required=None, browser=None, scope='full'):
    browser=browser or pw.chromium.connect_over_cdp(session['websocket'],timeout=15000)
    if not browser.contexts: raise RuntimeError('无法找到原浏览器会话，登录窗口保持打开，请重试。')
    # Inspect every matching tab, since sign-in may leave an earlier guest tab.
    context=browser.contexts[0]
    if capture_page is None and not any(same_conversation(p.url,target) for ctx in browser.contexts for p in ctx.pages if not p.is_closed()):
        page=context.new_page()
        page.goto(target,wait_until='domcontentloaded',timeout=45000)
    start=time.monotonic();deadline=start+timeout;last='';stable=0;last_notify=-10;last_report=[]
    while time.monotonic()<deadline:
        if cancelled.is_set(): raise CaptureCancelled('已停止读取。登录窗口保持打开。')
        candidates=[];report=[]
        if capture_page is not None and not same_conversation(capture_page.url,target):
            parsed=urlsplit(capture_page.url)
            if on_login_required and (parsed.hostname=='accounts.google.com' or (parsed.hostname in ('chatgpt.com','chat.openai.com','auth.openai.com') and re.search(r'auth|login|signin',parsed.path))):
                on_login_required(capture_page)
                start=time.monotonic();deadline=start+timeout;stable=0;last=''
                continue
        contexts = [SimpleNamespace(pages=[capture_page])] if capture_page is not None else browser.contexts
        for ctx in contexts:
            for page in ctx.pages:
                if page.is_closed():continue
                if not same_conversation(page.url,target):continue
                try:
                    value=snapshot(page)
                    diagnostics=value['diagnostics']
                    messages=validate_messages(value['messages'])
                    report.append(diagnostics)
                    candidates.append((len(messages),page,messages,diagnostics))
                except Exception as exc:
                    report.append({'url':target,'error':str(exc)[:300]})
        last_report=report
        if diagnose:diagnose({'target':target,'elapsed_seconds':round(time.monotonic()-start),'tabs':report})
        if not candidates:
            if not report:raise RuntimeError('原浏览器中没有目标会话标签页；可能已跳转到登录或验证页。请打开目标会话后重试。')
            if time.monotonic()-start>15:raise RuntimeError('无法读取目标页面结构。详细原因已保存到本机读取诊断。')
            cancelled.wait(0.5);continue
        _,page,messages,diag=max(candidates,key=lambda c:c[0])
        elapsed=time.monotonic()-start
        if not messages and all(d.get('login') for _,_,_,d in candidates):
            if on_login_required:
                on_login_required(page)
                start=time.monotonic();deadline=start+timeout;stable=0;last=''
                continue
            raise RuntimeError('原窗口当前仍是未登录状态。请先在该窗口登录 ChatGPT，再点读取；程序不会关闭窗口。')
        if not messages and all(d.get('denied') for _,_,_,d in candidates):
            raise RuntimeError('目标页面提示会话不存在、加载失败或没有访问权限。请在原窗口确认账号有权查看这条会话。')
        signature=message_text(messages if scope=='full' else messages[-2:]) if messages else ''
        stable=stable+1 if signature and (scope!='full' or signature==last) and not diag.get('generating') else 0
        last=signature
        if elapsed-last_notify>=4:
            count=len(messages)
            state='页面仍在生成回答' if diag.get('generating') else '正在确认正文完整' if count else '暂未识别出聊天消息'
            notify('reading',f'已连接「{diag.get("title") or "目标会话"}」，识别到 {count} 条消息；{state}（{int(elapsed)} 秒）。')
            last_notify=elapsed
        if stable>=2:
            final=collect_messages(page,cancelled,notify,scope=scope)
            if not final:raise RuntimeError('已识别消息，但收集阶段未取得正文。诊断已保存在本机。')
            text=message_text(final)
            if scope!='full':
                label='最近可读取的对话（最多20轮）' if scope=='recent' else '当前已加载的内容'
                text=f'{PARTIAL_PREFIX} 采集范围：{label}，共 {len(final)} 条消息；未读取完整历史。\n\n'+text
            return {'url':target,'title':page.title(),'text':text,'message_count':len(final),'partial':scope!='full','capture_scope':scope}
        if not messages and elapsed>=20 and diag.get('readyState')=='complete' and diag.get('mainChars',0)>100:
            raise RuntimeError(f'「{diag.get("title") or "目标会话"}」已加载，但未识别出有效助手消息（角色节点 {diag.get("authorNodes",0)}、对话节点 {diag.get("turnNodes",0)}）。读取诊断已保存在本机，当前窗口保持打开。')
        page.wait_for_timeout(1500)
    counts=max((d.get('messages',0) for d in last_report),default=0)
    raise RuntimeError(f'读取等待达到 {int(timeout)} 秒；最后识别到 {counts} 条消息。'+('页面仍显示正在生成回答。' if any(d.get('generating') for d in last_report) else '页面消息尚未满足采集条件。')+'诊断已保存，原窗口保持打开。')


def read(url, profile_dir, notify, cancelled, timeout=600, login_complete=None, background=False, close_new_tabs=False, scope='full'):
    if background or close_new_tabs:
        from .capture_browser import read_managed
        return read_managed(url, profile_dir, notify, cancelled, timeout, login_complete, background, close_new_tabs, scope=scope)
    target=conversation_url(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('浏览器连接组件未安装，请重新运行启动脚本安装依赖。') from exc
    profile=Path(profile_dir).resolve();profile.mkdir(parents=True,exist_ok=True)
    if os.name!='nt': profile.chmod(0o700)
    notify('opening_browser','正在打开或复用专用 Chrome，读取过程中窗口将保持打开。')
    confirmed=login_complete if login_complete is not None else threading.Event()
    session=manual_login(target,profile,notify,cancelled,confirmed,timeout)
    try:
        with sync_playwright() as pw:
            result=read_from_browser(pw,session,target,notify,cancelled,min(timeout,90),diagnose=lambda report:(profile.parent/'last-capture-diagnostic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)),scope=scope)
        session['confirmed']=True;save_session(profile,session)
        return result
    except Exception:
        session['confirmed']=False;save_session(profile,session)
        raise
