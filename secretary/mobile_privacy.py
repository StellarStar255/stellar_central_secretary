"""Constrain mobile-origin model jobs to the destination the phone approved."""
import hashlib
import json
from contextvars import ContextVar
from urllib.parse import urlsplit

from . import company_ai

active = ContextVar('mobile_model_authorization', default=None)


class ApprovalRequired(ValueError):
    def __init__(self):
        super().__init__('请在手机的「连接 → 隐私与 AI」确认当前模型服务后重试。')


def destination(config):
    if isinstance(config, dict):
        url = config['base_url']
        model = config['model']
        parsed = urlsplit(url)
        label = parsed.hostname or '自定义 API'
        if parsed.port:
            label += f':{parsed.port}'
        identity = ('api', url, model)
    else:
        label = company_ai.descriptor(config)['destination']
        model = ''
        identity = ('cli', str(config))
    fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return {'destination': label, 'model': model, 'fingerprint': fingerprint}


def check(config):
    authorize = active.get()
    if authorize is not None:
        authorize(config)
