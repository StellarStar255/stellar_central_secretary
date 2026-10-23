"""Shared, testable labels for the native application's service state."""


def _presentation(status):
    if status.get('error'):
        return {'title':'异常', 'detail':'服务连接异常，请查看运行日志', 'icon':'error', 'badge':'!'}
    if not status.get('application'):
        return {'title':'启动中', 'detail':'正在启动知识秘书…', 'icon':'starting', 'badge':'…'}
    update = status.get('update', {})
    if update.get('phase') in ('downloading', 'verifying', 'installing'):
        return {'title':'升级中', 'detail':'正在升级，请稍候…', 'icon':'busy', 'badge':'升级'}
    runtime = status.get('runtime', {})
    labels = [(runtime.get('reading', 0), '读取会话', '读取'),
              (runtime.get('processing', 0), '整理资料', '整理'),
              (runtime.get('answering', 0), '回答问题', '问答')]
    active = [(n, label, badge) for n, label, badge in labels if n]
    if active:
        return {'title':'处理中', 'detail':' · '.join(f'{label} {n} 项' for n,label,_ in active),
                'icon':'busy', 'badge':active[0][2]}
    return {'title':'就绪', 'detail':'运行中 · 就绪', 'icon':'ready', 'badge':None}


def presentation(status):
    from .i18n import translate
    value=_presentation(status);language=status.get('settings',{}).get('ui_language','zh')
    if language=='en':
        value={key:translate(text,language) if isinstance(text,str) else text for key,text in value.items()}
        import re
        value['detail']=re.sub(r' (\d+) 项',r': \1',value['detail'])
    return value
