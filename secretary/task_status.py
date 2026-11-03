"""Actionable task failures without hiding the underlying diagnostic."""
def explain(error):
    text=str(error or '');lower=text.lower()
    if any(word in lower for word in ('已停止','cancelled','canceled')):kind,message='stopped','已停止，原文和已有结果保持不变。'
    elif any(word in lower for word in ('超时','timeout','timed out','deadline')):kind,message='timeout','等待模型响应超时。请检查连接后重试，已有资料已保留。'
    elif any(word in lower for word in ('quota','额度','billing','credit','rate limit','429')):kind,message='quota','服务额度不足或请求过于频繁。请检查账户额度，或稍后重试。'
    elif any(word in lower for word in ('没有找到','未安装')):kind,message='setup','未找到所选模型工具。请安装工具，或在设置中选择可用模型。'
    elif any(word in lower for word in ('登录','unauthorized','authentication','oauth','token expired','log in','401','403','sign in','account is on hold')):kind,message='login','登录或访问权限未通过。请确认所选账户可用后重试。'
    elif any(word in lower for word in ('网络','代理','connection','proxy','tls','ssl','connect','econn','enotfound','dns','socket','端口')):kind,message='network','网络或代理连接未成功。可先在设置中检查代理端口和模型连接。'
    elif any(word in lower for word in ('json','格式','有效文本','invalid response')):kind,message='format','服务返回的内容无法用于整理。可重试或切换模型。'
    else:kind,message='other','任务未完成，已有资料已保留。查看详细原因后可重新尝试。'
    return {'kind':kind,'message':message,'detail':text[:1600]}
