"""User-confirmed model destination for company/browser material."""
import hashlib
import ipaddress
import json
from urllib.parse import urlsplit

KEY='company_model_approval'
PENDING='正文已保存。确认公司允许的模型服务后，可继续自动总结和问答。'

class ApprovalRequired(ValueError):
    def __init__(self,info):
        super().__init__(PENDING)
        self.info=info

def internal_url(url):
    try:
        host=(urlsplit(url).hostname or '').lower().rstrip('.')
        if not host:return False
        try:return not ipaddress.ip_address(host).is_global
        except ValueError:return '.' not in host or any(part in host.split('.') for part in ('infra','internal','intranet','corp','local','localhost'))
    except ValueError:return False

def restricted(item):
    if item.get('company_data') or internal_url(item.get('url','')):
        return True
    if item.get('text','').startswith(('【网页已加载内容归档】','[Loaded webpage capture]')):
        return True
    sources=list(item.get('group_links',[]))
    for batch in item.get('additions',[]):sources.extend(batch.get('links',[]))
    return any(internal_url(link.get('url','')) for link in sources)


def descriptor(config):
    if isinstance(config,dict):
        identity={k:v for k,v in config.items() if k!='_proxy'}
        destination=config['base_url'];label=config['model'];backend='api'
    else:
        backend=str(config);identity={'backend':backend}
        destination={'codex':'ChatGPT · Codex CLI','claude':'Claude CLI','gemini':'Gemini CLI'}.get(backend,backend)
        label='使用当前 CLI 登录账户；更换账户后请重新确认'
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(fingerprint=fingerprint,backend=backend,destination=destination,model=label)

def status(archive,config):
    info=descriptor(config)
    with archive.db() as db:
        row=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
    return dict(info,approved=bool(row and row[0]==info['fingerprint']))

def require(archive,config,item_ids):
    if any(restricted(archive.get(item_id)) for item_id in set(item_ids or [])):
        info=status(archive,config)
        if not info['approved']:raise ApprovalRequired(info)
    return config

def approve(archive,config,body):
    info=descriptor(config)
    if body.get('acknowledged') is not True or body.get('fingerprint')!=info['fingerprint']:
        raise ValueError('模型配置已变化，请重新核对服务与账户后确认。')
    with archive.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(KEY,info['fingerprint']))
    return {'ok':True,'company_model':dict(info,approved=True)}

def revoke(archive):
    with archive.db() as db:db.execute('DELETE FROM settings WHERE key=?',(KEY,))
    return {'ok':True}

def mark(archive,item_id):
    # No content/revision changes: this controls outbound model use only.
    with archive.db() as db:db.execute('UPDATE items SET company_data=1 WHERE id=?',(item_id,))
