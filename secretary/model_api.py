"""OpenAI-compatible API configuration and isolated, tool-free HTTP requests."""
import ipaddress,json,os,re,sys,tempfile,urllib.error,urllib.request
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

NAME='model-api.json'
DEFAULT={'base_url':'https://api.deepseek.com','model':'deepseek-flash','vision':False,'json_mode':False,'max_tokens':8192,'token_parameter':'max_tokens','use_key':True,'api_key':''}

def read(root):
    path=Path(root)/NAME
    try:
        if not path.exists():return dict(DEFAULT)
        return {**DEFAULT,**json.loads(path.read_text(encoding='utf-8'))}
    except (OSError,ValueError,TypeError):raise ValueError('模型 API 配置无法读取，请重新保存配置') from None

def public(root):
    try:value=read(root)
    except ValueError:return {**{k:v for k,v in DEFAULT.items() if k!='api_key'},'has_key':False,'configured':False}
    return {key:value[key] for key in DEFAULT if key!='api_key'}|{'has_key':bool(value['api_key']),'configured':bool(value['model'] and (value['api_key'] or not value['use_key']))}

def normalize(url):
    if not isinstance(url,str) or len(url)>2048:raise ValueError('请填写有效的 API 地址')
    parsed=urlsplit(url.strip().rstrip('/'))
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('API 地址需为 http(s) 地址，不能包含密码、查询参数或片段')
    if parsed.scheme=='http':
        try:local=ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:local=parsed.hostname=='localhost'
        if not local:raise ValueError('远程 API 请使用 HTTPS；HTTP 仅支持本机地址')
    path=parsed.path.rstrip('/')
    if path.endswith('/chat/completions'):path=path[:-len('/chat/completions')]
    return urlunsplit((parsed.scheme,parsed.netloc,path,'',''))

def prepare(root,body):
    if not isinstance(body,dict):raise ValueError('模型 API 配置格式无效')
    try:old=read(root)
    except ValueError:old=dict(DEFAULT)
    value={**old,**{key:body[key] for key in DEFAULT if key in body and key!='api_key'}}
    value['base_url']=normalize(value['base_url'])
    if not isinstance(value['model'],str) or not re.fullmatch(r'[^\s\x00-\x1f]{1,200}',value['model']):raise ValueError('请填写有效的模型名称')
    for key in ('vision','json_mode','use_key'):
        if type(value[key]) is not bool:raise ValueError('模型 API 选项无效')
    if type(value['max_tokens']) is not int or not 128<=value['max_tokens']<=65536:raise ValueError('最大输出 token 必须为 128–65536')
    if value['token_parameter'] not in ('max_tokens','max_completion_tokens'):raise ValueError('输出长度参数无效')
    key=body.get('api_key','')
    if not isinstance(key,str) or len(key)>8192 or any(ord(char)<33 or ord(char)>126 for char in key):raise ValueError('API Key 格式无效，请勿包含空格或换行')
    if not value['use_key']:value['api_key']=''
    elif key:value['api_key']=key
    elif value['base_url']!=old['base_url']:raise ValueError('更换 API 地址时，请重新填写 API Key，避免把旧密钥发送到新地址')
    if value['use_key'] and not value['api_key']:raise ValueError('请填写 API Key；本地无鉴权服务可选择「无需 API Key」')
    if not isinstance(value['api_key'],str) or len(value['api_key'])>8192 or any(ord(char)<33 or ord(char)>126 for char in value['api_key']):raise ValueError('已保存的 API Key 格式无效，请重新填写')
    return value

def write(root,value):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.model-api-',suffix='.tmp',dir=root)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False)
        os.chmod(name,0o600);os.replace(name,root/NAME)
    finally:Path(name).unlink(missing_ok=True)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def complete(config,prompt,images):
    # Validate even when invoked as a standalone worker.
    base=normalize(config['base_url']);content=prompt
    if images:
        if not config['vision']:raise ValueError('当前 API 未启用图片输入')
        content=[{'type':'text','text':prompt}]+[{'type':'image_url','image_url':{'url':'data:'+image['media']+';base64,'+image['data']}} for image in images]
    from .ai import RULES
    payload={'model':config['model'],'messages':[{'role':'system','content':RULES},{'role':'user','content':content}],'stream':False,config.get('token_parameter','max_tokens'):config['max_tokens']}
    if config['json_mode'] and '仅输出 JSON' in prompt:payload['response_format']={'type':'json_object'}
    headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'StellarSecretary'}
    if config['use_key']:headers['Authorization']='Bearer '+config['api_key']
    host=urlsplit(base).hostname
    handlers=[NoRedirect()]
    if host in ('localhost','127.0.0.1','::1'):handlers.append(urllib.request.ProxyHandler({}))
    opener=urllib.request.build_opener(*handlers)
    try:
        with opener.open(urllib.request.Request(base+'/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers),timeout=120) as response:
            raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise ValueError('模型 API 返回内容过大')
        result=json.loads(raw);choice=result['choices'][0]
        if choice.get('finish_reason')=='length':raise ValueError('模型输出达到 token 上限，请提高最大输出 token 后重试')
        answer=choice['message'].get('content')
        if not isinstance(answer,str) or not answer.strip():raise ValueError('模型 API 没有返回有效文本，请检查模型和接口格式')
        return answer.replace(config['api_key'],'[redacted]') if config['api_key'] else answer
    except urllib.error.HTTPError as error:
        messages={400:'请求不被支持，请检查模型、图片输入和 JSON 输出选项',401:'API Key 无效或已过期',403:'API 没有访问权限',404:'API 地址或模型不存在',429:'API 限流或额度不足，请稍后重试'}
        raise RuntimeError('模型 API：'+messages.get(error.code,'服务请求失败（HTTP '+str(error.code)+'）')) from None
    except (urllib.error.URLError,TimeoutError,OSError):raise RuntimeError('模型 API 连接失败，请检查地址、网络、代理和证书') from None
    except (ValueError,KeyError,IndexError,TypeError) as error:
        if isinstance(error,ValueError) and not isinstance(error,json.JSONDecodeError):raise
        raise RuntimeError('模型 API 返回格式不兼容，请确认使用 Chat Completions 接口') from None

def worker_stdio():
    # Windowed Windows builds leave Python's streams unset even with inherited pipes.
    if sys.platform!='win32':return
    import ctypes,msvcrt
    get_handle=ctypes.WinDLL('kernel32',use_last_error=True).GetStdHandle
    get_handle.argtypes=[ctypes.c_ulong];get_handle.restype=ctypes.c_void_p
    for name,index,mode,flags in [('stdin',-10,'r',os.O_RDONLY),('stdout',-11,'w',os.O_WRONLY)]:
        if getattr(sys,name) is not None:continue
        handle=get_handle(ctypes.c_ulong(index).value)
        if handle in (None,ctypes.c_void_p(-1).value):raise RuntimeError('API worker pipe is unavailable')
        fd=msvcrt.open_osfhandle(handle,flags|os.O_BINARY)
        setattr(sys,name,os.fdopen(fd,mode,encoding='utf-8'))

def main():
    worker_stdio()
    from . import paths
    paths.configure_tls()
    value={}
    try:
        value=json.loads(__import__('sys').stdin.read());answer=complete(value['config'],value['prompt'],value.get('images',[]))
        print(json.dumps({'answer':answer},ensure_ascii=False),flush=True)
    except Exception as error:
        message=str(error);key=value.get('config',{}).get('api_key','')
        if key:message=message.replace(key,'[redacted]')
        print(json.dumps({'error':message},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
