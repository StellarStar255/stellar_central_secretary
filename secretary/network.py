"""Resolve model and capture-browser routes without changing system configuration."""
import os
import ipaddress
import re
import socket
import subprocess
import urllib.request
from urllib.parse import urlsplit,urlunsplit


PROXY_KEYS=('https_proxy','HTTPS_PROXY','http_proxy','HTTP_PROXY','all_proxy','ALL_PROXY')

def is_loopback_url(url):
    try:
        host=urlsplit(url).hostname
        if host=='localhost':return True
        return ipaddress.ip_address(host).is_loopback
    except (ValueError,TypeError):return False

def proxy_config(value=None, browser=False):
    if value is None:return {'mode':'auto','url':''}
    if not isinstance(value,dict) or value.get('mode') not in ('auto','direct','custom'):raise ValueError('无效的模型代理设置')
    mode=value['mode']
    if mode!='custom':return {'mode':mode,'url':''}
    url=value.get('url','')
    message='浏览器代理请使用 http:// 或 socks5://，并填写正确端口；暂不支持账号密码。' if browser else '模型连接请填写 HTTP / Mixed 端口；SOCKS 端口请填到浏览器代理选项中。'
    if not isinstance(url,str) or len(url)>2048:raise ValueError(message)
    url=url.strip()
    try:
        parsed=urlsplit(url);port=parsed.port
        if (parsed.scheme not in (('http','socks5') if browser else ('http',)) or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('','/') or parsed.query or parsed.fragment or any(ord(c)<=32 for c in url)
            or (port is not None and not 1<=port<=65535)):raise ValueError(message)
    except ValueError:raise ValueError(message) from None
    return {'mode':mode,'url':urlunsplit((parsed.scheme,parsed.netloc,'','',''))}


def local_proxy_alive(url):
    parsed=urlsplit(url)
    if not is_loopback_url(url): return True
    try:
        with socket.create_connection((parsed.hostname,parsed.port or (1080 if parsed.scheme=='socks5' else 80)),timeout=.5):return True
    except ConnectionRefusedError:return False
    except OSError:
        # A permission/network restriction is not proof that the proxy is dead.
        return True


def running_proxy_candidates():
    try:
        result=subprocess.run(['lsof','-nP','-iTCP','-sTCP:LISTEN','-Fpcn'],capture_output=True,text=True,timeout=3)
    except (OSError,subprocess.TimeoutExpired):return []
    candidates=[];command=''
    for line in result.stdout.splitlines():
        if line.startswith('c'):command=line[1:].lower()
        if line.startswith('n') and command in ('xray','mihomo','clash','clash-verge','sing-box','v2ray'):
            match=re.fullmatch(r'n(?:127\.0\.0\.1|\*):([0-9]+)',line)
            if match:candidates.append('http://127.0.0.1:'+match[1])
    return list(dict.fromkeys(candidates))


def http_proxy_works(url):
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1'):return False
    try:
        with socket.create_connection((parsed.hostname,parsed.port or (1080 if parsed.scheme=='socks5' else 80)),timeout=3) as sock:
            sock.settimeout(4)
            sock.sendall(b'CONNECT chatgpt.com:443 HTTP/1.1\r\nHost: chatgpt.com:443\r\n\r\n')
            status=sock.recv(512).split(b'\r\n',1)[0]
            return bool(re.match(rb'HTTP/1\.[01] 200(?: |$)',status))
    except OSError:return False


def child_env(source=None,policy=None):
    env=dict(os.environ if source is None else source)
    env.pop('CLAUDECODE',None)
    policy=proxy_config(policy)
    if policy['mode']=='direct':
        for key in PROXY_KEYS:env.pop(key,None)
        env['no_proxy']=env['NO_PROXY']='*'
        env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
        return env
    if policy['mode']=='custom':
        route=policy['url']
        if not local_proxy_alive(route):raise RuntimeError('自定义代理无法连接：'+describe({'HTTP_PROXY':route})+'。请启动代理软件并确认 HTTP 端口；本次不会改用直连。')
        for key in PROXY_KEYS:env.pop(key,None)
        for key in ('http_proxy','HTTP_PROXY','https_proxy','HTTPS_PROXY'):env[key]=route
        env['no_proxy']=env['NO_PROXY']='localhost,127.0.0.1,::1'
        env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
        return env
    explicit=next((env[k] for k in PROXY_KEYS if env.get(k)),None)
    route=explicit if explicit and local_proxy_alive(explicit) else None
    if not route:
        try:system=urllib.request.getproxies()
        except Exception:system={}
        system_route=system.get('https') or system.get('http')
        if system_route and system_route!=explicit and local_proxy_alive(system_route):route=system_route
        if not route:
            route=next((url for url in running_proxy_candidates() if http_proxy_works(url)),None)
        if not route and explicit:
            p=urlsplit(explicit)
            raise RuntimeError(f'配置的本地代理 {p.hostname}:{p.port} 没有运行，未找到经过连接验证的替代代理。请启动代理软件后重试摘要。')
    if route:
        for key in PROXY_KEYS:env.pop(key,None)
        for key in ('http_proxy','HTTP_PROXY','https_proxy','HTTPS_PROXY'):env[key]=route
        bypass=env.get('no_proxy') or env.get('NO_PROXY') or ''
        bypass=','.join(dict.fromkeys(filter(None,('localhost','127.0.0.1','::1',*bypass.split(',')))))
        env['no_proxy']=env['NO_PROXY']=bypass
    env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    return env


def describe(env):
    route=next((env[k] for k in PROXY_KEYS if env.get(k)),None)
    if not route:return '直连'
    p=urlsplit(route)
    return f'{p.scheme}://{p.hostname}:{p.port}'


def capture_proxy_config(value=None):
    if value is None:return {'mode':'system','url':''}
    if not isinstance(value,dict) or value.get('mode') not in ('system','model','direct','custom'):raise ValueError('无效的浏览器代理设置')
    if value['mode'] in ('system','model'):return {'mode':value['mode'],'url':''}
    return proxy_config(value,browser=True)


def capture_proxy_route(value=None,model=None):
    policy=capture_proxy_config(value)
    if policy['mode']=='system':return None
    if policy['mode']=='model':policy=proxy_config(model)
    if policy['mode']=='direct':return 'direct://'
    if policy['mode']=='custom':
        if not local_proxy_alive(policy['url']):raise RuntimeError('浏览器代理端口没有连接成功，请先启动代理软件并核对端口。')
        return policy['url']
    env=child_env(policy=policy)
    return next((env[key] for key in PROXY_KEYS if env.get(key)),None)


def check_proxy_port(policy=None, browser=False, model=None):
    if browser:route=capture_proxy_route(policy,model)
    else:
        value=proxy_config(policy)
        env=child_env(policy=value)
        route=next((env[key] for key in PROXY_KEYS if env.get(key)),None)
    if not route or route=='direct://':return {'ok':True,'proxied':False,'message':'当前未指定代理端口；将使用所选的自动或直连方式。'}
    parsed=urlsplit(route)
    try:
        with socket.create_connection((parsed.hostname,parsed.port or (1080 if parsed.scheme=='socks5' else 80)),timeout=3):pass
    except OSError as error:raise RuntimeError('代理端口连接失败。请打开代理软件，并核对这里的端口数字。') from error
    return {'ok':True,'proxied':True,'message':'代理端口可以连接；模型和网页是否可用还需继续测试。'}
