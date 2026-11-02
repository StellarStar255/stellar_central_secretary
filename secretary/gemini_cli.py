"""Tool-free Gemini CLI requests, retaining the user's CLI authentication."""
import json
from pathlib import Path


def prepare(cli, cwd, prompt, images, env, rules):
    root=Path(cwd)
    system=root/'system.md';system.write_text(rules,encoding='utf-8')
    policy=root/'no-tools.toml'
    policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n',encoding='utf-8')
    context_name=f'.stellar-context-{root.name}.md'
    (root/context_name).write_text('',encoding='utf-8')
    settings={
        'tools':{'core':[],'discoveryCommand':'','callCommand':''},
        'admin':{'mcp':{'enabled':False},'extensions':{'enabled':False},'skills':{'enabled':False}},
        'policyPaths':[str(policy)],'mcp':{'allowed':['__stellar_no_mcp__']},
        'hooksConfig':{'enabled':False},
        'context':{'fileName':context_name,'includeDirectories':[],'includeDirectoryTree':False},
        'advanced':{'ignoreLocalEnv':True},'ide':{'enabled':False},
        'general':{'enableAutoUpdate':False,'sessionRetention':{'enabled':False}},
        'model':{'maxSessionTurns':1},
        'telemetry':{'enabled':False,'logPrompts':False},
        'privacy':{'usageStatisticsEnabled':False},
        'experimental':{'autoMemory':False},
    }
    if env.get('NO_PROXY')=='*':settings['proxy']=''
    config=root/'.gemini/settings.json';config.parent.mkdir()
    config.write_text(json.dumps(settings),encoding='utf-8')
    # Trust our own temporary directory before Gemini loads project settings;
    # --skip-trust alone is processed too late to apply those overrides.
    env={**env,'GEMINI_SYSTEM_MD':str(system),'GEMINI_CLI_TRUST_WORKSPACE':'true','NO_BROWSER':'true'}
    env.pop('GEMINI_WRITE_SYSTEM_MD',None)
    # Gemini expands @paths before the model sees input, even with no tools.
    # Encode all supplied text as JSON; only our explicit attachment paths use @.
    source=json.dumps({'request':prompt},ensure_ascii=False).replace('@',r'\u0040')
    for index,image in enumerate(images):
        suffix={'image/png':'.png','image/webp':'.webp','image/gif':'.gif'}.get(image.get('media'),'.jpg')
        name=f'stellar-image-{index+1}{suffix}'
        (root/name).write_bytes(image['data'])
        source+='\n@'+name
    command=[cli,'--output-format','json','--extensions','none','--approval-mode','default','--skip-trust',
             '--allowed-mcp-server-names','__stellar_no_mcp__','--policy',str(policy),
             '--prompt','请依据标准输入中的 JSON request 和显式附加的图片完成请求。']
    return command,source,env


def response(output):
    try:result=json.loads(output)
    except ValueError:raise RuntimeError('Gemini CLI 未返回有效 JSON，请升级 CLI 后重试。') from None
    if not isinstance(result,dict):raise RuntimeError('Gemini CLI 返回格式无效，请升级 CLI 后重试。')
    if result.get('error'):
        error=result['error']
        message=error.get('message') if isinstance(error,dict) else error
        raise RuntimeError('Gemini CLI：'+str(message or '调用失败')[:1200])
    answer=result.get('response')
    if not isinstance(answer,str) or not answer.strip():raise RuntimeError('Gemini CLI 没有返回有效内容，请检查登录状态和账户额度。')
    return answer
