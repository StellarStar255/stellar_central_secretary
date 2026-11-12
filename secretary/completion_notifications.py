"""Opt-in desktop completion events without source titles or contents."""
from collections import deque
import secrets
import threading

class CompletionEvents:
    def __init__(self):self.lock=threading.Lock();self.events=deque(maxlen=100)
    def add(self,item_id,stage):
        with self.lock:self.events.append({'id':secrets.token_hex(16),'item_id':item_id,'stage':stage})
    def snapshot(self):
        with self.lock:return list(self.events)

class CompletionConsumer:
    def __init__(self):self.seen=set()
    def consume(self,status):
        events=status.get('completion_events',[]);fresh=[e for e in events if e['id'] not in self.seen]
        self.seen.update(e['id'] for e in events)
        if len(self.seen)>300:self.seen={e['id'] for e in events}
        return fresh if status.get('settings',{}).get('completion_notifications') else []

def message(event,language='zh'):
    if language=='en':return ('Material organized','Open the library to view it.') if event['stage']=='done' else ('Organization failed','Open Tasks for the reason and retry.')
    return ('资料已整理','可在知识库中查看。') if event['stage']=='done' else ('资料整理失败','打开任务中心查看原因并重试。')
