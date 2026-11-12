"""Short-lived, content-free progress for concurrent library requests."""
import re
import threading
import time


class QuestionProgress:
    def __init__(self):
        self.lock=threading.Lock();self.records={}

    @staticmethod
    def validate(key):
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('问答进度标识无效')

    def begin(self,key):
        self.validate(key)
        with self.lock:
            now=time.monotonic()
            self.records={k:v for k,v in self.records.items() if now-v.get('ended',now)<120}
            if key in self.records and self.records[key]['stage']!='error':raise ValueError('问答请求已存在，请重试')
            if len(self.records)>=128:raise ValueError('问答请求过多，请稍后重试')
            self.records[key]={'stage':'preparing','started':now,'stage_at':now}

    def update(self,key,stage,count=None):
        with self.lock:
            value=self.records[key];value.update(stage=stage,stage_at=time.monotonic())
            value.pop('count',None)
            if count is not None:value['count']=count
            if stage in ('done','error'):value['ended']=time.monotonic()
            if stage in ('done','error'):value.pop('partial',None)

    def partial(self,key,text):
        with self.lock:self.records[key]['partial']=str(text)[:16000]

    def snapshot(self,key):
        self.validate(key)
        with self.lock:
            value=self.records.get(key)
            if not value:return {'stage':'connecting','elapsed_seconds':0,'stage_seconds':0}
            now=value.get('ended',time.monotonic())
            return {'stage':value['stage'],'elapsed_seconds':round(now-value['started'],1),'stage_seconds':round(now-value['stage_at'],1),
                    **({'count':value['count']} if 'count' in value else {}),**({'partial':value['partial']} if 'partial' in value else {})}
