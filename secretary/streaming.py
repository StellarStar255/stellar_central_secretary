"""Bounded Chat Completions SSE parsing and isolated-worker text progress."""
import json
import subprocess
import threading
import time

def chat_sse(response,callback,key=''):
    text='';total=0;finished=False;last=0
    while True:
        line=response.readline(1_000_001)
        if not line:break
        total+=len(line)
        if total>4_000_000:raise ValueError('模型 API 返回内容过大')
        if len(line)>1_000_000:raise ValueError('模型 API 返回内容过大')
        if not line.startswith(b'data:'):continue
        data=line[5:].strip()
        if data==b'[DONE]':finished=True;break
        if not data:continue
        event=json.loads(data)
        if event.get('error'):raise ValueError('模型 API 流式响应失败')
        for choice in event.get('choices',[])[:1]:
            delta=choice.get('delta',{}).get('content','')
            if isinstance(delta,str):text+=delta
            reason=choice.get('finish_reason')
            if reason=='length':raise ValueError('模型输出达到 token 上限，请提高最大输出 token 后重试')
            if reason in ('stop','end_turn'):finished=True
        if time.monotonic()-last>=.1:
            # Hold a possible partial key suffix until the next chunk is known.
            safe=text.replace(key,'[redacted]') if key else text
            if key:
                for length in range(len(key)-1,0,-1):
                    if safe.endswith(key[:length]):safe=safe[:-length];break
            callback(safe);last=time.monotonic()
    if not finished:raise ValueError('模型流式响应中断，未保存不完整回答，请重试')
    if not text.strip():raise ValueError('模型 API 没有返回有效文本')
    return text.replace(key,'[redacted]') if key else text

def worker_result(proc,payload,callback,timeout,terminate):
    done=threading.Event();result={};errors=[]
    def read():
        try:
            proc.stdin.write(payload);proc.stdin.close()
            total=0
            while True:
                line=proc.stdout.readline(4_000_001)
                if not line:break
                if len(line)>4_000_000:raise ValueError('模型 API 返回内容过大')
                total+=len(line)
                if total>32_000_000:raise ValueError('模型 API 返回内容过大')
                event=json.loads(line)
                if isinstance(event.get('partial'),str):callback(event['partial'][:16000])
                else:result.update(event)
        except Exception as error:errors.append(error)
        finally:done.set()
    thread=threading.Thread(target=read,daemon=True);thread.start()
    if not done.wait(timeout):
        terminate(proc);thread.join(2);raise subprocess.TimeoutExpired(proc.args,timeout)
    if errors:raise errors[0]
    if not result:raise ValueError('模型 API 没有返回完整结果')
    return result
